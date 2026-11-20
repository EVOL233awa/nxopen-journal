# nxopen-journal

[English](README.en.md) | 中文

当前版本 1.7.0（变更见 [CHANGELOG.md](CHANGELOG.md)）。

面向 Siemens NX 12 的 agent 技能。安装后，agent 可根据自然语言描述编写 NXOpen Python
journal，在本机 NX 12 中以批处理方式运行，生成三维模型、装配、Drafting 工程图、Nastran
有限元和 Motion 运动仿真结果。

## 适用版本

NX 12（当前使用 12.0.0.27）。其他 NX 版本未经测试。

### Python 版本

| 用途 | 解释器 | 版本 |
| --- | --- | --- |
| NX journal 执行 | NX 12 内嵌 Python | 3.6.1（固定，不能替换） |
| 仓库检查、PDF 复核 | 宿主 Python | 3.11+ |
| nxopen MCP | 宿主 Python | 3.11+（上游 `requires-python = ">=3.11"`） |

宿主工具本身的最低要求低于 3.11：`check_repo.py` 需要 3.8+，当前 pymupdf 需要 3.10+。统一使用
3.11+ 可以与 nxopen MCP 共用一套环境，避免维护两个 Python。

## 功能范围

技能覆盖 NX 自动化的五个基础域，并提供逆向重建、测量与交付件验证。工作方式都是 agent 编写 journal、批处理执行、核对产物：

| 域 | 覆盖内容 |
| --- | --- |
| 三维建模 | 草图、拉伸与旋转、布尔、抽壳与拔模、阵列（线性、圆周、沿路径、螺旋、正多边形、螺线、目标点、引用已有阵列）、孔包三种非螺纹孔型（螺纹用底孔+标注）、图层与类别、STL 导出 |
| 装配 | 装配结构、配对约束、可拖动机构、转动副两条路线、干涉检查两条几何路线 |
| Drafting | 三视图与投影视图、局部放大、剖视（阶梯剖、半剖、旋转剖）、装配图序号球/剖视/完整标题栏、尺寸与中心线标注、半径尺寸 |
| 有限元 | Nastran SOL101 静力、2D 壳网格、求解级标定、解算方案与边界条件描述符 |
| 运动仿真 | 连杆、转动副、滑动副、齿轮连接件，驱动、求解与结果提取 |
| 逆向重建 | 从无特征实体提取结构清单与截面，按结构特征重建为可编辑模型；用独立脚本复算截面轮廓、孔系、体积、包围盒、四视图和双向表面偏差 |
| 交付件验证 | STEP 实体普查（实体/面/边、NAUO、PRODUCT、PMI 子类型、悬空引用）、STL 拓扑（水密、绕向、有符号体积、欧拉数）、DXF 布局与实体计数、三轴切片占用与连通分量、图纸 PDF 文本层；判决三态 `PASS`/`FAIL`/`NO_SIGNAL` |

除了生成脚本，技能里还有几样配套工具：静态检查 `scripts/check_journal.py`、批处理入口
`scripts/run_journal_batch.bat`、国标出图模块 `scripts/gb_drawing.py`（A4/A3 图框、三视图钉位、装配图序号/剖视/完整标题栏、
标题栏、技术要求、尺寸道位，journal 中 `import gb_drawing` 后可直接使用）、用例标准层
`scripts/nxlib/`（测试框架与建模、装配、制图、测量、圆角滚刀、参数化模板、逆向测量编译/骨架/结构库/结构推断/转换/交换/审计等十五模块配方，回归用例直接 import，不各自复制），以及
`scripts/render/` 的离线出图链（批处理截不了图，三维图由 STL 在 NX 外渲染，工程图 PDF 转成图片）。
宿主侧另有交付件门 `scripts/deliverable.py`、`scripts/check_deliverables.py`、占用门
`scripts/occupancy.py`、离线 API 索引 `scripts/api_index.py` 与标记包装器 `scripts/run_journal_checked.py`。

## 示例产物

覆盖六个域（三维建模、装配、Drafting/国标出图、有限元、运动仿真、逆向重建）的实跑图件、生成环境与
版本标注，统一维护在 **nxopen-journal-toolkit** 的 README：
<https://github.com/EVOL233awa/nxopen-journal-toolkit>。

图件是安装后的 toolkit 在 NX 12 批处理中重新生成的，不是示意图；本仓库只保留技能源文件、参考
文档与回归套件。

## 前置条件

| # | 条件 | 怎么确认 | 缺了会怎样 |
| --- | --- | --- | --- |
| 1 | Windows 11 + Siemens NX 12（12.0.0.27），且安装了 NXOpen 自动化接口 | `%NX_HOME%\NXBIN\run_journal.exe` 存在 | 批处理无法运行，回归套件（51 个带判定的用例）无法执行，只剩静态检查可用 |
| 2 | `NX_HOME` 指向 NX 安装根 | 默认 `D:\UG-NX12`，装在别处先设 `NX_HOME`（写法见下一节） | 批处理找不到 `run_journal.exe`，打印报错并以退出码 2 结束，不会进入错误路径 |
| 3 | 一个能加载技能的 agent | 目录放进 agent 的技能目录后，让它读一次 `SKILL.md` | 技能不会被触发。本技能由 `SKILL.md` 头部的描述触发，不需要注册或编译 |
| 4 | Python 3.11+（宿主） | `python -V`。`check_journal.py`、`check_repo.py` 与工程图 PDF 数值复核使用它（后者还用到 pymupdf） | journal 不受影响：它由 NX 内嵌的 Python 3.6.1 执行；宿主 Python 只跑检查与 MCP |
| 5 | NX Nastran 解算授权 | 求解日志开头打印 `NASTRAN LICENSE:` 行，本机环境为 `DESKTOP BUNDLE`，授权来自本机许可服务 | 用例 09 与 25 无法运行，其余照常；这两个用例会实际调用求解器，不能跳过 |
| 6 | nxopen MCP | 见下一节 | 不装也能用，但写 API 时要靠 `dir()` 和 UGOPEN 头文件核实 |

### nxopen MCP（可选）

写 journal 时最容易出错的是 API 名与签名。nxopen MCP 用本机 NX 安装里的官方文档建索引，让 agent
查真实存在的类、成员与签名，而不是凭记忆写。它不属于本技能，需要单独安装：

- 整套安装：用 `nxopen-journal-toolkit`，`nxjt install` 会一并注册 MCP 并接好索引。
- 只装 MCP：本 fork [`nxopen-mcp-enhanced`](https://github.com/EVOL233awa/nxopen-mcp-enhanced)
  （远程嵌入与重排、重排超时回退、`get_class` 分页），或上游
  [`nxopen-mcp`](https://github.com/mingfeng6684/nxopen-mcp) v0.2.0。

装好后对 NX 安装目录建一次索引（`nxopen-mcp-enhanced index --nx-path <NX 安装根>` 或
`nxopen-mcp index --nx-path <NX 安装根>`）。索引、嵌入/重排配置与失败边界见 MCP 仓库的 README。

不装 MCP 也能用，只是 API 核实要退回 `dir()` 与 UGOPEN 头文件；查询中文夹英文术语
（如 `创建拉伸特征 extrusion`）命中明显更好，纯中文短词不可靠。

## 安装与使用

本节是一份可直接交给 agent 执行的任务说明。将下面代码块完整发送给 agent，技能来源已写为本仓库地址。

```text
任务：安装并验证 nxopen-journal 技能。

技能来源：https://github.com/EVOL233awa/nxopen-journal

步骤：
1. 安装技能
   - 将仓库克隆或下载到 agent 的技能目录，目录名保持 nxopen-journal：
     git clone https://github.com/EVOL233awa/nxopen-journal
   - Codex CLI：~/.codex/skills/
   - ZCode：~/.zcode/skills/
   - Claude Code：~/.claude/skills/
   - 其他 agent：按其文档放置。
   - 确认目录内存在 SKILL.md、scripts/run_journal_batch.bat、scripts/tests/RUN_TESTS.bat。

2. 检查运行环境
   - 操作系统：Windows 11。
   - NX 版本：Siemens NX 12（当前使用 12.0.0.27）。其他 NX 版本未经测试。
   - 确认 %NX_HOME%\NXBIN\run_journal.exe 存在。NX_HOME 默认 D:\UG-NX12；安装在别处时设置 NX_HOME。
   - 确认 NX 内嵌解释器为 Python 3.6.1；journal 脚本按 3.6 语法编写。
   - 宿主 Python：3.11+（用于 check_repo.py、check_journal.py、PDF 复核与 nxopen MCP；与 NX 内嵌解释器无关）。

3. 运行静态检查与回归
   - 执行 python scripts\check_repo.py，确认输出 CHECK_REPO_OK。
   - 执行 scripts\tests\RUN_TESTS.bat，逐条报告用例结果。
   - 判定标准：日志出现各用例的预期标记，且不出现 _FAIL 与 SKIP；最后一行是 === ALL TESTS PASSED ===。
   - 若失败，报告用例号、失败项、日志末尾 50 行；不要只报告退出码。

4. 配置 nxopen MCP（可选）
   - 推荐用 nxopen-journal-toolkit 的 nxjt install 一步完成技能与 MCP；也可按上一节单独安装。
   - 按 MCP 仓库的 README 用本机 NX 安装目录建索引。
   - 验证：get_class / get_member 返回成员，search_api 返回检索结果。
   - 未配置 MCP 时，说明编写 API 会退回 dir() 与 UGOPEN 头文件核实。

5. 输出报告
   - 安装路径与技能目录。
   - NX 版本、NX_HOME、Python 版本。
   - check_repo 与 RUN_TESTS 的结果。
   - 缺失项与需要人工决定的项（NX 版本不是 12、安装盘符不同等）。
```

### 日常使用

配置完成后，可直接用自然语言描述任务，例如：

> 用 nxopen-journal 建一个 120×80×12 的支座，四角 M8 沉头孔，并导出三视图。

agent 会先读 `SKILL.md`，再按任务类型读取对应的域文件，然后编写 journal、通过静态检查、执行批处理。产物是 `.prt` 文件与工程图。

### 安装后的验证

在技能目录中执行一次全量回归。日志中没有 SKIP 行，且最后一行显示全部通过，才表示本机环境齐备：

```
> scripts\tests\RUN_TESTS.bat
（输出从 PASS 01_bracket.py 开始，直至 PASS 30_fea_descriptors）
PASS 31_drafting_sections.py
PASS 32_pattern_enums.py
PASS 33_gb_sheet.py
PASS 34_involute_gear.py
PASS 35_assembly_preload.py
PASS 36_motion_slider.py
PASS 37_sketch_autodim_param.py
PASS 38_measure.py
PASS 39_reverse_route.py
PASS 40_rolling_network.py
（中间省略 PASS 41_template.py 至 PASS 53_pmi_census.py）
PASS 09_fea_static.py
PASS check_journal rule selftest - counter-examples hit, clean passes
PASS runner marker selftest
PASS pdf value check - test 19 annotation values
=== ALL TESTS PASSED ===
```

出现 SKIP 说明宿主 Python 或 pymupdf 缺失：装好 Python 3.11+ 并在该解释器里 `pip install pymupdf` 后重跑；打了 SKIP 的步骤不算通过。

51 个带判定的用例逐条通过。执行完成后默认删除 `scripts/tests/parts/` 下的产物，其中包括 Nastran 的中间
文件；这些文件每次运行都会重新生成。

## 回归用例

套件按域分布如下。每个用例覆盖什么、反向验证怎么做，记录在 `scripts/tests/README.md`。

| 域 | 用例 |
| --- | --- |
| 三维建模 | 01 02 03 05 08 14 15 22 26 28 32 34 37 |
| 参数化与审计 | 41 42 43 44 45 46 47 48 |
| 装配 | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 |
| 有限元 | 09 24 25 30 |
| 运动仿真 | 18 23 36（16 与 17 覆盖装配层运动副） |
| 测量与逆向 | 38 39 40 49 |
| 交付件验证 | 50 51 52 53（STEP 实体普查、STL 拓扑、导入矩阵、占用门、PMI 子类型） |

套件共 54 个用例文件 = 51 个带判定的 gate + 3 个一次性 API 探测脚本（后者不纳入校验，保留作参考）。

## 设计思路

NXOpen 的难点通常不在语法，而在于某个调用在 NX 12 批处理中能否正常运行。官方文档只解释
函数本身，不说明某些参数是否会导致进程崩溃。本技能把这些判断整理成了可以直接采用的
配方：每条结论先在 nxopen MCP 里核实 API 存在，再在 NX 12 批处理中通过；能固化的结论都有
对应的回归用例，改动后执行一次 `scripts\tests\RUN_TESTS.bat` 即可确认是否破坏。不可行的
写法按域内联在对应路线的约束句里，按“遇到什么 → 如何处理”查阅；跨域通用且高发的陷阱只在
`SKILL.md` §1。例如干涉检查给的是布尔求交与
`SimpleInterference` 两条几何路线，螺纹孔给的是“底孔 + 标注”，逆向重建给的是结构表 → 测量链 → 按结构建特征 → 验收门。

## 已知限制

- 验证环境为 Windows 11 + NX 12.0.0.27；其他平台与版本未经测试。
- 批处理会话不能直接截图：图像捕获 builder 提交后不报错也不写文件，UF 的 `Disp.CreateImage`
  会抛内存访问违例（视图定向与渲染样式可以改）。需要图片时，工程图走 Drafting 导出 PDF，
  三维模型导出 STL 后在 NX 外渲染；工具包 README 里的展示图就是这样来的。
- 用例 26 故意保留了一次原生崩溃，用来记录 `ThreadedHole` 的边界；这也是回归判定看日志里的预期输出、不看退出码的原因。崩溃发生在独立的 NX 进程里，不会影响本机 NX 安装或已有模型。
- 交付件门在仪器看不见时给 `NO_SIGNAL` 而不是 `PASS`，原因随判决一起返回（缺 `ezdxf`、缺 `pymupdf`、站距粗于最小特征的一半、页面无可提取文本）。ASCII DXF 走纯标准库解析、无 `ezdxf` 也能验；二进制 DXF 缺库时只能给 `NO_SIGNAL`。
- 图纸 PDF 门统计的是可提取 token（默认阈值 3 词），证明页面有文本层，不证明内容画全：标题栏与中文技术要求是矢量路径，由 NX 模型侧回读，内容完整度要看 `--pdf-expect`。
- 阵列九个类型里，`Linear`、`Circular`、`AlongPath`、`Helix`、`Polygon`、`Spiral`、`General`、
  `Reference` 都能在 `PatternFeatureBuilder` 里生成实例（用例 01、02、22、28、32）；`Mirror`
  在提交阶段被 NX 拒绝，特征镜像改用 `Features.MirrorFeatureBuilder`（用例 03）。
- 逆向重建仍不保证复杂件通过：本版提供结构清单、可编辑特征树和独立复算的验收链，但复杂铸件（如转向节）仍不能保证一次还原到位。
- 装配层只提供定位类约束（`Touch`/`Concentric`/`Fix`/`Distance`/`Parallel`/`Perpendicular`/`Angle`/`Fit`/`Bond` 等）：球铰、圆柱铰、铰链与滑块在 NX 12 装配层建不出来（赋类型直接抛错），真空间机构请用装配层定位后到 Motion 域建运动副；硬凑 `Fit`/`Bond` 会让解算把件甩飞。
- 技能只生成脚本和产物，不修改 NX 安装目录，脚本与模型都落在工作目录下。

## 目录结构

```
nxopen-journal/
├── SKILL.md                        ← 入口层：铁律 / 环境 / 脚本骨架 / 通用部件操作 / 日志导出 / 工作流 / 域路由
├── LICENSE                         ← MIT 许可证
├── CHANGELOG.md                    ← 版本变更记录（Keep a Changelog）
├── .github/workflows/ci.yml        ← 云端 CI（check_repo.py / check_journal 规则自测 / journal 静态检查，不需要 NX）
├── docs/wiki/                      ← 维护者导览：架构 / 主执行流 / 模块 / 数据流 / 边界与风险（入口 [docs/wiki/README.md](docs/wiki/README.md)）
├── references/                     ← 九个域文件：modeling / assembly / drafting / drafting-annotation / fea / motion / gb-drawing / reverse-engineering / verification
├── scripts/
│   ├── gb_drawing.py               ← 国标出图标准件（图框/三视图/装配图序号/剖视/标题栏/技术要求/尺寸道位/PDF）
│   ├── nxlib/                      ← 用例标准层（测试框架 + 建模/装配/制图/测量/圆角滚刀/模板/逆向五表/骨架/结构库/审计，用例 import 用）
│   ├── check_journal.py            ← 静态检查（AST + 已固化坑位规则库）
│   ├── check_repo.py               ← 仓库自检八组（Py3.6 语法 / 用例清单 / 文档结构 / 文件清单 / 标准层独占 / 文档精简 / 路线优先 / 维护者 wiki）
│   ├── run_journal_batch.bat       ← 单件批处理执行（NX_HOME 参数化）
│   ├── render/                     ← 离线出图链（STL 着色渲染、PDF 栅格化、裁边与比例尺）
│   └── tests/                      ← 回归套件（51 个带结果判定的用例 + 3 个一次性 API 探测脚本）+ 套件说明
└── agents/openai.yaml              ← Codex 与 OpenAI 端界面配置，跨端迁移用
```

每个用例覆盖什么、反向验证记录、已经不可行的路线，都在 `scripts/tests/README.md`。仓库自带
一份云端 CI（`.github/workflows/ci.yml`）：每次提交执行 `check_repo.py`、`check_journal` 规则自测，
以及对全部 journal 的静态检查；这些不需要 NX。回归套件本身要在装了 NX 12 的机器上执行。
