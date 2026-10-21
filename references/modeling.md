# 建模域：方法论 + 可复现路线（NX 12 本机批处理）

> 先读 SKILL.md。§1 方法论；§2-§6 路线（⚠ 已验证）。示例 `scripts/tests/01-03`；§3.4-§3.6 抽壳/拔模/质量属性/去参，§4.4 螺纹。

## 1. 建模方法论（风格约定，非 API）

### 1.1 规划与设计意图

- **特征树当源码**：设计意图 → 特征框架 → 原点/基准 → 草图作根。
- 四问：定位基准、改动波及、最易变值（→ 表达式）、外部引用风险；再定驱动尺寸 vs 保形尺寸。

### 1.2 特征树顺序

- **加材 → 切除 → 细节 → 倒圆/倒角 → 阵列/镜像**；重算特征放树尾，复杂形状拆多特征。
- 倒圆大半径先、小半径后；<1 mm 装饰圆角用 3D 特征且靠后。

### 1.3 特征语义

- 孔用 Hole 特征（标准孔/沉头/螺纹语义），不用"拉伸圆柱+布尔差"；槽用 Slot 或草图+拉伸差。
- Pattern Feature 优于 Pattern Face（复制特征树、改种子全联动）。

### 1.4 重复特征

- **种子 + 依赖细节 + 阵列/镜像**：打孔→孔口倒圆→一起阵列；禁止逐个复制、禁止先阵列后补细节。
- 位置用构造几何（构造线/构造圆/十字线）驱动。

### 1.5 草图纪律

- 先几何约束后尺寸约束；~60-80% 自由度由几何约束吃掉；对称用 Symmetric/Equal。
- 完全约束并锚定原点；闭轮廓才可拉伸。
- 一个草图一个用途（>~15-20 实体拆分）；同一基准面不叠多个草图。

### 1.6 对称件

- 画一半 + 镜像（特征级 `MirrorFeatureBuilder`；草图级不可用，§4.3）。

### 1.7 参数化与命名

- 顶层参数表达式化（`L_Plate=100`、`D_Bore=8`）；≥2 次出现或可能被改即表达式；次级尺寸派生（§4.1）。
- 需回看才能认出的特征 `SetName`；常见项目做模板。
- 图层：Solids 1-10 / Sheets 11-20 / Sketches 21-40 / Curves 41-60 / Datums 61-80；Layer Category 整层开关。

```python
body.Layer = 5  # 实体可写；Feature 没有 .Layer（AttributeError），
  # 按特征归层只能在建它的那一层里设它产出的体
wp.Layers.WorkLayer = 1  # 工作层
wp.Layers.SetState(5, NXOpen.Layer.State.Hidden, True)  # ⚠ 第1参必须是 int（传 [5] → 0xC0000374 堆崩）
st = wp.Layers.GetState(5)  # Layer.State: Hidden=3 / Visible=2 / Selectable / WorkLayer
n  = len(wp.Layers.GetAllObjectsOnLayer(5))
wp.Layers.MoveDisplayableObjects(5, [body])  # 搬层，之后 GetAllObjectsOnLayer 计数 +1
cat = wp.Layers.CreateCategory("PT_CAT", "probe category", [1, 2, 3, 4, 5])
cat.SetState(NXOpen.Layer.State.Hidden)  # 整类开关：成员层状态立即变 3
members = cat.GetMemberLayers()  # → [1,2,3,4,5]
```
  `Layer.State` = `Hidden / Visible / Selectable / WorkLayer`；`wp.Layers.GetStates()` → `StateCollection`。

### 1.8 稳定引用与验证习惯

- 引用原点/基准面/最早根特征；圆角边、阵列面、会被布尔吃掉的面禁止作基准；外部投影少用。
- 基准最少必要：能引用已有稳定几何就不新建 Datum Plane/Axis。

```python
dp = wp.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)
dp.SetFaceAndOffset(face, 25.0, "")  # (Face, Double 偏置, String 备选名)
f  = dp.CommitFeature(); dp.Destroy()  # → 'DATUM_PLANE'
dp2.SetPointAndDirection(point, direction)  # (Point, Direction)
```
  独立基准坐标系用 `Planes.CreatePlane`（§3.2）；`DatumCsysBuilder` 只暴露 `Csys` 拾取，无既有坐标系时报 `Reference coordinate system undefined.`。
- 边建边查：体数/孔壁数/倒圆面数与设计值比对；**布尔后断言体数**（§2.5）。
- builder 异常先 `print([a for a in dir(builder) if not a.startswith('_')])`。
- 批处理改过的 prt 不热重载。

### 1.9 重复特征决策表（先决策再动手）

按分布选型（详见 §3.1a-§3.2）：矩形/栅格 `Linear`、圆周 `Circular`、沿曲线 `AlongPath`、螺旋 `Helix`、正多边形 `Polygon`、指定坐标 `General`、跟随已有阵列 `Reference`、螺旋线 `Spiral`；不规律且仅 2-3 件逐个创建。镜像走 §3.2 的 `MirrorFeatureBuilder`（`PatternEnum.Mirror` 的 `CommitFeature()` 必抛 `Feature cannot be mirrored.`）。

`PatternEnum` 全集：`AlongPath / Circular / General / Helix / Linear / Mirror / Polygon / Reference / Spiral`。`Axes.CreateAxis` 首参传 `Point3d`（传 `Axis.Null` 内存访问违例）。

### 1.10 交付自检清单（逐项过）

- 脚本 `run_journal_batch.bat`/`check_journal.py` 通过；其余见 §6。

## 2. 特征配方

### 2.1 方块 / 圆柱

```python
blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
blk.CommitFeature(); blk.Destroy()
# ⚠ Length/Width/Height、Diameter/Height 只读（AttributeError）：用 SetLength/SetWidth/SetHeight 或 SetOriginAndLengths。
# ⚠ CylinderBuilder 先建圆曲线赋 Arc 再拉伸。
# 坐标必须 float（0.0），长度必须 str（"100"）；SKILL.md §3 路线约束 7/8。
```

方块布尔用 `SetBooleanOperationAndTarget`（§2.5）：

```python
cut = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
cut.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
cut.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Subtract, target_body)
cut.CommitFeature(); cut.Destroy()
```

### 2.1b 圆柱 / 圆锥 / 表达式绑定补充

- `CylinderBuilder.Types` 只有 `ArcAndHeight`/`AxisDiameterAndHeight`，无 `BooleanType`。
- 无 UF `CreateCone`/`CreateCylinder`；圆锥用 `ConeBuilder.Types.DiametersAndHeight` + `Axes.CreateAxis(Point3d, Vector3d, UpdateOption)`。
- `Diameter`/`Height` 只读，`.Expression.RightHandSide` 可绑定（`cyl.Diameter.RightHandSide = "D_Base"`）。
- Builder 首参传 `NXOpen.Features.Feature.Null`（Cylinder/Block 等）、`NXOpen.Features.Cone.Null`（Cone）；`None` 报 TypeError。`Direction` 收 `Vector3d`（传 `Direction` 报 "Expecting NXOpen.Vector3d type"）。

### 2.2 拉伸（Section 路线）

- `Sections.CreateSection(0.0009, 0.001, 0.01)`：3 容差重载。
- `ExtrudeBuilder.Section` 恒为 `None`：先建独立 Section，再赋给 builder。
- `AddToSection` 的 seed/connector 传 `NXObject.Null`（`None` 报 `No overload matches`）。
- 显式设 `Direction`（否则 `No axis selected`）。
- `Curves.CreateArc` 的 startAngle/endAngle 用**弧度**。
- 示例：`scripts/tests/01_bracket.py`。

### 2.2b 多截面放样（ThroughCurves）

```python
secs = wp.Sections.CreateSectionsUsingCurves(
    curves, NXOpen.SectionCollection.LoopOption.Separate, 0.01, 0.01, 0.5)
# curves：同向、同起点、同段数的闭合曲线（精确直线/圆弧或样条）
tb = wp.Features.CreateThroughCurvesBuilder(NXOpen.Features.Feature.Null)
tb.BodyPreference = NXOpen.Features.ThroughCurvesBuilder.BodyPreferenceTypes.Solid
for sec in secs:
    tb.SectionsList.Append(sec)
tb.Validate()
tb.CommitFeature(); tb.Destroy()
```

- `CreateSectionsUsingCurves` 返回 `Section` 对象列表（不是元组）；参数依次为曲线、`LoopOption.Separate`、链容差、距离容差、角度容差（弧度）。
- 截面必须同向、同起点、同段数；方向翻转会让放样自交。
- 闭合环不要做成单条周期闭合样条：拆成“开链 + 接缝处一段”两个截面元素再放样，否则 `ThroughCurves` 报 "Unable to reference edge"（同一对截面拆缝后可放样）。
- 相邻截面面积突变（接近 3 倍）时多截面放样报 "Cannot create B-surface by through curves"；在突变处分段放样或补中间截面。
- 提交前逐张校验闭合与方向；`BodyPreference=Solid` 出实体，否则出片体。
- 端部形状（圆头、C 形开口）直接进末截面，或按端面轮廓单独切除；不要用球冠/方块求交二次修形。

### 2.3 孔（Hole 特征 + 十字辅助线）

```python
hb = wp.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
hb.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
hb.SetSimpleHole(NXOpen.Point3d(x, y, z), False, placementFace, "8")  # 直径可传表达式名
hb.SetThruFace(bottomFace)
hb.HoleLocation = NXOpen.Point3d(x, y, z)
hb.CommitFeature(); hb.Destroy()
```

⚠ **孔位贴边 = 零壁厚**（`... zero wall thickness`）；孔边至少留壁厚（≥10 mm）。

十字辅助线：

```python
# 1) 每孔 2 条互相垂直短线段，与轮廓一起入草图
for cx, cy in hole_positions:
    h = 6.0
    cross.append(wp.Curves.CreateLine(NXOpen.Point3d(cx-h, cy, 0), NXOpen.Point3d(cx+h, cy, 0)))
    cross.append(wp.Curves.CreateLine(NXOpen.Point3d(cx, cy-h, 0), NXOpen.Point3d(cx, cy+h, 0)))
# 2) 转参考线：虚线显示、不参与拉伸
cb = wp.Sketches.CreateConvertToFromReferenceBuilder()
for rc in cross: cb.InputObjects.Add(rc)
cb.OutputState = NXOpen.ConvertToFromReferenceBuilder.OutputType.Reference
cb.Commit(); cb.Destroy()
# 3) 完全固定防漂移（枚举成员是 NotSet 不是 None）
for rc in cross:
    sketch.CreateFullyFixedConstraints(
        NXOpen.Sketch.ConstraintGeometry(rc, NXOpen.Sketch.ConstraintPointType.NotSet, 0))
# 4) 孔心 = 水平辅助线 StartPoint/EndPoint 中点，传入 SetSimpleHole
```

⚠ Hole 位置是 WCS 点，无与草图几何关联的 API → 改孔位 = 改辅助线坐标后重跑。

### 2.4 倒圆 / 倒角

```python
rule = wp.ScRuleFactory.CreateRuleEdgeDumb(edges)  # 或 CreateRuleEdgeFace(faces)
col = wp.ScCollectors.CreateCollector()
col.ReplaceRules([rule], False)  # 第二参数必须 False（SKILL.md §3）
eb = wp.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
eb.AddChainset(col, "2.0")  # ⚠ 没有 Radius 属性，半径经 AddChainset 传
eb.CommitFeature(); eb.Destroy(); col.Destroy()
```

倒角（已有部件；打开见 SKILL.md §3）：

```python
body = [b for b in part.Bodies][0]
faces = [f for f in body.GetFaces() if f.SolidFaceType == NXOpen.Face.FaceType.Cylindrical]
rule = part.ScRuleFactory.CreateRuleEdgeFace(faces)  # 选中孔口棱边
collector = part.ScCollectors.CreateCollector()
collector.ReplaceRules([rule], False)  # 第二参数必须 False
builder = part.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.OffsetAndAngle
builder.FirstOffset = "1.0"
builder.Angle = "45.0"
builder.SmartCollector = collector
builder.CommitFeature()
builder.Destroy(); collector.Destroy()
```

- ⚠ `Edge.GetVertices()` 返回 `Point3d` 列表。
- 角点处的边不能逐条倒圆：同一顶点的相邻边要放进同一个 ChainSet，否则报 "Unable to terminate the blend faces"；重建件上后补圆角受相邻拓扑影响大，能在截面轮廓里带的圆角（腔口/槽口小半径）优先画进轮廓。
- 验证：Ø12 孔口 dV=−39.794；直边 dV=−60.000；面数 = 双棱边 2、单直边 1；倒角锥面 type **17**、直边倒角平面 22。

### 2.5 布尔与孔壁识别

**布尔路线**：`CreateBooleanBuilder(NXOpen.Features.BooleanFeature.Null)` → `SetBooleanOperationAndTarget(Subtract/Unite, target)` → `CommitFeature()` → 断言体数。方块布尔只用这条入口；`BooleanOption.Type`+`SetTargetBodies` 会静默不生效（体数 1→2）。

- 工具体与目标体必须**真正体积相交**；面/点/线接触会静默留两个体，工具体在外报 `Tool body completely outside target body`。
- 相切工具体被拒（`... zero wall thickness.`）：留间隙或先合并；Ø60 凸台改 Ø56（留 4 mm）。
- 孔壁识别：遍历 `GetFeatures()` 找 `FeatureType == "SUBTRACT"` 后取 `GetFaces()`，或 Hole 特征用 `AskFaceData` 按半径过滤（§5）；不要按"所有圆柱面"过滤。
- 依次合并每步接触当前材料；命名体数与实际体数不符时查孤立体。

## 3. 阵列 / 镜像 / 旋转 / 衍生特征

### 3.1 线性 / 圆周阵列（PatternFeatureBuilder）

```python
pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
pb.FeatureList.SetArray([seed_feature])  # 依赖特征一起入列: [seed_hole, blend_feature]
pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
pd = pb.PatternService
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Linear  # 或 Circular
r = pd.RectangularDefinition
r.XDirection = wp.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
r.XSpacing.SpaceType = NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Pitch
r.XSpacing.PitchDistance.RightHandSide = "30"; r.XSpacing.NCopies.RightHandSide = "3"
r.YSpacing.NCopies.RightHandSide = "1"
pb.CommitFeature(); pb.Destroy()
# 圆周: cd = pd.CircularDefinition; cd.RotationAxis = axis;  # axis 类型 NXOpen.Axis
#        axis = wp.Axes.CreateAxis(NXOpen.Point3d(0,0,0), NXOpen.Vector3d(0,0,1),
#                                  NXOpen.SmartObject.UpdateOption.WithinModeling)
#        cd.AngularSpacing.SpaceType=Pitch; PitchAngle/NCopies 走 RightHandSide
```

⚠ 2D 线性阵列必须 `rect.UseYDirectionToggle = True` 并给 YDirection。
⚠ 依赖特征一起阵列（打孔→倒圆）自带倒圆。
⚠ 验证：孔壁 type=16 半径=HD/2；孔口倒圆 type=19，`radius` = 主半径 = HD/2 + 倒圆半径。
⚠ 圆周间距用 `PitchDistance`（`CountAndPitch` 不存在）。

### 3.1a 沿路径阵列（`AlongPath`）

```python
line = wp.Curves.CreateLine(NXOpen.Point3d(150.0, 0.0, 10.0), NXOpen.Point3d(250.0, 0.0, 10.0))
# pb/pd 建法同 §3.1
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.AlongPath

apd = pd.AlongPathDefinition  # 另一个可用成员是 pd.HelixDefinition
rule = wp.ScRuleFactory.CreateRuleCurveDumb([line])
sec = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
sec.AddToSection([rule], line,
                 NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                 NXOpen.Point3d(150.0, 0.0, 10.0),
                 NXOpen.Section.Mode.Create, False)
apd.XPath = sec  # 路线 1：赋值（可写引用属性）
# 路线 2（等效）：apd.XPath.AddToSection([rule], line, ..., NXOpen.Section.Mode.Create, False)
pb.CommitFeature(); pb.Destroy()
```

- `AddToSection` 签名 `(rules, seed, startConnector, endConnector, helpPoint, Mode, chainWithinFeature)`；第 6 参 `NXOpen.Section.Mode`。
- 引导线 `CreateRuleCurveDumb([line])`；`ScRuleFactory` 无 point 规则（§4.4）。`XPath` 赋值与 `AddToSection` 等效。
- ⚠ 间距显式设：`XOnPathSpacing` 的 `SpaceType` 用 `PatternSpacingSpacingType`（`Offset=0` 默认 / `Span=1` / `PitchAndSpan=2` / `Pitch=3` / `List=4`）；距离槽写 `.Expression`，默认 `IsPercentUsed=True`（50 = 50%）。
- Pitch：`IsPercentUsed=False` + `Expression.RightHandSide="<mm>"`；Span：`NCopies` 含种子；Offset：忽略距离槽，改 `NCopies` 无效。
- 超末端副本丢弃；节距按实际路径长度。
- ⚠ 无 `CreateSlotBuilder` → 槽用方块布尔差（§2.5）。

### 3.1b 原生螺旋阵列（`PatternType=Helix`）

```python
# pb/pd 建法同 §3.1（FeatureList=[seed_feature]）
# ⚠ 轴工厂签名 (Point3d, Vector3d, UpdateOption)。首参传 NXOpen.Axis.Null 会崩
#   "NXException: Internal error: memory access violation"；DatumAxis 赋 RotationAxis 被类型拒绝。
axis = wp.Axes.CreateAxis(NXOpen.Point3d(0.0, 0.0, 0.0),  # 轴上一点
                          NXOpen.Vector3d(0.0, 0.0, 1.0),  # 轴方向
                          NXOpen.SmartObject.UpdateOption.WithinModeling)  # -> NXOpen.Axis
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Helix
hd = pd.HelixDefinition  # NXOpen.GeometricUtilities.HelixPattern
hd.SizeOption = NXOpen.GeometricUtilities.HelixPattern.SizeOptions.CountHelixPitchAndTurns
hd.CountOfInstances.RightHandSide = "4"  # 表达式：没有 SetRightHandSide
hd.NumberOfTurns.RightHandSide    = "1"
hd.HelixPitch.RightHandSide       = "20"  # 每整圈升高（mm）
hd.RotationAxis = axis  # 必须是 NXOpen.Axis
pb.CommitFeature(); pb.Destroy()
```

- `CountOfInstances` 含种子：角步距 = `360/(CountOfInstances-1)`；`z=p·θ/2π`。
- `SizeOptions`：`AngleHelixPitchAndSpan / AngleHelixPitchAndTurns / CountAngleDistance / CountHelixPitchAndSpan / CountHelixPitchAndTurns`。
- ⚠ `RotationAxis` 必须给；留空不报错但无副本，用体数判定。

### 3.1c 正多边形阵列（`PatternType=Polygon`）

```python
GU = NXOpen.GeometricUtilities
# pb/pd 建法同 §3.1
pd.PatternType = GU.PatternDefinition.PatternEnum.Polygon
pg = pd.PolygonDefinition  # NXOpen.GeometricUtilities.PolygonPattern
pg.RotationAxis = axis  # 必须是 NXOpen.Axis，且**过原点**
pg.NumberOfSides.RightHandSide = "6"  # ⚠ 表达式：给 int 报 Expecting Unicode str type, found int
pg.PolygonSizeOption = GU.PolygonPattern.SizeOptions.Inscribed
pg.PolygonSpacing.SpaceType = GU.PatternSpacingSpacingType.PolygonCountPerSide
pg.PolygonSpacing.NCopies.RightHandSide = "2"  # ⚠ 也是表达式
pb.CommitFeature()
```

**布点**：顶点在半径 R（种子质心到轴距离）的圆上，相位由种子决定；每边被 `NCopies-1` 等分；总数 = `边数×(NCopies-1)`。

示例（N=6）：`NCopies=2/3/4` → 6/12/18 件。

- `NCopies` 是每边等分数，至少 2（`=1` 被拒 `Update undo happened.`）。
- ⚠ `NCopies≥4` 角距不均匀（沿边等弦长排）；轴必须过原点，`RotationCenter` 救不回来 → 用 `Circular` 或搬到原点。
- `PolygonSizeOption` 只有 `Inscribed`/`Circumscribed`，不改半径；`SpaceType` 必须设 `PolygonCountPerSide`（默认 `Offset` 会排错）。
- `PolygonPattern` 成员：`Flip / HorizontalRef / Null / NumberOfSides / PolygonSizeOption / PolygonSpacing / RadialSpacing / RotationAxis / RotationCenter / SizeOptions / Tag / UseRadialDirectionToggle / Validate`。

### 3.1d 指定目标点阵列（`PatternType=General`）

```python
GP = NXOpen.GeometricUtilities.GeneralPattern
# pb/pd 建法同 §3.1
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.General
gd = pd.GeneralDefinition  # NXOpen.GeometricUtilities.GeneralPattern
gd.FromLocationType = GP.FromLocationOptions.Point  # 种子上的参照位置
gd.FromLocationPoint = part.Points.CreatePoint(NXOpen.Point3d(*FROM))  # 参照点坐标
targets = [part.Points.CreatePoint(NXOpen.Point3d(*p)) for p in TO_POINTS]
rule = part.ScRuleFactory.CreateRuleCurveDumbFromPoints(targets)
gd.ToPoints.AddToSection([rule], targets[0], NXOpen.NXObject.Null,
                         NXOpen.NXObject.Null, NXOpen.Point3d(0.0, 0.0, 0.0),
                         NXOpen.Section.Mode.Create, False)
pb.CommitFeature()
```

- 目标点是 `NXOpen.Section`：把种子参照点搬到每个目标点，不旋转、种子不在结果里。
- ⚠ `ToPoints` 留空被拒（`Update undo happened.`）；提交失败会污染同会话后续属性报错 → 每工况独立部件 + builder。
- `CommitFeature()` 返回特征标签，`part.Bodies` 是体标签。

### 3.1e 引用已有阵列（`PatternType=Reference`）

```python
# pb/pd 建法同 §3.1
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Reference
rd = pd.ReferenceDefinition  # NXOpen.GeometricUtilities.ReferencePattern
rd.ReferencedPattern.SetValue(ref_pattern_feature, NXOpen.View.Null,
                              NXOpen.Point3d(0.0, 0.0, 0.0))
rd.SetBaseInstance(1, 0)  # 可选；不设就是默认基准实例
pb.CommitFeature()
```

- ⚠ `ReferencedPattern` 是 `SelectNXObject` 类选择对象（只读）：`SetValue(obj, view, point)` 灌值，`GetValue()` 读回三元组。
- `SetBaseInstance(1,0)` 把第 1 件映射到种子并平移一个节距；`ResetBaseInstance()` 复位。
- ⚠ 种子即基准实例，新增副本数 = 件数 − 1。

### 3.1f 螺旋阵列（`PatternType=Spiral`）

```python
# pb/pd 建法同 §3.1
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Spiral
sd = pd.SpiralDefinition  # NXOpen.GeometricUtilities.SpiralPattern
sd.SizeSpiralType = NXOpen.GeometricUtilities.SpiralPattern.SpiralDefineSize.NumberOfTurns
sd.NumberOfTurns.RightHandSide = "1"  # 表达式；TotalAngle 是另一种定尺方式
sd.RadialPitch.RightHandSide = "10"
sd.PitchAlongSpiral.SpaceType = <PatternSpacing SpacingType>.Pitch
sd.PitchAlongSpiral.OnPathPitchDistance.Expression.RightHandSide = "20"
sd.SpiralNormal = <NXOpen.Direction>
sd.HorizontalRef.HorizontalRefVector = <NXOpen.Direction>  # 这一条是工作形态
pb.CommitFeature()
```

- ⚠ 水平参考填 `HorizontalRef.HorizontalRefVector`（Direction）；不填报 `No section curves or points created.`。
- ⚠ 不按阿基米德螺线算：半径对转角不单调，可产出零实例；严格螺线用 `General`。

### 3.2 特征级镜像

```python
plane = wp.Planes.CreatePlane(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
mb = wp.Features.CreateMirrorFeatureBuilder(NXOpen.Features.Feature.Null)
mb.FeatureSet.SetArray([half_feature])
mb.PlaneOption = NXOpen.Features.MirrorFeatureBuilder.PlaneOptions.New
mb.PlaneConstructor = plane
mb.CommitFeature(); mb.Destroy()
```

⚠ 草图级镜像不可用（§4.3）；对称用 Symmetric 规则或手工曲线。

### 3.3 旋转体（UF 路线）

```python
# 用 UF Modl.CreateRevolved；RevolveBuilder.CommitFeature 批处理报内存访问违例
#   （Axes.CreateAxis 的轴也崩；DatumAxis 赋 Axis 属性被类型拒绝）。
ufs = NXOpen.UF.UFSession.GetUFSession()
feats = ufs.Modl.CreateRevolved(
    [c.Tag for c in profile_curves], ["0.0", "360.0"],
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],  # 原点 + 旋转轴方向
    NXOpen.UF.ModlFeatureSigns.NULLSIGN,  # ⚠ 枚举是 ModlFeatureSigns，不是 FeatureSigns
)
# ⚠ 剖面含落在轴上的边或带台阶/凹剖面 -> "Cannot create Swept geometry"；凸剖面（矩形）可用。
#   复杂旋转体 = 多段凸剖面旋转 + BooleanBuilder Unite。
```

### 3.4 抽壳（Shell）与拔模（Draft）（`scripts/tests/15_shell_draft.py`）

**容差默认 `0.0`，不改必报错**（`ShellBuilder.Tolerance`→"Tolerance error"；`DraftBuilder.AngleTolerance`→"Angle tolerance is too small"）。

抽壳（100×60×20 移除顶面、壁厚 2.0 → `V=23232.000`）：

```python
sb = wp.Features.CreateShellBuilder(NXOpen.Features.Feature.Null)
sb.Tolerance = 0.01  # ⚠ 默认 0.0
sb.Body = body
sb.SetDefaultThickness("2.0")  # ⚠ 厚度传 str 表达式
col = wp.ScCollectors.CreateCollector()
col.ReplaceRules([wp.ScRuleFactory.CreateRuleFaceDumb([top_face])], False)
sb.RemovedFacesCollector = col  # 要"挖掉"的面；不设 = 闭腔抽壳
sb.CommitFeature(); sb.Destroy(); col.Destroy()
```

拔模（100×60×20 四侧面 5°、固定底面 → `V=114482.3710`）：

```python
db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)
db.AngleTolerance = 0.5  # ⚠ 默认 0.0
db.DistanceTolerance = 0.001  # ⚠ 默认 0.0
db.TypeOfDraft = NXOpen.Features.DraftBuilder.Type.Face
db.DraftIsoclineOrTruedraft = NXOpen.Features.DraftBuilder.Method.TrueDraft
db.Direction = wp.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 0.0, 1.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
db.StationaryEntity = bottom_face  # ⚠ 必须传 Face 对象，不能传 SC 收集器
ecs = wp.CreateExpressionCollectorSet(
        collector_of_side_faces, "5", "", 0)  # 角度传 str；unitsType 传 ""
db.FaceSetAngleExpressionList.Append(ecs)
db.CommitFeature(); db.Destroy()
```

**拔模必设项**：

- 拔模方式设 `DraftIsoclineOrTruedraft`（`Method` 只读）：`TrueDraft`/`Isocline`。
- `StationaryEntity` 传 `Face`：传 `ScCollector` 报 `First parameter is invalid`，传 `Direction`/`DatumPlane` 或不设报 `Draft reference is missing.`。
- `StationaryReference`/`StationaryPartingReference` 只读，`PartingReference` 只读；固定/分型基准只走 `StationaryEntity`。
- 角度经 `CreateExpressionCollectorSet(collector, 角度串, unitsType, 0)` 追加到 `FaceSetAngleExpressionList`，按度解释。

**符号与解析式**：`StationaryEntity` = 固定面、`Direction` = 拔模方向（+Z）。四侧面拔模、底面固定时

```
t = tan(角度)  # 带符号；正角收缩、负角张开
V = V0 − 64000·t + (32000/3)·t²  # V0=120000（100×60×20）
```

校验：5° → 114482.3710、−5° → 125680.9200、10° → 109046.7127。**正角 = 沿 Direction 向上收口**。

### 3.5 质量属性校验（交付前数值验证）

```python
uc = wp.UnitCollection
units = [uc.FindObject(n) for n in
         ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
mp = wp.MeasureManager.NewMassProperties(units, [0.99], [body])  # ⚠ 容差是 list，不是标量
print("V=%.3f A=%.3f C=(%.3f,%.3f,%.3f)" % (mp.Volume, mp.Area, mp.Centroid.X, mp.Centroid.Y, mp.Centroid.Z))
```

- 基线（100×60×20）：`V=120000.000`、`A=18400.000`、质心 `(50,30,10)`。
- ⚠ `tolerances` 是数组 `[0.99]`（签名 `(Unit[], Double[], IBody[])`）；多体测量返回各体之和。
- 无 `uf.Modl.AskBoundingBox`；包围盒用 `GetEdges()` → `GetVertices()` 取 min/max。

### 3.6 去参（改哑体，慎用）

```python
rpb = wp.Features.CreateRemoveParametersBuilder()
rpb.Objects.Add(bodies)  # 传入体列表
rpb.Commit(); rpb.Destroy()
```

⚠ 去参销毁特征树，与历史模式（§6）冲突——仅用户要求哑实体时用。

### 3.7 渐开线直齿圆柱齿轮（标准层 `nxlib.modeling.involute_gear`）

```python
from nxlib.modeling import involute_gear
res = involute_gear(wp, m=2, z=20, alpha_deg=20, b_width=20, bore_d=20,
                    hub_d=40, hub_len=30, z_offset=0.0)
```
- 无变位、无根切保护；改 `p_gear_*` 表达式可联动；`hub_d`/`hub_len` 为 0 时不建轮毂。
- 验收：34 号用例（体积对 z 敏感 ~5%/齿，容差 ±2%）；齿面表达式不能写 `atan`。

## 4. 草图与表达式

### 4.1 表达式驱动链路

```python
unit = wp.UnitCollection.GetBase("Length")  # ⚠ 不是 GetBase("Millimeters")
wp.Expressions.CreateSystemExpressionWithUnits("L_Plate = 100.0", unit)
# 特征尺寸直接引用表达式名：Extrude Limits RHS="T"、Hole SetSimpleHole 直径传 "HD"
expr.RightHandSide = "8"  # 改值
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "upd")
session.UpdateManager.DoUpdate(mark)  # ⚠ Session 属性是 UpdateManager（不是 Update）
```

- 单位按量纲传：角度用 `GetBase("Angle")`；`RightHandSide` 支持表达式名、`.Value` 只接受数值 → **统一用 `RightHandSide`**。
- 硬限制：
  1. 表达式名**大小写不敏感**（`D` 存在时建 `d` 报 "expression variable already exists"）。
  2. NX12 **无 atan/acos/asin/atan2**；渐开线改压力角参数化 `r=rb/cosα, φ=ψb−(tanα−α)`。**两套参数域不可混用**：压力角域上限 `degrees(atan(umax))`（31.32°），给成 `umax*180/π`（34.81°）会越过齿顶圆，报 "Section curves are not connected each other"。
  3. 规律曲线 `ZLaw` 缺常量报 "Expression does not exist for law" → `ZLaw.LawType=Constant` + `Value.RightHandSide="0"`。
  4. `FileNew` Commit 不落盘，以 `part.Save()` 为准。

### 4.2 自动约束 / 自动标注（替代手加约束）

```python
wp.Sketches.CreateAutoConstrainBuilder().Commit()  # 自动几何约束
adb = wp.Sketches.CreateAutoDimensionBuilder()
adb.SelectionObject.SetArray(curves)
adb.SetRules([NXOpen.Sketch.AutoDimensioningRule.Length,
              NXOpen.Sketch.AutoDimensioningRule.Symmetric])
adb.DimensionType = NXOpen.SketchAutoDimensionBuilder.DimType.Driving
adb.Commit(); adb.Destroy()  # 自动生成驱动尺寸表达式
```

⚠ AutoDimension 非确定性：偶发 0 尺寸 → `UnderConstrained`（但 dof=0）。`GetStatus()` 非 `WellConstrained` 时对轮廓线 `CreateFullyFixedConstraints` 兜底（已有驱动尺寸时勿加）。

### 4.3 草图尺寸与约束路线

- 尺寸与约束统一走 §4.2 的 `CreateAutoConstrainBuilder` + `CreateAutoDimensionBuilder`；`GetStatus()` 非 `WellConstrained` 时对轮廓线 `CreateFullyFixedConstraints` 兜底。
- `Sketch.CreateDimension` / `CreateRadialDimension`、`SketchLinearDimensionBuilder.FirstAssociativity` / `SecondAssociativity`、`SketchConstraintBuilder.GeometryToConstrain` / `GeometryToConstrainTo` 批处理不可用（只读或 `No overload matches`），不要在这条路线上尝试。
- 草图级镜像走不通（`SketchMirrorPatternBuilder.DirectionObject` 只读）；对称件用特征级 `MirrorFeatureBuilder`（§3.2）。
- 面查询用 §5 的 `AskFaceData`（`Part.Faces.FindFace` / `Face.IsPointOnFace` 不存在）。

### 4.4 孔与螺纹路线（`HolePackage`；`scripts/tests/26_hole_package.py`）

- 螺纹用 HolePackage：`CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)`，`Types` = `DrillSizeHole / GeneralHole / HoleSeries / ScrewClearanceHole / ThreadedHole`（NX12 没有 `Thread`/`CreateThreadBuilder`/`ThreadFeatureBuilder`）。
  ⚠ 枚举用模块级类（`HolePackageBuilder.Types.ThreadedHole`、`…HoleDepthLimitOptions.Value`、`…ThreadLengthOptions.Standard`）；写成 `b.Types()` 抛 `NXException: instances of NX enums can not be created` 并中断 journal。

孔位：只读 `Section`，点用 `ScRuleFactory` 灌入：

```python
pt   = wp.Points.CreatePoint(NXOpen.Point3d(30.0, 20.0, 20.0))
rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])  # 点规则在这里
b.HolePosition.AddToSection([rule], pt, NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                            NXOpen.Point3d(30.0, 20.0, 20.0), NXOpen.Section.Mode.Create, False)
bt = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
b.BooleanOperation.SetBooleanOperationAndBody(bt.Subtract, body)  # 目标体在这里
b.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(pt, NXOpen.Vector3d(0.0, 0.0, -1.0))
b.HoleDepthLimitOption = NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.Value
b.Tolerance = 0.0254  # ⚠⚠ 必填（距离公差 double）：不写 Validate 报
  #   "The Tolerance Specification requires three numbers"
b.Validate(); b.CommitFeature()
```

- ⚠ 无 `PropertyTable`；深度是 Expression：`b.EndHoleData.HoleDepth.RightHandSide = "15"`（`ThreadDepth / TapDrillDiameter / ThreadedHoleDepth / DrillSizeHoleDepth / GeneralSimpleHoleDepth` 同理）；直接赋值报 not writable；孔深/螺纹段深分居 `EndHoleData`/`StartHoleData`/`MiddleHoleData`。

| 类型 | 必须给什么 | 结果 |
| --- | --- | --- |
| `GeneralHole` | `GeneralSimpleHoleDiameter / GeneralSimpleHoleDepth / GeneralTipAngle` | Ø10 × 15 精确；**首选** |
| `DrillSizeHole` | `DrillSizeStandard="ISO"` + `DrillSizeFitOption="Exact"` + `DrillSize` 标签（`"10"`）**且** `DrillSizeHoleDiameter/Depth` | 只给标签 → 默认 Ø11 贯通；只给 Expression → `Standard data not found` |
| `ScrewClearanceHole` | `ScrewStandard="ISO"` + `ScrewType="General Screw Clearance"` + `ScrewSize="M10"` + `ScrewFitOption="Normal (H13)"` | 过孔 **Ø11** |

- ⚠ `ScrewStandard/ScrewType/ScrewSize/ScrewFitOption` 仅螺钉过孔适用；成员名 `ScrewFitOption`，无 `ScrewFit`。
- ⚠ 标准名须匹配 `modeling_standards\*.xml` 的 `Standard=`：钻孔 `nx6_Drill_Size_Hole_Standard.xml`（`ISO`，尺寸 `10`/`10.2`，`Fit` 仅 `Exact`）；螺纹孔 `nx502_Threaded_Hole_Standard.xml`（`Metric Coarse`，`M10 x 1.5`）。写错 → `Standard data not found`；别用 `thd_metric.dat`。

**螺纹孔走替代路线**：底孔 `GeneralHole`（M10×1.5 底孔 Ø8.5）或 `DrillSizeHole`，螺纹用标注（`Annotations`/`SymbolicThread`），装配用 `ScrewClearanceHole`。`ThreadedHole` 的 `Validate()` 通过但 `CommitFeature()` 必抛 `memory access violation`，树里只留无几何 `HOLE PACKAGE`；崩溃后退出码 1（日志仍写 successful）→ 按令牌校验，`UndoMark`/`UndoToMark` 撤残废特征。
⚠ `AskFaceData` 的 box 是 `(xmin, ymin, zmin, xmax, ymax, zmax)`，配对 **(0,3)/(1,4)/(2,5)**。

## 5. 几何查询工具

```python
ufs = NXOpen.UF.UFSession.GetUFSession()
d = ufs.Modeling.AskFaceData(face.Tag)
# ⚠ UF 会话属性是 Modeling 不是 Modl（Modl.AskFaceData 不存在）
# 返回 (type, point, dir, box, radius, rad_data, norm_dir)：平面 22、圆柱面 16、圆环面 19
# dir 是 list 不是 Vector3d；圆环面 radius=主半径（孔半径+倒圆半径）
# ⚠ rad_data = 圆环小半径 / 圆锥半角；norm_dir 是 ±1 的面法向翻转标志，不是法向矢量
```

## 6. 可编辑性 / 可检查性铁律（用户会打开检查并修改生成的 prt）

- **历史模式**：可编辑特征构成；禁止哑体、转同步建模/去参。
- **草图完全约束**：`status, dof = sketch.GetStatus()`（不传参、返回元组）；`WellConstrained == 3` 且 dof=0。
- **参数可改**：顶层尺寸命名表达式（§4.1）；关键特征 `SetName`。
- **表达式必须被引用**：逐个改 ±10% 后 `DoUpdate`，体积必须变；体积不变的是死参数（特征里用了字面值），接进特征后再交付。
- **层间不要共面堆叠**：上游厚度表达式一变，共面处拓扑重排会让下游圆角边失效并回滚；让切除工具穿过目标面，或给 0.5 mm 重叠。
- **无垃圾几何**：未参与建模的线转参考线或删除。
- **交付前验证**：`08_editability_probe.py`；数值见 §3.5；`Point3d` 坐标不受表达式驱动。
