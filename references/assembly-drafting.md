# 装配与工程图域（NX 12 本机批处理实测）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。§A 装配（A.5 为运动连接/可拖动机构）、§B 工程图；⚠ 均为实测结论。可跑示例：`scripts/tests/04/06/07/10/16/17`，工程图标注链路见 `scripts/tests/19`。

## A. 装配

### A.1 添加组件与组件操作

```python
m = NXOpen.Matrix3x3(); m.Xx = 1.0; m.Yy = 1.0; m.Zz = 1.0   # ⚠ 无参构造为全 0，必须手动置对角
comp, status = assy.ComponentAssembly.AddComponent(
    part_path, "1", "MODEL", NXOpen.Point3d(0,0,0), m, 1)     # ⚠ 返回 (component, loadStatus) 元组
children = assy.ComponentAssembly.RootComponent.GetChildren() # ⚠ 没有 .Components 属性
```

⚠ `Matrix3x3` 的**列向量 = 组件局部轴**（2026-08-22 实测）；姿态角（如 TH1）经表达式驱动后按列向量构造矩阵。
⚠ `ComponentAssembly.MoveComponent` 语义不可靠（2026-08-22 实测）→ 重定位组件用 Remove + `AddComponent` 按新位姿重加；重加后组件 `Name` 变 "MODEL"，取显示名用 `DisplayName`。
⚠ 验证后才保存；NX GUI 不热重载，批处理改过的装配需重开文件（见 modeling.md §1.8）。

### A.2 配对约束（2026-08-23 实测通过，回归 `scripts/tests/10_assembly_constraints.py`）

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
session.UpdateManager.DoUpdate(mark)                 # ⚠ 关键 1：缺 DoUpdate 则 Solve 无错但组件不动
net = pos.EstablishNetwork()
net.AddConstraint(con)
net.Solve()                                          # 返回 None=无错
net.ApplyToModel()                                   # ⚠ 关键 2：把解算变换应用到组件
con.SetName("PinOnBase_Touch")
pos.ClearNetwork(); pos.EndAssemblyConstraints()
c_moving.GetPosition()                               # (Point3d, Matrix3x3) 验证已贴合
```

坑位（全部实测）：
- `con.Type` 属性 Python 封装只读 → 必须用 `con.ConstraintType`。
- Distance 的 `con.OffsetRightHandSide` setter 报 "Not yet implemented" → 尺寸定位改用 AddComponent 显式坐标或 Touch/Concentric 组合。
- `Component.GetDegreesOfFreedom()` 读数**不能单独当判据**，只能作辅助：必须在约束仍存活时读（先删持久约束再读，任何件都会回到 `3T+3R`，2026-09-20 实测踩过这个测量伪影）；同一轮里几个值互相印证才作数 —— 被 `Fix` 的件 `0T+0R`、`Fit` 等半径孔面 `1T+1R`、`Concentric` 两孔口圆边 `0T+1R`、未参与约束的件 `3T+3R`。位置验证以 `GetPosition()` 为准；运动连接场景下它与 `3T+3R` 的差别是区分真假转动副的决定性证据（§A.5）。
- `RemoveComponent` **不删** positioner 里残留的持久约束：反复建约束会累积成几十条，GUI 冷开解算时零件散乱，而批处理不解约束、`GetPosition()` 与出图都正常（2026-08-26 实测 68 条历史 Fix）。清空配方：`for c in list(positioner.Constraints): c.Persistent = False` → `positioner.DeleteNonPersistentConstraints()` → 冷开验证 `list(positioner.Constraints) == []`。
- 面引用 = `comp.FindOccurrence(原型面)` 实例面；BC/约束目标用错原型面会报 "not in the same file as the Targetset"（FEA 同坑，见 fea.md §5）。

约束类型枚举（NX12 全表）：Touch/Concentric/Fix/Distance/Parallel/Perpendicular/Center12/Center22/Angle/Fit/Bond/OrientAngle/AlignLock/Hinge/Slider/Cylindrical/Ball/Screw/Gear/RackPinion/Cable/LinearPattern/CircularPattern/Linear2dPattern/RadiantPattern。
⚠ 其中 **`Hinge`/`Slider`/`Cylindrical`/`Ball`/`Screw`/`Gear`/`RackPinion`/`Cable`/`LinearPattern`/`CircularPattern`/`Linear2dPattern`/`RadiantPattern`/`CommonOffsetTransform` 的 `NXOpen.xml` 文档标注 `For internal use only`**，API 赋 `ConstraintType` 即抛 "not valid for this operation"（2026-09-15 实测）→ 运动副走 §A.5 的 `Fit`/`Bond` 方案。

⚠ **约束排障三条（2026-09-25 冷测 T2/T10 实测）**：
1. NX12 `Constraint.Type` 无 `Align` 成员（枚举不存在，别按名字猜）。
2. 装配约束求解后位置不动，先查基准件是否接地——无固定参考时解不唯一，求解器静默不更新；先 Fix 基准件再加 Touch/Concentric。
3. 显式坐标回退（本节上文的 Distance 偏置 setter 不可用路线）之后必须过一遍 §A.5 的 Bond 决策树：凡"间隙配合/同轴贴合"场景（如 r6 销配 r6.1 孔），优先用 Bond 落一条真实持久约束——交付 PERSISTENT_CONSTRAINTS=0 的装配在"装配约束真实有效"判据下是硬失分（T2 教训）。

### A.3 组件阵列 / 引用集 / 干涉

- 组件阵列：`assy.ComponentAssembly.CreateComponentPatternBuilder(NXOpen.Assemblies.ComponentPattern.Null)`，结构与特征阵列同源（PatternService + GeometricUtilities.PatternDefinition）。**2026-09-22 实测补充**：入参 `SelectObjectList`（`cps.Add(comp)` / `SetArray([...])`）可加单个或多个组件，`Commit` 后子件数按阵列数增加（2→3）；`PatternService` 的可用成员 = `PatternType` / `AlongPathDefinition` / `CircularDefinition` / `RectangularDefinition` / `HelixDefinition` / `MirrorDefinition` / `PolygonDefinition` / `ReferenceDefinition` / `SpiralDefinition` / `GeneralDefinition` / `PatternFill` + `CreateClockingBuilder` / `CreatePatternInstanceEditBuilder`，用法与特征阵列（modeling.md §3.1）同构。
- 引用集：`ca.ReplaceReferenceSet(comp, "Entire Part" / "MODEL" / "Empty")`；`comp.ReferenceSet` 可读回（实测：新建组件默认 `MODEL`）。
  - 语义（2026-09-19 补，专业惯例）：**MODEL** = 仅实体（装配/出图默认，轻）；**Entire Part** = 实体 + 草图曲线 + 基准（重）；**Empty** = 整件空载（占位/大装配减负）。装配脚本给标准件、大件统一设 MODEL，可避免草图曲线进装配与图纸投影。
  - ⚠ 本机实测反例（§B.1）：组件引用集为 MODEL 时，零件内与实体同层的草图曲线**仍会投影进每个视图**且无 API 单独屏蔽；引用集不是万能滤镜，建视图前 Blank 源头才是正解（§B.1）。
- **干涉检查别找 `ClearanceSets`**：`ca.ClearanceSets` 只有读/删方法（`CountClearanceSets` / `DeleteAllAnalysisData` / `FindObject`），`ca.AssembliesUtils` 只有 `NewWaveQuery`，没有创建入口（AttributeError）。两条几何路线（2026-09-23 实测通过，已入用例 29）：
  - **布尔交集 = 干涉体积**（最省，可量化）：第二个体当工具体，`tool.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Intersect, body_a)` → `CommitFeature()`。实测两个 10 mm 立方体搭接 5 mm：提交后只剩**一个**体，体积 **500.000 mm³**（解析 5×10×10，容差 1e-3）；分离或面贴面的一对被明确拒绝（`Tool body completely outside target body.`），拒绝本身就是"无体积干涉"的干净判据，不留空壳体。
  - **内建检查 `SimpleInterference` = 独立的判定来源**：`si = part.AnalysisManager.CreateSimpleInterferenceObject()`；`si.FirstBody` / `si.SecondBody` 是 `SelectObject`（属性不可写，写它的 `.Value`）；`si.PerformCheck()` 相交返回 `InterferenceExists`（`value=2`）+ `GetInterferenceResults()` 给 2 个 `Face`，分离返回 `NoInterference`（`value=0`）+ 空列表；比完 `si.Reset()` / `si.Destroy()`。别把返回的枚举成员当字符串比，`res.value` 是 int。
  - 两条路线互相独立（一条走布尔几何，一条走分析管理器），同一对体上结论一致；装配干涉判据建议两条都跑，互相印证。
- **组件质量属性（实测可用）**：按实例体取，才能拿到装配坐标系下的值——
  ```python
  proto = [b for b in comp.Prototype.Bodies][0]   # ⚠ Prototype.Bodies 是 BodyCollection，
                                                  #    不能下标取值（'not subscriptable'）
  inst  = comp.FindOccurrence(proto)              # → 实例体
  mp = wp.MeasureManager.NewMassProperties(units, [0.99], [inst])
  # 实测：两块 60×50×20 与 20×20×10，SUM V=64000.000、A=17000.000、
  #       质心 C=(48.438,29.687,6.562) 与分部质心/体积自洽
  ```
- 保存装配后**必须断言落盘**（实测 117 KB）：`wp.Save(SaveComponents.TrueValue, CloseAfterSave.FalseValue)` + `os.path.getsize(...)>0`（SKILL.md §3）。

⚠ **干涉检查两条语义（2026-09-25 冷测 T2/T10 实测）**：
1. 组件体惰性加载——重开装配后 `component.Prototype` 下的实例体不自动进入上下文，干涉检查/约束读回前先 `session.Parts.Open(子件.FullPath)` 预载全部子件，否则 SimpleInterference 空跑（T2 实证 inst_bodies=0）。
2. `SimpleInterference` 对**重合面**（零间隙配合，如 Ø20 轴配 Ø20 孔）报 `InterferenceExists`；判定"材料重叠"须走布尔交集路线（T10 实证：零间隙报 2 对"干涉"面，布尔交集拒绝求解 "Tool body completely outside target" = 零体积重叠）。零间隙场景的结论表述必须写明这层语义。
3. **同一会话内重开装配**（先建后验的用例/验证脚本）：已加载 part 直接 `Parts.Open` 报 "File already exists"，重开前先 `ufs.Part.CloseAll()`（无参；.NET `session.Parts.CloseAll` 在 NX12 Python 包装里参数枚举校验报错，2026-09-25 用例 35 实测）。重开后实例体读走 `Prototype.Bodies + FindOccurrence`（`asm.Bodies` 批处理下恒为 0），`GetPosition()` 返回 `(Point3d, Matrix3x3)` 位姿对，取 `[0]` 为原点。
4. 间隙配合的最小间隙定量复测走 `ufs.Modeling.AskMinimumDist2`（`ufs.Modl` 下无此成员，与包盒走 `ModlGeneral` 同款"Modl≠Modeling"坑；2026-09-25 冷测 T2-R2 实测 0.100000，与 r6.1 孔/r6.0 销的设计间隙吻合）。

### A.4 装配方法论（社区共识 + 经典夹具原理，非 API；2026-09-19 扩写）

- **3-2-1 定位规则**：一件刚体 6 个自由度，逐个消灭：主基准面贴合（消 3）+ 第二基准孔/销对齐或侧基准面（消 2）+ 止推面定程（消 1）；**每个自由度恰好被一个约束消灭**，约束数恰好等于剩余自由度数，不再多给。
- **冗余约束三形态**（过约束 = 求解冲突与位姿漂移之源）：① 同一自由度被重复限制（贴合后又补等距 Distance）；② 两个约束互相对抗（各拉半程）；③ 重复定向。GUI 会报冗余，**批处理 `Solve()` 返回 None 就通过、不报冗余**，§A.2 的"68 条历史 Fix 约束累积"即典型：组件自由度已 0，后续约束全是冗余，只是 GUI 冷开解算时才发作。
- **约束优先挂基准（面/轴）而非易变特征边**；圆角边、阵列结果面、布尔易变面禁止做约束目标（同 modeling.md §1.8 易变引用清单）。
- **重复件用组件阵列而非逐个 Add**；**装配树按子装配分组命名**（按功能模块分层，不给装配根塞几十个平铺组件）；组件改名取 `DisplayName`（`Name` 是内部名，重加后恒 "MODEL"，§A.1）。
- **主模型制**（2026-09-19 补，专业惯例）：图纸/分析文件**不拥有几何、只引用**模型件；出图人改不了模型、改模型自动更新图纸。本技能 §B 的批处理出图是"直接在部件上建 sheet"的单文件轻量路线（本机实测可用），单人交付够用；多图多件/多人协同交付时应回归主模型制（单独 drawing prt 引用组件）。
- **上下文编辑（WAVE 链接）慎用**：跨部件关联把上游改动扩散到下游；批处理场景显式声明哪条链接是设计意图、哪条是临时手段，不留隐式依赖。

### A.5 运动连接：把定位装配做成可拖动机构（2026-09-15 实测，回归 `scripts/tests/16_motion_constraints.py`）

需求背景：0 约束的**定位装配**在 NX 里拖不动（没有任何运动副）。要在装配定位约束层（**不是** Motion 模块）重建转动副，配方如下。全部结论源于四连杆机构的装配实测改造。

**唯一可用的转动副基元 = `Fit` 作用在两个圆柱孔面上**：

```python
con = pos.CreateConstraint(True)
con.ConstraintType = NXOpen.Positioning.Constraint.Type.Fit
con.CreateConstraintReference(comp_a, comp_a.FindOccurrence(hole_face_a), False, False, False)
con.CreateConstraintReference(comp_b, comp_b.FindOccurrence(hole_face_b), False, False, False)
```
- **两圆柱必须半径相等**，否则 `InternallyInconsistent`（r=3 立轴配 r=5 孔即此错）→ 配合件做成与孔同半径。
- 单个 Fit 给出 **`1T+1R`**（沿轴滑 + 绕轴转）。要得到纯转动 `0T+1R`，需另加约束去掉轴向滑动。机构装配实测：带 `Touch` 锁平面的曲柄为 `0T+1R`，其余摇杆为 `1T+1R`。

**附属件（销轴/套筒等）跟动 = `Bond`**：
```python
c = pos.CreateConstraint(True)
c.ConstraintType = NXOpen.Positioning.Constraint.Type.Bond
c.CreateConstraintReference(comp_pin, comp_pin, False, False, False)    # 成员 1
c.CreateConstraintReference(comp_host, comp_host, False, False, False)  # 成员 2
```
- **每个附属件单独一组、两成员**。⚠ **绝不可**把 N 个销轴 + M 个宿主放进同一个 Bond——`Bond` 语义是"多个可动对象构成刚性组"，那样等于整机刚性、机构完全不能动。
- 销轴实为间隙配合（r=4.9 配 r=5.0 孔）时 `Fit` 用不了（等半径要求），`Bond` 是几何关系补丁：装配演示够用，做间隙动力学须另建。

**拖动配方**（API 等价于 GUI 拖动）：
```python
net = pos.EstablishNetwork()
for c in cons:
    net.AddConstraint(c)
net.NonMovingGroupGrounded = False          # ⚠ True(默认) 时实测拖不动
net.BeginDrag()
net.SetMovingGroup([by["曲柄"]])            # ⚠ 移动组只含一件时，组外对象被当作接地
net.DragByTransform(NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(5.0))
net.Solve(); net.ApplyToModel(); net.EndDrag(); pos.ClearNetwork()
```
- **拖动语义与直觉相反**：`DragByTranslation` 是"按住被拖件"。GUI 拖连杆得到的是**转动**，API 等价写法是绕该件**自身原点**转 —— 要求被拖件的**组件原点正好落在铰轴上**（"绕自身原点转" == "绕该铰轴转"）。
- **移动组语义实测**：`SetMovingGroup([单件])` 且组外接地时，该件实测转 **+0.000°（完全不动）**；移动组含**全部活动件**时正好转 **+5.000°**。GUI 一般自动推断移动组；**任意一根活动杆都能驱动整机**（机构装配实测抓 5 根杆分别得 +5.000/+34.119/+7.731/−2.867/+7.177°，五次都 5/5 联动、铰轴间隙全 0）。
- GUI 操作路径：`UGII\menus\ug_main.men` 的菜单 `UG_ASSY_COMPONENT_POSITION` → `UG_NXPOS_MOVE_COMPONENT`，即 **装配 → 组件位置 → 移动组件**，类型选「动态」。运动平面平行 XY 时**切俯视图**拖最直观。

**坑位对照（遇到 → 怎么做）** —— 回归检查 `scripts/tests/17_motion_deadends.py`（2026-09-20 由预期失败探针改为正式检查；断言下面这些实测值，行为一变即 FAIL）：

| 遇到 | 怎么做 |
| --- | --- |
| 用 `Hinge` / `Cylindrical` / `Ball` / `Screw` / `Gear` / `RackPinion` / `Cable` 当约束类型，抛 `The constraint type is not valid for this operation.` | 这些枚举在 `NXOpen.xml` 里全标注 `For internal use only`，**枚举里有值不等于能调用**（7/7 复测一致）；运动副走本节的 `Fit` + `Bond` |
| `Concentric` 挂圆柱面，状态 `CannotSolve` | 面被解析成 `Line` / `Cylinder`；改挂孔口圆边 |
| 用 `Concentric` 圆边，想知道它到底约束住了什么 | 只看 `Solved` 与 DOF 读数判断不了；拖动复验才作数（实测它是单约束纯转动副：位移 25.000 mm 落到轴上、DOF `0T+1R`、绕轴转 12° 自由、沿轴平移 8 mm 被拒），见下面两条路线对照 |
| `Fit` 两个不等半径的孔面，报 `InternallyInconsistent` | `Fit` 必须等半径 |
| `AlignLock` 看着正合语义（共轴且不绕轴转）却建不出来 | `FindOccurrence(圆柱面)` 返回 `None`，`CreateConstraintReference` 报 `No overload matches these arguments.`；改走 `Concentric` 圆边或 `Fit` |

**两条转动副路线（2026-09-20 起，均为拖动复验过的事实）**：

| 路线 | 约束 | DOF | 绕轴转 | 沿轴滑 | 半径要求 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `Concentric` 两个**孔口圆边** | 1 条 | `0T+1R` | 自由（12° 实测） | **被拒**（8 mm 实测 0 位移） | **无**（Ø10 配 Ø20 实测可解） | 检查 `tests/17` |
| `Fit` 两个**圆柱孔面** | 1 条（要纯转还得再加约束去掉轴向滑动） | `1T+1R` | 自由（12° 实测） | 允许（8 mm 实测移动 8 mm） | **必须等半径** | 检查 `tests/16`、实际装配在用的那条 |

取圆边口径时，边要取**孔口那一圈整圆**（`p1 == p2 == 圆心`），用 `hole_top_edge()` 那种"两顶点重合 + 取近顶面"的筛法；本机实测同一通孔有上下两条等半径圆边，取错面会让轴对齐到另一端。⚠ 圆边路线目前只在最小几何上做过拖动复验，**真实多杆机构尚未复验**，实际交付仍走已长期验证的 `Fit`+`Bond`。

**验证方法学（关键，否则会假通过）**：
1. **故意把件移开再解算**，看是否弹回同轴 —— 静态位姿本就重合时，"解算无错 + 间隙 0"**证明不了**任何事（回归 16 用 `GAP_BEFORE_SOLVE=36.0555 → GAP_AFTER_SOLVE=0.0000` 做 falsify 基线）。
2. **拖动后重测铰轴间隙**，不是只测拖动前。
3. **"静态量相等"没有鉴别力**：0 约束原件与正品在静态下铰轴间隙都是 0，必须靠"拖动后机构是否真的动了"区分（0 约束件拖动后转角 `+0.000°`）。
4. 有条件时用**独立运动学**（纯 Python 由设计杆长/铰点预测位置）与 NX 实测对照，可发现解错/杆长被拉伸/解到另一分支。
5. **验证脚本不要保存**：拖动会改位姿，保存就毁了设计姿态。
6. **冷启动复验**（2026-09-19 补，来自 nx-assembly-verification-must-read-file 教训）：保存后重新 `Parts.Open` 再测一遍；内存态与磁盘态可能不一致，§A.2 残留约束正是 GUI 冷开解算才暴露的。
7. **兜底证据**（同日补）：用 NX 自己导出的几何做第三方对照，`DexManager.CreateStlCreator` + occurrence 实体导 STL，独立解析复算包围盒/相对位置，作为"NX 眼里长什么样"的证据（SKILL.md §3 坑位 6 同款路线）。

⚠ 不要假设"被抓住的杆自身必转指定角度"：长连杆对曲柄角灵敏度极低（553 mm 连接杆在曲柄转 15° 时自身只转 0.09°），该假设会误判。应改为对**每个位姿**做运动学自洽核对。

**保存陷阱：`ufs.Part.Save()` 保存的是「显示部件」，不是你以为的那个件**（2026-09-15 实测）：
- 装配脚本常需要"切到零件读局部孔面"（见 §A.2；作为装配组件载入的零件 `Bodies` 为空）——这个 `SetDisplayPart(零件)` **读完后必须显式切回装配件**，否则结尾的保存静默写回零件，装配件根本不落盘（回归 16 实测：三个零件都在，`m16_asm.prt` 缺失，且不报任何错）。
- 稳妥写法是**显式对目标部件保存**（不依赖"当前显示部件是谁"）：
  ```python
  asm.Save(NXOpen.BasePart.SaveComponents.TrueValue,
           NXOpen.BasePart.CloseAfterSave.FalseValue)
  assert os.path.exists(path) and os.path.getsize(path) > 0   # 落盘才算数
  ```
- 与验证方法学第 5 条不冲突：**真实交付件的拖动验证脚本绝不保存**（拖动改位姿）；只有像回归 16 这种自建的一次性试件才保存，且必须断言落盘。

### A.6 装配交付自检清单（逐项过，2026-09-19 补，对齐 modeling §1.10 体例）

- [ ] 每个组件自由度恰好清零、无冗余约束：残留约束审计 `list(positioner.Constraints)` 数量与设计意图一致（清理配方见 §A.2），不再多给一个"保险约束"
- [ ] 约束目标全部是实例面（`FindOccurrence`）且挂在稳定几何（基准/主平面），无易变边（§A.4）
- [ ] 组件位姿验证读**文件真实几何**：`GetPosition()`、`ufs.Modeling.AskFaceData()` 孔轴间距等独立几何量，不与自己刚写入的值比对（§A.5 方法学 1）
- [ ] 冷启动复验：保存后重新 `Parts.Open` 再测，内存内自测不算数（§A.5 方法学 6）
- [ ] "被测现象必须发生"断言在位：验证脚本对 0 约束原件必须 FAIL（如"拖动后转角 <1° 即 FAIL"），否则改坏前后都 PASS（§A.5 方法学 3）
- [ ] 附属件（销轴/套筒）Bond 每件一组、两成员，绝无 N 件混一组（§A.5 Bond 语义）
- [ ] 保存显式指名目标部件并断言落盘；`ufs.Part.Save()` 保存的是**显示部件**，`SetDisplayPart` 切出去读面后必须切回（§A.5 保存陷阱）
- [ ] 引用集统一（标准件/大件 MODEL，§A.3 语义）；装配树按子装配分组；组件 `DisplayName` 可读（§A.4）
- [ ] 可拖动机构：拖动后重测铰轴间隙（不只测拖动前）；有条件时独立运动学预测逐位姿对照（§A.5 方法学 2/4）

## B. 工程图（Drafting）

### B.1 图纸 + 三视图（实测可用）

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

**`ViewType` 必须用 `View.Base`，绝不能用 `View.Drawing`**（2026-09-17 定界）。`View.Drawing`
建的是**空的 2D 视图**：`AskVisibleObjects()` 恒 0、`IsOutOfDate` 恒 False，随后
PrintPDFBuilder 只出 **917 字节空白页**。此前"批处理无图形内核 → 制图不可能"的整个结论，
根因就是这一个枚举写错；改用 `View.Base` 后 `run_journal.exe` 无头批处理 7/7 出真图，
**不需要 GUI、不需要解锁会话、不需要交互回放**。

> 2026-09-20 补充：本结论当时**只写在文档里，没进回归测试**。回归用例 06 反而用了
> `View.Drawing` 且只断言视图**个数**，于是在三视图全空的情况下长期打 `TEST06_DONE`——
> 典型的"文档对、检查误判通过"。现已双重加固：06 改用 `View.Base` 并断言每个视图
> `AskVisibleObjects() ≥ 8`（实测 13/13/15），用例 20 再把两种枚举的差别做成**成对断言**
> （`View.Base` 各 ≥10、`View.Drawing` 各必须恰好 0），NX 行为若变会立刻变成 FAIL。
> 另注：`AskVisibleObjects()` 只对**当前图纸**上的视图有效，视图所在图纸不是当前图时抛
> `The view is not displayed`——读内容前先 `sheet.Open()`。反向验证见
> `scripts/tests/README.md` 的"20 / 06 的反向验证记录"。

其它已验证的落位/比例细节：

| 项 | 实测结论 |
| --- | --- |
| `svb.Coordinate` / `FirstCorner` / `SecondCorner` / `HiddenObjects.Objects` | 全**只读**，`PlacementType` 也只有 Center/Corner 两个成员——生成器不接受位置，只能提交后自己摆 |
| `svb.ViewStyle.ViewStyleGeneral.Reference` | 默认已是 False，与游离曲线无关（别再试） |
| `ufs.Draw.SetViewScale(view_tag, s)` | **相对/乘性**，新建视图基准为 1.0，故传目标值一次即绝对比例；`ufs.Draw.AskViewScale(tag)` → `(0, 实际比例)`；`DraftingView.Scale` 读回的是 `实际×0.83436`，**不可用它反推缩放系数** |
| `v.SetDrawingReferencePoint(Point3d(x,y,0))` | 钉住的是**建视图时 NX 选定的锚点模型点**，不是必然的内容中心：Set 移动的是 plot 内容（2026-09-24 逐份 PDF 数值验证），但内容中心相对锚点有**视图相关常数偏差**（2026-09-23 用例 06 实测每视图 4–5mm）——关键落位走 drafting-annotation.md 的**内容包盒闭环**（`gb_drawing.pin_view`）或把常数预先减进常量；**同一图纸上后续视图越界抛 `Cannot move view off of the drawing` 会回滚之前已成功的移动**（2026-09-24 用例 33 实测），布局须保证任何视图不出图幅 |
| `v.MoveView(p)` / `v.SetOrigin(p)` / 成员视图 `v.Fit()` | `Fit()` 报 "Member view may not be fit"；落位统一走 `SetDrawingReferencePoint` |
| `sheet.SheetDraftingViews.CreateBaseView(mv, Point3d, scale, inheritClip)` | 存在但**忽略**传入的比例与位置，会自选原点（同 `svb.Coordinate` 无效） |
| `part.Datums` | 装配/零件的 DatumCsys 特征带 3 基准面 + 3 基准轴；**必须在建视图之前** `Blank()`，建视图后再 Blank 已投影的副本无效 |
| `Component.RemoveComponent` | 内存中移除后**当次会话的视图仍投影旧几何**；要真消失须 `SaveAs` 后重开——但重开后组件 Body 不再载入（视图 vis=0），故**该路线不可用于出图** |
| `DraftingCurve.Blank()` | 无异常但**不生效**（可见对象计数不变，`IsReference` 恒 False），游离曲线只能靠"建视图前 Blank 源头" |
| `ufs.Sf.BodyAskBoundingBox(tag)` | 传体、边、面、甚至 DraftingCurve 的 tag 都不报错，但曲线返回**退化点**——用曲线量包围盒会得到 0 尺寸，别拿它当尺寸来源 |

`Blank()` 对拆件零件的构造曲线不生效：每个零件在 1 号层同时放着 1 个实体和 8 条草图曲线，
组件引用集为 `MODEL`，这些曲线会一并投影进每个视图（如装配右视图 8 体 + 40 条曲线）。
实测无 API 可单独屏蔽（组件草图几何未暴露），但它们都落在图纸内、不影响版式，接受即可。

⚠ **视图排布与剖视语义（2026-09-25 冷测 T1/T7 实测）**：
1. NX `StandardViewsBuilder.FrontTopRight` 在 FirstAngle 声明下原生把 Right 视图排在主视图**右侧**（与 GB 第一角"右视图置主视图左方"相左，33 号基准同款）；需要严格第一角排布时手动重排或改投影视图。
2. 全剖主视图 = 剖切线画在 ⊥ 剖切面的视图（俯视图）上且过轴线；`SectionViewBuilder` 的剖切腿平面 = 腿线段沿父视图视线方向拉伸，**恒 ⊥ 父视图图面**——想要 ∥ 图面的过轴纵剖，剖切线必须挂在别的视图上。
3. 关联尺寸前确认目标边在所选视图投影非退化：轴向边挂到横剖圆环视图会渲染成 "0" 值尺寸；交付前 PDF 文本层逐值复核是固定步骤。
4. 局部放大的源视图必须包含目标细节（放大对象选错会把无关弧当 R3 标注）；detail 视图须在图面标注放大比例（如 2:1）。

### B.2 批处理标注（2026-09-20 定稿：完全可用，且**不需要** `sheet.Open()`）

> 本节只讲"能不能标"（API 可用性与前置条件）。**标注质量层（道位布局、字高/箭头风格、
> 注释排版、表格、中心线体系、反模式清单）见 `references/drafting-annotation.md`**
> （2026-09-19 实测定稿），出正式图纸时两份都要读。

**两条要点**：

- **不用调 `sheet.Open()`**：部件自带的当前图纸、本会话新建且从未激活的图纸这两种配置下，UF 尺寸、
  中心标记、中心线、注释、引线标签、表格、PDF 导出**全部成功**（`scripts/tests/19_drafting_annotation.py`
  把该调用删掉后仍然全部通过）。保留它无副作用，但它**不是必要条件**。
- **`CenterMarkBuilder` 一次提交只能带一个 location**：n=1、n=2 通过，n=3、n=4 报 1175305，n=8 报 1175307；
  同一条边重复放两次也通过，故与孔位、视图、图纸是否打开均无关。配方：一个标记一个 builder
  （`CreateCenterMarkBuilder` → `Locations.Add` 一次 → `Commit` → `Destroy`），4 个孔位实测 4/4 成功，
  回归见 `scripts/tests/07_center_marks.py`（每次运行都会复测"n=3 被拒"，行为若变日志里会显示
  `CENTERMARK_MULTI=accepted`）。

下列路线全部在 `run_journal.exe` 无头批处理实测通过（回归：七张图纸自动标注，
UF 尺寸关联值经 PDF 文本逐项核验；`tests/19` 又把该链路压成可复跑的令牌校验）：

**尺寸（UF DRF 路线，唯一可用的尺寸路线）**：

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

⚠ 字段名是 PascalCase（`ObjectAssocType`，不是 snake_case）；枚举必须传枚举成员
（`getattr(NXOpen.UF.Drf.AssocType, "ARC_CENTER")`），传 int 报类型错；
⚠ `NXOpen.UF.Drf` 是属性容器不可 `import NXOpen.UF.Drf`，`import NXOpen.UF` 后用属性。

**模型点 → 图纸点：`ufs.View.MapModelToDrawing(view_tag, [x, y, z])`（2026-09-20 实测）**：

```python
pt = ufs.View.MapModelToDrawing(view.Tag, [35.0, -20.0, 9.0])   # 直接返回图纸坐标数组
```

实测与手工映射式 `sheet = ref + proj(p) − proj(中心)` **逐位一致**（俯视图差 0.000），
但只对**视图比例 1:1** 且已知投影关系时那条公式才成立；`MapModelToDrawing` 自带比例与
视图方向，是填 `AssocDwgPos` / 定位标注的首选。**本机验证**：`tests/19` 同时算两者并
逐位比对差值。

**其余标注（.NET 路线，无需 `sheet.Open()`）**：

```python
part.Annotations.Centerlines.CreateCenterMarkBuilder(NXOpen.Annotations.CenterMark.Null)
    # .Locations.Add(edge, view, Point3d) —— ⚠ 一个 builder 只放一个 location（见上）
part.Annotations.Centerlines.CreateCenterline2dBuilder(NXOpen.Annotations.Centerline2d.Null)
    # .Type = ...ByPoints; .Point1/.Point2.SetValue(edge, view, Point3d)
part.Annotations.CreateNote(lines, Point3d, NXOpen.AxisOrientation.Horizontal, None, None)
    # ⚠ origin 是文本块中心，多行整体居中
part.Curves.CreateLine(...)   # 图框/表格线，sheet 打开后即可
ufs.Drf.CreateIdSymbol(NXOpen.UF.Drf.IdSymbolType.SYM_CIRCLE, "1", "", [x,y,0.0],
    NXOpen.UF.Drf.LeaderMode.WITH_LEADER,
    NXOpen.UF.Drf.LeaderAttachType.LEADER_ATTACH_OBJECT, obj, [x,y,0.0])  # 球标
```

**尺寸别走 .NET**：`part.Dimensions.Create*Dimension(DimensionData,…)` 在无头批处理下一律
`Internal error: memory access violation`，.NET dimension builder 报 `Unable to infer a dimension type`。
尺寸一律走上面的 UF DRF 路线。

**装配图纸的边解析**：组件体是惰性加载，打开装配后 `Prototype.Bodies` 为空 →
先逐个只读 `s.Parts.Open(子件)` 预载，再 `comp.FindOccurrence(body).GetFaces()`
取实例边（装配坐标），按顶点坐标匹配（TOL 0.02）定位关联边。圆边两顶点重合
（`GetVertices` 相等）即为整圆，其顶点=圆上参考点（不是圆心；孔心=上下两 rim
的中点）。

**视图坐标映射**（标注文本定位用）：`sheet = ref + s*(proj(p) - proj(bbox中心))`，
proj：Front=(x,z)、Right=(y,z)、Top=(x,y)；孔轴线向 z 的回转面在 Front/Right
呈矩形轮廓（Ø 尺寸标在其上属惯例），真实形状/平面角度在 Top。**角度尺寸须在
两线延长线交点落图内的视图上**，交点在图外时改用注记文本（数值由模型坐标反算）。

完整可跑样例（在项目工作区，不随技能分发）：`67_annotate.py` 执行器 + `68_cfg0*.py` 配置
（配置生成器），配置 JSON 含 `expect` 供 PDF 文本层自动核对。

### B.3 出图导出（2026-09-17 修正：批处理完全可用，走 `View.Base`）

**批处理出图要用 `View.Base`**（2026-09-17 修正）：误用 `View.Drawing` 得到的是空 2D 视图
（vis 恒 0、PDF 恒 917B）。改用 `View.Base` 后 `run_journal.exe` 无头批处理**直接产出真图**：
7 个零件/装配各出 A3 三视图 PDF（1.4–7.8 KB，数百条图元）+ 同名 .prt，全程无需 GUI、无需解锁。
下表"批处理实测结果"中的空产出**全部归因于视图类型，不是导出器本身**；以 `View.Base` 重测，
PrintPDFBuilder 一次 Commit 即落盘正常 PDF：

| 导出路线 | 以 View.Base 重测（2026-09-17） |
| --- | --- |
| `PrintPDFBuilder`（`part.PlotManager.CreatePrintPdfbuilder()`，在 **part** 上不在 session） | **正常出图**：`Filename` 小写 n、`Size=FullScale`、`Units=Metric`、`Scale=1.0`、`Colors=BlackOnWhite`，每 sheet 一个 PDF |
| `CGMBuilder` / `ufs.Plot.SaveCgm` / `DxfdwgCreator` / `Nxto2dCreator` | 未再复测；既然 PDF 路线已够用，无需回访 |

PrintPDFBuilder 属性名陷阱（NX12）：`Filename`（**小写 n**，`FileName` 不存在）；尺寸属性是 **`Size`**（`SizeOption` 只读）；`Action` 是 Teamcenter 语义（Native/New/Append/Overwrite），本地导出无需纠结；枚举 `Color` 成员 = BlackOnWhite/AsDisplayed/ColorsByWidth/CustomPalette/LegacyColors/PartColors。`PlotSourceBuilder.SetSheets` 的所有 sheet 必须属于 display part。

**交付形态**：直接给 `run_journal.exe` 批处理一键（`.bat` 必须 **GBK + CRLF**，否则 cmd 乱码；
NX 内嵌 Python 是 3.6，其 UTF-8 输出与 GBK 控制台混排会乱码 → 把 journal 输出重定向进日志，
只让 bat 自己的 GBK 文案上屏）。图纸为 A3 三视图（第一角），**不含尺寸与中心线**（见 B.2）。

### B.4 投影视图 / 局部放大视图 / 剖视图（2026-09-20、2026-09-22、2026-09-23 实测，回归 `scripts/tests/20_drafting_views.py`、`21_drafting_section.py`、`31_drafting_sections.py`）

`StandardViewsBuilder` 只管三视图：投影视图与局部放大视图走 **UF 路线**，剖视图走
**builder 路线**（2026-09-22 打通，见下小节；此前"builder 拿不到父视图"的结论已修正）。

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

实测值（A4，120×80×12 带 Ø20/Ø8 通孔的板，父视图钉到 1:1，基准已消隐，2026-09-23 重测）：

| 项 | 实测 |
| --- | --- |
| 投影视图 | 建出 `ORTHO@n`；**建完必须 `ufs.Draw.UpdateOneView(sheet.Tag, tag)` 再问**——新建投影视图不更新时 `AskVisibleObjects()` 返回 **0**（几何其实已在出图），更新后 = **7**（Below / Right 各一，均 7） |
| 局部放大视图 | 建出 `DETAIL@n`，更新后 `AskVisibleObjects()` = **3**（锚到双孔区域的真实内容数；旧版锚在前视图薄边上 11 个对象只是两条平行边，无信息量） |
| 局部放大视图的比例 | UF `AskViewScale(detail)` = **2.0 × UF 父比例（乘性）**；.NET 属性 `view.Scale` 报的是自缩放链（2.36 = 2.0 × 1.18），**核对比例用 UF 值**，它是实际出图的比例 |
| 局部放大边界圆 | NX 画的虚线边界圆半径 ≈ **选框半对角的 0.83 倍**（两次实测缩进 5–6 mm）：选框要留出余量，否则圆会裁掉目标特征的边 |
| 放置点越界 | 放 y=250（A4 高 210）抛 `Input is not a valid parameter`，**不创建视图**——可当反向对照 |
| 出图字节数 | 同页空白图 **917** B / 含三视图+2 投影+1 放大 **约 33 000** B；空白页字节数是现成的"内容判据" |
| 删除视图 | `ufs.Obj.DeleteObject(tag)`（**没有** `DeleteObj`；`UF_DRAW_delete_view` 不存在） |

UF 包装类的取用方式（三个都踩过）：

- 枚举挂在**会话对象**上，不在 `NXOpen.UF` 模块上：`NXOpen.UF.UFDraw` 不可 import
  （`module 'NXOpen.UF' has no attribute 'UFDraw'`），要写 `ufs.Draw.ProjDir`；成员名是
  `PROJECT_INFER / PROJECT_ABOVE / PROJECT_RIGHT / PROJECT_BELOW / PROJECT_LEFT`（**没有**
  `Below` 这种短名），`ufs.Draw.SxsegType` 是 `SXSEG_CUT / SXSEG_BEND / SXSEG_ARROW`。
  传裸 int 会被拒：`Expecting NXOpen.UF.Draw.ProjDir type, found int`。
- nxopen MCP 索引**不全**：`ufs.Draw` 上还有 `CreateSteppedSxview` / `CreateHalfSxview` /
  `CreateRevolvedSxview` / `CreateUnfoldedSxview` / `CreateSxviewFromDmv`，索引里都没有。
  查 UF 能力以 `dir(ufs.Draw)` + `%NX_HOME%\UGOPEN\uf_draw.h`（含精确原型与注释）为准。
- `part.DraftingViews` **没有 `__len__`**：`len(part.DraftingViews)` 抛 TypeError，用列表推导；
  `sheet.GetDraftingViews()` 可 `list()`。

#### 剖视图（2026-09-22 打通，回归 `scripts/tests/21_drafting_section.py`）

```python
svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
svb.ParentView.View.Value = front            # 缺这一步下面必抛 Invalid parent view
loc = svb.SectionLineSegments.SegmentLocation
loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(30.0, 40.0, 6.0)))   # 模型坐标
loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(90.0, 40.0, 6.0)))
svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = NXOpen.Point3d(ref.X, ref.Y - 70.0, 0.0)
svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(
    NXOpen.Point3d(ref.X, ref.Y - 70.0, 0.0))
view = svb.Commit(); svb.Destroy()           # -> NXOpen.Drawings.SectionView
```

四个关键点：

1. 空引用写 `NXOpen.Drawings.SectionView.Null`，不能写 `None`。
2. **父视图只能从 `ParentView.View.Value` 进**：`ParentViewBuilder.View` 属性本身只读
   （`attribute 'View' … is not writable`），但它返回的是 `NXOpen.SelectObject`，该对象的
   `Value` 文档写明 "Returns or sets the object being selected"，赋值可用、读回即父视图。
   删掉这一行（改坏验证实测）→ 提交出的视图 `Value` 恒为 None，首个 `AddCutSegment` 抛
   `Invalid parent view for section line.`。`ViewPlacementBuilder.Placement` 是同一套路。
3. **两个切点用模型坐标**，且要落在父视图看得见的实体内。改用图纸坐标的变异实测：能 commit，
   但 `AskSxsolidsOfSxview` 落空（视图没剖到任何实体）。
4. 放置点与 `SectionLineOnlyPlacementOrigin` 用**图纸坐标**（父视图参考点下移 70 mm）。

实测值（A4，120×80×12 板 + Ø20 通孔，父视图自缩放 1.18）：

| 判据 | 实测 |
| --- | --- |
| `ufs.Draw.IsSxview(view.Tag)` | **True**（普通投影视图为 False） |
| `ufs.Draw.AskSxlineOfSxview(tag)` | 非 0 剖切线标签（实测 36217） |
| `ufs.Draw.AskSxsolidsOfSxview(tag, ufs.Draw.SxlineLeg.SXLINE_LEG1)` | `n=1`，并给出被剖实体列表 |
| `view.AskVisibleObjects()` | **18**（同一毛坯无孔时 16） |
| 其中的 `Hatch` | **1**（剖面线；无孔时也是 1） |
| 其中的 `DraftingCurve` | **8**（无孔时 6，**只有这一项随孔变化**） |
| `view.IsOutOfDate` / `Scale` | False / **1.1800**（继承父视图自缩放） |
| 视图名 | `SX@4`（自动命名） |

三条判据分工要分清：`IsSxview` 证明"这是剖视图"，`AskSxsolidsOfSxview` 证明"剖到了实体"，
`Hatch` 证明"画了剖面线"。**`Hatch` 单独说明不了切到没切到孔**——实心块剖开同样打剖面线，
所以 21 号用例另外断言毛坯上存在一个圆柱面（`AskFaceData` 面类型 16），把"孔真的被切出来"
钉在几何上。

⚠ **剖视图显示的是"剖切面 + 面后可见几何"，不是只有切口**（2026-09-22 实测，写断言时最容易踩）：
一块板在两个不同 Y 上各开一个 Ø8 孔（y=20 与 y=60），把剖切面分别放在 y=20 和 y=60，
两次读数**完全一样**（`AskVisibleObjects()` 20、`DraftingCurve` 10、`Hatch` 1）。
所以"用曲线条数判断切面切到了哪个孔"是错的——曲线数只反映**模型里有什么**，
不反映**切面放在哪**。要证明切面位置，得读剖切线几何本身（或比较剖切面两侧的实体）。

#### 阶梯剖：已打通（2026-09-23 实测，旧"未打通"结论作废）

**配方**（已入用例 21 阶段 4/5）：剖切**类型**是 builder 属性，**阶梯靠 Z 形切点路径**形成：

```python
SVB = NXOpen.Drawings.SectionViewBuilder
svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
svb.ParentView.View.Value = state["top"]          # ⚠ 父视图必须选"切点所在投影面"的那个视图
svb.SectionViewType = SVB.SectionLineType.SimpleStepped   # ⚠ 属性名是 SectionViewType
loc = svb.SectionLineSegments.SegmentLocation
for x, y in ((20.0, 40.0), (80.0, 40.0), (80.0, 60.0), (110.0, 60.0)):   # 模型坐标，Z 形
    loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(x, y, 6.0)))
svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = NXOpen.Point3d(ref.X, ref.Y - 140.0, 0.0)
svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(NXOpen.Point3d(ref.X, ref.Y - 140.0, 0.0))
view = svb.Commit()
```

- 两个承重的坑：①**属性名是 `SectionViewType`**——`SectionViewBuilder.SectionLineType` 是**枚举类本身**（成员可取），但对实例赋 `svb.SectionLineType` 报 `attribute 'SectionLineType' is read-only`；②**切点必须落在父视图的投影平面内**：同样的 Z 形路径挂在前视图（Front，投影面 XZ）上，第 3 个点就报 `Invalid point for section line`，挂到顶视图（Top，投影面 XY）才通过。
- **"类型标签"不能用来指认阶梯剖**：`AskSxlineType` 对**普通两点剖切线也返回 `STEPPED_SXLINE`（value=2）**（实测两条线同为 2）。真正不同的是 `AskSteppedSxline` 第 6 个字段的**腿段数**：Z 形路径 **9**，直线两点 **5**，且第 7 个字段的 tag 列表长度与它一致 —— 用例 21 就是拿这个"腿段数更多"当判据的（`AskSteppedSxline` 对普通剖切线同样会答，不是阶梯专属）。
- `AskSimpleSxline` 对阶梯线报 `Section line is not correct type.`；`ufs.Draw.SxlineType` 全集 = `BREAKLINE / FOLDED_SXLINE / HALF_SXLINE / REVOLVED_SXLINE / SIMPLE_SXLINE / STEPPED_SXLINE / UNFOLDED_SXLINE`。
- `SectionViewType.PointToPoint`（两点路径）产出的是 **`FOLDED_SXLINE`（value=7）**，`AskFoldedSxline` 会答、`AskSteppedSxline` 拒绝 —— 别把 `PointToPoint` 当"普通剖"用。
- UF 侧的 `ufs.Draw.CreateSteppedSxview` 确实存在，docstring 指向 `UF_DRAW_create_stepped_sxview`，原型在 `uf_draw.h` 里是
  `(dwgTag, sxviewScale, stepDir, arrowDir, pviewTag, numSxsegs, steppedSxsegs, viewPlacementPt)`——
  `steppedSxsegs` 要 `UF_DRF_object` 数组，与下表里 `CreateSimpleSxview` 同一条鸡生蛋死路，**不必再走**（builder 已经够用）。
#### 半剖 / 旋转剖 / 展开剖：三种都在批处理里打通（2026-09-23 实测，回归用例 31）

入口与阶梯剖完全一样，差别只在 `SectionViewType` 与切点怎么给：

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

- **实测读数**（用例 31 每次重跑都会重打这些数）：半剖 → `AskSxlineType` 报 `HALF_SXLINE`（value=4）、`AskHalfSxline` 答 **8** 个字段（第 6 个是段数 3、第 7 个是 tag 列表长度 3；L 形三点路径与直线两点路径都是 8）、被剖实体 1、可见对象 18（`DraftingCurve` 8 + `Hatch` 1，直线路径则为 17 / 7）；旋转剖 → `REVOLVED_SXLINE`（value=3）、`AskRevolvedSxline` 答 **11** 个字段（第 8 个是腿段数 4，两条腿的 `SegmentLocation.Length` 分别读到 4 与 2）、一次剖到 2~3 个实体、`Hatch` 1、`IsOutOfDate` 均为 False。⚠ **这些元组长度不是固定常数**（实测半剖 8、两条腿的旋转剖 11；腿数或切点变化会改变长度），所以断言要取"长度 ≥ 已知最少"或直接取字段位置，别把某个具体长度当 API 契约。两者对其余 `Ask*Sxline` 一律报 `Section line is not correct type.`，所以**剖切线类型就是最省事的判据**。
- ⚠ **旋转剖不设旋转点必被拒**：`RotationPoint` 默认落在折点上，`AddCutSegment` 直接报 `NXException: Rotation and bend points cannot be coincident.`（用例 31 把它做成负向对照）。赋 `Point3d` 会报 `Expecting NXOpen.Point type, found NXOpen.Point3d`。
- ⚠ **`SegmentLocation` 的 `Length` 计的是段端点，不是交给它的点数**：旋转剖两条腿各 2 点读到 4、腿 2 单点读到 2；半剖的 L 形三点读到 3，而**直线两点路径也读到 3**（半剖线自己有转折点）。拿 `Length` 当"点数够了没"的判据会错。
- **展开剖就是 `ViewUnfolded` 开关**：`svb.ViewUnfolded = True` 能设能提交（读回 True，同时 `CreateFolded` 从默认 True 变 False），但**对象级读数与折叠态完全相同**（同一旋转剖：可见对象 4、`DraftingCurve` 3、`Hatch` 1，腿段数与方向向量也一致），唯一测得的差别是出图——折叠态与展开态导出的 A4 图纸 PDF 字节数不同。⚠ **这个字节数会随图纸上的视图名与视图条数浮动，大小顺序也不固定**（三组实测：18372/18414、18248/18077、18246/18077），所以判据只能取"开关读回 + 视图有效 + 两份出图不一样"，别把具体数值写进断言。
- **剖切线类型里没有"展开剖"入口**：`ufs.Draw.SxlineType` 有 `UNFOLDED_SXLINE`，但 .NET 侧 `SectionViewBuilder.SectionLineType`（`Half / PointAndAngle / PointToPoint / Revolved / SimpleStepped`）与 `Drawings.SectionLineBuilder.Types`（`Half / HalfPictorial / Oriented / Pictorial / PointAndAngle / PointToPoint / Revolved / SimpleOrStepped`）都没有展开剖成员，`AskUnfoldedSxline` 对这两种线都报 `Section line is not correct type.`。UF 的 `ufs.Draw.CreateUnfoldedSxview` 存在，但属下表里那条 `UF_DRF_object` 路线。

**坑位对照（遇到 → 怎么做）**：

| 遇到 | 怎么做 |
| --- | --- |
| 一条腿里交替塞 4 个点（两点 y=26、两点 y=54），只有 2 个被接受，另 2 个报 `Invalid point for section line`，视图仍是单腿剖 | 先设 `SectionViewType = SimpleStepped`，再把 Z 形 4 点整条挂在投影面匹配的父视图上（两处缺一不可） |
| 腿 1 走 `SegmentLocation`、腿 2 走 `SegmentLocationForSecondLeg`，腿 2 的 `AddCutSegment` 不报错也不生效（`loc2.Length` 读 0），视图反而变小 | 别分两条腿填点；阶梯剖的点全给在一条腿里 |
| 不设父视图直接 `AddCutSegment`，报 `Invalid parent view for section line.` | 先 `svb.ParentView.View.Value = <父视图>`（这条报错现为 21 号的负向对照断言） |
| 切点给图纸坐标，能 commit 但视图 out-of-date 且空，`AskSxsolidsOfSxview` 落空 | 切点必须给模型坐标，图纸坐标只用于放置点 |
| `SectionViewMode.StandAlone` | 报内存访问违例或 `Section line lost model associativity.`；用默认模式 |
| 在实例上设 `SectionViewBuilder.SectionLineType`，报 `attribute 'SectionLineType' is read-only` | 它是枚举类本身；要设的是 `SectionViewType`（见上"阶梯剖已打通"） |
| 用弃用的 `SectionLineBuilder` | `Validate()` 报 `Section line must have a cut segment.`、`Commit()` 报 `Invalid view.`、`Leg1.Append` 报 `No overload matches`、`CreateSectionLineSegmentBuilder()` 不收参数；一律改用 `SectionViewBuilder` |
| `ufs.Draw.AskXhatchOfSxsolid` 传视图标签，报 `Tag is not a section line segment.` | 它要的是剖切段标签，不是视图标签 |
| 想走 `ufs.Draw.CreateSimpleSxview` / `CreateSxviewFromDmv` | `cut_object` 要 `UF_DRF_object` 且 `assoc_dwg_pos` 必须落在图纸上，而官方唯一样例是用 `UF_DRAW_ask_sxline_sxseg` 从既有剖切线里取段再复制，`UF_DRAW_add_sxline_sxseg` 又要求先有剖切线标签 —— 鸡生蛋，不必再走；builder 路线已经够用 |

#### builder 只读属性一览（2026-09-22 修正）

| 位置 | 实测 |
| --- | --- |
| `None` 当空引用 | 被拒：`Expecting NXOpen.NXObject type, found NoneType`。要传 `NXOpen.Drawings.SectionView.Null` / `DetailView.Null`；`NXOpen.Tag.Null` 取不到（`module 'NXOpen' has no attribute 'Tag'`），C 侧空标签直接写 `0` |
| `ParentViewBuilder.View` | 属性只读，但返回的 `SelectObject.Value` **可写**（剖视图的关键，见上） |
| `ViewPlacementBuilder.Placement` | 同上，`.Value` 可写 |
| `DetailViewBuilder.Origin` / `Scale` | 属性只读，未找到容器通道 —— 局部放大视图仍走 UF `AddDetailView` |
| `DetailViewBuilder.BoundaryPoint1/2` | 要求 `NXOpen.Point` **对象**，传 `Point3d` 报 `Expecting NXOpen.Point type, found NXOpen.Point3d`；两个都不给则 `Validate`/`Commit` 报 `The points defining the boundary cannot be the same` |
| 空 `SectionLine` 直接 Commit | `Null tag not allowed` |

**通用判据**：builder 的输入属性报只读时，先看它返回的是不是 `SelectObject` / `ScCollector`
这类容器 —— 容器自身往往可写（`.Value`）；只有拿不到容器通道时才退回 UF。注意
`SelectView.SetValue(...)` 这条路走不通（`No overload matches these arguments`），
能用的是 `ParentView.View.Value`，两者别混。

`SectionViewBuilder.SectionLineSegments`（`SectionLineSegmentsBuilder`）**没有 Add 方法**，
段几何靠 `SegmentLocation.AddCutSegment()`；`SectionLine`（`SpecifySectionLineBuilder`）
只有只读的 `SectionLine` 属性，别往那儿找入口。

### B.5 无人值守 GUI 出图：已无必要（2026-09-17 修正）

原 B.4 整节（后被重编号为 B.5；startup 钩子三子路线证伪、锁屏下 UI 注入全灭、"锁屏会话不可达"）的**前提已消失**：
那批实验都是为了绕开"批处理出不了图"的假定。既然 `View.Base` 下批处理直接出图（B.1/B.3），
GUI 直启（`ugraf.exe -journal`）、startup 钩子、SendKeys/SetForegroundWindow 注入
**全部不再需要**，也无需再纠结锁屏与否。

保留其中两条当"别再投入"的排查经验：① startup 钩子期 NXOpen 恒报"未充分初始化"（自等死锁），
钩子内 spawn 的线程在钩子返回时被杀，钩子线程的 `SetTimer(NULL,…)` 永不触发（该线程不泵消息）；
② 锁屏（`LogonUI.exe` 在跑）下 `WScript.Shell.AppActivate` 无限挂起、`SetForegroundWindow` 返 False、
键击落入安全桌面。遇到"无人值守出图"需求，**先确认有没有踩 `View.Drawing` 这个坑**，再谈 GUI。
