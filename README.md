# nxopen-journal

[English](README.en.md) | 中文

让 agent 用自然语言写 NX 12 journal，批处理生成模型与图纸。

`NX 12 (12.0.0.27)` · `NX Python 3.6.1` · `Host Python 3.11+` · `v1.7.0` · `MIT`

## 目录

- [背景](#背景)
- [特性](#特性)
- [目录结构](#目录结构)
- [安装](#安装)
- [行为说明与已知限制](#行为说明与已知限制)
- [测试](#测试)
- [许可证](#许可证)

## 背景

NXOpen journal 的难点不在语法，而在某个调用能否在 NX 12 批处理中存活。本技能把验证过的判断整理成配方：每条结论先在 nxopen MCP 核实 API 存在，再在 NX 12 批处理中跑通；能固化的结论都配回归用例。agent 读 `SKILL.md` 选域，按域读参考文件，写 journal，过静态检查，再批处理回放。

覆盖三维建模、装配、Drafting 工程图、Nastran 有限元、Motion 运动仿真与逆向重建，并带一套交付件验证门。六个域的实跑图件在 [nxopen-journal-toolkit](https://github.com/EVOL233awa/nxopen-journal-toolkit) 的 README；本仓库只保留技能源文件、参考文档与回归套件。

## 特性

| 域 | 覆盖内容 |
| --- | --- |
| 三维建模 | 草图、拉伸与旋转、布尔、抽壳与拔模、九种阵列、孔包三种非螺纹孔型、图层与类别、STL 导出 |
| 装配 | 装配结构、配对约束、可拖动机构、转动副两条路线、干涉检查两条几何路线；球铰、圆柱铰、铰链、滑块到 Motion 域建 |
| Drafting 与国标出图 | 三视图、投影、局部放大、剖视、装配图序号/剖视/标题栏、尺寸与中心线；国标图框、线宽、字体与第一角摆位由 `gb_drawing.py` 处理 |
| 有限元 | Nastran SOL101 静力、2D 壳网格、求解级标定、边界条件描述符；需要 NX Nastran 解算授权 |
| 运动仿真 | 连杆、转动副、滑动副、齿轮连接件、驱动、求解与结果提取；帧 0 为 t=0 |
| 逆向重建 | 从无特征实体提取结构清单与截面，按结构特征重建为可编辑模型；独立复算截面、孔系、体积、包围盒、四视图与双向偏差 |
| 交付件验证 | STEP/STL/DXF/占用/PDF 门，判决三态 `PASS`/`FAIL`/`NO_SIGNAL`；宿主侧入口 `check_deliverables.py`、`run_journal_checked.py`、`api_index.py` |

配套脚本：`check_journal.py` 静态检查、`run_journal_batch.bat` 批处理、`nxlib/` 用例标准层、`render/` 离线出图链、`tests/` 回归套件。

## 目录结构

```text
nxopen-journal/
├── SKILL.md                  入口层：铁律 / 环境 / 骨架 / 日志 / 工作流 / 域路由
├── README.md / README.en.md  中英文说明
├── CHANGELOG.md              版本变更
├── references/               九个域文件
├── scripts/
│   ├── check_journal.py      静态检查
│   ├── check_repo.py         仓库自检
│   ├── run_journal_batch.bat 批处理回放
│   ├── gb_drawing.py         国标出图
│   ├── nxlib/                用例标准层
│   ├── render/               离线出图链
│   └── tests/                54 个用例文件 + RUN_TESTS.bat
├── docs/wiki/                维护者导览
├── .github/workflows/ci.yml  云端 CI
└── agents/openai.yaml        Codex/OpenAI 配置
```

## 安装

快速开始：把下面整段复制给任意宿主的 agent；它克隆本仓库、确认 NX 环境并跑静态检查与回归。变更见 [CHANGELOG.md](CHANGELOG.md)。

```text
任务：安装并验证 nxopen-journal。
1. 克隆到 agent 技能目录，目录名保持 nxopen-journal。
2. 确认 NX_HOME 与 %NX_HOME%\NXBIN\run_journal.exe，NX 内嵌 Python 为 3.6.1。
3. 运行 python scripts\check_repo.py，确认输出 CHECK_REPO_OK。
4. 运行 scripts\tests\RUN_TESTS.bat，确认最后一行 === ALL TESTS PASSED ===，日志中无 _FAIL、FATAL、SKIP。
5. 报告安装路径、NX 版本、NX_HOME、Python 版本与两项检查结果；失败时报告用例号、失败项与日志末尾 50 行。
```

也可以按下面的步骤手动安装。

### 前置条件

| 条件 | 要求 | 缺了会怎样 |
| --- | --- | --- |
| 操作系统 | Windows 11 | 批处理与回归无法运行 |
| NX | Siemens NX 12（验证版本 12.0.0.27）与 NXOpen 自动化接口 | 只剩静态检查 |
| `NX_HOME` | 指向 NX 安装根，默认 `D:\UG-NX12` | 批处理报错并以退出码 2 结束 |
| agent | 能加载技能目录的 agent | 技能不会触发 |
| Python | 宿主 3.11+ | journal 不受影响；检查与 MCP 不可用 |
| NX Nastran 授权 | 求解日志打印 `NASTRAN LICENSE:` | 09 与 25 号用例不能跑，其余照常 |
| nxopen MCP（可选） | 见下节 | 写 API 时退回 `dir()` 与 UGOPEN 头文件核实 |

NX journal 由 NX 12 内嵌 Python 3.6.1 执行，与宿主 Python 无关；两者不可互换。

### 配置

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `NX_HOME` | NX 安装根 | `D:\UG-NX12` |
| `KEEP_PARTS` | `RUN_TESTS.bat` 是否保留 `scripts/tests/parts/` | 未设置（清理） |

### 手动安装

1. 把仓库放进 agent 的技能目录，目录名保持 `nxopen-journal`：

   ```bash
   git clone https://github.com/EVOL233awa/nxopen-journal
   ```

   Codex CLI 用 `~/.codex/skills/`，Claude Code 用 `~/.claude/skills/`；其他 agent 按自己的技能目录约定放置。

2. 确认 `NX_HOME` 与 `%NX_HOME%\NXBIN\run_journal.exe`。NX 装在别处时先设置 `NX_HOME`。

3. 静态检查：

   ```bash
   python scripts/check_repo.py
   ```

   输出 `CHECK_REPO_OK` 即通过。

4. 全量回归：

   ```bat
   scripts\tests\RUN_TESTS.bat
   ```

   最后一行是 `=== ALL TESTS PASSED ===`，且日志中没有 `_FAIL`、`FATAL`、`SKIP`。

5. 安装完成后，直接用自然语言描述任务：

   > 用 nxopen-journal 建一个 120×80×12 的支座，四角 M8 沉头孔，并导出三视图。

### nxopen MCP（可选）

写 journal 最容易错的是 API 名与签名。nxopen MCP 用本机 NX 文档建索引，让 agent 查真实存在的类、成员与签名。

- 整套安装：用 `nxopen-journal-toolkit`；`nxjt install` 注册 MCP，`nxjt index` 建索引。
- 只装 MCP：本 fork [`nxopen-mcp-enhanced`](https://github.com/EVOL233awa/nxopen-mcp-enhanced) 1.0.0，或上游 [`nxopen-mcp`](https://github.com/mingfeng6684/nxopen-mcp) v0.2.0。
- 建索引：`nxopen-mcp-enhanced index --nx-path <NX 安装根>` 或 `nxopen-mcp index --nx-path <NX 安装根>`。

不装也能用；查询中文夹英文术语（如 `创建拉伸特征 extrusion`）命中更好，纯中文短词不可靠。

## 行为说明与已知限制

- 当 `NX_HOME` 未设置时：批处理按默认 `D:\UG-NX12` 查找 NX；找不到时以退出码 2 结束。
- 当 journal 进入 NX 时：解释器固定为 3.6.1，不能使用 `math.dist`、`math.prod`、`math.isqrt`、f-string `=`、dict 合并运算符或 `functools.cache`；写完先过 `check_journal.py`。
- 当 `RUN_TESTS.bat` 运行时：默认清空 `scripts/tests/parts/`，设置 `KEEP_PARTS=1` 保留产物；判定看日志 token，不看退出码。
- 当交付件门看不到对应仪器时：返回 `NO_SIGNAL`，不返回 `FAIL`。ASCII DXF 无 `ezdxf` 也能验，二进制 DXF 缺库只能给 `NO_SIGNAL`。
- 只验证 Windows 11 + NX 12.0.0.27；其他平台与版本未测试。
- 批处理不能截图；图走 Drafting PDF 或 STL 外部渲染。
- 26 号用例保留一次原生崩溃记录 `ThreadedHole` 边界；判定看日志 token。
- 图纸 PDF 门只证明文本层存在，不证明内容画全；标题栏与中文技术要求由 NX 模型侧回读。
- 九种阵列中 `Mirror` 在提交阶段被拒；特征镜像走 `Features.MirrorFeatureBuilder`。
- 逆向重建不保证复杂件一次通过；本版提供结构清单、可编辑特征树与独立复算验收链。
- 技能只生成脚本与产物，不修改 NX 安装目录。

## 测试

套件 54 个用例文件 = 51 个带判定的 gate + 3 个一次性 API 探针。每个用例覆盖什么、反向验证怎么做，见 `scripts/tests/README.md`。

| 域 | 用例 |
| --- | --- |
| 三维建模 | 01 02 03 05 08 14 15 22 26 28 32 34 37 |
| 参数化与审计 | 41–48 |
| 装配 | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 54 |
| 有限元 | 09 24 25 30 |
| 运动仿真 | 18 23 36（16/17 覆盖装配层运动副） |
| 测量与逆向 | 38 39 40 49 |
| 交付件验证 | 50 51 52 53 |

```bash
python scripts/check_repo.py
scripts\tests\RUN_TESTS.bat
```

## 许可证

MIT。见 [LICENSE](LICENSE)。
