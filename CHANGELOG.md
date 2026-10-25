# Changelog

本文件记录 `nxopen-journal` 技能的版本变更。格式遵循
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

### Added

- `scripts/nxlib/measure.py`：只读测量模块——面表/同轴分组/孔锥参数、STL 截面面积与 IoU、件间比对；打开部件不保存。
- `scripts/nxlib/measure.py`：`expression_survey` 批量可编辑性检查——逐条命名表达式 ×1.1、DoUpdate、量体积、还原复核，返回 named/live/dead/broken/skipped/alerts/alive_ratio/pass，不保存。
- `scripts/tests/38_measure.py`：新增 `REG_EXPRESSION_SURVEY`（23→24 项）。
- `scripts/tests/38_measure.py`：新增 `REG_UNITS` 并扩展测站自比对（24→25 项）。
- `scripts/nxlib/measure.py`：新增 `functional_hole_groups`（轴向截面内环筛功能孔），`verify_parts` 未给 `ref_a` 时用它作 G2 分母，圆角/凸台/外轮廓转角不计入。
- `scripts/nxlib/measure.py`：`exact_section` 用完按 undo mark 回滚截面特征与临时平面，避免把临时截面留在内存部件里；`scripts/tests/38_measure.py` 新增 `REG_SECTION_CLEANUP`（26→27 项）。
- `scripts/nxlib/measure.py`：`compare_parts` 增加 `applicable`/`verdict`，原件无功能孔时 G2 记 N/A；`scripts/tests/38_measure.py` 新增 `REG_COMPARE_NA`（25→26 项）。
- `scripts/nxlib/measure.py`：新增 `brep_section_iou`/`station_report_hybrid`，`verify_parts` 的面表平面站改用 B-rep 精确截面、轴站仍用 STL，阈值不变；`references/reverse-engineering.md` §4.1/§10.1 同步为“STL 共面切面不作形状判据”。
- `scripts/nxlib/measure.py`：`part_length_scale` 改用 `NXOpen.BasePart.Units`（原 `NXOpen.Part.Units` 与运行时类型不等，曾把所有部件判为 unknown）。
- `scripts/nxlib/measure.py`：`exact_section` 每个环给 `gap`，未闭环缺口汇总为 `open_gaps`，用于区分真实开口与拟合误差。
- `scripts/nxlib/measure.py`：`station_report` 每站增加 `area_inter/area_union/only_a/only_b`，自检可按缺料/多料定位结构。
- `scripts/nxlib/measure.py`：`mesh_bbox` 给 STL 包盒；`compare_parts` 按包盒中心（垂直轴）匹配、逐 pair 判 G2 阈值，`ref_a`/`ref_b` 接原件功能清单。
- `scripts/nxlib/measure.py`：`view_iou` 给 top/front/side/任意法向的轮廓 IoU（三角面投影并集），用于 G5 自检。
- `references/reverse-engineering.md` §2.3：开链缺口大于 2×tolerance 是真实开口，禁止放宽容差闭合；叉/耳双圆柱是两块耳板，不得整宽桥接；低 z 内环高 z 消失的窗口单独切除。
- `references/reverse-engineering.md` §4.2：G2 半径/孔心/轴全对而长度差过渡段时按同轴半径分桶逐段建孔，不用总深单孔。
- `references/reverse-engineering.md` §10.1：自检未过不得交付；按 only_a/only_b 排序修结构，G6 大偏差先修结构再补圆角。
- `references/reverse-engineering.md` §1：结构清单纳入叉/clevis 开口，截面两条平行壁夹开口即按槽建切除体。
- `references/reverse-engineering.md` §1.1：新增结构表模板（证据/成形方式/特征名/自检站）与基体→臂耳叉→孔系→圆角的阶段关卡。
- `references/reverse-engineering.md` §1.5：校核顺序改为结构表→分区形状→双向偏差→体积/包盒；体积分多料与缺料两份。
- `references/reverse-engineering.md` §2.2：放样限定为变截面头部（5–6 张结构站）；整件剪影闭合旋转会把环/腔/槽填实，回转体只旋转功能回转体。
- `references/reverse-engineering.md` §2.2：孔把截面切成两瓣的站按形心射线合成外包裹并取凸包（跳站会削掉凸台外侧瓣，自交截面让放样静默失效）；塔体截面取实测外环，不用整环凸包。
- `references/reverse-engineering.md` §2.2：凸台端面垂直于斜孔轴时，水平截面族收不出端面，按端面截面沿轴拉伸有界棱柱再并。
- `references/reverse-engineering.md` §4.2：沉孔底面是锥面时改“浅孔 + 45° 锥刀”，加实心锥会封孔并零壁厚回滚。
- `references/reverse-engineering.md` §4.2：孔内浮环在大孔径下脱离孔壁致 `Update undo`，改三段同轴孔并绑定主径表达式。
- `references/reverse-engineering.md` §4.2：修边盒按“区域”给大盒会切掉环/肋/根部凸台，只覆盖要修的 0.1–0.2 mm。
- `references/reverse-engineering.md` §4.2：相邻两段放样首末截面来源不同会在接缝报 intersecting faces，同 z 带只用一套来源。
- `references/reverse-engineering.md` §4.2：命名尺寸改后部分特征回滚说明该尺寸未被所有相关面引用，同轴/相邻面一律写成它的表达式。
- `references/reverse-engineering.md` §4.2：底板低 z 站面积偏大归因于板底拔模，按底站/z4 外环放样并另切窗口。
- `references/reverse-engineering.md` §4.2：更新失败定位用 Suppress/Accept 模式 + `ErrorList`（`Length`/`GetErrorInfo`）+ 被抑制特征给出失败点；`FailureOption` 枚举含 Accept。
- `references/reverse-engineering.md` §4.2：孔底锥口切除必须先于底部凹槽环切，扩径后锥体悬空会致父径更新回滚；通孔下延是几何要求，不是回滚解药。
- `references/reverse-engineering.md` §4.2：面表圆柱 `point` 是轴上锚点、`center` 只是 bbox 中心，孔轴按"过 point 沿 dir"建。
- `references/reverse-engineering.md` §4.2：外缘圆柱 `concave=true` 且截面叠图全空是缺口不是凸台，勿建 unite。
- `references/modeling.md` §2.2：拉伸拔模必须先设 `DraftOption`（`SimpleDraft.SimpleDraftType`）再设角度，只设角度静默无效；受控实验修正"批处理下拔模无效"的错误归因。
- `references/reverse-engineering.md` §4.2：面簇 bbox 中心/采样质心不是轴线，轴向以面表 point 或横截面圆拟合为准。
- `references/reverse-engineering.md` §4.2：薄壁贯通切除会静默切成多体（Subtract 成功、体数 2），刀具沿壁留皮保单实体，布尔后校验体数。
- `references/reverse-engineering.md` §4.2：斜结构轮廓以沿特征轴纵剖面 z(r) 为权威，水平站表达不了斜下缘。
- `references/reverse-engineering.md` §7：孔深落进后续锥面切削区时表达式必死，该深度用字面值。
- `references/reverse-engineering.md` §10.1：局部差异先做角度-半径剖面定位方位；测站避开台阶高度伪影，层叠结构按层取截面。
- `references/reverse-engineering.md` §10.1：面表每张平面（含斜平面）的法向站按原件 point/normal 原样复算，不得按台阶伪影剔除或偏移；斜面轮廓端点用相邻平面交线解析求，STL 采样会让位置差远小于 G4 容差却使整面站归零。
- `references/reverse-engineering.md` §4.2：斜轴凸台的轴法向截面偏窄归因于水平截面放样，凸台按孔轴单独成形。
- `references/reverse-engineering.md` §4.2：锥面孔心/长度偏差归因于凸台沿孔轴的厚度与端面。
- `references/reverse-engineering.md` §4.2：包盒极值在臂端时按竖直平面切尖头，不用圆头。
- `references/reverse-engineering.md` §7：倒角刀在扩径超过倒角径向宽度、完全落入孔内时回滚（×1.1 不是固定阈值）；改用随边更新的边倒角或把倒角切在孔前。
- `references/reverse-engineering.md` §2.2：端部最高点取端部截面族最外站，不取中间站。
- `references/reverse-engineering.md` §4.2：孔口/孔底倒角切在孔特征之前，避免倒角刀被扩大后的孔吞掉。
- `references/reverse-engineering.md` §4.2：表达式表里“改了体积不变”的参数是死参数，接上驱动尺寸或删除，否则可编辑性检查判失败。
- `references/reverse-engineering.md` §4.2：水平截面全对、竖直截面在臂端仍缺料 2–4 mm 是放样面尖角下垂，加密截面无效，按垂直臂长的截面沿臂宽拉伸成棱柱再并。
- `references/reverse-engineering.md` §4.2：锥孔孔心/轴取面表 `point/dir`，不从截面圆拟合。
- `references/reverse-engineering.md` §7：G8 存活检查先 ×1.1，抛 `Update undo` 即 broken；参数留 10% 余量，命名不以 `p` 开头。
- `references/reverse-engineering.md` §10.1：自检测站取原件结构分界全集；G5 用 `view_iou`。
- `references/reverse-engineering.md` §1：动手前先出结构清单（原件功能组为建模与自检分母），结构尺寸先建命名表达式再绑定。
- `references/reverse-engineering.md` §10.1：自检分母用原件、功能清单筛 `ref_a`、匹配成功不等于合格、G4 用 STL 包盒。
- `references/reverse-engineering.md` §2.2：有孔分瓣截面凸包只补孔内桥接，外边界取两瓣外包络。
- `references/reverse-engineering.md` §2.2：重采样点数按弦高定（`N ≥ π·sqrt(r_max/(2·tol))`）；端部收口沿用末站量得轮廓，不缩放极值截面。
- `references/reverse-engineering.md` §4.2：俯视 `only_b` 偏大归因于开口被单环放样/凸包填实；包盒偏短归因于收口缩放或末站内移。
- `references/reverse-engineering.md` §10.1：自检结论取整链布尔值（`pass` 且 `unmatched_a` 为空），`pairs` 数不作通过证据。
- `references/reverse-engineering.md` §4.2：低 z 多料→底部让位结构或外圆锥形过渡。
- `references/reverse-engineering.md` §7/§9：尺寸参数化属于交付件；圆角是交付前固定阶段。
- `scripts/tests/38_measure.py`：受控实体测量用例（`TEST38_DONE`）；`RUN_TESTS.bat` 与 `tests/README.md` 登记。
- `references/reverse-engineering.md` §10.1：无外部检查包时的自检闭环（量原件→建→量自建件→比），含面表→结构假设与截面站选择。
- `references/reverse-engineering.md` §2.2/§4.2：腰形凹腔按截面放样切除、端盖 B 曲面按 z 窗口收口，以及耳座圆柱/孔长/锥面/底板/clevis/端盖的症状→动作。
- `references/reverse-engineering.md` §8：孔包入口固定延伸改独立圆柱、锪面孔深校验、入口锥与孔壁分开建。
- `references/modeling.md` §2.1b/§2.3：独立圆柱凸台用 `Origin`+`Direction`、斜耳座绕孔轴回转、孔包延伸与锪面深度。
- `references/modeling.md` §4.2：AutoDimension 不出尺寸的判据改为 AutoConstrain 抢占；`GetStatus()` 只读 dof。
- `references/modeling.md` §4.2b：新增自动尺寸接命名参数配方（`GetAllExpressions` 按 RHS 匹配后改指）。
- `references/modeling.md` §4.3：新增共面堆叠特征表达式起点、倒圆边归属、一进程一次 `FileNew` 三条约束。
- `references/reverse-engineering.md` §4.1：新增 G8 还原残差判据（新会话 ×1.5 复核）。
- `scripts/nxlib/modeling.py`：新增 `make_sketch_dims`；`make_sketch` 注释标注其 AutoDimension 不产尺寸。
- `scripts/tests/37_sketch_autodim_param.py`：新增自动尺寸→命名参数用例（`TEST37_DONE`）；`RUN_TESTS.bat`、`tests/README.md` 登记。
- `references/reverse-engineering.md` §2.1：从 B-rep 批量取精确截面的配方——`SectionFromPlanes`/`SectionFromParallelPlanes`、端点参数用 `AskCurveProps(ct, 0/1)`、闭环用 `JoinType=0` 原始段按端点聚类自建、圆弧只读 `Eval.AskArc`。
- `references/reverse-engineering.md` §2.2：多截面放样路线——重采样参数化（弧长等分/绕形心等角）的选择、放样后体积校验、定位截面、端部收口、拓扑突变与凸台孔闭合的处理。
- `references/reverse-engineering.md` §3：分层路线定位改为“只作测量与核验，不作交付”，交付件走结构特征路线。
- `references/reverse-engineering.md` §4：逆向重建验收项与失败归因——逐站截面 IoU/面积差、孔系半径/孔心/轴向/半角/长度、体积与包围盒、四视图、双向偏差、圆角面数覆盖、单实体/告警/表达式存活、结构语义；验收结果必须由独立脚本从交付件复算。
- `references/reverse-engineering.md` §8：组件闭合与切除边界规则——端部形状进末截面、切除边界取实测面、孔独立切除体、堆叠层各用各的截面、切除刀具穿过目标面、布尔顺序。
- `references/reverse-engineering.md` §9：圆角阶段——圆角地图（半径组→边链→预期面数）、按组选边（exact/ring）、主组覆盖 ≥70%。
- `references/reverse-engineering.md` §10：测量链——一次探针取全量事实、按结构分界布置测站、特征分组、确定性序列化、边界目录。
- `references/modeling.md` §1.11：会话/部件设置入口（`NXOpen.Preferences` 子模块、`session.Preferences.Modeling.BodyType`）。
- `references/modeling.md` §2.1b/§2.2b：斜轴圆柱/锥孔切除与多截面放样配方。
- `references/modeling.md` §2.5：切孔按面表验收（核对新增面的半径/半角/孔心），失败布尔用 undo mark 回滚。
- `references/modeling.md` §6：特征按结构划分，不按层划分。
- `references/modeling.md` §4.3：非 XY 草图平面只能靠 `Sketch.Reattach`（`PlaneReference` 在 NX12 批处理里被忽略，`AttachPlane` 仍是 XY）；任意法向/过任意点的基准面用 `DatumPlaneBuilder.SetPointAndDirection`，参考轴用 `FixedType.Z`。
- `references/modeling.md` §4.2/§4.3：实测轮廓只加 `CreateFixedConstraint`（`CreateFullyFixedConstraints` 静默无效）；AutoConstrain/AutoDimension 会挪动几何（小 R3 弧被拉到自交，2 507→956 671 mm³）。
- `references/modeling.md` §4.3：`RevolveBuilder` 对草图截面报 `memory access violation`，改用 UF `Modl.CreateRevolved`。
- `references/modeling.md` §4.4：沉孔 HolePackage 配方（`GeneralHoleForm=HoleForms.Counterbored` + `GeneralCounterboreHole*` + `GeneralCounterbore*`），受控实验与解析值一致；直径/深度可传表达式名。
- `SKILL.md` §3：`SaveAs` 到已存在路径报 `File already exists`，阶段件写新路径或先删目标。
- `references/reverse-engineering.md` §2.2：等截面判据量化（底/中/顶三站面积差 ≤2% 且轮廓重合），面积随站位单调变化即按底站与中站分段成形，不用中间轮廓拉整厚。
- `references/reverse-engineering.md` §4.1：阶段门与自检站是阻塞条件，低于阈值不进下一阶段、不带低站交付。
- `references/reverse-engineering.md` §4.2：包盒单方向大 0.3–1 mm 且极值在凸角归因于未建倒圆/倒角，补局部倒角而非整件倒圆。
- `references/reverse-engineering.md` §7：公式型表达式被逐项改数值的存活检查跳过、存活率到不了 1.0，交付件命名表达式一律写数值。
- `references/reverse-engineering.md` §8：孔壁长度比原件长 0.5–1 mm 的整倍数归因于入口倒角未切，先建倒角再复测，不缩孔深。
- `references/reverse-engineering.md` §2：解析边界（圆角/圆孔/圆弧外缘）用精确圆弧 + 直线建截面，不按采样点逐段建线；判据是面类型直方图里圆柱/圆锥/B 曲面占圆弧边界。
- `references/reverse-engineering.md` §10.1：交付前数拓扑（曲线数、面类型直方图、面数比原件），构造线删掉或隐藏；平面占八成即折线化。
- `references/modeling.md` §2.2b：N 点折线是放样输入不是交付边界，放样后按面表半径重建解析圆弧。
- `references/reverse-engineering.md` §2：裸曲线轮廓的长/宽/圆角是静默死参数，改草图 + 驱动尺寸或特征化几何；拉伸后不删父曲线。
- `references/reverse-engineering.md` §4.2：圆角/切角参数用体积 + 角部圆柱/环面半径复核，不用包盒。
- `references/reverse-engineering.md` §7：表达式名禁用 `p`/`P` 前缀（大小写都算），与自动表达式 `p0`/`p1` 同前缀会被可编辑性检查一并过滤。
- `references/reverse-engineering.md` §10.1：圆锥组按 (轴, 半角) 分桶，圆截面放样把一个锥面拆成多组同轴锥；先改单段直线剖面回转或单个圆锥体再比孔锥参数。
- `references/reverse-engineering.md` §10.1：站表从面表生成（水平平面族、孔轴端点/中点/法向站、臂轴 0/0.5/1），只取 z 站的子集自检与整门结论相反。
- `references/reverse-engineering.md` §10.1：每类失败只重建一次，非功能多出面不计缺陷，几何与结构门做齐后再评估圆角；`THRU_CURVE` 告警同样算 G8 失败。
- `references/modeling.md` §1.7：参数命名不用 `p`/`P` 前缀，判据交叉引用 `reverse-engineering.md` §7。
- `references/reverse-engineering.md` §9：交界交线平均段长 <1 mm 时 `EdgeBlend` 三种失败（终止/应用/滚过尖边）；根部 flare 放进末截面或先合并切向面。
- `references/reverse-engineering.md` §2：耳/眼端部按双瓣截形建——矩形块 + 两肩倒 `R_EYE`、平台半宽 `W_HALF = H_LOBE + R_EYE`、端面整圈 `R_END` 得环面。
- `references/reverse-engineering.md` §2：锥孔收敛方向按沿孔轴 ≥3 站的半径 `r(s)` 符号定，起刀面取外端面、轴向起止取面表区间两端。
- `references/reverse-engineering.md` §2：拔模窗口起剖面取中面外偏 `h/2·tanθ`；口部圆角在减料后加，先下口后上口。
- `references/reverse-engineering.md` §2：重复结构先在规范坐标系建一件，其余方位按量得旋转角与平移量复制同一特征。
- `references/reverse-engineering.md` §2：扇环窗口端壁按两端角弧中心连线建，两端角弧半径可不同。
- `references/reverse-engineering.md` §2.2：耳座由“绕耳孔轴回转圆柱”改为“双瓣截形”；孔座圆柱只代表孔口包络。
- `references/reverse-engineering.md` §4.2：新增四条症状→动作——端壁差 0.5–1 mm、中截面系统偏小、锥孔方向反、重复结构仅一个方位对上。
- `references/reverse-engineering.md` §7：公式型表达式保留为系统式，每个结构尺寸另给数值参数入口；新增按体拆名、×1.1 面数不变、位置量不列表达式三条。
- `references/reverse-engineering.md` §10：B 曲面（类型 43）的 `AskFaceData` 参考点恒为 (0,0,0)，区域筛选用 `box` 与邻接边。
- `references/reverse-engineering.md` §10.1：标题改为“测量与比对”，闭环措辞改为核验/比对，去掉“无外部检查包”前提。
- `references/reverse-engineering.md` §2.1/§2.2/§4.1/§4.2/§8/§9：去掉过程读数与零件量值，保留判据、配方与症状→动作。
- `references/reverse-engineering.md` §4.1：单轮验收的过程叙述改写为门判据与阻塞规则。
- `references/modeling.md` §1.7：一个表达式只驱动一个结构/一个体，多个体共用同一名字时按体拆名。
- `references/modeling.md` §2.2：新增拔模拉伸的起剖面偏置 `h/2·tanθ`，中面截面作验收站。
- `references/modeling.md` §2.4：新增双瓣耳（块 + 两肩倒圆）与口部圆角先下口后上口的顺序。
- `references/modeling.md` §4.2b：新增系统式保留、位置量用字面值两条。
- `references/modeling.md` §2.1b/§2.2b/§4.2：受控实验措辞改验收值，删放样读数。

- `references/reverse-engineering.md` 文件头：新增按阶段跳转的索引（结构表/测量/成形/归因/收尾分别读哪节）。
- `references/reverse-engineering.md` §2：双瓣耳与拔模窗口改为逆向判据 + `modeling.md` 指针；锥孔方向并入带拔模拉伸。
- `references/reverse-engineering.md` §2.1：删与精确截面重建重复的平滑重建条。
- `references/reverse-engineering.md` §2.2：剪影/等截面、外环/凸包、端部收口、多闭环、端部截面族、截面叠图各并为一条；放样提交校验指向 `modeling.md` §2.2b；门站条归 §4.2。
- `references/reverse-engineering.md` §3：约束由 8 条压到 4 条，Tag 识别移 `modeling.md` §2.5。
- `references/reverse-engineering.md` §4.1：门阻塞与冻结阈值并为一条，证明路线与 G9 并为一条。
- `references/reverse-engineering.md` §4.2：按基体/臂耳/孔系/圆角参数四组归并，40 条压到 24 条。
- `references/reverse-engineering.md` §7：按体拆名、位置量、共面堆叠三条归 `modeling.md`，公式型表达式改为交付判据。
- `references/reverse-engineering.md` §8：组件门站/region、孔包入口/入口锥、孔表/独立切除体各并为一条。
- `references/reverse-engineering.md` §10.1：分母/功能清单、匹配/整链布尔、截面站/站表各并为一条，删重复的验收条。
- `references/modeling.md` §2.2：接收拔模 `MultiDraft` 配方。
- `references/modeling.md` §2.2b：合并重叠/体数断言并入合并条，补 intersection gaps 折线减点与封口面错开 0.1 mm。
- `references/modeling.md` §2.3：新增锥底沉孔 45° 锥刀配方。
- `references/modeling.md` §2.5：新增布尔目标/刀具按 Tag 识别。
- `SKILL.md` 路由表：逆向重建描述改为“结构表→测量链→按结构建特征→验收门”，构造配方指向 `modeling.md`。
- `references/reverse-engineering.md` §1.1：清单与站表互查（每张站写出负责结构，写不出即补结构行）；同阶段主结构先建全再逐个修门。
- `references/reverse-engineering.md` §4.1：验收基准为原件本身（站表按 §10.1 生成、阈值取默认档），任务无容差时按默认档执行；交付说明逐门列 PASS/FAIL，缺结构补建。
- `references/reverse-engineering.md` §4/§4.2/§10：删“阈值按任务确定”“铸件放宽 5%”“阈值与零件类型不匹配即改阈值”三处自定口径，结果不符先查测量口径与站表。
- `references/reverse-engineering.md` §10.1：站表按每个结构自身轴取根/中/端、开口/槽取槽底与两端，不按全局三轴枚举。
- `references/reverse-engineering.md` §10.1：一次性重建限缩为数值项，结构缺失回清单补建。
- `scripts/nxlib/measure.py`：`mesh_deviation` 给双向面积加权点—面 RMS/P95（精确点到三角面距离、均匀网格索引、固定 seed）；`station_plan`/`station_report` 从面表平面族与圆柱/圆锥轴生成测站并逐站复算；`verify_parts` 汇总 G0–G6；`measure_part`/`compare_parts` 增加单位与毫米换算。
- `scripts/nxlib/measure.py`：新增 `exact_section` 从 B-rep 取截面曲线并按端点串成闭环；`station_plan` 的预算改为先保留平面族、再按半径保留轴中点/端点，`dropped`/`complete` 明示未测边界；`compare_parts.pass` 只要求原件功能组全匹配，`strict_pass` 才要求双向全匹配。
- `scripts/tests/38_measure.py`：新增 B-rep 截面面积与测站预算断言（21→23 项）。
- `scripts/tests/38_measure.py`：新增采样复现、已知 2 mm 平移偏差、偏差自比对、自动测站自比对与 `verify_parts` 自比对 5 项断言（15→21 项）。
- `references/reverse-engineering.md` §10.1：新增 `verify_parts` 通用几何门汇总与 `mesh_deviation`/`station_plan` 用法。
- `references/reverse-engineering.md` §4.1：G6 由相对比例改为双向 RMS ≤0.8 mm、P95 ≤1.8 mm。

### Changed

- 用例计数 37→38、gate 34→35、`nxlib` 五域→六域（`SKILL.md`/`README.md`/`tests/README.md` 同步）。
- 逆向重建交付路线改为结构特征优先：组件按自然成形方式建（回转/拉伸/放样/布尔/阵列），特征数与结构数同量级；验收新增结构语义（无逐层拉伸堆栈、每个结构可单独修改），与几何验收同时通过。
- 截面验收由“覆盖组件与平面族”收紧为“每站 IoU ≥0.95、面积差 ≤5%”。
- `references/reverse-engineering.md` §4.1/§10.1、`references/modeling.md`：G 编号退为机器键，验收表与正文改用具体指标名（单实体可读、截面轮廓重合度、圆柱/锥面参数一致性、体积相对差、包盒位置与尺寸差、四视图投影重合度、双向表面偏差、圆角覆盖、表达式可编辑性、特征树结构）；§4.1 的 G5 原写“同站截面”，与 `verify_parts`/冻结 QA 的四视图 G5 不一致，改为“四视图投影重合度”（top/front/side/iso 轮廓 IoU ≥0.99），逐站截面仍由“截面轮廓重合度”把关。
- `references/reverse-engineering.md` §4.1：增加指标适用条件——原件无功能圆柱/锥面或圆角时，圆柱/锥面参数一致性与圆角覆盖记 N/A，不记失败；补充包盒位置与尺寸差（整件全局包盒）和双向表面偏差（缺料/多料双向 RMS/P95）的说明。
- `SKILL.md` 路由表中的逆向重建描述改为“原件+一句重建要求→测量链→截面/放样→切除→验收项”。

### Fixed

- `references/modeling.md` §4.4：HolePackage 类型属性是 `Type`（可写），`Types` 只读；孔向默认 `FaceNormal`，接缝处需显式切 `ProjectDirectionMethod=ProjectionOptionsDirectionType.Vector`。
- 截面端点参数与闭环提取：端点用 `AskCurveProps(ct, 0/1)`，闭环用 `JoinType=0` 原始段按端点聚类自建。
- 布尔顺序：切除刀具穿过目标面，补孔排在整圆盘并集之后。
- 圆角选边改用 exact，避免 ring 带入曲面缝边。
- 孔轴判读、堆叠层截面、凸台顶面与板顶面的区分。

## [1.2.0] - 2026-10-20

### Added

- `references/reverse-engineering.md`：新增逆向重建域——自然坐标系与截面策略、逐层闭合草图拉伸、孔系/凹槽后置切除、双向点-三角面偏差校核与验收阈值、重建件后续修改。
- `references/reverse-engineering.md` §2.1：从 B-rep 批量取截面曲线的 UF 配方（`SectionFromPlanes`/`SectionFromParallelPlanes`、PascalCase 结构体、平行面等距语义、`ModlGeneral.AskCurveProps` 采样）。
- `gb_drawing.save_model_view/base_view/set_cjk_font`：命名模型视图、从模型视图建基本视图（落在图纸原点，定位由调用方完成）、中文字体一键设置。
- `gb_drawing.dim_text_box` / `box_overlap`：尺寸文字框估算与重叠判定（标注布点）。
- `references/gb-drawing.md`：非轴对齐零件的出图配方（自定义模型视图 + `BaseViewBuilder.SelectModelView`，含第一角三视图矩阵）与中文字体 `chinesef` 加载配方（`FontCollection.AddFont` + `Lettering.Cfw.Font`）。
- `references/gb-drawing.md`：视图样式 builder（隐藏线/虚拟交线/平滑边默认值）与 Tabnot 行数 = `len(row_heights)` 的事实。
- `references/gb-drawing.md`：图框与自定义表格线可用 `part.Curves.CreateLine`（`sheet.Open()` 后）。
- `references/gb-drawing.md`：最小调用骨架补 `set_cjk_font`，调用顺序同步更新。
- `references/drafting-annotation.md` §6：最小 2×2 表格配方（默认 5×5 清空、行列重建、逐格关自适应、回读）。
- `references/drafting-annotation.md` §6b：球标（`CreateIdSymbol`）完整配方——第 7 参为 `NXOpen.UF.Drf.Object` 结构体、PascalCase 字段、枚举传成员、入口是 `ufs.Drf`。
- `references/drafting-annotation.md`：尺寸不走 .NET 的判据（`part.Dimensions.Create*Dimension` 无头崩溃、.NET builder 报 `Unable to infer a dimension type`）；FCF/粗糙度/孔表 builder 入口存在但配方未打通。
- `SKILL.md` §3：批量导出 STEP 写出 0 实体时的 Parasolid 回退（`ufs.Ps.ExportData`，`.x_t` 回读验证）。
- `references/fea.md` §0a：`.fem`/`.sim`/理想化件的显式保存配方（`fem.Save`、`fem.IdealizedPart.Save`、`sim.Save`）与显示部件陷阱。
- `references/assembly.md` §A.2：`Fix` 约束创建配方（引用对象为组件自身，DOF 读回 `0T+0R`）。
- `references/drafting.md` §B.4：视图自动命名规则（`Right@1`/`ORTHO@4`/`SX@5`/`DETAIL@7`）与 `SetName` 改名/查找方式。
- `scripts/check_repo.py`：新增第 7 组 ROUTE 检查——域文件禁新开坑位清单/坑位表，负面断言必须带做法，跨域高发陷阱限 `SKILL.md` §1。
- `scripts/check_repo.py`：CONCISE 词表补充过程叙述与历史指代类词汇。

### Changed

- 工程图三文件按权威分工去重：标注规则（道位/字高/`<O>`/中心线/球标/表格）统一到 `references/drafting-annotation.md`，`references/drafting.md` 只留视图/PDF 与坐标映射，`references/gb-drawing.md` 只留模块专用行为与 GB 条款映射。
- `SKILL.md` 路由表增加逆向重建域；`references/assembly-drafting.md` 按域拆为 `references/assembly.md`（§A 装配）与 `references/drafting.md`（§B 工程图），域文件计数改为八个；节号保持 §A.x/§B.x，交叉引用同步更新。
- 文档治理：`SKILL.md` §1 声明为唯一跨域高发陷阱清单，§3「通用坑位」改名「通用 API 路线约束」，§7 落位规则与增长纪律改为「负面事实内联、不新开坑位清单」。
- 坑位表按路线内联：`references/modeling.md` §4.3 草图 API 不可用项、`references/motion.md` 坑位对照、`references/drafting-annotation.md` §9 对照表并入对应路线；`references/drafting-annotation.md` §8 反模式清单改为正向出图验收清单。
- `scripts/tests/README.md`：删除「已知限制」与「新增坑位」两节，改为「配方归属」指针，配方权威统一到 `references/*.md`。
- `references/modeling.md`：删除 §7 整机示例沉淀，章节范围改为 §2-§6。
- 全仓 agent 文档与脚本注释去除日期戳与历史指代（`scripts/tests/*.py`、`nxlib`、`render`、`gb_drawing.py` docstring）；脚本注释保留 API 失败原文。
- `references/gb-drawing.md`：标注文字必须落在轮廓外的空白图纸上，补 `dim_text_box`/`box_overlap` 布点与渲染复核配方；注明 `dim_diameter` 的 `text` 形参不生效；成图前把未请求的 `CenterMark` 全部隐藏。
- `references/gb-drawing.md`：视图级简化配方（`AskVisibleObjects` + `DraftingCurve.GetDraftingCurveInfo().GetParents()` + `DependentDisplay.Erase`），并记录按 `Intersection` 全删会断开轮廓的判据。
- `references/fea.md` §8：峰值应力落在孔口/锐边时补 3~5 个测点作强度判据，峰值只列出不判定。
- `references/motion.md` M.9：明确 `run_journal.exe` 只接收 `.bat` 传入的 journal 路径，不转发额外参数。
- `references/drafting-annotation.md` §5：删除与代码块内注释重复的 `NumberOfLeaders` 前置告警。

### Fixed

- `references/gb-drawing.md`：补充文字控制字符坑位（`×` U+00D7 触发 locale 报错、`~` 被当控制符、`Ø` 写 `<O>`）与标题栏日期列溢出处理。
- `references/modeling.md` §4.2：自动标注 API 名更正为 `NXOpen.Sketch.AutoDimensioningRule` 与 `NXOpen.SketchAutoDimensionBuilder.DimType`（原写法 `AutoDimensionRule` / `Sketch.AutoDimensionBuilder.DimensionType` 在 NX12 Python 封装中不存在）。
- `scripts/render/condition.py`：比例尺按裁剪后的缩放因子计算（原式用裁剪宽/原画布宽，比例尺偏短）。
- `scripts/tests/README.md`：14 号体积期望改为 `120000−20³`（112000），与用例一致。
- `scripts/tests/verify_check_rules.py`：每条反例除退出码外还断言输出命中对应规则痕迹，防止被另一条规则误拦截而静默通过。
- `scripts/check_journal.py`：重复的规则编号 5.19 改为 5.20；修正 `ENUM_ACCESSOR_PROPS` 拼写与 `HoleDepthOptions` 的文件指向。
- `scripts/check_repo.py`：PY36 组覆盖 `scripts/render/export_stl.py`；`.github/workflows/ci.yml` 增加 `verify_check_rules.py`。
- `scripts/run_journal_batch.bat`：workdir 传入文件时显式报错退出，不再静默回落到调用者 CWD。
- `gb_drawing.standard_views`：`size` 必须显式传入，避免 A3 图纸按 A4 排版；`model_bbox` 回退直边时打印警告。
- 文档一致性：`SKILL.md` 的 gate token/崩溃探针顺序/文件清单、README 的坑位表表述、`gb-drawing.md` 的未覆盖范围与 API 签名、`drafting*.md` 的视图落位偏差表述、`motion.md` 的交叉引用。
- `references/reverse-engineering.md` §2.1：结构体名经 NX12 批处理探针复核（`NXOpen.UF.Curve.SectionGeneralData` / `SectionPlanesData` / `SectionParallelData`、`NXOpen.UF.ModlCurveFitData_Struct`）。
- `references/drafting.md`：球标示例的 `AssocDwgPos` 改为 2 个 double；该字段运行期对长度 3 报 `Array length mismatch`。
- `references/modeling.md` §5：`AskFaceData` 返回字段更正为 `(type, point, dir, box, radius, rad_data, norm_dir)`。
- `scripts/check_journal.py`：`CylinderBuilder.Diameter/Height` 的修复提示改为 Expression 通道（NX12 无 `SetDiameter`/`SetHeight`）。

## [1.1.0] - 2026-10-19

### Added

- Motion 滑动副配方（`JointDefine.Type.Slider`，两组几何、关节局部 z 轴）与 36 号回归用例（偏置曲柄滑块，解析偏差 0.0013 mm）。
- Motion 齿轮连接件配方（`Couplers.CreateCouplerGearBuilder`，60 r/min 输入 → −30 r/min 输出）。
- `nxlib.modeling.involute_gear` 增加可选轮毂参数 `hub_d` / `hub_len` / `z_offset`，34 号用例覆盖体积增量。
- `gb_drawing.assembly_bbox(bodies)` 多组件包盒；`tech_note(..., base_y=)` 避开明细栏。
- `check_journal.py` 规则 5.19（`NXOpen.UF.UFDrf` 伪容器）与 `from math import dist` 形式的 Python 3.6 检测。
- `nxlib.testing.write_log()`：用例日志落盘（18/36 号此前日志恒为空）。

### Changed

- `references/motion.md`：补齐公共导入与 `set_expr`/`VC`/`RF` 约定；M.6 修正为 0 基帧模型（帧 0 = t=0），删除"首帧非 t=0 / 末帧重复或归零"的误判；M.7 按旋转轴给角度元素表并补线速度配方；M.5c 明确 `MotionTranslationZ` 沿关节局部 z 轴、正速度沿 −z。
- `references/motion.md`：澄清 Euler 驱动正值绕 +Z 为顺时针、`frame k ↔ t=k·T/nstep`、`atan2(R[1,0],R[0,0])` 只给相对设计位姿角（绝对角走 §M.4）、journal 内无 numpy（差分与 unwrap 手写）。
- 文档精简：`SKILL.md`、六个域文件与 `scripts/tests/README.md` 删除验证过程、日期、历史沿革和重复解释，只保留结论、配方与判据；`README.md` / `README.en.md` 去掉会随文档变动的实测计数，改为稳定的能力描述。
- `README.md` / `README.en.md`：孔包覆盖改为三种非螺纹孔型（螺纹用底孔+标注）；Motion 覆盖补滑动副与齿轮连接件；前置条件中的用例数改为 33 个带判定的用例。
- README 运动图按 0 基帧模型重新生成（720 步、721 帧；摆角跨度与解析解相差 0.0014°，换向 2 次）。
- 维护规则：新知识按“结论/做法”模板入库，禁止日期与过程叙述；`check_repo.py` 新增 CONCISE 组自动拦截，并保留“先合并后追加”的增长纪律（不设体积硬上限）。
- `references/assembly-drafting.md`：移动副改用两组平面 `Touch`；补轴环 + `Touch` 去轴向滑动；约束枚举补全并标注 `ValueOf` 非成员；`Matrix3x3` 字段组语义明确为局部轴分量。
- `references/gb-drawing.md`：导入骨架改为绝对路径插入 `sys.path`；装配图尺寸增加 PDF 文本层数值复核硬步骤。
- `references/reverse-engineering.md` §2.2：端部耳座沿臂轴先鼓后收，等分站插值会削平鼓包（150 站少 27%）并被孔座圆柱顶替；耳座按孔轴截面族放样，孔座圆柱只代表孔口包络。
- `references/reverse-engineering.md` §4.2：自检站 IoU < 0.5 归因为结构缺失（端部/耳座/槽/孔），按结构补建而不是调截面。
- `references/reverse-engineering.md` §10.1：交付前逐组件比轴向投影极值，差 >1 mm 即端部缺失或外推。
- `references/reverse-engineering.md` §2.1：重建轮廓直接取 B-rep 精确截面段（线/弧判定、样条拟合到 0.02 mm、圆心投影保证端点相接），不从 STL 重采样。
- `references/reverse-engineering.md` §2.1：批处理打开刚生成的 prt 报 `File already exists`，改从另一目录打开副本或先开原件。
- `references/modeling.md`：补相切工具体布尔失败；新增 §3.7 渐开线齿轮标准层入口。
- `references/drafting-annotation.md`：剖视图 placement origin 与内容中心的偏移说明。
- `nxlib.modeling.expressions` 增加 `unit_name` 参数，角度表达式可传 `"Angle"`（默认仍为 `"Length"`）。

### Fixed

- `RUN_TESTS.bat` 第 102 行 `exit /b 1call :gate 34...` 拼接，导致 34 号从未执行却仍打印 `ALL TESTS PASSED`。
- `check_repo.py` 覆盖正则未锚定行首，把上述畸形行误算为已覆盖。
- `gb_drawing.map_point` 在 `MapModelToDrawing` 失败时静默返回 `ref + xyz`，忽略投影与比例，导致尺寸/包盒静默错位。
- 球标 `CreateIdSymbol` 第 7 参必须为 `NXOpen.UF.Drf.Object` 结构体；文档原写法直接传 Edge 必失败。
- 装配实例边 + 剖视图上的线性尺寸可能静默读错（200→200.2、140→136.3），已写入复核要求。
- Motion 帧索引口径：`AskLinkTransfromForGivenFrame` 为 0 基（0..nfr-1，帧 0 = t=0）；修正 18/36 号用例与文档中"首帧是 t=dt、末帧重复"的误判（此前按 1..nfr 遍历，越界索引返回值被误读）。18 号用例的 CSV 同步改为 0 基并增加 `time_s` 列。
