# 装配与工程图域（NX 12 批处理）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。§A 装配（A.5 运动连接）、§B 工程图。示例 `scripts/tests/04/06/07/10/16/17`；标注 `scripts/tests/19`。

## A. 装配

### A.1 添加组件与组件操作

```python
m = NXOpen.Matrix3x3(); m.Xx = 1.0; m.Yy = 1.0; m.Zz = 1.0   # ⚠ 无参构造为全 0，必须手动置对角
comp, status = assy.ComponentAssembly.AddComponent(
    part_path, "1", "MODEL", NXOpen.Point3d(0,0,0), m, 1)     # ⚠ 返回 (component, loadStatus) 元组
children = assy.ComponentAssembly.RootComponent.GetChildren() # ⚠ 没有 .Components 属性
```

- `Matrix3x3` 字段组 = **局部轴在全局坐标中的分量**（`Xx/Xy/Xz` 为局部 X 轴三分量，`Y*`/`Z*` 同理，按列存）。+θ 绕 Z：`m.Xx=ca; m.Xy=sa; m.Yx=-sa; m.Yy=ca`；按行组读差 θ 变号。写错 = 镜像角位且**无报错**，须用含姿态的 `GetPosition` 断言暴露。
- `MoveComponent` 不可靠 → Remove + `AddComponent` 新位姿；重加后 `Name`="MODEL"，显示名用 `DisplayName`。
- 验证后才保存；GUI 不热重载，需重开（modeling.md §1.8）。

### A.2 配对约束（用例 10）

```python
ca = assy.ComponentAssembly
occ_base_top = c_base.FindOccurrence(proto_face)     # 原型面 -> 实例面（配对必须用实例面）
pos = ca.Positioner
pos.BeginAssemblyConstraints()
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "con")
con = pos.CreateConstraint(True)                     # True=持久约束
con.ConstraintType = NXOpen.Positioning.Constraint.Type.Touch
con.CreateConstraintReference(c_moving, occ_face_moving, False, False, False)
con.CreateConstraintReference(c_fixed,  occ_face_fixed,  False, False, False)
session.UpdateManager.DoUpdate(mark)                 # ⚠ 缺 DoUpdate 则 Solve 无错但组件不动
net = pos.EstablishNetwork()
net.AddConstraint(con)
net.Solve()                                          # 返回 None=无错
net.ApplyToModel()                                   # ⚠ 把解算变换应用到组件
con.SetName("PinOnBase_Touch")
pos.ClearNetwork(); pos.EndAssemblyConstraints()
c_moving.GetPosition()                               # (Point3d, Matrix3x3) 验证贴合
```

- `con.Type` 只读 → 用 `con.ConstraintType`。
- Distance `con.OffsetRightHandSide` setter 报 "Not yet implemented" → 用显式坐标或 Touch/Concentric。
- DOF 仅辅助，须约束存活时读（删约束后任何件 `3T+3R`）；互证：`Fix` `0T+0R`、`Fit` 等半径孔面 `1T+1R`、`Concentric` 孔口圆边 `0T+1R`、未约束 `3T+3R`；位置以 `GetPosition()` 为准。
- `RemoveComponent` 不删 positioner 持久约束。清空：`for c in list(positioner.Constraints): c.Persistent = False` → `DeleteNonPersistentConstraints()` → 冷开 `list(...)==[]`。
- 面引用 = `FindOccurrence(原型面)`；用错原型面报 "not in the same file as the Targetset"（fea.md §5）。

约束类型枚举（NX12 全表）：Touch/Concentric/Fix/Distance/Parallel/Perpendicular/Center12/Center22/Angle/Fit/Bond/OrientAngle/AlignLock/Hinge/Slider/Cylindrical/Ball/Screw/Gear/RackPinion/Cable/LinearPattern/CircularPattern/Linear2dPattern/RadiantPattern/CommonOffsetTransform/SplineData/SplineLength/Undefined。
（`ValueOf` 在 `dir()` 里但**不是枚举成员**，赋类型报 `Expecting NXOpen.Positioning.Constraint.Type type, found builtin_function_or_method`。）
⚠ **`Hinge`/`Slider`/`Cylindrical`/`Ball`/`Screw`/`Gear`/`RackPinion`/`Cable`/`LinearPattern`/`CircularPattern`/`Linear2dPattern`/`RadiantPattern`/`CommonOffsetTransform` 标注 `For internal use only`**，赋 `ConstraintType` 抛 `NXOpen.NXException: The constraint type is not valid for this operation.` → 转动副走 §A.5 的 `Fit`/`Bond`，移动副走「两组平面 Touch」。

排障：① 无 `Align` 成员；② 求解后不动先 Fix 基准件再加 Touch/Concentric；③ 显式坐标回退后过 §A.5 Bond 决策树——间隙配合/同轴贴合（r6 销配 r6.1 孔）优先 Bond，PERSISTENT_CONSTRAINTS=0 硬失分。

### A.3 组件阵列 / 引用集 / 干涉

- 阵列：`CreateComponentPatternBuilder(ComponentPattern.Null)`；`SelectObjectList`（`cps.Add(comp)`/`SetArray`）→ `Commit` 后子件数按阵列数增；`PatternService` 成员同特征阵列（modeling.md §3.1）。
- 引用集：`ReplaceReferenceSet(comp, "Entire Part"/"MODEL"/"Empty")`（默认 MODEL）；MODEL=仅实体、Entire Part=+草图+基准、Empty=空载。⚠ MODEL 下草图曲线仍投影 → 建视图前 Blank 源头（§B.1）。
- **干涉别找 `ClearanceSets`**（只有读/删；`AssembliesUtils` 只有 `NewWaveQuery`）。
  - 布尔交集：`SetBooleanOperationAndTarget(BooleanType.Intersect, body_a)` → `CommitFeature()`；10 mm 立方体搭接 5 mm → 单个体 **500.000 mm³**（容差 1e-3）；分离/面贴面报 `Tool body completely outside target body.` = 无体积干涉。
  - `SimpleInterference`：`CreateSimpleInterferenceObject()`；`FirstBody`/`SecondBody` 是 `SelectObject`（写 `.Value`）；`PerformCheck()` 相交 `InterferenceExists`（2）+ 2 `Face`，分离 `NoInterference`（0）+ 空列表；完 `Reset()`/`Destroy()`。
  - 两路线独立，建议都跑。
- 质量属性（按实例体取）：
  ```python
  proto = [b for b in comp.Prototype.Bodies][0]   # ⚠ BodyCollection 不能下标（'not subscriptable'）
  inst  = comp.FindOccurrence(proto)              # → 实例体
  mp = wp.MeasureManager.NewMassProperties(units, [0.99], [inst])
  ```
- 保存后断言落盘：`wp.Save(SaveComponents.TrueValue, CloseAfterSave.FalseValue)` + `getsize(...)>0`（SKILL.md §3）。

⚠ 语义：① 体惰性加载，检查前 `Parts.Open(子件.FullPath)` 预载；② `SimpleInterference` 对重合面（零间隙）报 `InterferenceExists`，判材料重叠走布尔交集；③ 同会话重开先 `ufs.Part.CloseAll()`（`Parts.Open` 报 "File already exists"），实例体走 `Prototype.Bodies + FindOccurrence`，`GetPosition()[0]` 为原点；④ 最小间隙 `ufs.Modeling.AskMinimumDist2`（`ufs.Modl` 无）。

### A.4 装配方法论（非 API）

- **3-2-1 定位**：主基准面（消 3）+ 第二基准孔/销或侧基准面（消 2）+ 止推面（消 1）；每自由度恰好一个约束。
- **冗余三形态**：同一自由度重复限制、两约束对抗、重复定向；批处理 `Solve()` 返回 None 不报冗余，DOF 已 0 后加的约束只在 GUI 冷开时发作。
- **约束挂基准（面/轴）**，禁用圆角边/阵列结果面/布尔易变面；重复件用组件阵列，装配树按子装配分组，改名取 `DisplayName`；主模型制；WAVE 链接慎用。

### A.5 运动连接：把定位装配做成可拖动机构（用例 16）

0 约束的定位装配拖不动。在装配定位约束层（**不是** Motion 模块）重建转动副。

**转动副基元 = `Fit` 作用在两个等半径圆柱面上（内孔或外圆柱销均可）**：

```python
con = pos.CreateConstraint(True)
con.ConstraintType = NXOpen.Positioning.Constraint.Type.Fit
con.CreateConstraintReference(comp_a, comp_a.FindOccurrence(hole_face_a), False, False, False)
con.CreateConstraintReference(comp_b, comp_b.FindOccurrence(hole_face_b), False, False, False)
```
- 两圆柱**必须等半径**，否则 `InternallyInconsistent` → 配合件做成与孔同半径；外圆柱销 × 内孔同样成立。
- 单个 Fit 给 **`1T+1R`**。纯转动 `0T+1R`：轴上做轴环/台阶面，`Touch(转动件端面, 轴环端面)`。闭合机构**逐铰点读 DOF**。

**移动副（Slider）替代路线 = 两组平面 `Touch`**：

```python
# 滑块底面 ↔ 底板/导轨顶面：去掉 Z 平移 + 绕 X/Y 转动
# 滑块侧面   ↔ 导轨侧面：  去掉 Y 平移 + 绕 Z 转动
# 剩余自由度 = 沿 X 平移（DOF 1T+0R）
```
- `Constraint.Type.Slider` internal-only（§A.2），**不要用 `Fit`/`Bond` 代替**。判据：滑块 DOF = `1T+0R`；再转曲柄 5° 与解析式对账。

**附属件（销轴/套筒）跟动 = `Bond`**：
```python
c = pos.CreateConstraint(True)
c.ConstraintType = NXOpen.Positioning.Constraint.Type.Bond
c.CreateConstraintReference(comp_pin, comp_pin, False, False, False)    # 成员 1
c.CreateConstraintReference(comp_host, comp_host, False, False, False)  # 成员 2
```
- **每附属件单独一组、两成员**。⚠ **绝不可**把 N 个销轴 + M 个宿主放进同一 Bond——语义是"多个可动对象构成刚性组"，等于整机刚性。
- 间隙配合（r=4.9 配 r=5.0）时 `Fit` 不可用，`Bond` 作几何补丁；间隙动力学须另建。

**拖动配方**：
```python
net = pos.EstablishNetwork()
for c in cons:
    net.AddConstraint(c)
net.NonMovingGroupGrounded = False          # ⚠ True(默认) 时拖不动
net.BeginDrag()
net.SetMovingGroup([by["曲柄"]])            # ⚠ 组只含一件时，组外对象被当作接地
net.DragByTransform(NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(5.0))
net.Solve(); net.ApplyToModel(); net.EndDrag(); pos.ClearNetwork()
```
- **拖动语义与直觉相反**：`DragByTranslation` 是"按住被拖件"；GUI 拖连杆得转动，API 等价写法是绕该件**自身原点**转 → 组件原点须落在铰轴上。
- **移动组须含全部活动件**；`SetMovingGroup([单件])` 且组外接地时该件不动。任意活动杆都能驱动整机。
- GUI 路径：装配 → 组件位置 → 移动组件，类型「动态」。

**判据与坑位**：
- `Concentric` 挂圆柱面报 `CannotSolve` → 改挂孔口圆边；圆边约束了什么须拖动验证（位移落轴、`0T+1R`、绕轴自由、沿轴滑被拒）。
- `Fit` 不等半径报 `InternallyInconsistent`；`AlignLock` 建不出来（`FindOccurrence(圆柱面)` 返回 `None`，报 `No overload matches these arguments.`）→ 改 `Concentric` 圆边或 `Fit`。
- 路线：`Concentric` 孔口圆边给 `0T+1R`、无半径要求；`Fit` 圆柱面给 `1T+1R`、必须等半径。交付用 `Fit`+`Bond`。

圆边取**孔口整圆**（`p1 == p2 == 圆心`），用 `hole_top_edge()` 的"两顶点重合+取近顶面"筛法；取错面对齐到另一端。⚠ 圆边路线只在最小几何上验证，**真实多杆机构未验证**。

**验证**：故意移开再解算须弹回同轴（静态重合时"无错+间隙 0"无证明力）；拖动后重测铰轴间隙；脚本不保存，保存后重新 `Parts.Open` 复测；`DexManager.CreateStlCreator` 导 STL 第三方复算（SKILL.md §3 坑位 6）。

⚠ 不要假设被抓住的杆自身必转指定角度（长连杆灵敏度极低），须逐位姿核对。

**保存陷阱：`ufs.Part.Save()` 保存「显示部件」**：
- 切到零件读孔面后**必须切回装配件**，否则保存静默写回零件、装配件不落盘且不报错。
- 显式对目标部件保存：
  ```python
  asm.Save(NXOpen.BasePart.SaveComponents.TrueValue,
           NXOpen.BasePart.CloseAfterSave.FalseValue)
  assert os.path.exists(path) and os.path.getsize(path) > 0
  ```
- 交付件的拖动验证脚本绝不保存；一次性试件才保存且必须断言落盘。

### A.6 装配交付自检清单

- [ ] 自由度清零/无冗余；目标为实例面且挂稳定几何；位姿读 `GetPosition()`/`AskFaceData()`，保存后 `Parts.Open` 复测
- [ ] 0 约束原件必须 FAIL；拖动后重测铰轴间隙；Bond 每件一组两成员；保存指名目标件并断言落盘

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

| 项 | 结论 |
| --- | --- |
| `svb.Coordinate` / `FirstCorner` / `SecondCorner` / `HiddenObjects.Objects` | 全**只读**；`PlacementType` 只有 Center/Corner——提交后自己摆 |
| `ufs.Draw.SetViewScale(view_tag, s)` | **相对/乘性**，新视图基准 1.0，传目标值一次即绝对比例；`AskViewScale` → `(0, 实际比例)`；`DraftingView.Scale` = `实际×0.83436`，不可反推缩放系数 |
| `v.SetDrawingReferencePoint(Point3d(x,y,0))` | 钉住**建视图时 NX 选定的锚点模型点**，非内容中心；内容中心有视图相关常数偏差（4–5 mm）→ 关键落位走 drafting-annotation.md 的**内容包盒闭环**（`gb_drawing.pin_view`）或预减常数；后续视图越界抛 `Cannot move view off of the drawing` 会回滚之前已成功的移动 |
| `v.MoveView(p)` / `v.SetOrigin(p)` / `v.Fit()` | `Fit()` 报 "Member view may not be fit"；落位统一走 `SetDrawingReferencePoint` |
| `part.Datums` | DatumCsys 带 3 基准面 + 3 基准轴；**建视图之前** `Blank()`，之后 Blank 副本无效 |
| `Component.RemoveComponent` | 内存移除后**当次会话视图仍投影旧几何**；`SaveAs` 后重开则组件 Body 不载入（vis=0）→ 不可用于出图 |
| `DraftingCurve.Blank()` | 无异常但**不生效**（可见计数不变）；游离曲线只能建视图前 Blank 源头 |

`Blank()` 对拆件零件的构造曲线不生效（1 号层实体 + 8 条草图曲线仍投影）；无 API 屏蔽，但都在图纸内，接受即可。

⚠ **视图排布与剖视语义**：
1. `FrontTopRight` 在 FirstAngle 下把 Right 视图排在主视图右侧（与 GB 第一角相反），严格第一角需手动重排。
2. 全剖主视图的剖切线须画在 ⊥ 剖切面的视图（俯视图）上且过轴线；剖切腿平面恒 ⊥ 父视图图面。
3. 关联尺寸前确认目标边投影非退化（轴向边挂横剖圆环视图会渲染成 "0"）；局部放大源视图须含目标细节，detail 标注比例。

### B.2 批处理标注（不需要 `sheet.Open()`）

> 标注质量层（道位布局、字高/箭头、注释排版、表格、中心线体系、反模式）见 `references/drafting-annotation.md`；出正式图纸时两份都读。

- **不用调 `sheet.Open()`**：当前图纸与未激活图纸下，UF 尺寸/中心标记/中心线/注释/引线标签/表格/PDF 导出全部成功（保留无副作用但非必要）。
- **`CenterMarkBuilder` 一次只能带一个 location**：n=1/2 通过，n=3/4 报 1175305，n=8 报 1175307。配方：一标记一 builder（`CreateCenterMarkBuilder` → `Locations.Add` 一次 → `Commit` → `Destroy`）。

**尺寸（UF DRF 路线，唯一可用）**：

```python
o = ufs.Drf.Object(); ufs.Drf.InitObjectStructure(o)
o.ObjectAssocType = NXOpen.UF.Drf.AssocType.ARC_CENTER   # 圆边；直线用 END_POINT
o.ObjectTag = edge.Tag; o.ObjectViewTag = view.Tag
o.AssocDwgPos = [0.0, 0.0]                                # 必须恰 2 个 double
t = ufs.Drf.Text()                                        # 默认=自动关联值
ufs.Drf.CreateVerticalDim(o1, o2, t, [x, y, 0.0])         # 同族：CreateHorizontalDim/
                                                          # CreateParallelDim/CreateDiameterDim/
                                                          # CreateAngularDim(form=1, 两线 END_POINT)
```

⚠ 字段名 PascalCase（`ObjectAssocType`）；枚举必须传成员（`getattr(NXOpen.UF.Drf.AssocType, "ARC_CENTER")`），传 int 报类型错。`NXOpen.UF.Drf` 是属性容器，不可 `import NXOpen.UF.Drf`。

**模型点 → 图纸点：`ufs.View.MapModelToDrawing(view_tag, [x, y, z])`**：

```python
pt = ufs.View.MapModelToDrawing(view.Tag, [35.0, -20.0, 9.0])   # 返回图纸坐标数组
```

**其余标注（.NET 路线）**：

```python
part.Annotations.Centerlines.CreateCenterMarkBuilder(NXOpen.Annotations.CenterMark.Null)
    # .Locations.Add(edge, view, Point3d) —— ⚠ 一个 builder 只放一个 location
part.Annotations.Centerlines.CreateCenterline2dBuilder(NXOpen.Annotations.Centerline2d.Null)
    # .Type = ...ByPoints; .Point1/.Point2.SetValue(edge, view, Point3d)
part.Annotations.CreateNote(lines, Point3d, NXOpen.AxisOrientation.Horizontal, None, None)
    # ⚠ origin 是文本块中心，多行整体居中
part.Curves.CreateLine(...)   # 图框/表格线，sheet 打开后即可

# 球标：第 7 参必须是 NXOpen.UF.Drf.Object 结构体，不是 Edge
o = ufs.Drf.Object()
ufs.Drf.InitObjectStructure(o)
o.ObjectAssocType = NXOpen.UF.Drf.AssocType.END_POINT
o.ObjectTag = edge.Tag
o.ObjectViewTag = view.Tag
o.AssocDwgPos = [x, y, 0.0]
ufs.Drf.CreateIdSymbol(NXOpen.UF.Drf.IdSymbolType.SYM_CIRCLE, "1", "",
    [x, y, 0.0], NXOpen.UF.Drf.LeaderMode.WITH_LEADER,
    NXOpen.UF.Drf.LeaderAttachType.LEADER_ATTACH_OBJECT, o, [x, y, 0.0])
```

⚠ **`NXOpen.UF.UFDrf` 运行期不存在**（`AttributeError`）；入口是 `NXOpen.UF.Drf`/`ufs.Drf`。传 Edge 当第 7 参报 `TypeError: Seventh parameter is invalid. Expecting NXOpen.UF.Drf.Object type.`

**尺寸别走 .NET**：`part.Dimensions.Create*Dimension(...)` 无头下一律 `Internal error: memory access violation`；.NET builder 报 `Unable to infer a dimension type`。

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
- **类型标签不能指认阶梯剖**：`AskSxlineType` 对普通两点线也返回 `STEPPED_SXLINE`（2）；区别在 `AskSteppedSxline` 第 6 字段腿段数（Z 形 **9**、直线 **5**）。
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

**坑位对照（遇到 → 怎么做）**：

| 遇到 | 怎么做 |
| --- | --- |
| 一条腿交替塞 4 点（两点 y=26、两点 y=54），只 2 个被接受，余报 `Invalid point for section line` | 先设 `SectionViewType = SimpleStepped`，再把 Z 形 4 点整条挂投影面匹配的父视图（缺一不可） |
| 腿 1 走 `SegmentLocation`、腿 2 走 `SegmentLocationForSecondLeg`，腿 2 不报错也不生效（`loc2.Length`=0） | 别分两条腿；阶梯剖的点全给一条腿 |
| `SectionViewMode.StandAlone` | 报内存访问违例或 `Section line lost model associativity.`；用默认模式 |
| 用弃用的 `SectionLineBuilder` | `Validate()` 报 `Section line must have a cut segment.`、`Commit()` 报 `Invalid view.`、`Leg1.Append` 报 `No overload matches`；改用 `SectionViewBuilder` |
| 走 `CreateSimpleSxview` / `CreateSxviewFromDmv` | `cut_object` 要 `UF_DRF_object`，`assoc_dwg_pos` 须在图纸上，官方样例靠既有剖切线取段 → 鸡生蛋；builder 够用 |

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

### B.5 无人值守 GUI 出图：已无必要

`View.Base` 下批处理直接出图，GUI 直启、startup 钩子、SendKeys/SetForegroundWindow 注入不需要；遇无人值守出图先查 `View.Drawing`。

## 装配图补充

- **持久约束一次建全 + 单一网络 Solve/ApplyToModel**（逐约束求解会重排不可见组件）。
- **`DraftingCurve.GetVertices()` 对装配视图曲线返回 0 条** → 改查 `ufs.Curve.AskArcData/AskLineData`；struct 属性 PascalCase，圆心 `ArcCenter`。
- **UF 曲线查询返回模型空间坐标**；图纸坐标只用于 `AssocDwgPos`/球标原点。
- **同一曲线两个 END_POINT 建尺寸读数 0** → 换两条不同边；端点含义不同时改挂顶圆弧 `ARC_CENTER`，以"创建→读数→不对即删重试"兜底。
- **视图曲线被截断成多段** → 共线匹配取最长段。
- **`SetDrawingReferencePoint` 后 `AskViewScale` 回读 0** → 比例用内容包盒反推（右视图内容宽=模型 Y 跨度）。
- **重跑同图页先 `ufs.Draw.DeleteDrawing(旧图页)`**；图框必须显式 `gb.frame(sheet, size)`。
- **球标避让**：origin 只被图框钳位、无碰撞检查，圆圈须落空白口袋；无口袋时换视图锚定。
- 表格 em dash 渲染成豆腐块 → 跨栏格写中文短语。
