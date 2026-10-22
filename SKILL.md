---
name: nxopen-journal
description: 生成、检查并批处理回放 Siemens NX 12 的 NXOpen Python journal 脚本（NX 安装根用环境变量 NX_HOME 指定），覆盖三维建模、装配、Drafting 工程图、Advanced Simulation 有限元与 NX Motion 运动仿真自动化。用于“用 UG 建模/出三视图/做有限元分析/做运动仿真”或“写 NXOpen 脚本”类请求；触发词包括 NXOpen、journal、UG 脚本、NX 二次开发、自动建模、Drafting、NX Nastran、运动仿真、NX Motion、run_journal；英文触发词（English triggers）：Siemens NX automation, NXOpen Python journal, NX journal scripting, NX 12 automation, UG NX API, NX modeling, NX drafting, NX Nastran FEA, NX Motion simulation, run_journal.exe.
---

# NXOpen Journal 生成（NX 12）

NX 自动化唯一入口是 NXOpen API。本技能生成可在 NX 12 回放的 Python journal，覆盖建模/装配/工程图/有限元/运动仿真。
分层：本文件 = 会话与部件层（必读）；八个域文件按任务选读其一（§5 路由表）。

⚠ **journal 解释器 = NX 12 内嵌 Python 3.6.1**：无 `math.dist`、`math.prod`、`math.isqrt`、f-string `=`、dict 合并运算符、`functools.cache`。`subprocess.run` 可用。宿主 3.12 预演通过不等于 NX 可跑，写完先过 `check_journal.py`。

## 1. 铁律

本节是技能内唯一保留的跨域高发陷阱清单（通用 + 静默失败/崩溃）；单域负面事实写在对应路线里，不新开坑位清单。

1. **API 零幻觉**：写任何 NXOpen 类/成员前，先用 `nxopen` MCP 核实（`search_api` / `get_class` / `get_member`）。
2. **MCP 核实“存在” ≠ Python 封装“可调用”**：新 API 必须先最小批处理验证，通过后才写入本技能。
3. **MCP 查不到 ≠ 不存在，MCP 查得到也 ≠ 运行期存在**：按 `dir()` 运行期对象 → `%NX_HOME%\UGOPEN\*.h` 与同目录 `*.c` 样例的顺序核实。反例：MCP 有 `NXOpen.UF.UFDrf.CreateIdSymbol`，运行期没有 `UFDrf`，真实入口是 `NXOpen.UF.Drf`/`ufs.Drf`。
4. **属性只读 ≠ 设不进去**：先看属性返回的是不是 `SelectObject`/`ScCollector` 等容器，容器自身的 `.Value` 往往可写；穷尽 builder 容器通道后再退回 UF。
5. **批处理 stdout 全缓冲，崩溃即丢光**：每行必须同时落盘并 flush：

```python
def say(msg):
    line = str(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
```

6. **传错参数类型会损坏原生堆，进程直接死且无 traceback**：禁止“猜签名、逐个候选调用”的自适应循环；签名来自 MCP 或 `dir()`，只调一次正确的那次。
7. 未知 API/参数 → 标注“未验证”，交付时提醒用户回放确认。
8. 不修改 NX 安装目录（默认 `D:\UG-NX12`，可用 `NX_HOME` 覆盖）；脚本与模型保存到用户工作区。
9. 回放前要求用户备份当前 Part；先用最小用例（新建 Part + 方块 + 保存）验证环境，再跑正式脚本。

## 2. 本机环境事实

- **NX 安装根 = 环境变量 `NX_HOME`，默认 `D:\UG-NX12`**；换位置只设该变量。`run_journal_batch.bat` 解析不到 `run_journal.exe` 时打印 `ERROR: run_journal.exe not found under NX_HOME=...` 并以 2 退出。
- NX 12.0.0.27；NXOpen .NET 程序集与 XML 文档在 `%NX_HOME%\NXBIN\managed\`。
- 批处理：`scripts\run_journal_batch.bat <journal.py> [workdir]`，自动加载 `ugiicmd.bat` 后调 `run_journal.exe`；每次启动新进程，不能注入已打开的 UG 会话。workdir 不存在会自动创建，并打印 `=== RUN_JOURNAL workdir=<绝对路径> ===`。
- 批处理无已打开部件：`Parts.Work` 为 `None`；`UI.GetUI()` 与 `Parts.Display` 仅交互回放有意义。
- mm 模板：`%NX_HOME%\UGII\templates\model-plain-1-mm-template.prt`。
- nxopen MCP 嵌入端点 = `http://127.0.0.1:11436`（bge-m3）。服务未起时 `search_api`/`find_builder` 直接报错，改用 `get_class`/`get_member`。
- 交互回放：中文 工具→操作记录→运行；英文 Tools→Journal→Run。
- 批处理 `.bat` 必须纯 ASCII（cmd 按 GBK 解析）。

## 3. Journal 骨架与通用部件操作

```python
import NXOpen
import NXOpen.UF

def main():
    theSession = NXOpen.Session.GetSession()
    workPart = theSession.Parts.Work          # 批处理中为 None，须先新建/打开
    # 功能代码：类/方法名先经 nxopen MCP 核实
    # 每个功能段 try/except 打印 NXException.Message
    # 结束必须显式保存

if __name__ == '__main__':
    main()
```

⚠ 子模块不会随 `import NXOpen` 自动加载：用 Motion 必须 `import NXOpen.Motion as M`，否则 `AttributeError: module 'NXOpen' has no attribute 'Motion'`。`NXOpen.Features`、`NXOpen.Positioning` 等同理。

### 新建部件

```python
fileNew = theSession.Parts.FileNew()
fileNew.Units = NXOpen.Part.Units.Millimeters      # 必设
fileNew.TemplateFileName = "model-plain-1-mm-template.prt"
fileNew.NewFileName = "part_name.prt"              # 必带 .prt
fileNew.UseBlankTemplate = False
part = fileNew.Commit(); fileNew.Destroy()
```

新建回退链：FileNew → NewDisplay → 当前工作部件（判空）→ 显式报错。

### 打开 / 保存 / 修改已有部件

```python
part, loadStatus = theSession.Parts.Open(r"C:\path\part.prt")   # 1 个参数，返回元组
NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(part.Tag)  # 修改前必须设显示部件
NXOpen.UF.UFSession.GetUFSession().Part.Save()                    # 无参 UF 保存
```

带阶段校验的保存：

```python
import os
wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue)
assert os.path.exists(path) and os.path.getsize(path) > 0   # 落盘才算数
```

成员名是 `TrueValue` / `FalseValue`（`True`/`False` 是 Python 关键字）。

### 通用 API 路线约束

1. **builder 创建不能传 `None`**：传 `NXOpen.Features.Feature.Null`（Block/Cylinder/Chamfer/Hole/EdgeBlend/Extrude/Revolve/Mirror/Pattern 等）、`NXOpen.Features.BooleanFeature.Null`（Boolean）。`.Null` 只存在于 Python 封装层。
2. **FileNew 不覆盖**：重复运行报 `File already exists`；生成类 journal 启动时清理本工程旧 `.prt`（含 `_i.prt`），多部件各用独立路径。同一进程内不要对同一路径 FileNew 两次。阶段件用 `SaveAs(新路径)`，`SaveAs` 到已存在路径同样报 `File already exists`，先删目标或换路径。
3. **`Part.FullPath` 批处理中可能只显示文件名**；以磁盘落盘位置为准。
4. **集合无 `ToArray()`**：`part.Bodies`、`DrawingSheets`、`DraftingViews` 直接 `for x in ...`。
5. **`ScCollector.ReplaceRules(rules, False)` 第二参必须 `False`**（立即求值）；`True` 会选中 0 条边。
6. **STL 可导，位图不可导**：STL 用 `SetArray`，不要用 `SelectionComp`：

```python
sc = s.DexManager.CreateStlCreator()
sc.OutputFile = stl_path
sc.ExportSelectionBlock.SetArray(bodies)
sc.ChordalTol = 0.05
sc.Commit(); sc.Destroy()
```

   容差成员只有 `ChordalTol`/`AngularTol`/`AdjacencyTol`，无 `TriangleTolerance`；输出类型是 `OutputType` + `OutputTypeEnum`。装配件按组件逐个导出：`Component.GetPosition()` + `Component.DisplayName`。`Body` 无 `GetVolume()`，体积走 `ufs.Modl` 或 STL 复算。
   位图无批处理入口：`ImageCaptureBuilder` 不落文件，`ufs.Disp.CreateImage` 抛内存访问违例。要位图走 Drafting PDF 或 STL 外部渲染。

7. **`Point3d`/`Vector3d` 必须传 float**：`NXOpen.Point3d(0.0, 0.0, 0.0)`；传 int 报 `Expecting double type, found int`。
8. **尺寸字符串不接受 float**：`SetOriginAndLengths(origin, "100", "60", "20")`、`AddChainset(col, "2.0")`、`FirstOffset = "1.0"` 都必须是 str；字符串可写表达式名。
9. **UF struct 类型名按所属组查**：多数挂在 UF 组容器下（`NXOpen.UF.Drf.Object`、`NXOpen.UF.Curve.SectionGeneralData`），运动模块的部分是顶层 `NXOpen.UF.<名>_Struct`（`MotionInterference_Struct`、`MotionTrace_Struct`）；先用 `dir(NXOpen.UF.<组>)` 核实。UF 参数表中的 `Xxx@`（out 参数）在 Python 里是返回值，不要当实参传（`st = ufs.Motion.InitInterferenceStruct()`）。
10. **builder 的 `Name` 有的是通道、有的是普通 str**：`SpringBuilder.Name` 直接赋值；`BushingDefine.Name` 要写 `b.BushingDefine.Name`。报 `A name has not been specified` 就是名字没落到承载对象上。

### 日志与阶段保存

1. 日志逐行写文件并 flush，不要只 `print()`。
2. 每步 try/except 记完整 traceback 后继续；只有致命错误才退出。
3. 阶段边界保存并 `assert os.path.exists(path) and os.path.getsize(path) > 0`；Commit 成功 ≠ 落盘。
4. 昂贵/易崩步骤前存 checkpoint 副本；每次布尔后断言体数（NX 布尔会静默不生效）。

### Undo mark 与失败回滚

```python
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "stage-1")
try:
    ...  # 本段作业
    session.DeleteUndoMark(mark, "stage-1")
except Exception:
    session.UndoToMark(mark, "stage-1")
    session.DeleteUndoMark(mark, "stage-1")
    raise
```

- `UndoToMark` 是批处理下唯一的事务边界；只用于“已确认失败、需要保持部件干净”的分支，不吞报错。
- 小段用 `Invisible`，整体可回滚段用 `Visible`；`DeleteUndoMark` 必须与 `SetUndoMark` 配对。

### 外部格式导入

先枚举能力，不要猜：

```python
s = NXOpen.Session.GetSession()
for n in dir(s.DexManager):
    if n.startswith('Create'): print(n)
```

- NX12 全集：Acis/Catiav4/Catiav5/Proe/Step(203/214/242)/Iges/Dxfdwg/Asc/Virtuallab/Stl/Nxto2d；3dxml/cgr 不在支持列表，先转 STEP/Parasolid 再导入。
- **假成功**：不支持几何复制成 `.CATPart` 再 Commit 不报错但 `part.Bodies` 为 0；导入后必须开文件读体数。
- CATProduct 导入是扁平化的，只解析当前文件直接层级；组件本体坐标通常已是整车坐标。

### 导出 STEP

```python
sc = session.DexManager.CreateStepCreator()
sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214      # Ap203 / Ap214 / Ap242
sc.ObjectTypes.Solids = True
sc.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
sc.ExportSelectionBlock.SelectionComp.Add(body)
sc.InputFile  = wp.FullPath
sc.OutputFile = r"C:\path\out.stp"
sc.ProcessHoldFlag = True                                  # 必设，否则 Commit 返回时文件未落盘
sc.Commit(); sc.Destroy()
```

`DexManager` 在 NX12 没有 Parasolid 导出方法。

⚠ **批处理下 STEP 可能写出 0 个实体**：Commit 成功、文件 2–3 KB、零 `ADVANCED_FACE`。落盘后必须开文件数实体；不可用时改用 Parasolid：

```python
ufs = NXOpen.UF.UFSession.GetUFSession()
ufs.Ps.ExportData([body.Tag], r"C:\path\out.x_t")   # 首 24 字节含 **PARASOLID
```

IGES 同坑。`.x_t` 可直接回读，作为交换格式交付并注明“Parasolid，等价于 STEP 的实体边界表示”。

## 4. 工作流

1. 明确任务：零件/装配/图纸/仿真 + 关键尺寸 + 单位（默认 mm）。
2. 按 §5 路由读域文件；建模先过 `modeling.md` §1 方法论。
3. 用 nxopen MCP 核实将用到的类/方法/枚举；新 API 先写最小探针（`scripts/tests/11_api_probe.py`、`12_api_probe2.py`、`13_api_probe3.py` 可抄）。
4. 按域文件配方生成 journal（`main()`、Session、部件新建/打开、保存、日志与阶段断言）。
5. `python scripts/check_journal.py <journal.py>` 静态检查。豁免标记：整文件探针写 `# check_journal: allow-probes`，单行负向对照写 `# check_journal: expected-raise`。
6. `scripts\run_journal_batch.bat <绝对路径\journal.py> <workdir>` 试跑 → 成功后交付交互回放；报错则 MCP 核实修正。

## 5. 模块路由

| 任务 | 必读 |
|---|---|
| 零件建模（草图/特征/孔/阵列/镜像/旋转/表达式/可编辑性） | `references/modeling.md` |
| 图层与图层类别、独立基准平面 | `references/modeling.md` §1.7-§1.9 |
| 阵列（线性/圆周/沿路径/螺旋/正多边形/目标点/引用已有阵列）与特征镜像 | `references/modeling.md` §3.1-§3.1f + §3.2 |
| 抽壳/拔模/质量属性校验/去参/渐开线齿轮/导出 | `references/modeling.md` §3.4-§3.7 + 本文件 §3 导出 |
| 装配（加组件/配对约束/组件阵列/引用集/装配质量属性/运动连接） | `references/assembly.md` |
| 工程图（图纸/三视图/投影视图/局部放大/剖视图/PDF 导出/装配图路线） | `references/drafting.md` |
| 工程图标注（尺寸道位布局/字高箭头风格/注释文字/表格/中心线/球标） | `references/drafting-annotation.md` |
| **逆向重建**（原件+一句重建要求→测量链→截面/放样→孔系/凹槽切除→验收项与双向偏差） | `references/reverse-engineering.md` |
| **国标成套出图**（GB 图框/标题栏/技术要求/尺寸道位一张图到位） | `scripts/gb_drawing.py` + `references/gb-drawing.md`（验收=33 号用例） |
| 有限元（CAD→FEM→SIM→求解→后处理；实体 CTETRA 与 2D 壳/PSHELL、模态 SOL103） | `references/fea.md` |
| 运动仿真（Link/转动副/滑动副/驱动/齿轮连接件/求解/结果提取/静不定反力陷阱） | `references/motion.md` |
| 可编辑性验证 | `references/modeling.md` §6 + `scripts/tests/08_editability_probe.py` |

- 纯修改已有部件通常只读本文件。
- 跨域复合任务按依赖顺序读多个域文件；域文件之间不互相依赖，少量通用事实允许域内重复。
- 载荷/边界数据可来自上游校核技能或手算结果；模型落在项目工作区固定目录。

## 6. 脚本与回归

宿主 Python 使用 3.11+（仓库检查、PDF 复核与 nxopen MCP 共用）；NX journal 仍由 NX 内嵌 Python 3.6.1 执行，两者无关。

```bash
# 静态检查（无需 NX）
python scripts/check_journal.py path/to/journal.py

# 批处理试跑（journal 用绝对路径；workdir 可选）
scripts\run_journal_batch.bat C:\abs\path\journal.py [workdir]

# 全量回归（36 例 = 33 个批处理令牌校验 + 11-13 三个一次性探针）
# 逐例覆盖内容与令牌名只维护在 tests/README.md
# 09 含 Nastran 求解较慢；跑完默认清理 parts\，KEEP_PARTS=1 保留
# 末尾先跑 check_journal 规则自检（宿主 python），再用 pymupdf 复核 19 号 PDF 文本层
scripts\tests\RUN_TESTS.bat
# 环境变量：NX_HOME（默认 D:\UG-NX12）、PYTHON（带 pymupdf）、KEEP_PARTS=1
```

改动 references、`check_journal.py`、`run_journal_batch.bat` 后，先跑 `RUN_TESTS.bat` 全绿再交付。

**写新用例先 `import nxlib`，不复制配方**：`scripts/nxlib/` 是五域标准层（`testing`/`session`/`modeling`/`assembly`/`drafting`）；探针/死路用例保持自包含，名单在 `check_repo.py` 的 `SELF_CONTAINED`，新增必须登记；用例顶层函数与 nxlib 公开 API 同名会被拦截。

⚠ **检查看输出 token，不看退出码**：未捕获异常返回非零，但脚本吞掉失败时退出码仍为 0。33 个 gate 必须出现期望 token 且不得出现 `_FAIL`。成功 token：`TESTxx_DONE`（09/16/18/36 为 `BENCH_PASS`、10 为 `CONSTRAINT_PASS`）；失败必须打 `_FAIL`。逐项 `check()` 型用例单条失败打 `REG_xxx=FAIL`（不含 `_FAIL`），末尾打 `TESTxx_FAIL failed=[...]`。
⚠ 已知崩溃探针（26 的 `ThreadedHole`、28 末条）在各自用例内运行，退出码非零不传给后续 gate；崩后用 Undo mark 撤掉残废特征。gate 顺序由 `RUN_TESTS.bat` 固定（09 含 Nastran 求解，放最后）。

⚠ **检查要有判别力**：期望值必须来自独立信息源（解析解、指令参数），不能取自被测数据本身；且要反向验证——故意改坏一处，确认对应检查 FAIL。

## 7. 维护约定

**入库模板**（所有新知识按此写；`check_repo.py` 的 CONCISE/ROUTE 组会拦截违规）：
1. 第一句写正确做法（祈使句），不写发现经过、验证过程或历史沿革。
2. 失败观察只留一行判据：症状 → 怎么做。
3. 数值只保留能当验收判据的（容差、阈值、比例），不写实验读数与日志。
4. 禁止日期与过程叙述；完整词表见 `check_repo.py` 的 `CONCISE_PATTERNS`。只删叙述，不删 API/判据；拿不准就保留事实、改写表述。改完文档先跑 `python scripts/check_repo.py`，CONCISE/ROUTE 失败按提示改写，不要加白名单。
5. 新条目先查重：已有条目能覆盖就改那一句，不追加新段；结论变更时直接改掉旧句，不保留新旧并存。
6. 落位：跨域会话/部件层 → 本文件 §3；单域完整成功路径 → 域文件正文。负面事实只作为路线里的一句约束（“用 X；Y 会…”），不新开坑位清单；只有跨域通用且高发（静默失败/进程崩溃）的才进本文件 §1 铁律。
7. 入库门槛 = 铁律 2：MCP 核实 + 批处理验证双通过。
8. 新增/重排小节后核对交叉引用：`grep -rn "§[0-9]" SKILL.md references/` 与 `grep -rn "铁律 [0-9]\|路线约束 [0-9]"`。
9. 吸收外部技能/项目时先在本机 NX12 验证；与本机冲突处以本机结果为准并注明。

**增长纪律**：不设体积硬上限。新增条目先查重并合并，同一主题不新开小节；每次版本发布前跑 `check_repo.py`。文件明显膨胀时，优先把坑位并回路线、删旧条目、压重复；只有两个独立任务域被迫共读一个文件时才按域拆分（装配/工程图即此例），不要靠拆文件掩盖重复。域文件不设坑位表；负面事实写进对应路线的约束句。

## 8. 文件清单

```
nxopen-journal/
├── SKILL.md                        ← 本文件（入口层：铁律/环境/骨架/通用部件操作/日志导出/工作流/路由）
├── LICENSE                         ← MIT 许可证
├── README.md                       ← 对外说明（中文，主文档）：定位 / 前置条件 / 安装与使用 / 实跑产物 / 覆盖范围 / 回归用例 / 已知限制 / 目录结构
├── README.en.md                    ← 同一份说明的英文落地页，与 README.md 顶部互链
├── CHANGELOG.md                    ← 版本变更记录（Keep a Changelog，当前 1.2.0）
├── images/                         ← README 的实跑产物图（三维与装配由 STL 离线渲染，其余来自回放产物）
├── references/*.md                 ← 八个域文件；各自的域与覆盖范围见 §5 路由表
├── scripts/gb_drawing.py           ← 国标出图标准件（图框/三视图钉位/标题栏/技术要求/尺寸道位/PDF；验收=33 号用例，用法=references/gb-drawing.md）
├── scripts/nxlib/                  ← 用例标准层（testing/session/modeling/assembly/drafting 五模块；新用例 import 它、不复制配方）
├── scripts/render/                 ← 离线出图链（STL→着色渲染、PDF→PNG；用法=scripts/render/README.md）
├── scripts/check_journal.py        ← 静态检查（语法/占位符/已固化约束，含 NX12 专属名与 Py3.6 API）
├── scripts/check_repo.py           ← 仓库自检（Py3.6 语法 / 用例清单一致 / 文档结构 / 文件清单 / 标准层独占 / 文档精简 / 路线优先）
├── scripts/run_journal_batch.bat   ← 批处理试跑（ugiicmd + run_journal.exe；NX 安装根走 NX_HOME）
├── scripts/tests/                  ← 回归套件；README.md 有运行方式、用例与判决 token 表、配方归属
│   ├── 01…36_*.py                  ← 33 个并入令牌校验的用例（RUN_TESTS.bat 全量跑）
│   ├── 11…13_api_probe*.py         ← 一次性 API 探针，不纳入检查
│   ├── verify_check_rules.py       ← check_journal 规则自检（宿主解释器，反例必须命中）
│   ├── verify_anno_pdf.py          ← 19 号用例的 PDF 文本层数值复核（宿主解释器 + pymupdf）
│   └── RUN_TESTS.bat               ← 全量回归 + 规则自检 + 19 号用例的 PDF 值级复核
└── agents/openai.yaml              ← Codex/OpenAI 端界面配置（跨端迁移用）
```
