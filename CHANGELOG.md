# Changelog

`nxopen-journal` 技能的版本变更记录。

格式遵循 [Keep a Changelog 2.0.0](https://keepachangelog.com/en/2.0.0/)，版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。
记录从 1.1.0 起；1.0.0 见 `git tag v1.0.0` 与对应 GitHub Release。

## [Unreleased]

### Changed

- 内部：`verify_check_rules.py` 补 5.9 布尔设置反例与形状 `Type`、`BooleanType.Create` 阴性对照。
- 许可：`LICENSE` 版权行补仓库地址，新增 `NOTICE` 与 `TRADEMARK.md`（MIT 条款不变）。

### Fixed

- `check_journal.py` 5.9：`BlockFeatureBuilder` 的形状 `.Type` 不再误报。
- `check_journal.py` 5.9：新增 `BooleanOption.SetBooleanOperationAndBody` 检测。
- `check_journal.py` 5.9：去掉命中后的 `break`，后续布尔误用不再被前面的形状 `Type` 掩盖。
- `check_journal.py` 5.9：builder 识别改为按词法作用域，同名变量不再跨函数误判。
- `check_journal.py` 5.9：`BooleanOption.Type = ...BooleanType.Create` 不再误报。

## [1.7.0] - 2026-11-19

装配图补齐 GB 序号、剖视与标题栏。

### Added

- `scripts/gb_drawing.py`：新增 GB 装配图要素——完整标题栏（180×56）、圆形序号球与引线、中心标记、装配剖视、装配图完整性门。
- `references/gb-drawing.md`：补装配图调用骨架、函数表与边界。

### Changed

- GB 出图线宽统一：图框、标题栏、明细栏 0.7→1.4（PDF 0.25→0.5 mm），内框 0.25 mm；尺寸线、箭头、尺寸界线、序号球线宽统一 0.25 mm。
- GB 出图偏好设置清空剖视标注的 `SECTION` 前缀，出图标注为 `A-A`。
- 展示图迁出本仓库，移交 `nxopen-journal-toolkit` 的 `docs/images/`；本仓库删除 `images/`，README 只保留入口。
- MCP 文档：语义检索改为外部嵌入服务（`bge-m3` + `bge-reranker-v2-m3`），依赖网络；服务不可用时按名核实。
- MCP 文档：补中文夹英文查询写法与 `get_class` 分页说明。

## [1.6.0] - 2026-11-17

运动与装配能力补齐，交付件链统一。

### Added

- 运动：Fit 铰可拖动、轴向滑动、`1T+1R` 枢轴、UF 四参速度/加速度、齿轮副、Screw+Cylindrical 导程耦合、14 种关节 DOF 读数。
- 装配：嵌套子装配预载、组件阵列份数、`MoveComponent` 增量、`Fix` + 两平面 `Touch` 滑块。
- 交付件链：STL 拓扑（水密、绕向、体积、欧拉数）统一实现；`import_step(target="work")` 在实体数未增加时用 `UF_PART_import` 兜底。

### Changed

- GB 三视图按第一角摆位（RIGHT 在 FRONT 左侧、TOP 在下方），钉位后逐视图校验内容框不越图框；新增装配图 `bbox=`。
- 交付件门收紧：PMI 门只接受实体类型名，传值类型直接报错；支撑面宽度改为构建警告。
- STEP 导出的 `annotations=None` 跟随 PMI；显式只开 PMI 时打警告。

### Fixed

- 中心标记改用面心。
- `DragByTranslation` + `Solve` 不回收越界位移，改用 `MoveComponent` + 重建网络求解；滑块路线补 `Fix(导轨)` 前提。
- 批处理包装器隔离 `run_journal` 的 stdin，DEX 转换失败时不再永久挂死。
- 修复 `import_step` 在部分安装上返回 0 实体工作件。

## [1.5.0] - 2026-11-05

交付件验证层落地，各门与文档口径对齐。

### Added

- 交付件验证层：STEP 实体普查（solid/face/edge、NAUO、PRODUCT、PMI 子类型、悬空引用）、STL 拓扑、DXF 布局感知统计、三轴占用门、图纸 PDF 文本层审计。
- 宿主侧入口：`check_deliverables.py` 汇总 STEP/STL/DXF/PMI/占用/PDF 判决；`run_journal_checked.py` 检查输出标记；`api_index.py` 三源 API 索引。
- `references/verification.md`：交付件验证域文件。

### Changed

- 判决三态 `PASS`/`FAIL`/`NO_SIGNAL`；PDF 文本层默认阈值 20→3 词。
- STEP 导出配方：`InputFile` + `ObjectTypes.Solids=True` + `ProcessHoldFlag`；AP214 用 `ugstep214.def`，AP242 不设 def。
- 支撑面宽度门槛统一为 `R + 0.5`；开环截面判 FAIL。
- 内部：文档与域文件计数同步，域文件 8→9，`nxlib` 增 `exchange`。

### Removed

- 删除零引用的公开函数：`edge_tangent`、`structure_template`、`testing.reset`。

### Fixed

- 过渡规划调错模块导致 `AttributeError`。
- 圆角支撑容差两套并存，统一 0.5 mm。
- G2 无孔件补 `status`，不再误判 PASS。
- 输出标记包装器吞掉 `USER FATAL MESSAGE` 与 `TESTxx_FAIL`。
- `--pmi` 单独给出时被丢弃并报 PASS。
- 球标第 7 参类型、`linear_edges` 重复边、`model_bbox` 回退直边包盒。

## [1.4.0] - 2026-11-03

逆向重建与审计层成形。

### Added

- 逆向结构推断：从面表生成结构表（板、回转、孔链、放样、臂），未识别面进 `unresolved`；同轴多半径并成一条，拔模相似形不判放样。
- 结构级 builder：板、回转、锥孔、孔组、腔、叉耳、双瓣耳、修边、倒圆、孔链、放样、拔模窗口；一个结构一次调用。
- 过渡规划：按支撑面与二面角选择 FaceBlend、滚圆刀或测量截面，给逐跑道证据与构建障碍分级。
- 参数化模板：参数表/schema、命名表达式、派生约束、局部编辑矩阵。
- 审计：G8 活性、局部性、编辑包络（bounded/narrow/stuck）、预算、G1full 全集站表。
- 测量：B-rep 精确截面、STL 双向偏差、功能孔分母、四视图 IoU、同轴分组与圆角地图。

### Changed

- 逆向交付路线改为结构特征优先：特征数与结构数同量级，结构语义与几何验收同时通过。
- 截面验收收紧为每站 IoU ≥0.95、面积差 ≤5%。
- G 编号退为机器键，验收表改用具体指标名（截面重合度、圆柱/锥面参数、体积差、包盒差、四视图 IoU、双向偏差、圆角覆盖、表达式活性、特征树结构）。
- 圆角支撑面宽度统一为“两条支撑面各 ≥ R + 0.5 mm”。

### Fixed

- `compare_parts` 按几何键匹配参考组，不以有序 face-tag 元组判 N/A。
- `section_iou` 空截面不再报 1.0；空站按 `coplanar_section`/`no_material` 分类。
- `g7_reachability` 的 `ceiling` 只作诊断，BLOCKED 需逐跑道证据。
- `liveness` 合并 `missing`、dead、broken；编辑包络还原逐位校验。
- `station_plan_full` 按面归属判覆盖；未分配面改 error。
- `param_table` 不把 data/derived 行当独立参数；schema 校验补重复 id、未定模板、design/data 混用、缺 `build_order`。

## [1.3.0] - 2026-10-26

测量与比对门落地。

### Added

- 只读测量模块：面表、同轴分组、孔/锥参数、STL 截面面积与 IoU、件间比对；打开部件不保存。
- B-rep 精确截面与测站报告：每站给 `area_inter/area_union/only_a/only_b`，支持按缺料/多料定位结构。
- 可编辑性普查：逐条命名表达式 ×1.1，返回 named/live/dead/broken/alive_ratio/pass。
- 逆向验收链：结构清单 → 结构表 → 测站 → 几何门 G0–G6 → 交付。
- 测量配方与归因：孔轴取面表 `point/dir`、沉孔锥底、拔模 `DraftOption`、薄壁切除保体数、斜结构按纵剖面等。

### Changed

- 逆向交付路线改为结构特征优先，验收新增结构语义（无逐层拉伸堆栈、每结构可单独修改）。
- 截面验收：每站 IoU ≥0.95、面积差 ≤5%。
- G 编号退为机器键，正文改用指标名。
- 内部：FEA/Motion/Drafting/GB 文档删除零件专属读数，保留判据与阈值。

### Fixed

- `HolePackage` 类型属性是 `Type`，`Types` 只读；接缝处显式设 `ProjectDirectionMethod`。
- 截面端点用 `AskCurveProps(ct, 0/1)`，闭环按端点聚类自建。
- 布尔顺序：切除刀具穿过目标面，补孔排在整圆盘并集之后。
- 圆角选边改用 exact，避免 ring 带入曲面缝边。
- 孔轴、堆叠层截面、凸台顶面与板顶面的区分。
- `Concentric` 孔口圆边的静态 DOF 读数不可靠，转动副改用拖动后的几何判定。

## [1.2.0] - 2026-10-20

逆向重建域与 GB 出图配方。

### Added

- `references/reverse-engineering.md`：逆向重建域——坐标系与截面策略、逐层闭合草图拉伸、孔系/凹槽后置切除、双向点-三角面偏差校核、验收阈值、重建件后续修改。
- B-rep 批量取截面配方（`SectionFromPlanes`/`SectionFromParallelPlanes`、`AskCurveProps` 采样）。
- GB 出图：命名模型视图、从模型视图建基本视图、中文字体、尺寸文字框/重叠判定、非轴对齐零件出图、视图样式。
- 标注：2×2 表格、球标完整配方、尺寸不走 .NET 的判据。
- STEP 0 实体时的 Parasolid 回退；FEA `.fem`/`.sim` 保存配方；装配 `Fix` 约束；视图自动命名。
- 内部：文档治理，ROUTE/CONCISE 组，`assembly-drafting.md` 拆为 `assembly.md` 与 `drafting.md`。

### Changed

- 工程图三文件按权威分工去重：标注规则统一到 `drafting-annotation.md`，`drafting.md` 只留视图/PDF，`gb-drawing.md` 只留模块专用行为。
- 内部：坑位表按路线内联，`SKILL.md` §1 为唯一跨域高发陷阱清单。
- 内部：文档与脚本注释去除日期戳与历史指代。

### Fixed

- GB 文字控制字符：`×` 触发 locale 报错、`~` 被当控制符、`Ø` 写 `<O>`；标题栏日期列溢出。
- 自动标注 API 名更正为 `AutoDimensioningRule` 与 `SketchAutoDimensionBuilder.DimType`。
- 比例尺按裁剪后的缩放因子计算。
- `check_journal.py` 重复规则编号 5.19 改 5.20；修正枚举属性名与文件指向。
- `run_journal_batch.bat` workdir 传入文件时显式报错，不再回落到调用者 CWD。

## [1.1.0] - 2026-10-19

Motion 滑动副与齿轮连接件。

### Added

- Motion 滑动副配方（`JointDefine.Type.Slider`，两组几何、关节局部 z 轴）。
- Motion 齿轮连接件配方（60 r/min 输入 → −30 r/min 输出）。
- 渐开线齿轮轮毂参数 `hub_d`/`hub_len`/`z_offset`。
- `gb_drawing.assembly_bbox` 多组件包盒；`tech_note(..., base_y=)` 避开明细栏。
- `check_journal.py` 规则 5.19（`NXOpen.UF.UFDrf` 伪容器）与 Py3.6 `math.dist` 检测。

### Changed

- Motion 文档改为 0 基帧模型（帧 0 = t=0）；补角度元素表与线速度配方；明确 `MotionTranslationZ` 沿关节局部 z 轴、正速度沿 −z。
- 内部：文档精简，删除验证过程、日期、历史沿革，README 去掉会随文档变动的计数。
- 孔包覆盖改为三种非螺纹孔型；Motion 覆盖补滑动副与齿轮连接件。

### Fixed

- `gb_drawing.map_point` 投影失败时静默返回错误坐标。
- 球标 `CreateIdSymbol` 第 7 参必须是 `NXOpen.UF.Drf.Object` 结构体。
- 装配实例边 + 剖视图线性尺寸静默读错。
- Motion 帧索引误判：`AskLinkTransfromForGivenFrame` 为 0 基。

[1.1.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.1.0
[1.2.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.2.0
[1.3.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.3.0
[1.4.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.4.0
[1.5.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.5.0
[1.6.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.6.0
[1.7.0]: https://github.com/EVOL233awa/nxopen-journal/releases/tag/v1.7.0
