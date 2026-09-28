# 运动仿真域（NX Motion，NX 12 本机批处理实测）

NXMotion = 机构运动学与动力学仿真。本域覆盖「建运动副 → 加驱动/载荷 → 求解 → 读结果」全链路。
全部条目经 2026-09-16 批处理实测（来源是四连杆机构的载荷用例，取证脚本归档在项目侧 `work` 下；回归见 §M.10）。
**读本文件前先读 SKILL.md §1 铁律与 §3 骨架**（Session/部件层通用操作在那里，本文件不重复）。

## M. 运动仿真

### M.1 建立仿真并进入 .sim 部件

```python
ms = theSession.MotionSession
ms.CreateSimulation(master_part)              # master = 已打开的装配件
sim_part = None
for p in theSession.Parts:                    # 新生成的 .sim 部件，按后缀认领
    if p is not None and (p.FullPath or "").lower().endswith(".sim"):
        sim_part = p; break
ms.InitializeSimulation(sim_part)
ufs.Part.SetDisplayPart(sim_part.Tag)         # 结果对象都挂在 .sim 部件上
theSession.Parts.SetWork(sim_part)
mm = sim_part.MotionManager                   # .Links / .Joints / .JointDrivers
                                              # / .MotionSolutions / .ScalarTorques
```

⚠ **运动结果只能在 `.sim` 部件上读**：`links`/`joints` 属于 sim_part，不是 master。⚠ `theSession.Parts` 直接迭代（集合无 `ToArray()`，见 SKILL.md §3 坑位 4）。

### M.2 Link（构件）与质量属性

**无几何 Link 可提交**：`Geometries` 留空 + `MassType = UserDefined` 即可。

```python
lb = mm.Links.CreateLinkBuilder(M.Link.Null)          # 空对象用 .Null（SKILL.md §3 坑位 1）
lb.Name = "L_" + cn
lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
set_expr(sim_part, lb.MassProperty.MassExpression, "%.6f" % MASS[cn])
for ax in ("IxxExpression", "IyyExpression", "IzzExpression"):
    set_expr(sim_part, getattr(lb.MassProperty, ax), "%.4f" % INERT[cn])
for ax in ("IxyExpression", "IxzExpression", "IyzExpression"):
    set_expr(sim_part, getattr(lb.MassProperty, ax), "0.0")
lb.MassProperty.MassCenter = cm[cn]                   # ⚠ 必须是 NXOpen.Point 对象
link = lb.Commit(); lb.Destroy()
```

⚠⚠ **两个静默失效点（必看，两者都曾致动力学完全失真）**：

1. **`MassCenter` 需要 `NXOpen.Point` 对象，不是 `NXOpen.Point3d`**。传 `Point3d` 报 `Expecting NXOpen.Point type`；若该行在 `try/except` 里被吞掉就**静默失败 → 质心回落绝对原点**，反力全错。且**质心点必须在建 Link 之前创建**（`sim_part.Points.CreatePoint(NXOpen.Point3d(x, y, 0.0))`）。
2. **`Ixx`/`Iyy` 不设（或设 0）而 `Izz` 非零 → 惯性张量非正定**，面外反力出现 500~900 N 伪尖峰。无几何杆件无法指定主轴方向，故取**各向同性** `Ixx=Iyy=Izz=m·L²/12`（细杆面内真值即 `Izz`；面外两向偏大，但只影响本应恒为零的面外反力，数值稳定且无害）。

**自检**：算完把每个 Link 的质心坐标/质量打印出来（`141` 的做法），质心若全在原点即中招 1。

### M.3 运动副（转动副）

```python
zd = sim_part.Directions.CreateDirection(pts[pn], NXOpen.Vector3d(0.0, 0.0, 1.0))  # 轴线方向
jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
jd = jb.JointDefine
jd.JointType = M.JointDefine.Type.Revolute
jd.FirstLink  = links[comp_a]      # ⚠ 接受 Motion.Link，不是 Component
jd.SecondLink = links[comp_b]
jd.FirstOrigin = pts[pn]           # ⚠ 接受 NXOpen.Point
jd.FirstVector = zd                # ⚠ 接受 NXOpen.Direction
jd.Name = jn                       # ⚠ 必填（漏了 Commit 报错）
joint = jb.Commit(); jb.Destroy()
ms.FixLinkToGround(links[ground_cn])          # 接地件
```

`JointDefine` 另可供：`SecondOrigin`/`SecondVector`、`FirstCsys`/`SecondCsys`/`FirstMatrix`、`ExcludeRxConstraint` 等、`AxisType`、`LimitsDefined`。**枚举在 `ufs.Motion`（`UFSession.GetUFSession().Motion`）下**：`MotionType`、`VectorComponent`、`ReferenceFrame`、`FuncResultType`、`FuncComponentType`、`FuncRefFrameType`。⚠ `NXOpen.UF.UFMotion` 不可导入（`from NXOpen.UF import UFMotion` 失败）——但 `ufs.Motion` 对象本身提供上述枚举。⚠ `.NET 侧` 的枚举（如 `SpringBuilder.AttachmentType`）挂在**类**上，不要写实例（SKILL.md §3 坑位 9/10）。

### M.4 驱动

```python
jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
jdb.Name = "DRV_CRANK"                       # ⚠ 必填
jdb.Joint.Value = joints["J_A"]
op = jdb.DriverMultiOperations.MotionEulerAngle1
op.TypeOption = M.DriverOperation.Type.Constant
op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
set_expr(sim_part, op.VelocityExpression, "%.1f" % OMEGA_DEG_S)   # ⚠ 单位 deg/s
jdb.Commit(); jdb.Destroy()
```
转速换算：`OMEGA_DEG_S = rpm × 6`（如 65 r/min → 390 deg/s）。

✅ **deg/s 口径已独立验证**（2026-09-16，测试 18）：四杆用例令 `OMEGA_DEG_S = 360.0`、`T_END = 1.0`、`NSTEP = 360`，
则每帧转角应 = `360×1.0/360 = 1.000000°`。实测取位姿后差分得 **mean = 1.000000°、max_dev = 1.9e-5°**，
与指令速率完全吻合 → `MotionEulerAngle1` + `IntegrationType.Velocity` 的 `VelocityExpression` 确为 **deg/s**（若按 rad/s 解释会得 57.2958°/帧）。
把这条期望写进检查，就是**驱动单位陷阱的常驻探针**。

⚠ **驱动转向与矩阵口径（2026-09-25 冷测 T3 实测）**：`MotionEulerAngle1` 正值速度驱动的实际转向为**顺时针**（+390 deg/s 解出 CW），反向需传负值；帧变换矩阵为**行主序**，相对角用 `atan2(r[4], r[0])` 口径曾引入 92° 相位伪偏差——角度提取一律用绝对角。

### M.5 载荷：标量力矩（ScalarTorque）

```python
stb = mm.ScalarTorques.CreateScalarTorqueBuilder(M.ScalarTorque.Null)
stb.Name = "ST_J_D"
stb.TorqueType = M.ScalarTorqueBuilder.ScalarTorqueType.Joint   # 作用于某运动副
stb.Joint.Value = joints["J_D"]
stb.ValueType = M.ForceValueTypes.Constant
stb.ApplicationType = M.ScalarTorqueBuilder.AppType.ActionReaction
set_expr(sim_part, stb.ValueExpression, "%.6f" % val)
stb.Commit(); stb.Destroy()
```

⚠⚠ **单位陷阱**：部件长度单位为 mm 时，`ValueExpression` 按 **N·mm** 解释，**不是 N·m**。判据：施加 `1608` 得到 J_B=34.47 N（与手算 34.93 N 相符，M=1.608 N·m ÷ 46.04 mm 力臂）；施加 `1.608` 只得到 0.63 N。**反力比手算小约 1000 倍时先查此单位。** 宏 `NM_TO_NMM = 1000.0`。

⚠⚠ **NX12 的 `ValueExpression` 不能引用运动状态函数**：`WZ(...)`、`IF`、`TANH`、`SGN` 全部报 `The specified string contains a syntax error`。故**库仑摩擦 `τ = −Mf·sgn(ω)` 无法在 NX 内表达**。已注册旧式函数（`ufs.Motion.CreateFunction(st)`，`st.Definition = [字符串]`）也**拿不到对象引用**（`stb.Function` / `stb.Profile.Value` 均为 `None`）。**变通**：按摇杆角速度符号拆成两个恒定力矩工况（`±sgn`）分别求解再拼接；精确的符号相关载荷改用外部静定解算器（见 §M.8）。

### M.5a 连接件：弹簧 / 阻尼 / 衬套（2026-09-22 实测）

**`MotionManager` 上真正存在的连接件集合**（`dir()` 实测，别猜 `ScalarSprings`）：

| 有 | 无（AttributeError） |
| --- | --- |
| `Springs`（`CreateSpringBuilder`）、`Dampers`（`CreateDamperBuilder`）、`Bushings`（`CreateBushingBuilder`）、`ScalarForces`、`VectorForces`、`BodyContacts`、`CurveContacts`、`AnalyticalContacts`、`ControlInputs`、`PlantInputs`、`PMDCMotors`、`FlexBodies` | `ScalarSprings`、`ScalarDampers`、`ScalarBushings`、类 `ScalarSpring`/`ScalarDamper`/`ScalarBushing`（不存在） |

**弹簧（实测建成功，`Commit OK springs 0->1`）**：

```python
b = mm.Springs.CreateSpringBuilder(M.Spring.Null)
b.Name = "PT_SPRING"                      # ⚠ Name 是普通可写 str（非通道）
# ⚠ 不要设 AttachmentType：它在实例上是**只读**属性，赋值报
#   'NXOpen.Motion.SpringBuilder' object attribute 'AttachmentType' is read-only
#   （枚举类本身存在：M.ConnectorBuilder.AttachmentType，成员含 Link；
#     不设它也能提交成功，默认已够用——本配方就是"不设它"跑通的）
b.ActionLink.Value  = links[0]            # ⚠ 链接是**只读容器属性**，见 SKILL.md 铁律 4：
b.ReactionLink.Value = links[1]           #   要写 b.ActionLink.Value，直接给 b.ActionLink 赋值无效
b.ActionPoint   = pts[0]                  # ⚠ 点/向量是直接可写属性（NXOpen.Point / Direction）
b.ReactionPoint = pts[1]
set_expr(sim_part, b.StiffnessExpression, "10.0")   # 同 §M.5 的 set_expr
b.Validate(); b.Commit(); b.Destroy()
```

在实例上**读** `b.AttachmentType` 一样报 AttributeError（同一条只读保护），所以连"读出来看看当前值"这条也走不通。

三个表达式都可写：`StiffnessExpression` / `CoefficientExpression` / `FreeLengthExpression`。

**阻尼（2026-09-22 打通）**：

```python
d = mm.Dampers.CreateDamperBuilder(M.Damper.Null)
d.Name = "PT_DAMPER"
d.ActionLink.Value   = links[0]      # 两个 SelectObject 一直都在，写 .Value 即可
d.ReactionLink.Value = links[1]
d.ActionPoint, d.ReactionPoint = pts[0], pts[1]
set_expr(sim_part, d.CoefficientExpression, "1.0")
d.CoefficientType = NXOpen.Motion.ConnectorCoefficientTypes.Constant   # ⚠ 真正缺的就是这一项
d.Validate(); d.Commit()             # → Dampers 0->1（实测）
```

`CoefficientType` 用**模块级枚举类** `NXOpen.Motion.ConnectorCoefficientTypes.Constant`；`AttachmentType`（枚举类
`M.ConnectorBuilderAttachmentType`，成员 `Link / RevoluteJoint / SliderJoint`）**不需要设**，阻尼器的连接关系由
ActionLink/ReactionLink 表达。

**衬套（2026-09-22 打通；此前卡在 `A NULL value` 上两轮）**：

```python
b = mm.Bushings.CreateBushingBuilder(M.Bushing.Null)
b.Name                            # ⚠ AttributeError：BushingBuilder 没有 Name
b.BushingDefine.Name = "PT_BUSH"   # ⚠ 名称/连接全在 BushingDefine 子对象里（通道语义）
b.BushingDefine.ActionLink.Value = links[0]     # ✅ 可写
b.BushingDefine.ReactionLink.Value = links[1]   # ✅ 可写
b.BushingDefine.ActionPoint / ReactionPoint     # ✅ 可写
b.BushingType = b.BushingTypes.General          # ⚠ 枚举挂在 **builder 实例** 上（b.BushingTypes），
                                                  #   M.BushingTypes 不存在；Cylindrical / General / Spherical
comp = b.BushingStiffnessCoefficients.GeneralTranslationalStiffnessCoefficients
tc   = b.BushingStiffnessCoefficients.GeneralTorsionalStiffnessCoefficients
for c in (comp, tc):
    for ax in ("X", "Y", "Z"):
        set_expr(sim_part, getattr(c, ax + "Expression"), "100.0")
    c.CoefficientsType = c.XCoefficientsType = NXOpen.Motion.ConnectorCoefficientTypes.Constant
# ⚠⚠ 唯一缺的那一项：Orientation 要 **NXMatrix**（给 Direction 报
#    Expecting NXOpen.NXMatrix type），只能取自部件坐标系的 Orientation：
xf   = sim_part.Xforms.CreateXformByPointXDirZDir(
           pts[0], xd, zd, NXOpen.SmartObject.UpdateOption.WithinModeling, 1.0)
csys = sim_part.CoordinateSystems.CreateCoordinateSystem(
           xf, NXOpen.SmartObject.UpdateOption.WithinModeling)
b.BushingDefine.Orientation = csys.Orientation     # type(csys.Orientation).__name__ == "NXMatrix"
b.Validate(); b.Commit()                           # → Bushings 0->1（实测）
```

- 不给 `Orientation` 的提交结果就是 `A NULL value was encountered`（负对照已入 23 号用例），
  `BushingDefine.Csys` / `Direction` 默认都是 `NoneType`，往这两个字段灌 csys/Direction 也都解不开。
- 系数容器全貌（`BushingStiffnessCoefficients` / `BushingDampingCoefficients` 各一份，结构相同）：
  `GeneralTranslational*Coefficients`（`CoefficientsType / XCoefficientsType / X|Y|ZExpression / X|Y|ZCurveProfile / X|Y|ZFunction`）、
  `GeneralTorsional*Coefficients`（同成员）、`Cylindrical*Coefficients`（`Radial / Longitudinal / Torsional / Conical`
  各带 `Expression / Type / CurveProfile / Function`）、`Spherical*Coefficients`（`Radial / Conical`）。
  ⚠ **通用型与圆柱/球形型不能混填**（混填报 `BushingCoefficients is deprecated … mixed usage is not supported`）；
  `General` 型只需给 General 那两组 + `CoefficientsType = Constant`。
  另有旧族 `BushingCoefficients`（deprecated，勿用）与第三族 `BushingActuatorCoefficients`（未实测）。
- `BushingDefine` 其余成员：`ActionOffset{X,Y,Z} / AngleCalculation(+Option) / ApplyActionOffset / ApplyBaseOffset /
  BaseOffset{X,Y,Z} / Dipole / ForceCalculation(+Option) / OrientationType`。
- 枚举：`BushingDefineOrientationTypes` 实测 `dir()` 只列出 `value`（成员名未暴露，需按值试）；`AngleCalculationOption` = `LargeAngle/SmallAngle`；`ForceCalculationOption` = `Abc/Bab/Standard`。

**枚举访问器陷阱（本域通用，两轮探针各崩一次）**：builder 上形如 `b.Types()` / `b.HoleDepthOptions()` /
`d.AttachmentType()` 的成员是**方法**（枚举访问器），**0 参调用会抛 `NXException: instances of NX enums can not
be created`** 并当场中断整个 journal（后面的诊断全部丢失）。要用枚举就用**模块级嵌套类**：
`NXOpen.Motion.ConnectorCoefficientTypes.Constant`、`NXOpen.Features.HolePackageBuilder.Types.ThreadedHole`。
另：对枚举**成员类型**做 `dir()` 结果为空，只有枚举**类**才能枚举出成员名。

### M.5b 后处理 / 干涉 / 自由度计数（2026-09-22 实测：存在性 + 一条可跑）

`mm.PostProcess` 实测成员全集：`CaptureArrangement / CreateEnvelope / CreateSequence / EnvelopeAccuracyModes / EnvelopeTolerance / EnvelopeToleranceTypes / ExplodeMechanism / ExportRealTimeMovie / ExportToMovie / GetInterferenceOption / GetMeasureOption / GetSpeed / GetStopOnEventOption / GetTraceOption / ListInterference / ListMeasure / RegisterUserButton / SetInterferenceOption / SetMeasureOption / SetSpeed / SetStopOnEventOption / SetTraceOption / TraceCurrentPosition / TraceEntireMechanism / TraceIntersectionCurve / UpdateDesignPosition`。

- ✅ `ufs.Motion.AskGrueblerCount()` 可跑：2 Link + 1 转动副的探针机构返回 **7**（该数在 `6n − 5j` 口径下是"未减约束"的粗计数，**不要与"机构自由度"混为一谈**，判静定仍按 §M.8 的空间计数）。
- `AskSolverDofCount()` 存在（未逐值核对）；`CalculateStaticEquilibrium()` 存在（未实测）。
- **UF 结构体命名（通用规矩，见 SKILL.md §3 坑位 9）**：`st = ufs.Motion.InitInterferenceStruct()`（0 参！out 参数是返回值），字段 `Solid1` / `Solid2`；`ufs.Motion.CreateInterference(...)` 在 Python 绑定下抛 `SystemError`（返回类型未映射），**干涉检查在批处理下无可用入口** → 用帧变换后处理自算（同 §M.10 的间隙判据）。
- `CreateTrace` / `InitTraceStruct` / `AskTrace` / `CreateMeasurement` / `InitMeasurementStruct` 均存在（**未逐值验证**，用前最小探针）。

### M.5c 驱动的种类上限（2026-09-22 实测）

`jdb.DriverMultiOperations` 实测**只有三个**：`MotionEulerAngle1`、`MotionPointOnCurve`、`MotionTranslationZ`（另有 `Tag`）。
即批处理可编程的驱动类型 = **绕轴转角 / 沿曲线 / 沿 Z 平移**。文档里的"旋转副用 …、滑动副用 …"若超出这三种，须回退到 GUI 或用运动状态函数（后者见 §M.5 的单位/语法限制）。

### M.6 求解

```python
sb = mm.MotionSolutions.CreateSolutionBuilder(M.MotionSolution.Null)
sb.Name = "SOL_CASE"                         # ⚠ 必填
sb.SolutionType = M.MotionSolutionBuilder.SolutionTypes.Normal
sb.AnalysisType = M.MotionSolutionBuilder.AnalysisTypes.Dynamic
sb.Step = nstep                              # 积分数
set_expr(sim_part, sb.TimeExpression, "%.3f" % t_end)     # 终止时间（只读 Expression）
# sb.GravityVector 需要 NXOpen.Direction（要重力时给）
sol = sb.Commit(); sb.Destroy()
sol.SolveNormalRunSolution()
```
`dt = t_end / nstep`；**帧数 = nstep + 1**。
⚠ **但首帧不是 t=0**（2026-09-16 实测，360 步四杆用例）：实测 361 帧，曲柄角序列为
`-1.00000, -2.00000, …, -360.00001, -360.00000` —— 第 1 帧已是**第一个积分步之后**的位形（t=dt），
**末帧与前帧完全重复**（步长 ~8e-6° 而非 1.00000°）。即 361 帧只含 **359 个真实增量**。
推论：**不要假定帧序号 k 对应时刻 (k-1)·dt**；做时间对齐时以「相邻帧增量是否符合指令速率」为准，
不要以帧序号为准（本用例的 1 帧重复在 1080 步的长工况表现为末 3 帧伪影，数量随模型而变）。

### M.7 结果提取

```python
nfr = int(ufs.Motion.AskNumberOfAnimationFrames())

# 反力 / 力矩：返回 (帧数, [值...]) 二元组，取 [1]
r = ufs.Motion.AskForceResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)   # VC=VectorComponent
r = ufs.Motion.AskTorqueResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)  # 驱动力矩

# 构件位姿（16 个 double = 4x4 行主序）
r = ufs.Motion.AskLinkTransfromForGivenFrame(link.Tag, frame)
```

- ⚠ **`AskLinkTransfromForGivenFrame` 优先用 2 参数形式**；3 参数 `(tag, frame, [0.0]*12)` 仅作回退（实测 2 参可用，写成 try/except 两条兜底最稳）。
- ⚠ **返回 16 值 = 完整 4×4 行主序矩阵，平移在索引 3/7/11**（2026-09-28 冷启动实测，逐帧 CSV 核对）：取前 12 即 `R00,R01,R02,Tx | R10,R11,R12,Ty | R20,R21,R22,Tz`——R22 在索引 10（恒 1.0）、Tz 在索引 11，这两位就是最省事的布局自检。只取角度仍用 `atan2(r[4], r[0])`（M.4 矩阵口径），要平移分量就取索引 3/7/11（冷启动四杆：曲柄首帧 Tx=0.00012、R22=1.0000，与解析 0.5° 旋转矩阵逐位吻合）。
- ⚠⚠ **`AskVelocityResults` / `AskAccelerationResults` 实测全返回 `0.0`**（静默失败，不可用）。签名形如 `(tag, MotionType.ROTATION, VC.MAGNITUDE, RF.ABSOLUTE)`，调用不报错但值是零——**不要用它**。
- **自己算 ω/α（推荐）**：对整周帧的连杆方位角做中心差分。平面机构取 `atan2(R[1,0], R[0,0])`（R 为变换左上 3×3）。**必须 `np.gradient(..., edge_order=2)`**，默认一阶边缘处理会在终段产生伪 α 跳变。
- ⚠ **尾部帧不可直接用**：末帧会**重复前一帧**（2026-09-16 四杆实测：361 帧的末帧步长 ~8e-6° vs 常规 1.00000°；长工况表现为末 3 帧位姿回零伪影，ω 从 −4.7 跳到 +350、α 达 10⁵ 量级）。**剔除判据**：从尾部往前，只要相邻帧增量 < 10% 的标称增量就判为重复帧丢弃（标称增量 = 指令速率 × dt）。
  ⚠ 别用「偏离中位步长」判据——从动件本就变速（本四杆 dψ/dθ ∈ 0~0.565 rad/rad），中位判据会把**真实变速**误判为伪影（实测曾把 361 帧误截到第 6 帧，摆角算成 1.7°）。
  剔除后实测与独立平面解偏差：ω 0.005%~0.02%、α 0.2%~0.7%。
- **传动角**可由各连杆局部的**常量方向向量**求出：用首帧变换的逆把设计态方向投到各 Link 局部系（模长恰等于杆长，可自校验），再经各帧 R 旋转后两两求夹角。此法天然免疫「首帧不在零位」的坐标系偏置。
- ⚠⚠ **帧变换平移分量语义（2026-09-17 实测确认）**：返回的 4×4 变换**直接作用于设计位姿世界坐标**，即 `world_k = T_k · [x_design, y_design, 0, 1]`；**不是**「先用 T₀ 求逆得局部坐标再变换」（后者曾致相邻构件共享铰点共点偏差 1.7 mm，探针定界后改正，共点降到 2.4×10⁻⁵ mm）。注意：杆长守恒、摆角、传动角都是**旋转不变量，验证不了平移解析对错**（第5章只用旋转分量，平移语义因此漏网一年）；刚体变换语义的最强轻量自检 = **相邻构件共享铰点逐帧共点检查**（语义正确时 ≤10⁻⁴ mm 量级）。
- **对 atan2 角度序列做差分前必须 `np.unwrap`**（弧度域）：±180° 卷绕跳变会混入增量序列（实测表现为 357.8°/帧 的假速率偏差），且「尾部重复帧」判据随之失效（尾部恰逢卷绕点时永不触发）。
- `ufs.Motion.GetObjectDerivedFunction(joint.Tag, FUNC_VELOCITY, FUNC_EULER3COMP, FUNC_RELATIVE_FRAME)` 返回**旧式函数名字符串**（如 `WZ(J_A_i,J_A_j,J_A_j)`、`WM(...)`），可用来核对「哪个函数名代表哪个量」，但**不能当数值结果用**。

### M.8 静不定与反力伪影（本域最重要的一条）

**用转动副描述平面机构会静不定，反力结果不可直接用。**

平面 5 活动构件 × 7 转动副：自由度计数 `6×5 − 5×7 = −5`，属**静不定（过约束）**。NX 会自己打印
`Redundant constraints will be removed automatically, results may be not as expected.`。
在**摇杆极限位**（曲柄与连杆共线、约束雅可比近奇异）附近，冗余约束的消去方式在相邻积分步之间往复切换，
反力出现**逐帧交替的高频抖动**（实测 `J_D` 相邻帧在 122 N / 185 N 间跳变，Z 向分量在 ~1 N / ~184 N 间跳变）。

**判伪方法（决定性）**：**步长加密 4 倍（1080 → 4320）后若尖峰位置与幅值完全不变 → 求解器冗余约束处理的数值伪影，非积分误差、非真实受力**。辅证：所有杆件面外旋转恒为 `0.0000°`；尖峰帧全部落在死点邻域。

**对策**：铰点反力改用**静定平面刚体动力学模型**另解——
- 每个构件 3 个方程（2 平动 + 1 绕质心转动）→ `3n` 个方程；未知量 = 铰点 × 2 分量 + 1 个驱动力矩。
- 平面六杆 5 构件：`15` 方程 / `15` 未知量（7 铰点 ×2 + 驱动力矩）→ **严格静定，解唯一且连续**。
- 三重验证：闭式解析逐值偏差 `1e-15`；能量守恒（驱动功率 / 摩擦耗散）`1.001`(μ=0.4)/`1.000`(μ=0.8)；与 NX 非死点区逐帧中位偏差 `0.02%~3.4%`。
- 要点：坐标**统一到 SI（mm → m）**（曾漏换构件形心致力臂差 1000 倍）；闭式校核用**实际 μ**，别用 μ=1 试算值。

**Kinematics 仍可取 NX 解**（位姿/摆角/传动角与平面解同源，偏差 ≤0.15°）；**只有反力**因静不定不可信。

⚠ **越简单的机构也躲不掉**（2026-09-16 测试 18 实测）：连「4 个转动副的平面四杆」都静不定 ——
`6×5 − 5×4 = −2`（连杆机构各构件间的公共约束使其按空间计数必然欠定）。求解日志会反复打印
`Starting redundant constraint check...`。故**别以为机构简单就能用 NX 反力**：判定标准是
「按 6-3-5 空间计数是否静定」，而不是机构看起来简不简单。同理，**四杆用例的反力只可用于验 API 通路
（返回条数、数值有限）**，作物理判据须换静定模型。

### M.9 批处理多工况（并行）

`run_journal.exe` **不接收命令行参数** → 用**环境变量**传配置路径，输出文件名按配置名区分：

```python
CFG = os.environ.get("RUN141_CFG") or os.path.join(RESDIR, "load_case.json")
```

加 env 后即可并行跑不同几何态/载荷（两个后台进程互不干扰，各自独立 NX 进程）。⚠ **Git Bash 调用方式**：
`cd` 到 journal 所在目录后直接 `"<技能>\scripts\run_journal_batch.bat" <journal.py>`，**不要**走
`cmd //c "....bat a b"` 形式传尾参（Git Bash 会吞掉/错拼，实测**静默不执行、退出码 0 却无产物**）。

### M.10 回归

```bash
python scripts\check_journal.py scripts\tests\18_motion_sim.py
scripts\run_journal_batch.bat C:\abs\...\scripts\tests\18_motion_sim.py C:\abs\...\scripts\tests\parts
scripts\run_journal_batch.bat C:\abs\...\scripts\tests\23_motion_connectors.py C:\abs\...\scripts\tests\parts
```

- **18 号**（运动学全链路）：成功标志打印 `TEST18_DONE` 且 `BENCH_PASS`（**不能只看退出码**，见 SKILL.md §6）。
- **23 号**（连接件与 UF 接口形状，2026-09-22 扩充）：成功标志 `TEST23_DONE`，**14 项全部通过** ——
  弹簧/阻尼/衬套三者 `Commit` 各使 `Springs`/`Dampers`/`Bushings` 0→1、衬套不给 Orientation 必报 `A NULL value`
  （负对照）、`csys.Orientation` 类型为 `NXMatrix`、`MotionInterference_Struct` 字段与 out 参数即返回值、
  `AskGrueblerCount` 为整数、`DriverMultiOperations` 三项上限。

用例 18 = 自包含平面四杆（AB20 / BC60 / CD40 / AD70，Grashof 满足，AB 为曲柄），4 检查：
曲柄速率+恒速、摇杆摆角 `60.0282°`（解析 `60.0218°`）、每转换向 `2` 次、反力 API 通路。期望值全部来自
**外部解析解**（`work/_t18_verify.py` 式整周扫描），不是从 NX 数据反推。

⚠ **检查必须做反向验证**（证明它有判别力，不是恒真）：2026-09-16 实测两次证伪均按预期 FAIL ——
① 驱动 `360 → 2π`（模拟单位误读）：速率/摆角/换向三检查 FAIL，反力通路仍 PASS（职责划分正确）；
② 连杆 `CD 40 → 50`（改几何、期望不动）：仅摆角检查 FAIL（`47.74°`）。修改检查后请重做此证伪。

### 坑位对照（遇到 → 怎么做）

| 遇到 | 怎么做 |
| --- | --- |
| `AskVelocityResults` / `AskAccelerationResults` 不报错，但返回全 0.0 | 静默失败，不可用；改用帧变换做中心差分 |
| `ScalarTorque.ValueExpression` 里写 `WZ(...)` / `IF(...)` / `TANH(...)` / `SGN(...)`，报 `The specified string contains a syntax error` | 符号相关的载荷改走外部解算器 |
| `ufs.Motion.CreateFunction()` 注册的函数当表达式引用时取不到（`stb.Function` / `stb.Profile.Value` 均为 `None`） | 不走这条；驱动用内置函数或运动状态函数 |
| `MassCenter` 传 `Point3d`，报 `Expecting NXOpen.Point type` | 传 `NXOpen.Point`；写在 try/except 里会静默失效，质心掉到绝对原点 |
| 想拿 NX 三维反力结果做强度校核 | 转动副构成的平面机构是静不定，死点邻域反力有 5~10 倍伪尖峰；反力改用静定解算器（§M.8） |
| 对无几何 Link 的模型用 NX 原生运动包络 / 干涉 | 源对象必须是几何体，无几何 Link 无体可扫掠；包络与构件间隙改用帧变换后处理 |
| `ufs.Motion.CreateInterference()` | Python 绑定抛 `SystemError`（返回类型未映射），批处理无干涉检查入口；只有 `InitInterferenceStruct()` 可用 |
| 访问 `MotionManager.ScalarSprings` / `ScalarDampers` / `ScalarBushings` | 属性不存在；真名是 `Springs` / `Dampers` / `Bushings`（§M.5a） |
| 给 `b.ActionLink` 直接赋值、或在实例上取 `AttachmentType` | 前者是只读容器，要写 `.Value`（否则静默无效）；后者枚举在类上，实例取会 AttributeError（§M.5a） |
| 阻尼器建不出来 | 连接入口一直都在，缺的是 `CoefficientType = Constant`（§M.5a） |
| `BushingBuilder.Commit()` 只给连接与系数，报 `A NULL value was encountered` | 缺 `BushingDefine.Orientation`，且它要 **NXMatrix**（取 `csys.Orientation`，给 Direction 会报 `Expecting NXOpen.NXMatrix type`）（§M.5a） |
| 衬套用旧族 `BushingCoefficients`，或通用型与圆柱·球形型混填 | 分别报 deprecated 与 `mixed usage is not supported`；统一走 `BushingStiffness/DampingCoefficients` 子容器（§M.5a） |
| 在 builder 实例上 0 参调用枚举访问器（`b.Types()` / `d.AttachmentType()` / `b.HoleDepthOptions()`） | 抛 `NXException: instances of NX enums can not be created`，**当场中断整个 journal**（后续诊断全丢）；枚举一律用模块级类（§M.5a 末） |
| 取连杆位姿（角度+平移分量） | 返回 16 值=完整 4×4 行主序，平移在索引 3/7/11；取前 12 即 R 三行+平移，R22（索引 10）恒 1.0 可作布局自检（§M.7） |
