# 装配域（NX 12 批处理）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。本文件 §A 装配：组件/配对约束/阵列/引用集/干涉/运动连接。工程图见 `drafting.md`，标注见 `drafting-annotation.md`。示例 `scripts/tests/04/10/16/17/29/35`。

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

**Fix（固定基准件）**：引用对象就是组件自身，不挂几何；与 Touch 一起进同一网络求解：

```python
cf = pos.CreateConstraint(True)
cf.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
cf.CreateConstraintReference(c_fixed, c_fixed, False, False, False)
cf.SetName("FIX_base")
```

加 Fix 后 `c_fixed.GetDegreesOfFreedom()` = `0T+0R` 且位置不变；同一网络里被 Touch 的活动件 = `2T+1R`（平面贴合消 1T+2R）。

- `con.Type` 只读 → 用 `con.ConstraintType`。
- Distance `con.OffsetRightHandSide` setter 报 "Not yet implemented" → 用显式坐标或 Touch/Concentric。
- DOF 仅辅助，须约束存活时读（删约束后任何件 `3T+3R`）；互证：`Fix` `0T+0R`、`Fit` 等半径孔面 `1T+1R`、`Concentric` 孔口圆边 `0T+1R`、未约束 `3T+3R`；位置以 `GetPosition()` 为准。
- `RemoveComponent` 不删 positioner 持久约束。清空：`for c in list(positioner.Constraints): c.Persistent = False` → `DeleteNonPersistentConstraints()` → 冷开 `list(...)==[]`。
- 面引用 = `FindOccurrence(原型面)`；用错原型面报 "not in the same file as the Targetset"（fea.md §5）。

约束类型枚举（NX12 全表）：Touch/Concentric/Fix/Distance/Parallel/Perpendicular/Center12/Center22/Angle/Fit/Bond/OrientAngle/AlignLock/Hinge/Slider/Cylindrical/Ball/Screw/Gear/RackPinion/Cable/LinearPattern/CircularPattern/Linear2dPattern/RadiantPattern/CommonOffsetTransform/SplineData/SplineLength/Undefined。
（`ValueOf` 在 `dir()` 里但**不是枚举成员**，赋类型报 `Expecting NXOpen.Positioning.Constraint.Type type, found builtin_function_or_method`。）
⚠ **`Hinge`/`Slider`/`Cylindrical`/`Ball`/`Screw`/`Gear`/`RackPinion`/`Cable`/`LinearPattern`/`CircularPattern`/`Linear2dPattern`/`RadiantPattern`/`CommonOffsetTransform` 标注 `For internal use only`**，赋 `ConstraintType` 抛 `NXOpen.NXException: The constraint type is not valid for this operation.` → 转动副走 §A.5 的 `Fit`/`Bond`，移动副走「两组平面 Touch」。

求解路线：先 `Fix` 基准件，再加 `Touch`/`Concentric`；显式坐标回退后走 §A.5 Bond 决策树——间隙配合/同轴贴合（r6 销配 r6.1 孔）优先 Bond。对齐没有 `Align` 成员，用 `Concentric`/`Fit`。

### A.3 组件阵列 / 引用集 / 干涉

- 阵列：`CreateComponentPatternBuilder(ComponentPattern.Null)`；`SelectObjectList`（`cps.Add(comp)`/`SetArray`）→ `Commit` 后子件数按阵列数增；`PatternService` 成员同特征阵列（modeling.md §3.1）。
- 引用集：`ReplaceReferenceSet(comp, "Entire Part"/"MODEL"/"Empty")`（默认 MODEL）；MODEL=仅实体、Entire Part=+草图+基准、Empty=空载。⚠ MODEL 下草图曲线仍投影 → 建视图前 Blank 源头（drafting.md §B.1）。
- **干涉路线**：布尔交集 + `SimpleInterference` 两条独立路线都跑；`ClearanceSets` 只有读/删，`AssembliesUtils` 只有 `NewWaveQuery`，不要用于新建干涉检查。
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

**判据与约束**：
- `Concentric` 挂圆柱面报 `CannotSolve` → 改挂孔口圆边；圆边约束了什么须拖动验证（位移落轴、`0T+1R`、绕轴自由、沿轴滑被拒）。
- `Fit` 不等半径报 `InternallyInconsistent`；`AlignLock` 建不出来（`FindOccurrence(圆柱面)` 返回 `None`，报 `No overload matches these arguments.`）→ 改 `Concentric` 圆边或 `Fit`。
- 路线：`Concentric` 孔口圆边给 `0T+1R`、无半径要求；`Fit` 圆柱面给 `1T+1R`、必须等半径。交付用 `Fit`+`Bond`。

圆边取**孔口整圆**（`p1 == p2 == 圆心`），用 `hole_top_edge()` 的"两顶点重合+取近顶面"筛法；取错面对齐到另一端。⚠ 圆边路线只在最小几何上验证，**真实多杆机构未验证**。

**验证**：故意移开再解算须弹回同轴（静态重合时"无错+间隙 0"无证明力）；拖动后重测铰轴间隙；脚本不保存，保存后重新 `Parts.Open` 复测；`DexManager.CreateStlCreator` 导 STL 第三方复算（SKILL.md §3 路线约束 6）。

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
