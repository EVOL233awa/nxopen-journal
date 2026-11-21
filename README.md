# nxopen-journal

[English](README.en.md) | 中文

让 agent 用自然语言写 NXOpen Python journal，在 NX 12 批处理中生成三维模型、装配、Drafting 工程图、Nastran 有限元和 Motion 运动仿真结果。

`NX 12 (12.0.0.27)` · `NX Python 3.6.1` · `Host Python 3.11+` · `v1.7.0` · `MIT`

> 快速开始：克隆到 agent 技能目录 → 确认 `NX_HOME` → 跑 `check_repo.py` 与 `RUN_TESTS.bat`。

## 快速开始

1. 把仓库放到 agent 的技能目录，目录名保持 `nxopen-journal`：

   ```bash
   git clone https://github.com/EVOL233awa/nxopen-journal
   ```

   Codex CLI 用 `~/.codex/skills/`，Claude Code 用 `~/.claude/skills/`，其他 agent 按其文档放置。

2. 确认 NX 12 与 `NX_HOME`：

   ```text
   %NX_HOME%\NXBIN\run_journal.exe
   ```

   `NX_HOME` 默认 `D:\UG-NX12`，装在别处先设置。

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

5. 配置完成后，直接用自然语言描述任务：

   > 用 nxopen-journal 建一个 120×80×12 的支座，四角 M8 沉头孔，并导出三视图。

## 适用版本与环境

| 用途 | 解释器 | 版本 |
| --- | --- | --- |
| NX journal 执行 | NX 12 内嵌 Python | 3.6.1（固定，不能替换） |
| 仓库检查、PDF 复核、MCP | 宿主 Python | 3.11+ |

NX 12（当前 12.0.0.27），其他 NX 版本未测试。`check_repo.py` 最低 3.8，pymupdf 需要 3.10+；统一用 3.11+ 可与 nxopen MCP 共用环境。

## 功能范围

| 域 | 覆盖内容 |
| --- | --- |
| 三维建模 | 草图、拉伸/旋转、布尔、抽壳/拔模、九种阵列、孔包三种非螺纹孔型、图层与类别、STL 导出 |
| 装配 | 装配结构、配对约束、可拖动机构、转动副两条路线、干涉检查两条几何路线 |
| Drafting | 三视图/投影/局部放大/剖视、装配图序号/剖视/标题栏、尺寸与中心线 |
| 有限元 | Nastran SOL101 静力、2D 壳网格、求解级标定、边界条件描述符 |
| 运动仿真 | 连杆、转动副、滑动副、齿轮连接件、驱动、求解、结果提取 |
| 逆向重建 | 结构清单与截面、可编辑特征树、独立复算截面/孔/体积/包盒/四视图/双向偏差 |
| 交付件验证 | STEP/STL/DXF/占用/PDF 门；三态 `PASS`/`FAIL`/`NO_SIGNAL` |

配套工具：`check_journal.py`（静态检查）、`run_journal_batch.bat`（批处理）、`gb_drawing.py`（国标出图）、`nxlib/`（用例标准层）、`render/`（离线出图）、`deliverable.py`、`check_deliverables.py`、`occupancy.py`、`api_index.py`、`run_journal_checked.py`（宿主侧门与索引）。

## 示例产物

六个域的实跑图件、生成环境与版本标注在 **nxopen-journal-toolkit** 的 README：
<https://github.com/EVOL233awa/nxopen-journal-toolkit>

图件由安装后的 toolkit 在 NX 12 批处理中重新生成，不是示意图；本仓库只保留技能源文件、参考文档与回归套件。

## 前置条件

| # | 条件 | 怎么确认 | 缺了会怎样 |
| --- | --- | --- | --- |
| 1 | Windows 11 + NX 12（12.0.0.27）与 NXOpen 自动化接口 | `%NX_HOME%\NXBIN\run_journal.exe` 存在 | 批处理与回归无法运行，只剩静态检查 |
| 2 | `NX_HOME` 指向 NX 安装根 | 默认 `D:\UG-NX12`；装在别处先设置 | 批处理报错并以退出码 2 结束 |
| 3 | 能加载技能的 agent | 目录放进技能目录，让它读一次 `SKILL.md` | 技能不会触发 |
| 4 | 宿主 Python 3.11+ | `python -V` | journal 不受影响（NX 用 3.6.1）；检查与 MCP 不可用 |
| 5 | NX Nastran 解算授权 | 求解日志打印 `NASTRAN LICENSE:` | 09 与 25 号用例不能跑，其余照常 |
| 6 | nxopen MCP（可选） | 见下节 | 写 API 时退回 `dir()` 与 UGOPEN 头文件核实 |

### nxopen MCP（可选）

写 journal 最容易错的是 API 名与签名。nxopen MCP 用本机 NX 文档建索引，让 agent 查真实存在的类、成员与签名。

- 整套安装：用 `nxopen-journal-toolkit`，`nxjt install` 会注册 MCP 并接好索引。
- 只装 MCP：本 fork [`nxopen-mcp-enhanced`](https://github.com/EVOL233awa/nxopen-mcp-enhanced) 1.0.0，或上游 [`nxopen-mcp`](https://github.com/mingfeng6684/nxopen-mcp) v0.2.0。
- 建索引：`nxopen-mcp-enhanced index --nx-path <NX 安装根>` 或 `nxopen-mcp index --nx-path <NX 安装根>`。

不装也能用；查询中文夹英文术语（如 `创建拉伸特征 extrusion`）命中更好，纯中文短词不可靠。

## 安装细节

把下面这段发给 agent，让它完成安装并报告结果：

```text
任务：安装并验证 nxopen-journal。
1. 克隆到 agent 技能目录，目录名保持 nxopen-journal。
2. 确认 NX_HOME 与 %NX_HOME%\NXBIN\run_journal.exe，NX 内嵌 Python 为 3.6.1。
3. 运行 python scripts\check_repo.py，确认输出 CHECK_REPO_OK。
4. 运行 scripts\tests\RUN_TESTS.bat，确认最后一行 === ALL TESTS PASSED ===，日志中无 _FAIL、FATAL、SKIP。
5. 报告安装路径、NX 版本、NX_HOME、Python 版本与两项检查结果；失败时报告用例号、失败项与日志末尾 50 行。
```

## 日常使用

配置完成后，直接用自然语言描述任务。agent 会读 `SKILL.md`，按域读参考文件，写 journal，过静态检查，批处理回放。产物是 `.prt` 文件与工程图。

## 回归用例

套件 54 个用例文件 = 51 个带判定的 gate + 3 个一次性 API 探针。每个用例覆盖什么、反向验证怎么做，见 `scripts/tests/README.md`。

| 域 | 用例 |
| --- | --- |
| 三维建模 | 01 02 03 05 08 14 15 22 26 28 32 34 37 |
| 参数化与审计 | 41–48 |
| 装配 | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 |
| 有限元 | 09 24 25 30 |
| 运动仿真 | 18 23 36（16/17 覆盖装配层运动副） |
| 测量与逆向 | 38 39 40 49 |
| 交付件验证 | 50 51 52 53 |

`RUN_TESTS.bat` 默认清理 `scripts/tests/parts/`；`KEEP_PARTS=1` 保留。判定看日志 token，不看退出码。

## 设计思路

NXOpen 的难点不在语法，而在某个调用能否在 NX 12 批处理中存活。技能把验证过的判断整理成配方：每条结论先在 nxopen MCP 核实 API 存在，再在 NX 12 批处理中跑通；能固化的结论都有回归用例。不可行的写法按域内联在对应路线的约束句里，跨域高发陷阱只放在 `SKILL.md` §1。

## 已知限制

- 验证环境 Windows 11 + NX 12.0.0.27；其他平台与版本未测试。
- 批处理不能截图；图走 Drafting PDF 或 STL 外部渲染。
- 26 号用例保留一次原生崩溃记录 `ThreadedHole` 边界；判定看日志 token，不看退出码。
- 交付件门在仪器看不见时给 `NO_SIGNAL`；ASCII DXF 无 `ezdxf` 也能验，二进制 DXF 缺库只能 `NO_SIGNAL`。
- 图纸 PDF 门只证明文本层存在，不证明内容画全；标题栏与中文技术要求由 NX 模型侧回读。
- 九种阵列中 `Mirror` 在提交阶段被拒；特征镜像走 `Features.MirrorFeatureBuilder`。
- 逆向重建不保证复杂件一次通过；本版提供结构清单、可编辑特征树与独立复算验收链。
- 装配层只提供定位类约束；球铰、圆柱铰、铰链、滑块到 Motion 域建。
- 技能只生成脚本与产物，不修改 NX 安装目录。

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

## 许可证

MIT。见 [LICENSE](LICENSE)。
