# 建模域：方法论 + 配方 + 坑位（NX 12 本机批处理实测）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。本文件按操作组织：§1 方法论（写任何 journal 前先过一遍），§2-§7 配方与坑位（⚠ 标注均为本机批处理实测结论，条目尾部为实测日期）。完整可跑示例见 `scripts/tests/01-03`；抽壳/拔模/质量属性校验/去参见 §3.4-§3.6，NX12 无螺纹 API 见 §4.4。

## 1. 建模方法论（风格约定，非 API；2026-08-05/06/23 三轮调研 + 本机实践对照）

来源：abctraining.in NX 工作流、UTEP Simple NX Parts、e-works《UGS NX 复杂壳体建模技术》、Saratech《NX 草图求解器》、Whole-Spec、GitHub parametric-modeling.md、Alibre/PTC Design Intent 指南。

### 1.1 规划与设计意图

- **特征树当源码**：先梳理设计意图 → 特征框架 → 原点/方向/基准 → 草图作根特征；自上而下可读、稳定基础在前、依赖细节在后。
- 动笔前过**设计意图四问**：① 特征相对什么定位？② 改 20 mm 什么该动、什么该留？③ 哪个数值最可能改（→ 命名表达式）？④ 草图离开自身还依赖什么（→ 外部引用风险）？再问"**哪个尺寸驱动整体、哪个保形**"——标注方案跟着答案走（轴类标总长 vs 各段长，改总长时行为完全不同）。

### 1.2 特征树顺序

- **主形状（加材）→ 功能切除（孔/槽）→ 支撑细节（筋/凸台）→ 倒角/倒圆最后 → 几何稳定后再阵列/镜像**。
- 计算重的特征（圆角、螺旋）放树尾（回放快、失败少）；复杂形状拆多个特征（机身/机翼/舱盖分开），禁止一个巨型操作。
- 倒圆顺序**大半径先、小半径后**；装饰性小圆角（<1 mm）不放草图（膨胀 DOF 且求解慢），一律 3D 特征且靠后。

### 1.3 特征语义

- **孔用 Hole 特征**，不用"拉伸圆柱+布尔求差"（Hole 带标准孔/沉头/螺纹语义，符合制造意图）；槽可用 Slot 设计特征或"草图+拉伸求差"（后者可编辑性更好）。
- **Pattern Feature 优于 Pattern Face**：前者复制特征树、实例可编辑、改种子全联动（PatternFeatureBuilder + OutputOption.PatternFeature 实测可用）；后者轻量但脆弱，仅特征级不可用时考虑。

### 1.4 重复特征

- **种子 + 依赖细节 + 阵列/镜像**：凡对称/规则分布的重复特征（孔、凸台、筋、槽、倒角、倒圆），一律"建 1 个种子 → 在种子上加依赖细节 → [种子, 细节] 一起阵列/镜像"，副本自动继承细节（如打孔→孔口倒圆→[孔+倒圆]一起阵列）。禁止逐个复制；禁止先阵列后补细节（副本漏细节、树臃肿、改一处要改 N 处）。
- 重复元素的位置用**构造几何驱动**（等长构造线/构造圆/十字辅助线，一改全动），比逐个标注可维护。

### 1.5 草图纪律

- **先几何约束后尺寸约束**：关系（同心、平行、对称、相等、中点、共线）用几何约束，数值（距离/角度/半径）才用驱动尺寸；目标 ~60-80% 自由度由几何约束吃掉。对称用 Symmetric/Equal，禁止两孔各标直径"手工同步"。
- **完全约束并锚定原点**（"内部全约束但整张图还是蓝"的常见原因是未锚原点）；闭轮廓才可拉伸成实体。
- **一个草图一个用途**：超过 ~15-20 实体就拆分；怪物草图难约束、求解慢、不可读。
- **同一基准面不叠多个草图**（2026-09-19 补，专业惯例）：第二个草图引用第一个草图的曲线极易随上游更新断链；要拆就拆放置面/拆特征，不拆同面草图。

### 1.6 对称件

- **画一半 + 镜像**：先建一半轮廓（含对称约束），几何稳定后再镜像（特征级 MirrorFeatureBuilder 实测可用；草图级镜像本机封装不可用，见 §4.3）。

### 1.7 参数化与命名

- **顶层参数命名表达式化**：前缀表意 + 显式单位（`L_Plate=100`、`D_Bore=8`、`T_Wall=5`、`N_Holes=4`）；任何数值出现 ≥2 次或可能被改 → 表达式（表达式本身就是设计意图文档，`pcb_clearance=0.4` 比裸数字有信息量）。次级尺寸公式派生，不在多个特征散写硬编码（表达式驱动全联动实测见 §4.1）。
- **命名与模板规范**：需要回看才能认出的特征必须 `SetName`（`Mounting boss`/`Bolt circle`，实测可用）；常见项目类型做模板；图层/命名/分组统一。
- **图层分类标准**（2026-09-19 补，NX 标准模板预定义惯例）：Solids 1-10 / Sheets（片体）11-20 / Sketches 21-40 / Curves 41-60 / Datums 61-80（共 256 层），按类别建 Layer Category 便于整层开关。批处理把草图曲线/基准放到对应层，可避免它们干扰拾取与视图投影。**已实测（2026-09-22）**：

```python
body.Layer = 5                        # 实体可写；✅ 但 Feature 没有 .Layer（AttributeError——
                                      # NXOpen.Features.Block 不是 DisplayableObject），
                                      # 想按特征归层只能在建它的那一层里直接设它产出的体
wp.Layers.WorkLayer = 1               # 工作层
wp.Layers.SetState(5, NXOpen.Layer.State.Hidden, True)   # ⚠ 第1参必须是 int（传 [5] → 0xC0000374 堆崩）
st = wp.Layers.GetState(5)            # Layer.State: Hidden=3 / Visible=2 / Selectable / WorkLayer
n  = len(wp.Layers.GetAllObjectsOnLayer(5))
wp.Layers.MoveDisplayableObjects(5, [body])              # 搬层，返回后 GetAllObjectsOnLayer 计数 +1
cat = wp.Layers.CreateCategory("PT_CAT", "probe category", [1, 2, 3, 4, 5])
cat.SetState(NXOpen.Layer.State.Hidden)                  # 整类开关：成员层状态立即变 3
members = cat.GetMemberLayers()                          # → [1,2,3,4,5]
```
  `Layer.State` 全集 = `Hidden / Visible / Selectable / WorkLayer`；`wp.Layers.GetStates()` 返回 `StateCollection`。

### 1.8 稳定引用与验证习惯

- **引用最稳的父几何**：原点/基准面/最早根特征 > 下游面/边；圆角边、阵列结果面、会被布尔吃掉的面都是"易变引用"，禁止作为定位基准。外部投影引用少用、有意为之；设计稳定后可改显式尺寸解耦。
- **基准最少必要**（2026-09-19 补，专业惯例）：能引用已有稳定几何（原点、已有基准面、早期根特征的平面）就不新建 Datum Plane/Axis：基准特征是树上的常驻节点，多一个就多一份"改上游时基准连带失效"的风险。**真基准特征 builder 已实测（2026-09-22）**：

```python
# 面 + 偏置（配对面选完就能提交）
dp = wp.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)
dp.SetFaceAndOffset(face, 25.0, "")          # (Face, Double 偏置, String 备选名)
f  = dp.CommitFeature(); dp.Destroy()        # → 特征类型 'DATUM_PLANE'

# 点 + 方向
dp2.SetPointAndDirection(point, direction)   # (Point, Direction)
```
  ⚠ **`DatumCsysBuilder` 是死路**：它只暴露一个 `Csys` 拾取（`dir()` 里跟坐标系相关的就只有 `Csys`/`ComponentsCreation`），不先给它一个既有坐标系就提交报 `NXException: Reference coordinate system undefined.`——批处理下没有可拾取的 Csys，所以建独立基准坐标系走既有路线（`Planes.CreatePlane` 智能平面，§3.2），不要用 DatumCsys 特征 builder。
- **先加材后减材；边建边查、验证后才保存**：每步打印关键统计（体数/孔壁数/倒圆环面数等）确认与设计值一致，再进下一步（批处理试跑即其自动化形式）；交付前确认无失败特征、无垃圾几何。**每次布尔后必须断言体数**（求差成功体数不变，静默失败则 +1，见 §2.5）。
- **builder 行为异常时 dump 它的属性表**：`print([a for a in dir(builder) if not a.startswith('_')])` 通常一行就能定位问题——例如方块同时有 `BooleanOption` 和 `SetBooleanOperationAndTarget`，前者被忽略、后者才生效（§2.5 就是这样发现的）。比反复试错快得多。
- 批处理改过的 prt，NX GUI **不热重载**，需重开文件才见更新（交付时提醒用户）。

### 1.9 重复特征决策表（先决策再动手）

| 分布形态 | 手段 | 要点 |
| --- | --- | --- |
| 矩形/栅格分布（孔阵、散热孔、加强筋排） | 2D 线性阵列 `PatternType=Linear` | 必须 `UseYDirectionToggle=True` 才启用 Y 方向；间距/数量用表达式 |
| 圆周分布（法兰孔、均布孔） | 圆周阵列 `PatternType=Circular` | `RotationAxis`（`wp.Axes.CreateAxis`）+ `AngularSpacing.SpaceType=Pitch` + `PitchAngle/NCopies` |
| 左右/上下镜像对称 | 特征级镜像 `MirrorFeatureBuilder` | 半剖草图+拉伸后镜像；`PlaneOption.New` + `PlaneConstructor=part.Planes.CreatePlane(...)` |
| 位置不规律且只有 2-3 件 | 直接逐个创建 | 位置用十字辅助线/表达式表达，不硬编码；件数再多又想留成一个可编辑的阵列特征，改用 §3.1d 的 `General` |
| 沿曲线分布（任意引导线） | 沿路径阵列 `PatternType=AlongPath`（2026-09-22 实测可跑） | 引导线装进 `PatternService.AlongPathDefinition.XPath`：**赋值**（`apd.XPath = sec`）与**原地 `AddToSection`**（`apd.XPath.AddToSection(...)`）两条路线均已受控 A/B 实测生效；**间距必须显式设 `XOnPathSpacing`，且取值默认按百分比解释**，见 §3.1a |
| 螺旋分布（绕轴升角） | 原生螺旋阵列 `PatternType=Helix`（2026-09-23 实测通过） | `HelixPattern.RotationAxis` 只收 `NXOpen.Axis`，工厂是 `wp.Axes.CreateAxis(Point3d, Vector3d, UpdateOption)`；`SizeOption=CountHelixPitchAndTurns` + `CountOfInstances/NumberOfTurns/HelixPitch`（表达式）见 §3.1b |
| 正多边形边等分（六角螺栓头、方形座） | 正多边形阵列 `PatternType=Polygon`（2026-09-23 实测通过） | 件数 = `边数×(NCopies-1)`，布置半径 = 种子质心到轴的距离，相位跟着种子；轴必须过原点，见 §3.1c |
| 位置不规律且各有指定坐标 | 目标点阵列 `PatternType=General`（2026-09-23 实测通过） | 目标点是 `NXOpen.Section`，用 `CreateRuleCurveDumbFromPoints` + `AddToSection` 填；参照点是"被搬走的那个点"，见 §3.1d |
| 跟着另一个已有阵列的布置排 | 引用阵列 `PatternType=Reference`（2026-09-23 实测通过） | 被引用的阵列装进 `ReferenceDefinition.ReferencedPattern`（**选择对象，用 `SetValue` 灌**）；种子兼作基准实例，`SetBaseInstance(i, j)` 换基准，见 §3.1e |
| 螺旋线分布 | 螺旋阵列 `PatternType=Spiral`（2026-09-23 实测通过） | 水平参考填 `HorizontalRef.HorizontalRefVector`（Direction），不填必报 `No section curves or points created.`；布置不按原型阿基米德螺线，见 §3.1f |

⚠ 阵列类型枚举 `PatternDefinition.PatternEnum` 全集（2026-09-22 实测）：`AlongPath / Circular / General / Helix / Linear / Mirror / Polygon / Reference / Spiral`。九个成员里**八个**已实测跑出实例（`Linear`/`Circular` 见 §3.1，`Helix` §3.1b、`Polygon` §3.1c、`General` §3.1d、`Reference` §3.1e、`Spiral` §3.1f，`AlongPath` §3.1a），同类回归在用例 01、02、22、28、32；**`Mirror` 这一个走不通**：`MirrorDefinition` 的面选得进、`md.Validate()` 回 `True`，`CommitFeature()` 与 `pb.Validate()` 都抛 `NXException: Feature cannot be mirrored.`，20 组受控提交（平面智能对象 / 基准平面 / 平面特征建出的 Plane / 固定平面 / 别的体的平面 / `PlaneOption` 两种取值及其同时填 / `PatternMethod` 两种 / 三种 `OutputOption` / 类型设在特征表前后 / 选择里带真实显示视图 / 显式参照点 / 种子用基体与子特征各一轮）全部同样被拒，说明拒绝发生在阵列特征 builder 内部而非输入（探针 41~47，2026-09-23）→ **镜像需求一律走 §3.2 的特征级镜像**。§3.1b 之前那条"NX12 造不出 `NXOpen.Axis`"的记录是探针自己的缺陷：`Axes.CreateAxis` 的签名是 `(Point3d, Vector3d, UpdateOption)`，把 `NXOpen.Axis.Null` 塞进第一个参数会以内存访问违例崩掉。

### 1.10 交付自检清单（逐项过）

- [ ] 特征树顺序：主形状 → 切除 → 细节 → 阵列/镜像 → 收尾；无"先阵列后补细节"；重算特征在树尾
- [ ] 所有重复特征都是"种子 + 依赖细节 + 阵列/镜像"生成，无逐个复制
- [ ] 顶层参数（含阵列计数/间距/角度）都是命名表达式，无散写硬编码
- [ ] 布尔操作每次后都断言体数；方块布尔用 `SetBooleanOperationAndTarget`（§2.5）
- [ ] 数值校验已跑（§3.5 体积/面积/质心 vs 解析值），偏差在容差内
- [ ] 草图完全约束且锚定原点；孔位等关键位置有可见参照（十字辅助线/参考线）
- [ ] 运行输出有统计验证（体数/孔壁数/倒圆环面数），与设计值一致
- [ ] 批处理 `run_journal_batch.bat` 通过 + `check_journal.py` 通过
- [ ] 可编辑性（详见 §6）：历史特征树无哑体；草图 `GetStatus` 全部 WellConstrained（dof=0）；关键特征已 `SetName`；无游离曲线/点
- [ ] 设计意图四问已过；倒圆/倒角在特征树尾部，大半径先于小半径

## 2. 特征配方

### 2.1 方块 / 圆柱

```python
blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
blk.CommitFeature(); blk.Destroy()
# ⚠ BlockFeatureBuilder.Length/Width/Height、CylinderBuilder.Diameter/Height 全部只读
#   （AttributeError），直接赋值不行，用 SetLength/SetWidth/SetHeight 或 SetOriginAndLengths。
# ⚠ CylinderBuilder 需先建圆曲线赋 Arc 再拉伸。
# ⚠ 坐标必须是 float（0.0 不是 0），长度必须是 str（"100" 不是 100.0）；详见 SKILL.md §3 坑位 7/8。
```

**方块做布尔要用 `SetBooleanOperationAndTarget`**（2026-09-15 实测，见 §2.5）：

```python
cut = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
cut.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
cut.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Subtract, target_body)
cut.CommitFeature(); cut.Destroy()
```

### 2.1b 圆柱 / 圆锥 / 表达式绑定实测补充（2026-09-25 冷测 T8/T10）

- NX12 `CylinderBuilder.Types` 只有 `ArcAndHeight` / `AxisDiameterAndHeight` 两个成员（无 `AxisAndHeight`），且 `CylinderBuilder` 无 `BooleanType` 属性（主线复证实测）。
- UF 的 `CreateCone` / `CreateCylinder` 在 NX12 Python 运行期不存在（MCP 索引不可信，权威源是 dir() 内省）；圆锥走 .NET `ConeBuilder`：`Types.DiametersAndHeight` + `wp.Axes.CreateAxis(Point3d, Vector3d, UpdateOption)`（T10 口径）。
- 圆柱/圆锥尺寸的表达式绑定通道：`Diameter` / `Height` 属性只读，但其 `.Expression` 的 `RightHandSide` 可绑定命名表达式——`cyl.Diameter.RightHandSide = "D_Base"`（T10 实测，全表达式驱动关键通道）。
- `CreateCylinderBuilder` / `CreateConeBuilder` 的首参传 `NXOpen.Features.Cylinder.Null` / `NXOpen.Features.Cone.Null`，传 `None` 报 TypeError。
- `CylinderBuilder.Direction` 的 Python 绑定收 `Vector3d`，传 `Direction` 对象报 "Expecting NXOpen.Vector3d type"（2026-09-25 冷测 T2-R2 实测）；与上条 `RightHandSide` 表达式绑定组合即全表达式驱动圆柱。

### 2.2 拉伸（Section 路线，⚠ 三条实测坑）

- `Sections.CreateSection(0.0009, 0.001, 0.01)`：3 容差重载实测存在。
- ⚠ 新建 `ExtrudeBuilder` 后 `builder.Section` 恒为 `None`，需先建独立 Section 再赋 `builder.Section`。
- ⚠ `Section.AddToSection` 的 seed/startConnector/endConnector 不能传 `None`，必须 `NXOpen.NXObject.Null`，否则报 `No overload matches`。
- ⚠ `ExtrudeBuilder` 必须显式设 `Direction`（`Directions.CreateDirection(Point3d, Vector3d, UpdateOption.WithinModeling)`），否则提交报 `No axis selected`。
- ⚠ `Curves.CreateArc` 的 startAngle/endAngle 单位是**弧度**，传度数会得到乱弧导致截面自相交。
- 完整可跑示例：`scripts/tests/01_bracket.py`。

### 2.3 孔（Hole 特征 + 十字辅助线）

方案 A 链路（实测可用，特征类型 SIMPLE HOLE）：

```python
hb = wp.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
hb.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
hb.SetSimpleHole(NXOpen.Point3d(x, y, z), False, placementFace, "8")   # 直径可传表达式名
hb.SetThruFace(bottomFace)
hb.HoleLocation = NXOpen.Point3d(x, y, z)
hb.CommitFeature(); hb.Destroy()
```

⚠ **孔位贴边 = 零壁厚**：孔心 + 半径恰好落在轮廓边缘时报 `The tool and target do not form a complete intersection ... zero wall thickness`（Ø10 孔心 x=55、右缘 x=60 即触发）。杆件端部孔不放矩形端点，孔边至少留壁厚（示例统一 ≥10 mm）。

十字辅助线（人机工程：孔位可见、可改；2026-08-06/07 实测）：

```python
# 1) 每孔画 2 条互相垂直短线段，与轮廓一起加入草图
for cx, cy in hole_positions:
    h = 6.0
    cross.append(wp.Curves.CreateLine(NXOpen.Point3d(cx-h, cy, 0), NXOpen.Point3d(cx+h, cy, 0)))
    cross.append(wp.Curves.CreateLine(NXOpen.Point3d(cx, cy-h, 0), NXOpen.Point3d(cx, cy+h, 0)))
# 2) 转辅助线（参考线）：虚线显示、不参与拉伸
cb = wp.Sketches.CreateConvertToFromReferenceBuilder()
for rc in cross: cb.InputObjects.Add(rc)
cb.OutputState = NXOpen.ConvertToFromReferenceBuilder.OutputType.Reference
cb.Commit(); cb.Destroy()
# 3) 完全固定防漂移（枚举成员是 NotSet 不是 None，.None 是 Python 语法错误）
for rc in cross:
    sketch.CreateFullyFixedConstraints(
        NXOpen.Sketch.ConstraintGeometry(rc, NXOpen.Sketch.ConstraintPointType.NotSet, 0))
# 4) 孔心 = 水平辅助线 StartPoint/EndPoint 中点，传入 SetSimpleHole
```

⚠ NX12 Python 封装 Hole 位置是 WCS 点，无与草图几何关联的 API → 改孔位 = 改辅助线坐标后重跑。

### 2.4 倒圆 / 倒角

```python
rule = wp.ScRuleFactory.CreateRuleEdgeDumb(edges)        # 或 CreateRuleEdgeFace(faces)
col = wp.ScCollectors.CreateCollector()
col.ReplaceRules([rule], False)                          # 第二参数必须 False（SKILL.md §3）
eb = wp.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
eb.AddChainset(col, "2.0")                               # ⚠ 没有 Radius 属性，半径经 AddChainset 传
eb.CommitFeature(); eb.Destroy(); col.Destroy()
```

倒角（修改已有部件场景，实测通过；部件打开/SetDisplayPart 见 SKILL.md §3）：

```python
body = [b for b in part.Bodies][0]
faces = [f for f in body.GetFaces() if f.SolidFaceType == NXOpen.Face.FaceType.Cylindrical]
rule = part.ScRuleFactory.CreateRuleEdgeFace(faces)          # 选中孔口棱边
collector = part.ScCollectors.CreateCollector()
collector.ReplaceRules([rule], False)                        # 第二参数必须 False
builder = part.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.OffsetAndAngle
builder.FirstOffset = "1.0"
builder.Angle = "45.0"
builder.SmartCollector = collector
builder.CommitFeature()
builder.Destroy(); collector.Destroy()
```

- ⚠ `Edge.GetVertices()` 返回 `Point3d` 列表（不是 `Point`），直接 `.X/.Y/.Z`。
- **适用面与验证判据（2026-09-28 探针实测）**：同进程新建部件 + Hole 特征孔壁
  （`CreateRuleEdgeFace` 挂圆柱孔壁）走同一配方同样成立。验证倒角用**体积差或
  `feature.GetFaces()`**：体积差与解析值分毫不差（Ø12 通孔上下孔口各削 π·19/3≈19.897、
  dV=-39.794；直边对照 dV=-60.000 恰=三角棱柱 0.5·1·1·L）；面数判据=孔口双棱边 2 面、
  单直边 1 面。按面型核对时，倒角锥面 `AskFaceData` 是 **17**、直边倒角的平面是 22。

### 2.5 布尔与孔壁识别

- 布尔：`CreateBooleanBuilder(NXOpen.Features.BooleanFeature.Null)`（Unite/Subtract）。
- ⚠ **方块（BlockFeatureBuilder）必须用 `SetBooleanOperationAndTarget(BooleanType.Subtract, target)`**（2026-09-15 实测，回归 `scripts/tests/14_block_boolean.py`）：设 `BooleanOption.Type=Subtract` + `SetTargetBodies([target])` 再 Commit **不报任何错**，但求差不生效、体数 1→2（多出一个工具体）。Cylinder 等其它 builder 的 `BooleanOption` 正常。**任何布尔后都断言体数**，这是唯一能发现静默失败的证据。
- ⚠ **不能按"所有圆柱面"过滤孔壁**：端部半圆、长圆槽端也是圆柱面（实测 Unite 端头后圆柱面由 2 变 4）。两条稳定路线：
  1. 旧布尔打孔：遍历 `part.Features.GetFeatures()` 找 `FeatureType == "SUBTRACT"`，用 `feature.GetFaces()` 取其创建的圆柱面（即孔壁）；
  2. Hole 特征：用 `ufs.Modeling.AskFaceData(face.Tag)` 按半径过滤圆柱孔壁（见 §5）。

**布尔几何规则（2026-09-15 吸收，几何事实非 API）**：要合并的两个体必须**真正体积相交**——面接触零重叠、点接触、线接触都不融合，会静默留下两个独立体；工具体完全在目标体外时后续求差报 `Tool body completely outside target body`；贴合面切孔壁厚不足也会失败（与 §2.3 孔位贴边零壁厚同源）。求差顺序有意义：多个体依次合并时，每一步都必须与**当前已存在**的材料接触。**检测静默孤立体**：统计"命名体数 vs 实际体数"，不一致即有未融合的孤立体。

## 3. 阵列 / 镜像 / 旋转 / 衍生特征

### 3.1 线性 / 圆周阵列（PatternFeatureBuilder，实测可用）

```python
pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
pb.FeatureList.SetArray([seed_feature])                  # 依赖特征一起入列: [seed_hole, blend_feature]
pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
pd = pb.PatternService
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Linear   # 或 Circular
r = pd.RectangularDefinition
r.XDirection = wp.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
r.XSpacing.SpaceType = NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Pitch
r.XSpacing.PitchDistance.RightHandSide = "30"; r.XSpacing.NCopies.RightHandSide = "3"
r.YSpacing.NCopies.RightHandSide = "1"
pb.CommitFeature(); pb.Destroy()
# 圆周: cd = pd.CircularDefinition; cd.RotationAxis = axis;   # axis 类型 NXOpen.Axis
#        axis = wp.Axes.CreateAxis(NXOpen.Point3d(0,0,0), NXOpen.Vector3d(0,0,1),
#                                  NXOpen.SmartObject.UpdateOption.WithinModeling)
#        cd.AngularSpacing.SpaceType=Pitch; PitchAngle/NCopies 走 RightHandSide
```

⚠ **2D 线性阵列必须 `rect.UseYDirectionToggle = True`** 并显式给 YDirection，否则 Y 方向不生成副本。
⚠ 依赖特征一起阵列（打孔→倒圆→[孔+倒圆]一起阵列，2026-08-06 实测）：副本自动带倒圆，特征树更干净。
⚠ 验证倒圆已随阵列：孔壁面 type=16 半径=HD/2；孔口倒圆面为圆环面 type=19，`AskFaceData` 的 radius 是**主半径 = HD/2 + 倒圆半径**（不是倒圆半径本身）。

⚠ 圆周阵列的间距属性名是 `PitchDistance`（不是 cookbook 所写 `CountAndPitch`，后者不存在）；`SpacingType.Offset` 亦可用但语义是偏移量而非节距，本机 §3.1 的 Pitch 路线已实测通过，优先沿用。

### 3.1a 沿路径阵列（`AlongPath`，2026-09-22 实测通过：体数 2→3）

```python
line = wp.Curves.CreateLine(NXOpen.Point3d(150.0, 0.0, 10.0), NXOpen.Point3d(250.0, 0.0, 10.0))
pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
pb.FeatureList.SetArray([seed_feature])
pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
pd = pb.PatternService
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.AlongPath

apd = pd.AlongPathDefinition                 # 另一个可用成员是 pd.HelixDefinition
# 引导线两种写法（2026-09-22 受控 A/B 均实测生效，见下方"两条路线都对"）
rule = wp.ScRuleFactory.CreateRuleCurveDumb([line])
sec = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
sec.AddToSection([rule], line,
                 NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                 NXOpen.Point3d(150.0, 0.0, 10.0),
                 NXOpen.Section.Mode.Create, False)
apd.XPath = sec                              # 路线 1：赋值（普通可写引用属性，不是只读）
# 路线 2（等效）：不新建，直接往定义自带的 Section 里加——
#   apd.XPath.AddToSection([rule], line, ..., NXOpen.Section.Mode.Create, False)
pb.CommitFeature(); pb.Destroy()
```

- `Section.AddToSection` 的真实签名（MCP 核实 + 实测）：`(SelectionIntentRule[], seed, startConnector, endConnector, helpPoint: Point3d, Mode, chainWithinFeature: bool)`。第 6 参是 **`NXOpen.Section.Mode`**（成员 `Create` / `Edit`），**不是**方向枚举——`Section.Direction.YAxis` 不存在，照抄会报 AttributeError。
- 规则用 `wp.ScRuleFactory.CreateRuleCurveDumb([line])`；`ScRuleFactory` **没有**任何 point 规则（见 §4.4）。
- **两条路线都对**（A/B 判定：两条平行且 Y 向错开 100mm 的引导线，分别只用一种写法，提交后量副本质心）：
  - 赋值路线：`apd.XPath = sec` **不报错**，且 `apd.XPath.Tag == sec.Tag`（真的换成了传入的那个 Section），副本落在该线中点。`Section` 没有 `.Value` 成员，`apd.XPath.Value = sec` 不成立。
  - 原地路线：`apd.XPath.AddToSection(...)` 同样生效，副本落在该线中点。
- ⚠ **间距与数量必须显式设，且默认按"百分比"解释**（2026-09-23 实测，三模式语义全部量过）：
  - `XOnPathSpacing` 是 `OnPathDistancePatternSpacing`；`SpaceType` 枚举**取不到** `PatternSpacing.SpaceType`（那是属性描述符），真名是模块级 `NXOpen.GeometricUtilities.PatternSpacingSpacingType`：`Offset=0`（默认）/ `Span=1` / `PitchAndSpan=2` / `Pitch=3` / `List=4`。
  - 距离槽 `OnPathPitchDistance` / `OnPathSpanDistance` 是 `OnPathDimensionBuilder`，**本身没有 `RightHandSide`**；可写的是它的 `.Expression`。且默认 `IsPercentUsed=True`——`Expression='50'` 是"路径的 50%"而不是 50 mm（照抄数字会得到"整条路径只放 1 个"这种莫名结果）。
  - **`Pitch` 模式**（推荐）：`SpaceType=Pitch` + `OnPathPitchDistance.IsPercentUsed=False` + `.Expression.RightHandSide="<mm>"` → 沿弧长每隔该距离放一个；本例弧长 254.4901 的 2 圈螺旋取节距 `arc/4` → 恰好 4 个，质心与解析螺旋 `z=p·θ/2π` 偏差 0.0004 mm。
  - **`Span` 模式**：`SpaceType=Span` + `OnPathSpanDistance`（同样先关百分比）→ 在整段跨度内均分，`NCopies` **把种子算在内**（`NCopies=4` → 3 个副本，间距 = span/(NCopies-1)）。
  - **`Offset` 模式（默认陷阱）**：两个距离槽都被忽略，实测把副本按"整圈"间隔摆放（2 圈螺旋 → z=20 与 40 两个），所以**只改 `NCopies` 不会改变副本个数**（NCopies=3/4/6/8 实测都是同样的 2 个）。
  - **超出路径末端的副本不会被外推，直接被丢弃**：`NCopies=6` 与 `NCopies=5` 在"只放得下 4 个"的路径上给出同样的 4 个；反之节距比 `弧长/4` 多 1e-4 mm 就会静默少一个 ⇒ **节距用实测路径长度算，不要用解析式**。
- `XPathOption`（`AlongPathPatternPathOptionsMemberType`）、`UseYDirectionToggle`（bool）可读。
- ⚠ **Slot（键槽）特征本机不存在**：`wp.Features` 上没有 `CreateSlotBuilder`，`dir()` 里连名字含 `Slot` 的成员都没有 → 槽用「方块布尔求差」表达（§2.5）。

### 3.1b 原生螺旋阵列（`PatternType=Helix`，2026-09-23 实测通过：种子 1 → 4 件）

沿路径阵列只能跟一条曲线走；要"绕轴旋转同时升高"用 NX 自带的 Helix 阵列类型，参数是**节距+圈数+轴**，不需要自己造螺旋曲线：

```python
# ⚠ 轴工厂的签名是 (Point3d, Vector3d, UpdateOption)。把 NXOpen.Axis.Null 填进第 1 个参数
#   会以 "NXException: Internal error: memory access violation" 崩掉；DatumAxis 赋给
#   RotationAxis 报 "Expecting NXOpen.Axis type, found NXOpen.DatumAxis"。
axis = wp.Axes.CreateAxis(NXOpen.Point3d(0.0, 0.0, 0.0),      # 轴上一点
                          NXOpen.Vector3d(0.0, 0.0, 1.0),     # 轴方向
                          NXOpen.SmartObject.UpdateOption.WithinModeling)   # -> NXOpen.Axis
pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
pb.FeatureList.SetArray([seed_feature])
pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
pd = pb.PatternService
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Helix
hd = pd.HelixDefinition                       # NXOpen.GeometricUtilities.HelixPattern
hd.SizeOption = NXOpen.GeometricUtilities.HelixPattern.SizeOptions.CountHelixPitchAndTurns
hd.CountOfInstances.RightHandSide = "4"       # 表达式：没有 SetRightHandSide
hd.NumberOfTurns.RightHandSide    = "1"
hd.HelixPitch.RightHandSide       = "20"      # 每整圈升高（mm）
hd.RotationAxis = axis                        # 必须是 NXOpen.Axis
pb.CommitFeature(); pb.Destroy()
```

- 实测（半径 20 处 5 mm 种子块，4 件 / 1 圈 / 节距 20）：新增 3 个实体，质心 `θ=120°/240°/360°`、`z=6.6667/13.3333/20.0000`、`r=20.0000`，与解析螺旋 `z=p·θ/2π` 偏差 **0.0000 mm**。
- **`CountOfInstances` 把种子算在内**：角步距 = `360/(CountOfInstances-1)`（4 → 120°），升高 = `HelixPitch`×整圈数。
- `HelixPattern.SizeOptions` 全集：`AngleHelixPitchAndSpan / AngleHelixPitchAndTurns / CountAngleDistance / CountHelixPitchAndSpan / CountHelixPitchAndTurns`；成员另有 `AnglePitch / DistancePitch / HelixSpan / DirectionType / DirectionTypes`。
- ⚠ `RotationAxis` 留空（赋 `NXOpen.Axis.Null` 会被接受并读回 `None`）时提交**不报错但一个副本都不生成**——静默空阵列，判据只能靠"体数变化"。
- 选型：需要**沿任意引导线**（样条/边链）阵列用 §3.1a；需要**绕轴螺旋**用本节，参数少且步距/圈数直接可控。

### 3.1c 正多边形阵列（`PatternType=Polygon`，2026-09-23 实测通过）

法兰的六角螺栓头、方形布置的安装座这类"沿正多边形边等分"的阵列用 `Polygon`，它比手算角度再逐个建要短，而且件数/半径由"种子 + 边数"直接决定：

```python
GU = NXOpen.GeometricUtilities
pd.PatternType = GU.PatternDefinition.PatternEnum.Polygon
pg = pd.PolygonDefinition                    # NXOpen.GeometricUtilities.PolygonPattern
pg.RotationAxis = axis                       # 必须是 NXOpen.Axis，且**过原点**（见下 ⚠）
pg.NumberOfSides.RightHandSide = "6"         # ⚠ 表达式：给 int 报 Expecting Unicode str type, found int
pg.PolygonSizeOption = GU.PolygonPattern.SizeOptions.Inscribed
pg.PolygonSpacing.SpaceType = GU.PatternSpacingSpacingType.PolygonCountPerSide
pg.PolygonSpacing.NCopies.RightHandSide = "2"    # ⚠ 也是表达式
pb.CommitFeature()
```

**布点规则（解析式，已用 6 组读数逐点核对，偏差 6e-14 mm）**：正多边形的**顶点**落在"以原点为心、半径 = 种子质心到轴的距离 R"的圆上，**相位由种子决定**（种子自己就是那个顶点）；每条边再被 `NCopies-1` 等分，每边放 `NCopies-1` 个实例（两端顶点只算一次），总数 = `边数×(NCopies-1)`。

| 边数 N | `NCopies` | 件数 | 半径读数 | 相邻角距 |
| --- | --- | --- | --- | --- |
| 6 | 2 | 6 | `[17.5000]` | 全 60.0000° |
| 6 | 3 | 12 | `[15.1554, 17.5000]` | 全 30.0000° |
| 6 | 4 | 18 | `[15.4335, 17.5000]` | 19.1066° / 21.7868° 交替 |
| 6 | 5 | 24 | `[15.1554, 15.7743, 17.5000]` | 13.8979° / 16.1021° 交替 |
| 4 | 3 | 8 | `[12.3744, 17.5000]` | 全 45.0000° |
| 4 | 4 | 12 | `[13.0437, 17.5000]` | 26.5651° / 36.8698° 交替 |

- **`NCopies` 是"每边等分数"，不是件数**：`NCopies=2` 只在顶点放件（6 边形 6 件），`NCopies=3` 多出各边中点（12 件）。`NCopies=1` 等于每边 0 个，提交被拒（`NXException: Update undo happened.`）——所以至少给 2。
- ⚠ **`NCopies≥4` 之后角距不再均匀**（见上表 19.1066/21.7868）：实例是沿**边**等弦长排的，不是等角度排的。按"每隔 360/N/份数 摆一件"去核算位置会算出偏差，用本节的解析式或直接量质心。
- 半径跟着种子走：种子质心 r=17.5 → 实例在 17.5；换成 r=12.5 → 实例在 12.5。所以"布置半径"这个量不需要另设参数，把种子摆对就够了。
- ⚠ **轴必须过原点**：把轴基点放在 (30,10,0)、种子相对该轴仍是 r=17.5 时，6 个副本落到相对原点半径 16.0078~48.5412、角距 5.6693~296.5524° 的乱位置；`pg.RotationCenter` 设成同一个点**读数完全一样**，救不回来。需要绕偏置中心布阵列时改用 `Circular`（§1.9 表），或先把几何搬到原点附近。
- `PolygonSizeOption` 只有 `Inscribed` 与 `Circumscribed` 两个成员；在本节测过的每个工况（N=4/6 × NCopies=2/3/4）里两者读数**完全相同**，所以不要指望它改半径，也别在配方里依赖它。
- `PolygonSpacing.SpaceType` 的枚举类是模块级 `PatternSpacingSpacingType`（成员 `Offset / Span / PitchAndSpan / Pitch / List / PolygonCountPerSide / PolygonPitchAlongSide`），不是 `PolygonPattern` 内嵌的。**不设它（默认 `Offset`）会排出两个半径上的 17 件**（探针实测），必须显式设成 `PolygonCountPerSide`。
- `PolygonPattern` 的成员全集：`Flip / HorizontalRef / Null / NumberOfSides / PolygonSizeOption / PolygonSpacing / RadialSpacing / RotationAxis / RotationCenter / SizeOptions / Tag / UseRadialDirectionToggle / Validate`。

### 3.1d 指定目标点阵列（`PatternType=General`，2026-09-23 实测通过）

位置不规律又想留成一个可编辑的阵列特征时用 `General`：给它一组目标点，种子被复制到每个点。**目标点是 `NXOpen.Section`，不是点列表**，这是本节唯一的门槛：

```python
GP = NXOpen.GeometricUtilities.GeneralPattern
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.General
gd = pd.GeneralDefinition                     # NXOpen.GeometricUtilities.GeneralPattern
gd.FromLocationType = GP.FromLocationOptions.Point    # 种子上的参照位置
gd.FromLocationPoint = part.Points.CreatePoint(NXOpen.Point3d(*FROM))   # 参照点的坐标
targets = [part.Points.CreatePoint(NXOpen.Point3d(*p)) for p in TO_POINTS]
rule = part.ScRuleFactory.CreateRuleCurveDumbFromPoints(targets)
gd.ToPoints.AddToSection([rule], targets[0], NXOpen.NXObject.Null,
                         NXOpen.NXObject.Null, NXOpen.Point3d(0.0, 0.0, 0.0),
                         NXOpen.Section.Mode.Create, False)
pb.CommitFeature()
```

- 实测（种子 5 mm 方块，参照点 `(17.5,0,30)`，三个目标点）：新增 **3** 个实体，质心与目标点偏差 **4.4e-15 mm**，种子原地不动，`gd.ToPoints.GetSectionData()` 提交后长度 1。
- 映射语义是"**把种子上的参照点搬到每个目标点**"：不算距离、不旋转，种子自己不在结果里。所以参照点要挑在种子上有几何意义的位置（角点、孔心），否则整体会平移错位。
- ⚠ **`ToPoints` 留空提交被拒**（`NXException: Update undo happened.`）——ToPoints 才是决定实例位置的东西，没有它整条阵列没意义。
- ⚠ **一次提交失败会污染同一个 NX 会话后续的属性赋值报错文本**：探针里前一个 poly 阵列被拒之后，后面的 `RotationAxis = axis` 报的是 "Expecting int type, found str"（跟 Axis 毫无关系）。所以每个工况用**独立部件 + 独立 builder**，别在一个部件里连做多个实验。
- 拿"实体标签"比"种子还在不在"时注意：`CommitFeature()` 返回的是**特征**标签，`part.Bodies` 给的是**体**标签，两者不相等（实测踩过，断言会假报失败）。

### 3.1e 引用已有阵列（`PatternType=Reference`，2026-09-23 实测通过）

把一件几何按**另一个已有阵列的布置**复制一遍（例如让加强筋跟着既有孔阵排）。门槛只有一个：被引用的阵列要**装进一个选择对象**。

```python
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Reference
rd = pd.ReferenceDefinition                      # NXOpen.GeometricUtilities.ReferencePattern
rd.ReferencedPattern.SetValue(ref_pattern_feature, NXOpen.View.Null,
                              NXOpen.Point3d(0.0, 0.0, 0.0))
rd.SetBaseInstance(1, 0)                         # 可选；不设就是默认基准实例
pb.CommitFeature()
```

- ⚠ **`ReferencedPattern` 不是可写属性**（直接赋值报 `AttributeError: not writable`）。它是 `NXOpen.SelectNXObject` 一类的**选择对象**：属性只读，但它交出来的那个对象可以被 `SetValue(选择对象, 视图, 点)` 灌值。同族的还有 `MirrorPattern.ExistingPlane`（`SelectISurface`）与 `SpiralPattern.HorizontalRef`。读回来用 `GetValue()`，返回 `(对象, 视图, 点)`。
- **基准实例语义**（实测）：被引用的 3 件线性阵列节距 30、种子坐在其中第 0 件的位置上时，默认基准实例让整族复现被引用阵列的偏移 `x = 0 / 30 / 60`；`SetBaseInstance(1, 0)` 把被引用的第 1 件映射到种子身上，整族随之平移一个节距（`−30 / 0 / 30`）。`ResetBaseInstance()` 回到默认。
- ⚠ **种子自己就是基准实例，新增副本数 = 件数 − 1**：上例提交后 y=60 那一排共 3 体（种子 + 2 件副本），不是 4 体。按"新增了 N 件"去断言会失败，要按整族的偏移核对。
- 该阵列保住种子的 y、z（实测 6 体全部 y=60.0000、z=0），只在布置方向上展开。

### 3.1f 螺旋阵列（`PatternType=Spiral`，2026-09-23 实测通过）

```python
pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Spiral
sd = pd.SpiralDefinition                          # NXOpen.GeometricUtilities.SpiralPattern
sd.SizeSpiralType = NXOpen.GeometricUtilities.SpiralPattern.SpiralDefineSize.NumberOfTurns
sd.NumberOfTurns.RightHandSide = "1"              # 表达式；TotalAngle 是另一种定尺方式
sd.RadialPitch.RightHandSide = "10"
sd.PitchAlongSpiral.SpaceType = <PatternSpacing SpacingType>.Pitch
sd.PitchAlongSpiral.OnPathPitchDistance.Expression.RightHandSide = "20"
sd.SpiralNormal = <NXOpen.Direction>
sd.HorizontalRef.HorizontalRefVector = <NXOpen.Direction>    # 这一条是工作形态
pb.CommitFeature()
```

- ⚠ **水平参考要填 `HorizontalRefVector`（一个 Direction）**；同族的 `HorizontalRef.HorizontalRefObject` 是选择对象，留着不填提交必报 `No section curves or points created.`（负向对照，回归用例 32 第 12 阶段）。`PitchAlongSpiral` 的 `IsPercentUsed` 在本例里设与不设读数相同，这点与 §3.1a 的 `AlongPath` 不同。
- 实测基线（种子 5 mm 方块、质心在 +x 的 r=20 处；圈数 1、径节距 10、沿线节距 20、法向 +z、水平参考 +x）：共 **2** 体，种子留在 (r=20.0000, 0.0000°)，副本落在 (r=21.4797~21.4799, 20.5051~20.5052°)。
- ⚠ **不要按原型阿基米德螺线去算布置**（实测证伪）：圈数 2、径节距 20、沿线节距 10 的 26 个实例半径从 9.86 跨到 59.19 mm，且半径对绕原点的转角**不单调**（对螺线中心与节距做最小二乘拟合仍留 1.8 mm 残差）；圈数 1 配沿线节距 40 时**一个实例都没生成**。需要严格螺线时自己按角度算坐标再用 §3.1d 的 `General` 或直接建体。

### 3.2 特征级镜像（实测可用）

```python
plane = wp.Planes.CreatePlane(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
mb = wp.Features.CreateMirrorFeatureBuilder(NXOpen.Features.Feature.Null)
mb.FeatureSet.SetArray([half_feature])
mb.PlaneOption = NXOpen.Features.MirrorFeatureBuilder.PlaneOptions.New
mb.PlaneConstructor = plane
mb.CommitFeature(); mb.Destroy()
```

⚠ 草图级镜像不可用（SketchMirrorPatternBuilder 限制，见 §4.3）；对称意图改用 AutoDimension 的 Symmetric 规则表达，或按坐标手工生成镜像曲线（失去镜像特征编辑语义）。

### 3.3 旋转体（RevolveBuilder 批处理不可用 → UF 路线）

```python
# ⚠ RevolveBuilder.CommitFeature 批处理报内存访问违例（把 wp.Axes.CreateAxis 造出的轴交给
#   builder 也照样崩——轴工厂本身是好的，见 §3.1b；DatumAxis 赋 Axis 属性被类型拒绝）→ 改用 UF:
ufs = NXOpen.UF.UFSession.GetUFSession()
feats = ufs.Modl.CreateRevolved(
    [c.Tag for c in profile_curves], ["0.0", "360.0"],
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],               # 原点 + 旋转轴方向
    NXOpen.UF.ModlFeatureSigns.NULLSIGN,             # ⚠ 枚举是 ModlFeatureSigns，不是 FeatureSigns
)
# ⚠ 限制：剖面含落在轴上的边或带台阶/凹剖面 -> "Cannot create Swept geometry"；凸剖面（矩形）可用。
#   复杂旋转体 = 多段凸剖面旋转 + BooleanBuilder Unite。
```

### 3.4 抽壳（Shell）与拔模（Draft）（2026-09-15 整机实测通过，回归 `scripts/tests/15_shell_draft.py`）

**共同前提：容差默认值是 `0.0`，不改必然 Commit 报错**（`ShellBuilder.Tolerance` 报 "Tolerance error"，`DraftBuilder.AngleTolerance` 报 "Angle tolerance is too small"）。

抽壳（100×60×20 方块移除顶面、壁厚 2.0 → 实测 `V=23232.000`，与 `120000 − 96×56×18` 分毫不差）：

```python
sb = wp.Features.CreateShellBuilder(NXOpen.Features.Feature.Null)
sb.Tolerance = 0.01                       # ⚠ 默认 0.0
sb.Body = body
sb.SetDefaultThickness("2.0")             # ⚠ 厚度传 str 表达式（同 §2.1 尺寸约定）
col = wp.ScCollectors.CreateCollector()
col.ReplaceRules([wp.ScRuleFactory.CreateRuleFaceDumb([top_face])], False)
sb.RemovedFacesCollector = col            # 要"挖掉"的面；不设 = 闭腔抽壳
sb.CommitFeature(); sb.Destroy(); col.Destroy()
```

拔模（100×60×20 四侧面 5°、固定底面 → 实测 `V=114482.3710`，与解析式分毫不差）：

```python
db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)
db.AngleTolerance = 0.5                   # ⚠ 默认 0.0
db.DistanceTolerance = 0.001              # ⚠ 默认 0.0
db.TypeOfDraft = NXOpen.Features.DraftBuilder.Type.Face
db.DraftIsoclineOrTruedraft = NXOpen.Features.DraftBuilder.Method.TrueDraft
db.Direction = wp.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 0.0, 1.0), NXOpen.SmartObject.UpdateOption.WithinModeling)
db.StationaryEntity = bottom_face         # ⚠ 必须传 Face 对象，不能传 SC 收集器
ecs = wp.CreateExpressionCollectorSet(
        collector_of_side_faces, "5", "", 0)   # 角度传 str；unitsType 传 ""
db.FaceSetAngleExpressionList.Append(ecs)
db.CommitFeature(); db.Destroy()
```

**拔模四个实测坑（缺任一即 Commit 失败）**：

- ⚠ **`DraftBuilder.Method` 只读** → 设 `DraftIsoclineOrTruedraft`（`Method.TrueDraft` / `Method.Isocline`）。
- ⚠ **`StationaryEntity` 必须传 `Face` 对象**。传 `ScCollector` 报 `First parameter is invalid`；传 `Direction`/`DatumPlane`、或干脆不设，报 **`Draft reference is missing. It may be consumed by another feature or suppressed.`**（这四个变体都实测过）。
- ⚠ **`StationaryReference` / `StationaryPartingReference` 在 NX12 Python 封装里只读**（赋值报 `attribute ... is not writable`）；可写入口只有 `StationaryEntity`。而 `PartingReference` 是**可读**的 `ScCollector`——属性表里读得出来 ≠ 写得进去，`dir()` 一次即可分辨。
- ⚠ 角度经 `ExpressionCollectorSet` 传入：`wp.CreateExpressionCollectorSet(collector, 角度串, unitsType, 0)`（第 4 参数 index 无作用），产物 `Append` 到 `FaceSetAngleExpressionList`。`unitsType` 传 `""` 或 `"Degrees"` 都被接受，实际按**度**解释。

**符号约定与解析式（实测标定）**：`StationaryEntity` = 固定面、`Direction` = 拔模方向（此处 +Z）。四侧面同时拔模、底面固定时

```
t = tan(角度)            # 带符号；正角收缩、负角张开
V = V0 − 64000·t + (32000/3)·t²      # V0=120000（100×60×20）
```

实测：5° → 114482.3710、−5° → 125680.9200、10° → 109046.7127，三者与公式完全一致（`160·(h²/2)·t = 64000t`、`4·t²·h³/3 = (32000/3)t²`）。**正角 = 沿 Direction 向上收口**（拔模方向的截面变小），负角向外张开——这个符号方向容易记反，交付前用体积对一下。

### 3.5 质量属性校验（交付前数值验证，2026-09-15 实测）

比"看体数/面数"更强的验证：直接测体积与质心，与解析值比对。

```python
uc = wp.UnitCollection
units = [uc.FindObject(n) for n in
         ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
mp = wp.MeasureManager.NewMassProperties(units, [0.99], [body])   # ⚠ 容差是 list，不是标量
print("V=%.3f A=%.3f C=(%.3f,%.3f,%.3f)" % (mp.Volume, mp.Area, mp.Centroid.X, mp.Centroid.Y, mp.Centroid.Z))
```

- 实测（100×60×20 方块）：`V=120000.000`、`A=18400.000`、质心 `(50,30,10)`，与解析值完全一致（探针 13）。
- ⚠ **`tolerances` 参数是数组**：`[0.99]` 正确。MCP 索引签名即 `(Unit[], Double[], IBody[])`；cookbook 写的标量 `0.99` 在 NX12 批处理下**也能跑通**（探针实测两种都返回正确值），但为与签名一致统一用 `[0.99]`。
- ⚠ **多体测量不会返回 0**（推翻了 cookbook 的 NX 2506 断言）：实测把 3 个体一起传入返回 `V=128500.000`（各体之和），与单体验证一致。**cookbook 的相关结论不可移植到 NX12**。
- NX12 **无** `uf.Modl.AskBoundingBox`；包围盒由 `body.GetEdges()` → `edge.GetVertices()` 取 min/max（与 §5 一致）。

### 3.6 去参（改哑体，慎用）

```python
rpb = wp.Features.CreateRemoveParametersBuilder()
rpb.Objects.Add(bodies)                   # 传入体列表
rpb.Commit(); rpb.Destroy()
```

⚠ 去参会**销毁特征树**，与本技能"必须历史模式"的铁律（§6）冲突——**仅当用户明确要求哑实体时才用**，常规交付禁用（2026-09-15 实测 API 可调用）。

## 4. 草图与表达式

### 4.1 表达式驱动链路（全联动实测）

```python
unit = wp.UnitCollection.GetBase("Length")            # ⚠ 不是 GetBase("Millimeters")
wp.Expressions.CreateSystemExpressionWithUnits("L_Plate = 100.0", unit)
# 特征尺寸直接引用表达式名：Extrude Limits RHS="T"、Hole SetSimpleHole 直径传 "HD"
expr.RightHandSide = "8"                              # 改值
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "upd")
session.UpdateManager.DoUpdate(mark)                  # ⚠ Session 属性是 UpdateManager（不是 Update）
```

⚠ 单位按量纲传：角度量（如装配姿态 TH1）用 `GetBase("Angle")`，勿一律 Length（2026-08-07 实测）；`Expression.Units` 可读回单位对象核对。建议封装 `create_expressions(wp, pairs, unit_name)`。

⚠ **单位换算陷阱（2026-09-15 实测，结论与 cookbook 相反）**：cookbook（NX 2506）警告对长度表达式赋 `.Value` 会引入 25.4×（英寸↔毫米）静默错误，必须用字符串 `RightHandSide`。本机 NX12 实测**不存在该问题**：长度量纲表达式 `L_Test=100.0`，`e.Value = 200.0` 后 `RightHandSide` 变成 `'200'`（不是 2540），`e.Value` 读回 `200.0`；反向赋 `RHS='300.0'` 后 `.Value` 读回 `300.0`。**两种写法在本机都安全**——但因为 `RightHandSide` 支持表达式名（`"p_BASE+p_TEETH"`）而 `.Value` 只接受数值，**统一用 `RightHandSide`**（既是习惯也是可编辑性要求）。跨版本移植到 NX 2506 时再按 cookbook 规避。

⚠ **表达式引擎与命名的硬限制（2026-09-25 冷测 T6/T8 实测）**：
1. NX 表达式名**大小写不敏感**——`D` 已存在时创建 `d` 报 "expression variable already exists"，同名异大小写不可共存；命名前查重（任务书的 D/d/t 符号需映射成 D/d1/T 之类）。
2. NX12 表达式引擎**无 atan/acos/asin/atan2**；渐开线类曲线改压力角参数化 `r=rb/cosα, φ=ψb−(tanα−α)`（纯 tan/cos/sin，与渐开线方程恒等），代价是曲线端点参数（如齿顶压力角）只能由宿主算好存字面量。
   ⚠ **两套参数域不可混用（2026-09-25 用例 34 实测）**：表达式按压力角域时，字面量上限必须给 `degrees(atan(umax))`（=31.32°），给成 u 参数域的 `umax*180/π`（=34.81°）则规律曲线越过齿顶圆、端点与齿顶弧错开，UF 拉伸报 "Section curves are not connected each other"。宿主几何若另有按 u 参数域写的 `flank_xy`（`r=rb*sqrt(1+u²)`），两个上限各归各，端点在齿顶重合。
3. 规律曲线 `ZLaw` 默认缺常量表达式，提交报 "Expression does not exist for law"——须显式 `ZLaw.LawType=Constant` + `Value.RightHandSide="0"`。
4. `FileNew` Commit 不立即落盘，落盘以显式 `part.Save()` 为准。

### 4.2 自动约束 / 自动标注（替代手加约束，实测可用）

```python
wp.Sketches.CreateAutoConstrainBuilder().Commit()      # 自动几何约束
adb = wp.Sketches.CreateAutoDimensionBuilder()
adb.SelectionObject.SetArray(curves)
adb.SetRules([Length, Symmetric])                      # NXOpen.Sketch.AutoDimensionRule
adb.DimType = NXOpen.Sketch.AutoDimensionBuilder.DimensionType.Driving
adb.Commit()                                           # 自动生成驱动尺寸表达式（p6=180 等），草图可编辑
```

⚠ **AutoDimension 非确定性**（2026-08-07 实测）：居中矩形偶发生成 0 个尺寸 → 草图 `UnderConstrained`（但 dof=0，NX 行为矛盾）。Commit 后 `sketch.GetStatus()` 非 `WellConstrained` 时，对轮廓线 `CreateFullyFixedConstraints` 兜底（已有驱动尺寸时勿加，避免过约束）；实测兜底后 status=3 dof=0。

### 4.3 草图 API 的不可用项（遇到 → 怎么做，2026-08-05/07 实测）

| 遇到 | 怎么做 |
| --- | --- |
| `Sketch.CreateDimension` / `CreateRadialDimension` 报 `No overload matches` | DimensionGeometry struct 绑定失败；草图尺寸改用 §4.2 自动标注 |
| 给 `SketchLinearDimensionBuilder.FirstAssociativity` / `SecondAssociativity`、`SketchConstraintBuilder.GeometryToConstrain` / `GeometryToConstrainTo` 赋值 | 这些属性只读；约束同样用 §4.2 |
| `SketchMirrorPatternBuilder.DirectionObject` 赋值 | 只读，且 `UpdateDirectionObject()` 无参；草图级镜像走不通 |
| `Part.Faces.FindFace` / `Face.IsPointOnFace` 报不存在 | 找面用 §5 的 `AskFaceData` |

MCP 核实"类/方法存在"不等于 Python 封装"可调用"；关键 API 必须批处理实测过才写成已实测条目。

### 4.4 孔与螺纹：`HolePackage` 批处理**能建三种孔、建不出螺纹孔**（2026-09-15 首测 / 2026-09-22 定论，回归 `scripts/tests/26_hole_package.py`）

- `NXOpen.Features.Thread`、`CreateThreadBuilder`、`ThreadFeatureBuilder` **在 NX12 全部不存在**（`hasattr` 全 False）。螺纹语义归 **HolePackage**：`wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)`，`Types` = `DrillSizeHole / GeneralHole / HoleSeries / ScrewClearanceHole / ThreadedHole`。
  ⚠ 枚举一律用模块级类（`NXOpen.Features.HolePackageBuilder.Types.ThreadedHole`、`…HoleDepthLimitOptions.Value`、`…ThreadLengthOptions.Standard`）；写成 `b.Types()` / `b.HoleDepthOptions()` 会抛 `NXException: instances of NX enums can not be created` 并**当场中断 journal**。

**孔位怎么给**：`HolePosition` 是只读 `Section` 容器，点靠 `ScRuleFactory` 灌进去：

```python
pt   = wp.Points.CreatePoint(NXOpen.Point3d(30.0, 20.0, 20.0))
rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])   # 点规则在这里
b.HolePosition.AddToSection([rule], pt, NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                            NXOpen.Point3d(30.0, 20.0, 20.0), NXOpen.Section.Mode.Create, False)
bt = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
b.BooleanOperation.SetBooleanOperationAndBody(bt.Subtract, body)   # 目标体在这里，不在别处
b.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(pt, NXOpen.Vector3d(0.0, 0.0, -1.0))
b.HoleDepthLimitOption = NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.Value
b.Tolerance = 0.0254        # ⚠⚠ 必填（距离公差 double）：不写 → Validate 直接报
                            #   "The Tolerance Specification requires three numbers"
b.Validate(); b.CommitFeature()
```

- ⚠ **`HolePackageBuilder` 没有 `PropertyTable`**（那是 CAE/FEM 的，建模 builder 都没有）——别往属性表上找这个公差。
- ⚠ 深度是 **Expression**，不能直接赋字符串：`b.EndHoleData.HoleDepth.RightHandSide = "15"`（`ThreadDepth / TapDrillDiameter / ThreadedHoleDepth / DrillSizeHoleDepth / GeneralSimpleHoleDepth` 同理）；直接 `b.EndHoleData.HoleDepth = "15"` 报 `attribute 'HoleDepth' … is not writable`。孔深/螺纹段深分居 `b.EndHoleData`、`b.StartHoleData`、`b.MiddleHoleData` 三处。

**实测能落地的三种孔（几何已逐项断言）**：

| 类型 | 必须给什么 | 实测结果 |
| --- | --- | --- |
| `GeneralHole` 通用孔 | `GeneralSimpleHoleDiameter / GeneralSimpleHoleDepth / GeneralTipAngle` 三个 Expression（不用标准数据） | Ø10 × 15 精确成立；**最省事、最可控，首选** |
| `DrillSizeHole` 钻孔 | `DrillSizeStandard="ISO"` + `DrillSizeFitOption="Exact"` + **`DrillSize` 规格标签**（如 `"10"`）**且** `DrillSizeHoleDiameter/Depth` 两个 Expression | Ø10、深 15 精确（圆柱 r=5.0000、z=[5.0, 19.4]）。**只给标签** → 变成默认 Ø11 贯通；**只给 Expression** → `Standard data not found` |
| `ScrewClearanceHole` 螺钉过孔 | `ScrewStandard="ISO"` + `ScrewType="General Screw Clearance"` + `ScrewSize="M10"` + `ScrewFitOption="Normal (H13)"` | 按标准数据做过孔 **Ø11**（ISO 273 正常配合）——螺纹连接在装配图上的真实孔形 |

- ⚠ `ScrewStandard / ScrewType / ScrewSize / ScrewFitOption` 只对**螺钉过孔**适用（API 文档明示 + 实测），螺纹孔写这些是无效动作；成员名是 `ScrewFitOption`，**没有 `ScrewFit`**。
- ⚠ **标准名必须与 `%NX_HOME%\UGII\modeling_standards\*.xml` 里的 `Standard=` 一致**：钻孔标准来自 `nx6_Drill_Size_Hole_Standard.xml`（Metric 单位下 = `ISO`，尺寸形如 `10` / `10.2`，`Fit` 只有 `Exact`）；螺纹孔标准来自 `nx502_Threaded_Hole_Standard.xml`（= **`Metric Coarse`**，尺寸串形如 **`M10 x 1.5`**，Callout 才是 `M10_x_1.5`）。写错 → `Thread standard data not found` / `Standard data not found`。
  ⚠ 别拿 `UGII\thd_metric.dat` 的条目名（`M10_X_1.5`、Tap Drill 8.7822）去填孔包：那是 **Thread 特征**的数据表；孔包自己那条 M10×1.5 / Metric Coarse 记录的 `TapDrillDia = 8.5`。

**螺纹孔 `ThreadedHole` 在批处理下不可用（可复现崩溃，已写成条件检查）**：标准名、尺寸串、`ThreadLengthOption`、深度三件套给全、`Validate()` 也通过，但 `CommitFeature()` **必抛 `NXException: Internal error: memory access violation`**（2026-09-22 实测五种深度组合全部复现；树里只留下一个没有几何的 `HOLE PACKAGE` 特征）。
**替代做法**：按工程图惯例——底孔用 `GeneralHole`（M10×1.5 底孔 Ø8.5）或 `DrillSizeHole`，螺纹用标注表达（`Annotations` 下的孔标注 / `SymbolicThread` 入口）；装配配合处要真实孔形就用 `ScrewClearanceHole`。
⚠ 崩溃会把进程退出码变成 1（日志仍写 `Execution was successful`）——**按令牌校验判定，不要看退出码**（SKILL.md §6）；崩后可用 `session.SetUndoMark(...)` + `session.UndoToMark(...)` 撤掉残废特征（26 号用例即此做法）。
⚠ 读孔位/孔径时 `ufs.Modeling.AskFaceData` 返回的 box 是 `(xmin, ymin, zmin, xmax, ymax, zmax)`，配对必须是 **(0,3)/(1,4)/(2,5)**。

## 5. 几何查询工具

```python
ufs = NXOpen.UF.UFSession.GetUFSession()
d = ufs.Modeling.AskFaceData(face.Tag)
# ⚠ UF 会话对象属性是 Modeling 不是 Modl（Modl.AskFaceData 不存在，dir 实测）
# 返回 (type, point, dir, box, radius, norm, count)：平面 type=22、圆柱面 16、圆环面 19
# dir 是 list 不是 Vector3d；圆环面 radius=主半径（孔半径+倒圆半径）
```

## 6. 可编辑性 / 可检查性铁律（用户会打开检查并修改生成的 prt）

- **必须历史模式**：产物由可编辑特征构成（SKETCH/EXTRUDE/HOLE/BLEND/PATTERN/MIRROR/SUBTRACT…），禁止哑体/无特征体、禁止转同步建模/去参。
- **草图完全约束**：`status, dof = sketch.GetStatus()`（⚠ Python 封装**不传参**、返回元组；传参报 `takes no arguments`）；`WellConstrained == 3` 且 dof=0。
- **参数可改**：顶层尺寸命名表达式（§4.1），特征尺寸引用表达式，用户在表达式对话框改一处全联动。
- **特征可改名**：`feature.SetName("Mounting boss")`（实测可用；`Feature.GetFeatureName()`/`Feature.FeatureType`/`FeatureCollection.GetFeatures()` 均可用）。
- **无垃圾几何**：草图中未参与建模的线要么转参考线要么删除；不留游离点/曲线。
- **交付前验证**：跑 `scripts/tests/08_editability_probe.py`（打开生成 prt，打印 FEAT 特征树 / EXPR 表达式 / SKETCH 约束状态 / bodies）。实测 bracket.prt：26 特征全历史、18 表达式、2 草图 fully=True、1 体。
- **数值校验（2026-09-15 吸收）**：结构性检查之外，用 §3.5 测体积/面积/质心与解析值比对——这是发现"几何静默错位"（布尔未融合、孔位偏移）的唯一手段。交付报告里给出实测值与理论值，不要只说"已生成"。
- **参数化覆盖范围要如实声明**：`Point3d` 坐标是裸数值、**不受表达式驱动**。交付时说明哪些尺寸是可改的表达式、哪些（特征位置、循环里写死的计数）需手工改——别让用户自己发现。

## 7. 整机示例沉淀（四连杆机构，2026-08-07 批处理实测通过）

完整示例（在项目工作区，不随技能分发）：曲柄摇杆四杆 + 平行双摇臂，整机 9 零件 + 14 组件装配，全部草图 WellConstrained）。

其坑位已并入本文件：孔位贴边零壁厚（§2.3）、FileNew 幂等清理（SKILL.md §3）、AutoDimension 非确定性（§4.2）、角度表达式单位（§4.1）。对照检查：特征顺序已符合方法论；改进方向 = 草图完全约束、一半+镜像、参数落 NX 表达式、减重槽评估 Slot 特征。
