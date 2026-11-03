# 边界与风险

按"破了会怎样"排序，前四条是环境硬边界，后三条是判据与流程风险。

## 1. journal 解释器固定是 Python 3.6.1

NX 12 内嵌解释器不可替换，3.7+ 的语法与标准库特性全部不可用：`math.dist`/`prod`/`isqrt`、`functools.cache`、`itertools.pairwise`、f-string `=`、dict 合并运算符（`SKILL.md` 抬头的解释器警告）。

两处机制保证这条边界不被破：

| 位置 | 机制 |
|---|---|
| 仓库层 | `check_repo.py` 的 PY36 组用 `ast.parse(feature_version=(3,6))` 扫全部用例 + nxlib + `gb_drawing.py`（`scripts/check_repo.py` 的 `check_py36()`） |
| 单文件层 | `check_journal.py` 同样按 3.6 解析（`scripts/check_journal.py` 的 `ast.parse(..., feature_version=(3, 6))`），规则 5.16 额外拦 3.7+ 专属 API（`scripts/check_journal.py` 规则 5.16） |

风险点：**宿主 3.12 预演通过不代表 NX 可跑**。这是最容易误判的地方——宿主机上 `python journal.py` 语法通过、函数存在，进了 NX 就在解析期失败。所以静态门一律按 3.6 判，不按宿主版本判。

## 2. 批处理能力上限

| 限制 | 后果 | 替代路线 |
|---|---|---|
| 无法截图 | `ImageCaptureBuilder` 不落文件、`ufs.Disp.CreateImage` 抛内存访问违例（`SKILL.md` 的「通用 API 路线约束」条目 6） | Drafting 导 PDF 后栅格化；实体导 STL 后离线渲染 |
| 无已打开部件 | `Parts.Work` 为 `None`，`UI.GetUI()`/`Parts.Display` 无意义（`SKILL.md` §2） | journal 自己新建或打开部件，保存用 UF 无参保存 |
| 每次起独立 NX 进程 | 不能注入已打开的 GUI 会话 | 交付时另附交互回放步骤 |
| stdout 全缓冲 | 崩溃时控制台输出全丢 | `say()` 逐行写文件 + `sys.stdout.flush()`（`SKILL.md` §1 第 5 条） |
| 参数类型不符 | 抛 Python 异常（`TypeError: No overload matches these arguments`、`AttributeError ... not writable`），进程存活、有 traceback（`SKILL.md` §1 第 6 条） | 签名来自 MCP 或 `dir()`，只调一次正确的那次；禁止"猜签名逐个试"（真崩溃只来自已知坑位的特定调用） |

## 3. 平台与版本绑定

- 验证环境只有 Windows 11 + NX 12.0.0.27（`README.md` 的已知限制）。其他 NX 版本未经测试，NX 版本分歧在别处有记录：NX 12 与 NX 2506 在螺纹 API、表达式 `.Value`、多体质量、Block 布尔上不一致。
- NX 安装根走 `NX_HOME`，默认 `D:\UG-NX12`（`scripts/run_journal_batch.bat` 的 `NX_HOME` 默认值）。这个默认值是开发机器的路径，**换机器必须设环境变量**，否则批处理打 `ERROR: run_journal.exe not found under NX_HOME=...` 并以 2 退出。
- `.bat` 必须纯 ASCII：cmd 按 GBK 解析（`SKILL.md` §2（`.bat` 必须纯 ASCII））。写中文注释会让脚本行为不可预测。
- Nastran 解算需要授权。用例 09 与 25 会实际调求解器，缺授权时这两个用例失败，其余照常（见 `README.md` 的前置条件表）。

## 4. NX 12 API 的已知硬边界

这些是"在别的版本/文档上能查到、在本机跑不通"的项，已固化成静态规则：

| 项 | 边界 | 替代 |
|---|---|---|
| 螺纹特征 | NX 12 无 `Features.Thread` / `CreateThreadBuilder` | HolePackage 螺纹选项或"底孔 + 标注" |
| 特征镜像 | `PatternFeatureBuilder` 的 `Mirror` 提交被拒（`README.md` 的已知限制（阵列）） | `Features.MirrorFeatureBuilder` |
| 位图导出 | 无批处理入口 | STL 离线渲染 |
| STEP 导出 | 可能写出 0 实体但 Commit 成功（`SKILL.md` 的「导出 STEP」小节） | 落盘后数实体；不可用改 Parasolid |
| 去参 | `RemoveParametersBuilder` 销毁特征树 | 不提供，违背历史模式铁律 |
| 剖切视图 | 必须先设父视图再 `AddCutSegment`（`references/drafting.md` §B.4） | 按 `drafting.md` §B.4 顺序 |

## 5. 判据判别力风险

套件的价值全在"判据能不能真的抓到错"。三条已固化的规则：

1. **期望值必须来自独立信息源**：解析解、指令参数，不能取自被测数据本身（`SKILL.md` §6（检查要有判别力））。用例 09 的悬臂梁与梁理论比、用例 25 的壳挠度与梁理论比，都是这个模式。
2. **反向验证**：故意改坏一处，确认对应检查 FAIL。`scripts/tests/README.md` §反向验证记录 的变异表逐条记录"改什么 → 应报哪个 FAIL"，包括"删父视图赋值""驱动 360→2π""期望体积改 120000−20³"。
3. **覆盖清单另钉项数**：只断言"全部项都在"时，删掉一项仍会通过。所以逐项用例末尾还要比项数（`scripts/tests/README.md` §反向验证记录（项数））。

已知的判别力弱点：阈值取成"默认值"会让断言空转——用例 19 的字高必须取非默认 5.0 才能证明 `SetLetteringPreferences` 生效（`scripts/tests/README.md` §反向验证记录（阈值））。

## 6. 流程风险

| 风险 | 触发条件 | 现状与对策 |
|---|---|---|
| 云端 CI 绿灯被当成可交付 | 改了 nxlib 或域文档后只跑 CI | CI 只跑静态侧（`.github/workflows/ci.yml` 文件头注释）；必须在有 NX 的机器上跑全量套件（`SKILL.md` §6） |
| 域文档退化成"故事集" | 把验证过程写回文档 | `check_repo.py` 的 CONCISE 组拦日期与过程词（`scripts/check_repo.py` 的 `check_concise()`） |
| 同一条结论在两处并存 | 结论变更时只新增不删旧 | ROUTE 组拦坑位标题与坑位表（`scripts/check_repo.py` 的 `check_routes()`）；维护约定要求直接改掉旧句（`SKILL.md` §7 第 5 条） |
| 配方被复制进用例 | 新用例不 import nxlib | NOLIB 组拦同名顶层函数（`scripts/check_repo.py` 的 `check_nolib()`），探针须显式登记 |
| 用例清单与批次脚本脱节 | 新增用例文件但没加 `call :gate` | COVERAGE 组双向校验 + 期望计数常量（`scripts/check_repo.py` 的 `EXPECTED_CASES`） |

## 7. 逆向重建的能力边界

这是本仓库唯一一条"不保证结果"的功能（`README.md` 的已知限制（逆向））：逆向路线提供结构清单、可编辑特征树与独立复算的验收链，但复杂铸件仍可能不过全部门。

设计上已经承认这条边界：`BLOCKED` 是合法的门结果，只用于几何不可达且已给出上限与残差分解的项，`delivery_pass` 在任一 `BLOCKED` 时为 false（`references/reverse-engineering.md` §4.1（四态判定））。也就是说，**该路线允许"做到上限仍不达标"被诚实记录，不允许把它写成 PASS**。

对应的停止规则写在 `references/reverse-engineering.md` §11.7：同一结构 2 轮参数/拓扑调整仍不过功能门就停，归因为"模板拓扑不覆盖/参数不可测"，不贴补丁。
