# Changelog

本文件记录 `nxopen-journal` 技能的版本变更。格式遵循
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

### Added

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
- `SKILL.md` §3：`SaveAs` 到已存在路径报 `File already exists`，阶段件写新路径或先删目标。

### Changed

- 逆向重建交付路线改为结构特征优先：组件按自然成形方式建（回转/拉伸/放样/布尔/阵列），特征数与结构数同量级；验收新增结构语义（无逐层拉伸堆栈、每个结构可单独修改），与几何验收同时通过。
- 截面验收由“覆盖组件与平面族”收紧为“每站 IoU ≥0.95、面积差 ≤5%”。
- `SKILL.md` 路由表中的逆向重建描述改为“原件+一句重建要求→测量链→截面/放样→切除→验收项”。

### Fixed

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
