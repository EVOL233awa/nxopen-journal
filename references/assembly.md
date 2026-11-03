# 装配域（NX 12 批处理）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。本文件 §A 装配：组件/配对约束/阵列/引用集/干涉/运动连接。工程图见 `drafting.md`，标注见 `drafting-annotation.md`。示例 `scripts/tests/04/10/16/17/29/35`。

## A. 装配

### A.1 添加组件与组件操作

```python
m = NXOpen.Matrix3x3(); m.Xx = 1.0; m.Yy = 1.0; m.Zz = 1.0   # ⚠ 无参构造为全 0，必须显式置对角
# 实参第 2 位=引用集名、第 3 位=组件名（已核对；再后面的实参未逐位验证）。
# 下面这行与仓库现有调用点写法一致（nxlib/assembly.py、tests/16、tests/17 都传 "1","MODEL"）：
# "1" 当引用集名（非法值 → 静默回退成 MODEL）、"MODEL" 当组件名，功能可用但没真正选引用集。
comp, status = assy.ComponentAssembly.AddComponent(
    part_path, "1", "MODEL", NXOpen.Point3d(0,0,0), m, 1)     # ⚠ 返回 (component, loadStatus) 元组
# 要显式写引用集/组件名：AddComponent(part_path, "MODEL", "LINK_A", ...)
children = assy.ComponentAssembly.RootComponent.GetChildren() # ⚠ 没有 .Components 属性
```

- `Matrix3x3` 字段组 = **局部轴在全局坐标中的分量**（`Xx/Xy/Xz` 为局部 X 轴三分量，`Y*`/`Z*` 同理，按列存）。+θ 绕 Z：`m.Xx=ca; m.Xy=sa; m.Yx=-sa; m.Yy=ca`；按行组写会得到**同一坐标系内的反向旋转**（+θ ↔ −θ，不是镜像角位），NX 原样回存、**不报错**，须用含姿态的 `GetPosition` 断言暴露。
- ⚠ **姿态/方向阵一律显式赋值**：`NXOpen.Matrix3x3()` 无参构造是**全零阵**，漏置对角传给 `MoveComponent`/`AddComponent` 不抛异常但语义退化（`MoveComponent` 会把组件原点塌到平移量上）。`nxlib.assembly.identity_matrix()` 显式置三对角就是为此。
- `MoveComponent(comp, Vector3d(t), R)` **可用**：`t` 是装配坐标系下的**增量**、逐次累加（不是绝对落位）；`Fix` 约束不阻止移动；`R` 的旋转枢轴是**全局原点**（不是组件自身原点），且传入矩阵被取转置（请求 +90° 的实际几何作用是 −90°）——**回读矩阵的角度判不出方向，要用模型点位移判**。需要绝对落位时先算差值或用约束，别 Remove + `AddComponent`（后者会丢 `Name`/refset）。
- 组件的 `Name` 取 `AddComponent` 的**组件名实参**（`comp.Name`）；显示名用 `DisplayName`。按上面那行写法（第 3 位 `"MODEL"`）回读就是 `Name='MODEL'`——那是实参，不是 NX 默认值；要别的名字用正确实参位或随后 `SetName()`（tests/16 就是加完再 `SetName`）。
- 验证后才保存；GUI 不热重载，需重开（modeling.md §1.8）。

**组件加载不到时先查加载方式**（三种方式互斥，不是叠加）：
- `AsSaved` 按 .prt 里记录的组件目录找；`FromDirectory` 只搜父件所在目录，搜索目录列表完全不参与；`SearchDirectories` 只按列表找，不搜父件目录。装配或图纸副本被移到别处、组件留在原目录时，`FromDirectory` 会把组件全部卸载。
- 未加载的唯一判据是 `PartLoadStatus.NumberUnloadedParts`（`GetPartName`/`GetStatusDescription` 给明细，按部件文件去重）；**`comp.Prototype` 对未加载组件也返回占位对象且不抛异常**，不能用来计数。
- 跨机持久化：`Session.Parts.LoadOptions.Save(def_path)` 生成 def，`UGII_LOAD_OPTIONS` 指向它（NX 启动读一次，需重启）；会话内改 `ComponentLoadMethod` **会写回 def**（def 里 `LoadOptions_LoadOption` 分记 `load_as_saved`/`load_from_dir`/`load_from_search_dirs`，三种方式写出三种取值）。反证法验收：把 def 改成另一种方式，新会话必须复现未加载；改回必须全加载——证明配置真被读取，而不是记住了上次会话状态。

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

**Fix（固定基准件）**：引用对象就是组件自身，不挂几何；与 Touch 一起进同一网络求解：

```python
cf = pos.CreateConstraint(True)
cf.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
cf.CreateConstraintReference(c_fixed, c_fixed, False, False, False)
cf.SetName("FIX_base")
```

加 Fix 后 `c_fixed.GetDegreesOfFreedom()` = `0T+0R` 且位置不变；同一网络里被 Touch 的活动件 = `2T+1R`（平面贴合消 1T+2R）。

- `con.Type` 只读 → 用 `con.ConstraintType`。
- `Distance` 偏置**真正可用的是 `con.Expression.RightHandSide = "50"`**（成功且回读 50）；`con.OffsetRightHandSide` setter 不可用（传 str 报 `Not yet implemented`，传 float 报 `Expecting str type, found float` 的类型错）。
- DOF 仅辅助，**读数可能陈旧，不能当"约束是否生效"的互证工具**：件已被解算移动、`Solve()` 返回 None 之后，`GetDegreesOfFreedom()` 仍可能读 `3T+3R`；补 `DoUpdate` 后同样可能读 `3T+3R`。何时读到 `0T+0R`/`1T+1R` 无稳定判据（陈旧机制疑在 `ClearNetwork`/约束持久性，未定论），`Fix`/`Fit` 在已解算网络上读到过正确值也不能外推。可当结论用的只有一条：删约束后任何件 `3T+3R`。做法：交付判据写拖动后的几何量与 `GetPosition()`，不写"DOF=X"。
- `RemoveComponent` 不删 positioner 持久约束。清空：`for c in list(positioner.Constraints): c.Persistent = False` → `DeleteNonPersistentConstraints()` → 冷开 `list(...)==[]`。
- 面引用 = `FindOccurrence(原型面)`；用错原型面**在装配约束里不报错**——错配的引用被接受，只在解算时静默变 `CannotSolve`。`not in the same file as the Targetset` 是 CAE 目标集（`SetObject`/TargetSetManager）的话（fea.md §5），别当装配约束的报错。

约束类型枚举（NX12 全表）：Touch/Concentric/Fix/Distance/Parallel/Perpendicular/Center12/Center22/Angle/Fit/Bond/OrientAngle/AlignLock/Hinge/Slider/Cylindrical/Ball/Screw/Gear/RackPinion/Cable/LinearPattern/CircularPattern/Linear2dPattern/RadiantPattern/CommonOffsetTransform/SplineData/SplineLength/Undefined。
（`ValueOf` 在 `dir()` 里但**不是枚举成员**，赋类型报 `Expecting NXOpen.Positioning.Constraint.Type type, found builtin_function_or_method`。）
⚠ **`Hinge`/`Slider`/`Cylindrical`/`Ball`/`Screw`/`Gear`/`RackPinion`/`Cable`/`CommonOffsetTransform`/`LinearPattern`/`CircularPattern`/`Linear2dPattern`/`RadiantPattern` 标注 `For internal use only`**，赋 `ConstraintType` 抛 `NXOpen.NXException: The constraint type is not valid for this operation.`（13 项全拒）。

**可用性结论（做空间机构必读）**：装配定位层**没有球铰/圆柱铰/铰链/滑块原语**——对 25 种类型逐一赋 `ConstraintType`：可赋 **16**（`Touch`/`Concentric`/`Fix`/`Distance`/`Parallel`/`Perpendicular`/`Center12`/`Center22`/`Angle`/`Fit`/`Bond`/`OrientAngle`/`AlignLock`/`SplineData`/`SplineLength`/`Undefined`），抛错 **9**（`Hinge`/`Slider`/`Cylindrical`/`Ball`/`Screw`/`Gear`/`RackPinion`/`Cable`/`CommonOffsetTransform`）。所以**球铰 + 圆柱铰的连杆机构在装配层无法约束**：硬凑 `Fit`/`Bond` 会让解算把件甩飞（真空间机构上件被挪走 **869.6 m**），且铰点同轴度读数对轴向滑移不敏感、不能用。正确做法：装配层只做**定位** + `Fit`/`Bond`（转动副走 §A.5 的 `Fit`/`Bond`，移动副走「两组平面 Touch」），铰链改在 Motion 域建——`motion.md` §M.3 只文档化并验证了 `Revolute` 与 `Slider` 两种关节的建法，`Ball`/`Cylindrical`/`Hinge` 在 Motion 域可建与否**未验证**（没有该实验）。

求解路线：先 `Fix` 基准件，再加 `Touch`/`Concentric`；`Distance` 偏置走 `con.Expression.RightHandSide`，其余可行回退走 §A.5 Bond 决策树——间隙配合/同轴贴合优先 Bond。对齐没有 `Align` 成员，用 `Concentric`/`Fit`。

### A.3 组件阵列 / 引用集 / 干涉

- 阵列：`CreateComponentPatternBuilder(ComponentPattern.Null)`；`SelectObjectList`（`cps.Add(comp)`/`SetArray`）→ `Commit` 后子件数按阵列数增；`PatternService` 成员同特征阵列（modeling.md §3.1）。
- 引用集：`ReplaceReferenceSet(comp, "Entire Part"/"MODEL"/"Empty")`（默认 MODEL）；MODEL=仅实体、Entire Part=+草图+基准、Empty=空载。⚠ MODEL 下草图曲线仍投影 → 建视图前 Blank 源头（drafting.md §B.1）。
- **干涉路线**：布尔交集 + `SimpleInterference` 两条独立路线都跑；`ClearanceSets` 只有读/删；`AssembliesUtils` 只有 `NewWaveQuery`，不要用于新建干涉检查——注意其真名是 **`NXOpen.AssembliesUtils`**（`session.AssembliesUtils`），`NXOpen.Assemblies.AssembliesUtils` **不存在**，照后者写会 `AttributeError`。
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
- 间隙配合时 `Fit` 不可用，`Bond` 作几何补丁；间隙动力学须另建。

**拖动配方**：
```python
net = pos.EstablishNetwork()
for c in cons:
    net.AddConstraint(c)
net.NonMovingGroupGrounded = False          # ⚠ 默认就是 False；置 True 的效果随几何而异（见下），不是可靠开关
net.BeginDrag()
net.SetMovingGroup([by["曲柄"]])            # 名单不决定谁动：谁动由约束连通性决定（见下）
net.DragByTransform(NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(5.0))
net.Solve(); net.ApplyToModel(); net.EndDrag(); pos.ClearNetwork()
```
- **拖动枢轴 = 约束铰轴线**（**不是**该件自身原点，也不是全局原点；与 §A.1 `MoveComponent` 绕全局原点**不是同一 API，不可混写**）：Fit 单铰下拖 90°，铰轴点原地不动、`dir` 不变、Fit 仍 `Solved`、DOF 仍 `1T+1R`，而组件原点绕铰轴划弧离开原位——若真绕自身原点转，孔轴必甩成水平、Fit 必破。`DragByTranslation` 是**纯平移**。传入矩阵同样被取转置（请求 +90° 实际 −90°）。
- 谁动**由约束连通性决定，不由移动组名单决定**：默认 `NonMovingGroupGrounded=False` 时单件组照样驱动机器（Bond 伙伴被一并带走、Touch 伙伴随动）。⚠ **置 True 不是"拖不动"的开关**——同一 flag 在两套几何里表现相反：Bond 组那套里 True 使整组（含组内件）原地不动，Fit 铰那套里 True 仍被驱动转 10°（`J17_DRAG rot_grounded_TRUE grounded=True applied=ok err=None (0.0,0.0,30.0,0.0) -> (-2.3009,3.7008,30.0,10.0) moved=10.0000`）。本环境只有"**默认值为 False**"是实证结论，别把 True 当锁死手段。任意活动杆都能驱动整机。
- GUI 路径：装配 → 组件位置 → 移动组件，类型「动态」。

**判据与约束**：
- `Concentric` 挂圆柱面报 `CannotSolve` → 改挂孔口圆边；圆边约束了什么须拖动验证（位移落轴、绕轴自由、沿轴滑被拒），不能靠静态 DOF 读数下结论。
- `Fit` 不等半径报 `InternallyInconsistent`；`AlignLock` **建得出来**（`FindOccurrence(圆柱面)` 返回 `Face` 不是 `None`，无 `No overload matches these arguments.`），但解算静默 `CannotSolve` → 不要用，改 `Concentric` 圆边或 `Fit`。
- 路线：`Concentric` 孔口圆边无半径要求；`Fit` 圆柱面**必须严格等半径**（硬几何前提：配合件的孔/轴半径要手工精确匹配到同一值，否则 `InternallyInconsistent`），可读 `1T+1R`。交付用 `Fit`+`Bond`。

圆边取**孔口整圆**（`p1 == p2 == 圆心`），用 `hole_top_edge()` 的"两顶点重合+取近顶面"筛法；取错面对齐到另一端。⚠ 该筛法**依赖几何构造方式**：同一几何上 `hole_face()` 可能返回含 4 条边（2 圆 2 直）的面，筛法在那种面上一个边都拿不到（返回 `None`），只有纯圆柱面才拿到 2 条——换几何后须先验证筛法成立，别当成通用。⚠ 圆边路线只在最小几何上验证，**真实多杆机构未验证**。

**验证**：故意移开再解算须弹回同轴（静态重合时"无错+间隙 0"无证明力）；拖动后重测铰轴间隙；脚本不保存，保存后重新 `Parts.Open` 复测；`DexManager.CreateStlCreator` 导 STL 第三方复算（SKILL.md §3 路线约束 6）。

⚠ 不要假设被抓住的杆自身必转指定角度，须逐位姿核对。2–3 件单铰几何上请求 12°/90° 都被精确交付，"长连杆灵敏度极低"**未复现**（长连杆机构本身未构造，不能据此断言会不会偏）。

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
