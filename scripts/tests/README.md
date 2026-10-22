# nxopen-journal 回归测试套件

本目录是 `nxopen-journal` 技能的回归测试套件：38 个用例（35 个并入令牌校验 + 11-13 三个一次性 API 探针），覆盖建模、装配、配对约束、运动连接、NX Motion、Drafting、FEA、测量与可编辑性。用例→文件→判决 token 见下表。改动技能（references 配方、`check_journal.py`、`run_journal_batch.bat`）后应先跑完本套件再交付。

## 运行方式（需 NX12 已安装；安装根用环境变量 `NX_HOME` 指定，默认 `D:\UG-NX12`）

全量（09 含 Nastran 求解）：

    scripts\tests\RUN_TESTS.bat

跑完默认删掉 `parts\` 下产物；想事后开模型检查，先 `set KEEP_PARTS=1` 再跑。

逐例运行（顺序同 `RUN_TESTS.bat` 的 `call :gate`）：

    scripts\run_journal_batch.bat <journal 的绝对路径> <parts 的绝对路径>

workdir 一律用 parts 目录；传相对路径会 File open failed。逐例清单以 `call :gate` 为准。

⚠ 26 号预期退出码 1（`ThreadedHole` 原生崩溃），日志仍写 `Execution was successful.`；判定只看令牌。

成功标志：出现该用例的判决 token，且输出中没有任何 `_FAIL`（实现见 `:gate` 子过程）。退出码不可作判据：未捕获异常才返回非零，journal 按 SKILL.md §3 每步 try/except 后继续，失败被吞时退出码仍为 0；26 号原生崩溃反而把退出码变成 1。

⚠ 22-30 九个用例是“逐项 `check()` 累加 + 末尾统一判”：单条失败打 `REG_xxx=FAIL <值>`（不含 `_FAIL`，不触发 `:gate` 扫描），全部通过才打 `TESTxx_DONE`，任一失败打 `TESTxx_FAIL failed=[...]` 并抛异常——两条独立失败路径（缺 token + `_FAIL` 行）。

NX 用例跑完后先做规则自检（host 端）：`verify_check_rules.py` 的每个反例必须命中对应规则、干净样本必须通过，判定出口 `PASS check_journal rule selftest - ...`。

19 值级复核（host 端）：NX 内嵌 Python 3.6 无 PDF 库，数值由 `verify_anno_pdf.py` 用 PDF 文本层核对（需 pymupdf）：

    python scripts\tests\verify_anno_pdf.py scripts\tests\parts\anno19.pdf

`RUN_TESTS.bat` 最后自动跑这一步（`set PYTHON=<带 pymupdf 的 python.exe>` 可指定解释器；无 pymupdf 返回 3，打印 SKIP 而非 FAIL）。token：`70`、`40`（两孔距关联尺寸真值）+ `R2.`、`4x`。该步骤无条件打印 `pdf value check interpreter: ...` 与 `pdf value check rc=<退出码>` 两行自证。判定出口三种：`PASS pdf value check - test 19 annotation values` / `SKIP pdf value check - ...`（无解释器或无 pymupdf）/ `FAIL pdf value check - ...`（RC 非 0 非 3，含 anno19.pdf 不存在）。

依赖：05 依赖 04 的 asm_plate.prt，06/08 依赖 01 的 bracket.prt。`RUN_TESTS.bat` 启动时清空并重建 `parts`，可反复全量重跑；逐条手动运行时才需自行清理旧同名产物。

## 用例、文件与判决 token

判决口径：日志必须出现本行 token，且没有任何 `_FAIL`。失败路径：有阶段的用例打 `TESTxx_FAIL stages=...`（17/19/20/21/31/32），逐项 `check()` 累加的打 `TESTxx_FAIL failed=[...]`（22-30），编号用例打 `TESTxx_FAIL <项名>`（06-08、14/15）。配方细节与已验证约束以 `references/*.md` 为准；本表只记判定出口与决定性判据（括号数字为值），用例源码头部注释记本用例的实现依据。除探针/死路用例（08/11-13/17/28/32）自包含外，其余用例一律 import `scripts/nxlib/` 标准层，不得复制配方——`check_repo.py` 会拦截同名顶层函数；写法见 `nxlib/__init__.py` docstring 与 SKILL.md §6。

| 用例 | 文件 | 判决 token | 决定性判据（验收什么；数字为值） |
| --- | --- | --- | --- |
| 01 | `01_bracket.py` | `TEST01_DONE` | 基座全流程：草图孔位取辅助线中点、种子孔+孔口倒圆+2×2 阵列、表达式改值更新；`stage()` 失败打 `TESTxx_FAIL` |
| 02 | `02_flange.py` | `TEST02_DONE` | UF 旋转体+布尔求和+圆周阵列+圆角 |
| 03 | `03_bracket_sym.py` | `TEST03_DONE` | 半剖草图拉伸+基准平面+特征级镜像 |
| 04 | `04_assembly.py` | `TEST04_DONE` | 多部件装配；`AddComponent`、`RootComponent.GetChildren` |
| 05 | `05_modify_existing.py` | `TEST05_DONE` | 打开已有部件改属性保存（依赖 04 的 asm_plate.prt） |
| 06 | `06_drafting.py` | `TEST06_DONE` | 消隐自带基准后三视图内容各 ≥8 可见（21/20/31）；只断个数会放过全空视图 |
| 07 | `07_center_marks.py` | `TEST07_DONE` | 一标记一 builder（4/4）+`Centerline2d` ByPoints；单 builder ≥3 location 报 1175305，变则打 `CENTERMARK_MULTI_CHANGED` |
| 08 | `08_editability_probe.py` | `TEST08_DONE` | 读回 01 的 prt：特征树非空、表达式可读、草图 `fully=True`、单实体；不满足打 `TEST08_FAIL <项名>` |
| 09 | `09_fea_static.py` | `BENCH_PASS` | 悬臂梁 SOL101 与手算比 0.9~1.4 |
| 10 | `10_assembly_constraints.py` | `CONSTRAINT_PASS` | `Touch` 把销钉解到 z=10 |
| 11-13 | `11…13_api_probe*.py` | （无） | 一次性 API 探针，不纳入令牌校验，留作历史证据 |
| 14 | `14_block_boolean.py` | `TEST14_DONE` | 布尔后断言体积：期望 `120000−20³`（112000）；token 须在 ok 判定之后 |
| 15 | `15_shell_draft.py` | `TEST15_DONE` | 抽壳去顶面 V=23232.000；四侧拔模 ±5° 与解析式零偏差 |
| 16 | `16_motion_constraints.py` | `BENCH_PASS` | 等半径圆柱孔面 `Fit` 转动副：孔轴间距 36.0555→0.0000；`Bond` 销轴跟动 ≤0.01 |
| 17 | `17_motion_deadends.py` | `TEST17_DONE` | 6 阶段：圆边 `Concentric` `Solved` 且移 25 mm（DOF `0T+1R`）、圆柱面 `Concentric` `CannotSolve`、等半径 `Fit` `Solved`、不等半径 `Fit` `InternallyInconsistent`、7 种内部枚举全被拒；失败打 `TEST17_FAIL stages=...` |
| 18 | `18_motion_sim.py` | `BENCH_PASS` | 曲柄 1.00000°/帧、摇杆 60.0282°（解析 60.0218°）、每转换向 2 次、反力通路；驱动 2π 时前三项 FAIL，`CD` 40→50 仅摆角 FAIL；0 基 361 帧；落盘 `m18_motion.csv`（不判） |
| 19 | `19_drafting_annotation.py` | `TEST19_DONE` | 12 阶段：节距 70/40、字高 `textSize=5.00`（须非默认）、3 个 UF 关联尺寸、中心标记/中心线/注释/引线、表格回读、PDF >20KB；失败打 `TEST19_FAIL stages=...` |
| 20 | `20_drafting_views.py` | `TEST20_DONE` | 10 阶段：`View.Base` 三视图各 ≥4 可见（5/5/7）、`View.Drawing` 对照 0、删 TOP/RIGHT 并钉 FRONT 1:1、2 投影视图各 7、局部放大按 UF `AskViewScale` 2.0=2.0×父（.NET `Scale` 2.36 不作口径）、超 A4 被拒 |
| 21 | `21_drafting_section.py` | `TEST21_DONE` | 6 阶段：毛坯圆柱面 ≥1（`Hatch` 单独证明不了孔）、三视图各 ≥10（13/13/14）、先设父视图再 `AddCutSegment`（无父视图必抛）、剖视可见 18 且 `Hatch` ≥1、阶梯剖腿段 9>普通剖 5（`AskSxlineType` 均报 `STEPPED_SXLINE`） |
| 22 | `22_modeling_extras.py` | `TEST22_DONE` | 13 项：图层/类别、`Feature.Layer` 不存在、`SetState` 只传 int（list 会堆损坏）、基准平面配方、`AlongPath` 质心 y=0/y=100（±1e-3）；`DatumCsysBuilder` 死路 |
| 23 | `23_motion_connectors.py` | `TEST23_DONE` | 14 项：连接件集合真名、三个 `Scalar*` 不存在、弹簧 `AttachmentType` 只读、阻尼器补系数后 0→1、衬套缺 `Orientation` 报 `A NULL value`、`MotionInterference_Struct` 字段 `Solid1/Solid2`、`AskGrueblerCount` 整数、`DriverMultiOperations` 三项 |
| 24 | `24_shell_mesh.py` | `TEST24_DONE` | 7 项：PSHELL 属性表+库材质+壳收集器；`ElementType` 含 `Shell` 不含 `ThinShell`；`CQUAD4` 节点 126；只网格不求解 |
| 25 | `25_shell_solve.py` | `TEST25_DONE` | 11 项：PSHELL 厚度 5.0、204 节点 CQUAD4、端边固支+−Z 100 N→SOL101；挠度比 0.9994、von Mises 比 0.9871（期望来自梁理论）；壳厚改 2.5 则两条 FAIL |
| 26 | `26_hole_package.py` | `TEST26_DONE` | 12 项：`GeneralHole`/`DrillSizeHole` Ø10×15、`ScrewClearanceHole` Ø11 可建且读回；缺 `Tolerance` → `Validate` 报 three numbers；`ThreadedHole` 必抛内存访问违例；预期退出码 1 |
| 27 | `27_radius_dim.py` | `TEST27_DONE` | 11 项：按 `Edge.SolidEdgeType` 筛边（`p1==p2` 整圆）；`CreateRadiusDim(..., ARC_CENTER)` 对圆弧边与孔口整圆边均 `computed=10.0000`；直线边必抛 `The input object is invalid.`；计数 2 |
| 28 | `28_pattern_helix.py` | `TEST28_DONE` | 18 项：`PatternEnum.Helix` 满足 `z=节距·θ/2π`、`r=R`，`CountOfInstances` 含种子，不给轴零副本；三种间距标定，超末端副本丢弃；末条崩溃探针 |
| 29 | `29_interference.py` | `TEST29_DONE` | 8 项：布尔交集干涉体积 500.000 mm³（5×10×10）；分离/面贴面被拒且不留空壳；`CreateSimpleInterferenceObject()` 独立判定；四件落盘 >100 KB |
| 30 | `30_fea_descriptors.py` | `TEST30_DONE` | 15 项：描述符全集 11 个并用独立字面量钉项数；显示名≠描述符名；垃圾名报 `Error number: 1775003`；新建方案带走激活方案，回切后恢复；中性名黑名单 3 拒、白名单 2 可建 |
| 31 | `31_drafting_sections.py` | `TEST31_DONE` | 8 阶段：半剖（`HALF_SXLINE`、可见 18、`DraftingCurve` 8）、两点直线也提交（17/7）、旋转剖（`REVOLVED_SXLINE`、两腿 4 段）、缺 `RotationPoint` 必抛、展开剖只靠出图字节数区分、落盘 210181 字节 |
| 32 | `32_pattern_enums.py` | `TEST32_DONE` | 13 阶段：`Polygon` 逐点核质心（`NCopies=4` 时 18 件、沿边等弦长，偏差 6e-14）、`NCopies=1` 必拒；`General` 按目标点映射、空 `ToPoints` 抛 `Update undo happened.`；`Reference` 种子兼基准实例、`SetBaseInstance(1,0)` 整族平移；`Mirror` 提交抛 `Feature cannot be mirrored.`；`Spiral` 缺水平参考抛 `No section curves or points created.` |
| 33 | `33_gb_sheet.py` | `TEST33_DONE` | 7 阶段经 `gb_drawing` 出国标图：三视图按内容包盒钉位（5/7/5）、标题栏回读、4 线性尺寸（100/44/60/10）+`2x<O>10` 引线、道位同向小内大外（`LANE_ORDER_OK`，换道 FAIL）、PDF 38912 字节。模块事实：`SetDrawingReferencePoint` 移动 plot 内容、越界回滚、`AskViewBorders` 被标签余量撑大（禁布局）、`DraftingDrawingSheet` 无 `Width/Height`、枚举 `END_POINT` |
| 34 | `34_involute_gear.py` | `TEST34_DONE` | 齿轮：表达式驱动规律曲线 40 条+ZLaw Constant+闭合轮廓一次 UF 拉伸；体积与解析积分比 ±2%（扣孔 18238.9 mm³）、圆柱面 bore=1/tip=20/root=20、`model_bbox` 走 `ufs.ModlGeneral.AskBoundingBox`（不是 Modeling）；轮毂分支体积增量 π(4.5²−2.5²)×4（175.929，0.000%） |
| 35 | `35_assembly_preload.py` | `TEST35_DONE` | 预载+干涉：base+pin 悬空 5mm 装配后重开；不预载则 SimpleInterference 空跑 inst_bodies=0，重复加载幂等；实例体 2；SimpleInterference 0 对（悬空负例；判材料重叠须布尔交集） |
| 36 | `36_motion_slider.py` | `BENCH_PASS` | 滑动副：3 Revolute+1 Slider，偏置曲柄滑块 r40/l120/e20；5 判据：721 帧、滑块 x 偏差 0.001316 mm、y 恒 20、杆长守恒 0.001303 mm（兼探针行主序，转置漂 14 mm）、线速度偏差 0.003213 mm/s |
| 37 | `37_sketch_autodim_param.py` | `TEST37_DONE` | 自动尺寸→命名参数：不调 `GetStatus` 也出尺寸（3 个）、改指后 dof=0、R10×5 拉伸 V=1570.7963（解析同值）、`R_TEST`×1.5 后 V=3534.2917（2.25 倍）、还原 1570.7963；反面对照 AutoConstrain 先跑 → 0 尺寸（这才是“不出尺寸”的真因） |
| 38 | `38_measure.py` | `TEST38_DONE` | 15 项只读测量链：块+Ø20 凸台+Ø10 通孔+90° 锪面+R2 圆角 → 面类型 16/17/19/22、孔组 D10 壁长 28（顶边被圆角吃掉 2）、锥半角 45°、STL 包盒 100×60×30、截面 z=10 面积 5843.147（解析 5842.920，0.0039%）、自 IoU 1.0、top 轮廓 IoU 1.0/面积 5849.176、自比对与功能清单比对均 0 未匹配且最大差 0 |

## 反向验证记录

判据判别力靠“改坏期望值或承重行 → 应 FAIL → 还原并校验文件哈希”确认。

| 用例 | 变异（几何不动，只改期望值或承重行） | 应报 FAIL |
| --- | --- | --- |
| 06 / 20 | `View.Base` 换成 `View.Drawing` | 两者均 FAIL（可见对象 0） |
| 20 | 投影阈值 4→99；局部放大比例乘改加 | 均 FAIL |
| 21 | 删父视图赋值；切点改图纸坐标；`HATCH_MIN` 1→2 | 三条各自 FAIL |
| 18 | 驱动 360→2π；连杆 40→50 | 前者曲柄/摆角/换向 FAIL，后者仅摆角 FAIL |
| 36 | 偏置符号 `E`→`−E` | 仅滑块 x 判据 FAIL（`MAX_DX=14.399113 mm`），其余四项 PASS |
| 19 | 节距 70→71；去掉 `SetLetteringPreferences` | 前者 FAIL；后者须字高取非默认 5.0 时才 FAIL |
| 17 | 圆边 `Concentric` 换等半径 `Fit` | 该阶段 FAIL（`dz=8.0000`） |
| 14 | 期望体积改 `120000-20³` | FAIL；未改副本 PASS |
| 22 / 23 | 质心 y=0→50；清单漏 `Tag` | 各有一条 `REG_*=FAIL` |
| 30 | 显示名改假名；回切断言改恒真；清单删一项；真名改假名 | 前两条 FAIL；删项须靠独立项数断言才 FAIL |
| 32 | 等弦长改等角度均分 | `polygon_copies_per_side` FAIL（2.0823 mm）；`NCopies=2` 两模型重合仍 PASS，判别力来自 `NCopies≥4` |
| 32 | 引用阵列期望写“新增 3 件” | `reference_layout`/`reference_base_instance` FAIL；改按整族 3 件核对后通过 |
| 19 PDF | 图纸 PDF 与另一份无关 PDF 各跑一次 | 均 `VERIFY_FAIL missing 70,40,R2.,4x` RC=1 |

四条判据设计规则：

- 阈值须取“只有真做了才可能出现”的值；19 取模板默认字高会让断言空转。
- 覆盖清单断言须另钉项数，否则删一项仍通过。
- 判定结果必须无条件出现；异常在 `stage()` 之外时须有顶层兜底与前置检查。
- 先证明模型真建成，再读它：21 探针 5 面选取出错时读数来自实心块，带孔为 18。

## 配方归属

域配方的唯一权威在 `references/*.md`；本文件只维护用例、判决 token 与反向验证。新增约束写进对应域文件的路线，不在这里累积。

## 静态检查

每个 journal 应先通过：

    python scripts\check_journal.py scripts\tests\01_bracket.py

探针文件（故意演示坑位）在文件头加一行 `# check_journal: allow-probes` 可豁免布尔/类型类拦截。

检查器规则 5.16 用 AST 拦截 journal 解释器是 Python 3.6.1 带来的专属陷阱：`math.dist`/`math.prod`/`math.isqrt`/`math.comb`/`math.perm`/`math.nextafter`、`functools.cache`/`functools.cached_property`、`itertools.pairwise`。用 AST 而非文本匹配是必要的——本技能 `tests/18` 的注释里就写着“不用 math.dist”，文本匹配会把自己的文件误判为错误。
