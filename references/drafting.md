# 工程图域（NX 12 批处理）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。本文件 §B 工程图：图纸/三视图/投影/局部放大/剖视/PDF/装配图路线。标注规则唯一权威见 `drafting-annotation.md`，国标成套出图见 `gb-drawing.md`，装配约束见 `assembly.md`。示例 `scripts/tests/06/07/19/20/21/31/33`。

## B. 工程图（Drafting）

### B.1 图纸 + 三视图

```python
part.DrawingSheets.InsertSheet("SHT1", NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4, 1.0, 1.0,
                               NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle)
svb = part.DraftingViews.CreateStandardViewsBuilder()
svb.Part = part
svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
svb.Autoscale = True
svb.Commit(); svb.Destroy()
# ⚠ DrawingSheets/DraftingViews 无 ToArray，用 for x in part.DrawingSheets 迭代
```

**`ViewType` 必须用 `View.Base`，绝不能用 `View.Drawing`**。`View.Drawing` 建空 2D 视图：`AskVisibleObjects()` 恒 0、`IsOutOfDate` 恒 False，PrintPDFBuilder 只出 **917 字节空白页**。`View.Base` 下 `run_journal.exe` 无头批处理直接出真图，**不需 GUI/解锁/交互回放**。

判据：`View.Base` 每视图 `AskVisibleObjects() ≥ 10`，`View.Drawing` 各视图恰好 0。`AskVisibleObjects()` 只对**当前图纸**的视图有效，否则抛 `The view is not displayed` → 先 `sheet.Open()`。

**视图定位与比例路线**：

- 落位统一用 `v.SetDrawingReferencePoint(Point3d(x,y,0))` + 内容包盒闭环（`gb_drawing.pin_view`）；它钉住的是 NX 建视图时选定的锚点模型点，不是内容中心，偏差按视图恒定，用包盒迭代补偿（收敛 <0.05 mm）。`MoveView`/`SetOrigin`/`Fit()` 不用（`Fit()` 报 "Member view may not be fit"）。
- 比例用 `ufs.Draw.SetViewScale(view_tag, s)`：相对/乘性，新视图基准 1.0，传目标值一次即绝对比例；`AskViewScale` 读 `(0, 实际比例)`。`DraftingView.Scale` = 实际×0.83436，不可反推缩放系数。
- 视图越界会抛 `Cannot move view off of the drawing` 并回滚之前已成功的移动，摆位前先算内容包盒。
- `svb.Coordinate` / `FirstCorner` / `SecondCorner` / `HiddenObjects.Objects` 只读；`PlacementType` 只有 Center/Corner，提交后用 `SetDrawingReferencePoint` 摆。
- 先 `Blank()` 基准与构造曲线（DatumCsys 带 3 基准面 + 3 基准轴）；建视图后 `Blank()` 副本无效，`DraftingCurve.Blank()` 不生效。
- 装配出图前 `Parts.Open` 预载子件；`Component.RemoveComponent` 后当次会话视图仍投影旧几何，`SaveAs` 重开则组件 Body 不载入。

拆件零件的构造曲线 `Blank()` 不生效（1 号层实体 + 8 条草图曲线仍投影）；保留即可（都在图纸内）。

⚠ **视图排布与剖视语义**：
1. `FrontTopRight` 在 FirstAngle 下把 Right 视图排在主视图右侧（与 GB 第一角相反），严格第一角需手动重排。
2. 全剖主视图的剖切线须画在 ⊥ 剖切面的视图（俯视图）上且过轴线；剖切腿平面恒 ⊥ 父视图图面。
3. 关联尺寸前确认目标边投影非退化（轴向边挂横剖圆环视图会渲染成 "0"）；局部放大源视图须含目标细节，detail 标注比例。

### B.2 批处理标注入口（不需要 `sheet.Open()`）

> 尺寸/文字/表格/中心线/球标的配方与字段约束统一见 `references/drafting-annotation.md` §4/§5/§6/§6b/§7；本文件只保留批处理入口与视图坐标映射。

- **不用调 `sheet.Open()`**：当前图纸与未激活图纸下，UF 尺寸/中心标记/中心线/注释/引线标签/表格/PDF 导出全部成功（保留无副作用但非必要）。

**模型点 → 图纸点：`ufs.View.MapModelToDrawing(view_tag, [x, y, z])`**：

```python
pt = ufs.View.MapModelToDrawing(view.Tag, [35.0, -20.0, 9.0])   # 返回图纸坐标数组
```

**装配图纸的边解析**：`Prototype.Bodies` 为空 → 先 `s.Parts.Open(子件)` 预载，再 `comp.FindOccurrence(body).GetFaces()` 取实例边，按顶点坐标匹配（TOL 0.02）。圆边两顶点重合（`GetVertices` 相等）即整圆，其顶点=圆上参考点（非圆心；孔心=上下两 rim 中点）。

**视图坐标映射**：`sheet = ref + s*(proj(p) - proj(bbox中心))`，proj：Front=(x,z)、Right=(y,z)、Top=(x,y)；孔轴线向 z 的回转面在 Front/Right 呈矩形轮廓（Ø 标其上属惯例），真实形状/角度在 Top。**角度尺寸须在两线延长线交点落图内的视图上**，交点在图外改用注记文本。

### B.3 出图导出（走 `View.Base`）

`View.Drawing` 得空 2D 视图（vis 恒 0、PDF 恒 917B）。`View.Base` 下 `run_journal.exe` 直接出真图（A3 三视图 PDF + 同名 .prt），无需 GUI/解锁。

`PrintPDFBuilder`（`part.PlotManager.CreatePrintPdfbuilder()`，在 **part** 上）正常出图，每 sheet 一个 PDF。

PrintPDFBuilder 陷阱（NX12）：`Filename`（**小写 n**，无 `FileName`）；尺寸属性是 **`Size`**（`SizeOption` 只读）；`Action` 是 Teamcenter 语义（Native/New/Append/Overwrite）；`Color` = BlackOnWhite/AsDisplayed/ColorsByWidth/CustomPalette/LegacyColors/PartColors。`SetSheets` 的 sheet 必须属于 display part。

**交付形态**：`run_journal.exe` 批处理一键（`.bat` 用 **GBK + CRLF**；Python 3.6 的 UTF-8 输出重定向进日志）。图纸 A3 三视图（第一角），**不含尺寸与中心线**。

### B.4 投影视图 / 局部放大视图 / 剖视图

`StandardViewsBuilder` 只管三视图；投影/局部放大走 **UF**，剖视图走 **builder**。

```python
sheet.Open()                                   # 目标图纸必须先是当前图纸
ufs.Draw.SetDisplayState(2)                    # 2 = DRAWING_VIEW，UF 建视图前置
ref = front.GetDrawingReferencePoint()          # 父视图在图纸上的参考点

# 投影视图：父视图 + 投影方向 + 图纸坐标
ufs.Draw.AddOrthographicView(sheet.Tag, front.Tag,
                             ufs.Draw.ProjDir.PROJECT_BELOW,
                             [ref.X, ref.Y - 90.0])        # -> 新视图 tag
# 局部放大视图（矩形边界）：图纸坐标两对角点 + 比例 + 放置点
ufs.Draw.AddDetailView(sheet.Tag, front.Tag,
                       [ref.X - 25.0, ref.Y - 15.0], [ref.X + 25.0, ref.Y + 15.0],
                       2.0, [ref.X, ref.Y - 60.0])          # -> 新视图 tag
```

| 项 | 判据 |
| --- | --- |
| 投影视图 | 建出 `ORTHO@n`；**必须 `ufs.Draw.UpdateOneView(sheet.Tag, tag)` 再问**——不更新时 `AskVisibleObjects()`=**0**（几何已在出图），更新后=**7** |
| 局部放大视图 | `DETAIL@n`，更新后 `AskVisibleObjects()`=**3**（双孔区域真实内容数） |
| 局部放大比例 | UF `AskViewScale(detail)` = **2.0 × UF 父比例（乘性）**；.NET `view.Scale` 是自缩放链（2.36 = 2.0×1.18），**核对用 UF 值** |
| 边界圆 | 虚线圆半径 ≈ **选框半对角的 0.83 倍**（缩进 5–6 mm），选框留余量 |
| 放置点越界 | y=250（A4 高 210）抛 `Input is not a valid parameter`，**不创建视图** |
| 删除视图 | `ufs.Obj.DeleteObject(tag)`（无 `DeleteObj`；无 `UF_DRAW_delete_view`） |

#### 视图命名与查找

- 自动名 = `<标签>@<视图号>`：标准三视图 `Right@1` / `Front@2` / `Top@3`（随建视图顺序变，**不要假设 `FRONT@1`**）；投影 `ORTHO@4`；剖视 `SX@5`；局部放大 `DETAIL@7`。
- `@n` 是视图标签序号，**不连续也不可预测**（局部放大的边界圆会占号，5 之后直接到 7）。精确匹配用实际名；按类找用前缀 `name.split("@")[0]`。
- 改名：`view.SetName("FRONT_MAIN")`，改后 `view.Name` 就是 `FRONT_MAIN`（`@n` 后缀消失）。`view.Name = ...` 抛 `AttributeError: attribute 'Name' of 'NXOpen.NXObject' objects is not writable`。
- 查找：图纸视图迭代 `sheet.GetDraftingViews()` 比名字（`gb_drawing.base_view` 按 `split("@")[0]` 前缀匹配，改名不破坏它）；模型视图用 `part.Views.FindObject("VFRONT")`（`save_model_view` 存的名字）。

UF 包装类：
- 枚举挂在**会话对象**上：`NXOpen.UF.UFDraw` 不可 import，写 `ufs.Draw.ProjDir`；成员 `PROJECT_INFER/PROJECT_ABOVE/PROJECT_RIGHT/PROJECT_BELOW/PROJECT_LEFT`（无 `Below` 短名），`SxsegType` = `SXSEG_CUT/SXSEG_BEND/SXSEG_ARROW`。传裸 int 报 `Expecting NXOpen.UF.Draw.ProjDir type, found int`。
- `part.DraftingViews` **无 `__len__`**：用列表推导；`sheet.GetDraftingViews()` 可 `list()`。

#### 剖视图

```python
svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
svb.ParentView.View.Value = front            # 缺这一步必抛 Invalid parent view
loc = svb.SectionLineSegments.SegmentLocation
loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(30.0, 40.0, 6.0)))   # 模型坐标
loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(90.0, 40.0, 6.0)))
svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = NXOpen.Point3d(ref.X, ref.Y - 70.0, 0.0)
svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(
    NXOpen.Point3d(ref.X, ref.Y - 70.0, 0.0))
view = svb.Commit(); svb.Destroy()           # -> NXOpen.Drawings.SectionView
```

1. 空引用写 `NXOpen.Drawings.SectionView.Null`（不能 `None`）。
2. 父视图只能从 `ParentView.View.Value` 进（`View` 只读但返回 `SelectObject`，`.Value` 可写）；缺则 `AddCutSegment` 抛 `Invalid parent view for section line.`。`ViewPlacementBuilder.Placement` 同理。
3. 切点用**模型坐标**且落在父视图可见实体内（图纸坐标能 commit 但 `AskSxsolidsOfSxview` 落空）；放置点与 `SectionLineOnlyPlacementOrigin` 用**图纸坐标**（参考点下移 70 mm）。

判据分工：`IsSxview` 证"是剖视图"，`AskSxsolidsOfSxview` 证"剖到实体"，`Hatch` 证"画了剖面线"。**`Hatch` 单独说明不了切到没切到孔**——实心块剖开同样打剖面线，还须断言毛坯上存在圆柱面（`AskFaceData` 面类型 16）。

⚠ 剖视图显示"剖切面 + 面后可见几何"，不是只有切口：两孔在 y=20/60 时对应剖切面读数完全一样；曲线数只反映模型里有什么，不反映切面在哪。

#### 阶梯剖

剖切**类型**是 builder 属性，**阶梯靠 Z 形切点路径**形成：

```python
SVB = NXOpen.Drawings.SectionViewBuilder
svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
svb.ParentView.View.Value = state["top"]          # ⚠ 父视图必须选"切点所在投影面"的视图
svb.SectionViewType = SVB.SectionLineType.SimpleStepped   # ⚠ 属性名是 SectionViewType
loc = svb.SectionLineSegments.SegmentLocation
for x, y in ((20.0, 40.0), (80.0, 40.0), (80.0, 60.0), (110.0, 60.0)):   # 模型坐标，Z 形
    loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(x, y, 6.0)))
svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = NXOpen.Point3d(ref.X, ref.Y - 140.0, 0.0)
svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(NXOpen.Point3d(ref.X, ref.Y - 140.0, 0.0))
view = svb.Commit()
```

- ① **属性名 `SectionViewType`**：`SectionLineType` 是枚举类本身，实例赋值报 read-only。② **切点必须在父视图投影平面内**：Z 形挂 Front（XZ）第 3 点报 `Invalid point for section line`，挂 Top（XY）才通过。
- **阶梯剖用 `AskSteppedSxline` 第 6 字段腿段数判定**（Z 形 **9**、直线 **5**），不要用 `AskSxlineType` 类型标签（普通两点线也返回 `STEPPED_SXLINE`（2））。
- `AskSimpleSxline` 对阶梯线报 `Section line is not correct type.`；`SxlineType` 全集 = `BREAKLINE/FOLDED_SXLINE/HALF_SXLINE/REVOLVED_SXLINE/SIMPLE_SXLINE/STEPPED_SXLINE/UNFOLDED_SXLINE`。
- `SectionViewType.PointToPoint` 产出 **`FOLDED_SXLINE`（7）**，`AskFoldedSxline` 答、`AskSteppedSxline` 拒。

#### 半剖 / 旋转剖 / 展开剖

入口同阶梯剖，差别只在 `SectionViewType` 与切点：

```python
SVB = NXOpen.Drawings.SectionViewBuilder
svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
svb.ParentView.View.Value = <父视图>

# 半剖：L 形三点路径——第 1 段穿过轴线，第 2 段垂直走到端面
svb.SectionViewType = SVB.SectionLineType.Half
for p in ((20, 40, 6), (60, 40, 6), (60, 40, 12)):
    svb.SectionLineSegments.SegmentLocation.AddCutSegment(
        part.Points.CreatePoint(NXOpen.Point3d(*p)))

# 旋转剖：两条腿各填各的，且必须先给旋转点
svb.SectionViewType = SVB.SectionLineType.Revolved
segs = svb.SectionLineSegments
segs.RotationPoint = part.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 6.0))  # ⚠ 要 Point
for p in ((20, 40, 6), (60, 40, 6)):
    segs.SegmentLocation.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(*p)))
segs.SegmentLocationForSecondLeg.AddCutSegment(
    part.Points.CreatePoint(NXOpen.Point3d(60.0, 70.0, 6.0)))
```

- **读数**：半剖 `HALF_SXLINE`（4），`AskHalfSxline` 8 字段（第 6 段数 3）；旋转剖 `REVOLVED_SXLINE`（3），`AskRevolvedSxline` 11 字段（第 8 腿段数 4）。⚠ 元组长度非固定，断言取"≥ 已知最少"或按字段位置取；其余 `Ask*Sxline` 报 `Section line is not correct type.` → **剖切线类型是最省事判据**。
- ⚠ **旋转剖不设旋转点必被拒**：默认落折点，报 `Rotation and bend points cannot be coincident.`；赋 `Point3d` 报 `Expecting NXOpen.Point type, found NXOpen.Point3d`。
- ⚠ **`SegmentLocation.Length` 计段端点**：两腿各 2 点读 4、腿 2 单点读 2；半剖 L 形三点读 3，直线两点也读 3。别拿它判点数。
- **展开剖 = `ViewUnfolded`**：可设可提交（`CreateFolded` 变 False），但对象级读数与折叠态相同，唯一差别是 PDF 字节数；判据只取"开关读回 + 视图有效 + 两份出图不同"。.NET 无展开剖类型，`AskUnfoldedSxline` 报 `Section line is not correct type.`。

**阶梯剖路线约束**：先设 `SectionViewType = SimpleStepped`，再把 Z 形 4 点整条挂到投影面匹配的父视图；阶梯剖的点全给一条腿，不要拆 `SegmentLocationForSecondLeg`（腿 2 不生效）。模式用默认值（`StandAlone` 报内存访问违例或 `Section line lost model associativity.`）；入口用 `SectionViewBuilder`（弃用的 `SectionLineBuilder` 报 `Section line must have a cut segment.` / `Invalid view.`；`CreateSimpleSxview`/`CreateSxviewFromDmv` 需要既有剖切线，builder 够用）。

#### builder 只读属性一览

| 位置 | 结论 |
| --- | --- |
| `None` 当空引用 | 被拒：`Expecting NXOpen.NXObject type, found NoneType`。传 `SectionView.Null`/`DetailView.Null`；`NXOpen.Tag.Null` 取不到，C 侧空标签写 `0` |
| `ParentViewBuilder.View` | 只读，但返回的 `SelectObject.Value` **可写** |
| `ViewPlacementBuilder.Placement` | 同上，`.Value` 可写 |
| `DetailViewBuilder.Origin` / `Scale` | 只读且无容器通道——局部放大仍走 UF `AddDetailView` |
| `DetailViewBuilder.BoundaryPoint1/2` | 要 `NXOpen.Point` 对象，传 `Point3d` 报 `Expecting NXOpen.Point type, found NXOpen.Point3d`；都不给则报 `The points defining the boundary cannot be the same` |
| 空 `SectionLine` 直接 Commit | `Null tag not allowed` |

**通用判据**：属性只读时先看返回的是否 `SelectObject`/`ScCollector` 容器（`.Value` 可写）；拿不到容器通道才退回 UF。

`SectionViewBuilder.SectionLineSegments` **无 Add 方法**，段几何靠 `SegmentLocation.AddCutSegment()`；`SectionLine`（`SpecifySectionLineBuilder`）只有只读属性。

### B.5 无人值守出图入口

`View.Base` 下批处理直接出图；无人值守出图走这条路线，不需要 GUI 直启、startup 钩子或 SendKeys/SetForegroundWindow 注入。先确认视图类型不是 `View.Drawing`。

### B.6 装配图路线（按顺序）

1. 约束一次建全，再 `EstablishNetwork` → `Solve` → `ApplyToModel`（逐约束求解会重排不可见组件）。
2. 出图前 `Parts.Open` 预载子件；`DraftingCurve.GetVertices()` 对装配视图曲线返回 0 条，改用 `ufs.Curve.AskArcData/AskLineData`（struct 属性 PascalCase，圆心 `ArcCenter`）。
3. UF 曲线查询返回模型空间坐标；图纸坐标只用于 `AssocDwgPos`/球标原点。
4. 尺寸关联：同一曲线两个 `END_POINT` 读数 0 时换两条不同边；端点含义不同时改挂顶圆弧 `ARC_CENTER`，创建后读数不对即删重试。
5. 视图曲线被截断成多段时，共线匹配取最长段。
6. `SetDrawingReferencePoint` 后 `AskViewScale` 回读 0 时，比例用内容包盒反推（右视图内容宽=模型 Y 跨度）。
7. 重跑同图页先 `ufs.Draw.DeleteDrawing(旧图页)`；图框显式 `gb.frame(sheet, size)`。
8. 球标布点见 `drafting-annotation.md` §6b；origin 无碰撞检查。
9. 表格 em dash 渲染成豆腐块时，跨栏格写中文短语。
