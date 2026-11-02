# 建模域：方法论 + 可复现路线（NX 12 本机批处理）

> 先读 SKILL.md。§1 方法论；§2-§6 路线。示例 `scripts/tests/01-03`；§3.4-§3.6 抽壳/拔模/质量属性/去参，§4.4 螺纹。

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

- 顶层参数表达式化（`L_Plate=100`、`D_Bore=8`）；≥2 次出现或可能被改即表达式；次级尺寸派生（§4.1）。参数名不用 `p`/`P` 前缀——自动表达式是 `p0`、`p1`，同前缀会被可编辑性检查一并过滤（判据见 `reverse-engineering.md` §7）。
- 一个表达式只驱动一个结构/一个体；多个体共用同一名字时按体拆名，否则改值的体积响应会叠加。
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

### 1.11 会话/部件设置入口（`NXOpen.Preferences`）

`NXOpen.Preferences` 是子模块，`import NXOpen` 后模块根上没有该属性（`hasattr(NXOpen, "Preferences") == False`），照 .NET 写法直接访问会抛 `AttributeError: module 'NXOpen' has no attribute 'Preferences'`。设置建模体类型（实体/片体）的正确入口是会话对象：

```python
import NXOpen
import NXOpen.Preferences          # 显式导入子模块，否则枚举路径不可达

session = NXOpen.Session.GetSession()
session.Preferences.Modeling.BodyType = \
    NXOpen.Preferences.SessionModeling.BodyTypeOption.Solid
```

- `session.Preferences` 返回 `SessionPreferences`，没有 `SessionModeling` 成员；建模偏好挂在它的 `Modeling` 属性下（类型 `SessionModeling`）。
- 枚举在 `NXOpen.Preferences.SessionModeling.BodyTypeOption`；批处理回读 `BodyType`：`Solid=0`、`Sheet=1`，可读可写。
- 多数建模特征自带 `BodyPreference`（如 `ThroughCurves`），不依赖会话偏好；只有需要全局切换时才设这一项。

### 1.12 参数化模板（结构模板 + 参数表）

交付件要被按结构改尺寸（模板/零件族）时，尺寸与结构不是边建边定，而是先落参数表和 schema，再由模板实例化；决策与验收口径见 `reverse-engineering.md` §11，这里只记构造配方。

- **命名分层**：`<结构>_<量>`（`PLATE_T`、`TOWER_H`、`EYE_U`、`SLOT_CEIL_R`），结构前缀让"改一个参数动哪个结构"可读；不用 `p`/`P` 前缀（§1.7）。
- **派生约束写成公式**，不要在两处写相等的字面值：`ROOT_FILL_U = U_BACK - ROOT_FILL_R`、`TAPER_R1 = TAPER_R + TAN4 * TAPER_T1`。父参数一改子量自动跟；两处字面值会在第一次编辑时就分叉。
- **无单位量**用 `CreateSystemExpression("Number", "TAN4 = tan(TAPER_HA)")`；`GetBase("Number")` 报错，长度/角度分别 `GetBase("Length")/("Angle")`（§4.1）。
- **轴心/方向的字面值陷阱**：圆柱、圆锥 builder 的轴向点与方向是字面值，改半径表达式不移动轴心。需要"随板厚移动"时，让高度承担变化（起点固定、`Height = T + BOSS_H`），或改用草图圆拉伸；把轴心写成另一个 Expression 再赋给 builder 不可靠。
- **模板层入口**：`nxlib.template` 负责参数表 → 表达式 → 告警读取 → 编辑矩阵；结构模板代码只读 `ctx`（工作部件 + 表达式表），零件常数留在 schema。

```python
from nxlib import template
values, units = template.param_table(template.load_json(SCHEMA))
exprs = template.create_expressions(wp, values, units)
plane = template.structure_params(template.load_json(SCHEMA), "plate")
cell = template.edit_check(wp, exprs["PLATE_T"], +1.0, probe=plate_probe)
```

- **模板件里的圆角**：优先边圆角/解析圆环带；FaceBlend 的支撑面集合会随参数移动而硬失败（`Update undo happened`），不当可编辑件的主圆角机制。上游尺寸会重建被圆角边时，把上游改成派生约束让边不动，或把该边排除出圆角集合；`blend edges consumed` 告警会随文件存盘。

### 1.13 草图驱动轮廓 + 骨架帧（让设计参数真的能驱动几何）

**适用**：轮廓简单（圆/矩形/台阶/扇形）、尺寸要由命名表达式驱动（模板/零件族/逆向重建）。测量轮廓（短弧+倒角+偏移线）不要开自动尺寸——会被拉变形，走 §1.5 固定约束 + 数据层字面值。

- **配方**：`make_sketch_dims(wp, curves, links=[(数值, "2 * R_TEST"), ...])` 建草图 → AutoDimension 出尺寸 → 按数值把尺寸改指命名表达式，返回 `(sketch, 改指数)`。改指后 `GetStatus()` 的 dof 归 0；`R_TEST ×1.5` 后体积按 r² 变 2.25 倍，还原回原值（`tests/37`）。
- ⚠ **多边形原语的尺寸点必须落在它自己的默认半径上**：`CreateSketchPolygonBuilder` 建出的多边形初始半径是默认值（100），若把尺寸点直接放在目标半径（如 4.0）再去改绑半径尺寸，约束是"尺寸点到多边形中心的距离"而不是标定半径，改绑后整个多边形**平移**到别处而不是缩放。做法是先读 `poly.RadiusDimension.RightHandSide` 取种子值把尺寸点放在该半径上，再对圆心与尺寸点各加 `CreateFixedConstraint`，之后改半径才只缩放不变位。
- **主要前提**：**不要先跑 `AutoConstrain`**——它会把简单轮廓标成完全约束且不产生表达式，随后的 AutoDimension 一个尺寸都不出。曾把"0 尺寸"归因于"少调 `GetStatus`"，受控实验证明 `GetStatus` 只用来读 dof，少调不影响出尺寸。已知证据只覆盖简单轮廓上的这种抢占；复杂轮廓的其它 0 尺寸成因未逐一排除，别把这一条当唯一解释。
- **links 的数值要写自动尺寸真会生成的量**（半径、直径 2r、长度），匹配按 `float(RightHandSide)` 1e-6；写推导量匹配不上时该尺寸不改指、也不报错，只表现为返回的改指数偏小——用改指数与 links 条数对账。
- **骨架帧**：`Frame.from_azimuth(az, origin)` 给径向 U、切向 V、+Z；构造函数即校验两两正交，非正交在构造处抛 `ValueError`，不要等提交特征才失败。`frame.pt/vec/vec3` 是唯一坐标出口，结构代码里不手写 sin/cos。
- **设计/数据分层**：设计量进命名表达式（`PLATE_T`），测量轮廓坐标留字面值（data 层，用 `polyline`/`loop_*` 传入），`schema_skeleton` 核对每个结构 design∩data=∅（分工见 `reverse-engineering.md` §12.2）。
- **基准轴/面**：`skeleton.axis/plane` 建的是 SmartObject，位置与方向按 data 字面值；需要随参数移动的量交给草图尺寸或拉伸起止承担。datum 能否由表达式点驱动未验证，不要当可驱动件用（同 §1.12 轴心陷阱）。
- **预算先算再建**：`audit.budget` 按结构数报 4N+12 特征上限（N=4 → 28），不是按特征数反算；建前过一遍，超了就减结构而不是加补丁特征。

### 1.14 拉伸拔模与分段回转（结构级 builder 的两条承重配方）

**拔模**：`ExtrudeBuilder.Draft` 是 `MultiDraft`。先设类型再设角度，两步缺一不可——只设角度提交成功、无告警、体积与直壁逐位相同：

```python
b.Draft.DraftOption = NXOpen.GeometricUtilities.SimpleDraft.SimpleDraftType.SimpleFromStart
b.Draft.SetDraftAngle("DRAFT_A")     # Angle 单位的命名表达式
```

拔模后起剖面在拉伸起点、按半角收缩；量得轮廓在这两者之间。验收只能对锥台解析值：矩形截面 `V = h/3·(A₀ + A₁ + √(A₀A₁))`，回转截面 `V = πh/3·(r₀² + r₀r₁ + r₁²)`。体数、面数、告警都区分不出"拔模没生效"。

**分段回转**：`revolve` 走 UF `Modl.CreateRevolved`，360° 只吃凸轮廓；带台阶/凹陷的整条轮廓报 `Cannot create Swept geometry`。按 (t, r) 轮廓切段、逐段回转再 unite，台阶落在段界上，不被平滑掉：

```python
res = structures.revolved_profile(wp, [(0.0, 20.0), (10.0, 20.0),
                                       (10.0, 12.0), (30.0, 12.0)],
                                 name="SHAFT")   # r=0 的点在轴上，零长度段自动跳过
```

同一阶梯轴，64 边形 z 带堆叠 131 面、分段回转 5 面（26.2×），体积一致——**面数爆炸是构造选择，不是网格化偶然**（`tests/47`）。（同 §2.2 的"共面堆叠要用表达式定起点"；那里是层的起点，这里是层的构造方式。）

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
- **斜轴孔/锥孔切除**：`CreateCylinderBuilder(Feature.Null)` → `Type=Types.AxisDiameterAndHeight`、`Axis=wp.Axes.CreateAxis(Point3d, Vector3d, UpdateOption)`、`Diameter/Height` 写 `.RightHandSide` → `CommitFeature()`；锥孔用 `CreateConeBuilder(Cone.Null)` + `Types.DiametersAndHeight` + `BaseDiameter/TopDiameter/Height` + `Axis`。两者都**不设布尔**，提交后单独 `CreateBooleanBuilder(Subtract)` 与目标体相减。验收：1 实体，圆柱切除体积按 πr²h、锥孔按 πh/3(R²+Rr+r²) 下降。
- **独立圆柱凸台**：同一 builder 用 `Origin`（Point3d，底面圆心）+ `Direction`（Vector3d）也能建，不必先建轴；提交后 `CreateUniteFeature` 合并。验收：合并后单实体，体积 = 基体 + πr²h。

### 2.2 拉伸（Section 路线）

- `Sections.CreateSection(0.0009, 0.001, 0.01)`：3 容差重载。
- `ExtrudeBuilder.Section` 恒为 `None`：先建独立 Section，再赋给 builder。
- `AddToSection` 的 seed/connector 传 `NXObject.Null`（`None` 报 `No overload matches`）。
- 显式设 `Direction`（否则 `No axis selected`）。
- `Curves.CreateArc` 的 startAngle/endAngle 用**弧度**。
- 示例：`scripts/tests/01_bracket.py`。
- **截面必须在新建件里建**：`Parts.FileNew()` + `model-plain-1-mm-template.prt` 提交后 `SetDisplayPart`。在打开的原件上下文里对同一组曲线调 `AddToSection` 抛 `NXException: Internal error`（与 helpPoint 无关，换料内点同样报错）。
- **多环截面 = 带孔轮廓**：一条规则含全部曲线、或每环一条规则逐次 `AddToSection`，两种写法等效，结果是单个实体（可多 lump），内环成孔；体积与解析值比较时扣掉多边形化误差。
- **每环必须精确闭合**：内环留 0.03 mm 缝时该环被静默丢弃，孔变实心；外环留 0.03 mm 缝时链被错误闭合，体积异常增大。截面环拼接后要校验首末点重合。
- **拔模拉伸的起剖面偏置**：`SimpleFromStart` 的起剖面在拉伸起点、向上按半角收缩；中面轮廓等于量得轮廓时，起剖面取中面外偏 `h/2·tanθ`。角弧拔模后是圆锥，中面半径 = 起剖面半径 − `h/2·tanθ`；中面截面作为验收站。
- **拔模角度**：`ExtrudeBuilder.Draft` 是 `MultiDraft`；先 `d.DraftOption = NXOpen.GeometricUtilities.SimpleDraft.SimpleDraftType.SimpleFromStart`（或 `SimpleFromProfile`）再 `d.SetDraftAngle("<deg>")`，正值向拉伸端收缩。只设角度不设类型 = 静默无效：提交成功、无告警、体积与直壁逐位相同；生效判据 = 体积显著低于直壁。
- `helpPoint` 取料内一点；落在曲线上的点不可用。

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
- 相邻截面面积突变（接近 3 倍）时，原始截面直接放样报 "Cannot create B-surface by through curves"；重采样后可提交，但常得到体积 0 的退化实体，必须按下面的体积校验走。
- 段数/类型不一致的截面先重采样成同一 N 点折线（每段一条 `CreateLine`，N=160），再用 `CreateJoinedCurve(tags[:-1], 1)` + 最后一段组 Section。这条折线是放样输入，不是交付边界：放样后按面表半径重建解析圆弧，等截面件直接用直线 + 圆弧建截面（见 `reverse-engineering.md` §2）。参数化按截面相似度选：
  - 弧长等分 + 起点对齐上一站：相邻两站形状相近时用。
  - 绕形心等角：面积/拓扑变化大时用。面内取 N 条等角射线与闭合环求交，每角取最外交点；索引 k 即固定角度，无需起点对齐。基向量必须是测站平面内的两轴（常半径站族的法向是径向，面内轴为切向与 z）。该参数化只对星形截面保形，凹口会被最外交点填平；保留凹口时先放样外轮廓再切凹入区。
- **提交后必须查体积，不只看 `IsSolidBody`**：对应关系扭曲时 `ThroughCurves` 仍提交，得到 `IsSolidBody=True`、体积 0 的自交实体；截面扫描线 IoU 仍可到 0.99，不能作为实体有效证据。体积为 0 时换绕形心等角参数化重做。
- **≥5 张截面时给首站加定位截面**：后段形状会把首站附近的曲面拉低；在首站外侧 2 mm 加一张同形、沿放样轴平移的截面，首站即可恢复。
- **`BodyPreference=Solid` 也可能出片体**：提交后查 `IsSolidBody`；片体不可与实体合并（"Cannot add solids and sheets"）。
- 两段实体合并：NX12 批处理里 `BooleanBuilder.Target/Tool/Tools` 会静默不执行（体数、体积都不变），`Tools.Add` 也不报错；用 `wp.Features.CreateUniteFeature(target, False, [tool], False, True)`。共面接触被拒（"zero wall thickness"/"completely outside"）。两段在同一区域体积重叠但侧面是同一张放样面时也失败（"Intersecting target and tool faces may have problems that cause intersection gaps"），此时不要加偏置领圈硬拼，改做一张连续放样；定位截面（上一条）是替代方案。合并前给 0.5–1 mm 重叠，合并后断言体数 = 1 且体积单调增加。合并报 intersection gaps 时把截面折线减到只保留棱线点（或改一条光滑闭合样条）；共面报 zero wall thickness 时把人工封口面错开 0.1 mm。
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

⚠ **孔位贴边 = 零壁厚**（`... zero wall thickness`）；孔边与轮廓之间留出壁厚，不要把孔放到轮廓边上。

锥孔（functional cone）用 UF 旋转一条凸梯形剖面切成型，不用 Hole 特征：

```python
# 孔径目录里的 center 是包围盒中心，radii 是 UF 面在面基准点处的半径，
# 两者不在同一轴向站。锥面必须用面基准 (point, radius) 定义，否则半径可差 0.06 mm。
# s 沿 axis 增加：r(s) = R_datum + (s - s_datum) * tan(half_angle)
s_datum = dot(datum_point - center, axis)
R_center = R_datum - s_datum * tan(half_angle)
# 剖面：轴上两点 + 两侧半径，绕 axis 旋转 360
pts = [c + s0*a, c + s0*a + r0*p, c + s1*a + r1*p, c + s1*a]
feats = ufs.Modl.CreateRevolved(tag_list, ["0.0", "360.0"], c, a,
                                NXOpen.UF.ModlFeatureSigns.NULLSIGN)
wp.Features.CreateSubtractFeature(target, False, tool_bodies, False, True)
```

- 凸梯形可以有两条边落在旋转轴上（360° 旋转可用）；凹剖面/带台阶剖面才报 "Cannot create Swept geometry"。
- 切完用 `ufs.Modeling.AskFaceData` 回读锥面：type 17、`rad_data` 即半角（弧度）、`radius` 在面基准点处。与孔表比较半径时，把两侧都归一到同一轴向站（面基准点），不要直接比原始 `radius`——UF 的面基准点随修剪边界移动。
- 旋转轴方向与孔表 axis 相反时，`AskFaceData` 的 dir 会翻转；比较轴向用绝对值点积。
- **孔轴与板法向不同（斜耳孔）时，耳座绕孔轴回转成圆柱再并**：棱柱只建到耳座切点，圆柱半径与轴向区间取面表；把棱柱直接沿板宽拉伸会把圆耳座包成方块，端站截面多料。反例与判据见 `reverse-engineering.md` §2.2/§4.2。
- **孔包的入口延伸与锪面深度**：`HolePackageBuilder` 的刀具在孔位前固定延伸约 2 mm，量得孔壁起点更靠近入口面时改用独立圆柱切除体按轴向区间建；锪面形式的孔深必须大于 `(锪径−孔径)/2/tan(半角)`，通孔已存在时也写成该值加 1 mm。细则见 `reverse-engineering.md` §8。
- **锥底沉孔**：沉孔底面是锥面时，把沉孔深度减 `t`，用一把 45° 锥刀（底径 = 孔壁 − 2·t、顶径 = 孔壁、高 `t`）切底；不加实心锥填角，会堵孔并报 "zero wall thickness"。

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
- ⚠ `ChamferBuilder.FirstOffset` / `.Angle` 是普通 `str` 属性，不是 `Expression` 对象。写 `builder.FirstOffset.RightHandSide = ...` 会抛 `'str' object has no attribute`；要给命名表达式驱动，直接赋表达式名（`builder.FirstOffset = "TIP_CHAMF_L"`），特征树里会记成该名字的引用，改表达式仍然驱动几何。
- `EdgeBlend` 在角点处不能逐条相邻边倒圆：同一顶点的相邻边要放进同一个 ChainSet，否则报 "Unable to terminate the blend faces"。FaceBlend 走两支撑面，不共享这条限制（见下）。
- **双瓣耳/眼**：矩形块沿孔轴拉伸，平台两侧各一条顶边倒 `R_EYE`，肩面应得到解析圆柱（类型 16）；平台半宽用系统式（`W_HALF = H_LOBE + R_EYE`）。端面整圈倒 `R_END` 得到环面（major = R_EYE − R_END、minor = R_END）。
- **口部双圆角顺序**：布尔减后在目标体口边加，先下口、后上口；每次 blend 后跑 no-op `DoUpdate`，面数不变、无告警。腔顶凹边增大半径会增加体积，凸口减小体积；同一表达式驱动多个体时按体拆名。
- 验收：孔口倒圆/倒角后体积下降；双棱边产生 2 个面、单直边 1 个面；倒角锥面 type **17**、直边倒角平面 22。

**两支撑面 FaceBlend（曲面支撑首选）**：支撑面是圆柱/圆锥/环面/B 曲面时，滚圆刀的截面边界不再是直线，改用 FaceBlend 的两面模式：

```python
from nxlib.modeling import face_blend, face_blend_edge

feat = face_blend(wp, face_a, face_b, 1.5875, True, True)
feat, rev = face_blend_edge(wp, edge, 1.5875)  # 未知法向组合时自动试
```

- 建造器固定 `BlendTwoFace` + `FirstFaceCollector`/`SecondFaceCollector` + `CircularCrossSection.SetRadius`；`BlendFromEdges` 只给边链会报 `combination ... not sufficient`。不要设 `OverflowOption.None`（NX12 无此枚举）。
- 法向组合不固定：凸平面-平面、凹口通常 `(True, True)`；凸圆柱-圆柱常见 `(False, False)`。`face_blend_edge` 按 `(TT, FF, TF, FT)` 各在自己的 undo mark 内试，失败回滚，返回成功的 `(rev_a, rev_b)` 并可用 `trace` 记录。
- 前置检查：**至少两条支撑面各自 ≥ `R + 0.5 mm`**（一个滚球圆角在两侧各吃掉一个 R，一条跑道旁常挂着尽端面与侧壁，按"最窄邻面"判会把可倒的跑道误标成障碍）、边处二面角 20°–160°、边长 ≥ `0.5R`。`Radius is too large/small for the faces selected` 是支撑面太窄或近相切，不是法向错；回建模加宽/重建支撑面，不要降半径。
- 开放链逐段 `face_blend_edge`，每段成功后按几何重找下一条边；闭合矩形窗口四段可逐段提交、0 告警。角部若原件是环面，另建角过渡；不要用直线段圆角冒充整圈。
- 结果面型：直边平面-平面 → type 16、`radius` = R；圆形平面-圆柱 → type 19、`rad_data` = R、`radius` = 主半径；圆柱-圆柱可能是 type 43。验收按半径/环面主副半径 + 体积变化。
- 命名表达式可驱动 `CircularCrossSection.SetRadius`：×1.1 后体积变化、还原后体积差 0、`DoUpdate` 0 错；这是可编辑性门的要求。
- **B 曲面只在真二面角上做**：放样条带之间的近相切缝是折面近似，FaceBlend 会“成功”但只生成近零体积薄片，不代表圆角已建；该处应回建模重建支撑面。

**开放链圆角刀（EdgeBlend 的替代）**：边不闭合（端缘折面链、开放轮廓边）时 `EdgeBlend` 提交会存下 `Unable to terminate the blend faces`，且没有 API 能清——不要在真实零件上试。用 `nxlib.modeling` 的滚圆刀：

```python
from nxlib.modeling import apply_roll, roll_edge

# 交钥匙：凸凹自动判、一个布尔、失败回滚，返回 (ok, 新实体)
ok, body = apply_roll(wp, body, edge, radius)
```

- `roll_edge(wp, edge, R)` 只建刀，返回 `(feature, 预期体积)`，调用方对 `feature.GetBodies()[0]` 做一次布尔（凸 Subtract / 凹 Unite）；`apply_roll` 封装判定 + 布尔 + 回滚。`trace=[...]` 收拒绝原因（短边/面型/夹角/切点退化）。
- **滚圆段必须建精确圆弧**（`Curves.CreateArc`），不能用 16 点折线。折线拉伸得到的是 16 张窄平面而不是圆柱：G7 半径组一个面也计不到，面数还翻倍；切点处用弦接圆弧会切进面内，留下 0.2–0.5 mm 宽、比原面低 0.01–0.2 mm 的平台（面表多出一族偏置平面）。角点外偏 0.1 即可，切点不回缩。
- **凸凹按两邻面的相互侧判**（`edge_is_concave`）：凸边时两个邻面都落在对面的材料侧（法向负侧），凹边时都落在空侧。体积不能判：凹边按凸边先减也会“成功”切掉一刀（等于在凹角开槽）。只对两平面邻边有效；曲面邻边跳过。
- 弧段与直边共点、截面在 edge 的局部系内建（`e1 = sgn*n0`、`e2 = d × e1`、滚心 `o·u_i = R`），拉伸方向沿边、终点穿出 `ee = min(0.8, 0.25L)`；起点与边端点平齐（起点在顶点处与邻边相接，穿出会切掉邻边该留的料），刀具体不要与目标体共面收尾。
- 截面与拉伸必须在 undo mark 内建，布尔失败立刻 `UndoToMark` + `DeleteUndoMark` + `UpdateManager.ClearErrorList()`，然后重新取实体（`part.Bodies` 的包装对象已失效）。
- **已成功提交的圆角不要回滚**：回滚后实体 out-of-date，质量属性读 0，下一次布尔报 `Tool body completely outside target body`。逐条滚时“成功就留在树上”。
- 候选边先筛：两面都是平面（type 22）、夹角 30°–150°、长度 ≥ max(1.2R, 自身面宽)；法向与边方向夹角 >60° 的面是前次刀具的端面，跳过。不筛会有一半尝试落在近共面残边（夹角 <10°）上。这是"值不值得试"的预筛，不是可行性判据；`apply_roll` 的刀具有默认 ≥4R 行程门槛，判"倒不出来"用 `structures.fillet_feasible` 的 ≥0.5R。
- 端缘是 2–5 mm 折面链时逐段滚，长度下限放到 1.2R，两端仍各穿出 0.8；相邻两段的刀具有重叠，顶点处自然形成过渡，不必另建球面。
- 每条边记中点（四舍五入到 0.01），被拒的边不再重试，否则重扫循环不收敛。
- 验收：滚出的圆角面是类型 16、`radius` = 圆角半径（直边，精确圆弧）或类型 19（`rad_data` = 圆角半径、`radius` = 主半径）；体积按“截面面积 × 边长”校验在 35% 以内（凸减、凹加）。

### 2.5 布尔与孔壁识别

**布尔路线**：`CreateBooleanBuilder(NXOpen.Features.BooleanFeature.Null)` → `SetBooleanOperationAndTarget(Subtract/Unite, target)` → `CommitFeature()` → 断言体数。方块布尔只用这条入口；`BooleanOption.Type`+`SetTargetBodies` 会静默不生效（体数 1→2）。

- **目标体与刀具按 Tag 识别**：每次访问 `part.Bodies` 返回新的包装对象，用 `is` 比较会选错体；操作前记下 tag 集，操作后取新增 tag 的体作为结果，刀具只取本次新建的体。

- 工具体与目标体必须**真正体积相交**；面/点/线接触会静默留两个体，工具体在外报 `Tool body completely outside target body`。
- 相切工具体被拒（`... zero wall thickness.`）：留间隙或先合并；缩小凸台直径留出间隙，不要靠调整布尔顺序。
- 孔壁识别：遍历 `GetFeatures()` 找 `FeatureType == "SUBTRACT"` 后取 `GetFaces()`，或 Hole 特征用 `AskFaceData` 按半径过滤（§5）；不要按"所有圆柱面"过滤。
- 依次合并每步接触当前材料；命名体数与实际体数不符时查孤立体。
- **切孔的验收看面表，不看体积差**：锥座若落在已挖空的腔里，切除仍会小降体积（数百 mm³）却不产生锥面。每把刀提交后按半径/半角/孔心核对新增面，再进入下一把。
- **失败的布尔要包 undo mark**：合并重试的分支失败后若不 `UndoToMark`，失败特征会留在树上变成告警（UNITE/EXTRUDE 都会），表达式可编辑性直接不过。

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
⚠ 验收：孔壁 type=16 半径=HD/2；孔口倒圆 type=19，`radius` = 主半径 = HD/2 + 倒圆半径。
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
# ⚠ 剖面含落在轴上的边时其余弦凸剖面可用（360° 可用）；凹剖面或带台阶/凹陷剖面报 "Cannot create Swept geometry"。
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

### 4.1b 参数表驱动与局部编辑检查

参数表驱动的件，验收不是"建出来了"，而是"改一个参数只动一个结构、还原可逆"：

```python
base = template.snapshot(part)                      # 体积/体数/面数/包盒/告警
cell = template.edit_check(wp, exprs["PLATE_T"], +1.0, probe=plate_probe)
cells = template.edit_matrix(wp, exprs, [("PLATE_T", +1.0), ("BOSS_D", 8.0)])
print(template.clean_cells(cells))                  # 干净格/总格
```

- `edit_check` 是"改值 → DoUpdate → 读数 → 还原 → 再读"：`update_errors`/`restore_errors` 都必须是 0，`diff_snapshot(base, after)` 只列变化项（体积/面数/包盒/告警），本结构 `probe` 读数用来证明"动的是该结构"。
- 还原后体积/面数与基线不逐位相同 → 更新过程重写了几何，该参数不适合直接驱动；先改引用，不要加豁免。
- 单格异常（如 `Update undo happened`）记 `invalid` 继续下一格，整张矩阵跑完再归因；一格崩掉整轮等于没有可编辑性证据。
- 局部性判据：无关结构的读数变化在 STL 噪声内（1e-6 相对或 1e-5 mm 量级）；超了就是引用串了结构。
- 矩阵只覆盖挑出来的参数，交付前另做全表普查：每个命名表达式 +10% → 体积响应，live/named ≥0.9、broken=0；派生量不进编辑集（改其 RHS 会破坏公式，还原报变量不存在）。

### 4.2 自动约束 / 自动标注（替代手加约束）

```python
sk.AddGeometry(NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
               NXOpen.Sketch.AddEllipseOption.TreatAsEllipse, curves)
sk.GetStatus()          # 查 dof 用；不是出尺寸的前提（见下条）
adb = wp.Sketches.CreateAutoDimensionBuilder()
adb.SelectionObject.SetArray(curves)
adb.SetRules([NXOpen.Sketch.AutoDimensioningRule.Length,
              NXOpen.Sketch.AutoDimensioningRule.Symmetric])
adb.DimensionType = NXOpen.SketchAutoDimensionBuilder.DimType.Driving
adb.Commit(); adb.Destroy()  # 自动生成驱动尺寸表达式
sk.GetStatus()
```

- **“AutoDimension 不出尺寸”的已知主因是先跑了 AutoConstrain**：AutoConstrain 会把简单轮廓直接标成完全约束且**不产生表达式**（圆 3→0 DOF，表达式表为空），随后 AutoDimension 无事可做。需要自动尺寸的草图**不要**先 AutoConstrain；两者都用时按 `auto = not dims` 分流。
- **`GetStatus()` 不是前提**：AddGeometry 之后不调 `GetStatus` 直接建 AutoDimension，尺寸照出；0 尺寸的原因是先跑了 AutoConstrain，不是少调 `GetStatus`。
- ⚠ AutoDimension 会**挪动几何**：测量轮廓（尤其小圆弧）会被拉到自交，拉伸体体积异常增大。测量轮廓只加固定约束，自动约束/自动尺寸只用于简单轮廓。
- **适用边界**：圆、矩形、扇形弧+线、10 点台阶轮廓安全（几何/体积不变）；曲线多、段长的轮毂轮廓会生成大量线长/角度尺寸而不是设计半径，**不可用**。轮廓越接近测量数据（短弧、倒角、偏移线越多），越不要开自动尺寸。

### 4.2b 自动尺寸 → 命名参数（简单轮廓上的可行参数化路线）

```python
for e in sk.GetAllExpressions():                 # 自动生成的驱动尺寸
    try:
        val = float(e.RightHandSide)
    except Exception:
        continue                                 # 已是表达式名，跳过
    for target, rhs in links:                    # (2 * R_WEB, "2 * R_WEB") ...
        if abs(val - target) < 1e-6:
            e.RightHandSide = rhs
```

- 改参数后实体精确跟随（圆半径 → `R_WEB`，体积按解析值变化），且尺寸仍是驱动尺寸。
- 同一草图多个尺寸时要成对链接直径/半径（`2 * R` 与 `R`），否则约束自相矛盾。
- **系统式与位置量**：联动尺寸可以写成系统式（`W_HALF = H_LOBE + R_EYE`），但每个独立结构尺寸都要有数值参数入口；块原点、圆柱轴心在批处理只收字面值，列入不可参数化清单，不伪装成命名表达式。
- **草图点不可标注**：对单点跑 AutoDimension 产生 0 尺寸、dof 不变；NXOpen 也没有参数化点特征（`PointFeatureBuilder.Point` 只收字面 `Point3d`）→ 孔位无法用“草图点 + 尺寸”参数化。
- 驱动参数必须真的接到几何上：接到会移动的边上时，先确认改参数不会让该边的主人变化（见 §4.3 的拓扑陷阱）。


### 4.3 草图尺寸与约束路线

- 尺寸与约束：简单草图走 §4.2；测量轮廓走 `sk.CreateFixedConstraint(NXOpen.Sketch.ConstraintGeometry(c, NXOpen.Sketch.ConstraintPointType.NotSet, 0))` 逐条固定，dof 未归零时再对每条试 `ArcCenter / StartVertex / EndVertex`（无效点类型会抛异常，逐条 try 即可）。`ConstraintPointType` 的“无点”成员是 `NotSet`（不是 `None`）。
- **非 XY 草图平面只能靠 Reattach**（NX12 批处理）：`PlaneReference` 无论配 `PlaneOption=ExistingPlane/NewPlane/NewCsys`、`PlaneCollection.CreatePlane(FixedY)`、`CreateFixedPlane` 还是 `CreateSketchInPlaceBuilder2` 都被忽略，提交后 `AttachPlane.Normal` 仍是 (0,0,1)。可行路线：
  ```python
  db = wp.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)   # ⚠ 参数是 Feature.Null
  db.SetPointAndDirection(wp.Points.CreatePoint(pt),
                          wp.Directions.CreateDirection(pt, Vector3d(*normal),
                              NXOpen.SmartObject.UpdateOption.WithinModeling))
  dpf = db.CommitFeature(); db.Destroy()
  ab = wp.Features.CreateDatumAxisBuilder(NXOpen.Features.Feature.Null)
  ab.SetFixedDatumAxis(NXOpen.Features.DatumAxisBuilder.FixedType.Z)      # Z 必须落在草图平面内
  daf = ab.CommitFeature(); ab.Destroy()
  # 先按默认平面建草图，再：
  sk.Reattach(dpf.DatumPlane, daf.DatumAxis, NXOpen.Vector3d(0,0,0),
              NXOpen.AxisOrientation.Horizontal, NXOpen.Sense.Forward,
              NXOpen.PlaneNormalOrientation.Outward, NXOpen.Point3d(*origin))
  ```
  `CreateSketch(..., attachmentPlane=dpf.DatumPlane, referenceAxis=...)` 这条直接建草图的路走不通（referenceAxis 传 DatumPlane 报 “wrong type”，传 DatumAxis 报 “Orientation ... invalid”）。
- **AddGeometry 只收 NXOpen 对象**：UF `CreateArcThru3pts` 返回 tag，必须改用 `Curves.CreateArc(center, xaxis, yaxis, r, a0, a1)`；三点弧用外接圆公式自行求心（端点必须与相邻线严格重合，否则拉伸报 “Section curves are not connected each other”）。
- **`RevolveBuilder` 对草图截面崩溃**（`memory access violation`）；改用 UF `Modl.CreateRevolved`（草图曲线可用，体积与解析值一致）。
- `Sketch.CreateDimension` / `CreateRadialDimension`、`SketchLinearDimensionBuilder.FirstAssociativity` / `SecondAssociativity`、`SketchConstraintBuilder.GeometryToConstrain` / `GeometryToConstrainTo` 批处理不可用（只读或 `No overload matches`），不要在这条路线上尝试。
- **共面堆叠特征要用表达式定起点**：板顶上的垫环/筋/轮缘/缺口，拉伸起点写 `Limits.StartExtend.Value.RightHandSide = "T_PLATE - 15.875"`，不要写 `"0"`。写死 0 时改 `T_PLATE` 会让上层特征与板顶脱开或互相吞并，更新整体回滚。
- **倒圆不要贴在会移动的边上**：沉孔上沿的倒圆在驱动参数 +10% 后边的主人改变，整个更新回滚（“Update undo happened”）。要么把倒圆放到所有驱动参数之后，要么换一条不随参数移动的边。
- **同一个 `FileNew` 只能建一个零件**：一个进程里第二次 `FileNew` 之后草图报 “Sketch is not initialized”、更新报 “Update undo happened”。批量跑多案例用进程级环境变量分流，一进程一案例。
- 草图级镜像走不通（`SketchMirrorPatternBuilder.DirectionObject` 只读）；对称件用特征级 `MirrorFeatureBuilder`（§3.2）。
- 面查询用 §5 的 `AskFaceData`（`Part.Faces.FindFace` / `Face.IsPointOnFace` 不存在）。

### 4.4 孔与螺纹路线（`HolePackage`；`scripts/tests/26_hole_package.py`）

- 螺纹用 HolePackage：`CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)`，`Type` = `DrillSizeHole / GeneralHole / HoleSeries / ScrewClearanceHole / ThreadedHole`（NX12 没有 `Thread`/`CreateThreadBuilder`/`ThreadFeatureBuilder`）。
  ⚠ 类型是**可写属性 `Type`**（`b.Type = …`）；`Types` 是只读枚举类。
  ⚠ 枚举用模块级类（`HolePackageBuilder.Types.ThreadedHole`、`…HoleDepthLimitOptions.Value`、`…ThreadLengthOptions.Standard`）；写成 `b.Types()` 抛 `NXException: instances of NX enums can not be created` 并中断 journal。
- ⚠ 孔向默认 `FaceNormal`：孔位点落在两面共面的接缝/共线边上时报 "No closest face found within tolerance for Normal to Face direction option"。必须显式切到矢量：
  ```python
  hb.ProjectionDirection.ProjectDirectionMethod = \
      NXOpen.GeometricUtilities.ProjectionOptionsDirectionType.Vector  # CrvPlaneNormal/FaceNormal/Vector
  hb.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(pt, NXOpen.Vector3d(0.0, 1.0, 0.0))
  ```
  只设 `ProjectVector` 不切方法无效（方法仍是 FaceNormal）。

孔位：只读 `Section`，点用 `ScRuleFactory` 灌入：

```python
pt   = wp.Points.CreatePoint(NXOpen.Point3d(30.0, 20.0, 20.0))
rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])
b.HolePosition.AddToSection([rule], pt, NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                            NXOpen.Point3d(30.0, 20.0, 20.0), NXOpen.Section.Mode.Create, False)
bt = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
b.BooleanOperation.SetBooleanOperationAndBody(bt.Subtract, body)
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
| `GeneralHole` + 沉孔 | `GeneralHoleForm=HoleForms.Counterbored` + 通孔 `GeneralCounterboreHoleDiameter/Depth` + 沉孔 `GeneralCounterboreDiameter/Depth` | 验收值：60×60×10 块，Ø10 通孔 + Ø20×4 沉孔，去料 1 727.876 = 解析值 |
| `DrillSizeHole` | `DrillSizeStandard="ISO"` + `DrillSizeFitOption="Exact"` + `DrillSize` 标签（`"10"`）**且** `DrillSizeHoleDiameter/Depth` | 只给标签 → 默认 Ø11 贯通；只给 Expression → `Standard data not found` |
| `ScrewClearanceHole` | `ScrewStandard="ISO"` + `ScrewType="General Screw Clearance"` + `ScrewSize="M10"` + `ScrewFitOption="Normal (H13)"` | 过孔 **Ø11** |

- 直径/深度字段都收表达式名（`"D_BOLT"`、`"2 * R_BRKT_HOLE"`），命名参数才能驱动孔特征；写 float 只会固化成字面值。

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
- **特征按结构划分，不按层划分**：一个结构一个特征（基体、筋、臂、凸台、回转体、腔）；禁止把测量截面逐层拉伸成特征堆栈——那会让特征树变成 z 带编号表，改一个结构要动十几层。切片只用于测量与核验。
- **草图完全约束**：`status, dof = sketch.GetStatus()`（不传参、返回元组）；`WellConstrained == 3` 且 dof=0。
- **参数可改**：顶层尺寸命名表达式（§4.1）；关键特征 `SetName`。
- **表达式必须被引用**：逐个改 ±10% 后 `DoUpdate`，体积必须变；体积不变的是死参数（特征里用了字面值），接进特征后再交付。
- **层间不要共面堆叠**：上游厚度表达式一变，共面处拓扑重排会让下游圆角边失效并回滚；让切除工具穿过目标面，或给 0.5 mm 重叠。
- **无垃圾几何**：未参与建模的线转参考线或删除。
- **交付前验证**：`08_editability_probe.py`；数值见 §3.5；`Point3d` 坐标不受表达式驱动。
