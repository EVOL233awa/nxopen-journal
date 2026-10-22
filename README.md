# nxopen-journal

[English](README.en.md) | 中文

当前版本 1.2.0（变更见 [CHANGELOG.md](CHANGELOG.md)）。

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

技能覆盖 NX 自动化的五个域，工作方式都是 agent 编写 journal、批处理执行、核对产物：

| 域 | 覆盖内容 |
| --- | --- |
| 三维建模 | 草图、拉伸与旋转、布尔、抽壳与拔模、阵列（线性、圆周、沿路径、螺旋、正多边形、目标点、引用已有阵列）、孔包三种非螺纹孔型（螺纹用底孔+标注）、图层与类别、STL 导出 |
| 装配 | 装配结构、配对约束、可拖动机构、转动副两条路线、干涉检查两条几何路线 |
| Drafting | 三视图与投影视图、局部放大、剖视（阶梯剖、半剖、旋转剖）、尺寸与中心线标注、半径尺寸 |
| 有限元 | Nastran SOL101 静力、2D 壳网格、求解级标定、解算方案与边界条件描述符 |
| 运动仿真 | 连杆、转动副、滑动副、齿轮连接件，驱动、求解与结果提取 |

除了生成脚本，技能里还有几样配套工具：静态检查 `scripts/check_journal.py`、批处理入口
`scripts/run_journal_batch.bat`、国标出图模块 `scripts/gb_drawing.py`（A4 图框、三视图钉位、
标题栏、技术要求、尺寸道位，journal 中 `import gb_drawing` 后可直接使用）、用例标准层
`scripts/nxlib/`（测试框架与建模、装配、制图等配方，回归用例直接 import，不各自复制），以及
`scripts/render/` 的离线出图链（批处理截不了图，三维图由 STL 在 NX 外渲染，工程图 PDF 转成图片）。

## 示例产物

下面的图都来自本机实际运行。每个模块由一个没有先前上下文的 agent 独立完成：
它只拿到技能文档和任务描述，自己设计零件、写 journal、通过静态检查、批处理执行并核对结果，
最后由人工检查最终图件。三维和装配图由批处理导出的 STL 在 NX 外渲染；工程图是批处理直接导出的 PDF
转成图片；有限元和运动图使用求解器写出的数据。

| 三维建模：轴承支座（正三轴测渲染） | 装配：板、销、衬套与轴帽（配对约束分色） |
| --- | --- |
| <img src="images/modeling.png" width="400"> | <img src="images/assembly.png" width="400"> |

装配图中的四个销钉由 13 条持久约束固定在底板孔位上，7 个组件的位置逐个回读确认。衬套和
轴帽套在底板中央，分色渲染用来区分配合关系。

| Drafting：三视图、A-A 剖视与尺寸中心线标注 | 国标出图：A4 图幅、图框、标题栏与技术要求 |
| --- | --- |
| <img src="images/drafting-annotation.png" width="400"> | <img src="images/gb-drawing.png" width="400"> |

Drafting 图的 9 道尺寸都关联在几何上，导出 PDF 后用文本层核对过数值。国标图的图框、
标题栏和尺寸位置由 `gb_drawing` 生成。

| 有限元：SOL101 悬臂梁静力 vs 梁论（双面板） | 运动仿真：曲柄摇杆摆角与角速度 vs 解析解 |
| --- | --- |
| <img src="images/fea.png" width="900"> | <img src="images/motion.png" width="900"> |

有限元图的上半部分是 14998 节点位移场与梁理论曲线的对比，自由端比值 0.982；下半部分是
底面纤维应力与理论的对比，中段比值 1.000，根部圣维南区已注明不作判据。运动图使用 720 步
求解的逐帧数据，摆角跨度与解析解相差 0.0014°，换向次数一致。

### 进阶案例：ZA 曲柄摇杆机构总成

在六个基础模块之外，还用同样的方式执行了一轮更完整的测试：7 种 18 件的曲柄摇杆机构总成，
从零件建模、装配到装配图一次完成，再基于装配参数出两张运动学分析图。装配图由 NX 12
批处理 Drafting 直接生成；两张运动学图由 Python 脚本复算并绘制，不经过 NX。

| 装配图：三视图 + 球标 + 明细栏 + 标题栏（A3 图幅） | 机构运动简图：GB 符号 + 极限位置 |
| --- | --- |
| <img src="images/za-assembly.png" width="450"> | <img src="images/kin-mechanism.png" width="450"> |

装配图的 7 只球标都挂在几何上，明细栏 7 行与零件一一对应，技术要求放在明细栏正上方。
竖直尺寸的字向通过 .NET 姿态接口固定为平行尺寸线，避免 UF 默认字向在同一代码路径下
随机叠放数字。

| 运动包络与干涉检查：包络外弧 + E 点连杆曲线 + 间隙标注 |
| --- |
| <img src="images/kin-envelope.png" width="900"> |

运动学数值经独立脚本复算：Grashof 判别成立，γmin=55.77°，摇杆摆角 49.58°，极限位置角
91.79°/141.38°，包络外弧到板边最小间隙 39.91 mm，解析解与 721 步数值扫描的最大偏差
0.009 mm。曲柄轨迹圆投影越出板缘 10 mm，Z 向最小间隙 2 mm，全程无空间干涉。

## 前置条件

| # | 条件 | 怎么确认 | 缺了会怎样 |
| --- | --- | --- | --- |
| 1 | Windows 11 + Siemens NX 12（12.0.0.27），且安装了 NXOpen 自动化接口 | `%NX_HOME%\NXBIN\run_journal.exe` 存在 | 批处理无法运行，回归套件（35 个带判定的用例）无法执行，只剩静态检查可用 |
| 2 | `NX_HOME` 指向 NX 安装根 | 默认 `D:\UG-NX12`，装在别处先设 `NX_HOME`（写法见下一节） | 批处理找不到 `run_journal.exe`，打印报错并以退出码 2 结束，不会进入错误路径 |
| 3 | 一个能加载技能的 agent | 目录放进 agent 的技能目录后，让它读一次 `SKILL.md` | 技能不会被触发。本技能由 `SKILL.md` 头部的描述触发，不需要注册或编译 |
| 4 | Python 3.11+（宿主） | `python -V`。`check_journal.py`、`check_repo.py` 与工程图 PDF 数值复核使用它（后者还用到 pymupdf） | journal 不受影响：它由 NX 内嵌的 Python 3.6.1 执行；宿主 Python 只跑检查与 MCP |
| 5 | NX Nastran 解算授权 | 求解日志开头打印 `NASTRAN LICENSE:` 行，本机环境为 `DESKTOP BUNDLE`，授权来自本机许可服务 | 用例 09 与 25 无法运行，其余照常；这两个用例会实际调用求解器，不能跳过 |
| 6 | nxopen MCP | 见下一节 | 不装也能用，但写 API 时要靠 `dir()` 和 UGOPEN 头文件核实 |

### nxopen MCP 与嵌入服务

nxopen MCP 不在本技能里，是另一个项目（[nxopen-mcp](https://github.com/mingfeng6684/nxopen-mcp)），
需要单独安装。它直接查 NX 自己的 API 文档，是这个技能避免 API 幻觉的主要手段。其中
`get_class` 和 `get_member` 只用本地索引；`search_api` 和 `find_builder` 还依赖本机的嵌入服务，
服务没起时会直接报错，不会退化成关键词检索。

上游已发布 v0.2.0（最新）与 v0.1.0，带 tag 和 release。安装方式：
`pip install "nxopen-mcp[embed,reflect]"`（上游 `requires-python` 为 >=3.11），或按上游 README 用
`uvx nxopen-mcp` 免安装运行。本机为源码可编辑安装，本地版本 0.2.0，下面的
`NXOPEN_MCP_*` 环境变量按该版本编写。安装后要对着本机的 NX 安装目录建一次索引，
索引和查询必须使用同一个嵌入模型。

嵌入服务只要提供 OpenAI 兼容的 `/v1/embeddings` 即可。llama.cpp 的 `llama-server --embedding`、
Ollama、LM Studio 都能加载 `bge-m3`（1024 维）。本机使用 llama-server，参数如下，仅作示例：

```
llama-server --model <bge-m3.gguf> --embedding --pooling cls --embd-normalize 2 --host 0.0.0.0 --port 11436 --ctx-size 8196
```

在 MCP 侧按实际使用的服务填三个环境变量，`NXOPEN_MCP_EMBEDDER` 选 `llama`（llama.cpp、
LM Studio 这类 OpenAI 兼容接口）或 `ollama`：

```
NXOPEN_MCP_EMBEDDER=llama
NXOPEN_MCP_OLLAMA_URL=<嵌入服务地址，例如 http://127.0.0.1:11436>
NXOPEN_MCP_OLLAMA_MODEL=bge-m3
```

服务就绪的判据是模型列表里能看到 `bge-m3`：llama.cpp 查 `GET {url}/v1/models`，Ollama 查
`GET {url}/api/tags`。走 `llama` 通道连 LM Studio 的兼容性未验证。

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
   - 判定标准：日志出现各用例的预期标记，且不出现 _FAIL；最后一行是 === ALL TESTS PASSED ===。
   - 若失败，报告用例号、失败项、日志末尾 50 行；不要只报告退出码。

4. 配置 nxopen MCP（可选）
   - 安装：pip install "nxopen-mcp[embed,reflect]"（Python 3.11+），或 uvx nxopen-mcp。
   - 上游最新 release 为 v0.2.0。
   - 按上游 README 用本机 NX 安装目录建索引：nxopen-mcp index --nx-path <NX 安装根>。
   - 嵌入服务需提供 OpenAI 兼容的 /v1/embeddings，并加载 bge-m3（1024 维）。
   - 配置 NXOPEN_MCP_EMBEDDER、NXOPEN_MCP_OLLAMA_URL、NXOPEN_MCP_OLLAMA_MODEL。
   - 验证：GET {url}/v1/models（llama.cpp）或 GET {url}/api/tags（Ollama）中能看到 bge-m3。
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

在技能目录中执行一次全量回归。最后一行显示全部通过，即表示本机环境齐备：

```
> scripts\tests\RUN_TESTS.bat
（输出从 PASS 01_bracket.py 开始，直至 PASS 30_fea_descriptors）
PASS 31_drafting_sections.py
PASS 32_pattern_enums.py
PASS 33_gb_sheet.py
PASS 34_involute_gear.py
PASS 35_assembly_preload.py
PASS 36_motion_slider.py
PASS 09_fea_static.py
PASS check_journal rule selftest - counter-examples hit, clean passes
PASS pdf value check - test 19 annotation values
=== ALL TESTS PASSED ===
```

35 个用例逐条通过。执行完成后默认删除 `scripts/tests/parts/` 下的产物，其中包括 Nastran 的中间
文件；这些文件每次运行都会重新生成。

## 回归用例

套件按域分布如下。每个用例覆盖什么、反向验证怎么做，记录在 `scripts/tests/README.md`。

| 域 | 用例 |
| --- | --- |
| 三维建模 | 01 02 03 05 08 14 15 22 26 28 32 34 |
| 装配 | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 |
| 有限元 | 09 24 25 30 |
| 运动仿真 | 18 23 36（16 与 17 覆盖装配层运动副） |

另有 3 个一次性 API 探测脚本不纳入校验，保留作参考。

## 设计思路

NXOpen 的难点通常不在语法，而在于某个调用在 NX 12 批处理中能否正常运行。官方文档只解释
函数本身，不说明某些参数是否会导致进程崩溃。本技能把这些判断整理成了可以直接采用的
配方：每条结论先在 nxopen MCP 里核实 API 存在，再在 NX 12 批处理中通过；能固化的结论都有
对应的回归用例，改动后执行一次 `scripts\tests\RUN_TESTS.bat` 即可确认是否破坏。不可行的
写法按域内联在对应路线的约束句里，按“遇到什么 → 如何处理”查阅；跨域通用且高发的陷阱只在
`SKILL.md` §1。例如干涉检查给的是布尔求交与
`SimpleInterference` 两条几何路线，螺纹孔给的是“底孔 + 标注”。

## 已知限制

- 验证环境为 Windows 11 + NX 12.0.0.27；其他平台与版本未经测试。
- 批处理会话不能直接截图：图像捕获 builder 提交后不报错也不写文件，UF 的 `Disp.CreateImage`
  会抛内存访问违例（视图定向与渲染样式可以改）。需要图片时，工程图走 Drafting 导出 PDF，
  三维模型导出 STL 后在 NX 外渲染；README 里的模型图与装配图就是这样来的。
- 用例 26 故意保留了一次原生崩溃，用来记录 `ThreadedHole` 的边界；这也是回归判定看日志里的预期输出、不看退出码的原因。崩溃发生在独立的 NX 进程里，不会影响本机 NX 安装或已有模型。
- 阵列九个类型里，`Linear`、`Circular`、`AlongPath`、`Helix`、`Polygon`、`Spiral`、`General`、
  `Reference` 都能在 `PatternFeatureBuilder` 里生成实例（用例 01、02、22、28、32）；`Mirror`
  在提交阶段被 NX 拒绝，特征镜像改用 `Features.MirrorFeatureBuilder`（用例 03）。
- 技能只生成脚本和产物，不修改 NX 安装目录，脚本与模型都落在工作目录下。

## 目录结构

```
nxopen-journal/
├── SKILL.md                        ← 入口层：铁律 / 环境 / 脚本骨架 / 通用部件操作 / 日志导出 / 工作流 / 域路由
├── CHANGELOG.md                    ← 版本变更记录（Keep a Changelog）
├── references/                     ← 八个域文件：modeling / assembly / drafting / drafting-annotation / fea / motion / gb-drawing / reverse-engineering
├── images/                         ← 实际运行产物图（上面九张）
├── scripts/
│   ├── gb_drawing.py               ← 国标出图标准件（图框/三视图/标题栏/技术要求/尺寸道位/PDF）
│   ├── nxlib/                      ← 用例标准层（测试框架 + 建模/装配/制图/测量等六域配方，用例 import 用）
│   ├── check_journal.py            ← 静态检查（AST + 已固化坑位规则库）
│   ├── check_repo.py               ← 仓库自检（Py3.6 语法 / 用例清单 / 文档结构 / 文件清单 / 标准层独占 / 文档精简）
│   ├── run_journal_batch.bat       ← 单件批处理执行（NX_HOME 参数化）
│   ├── render/                     ← 离线出图链（STL 着色渲染、PDF 栅格化、裁边与比例尺）
│   └── tests/                      ← 回归套件（35 个带结果判定的用例 + 3 个一次性 API 探测脚本）+ 套件说明
└── agents/openai.yaml              ← Codex 与 OpenAI 端界面配置，跨端迁移用
```

每个用例覆盖什么、反向验证记录、已经不可行的路线，都在 `scripts/tests/README.md`。仓库自带
一份云端 CI（`.github/workflows/ci.yml`）：每次提交执行 Python 3.6 语法检查、`check_journal.py`
与 `scripts/check_repo.py`，这三项不需要 NX；回归套件本身要在装了 NX 12 的机器上执行。
