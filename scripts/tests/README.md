# nxopen-journal 回归测试套件

本目录是 `nxopen-journal` 技能的回归测试套件：35 个用例（32 个并入令牌校验 + 11-13 三个一次性 API 探针），覆盖建模、装配、配对约束、运动连接、NX Motion 运动仿真、Drafting、FEA 与可编辑性验证——**逐个用例覆盖什么、判决 token 是什么，见下表**。任何对技能（references 配方、check_journal.py、run_journal_batch.bat）的改动，都应先跑完本套件再交付。

## 运行方式（需 NX12 已安装；安装根用环境变量 `NX_HOME` 指定，默认 `D:\UG-NX12`）

在 cmd/PowerShell 中一键全量（09 含 Nastran 求解，较慢）：

    scripts\tests\RUN_TESTS.bat

跑完默认会删掉 `parts\` 下的产物（2026-09-23 全量实测 **72 个文件 / 27.7 MB**，按 `parts\` 递归统计（含 `m18_asm\`、`t23_connectors\` 两个子目录），原始 28 994 071 字节；其中含 Nastran 的 `.f06`/`.op2` 中间件、30 号用例的 4 个产物与 18 号用例的逐帧曲线 CSV，它们每次运行都完整重建）；想事后开模型检查，先 `set KEEP_PARTS=1` 再跑。

或逐个运行。顺序与 `RUN_TESTS.bat` 里的 `call :gate` 清单一致（09 含 Nastran 求解，排在最后）：

    scripts\run_journal_batch.bat <journal 的绝对路径> <parts 的绝对路径>

workdir 一律用 parts 目录：批处理会先切到 workdir，传相对路径会 File open failed。逐例清单不在这里重复维护，以 `RUN_TESTS.bat` 的 `call :gate` 行为准。

⚠ **26 号预期退出码为 1**（它故意复现 `ThreadedHole` 的原生崩溃，见下"已知限制"），日志里仍会写 `Execution was successful.` —— 判定只看令牌，不看退出码。

成功标志：**出现该用例的判决 token，且输出中没有任何 `_FAIL`**（2026-09-20 起全部用例统一令牌校验，实现见 `RUN_TESTS.bat` 的 `:gate` 子过程）。检查不依赖退出码是有原因的：`run_journal.exe` 对**未捕获**异常确实返回非零（顶层 `raise` 实测 `RUN_JOURNAL_EXIT=1`），但这些 journal 按 SKILL.md §3 的要求"每步 try/except 打 traceback 后继续"，失败被自己吞掉时退出码仍是 0；另有第三种污染源——**26 号故意触发的 `ThreadedHole` 原生崩溃会把退出码变成 1（日志却写 `Execution was successful.`）**。故约定：成功路径只在全部通过时打印判决 token，失败路径必须打印带 `_FAIL` 的判定结果。
⚠ 22/23/24/25/26/27/28/29/30 九个用例是"逐项 `check()` 累加 + 末尾统一判"的写法：单条失败打 `REG_xxx=FAIL <实测值>`（**不含 `_FAIL` 子串**，不会触发 `:gate` 的 `_FAIL` 扫描），全部通过才打 `TESTxx_DONE`，任一失败则打 `TESTxx_FAIL failed=[...]` 并抛异常——两条独立的失败路径（缺 token + `_FAIL` 行）。

**19 的值级复核（host 端）**：NX 内嵌 Python 3.6 没有 PDF 库，尺寸**数值**由
`verify_anno_pdf.py` 在宿主解释器上用 PDF 文本层核对（需 pymupdf）：

    python scripts\tests\verify_anno_pdf.py scripts\tests\parts\anno19.pdf

`RUN_TESTS.bat` 会在最后自动跑这一步（`set PYTHON=<带 pymupdf 的 python.exe>` 可指定解释器；
没装 pymupdf 时脚本返回 3，检查打印 SKIP 而非 FAIL）。实测 token：`70`、`40`（两孔距
关联尺寸的真实值）+ `R2.`、`4x`（技术要求注释与引线标签确实渲染进图）。

该步骤**无条件打印两行自证**——`pdf value check interpreter: <解释器绝对路径>` 与
`pdf value check rc=<退出码>`——再加上解释器自身的 `PDF pages=...` / `VERIFY_PASS ...`。
之所以强制自证：这一段曾经因为 `if (...)` 块内 echo 文本带裸括号而**整段静默不执行**
（套件照样全部通过），"没输出"必须能与"没执行"区分开。判定出口只有三种，都带关键字：
`PASS pdf value check - test 19 annotation values` / `SKIP pdf value check - ...`（无解释器或无 pymupdf）/
`FAIL pdf value check - ...`（RC 非 0 非 3，含 anno19.pdf 不存在）。

这两道 host 侧步骤也做过反向验证（记录见"反向验证记录"一节）：`verify_anno_pdf.py` 对 `anno19.pdf`
打 `VERIFY_PASS 70 40 R2. 4x` RC=0，对两份外来 PDF（一张图纸 PDF、一篇论文 PDF）均打
`VERIFY_FAIL missing 70,40,R2.,4x` RC=1，文件不存在时抛 `FileNotFoundError` RC=1（判 FAIL，不静默
SKIP）。

依赖关系：05 依赖 04 生成的 asm_plate.prt，06/08 依赖 01 生成的 bracket.prt。`RUN_TESTS.bat` 启动时会清空并重建 `parts` 目录，因此可反复全量重跑；逐条手动运行时才需自行清理旧同名产物。



## 用例、文件与判决 token

判决口径见上一节：**日志里必须出现本行的 token，且没有任何 `_FAIL`**。失败路径的约定是：
有阶段划分的用例打 `TESTxx_FAIL stages=...`（17/19/20/21/31/32），逐项 `check()` 累加的用例打
`TESTxx_FAIL failed=[...]`（22-30），编号用例打 `TESTxx_FAIL <项名>`（06-08、14/15）。
逐例的配方细节、坑位与实测过程写在用例源码的头部注释里（那里是唯一真源，改用例时一并更新），
本表只记判定出口与该例的**决定性判据**（括号里的数字是实测值，不是设计值）。
除探针/死路用例（08/11-13/17/28/32）保持自包含外，其余用例一律 import `scripts/nxlib/` 的
标准层（stage/new_part/建模装配制图配方），不得把配方复制进用例——`check_repo.py` 会拦截同名顶层
函数；写法与引导样板见 `nxlib/__init__.py` 的 docstring 与 SKILL.md §6。

| 用例 | 文件 | 判决 token | 决定性判据（验收什么；数字为实测值） |
| --- | --- | --- | --- |
| 01 | `01_bracket.py` | `TEST01_DONE` | 基座全流程：草图孔位从辅助线中点读取、种子孔 + 孔口倒圆 + 2×2 阵列（依赖特征一起阵列）、表达式改值后更新；任一 `stage()` 失败打 `TESTxx_FAIL`，不打印成功 token |
| 02 | `02_flange.py` | `TEST02_DONE` | UF 旋转体 + 布尔求和 + 圆周阵列 + 圆角 |
| 03 | `03_bracket_sym.py` | `TEST03_DONE` | 半剖草图拉伸 + 基准平面 + 特征级镜像 |
| 04 | `04_assembly.py` | `TEST04_DONE` | 多部件装配、`ComponentAssembly.AddComponent`、`RootComponent.GetChildren` |
| 05 | `05_modify_existing.py` | `TEST05_DONE` | 打开已有部件改属性后保存（依赖 04 生成的 asm_plate.prt） |
| 06 | `06_drafting.py` | `TEST06_DONE` | 先消隐零件自带基准（`part.Datums` 逐个 `Blank()`，2026-09-23 加），再三视图**内容**断言各 ≥8 个可见对象（消隐后实测 21/20/31）。旧版只断言视图**个数**，三视图全空也照样通过——见 20 号用例与"反向验证记录"一节 |
| 07 | `07_center_marks.py` | `TEST07_DONE` | 一个标记一个 builder（4/4）+ `Centerline2d` ByPoints；同时复测"单 builder 放 ≥3 个 location"（n=3 报 1175305），行为若变会打 `CENTERMARK_MULTI=accepted` + `CENTERMARK_MULTI_CHANGED` |
| 08 | `08_editability_probe.py` | `TEST08_DONE` | 读回 01 的 prt 并断言：特征树非空、表达式全部可读、草图全部 `fully=True`、单实体（实测 26 特征 / 18 表达式 / 2 草图）；不满足打 `TEST08_FAIL <项名>` |
| 09 | `09_fea_static.py` | `BENCH_PASS` | 悬臂梁 SOL101 与手算比值落在 0.9~1.4 |
| 10 | `10_assembly_constraints.py` | `CONSTRAINT_PASS` | `Touch` 约束把销钉解到 z=10 |
| 11-13 | `11…13_api_probe*.py` | （无） | 一次性 API 探针，**不纳入令牌校验**，留作历史证据 |
| 14 | `14_block_boolean.py` | `TEST14_DONE` | 布尔静默失败回归：期望体积 `120000−21³`；token 必须放在 ok 判定**之后**，否则失败运行也会打出成功 token |
| 15 | `15_shell_draft.py` | `TEST15_DONE` | 抽壳移除顶面后 V=23232.000；四侧面拔模 ±5° 与解析式 `120000−64000t+(32000/3)t²` 零偏差 |
| 16 | `16_motion_constraints.py` | `BENCH_PASS` | 等半径圆柱孔面 `Fit` 做转动副：孔轴间距 36.0555 → 0.0000；`Bond` 让销轴跟动（偏差 ≤0.01） |
| 17 | `17_motion_deadends.py` | `TEST17_DONE` | 6 个阶段：圆边 `Concentric` 报 `Solved` 且件移动 25 mm（拖动复验绕轴 12° 自由 / 沿轴 8 mm 被拒、DOF `0T+1R`）、圆柱面 `Concentric` 报 `CannotSolve`、等半径 `Fit` 报 `Solved`、不等半径 `Fit` 报 `InternallyInconsistent`、7 种内部专用枚举 7/7 被拒；任一阶段失败打 `TEST17_FAIL stages=...` |
| 18 | `18_motion_sim.py` | `BENCH_PASS` | 曲柄每帧 1.00000°（指令 360°/s）、摇杆摆角 60.0282°（解析 60.0218°）、每转换向 2 次、反力通路；期望值取自**解析解**；驱动改成 2π 时前三条 FAIL，`CD` 40→50 时只有摆角 FAIL。落盘 `parts\m18_motion.csv`（360 行逐帧曲柄/摇杆转角，不参与判决，供查看与出图） |
| 19 | `19_drafting_annotation.py` | `TEST19_DONE` | 12 个阶段：阵列节距 70/40、字高继承回读 `textSize=5.00`（**故意取非模板默认值**，取默认值会让断言空转）、3 个 UF 关联尺寸、中心标记 / 中心线 / 注释 / 引线、表格单元格回读一致、PDF >20KB；任一阶段失败打 `TEST19_FAIL stages=...` |
| 20 | `20_drafting_views.py` | `TEST20_DONE` | 10 个阶段（2026-09-23 重构）：消隐基准面/轴、`View.Base` 三视图各 ≥4 个可见对象（消隐后实测 5/5/7）、`View.Drawing` 对照组**恰好 0**、删 TOP/RIGHT（`ufs.Obj.DeleteObject`）并把 FRONT 钉到 1:1 (90,158)、2 个投影视图各 7（新建视图必须先 `ufs.Draw.UpdateOneView` 再问，否则 AskVisibleObjects 恒 0）、局部放大锚到俯视图双孔区（比例按 **UF AskViewScale** 2.0 = 2.0 × 父 1.0；.NET `Scale` 属性报自缩放链 2.36，不作核对口径；边界圆 ≈ 选框半对角 0.83 倍，选框须留余量）、放置点超出 A4 图幅必须被拒且不多出视图、图框+标题栏表格、内容页约 33 000 字节 vs 空白页 917 字节、存盘 |
| 21 | `21_drafting_section.py` | `TEST21_DONE` | 6 个阶段：毛坯圆柱面 ≥1（证明孔真的切出来了——实心块剖开也有 `Hatch`，`Hatch` 单独证明不了）、三视图各 ≥10（13/13/14）、不设父视图时 `AddCutSegment` 必抛、剖视图可见对象 18 且 `Hatch` ≥1、**阶梯剖**挂 Top 视图且 `AskSteppedSxline` 腿段 9 > 普通剖 5（`AskSxlineType` 对两者都答 `STEPPED_SXLINE`，腿段数是唯一有效判据）、UF 入口调查 |
| 22 | `22_modeling_extras.py` | `TEST22_DONE` | 13 项：图层读写与类别、`Feature.Layer` **不存在**、`SetState` 往返（只传 int，传 list 会堆损坏）、两个独立基准平面配方、`AlongPath` 两条引导线路线副本质心 y=0 与 y=100（±1e-3）；`DatumCsysBuilder` 是死路，只打 INFO 不做断言 |
| 23 | `23_motion_connectors.py` | `TEST23_DONE` | 14 项：连接件集合真名、三个 `Scalar*` 全不存在、弹簧 `AttachmentType` 实例只读 + `ActionLink.Value` 容器通道、阻尼器补上系数类型后 0→1、衬套不给 `Orientation` 必报 `A NULL value`、`MotionInterference_Struct` 字段恰为 `Solid1/Solid2`、`AskGrueblerCount` 返回整数（实测 7）、`DriverMultiOperations` 恰三项 |
| 24 | `24_shell_mesh.py` | `TEST24_DONE` | 7 项：PSHELL 物理属性表 + 库材质 + 壳收集器可建；`ElementType` 含 `Shell` 且**不含** `ThinShell`（锁住上一轮的错名）；`CQUAD4` 网格节点数 126（断言 ≥4）。只做网格不做求解 |
| 25 | `25_shell_solve.py` | `TEST25_DONE` | 11 项：PSHELL `element thickness` 回读 5.0、204 节点 CQUAD4、端边固支 + 端边 −Z 100 N → SOL101；挠度比 0.9994（`3.090916 / 3.092684`）、von Mises 比 0.9871（`473.83 / 480.0`），期望值来自**独立梁理论**；把壳厚改成 2.5 mm 而理论仍按 5 mm → 比值 7.9803 / 3.8682，两条数值检查 FAIL |
| 26 | `26_hole_package.py` | `TEST26_DONE` | 12 项：`GeneralHole` Ø10×15、`DrillSizeHole` Ø10×15（标签与表达式**同时给**才精确）、`ScrewClearanceHole` Ø11 三种可建且几何读回；不给 `Tolerance` → `Validate` 报 three numbers；`ThreadedHole` **必抛内存访问违例**（边界锁死，用 `SetUndoMark/UndoToMark` 撤残废特征）。⚠ 本用例预期退出码 1 |
| 27 | `27_radius_dim.py` | `TEST27_DONE` | 11 项：按 `Edge.SolidEdgeType` 筛边（`p1==p2` 是整圆）；`CreateRadiusDim(..., ARC_CENTER)` 对倒圆圆弧边与孔口整圆边**都**算出 `computed=10.0000`、文本 `'10'`——直接证伪"圆柱孔必须真圆弧边"的旧记录；直线边必须抛 `The input object is invalid.`；`RadiusDimension` 计数 2 |
| 28 | `28_pattern_helix.py` | `TEST28_DONE` | 18 项：原生 `PatternEnum.Helix` 的实例逐个满足 `z = 节距·θ/2π`、`r=R`（偏差 0.0000），`CountOfInstances` **含种子**，不给轴则静默零副本；路线 B 三种间距标定（`Pitch` 裸数须 `IsPercentUsed=False`、`Span` 均分、默认 `Offset` 按整圈排），超出路径末端的副本被丢弃；末条是原生崩溃探针 |
| 29 | `29_interference.py` | `TEST29_DONE` | 8 项：布尔**交集**当干涉体积 `500.000 mm³`（解析 5×10×10）；分离与面贴面必须被拒（`Tool body completely outside target body.`）且不留空壳；`CreateSimpleInterferenceObject()` 作独立判定来源（相交 → `InterferenceExists` + 2 个 `Face`）；四个零件落盘 >100 KB |
| 30 | `30_fea_descriptors.py` | `TEST30_DONE` | 15 项：从模板抽出描述符全集 11 个，并用独立字面量钉住期望清单**项数**；显示名 ≠ 描述符名（用 `GetDisplayNameOfSolutionType()` / `GetSolverType()` 分别核对），垃圾名报 `Error number: 1775003`（错误文本没有可分辨信息，判据只能靠正对照 + 模板真名）；**新建方案会把"当前激活方案"带走**，显式回切后同一个名字才恢复可用；中性名黑名单三个必拒、白名单两个可建 |
| 31 | `31_drafting_sections.py` | `TEST31_DONE` | 8 个阶段：半剖（L 形三点路径，`HALF_SXLINE`、可见对象 18、`DraftingCurve` 8）、半剖直线两点路径也提交（17 / 7，说明**类型标签认不出路径形状**）、旋转剖（`REVOLVED_SXLINE`、两条腿 4 段、剖到 2~3 个实体）、不设 `RotationPoint` 必抛 `Rotation and bend points cannot be coincident.`（负向对照）、展开剖开关（对象级读数与折叠态全同，只靠两份出图字节数不同区分）、落盘 210181 字节 |
| 32 | `32_pattern_enums.py` | `TEST32_DONE` | 13 个阶段：读 `PatternEnum` 九个成员名；`Polygon` 用解析式逐点核对质心（六边形 6 件、正方形 4 件、`NCopies=4` 时 18 件且角距 19.1066/21.7868 不等——证明实例是沿边等弦长排的，偏差 6e-14 mm）、种子远离轴时布置半径跟着变（12.5）、`NCopies=1` 必被拒（负向对照）；`General` 按目标点映射（3 件偏差 4.4e-15，种子原地不动）、空 `ToPoints` 必抛 `Update undo happened.`（负向对照）；`Reference` 在 3 件线性阵列（节距 30）上把第二种子（y=60）摆成整族 x=0/30/60，`SetBaseInstance(1,0)` 后整族移到 −30/0/30（两次各 6 体，**种子自己兼作基准实例，新增副本只有 2 件**）、`Mirror` 选面成功且 `md.Validate()` 回 `True` 而提交抛 `Feature cannot be mirrored.` 且不留体（负向对照）、`Spiral` 实例读数 r=21.4799/θ=20.5051° 与不给水平参考时抛 `No section curves or points created.`（负向对照）；每种阵列各建独立部件，避免上一次提交失败污染后续属性赋值 |
| 33 | `33_gb_sheet.py` | `TEST33_DONE` | 7 个阶段，**全部经 `gb_drawing` 模块**（除给尺寸/中心线挑边）跑通一张国标图纸：板 100×60×10 双孔 Ø10（间距 44）→ 消隐基准 + 字高/箭头偏好 → A4 第一角图幅 + 25/5 图框（双线宽）→ 三视图按**内容包盒**钉位（FRONT 43..143×177..187、TOP 43..143×95..155、RIGHT 165..225×177..187，AskVisibleObjects 5/7/5）→ 标题栏逐格回读 + 技术要求 TopLeft 对齐并把 `AnnotationOrigin` 钉到标题栏左缘 → 4 个线性尺寸（100/44/60/10，孔半径按面数据复核 5.00）+ 1 条 `2x<O>10` 数量引线（成组等径孔只标一个，GB/T 4458.4），道位 LANE_FIRST/LANE_STEP 从内容包盒推导且**同向小内大外**（44 内道 y85.0 / 100 外道 y78.0，`AnnotationOrigin` 回读断言 LANE_ORDER_OK，红检故意换道即 FAIL）→ 2 中心标记 + 1 ByPoints 中心线 → PDF 38912 字节（文本层 token `2x` 在、44 高于 100）。覆盖的模块级事实：`SetDrawingReferencePoint` 移动的是 plot 内容（逐份 PDF 数值验证）、**同图后续调用抛"Cannot move view off of the drawing"会回滚已成功的移动**、`AskViewBorders` 被标签余量撑大（TOP 边框 141 vs 内容 60，禁止用于布局）、`DraftingDrawingSheet` 无 `Width/Height` 属性、关联类型枚举名是 `END_POINT` 不是 `ENDPOINT`、Note 默认居中锚（`LetteringPreferences.AlignmentPosition` + 后设 `AnnotationOrigin` 才能钉左上角）、NX 表格 2.5 字高下 21mm 列放不下 10 字符日期（溢出画 `#`，列宽改 10/25） |
| 34 | `34_involute_gear.py` | `TEST34_DONE` | 渐开线直齿圆柱齿轮（`nxlib.modeling.involute_gear`，2026-09-25 冷测 T8 配方沉淀）：表达式驱动规律曲线 40 条（压力角参数化——NX12 表达式无反三角）+ ZLaw 显式 Constant（默认缺常量表达式报 "Expression does not exist for law"）+ 齿顶/齿根三点弧 + 径向线 + 全齿闭合轮廓一次 UF 拉伸 + 负向拉伸打孔；z=20/m=2/B=20/孔Ø20 体积与解析齿面积分（扣孔 18238.9 mm³）比 ±2% 带，圆柱面普查 bore=1/tip=20/root=20，`gb_drawing.model_bbox` 走 `ufs.ModlGeneral.AskBoundingBox` 主路线（**ModlGeneral 不是 Modeling**——旧属性名错误会静默落入直边回退、纯回转体无直边即抛 "body has no edges"，T10 发现后修正）对纯回转齿轮给精确包盒，齿顶/齿根弧半径逐 tag 核对，表达式参数链 p_gear_*/p_rp/ra/rf/rb/p_smax 齐全 |
| 35 | `35_assembly_preload.py` | `TEST35_DONE` | 装配子件预载 + 干涉（`nxlib.assembly.preload_components`，2026-09-25 冷测 T2/T10 沉淀）：base(块 40×40×10) + pin(Ø10×20 悬空 5mm 布置) 装配后重开，`preload_components` 收集并 `session.Parts.Open` 预载子件（组件体惰性加载——不预载 SimpleInterference 空跑 inst_bodies=0，T2 实证；已加载子件的 "File already exists" 异常被吞故幂等，二次调用 0 开）→ GetPosition 位姿读回 → 装配上下文实例体 2 个 → SimpleInterference 0 对结果面（悬空负例；⚠ 重合面/零间隙配合会报"接触=干涉"，判材料重叠须布尔交集，见 assembly-drafting.md） |

## 反向验证记录

判定有没有判别力，不靠断言本身，靠"把期望值或承重行改坏 → 重跑 → 看是否真的报 FAIL → 还原 → 校验
文件哈希"验证过。驱动脚本归档在项目侧 `work\`（`redgreen20.py`、`redgreen30.py`、
`nxopen-journal-gate-fix\`）。逐条变异与实测结果：

| 用例 | 变异（几何不动，只改期望值或承重行） | 实测结果 |
| --- | --- | --- |
| 06 / 20 | `View.Base` 换成 `View.Drawing` | 两者都报 FAIL，视图可见对象 0 |
| 20 | 投影视图阈值 4→99；局部放大比例式由乘改加 | 都报 FAIL（比例确实乘在父视图自缩放之上） |
| 21 | 删掉父视图赋值；切点改给图纸坐标；`HATCH_MIN` 1→2 | 三条各自报 FAIL，三处都是承重行 |
| 18 | 驱动速率 360→2π；连杆长度 40→50 | 前者曲柄/摆角/换向三项 FAIL，后者只有摆角 FAIL |
| 19 | 节距期望 70→71；去掉 `SetLetteringPreferences` | 前者 FAIL；后者首轮未报 FAIL（期望取的是模板默认字高 3.5），改取非默认的 5.0 后立刻 FAIL |
| 17 | 圆边 `Concentric` 换成等半径 `Fit` | 该阶段报 FAIL：轴向滑移未被约束（`dz=8.0000`） |
| 14 | 期望体积改成 `120000-21³` | `V=112000.000 expect=110739.0`，判定 FAIL；未改动的副本判 PASS |
| 22 / 23 | 副本质心期望 y=0→50；期望清单漏掉基类 `Tag` | 各有一条 `REG_*=FAIL`，还原后全项通过 |
| 30 | 显示名改假名；回切断言换成恒真 `True`；清单删一项；真名改假名 | 前两条报 FAIL；删清单项首轮未报 FAIL，加独立字面量钉住项数后才报 FAIL |
| 32 | 期望式由"沿边等弦长"改成"等角度均分"（件数不变，只改位置模型） | `polygon_copies_per_side` 报 FAIL（2.0823 mm 偏差）并打 `TEST32_FAIL`；`NCopies=2` 那一档两模型重合，照样通过，说明**判别力来自 `NCopies≥4` 那两档** |
| 32 | 引用阵列的期望式写成"新增 3 件"（把种子自己漏在族外） | `reference_layout` / `reference_base_instance` 报 FAIL 并打 `TEST32_FAIL stages=...`；改成按整族 3 件的 x 偏移核对后通过——判据能分辨"族口径"与"副本口径"两种模型。同一趟里默认档要 0/30/60、`SetBaseInstance(1,0)` 档要 −30/0/30，两档各自通过，说明该参数确实在改变布置而没有被静默忽略 |
| 19 PDF | 对图纸 PDF 与论文 PDF 各跑一次 | 均 `VERIFY_FAIL missing 70,40,R2.,4x` RC=1 |

这几轮踩出来的四条教训：

- **阈值必须取"只有真做了才可能出现"的值。** 19 的继承审计第一版取模板默认字高，去掉 `SetLetteringPreferences` 也照样通过，等于断言空转。
- **覆盖清单型断言看不见自己的覆盖缩水。** 30 从期望清单里删掉一项，断言依然通过；清单旁边必须另钉一个项数。
- **判定结果必须无条件出现。** 06 单独重跑时 `InsertSheet` 与已有图纸重名，异常发生在 `stage()` 之外，日志里既没有 token 也没有 `_FAIL`，检查只能报"缺 token"；现已加顶层兜底与前置检查。
- **先证明模型真建成了，再读它。** 21 的探针 5 面选取出错（`ACT_ERR`）导致孔根本没建出来，当时记下的 16 个可见对象其实来自实心块，带孔实测是 18。

## 已知限制（实测；配方见对应 reference）

**Drafting 视图**（assembly-drafting.md §B.1/§B.3/§B.4）：

- 视图类型用 `StandardViewsBuilder.View.Base`。用 `View.Drawing` 得到的是空视图：`AskVisibleObjects()` 全 0、整张 A4 出图 917 字节；换 `View.Base` 后 13/13/15 个可见对象、出图 2179 字节。与图纸插入顺序无关。
- `AskVisibleObjects()` 只对**当前图纸**上的视图有效，否则抛 `The view is not displayed`；读内容前先 `sheet.Open()`。
- `part.DraftingViews` **没有 `__len__`**（`len()` 抛 `TypeError`），要用 `[v for v in part.DraftingViews]`；`sheet.GetDraftingViews()` 可 `list()`。
- 建 builder 要传**类型化空引用**：`CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)` / `CreateDetailViewBuilder(DetailView.Null)`，传 `None` 报 `Expecting NXOpen.NXObject type, found NoneType`。`NXOpen.Tag.Null` 在本 build 取不到（`module 'NXOpen' has no attribute 'Tag'`），C 侧 `NULL_TAG` 直接写 `0`。
- builder 的**输入属性多半只读，但容器可写**：`ParentViewBuilder.View` / `ViewPlacementBuilder.Placement` 属性只读，其返回的 `SelectObject.Value` 可写（剖视图靠 `ParentView.View.Value = front` 打通）。`DetailViewBuilder.Origin`/`Scale` 未找到容器通道，故局部放大与投影视图走 UF：`ufs.Draw.AddDetailView` / `AddOrthographicView`（父视图标签与图纸坐标是普通入参）；`dvb.BoundaryPoint1` 要 `NXOpen.Point` 对象而非 `Point3d`。
- 局部放大视图的放置点必须在图幅内，出界报 `Input is not a valid parameter`（A4 高 210，放 y=250 报错，y=125 正常）。
- 剖视图配方：`CreateSectionViewBuilder(SectionView.Null)` → `svb.ParentView.View.Value = <父视图>` → `SectionLineSegments.SegmentLocation.AddCutSegment(<模型坐标点>)` ×2 → `SectionLineOnlyPlacementOrigin` + `ViewPlacement.Placement.Value` 给图纸坐标 → `Commit()`。判据：`ufs.Draw.IsSxview` True、剖切线标签非 0、`AskSxsolidsOfSxview` n≥1、可见对象含 `Hatch`。
- 阶梯剖要点：设 `SectionViewType = SimpleStepped`、Z 形点挂**投影面匹配**的父视图、点给模型坐标；完整坑位见 assembly-drafting.md §B.4。
- 剖视图读数**不反映切到了哪个特征**：一块板在两个 Y 各开一个 Ø8 孔，切面放 y=20 与 y=60 两次读数完全相同（20 个可见对象 / 10 个 DraftingCurve / 1 个 Hatch），曲线数只说明模型里有什么。
- UF 包装类的枚举挂在**会话对象**上（`ufs.Draw.ProjDir` / `ufs.Draw.SxsegType`，成员是 `PROJECT_BELOW`、`SXSEG_CUT` 这类全大写名）；`import NXOpen.UF.UFDraw` 不可用，nxopen MCP 索引也没收全 `ufs.Draw` 的 `Create*Sxview` —— 以 `dir(ufs.Draw)` 与 `%NX_HOME%\UGOPEN\uf_draw.h` 为准。
- `RevolveBuilder` 批处理 CommitFeature 内存访问违例 → 用 `ufs.Modl.CreateRevolved`；仅接受凸剖面/开放曲线（references/modeling.md §3.3）。
- Drafting 标注类对象批处理**可**创建，**且不需要 `sheet.Open()`**（自带当前图纸与会话内新建图纸两种配置实测均通过）；`1175307/1175303` 的真因是 `CenterMarkBuilder` 单次提交携带 ≥3 个 location。详见 assembly-drafting.md §B.2，回归见用例 07/19。
- 草图级镜像、草图直调尺寸 API 不可用（references/modeling.md §4.3 坑位表）。
- NX12 无螺纹特征 builder（`Features.Thread` / `CreateThreadBuilder`）→ HolePackage 里**只有三种非螺纹孔可建**（`GeneralHole`/`DrillSizeHole`/`ScrewClearanceHole`），`ThreadedHole` 提交必崩；螺纹用"底孔 + 标注"表达（用例 26、references/modeling.md §4.4）。
- `BlockFeatureBuilder` 的 `BooleanOption` 被静默忽略 → 用 `SetBooleanOperationAndTarget`（references/modeling.md §2.5）。
- STL 批处理导出：选择器用 `SetArray`（不是 `SelectionComp`）即可落盘，无需 `ProcessHoldFlag`；容差成员只有 `ChordalTol`/`AngularTol`/`AdjacencyTol`（**没有 `TriangleTolerance`**），输出类型成员是 `OutputType` 配 `OutputTypeEnum`（**没有 `OutputTypeOption`**），写错成员名会让整批导出中断且一件不落；装配件的几何在组件里，`part.Bodies` 为 0、`ExportSelectionBlock` 也没有 `SelectionScope`，只能按组件逐个导出（`GetPosition` 给位置、`DisplayName` 给原型件名）；STEP 反之需设 `ProcessHoldFlag=True`（SKILL.md §3 坑位 6 与导出节）。
- 批处理会话**出不了位图**：图像捕获 builder 提交后不报错也不落文件，UF 的 `Disp.CreateImage` 直接抛内存访问违例；视图定向与渲染样式可改但没法存图。要位图就走 Drafting 出 PDF、三维几何导 STL 后外部渲染（SKILL.md §3 坑位 6）。
- `ShellBuilder.Tolerance` / `DraftBuilder.AngleTolerance` / `DraftBuilder.DistanceTolerance` 默认 `0.0`，不显式设置必然 Commit 报错（references/modeling.md §3.4）。
- `DraftBuilder.Method` / `StationaryReference` / `StationaryPartingReference` 只读；拔模固定面只能经可写的 `StationaryEntity` 传入**且必须传 Face 对象**（references/modeling.md §3.4）。
- NX Motion：`AskVelocityResults` / `AskAccelerationResults` **静默全返回 0.0**，不可用 → 改用 `AskLinkTransfromForGivenFrame` 取位姿后对角度做差/数值微分（references/motion.md §M.7）。
- NX Motion：`AskNumberOfAnimationFrames` 返回 **NSTEP+1** 帧，第 1 帧已是第一个积分步之后的状态（非 t=0），**末帧与前帧完全重复**（转角差 ~1e-5°）。按步长做运动学判据前必须先剔除重复尾帧（references/motion.md §M.7）。
- NX Motion：`ScalarTorque.ValueExpression` 与无几何 Link 共用**零件长度单位**，mm 零件下按 **N·mm** 解释（N·m 值须 ×1000）；`MassCenter` 必须传 `NXOpen.Point` 而非 `Point3d`（类型不符在 try/except 内会静默失败，质心掉到绝对原点）；`Ixx=Iyy=0` 配 `Izz≠0` 得到非正定惯量张量 → 逆 Z 平面外伪尖峰（references/motion.md §M.3/§M.5）。
- NX Motion：4 转动副的平面四杆**同样是静不定**（6×5−5×4 计数口径为 −2；求解日志会反复打印 `redundant constraint check`），其反力**不可作物理判据**，只能验 API 通路；可信反力须用静定平面刚体动力学模型另解（references/motion.md §M.8）。
- **后训练轮新增的坑位**（逐条在 references 里有实测记录）：
  - 建模：`Features.CreateDatumCsysBuilder` 提交报 `Reference coordinate system undefined`（成员只有 `Csys`，无 `SetOrigin*`）；`Features` 上没有 `CreateSlotBuilder`（连含 `Slot` 的成员都没有）→ 键槽走布尔求差。**孔包**：`HolePackage` **能建** `GeneralHole`/`DrillSizeHole`/`ScrewClearanceHole` 三种孔（孔位靠 `ScRuleFactory.CreateRuleCurveDumbFromPoints` 灌点 Section，目标体在 `b.BooleanOperation`，`Tolerance` 必填，深度走 `EndHoleData.*.RightHandSide`）；**只有 `ThreadedHole` 不可用** —— 标准名给对（`Metric Coarse` + `M10 x 1.5`，来自 `UGII\modeling_standards\nx502_Threaded_Hole_Standard.xml`）、`Validate()` 也通过，`CommitFeature()` 仍**必抛内存访问违例**（五种深度组合全部复现，并把进程退出码污染成 1）→ 螺纹用"底孔 + 标注"表达，见 modeling.md §4.4。
  - 阵列（2026-09-23，回归用例 32）：`PatternEnum` 的 `Reference` 与 `Spiral` 都能经 `PatternFeatureBuilder` 跑出实例——`ReferencePattern.ReferencedPattern` 与 `SpiralPattern.HorizontalRef.HorizontalRefObject` 是**选择对象**（`SelectNXObject`），用 `SetValue(对象, NXOpen.View.Null, NXOpen.Point3d(0,0,0))` 灌入，直接赋值不生效；引用阵列的种子**自己兼作基准实例**（新增副本数 = 件数−1），`SetBaseInstance(i,0)` 把被引用的第 i 件挪到种子位置、整族随之平移。**只有 `Mirror` 走不通**：面选得进、`md.Validate()` 回 `True`，`CommitFeature()` 仍抛 `Feature cannot be mirrored.`（20 组受控提交全部复现，只留种子 1 体）→ 镜像特征改走 `Features.MirrorFeatureBuilder`（用例 03）。配方与实测数据见 modeling.md §3.1e/§3.1f。
  - 装配：干涉检查的 `ClearanceSet` 批处理**不可建**（`ClearanceSetCollection` 只有 `CountClearanceSets`/`DeleteAllAnalysisData`/`FindObject`）→ 改用两条几何路线（2026-09-23，回归用例 29）：①布尔**交集**直接给出干涉体积（搭接 5 mm 的 10 立方体 = 500.000 mm³，分离 / 面贴面被明确拒绝）；②`AnalysisManager.CreateSimpleInterferenceObject()` 给独立判定（`InterferenceExists` + 2 个 `Face` / `NoInterference` + 0）。装配质量属性走 `comp.FindOccurrence(原型体)` + `MeasureManager.NewMassProperties`（见 assembly-drafting.md §A.3）。
  - Motion：`MotionManager` 上**没有** `ScalarSprings/ScalarDampers/ScalarBushings`（真名 `Springs/Dampers/Bushings`）；三种连接件都已打通 —— 阻尼器缺 `CoefficientType = Constant`（`NXOpen.Motion.ConnectorCoefficientTypes.Constant`），衬套缺 `BushingDefine.Orientation` 且它要 **NXMatrix**（取自部件坐标系 `csys.Orientation`，给 Direction 报 `Expecting NXOpen.NXMatrix type`）；builder 上形如 `b.Types()`/`d.AttachmentType()` 的**枚举访问器方法 0 参调用会抛 `NXException: instances of NX enums can not be created` 并当场中断 journal**，枚举一律用模块级类；`ufs.Motion.CreateInterference` 在 Python 绑定下抛 `SystemError`，**批处理无干涉检查入口**（只有 `InitInterferenceStruct()` 可用）；`DriverMultiOperations` 实测只有 EulerAngle1 / PointOnCurve / TranslationZ 三项（另有基类 `Tag`）→ 超出这三种驱动类型须回退 GUI 或运动状态函数。
  - UF 接口形状（SKILL.md §3 坑位 9）：struct 类型是模块级 `NXOpen.UF.<名>_Struct`（`NXOpen.UF.MotionInterference_Struct`，Motion 一族 25 个），`NXOpen.UF.UFMotion` 不可导入；**out 参数（MCP 写 `X@`）是返回值**，`st = ufs.Motion.InitInterferenceStruct()` 必须 0 参调用。
  - 标注：`ufs.Drf.SetOrigin` 按文档签名调用报 `The first parameter passed in was invalid`（表格定位走 `ufs.Tabnot` 路线）；`AddHeaderRow` 是 **3 参**、`MergeCells` **2 参**、`EnableAutomaticUpdate` 是 0 参取值、`ufs.Tabnot` 无 `Sort`；`CreateRadiusDim` **可用**（倒圆圆弧边与孔口整圆边都算出 `computed=10.0000`，直线边按预期被拒，回归用例 27）；FCF/表面粗糙度/孔表的 `.NET` 空对象类在 NX12 不存在（`DraftingFeatureControlFrame`/`DraftingSurfaceFinishSymbol` 取不到 `.Null`）。
  - FEA：BC 描述符的**有效性跟"当前激活解算方案"绑定**（同一批描述符在静态方案下有效、切到模态方案后立刻 `Invalid LBC neutral name`）；实测有效中性名只有 `ComponentForceField`（载荷）与 `UserDefinedDisplacementConstraint`（约束）；模态解算方案描述符是**裸 `"SEMODES 103"`**（`" - Normal Modes"` 后缀的写法不存在），真名从 `%NX_HOME%\SIMULATION\templates\SimNxNastran*.sim` 正则抽取；2D 壳已从"网格级"推进到**求解级标定**（2026-09-22：悬臂壳 vs 梁理论，挠度比 0.9994、von Mises 比 0.9871，反向验证已做）→ 见 fea.md §3a/§3a-2/§6a。
  - 探针写法（SKILL.md 铁律 5/6）：批处理 stdout 全缓冲，硬崩会丢光已 print 的输出 → 每行必须落盘 + `flush()`；把 Python **list** 传给期望 **int** 的 .NET 参数（如 `Layers.SetState([5], 1, 1)`）会让 NX 以 `0xC0000374` 堆损坏退出且无 traceback → **禁止写"猜签名逐个候选调用"的自适应循环**。

## 静态检查

每个 journal 应先通过：

    python scripts\check_journal.py scripts\tests\01_bracket.py

探针文件（故意演示坑位）在文件头加一行 `# check_journal: allow-probes` 可豁免布尔/类型类拦截。

检查器规则 5.16（2026-09-16 新增，反向验证已做）用 **AST** 拦截 journal 解释器是 **Python 3.6.1** 这一事实带来的专属陷阱：`math.dist`/`math.prod`/`math.isqrt`/`math.comb`/`math.perm`/`math.nextafter`、`functools.cache`/`functools.cached_property`、`itertools.pairwise`。用 AST 而非文本匹配是必要的——本技能 `tests/18` 的注释里就写着"不用 math.dist"，文本匹配会把自己的文件误判为错误。
