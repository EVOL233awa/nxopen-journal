# 运动仿真域（NX Motion，NX 12 批处理）

NXMotion = 机构运动学与动力学仿真：建运动副 → 加驱动/载荷 → 求解 → 读结果。
前置：SKILL.md §1 铁律、§3 骨架。

公共约定：

```python
import NXOpen
import NXOpen.Motion as M

ufs = NXOpen.UF.UFSession.GetUFSession()
VC = ufs.Motion.VectorComponent          # 结果分量枚举
RF = ufs.Motion.ReferenceFrame           # 参考系枚举


def set_expr(part, expr, value):
    """写表达式。部分 builder 只写 RightHandSide 不生效，需再走 Expressions.Edit。"""
    expr.RightHandSide = str(value)
    try:
        part.Expressions.Edit(expr, str(value))
    except Exception:
        pass
```

## M. 运动仿真

### M.1 建立仿真并进入 .sim 部件

```python
ms = theSession.MotionSession
ms.CreateSimulation(master_part)              # master 已打开
sim_part = None
for p in theSession.Parts:                    # 按后缀认领 .sim
    if p is not None and (p.FullPath or "").lower().endswith(".sim"):
        sim_part = p; break
ms.InitializeSimulation(sim_part)
ufs.Part.SetDisplayPart(sim_part.Tag)
theSession.Parts.SetWork(sim_part)
mm = sim_part.MotionManager                   # .Links/.Joints/.JointDrivers
                                              # /.MotionSolutions/.ScalarTorques
```

- 结果只在 `.sim` 读：`links`/`joints` 属 sim_part；`theSession.Parts` 直接迭代（无 `ToArray()`，SKILL.md §3 坑位 4）。
- `.sim` 位于 `<master 目录>\<master 基名>\motion_1.sim`；重跑须连该子目录清理，否则生成 `motion_2.sim` 或认领旧仿真。

### M.2 Link（构件）与质量属性

无几何 Link：`Geometries` 留空 + `MassType = UserDefined`。

```python
lb = mm.Links.CreateLinkBuilder(M.Link.Null)          # 空对象用 .Null
lb.Name = "L_" + cn
lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
set_expr(sim_part, lb.MassProperty.MassExpression, "%.6f" % MASS[cn])
for ax in ("IxxExpression", "IyyExpression", "IzzExpression"):
    set_expr(sim_part, getattr(lb.MassProperty, ax), "%.4f" % INERT[cn])
for ax in ("IxyExpression", "IxzExpression", "IyzExpression"):
    set_expr(sim_part, getattr(lb.MassProperty, ax), "0.0")
lb.MassProperty.MassCenter = cm[cn]                   # 须 NXOpen.Point
link = lb.Commit(); lb.Destroy()
```

- `MassCenter` 要 `NXOpen.Point`（非 `Point3d`）；传错报 `Expecting NXOpen.Point type`，被 try/except 吞掉则质心落原点、反力全错；点须先建。
- `Ixx`/`Iyy`=0 而 `Izz`≠0 → 惯性张量非正定，面外反力 500~900 N 伪尖峰；取各向同性 `Ixx=Iyy=Izz=m·L²/12`。自检：质心全在原点即中招。

### M.3 运动副（转动副 / 滑动副）

```python
zd = sim_part.Directions.CreateDirection(pts[pn], NXOpen.Vector3d(0.0, 0.0, 1.0))  # 轴线
jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
jd = jb.JointDefine
jd.JointType = M.JointDefine.Type.Revolute
jd.FirstLink  = links[comp_a]      # Motion.Link，非 Component
jd.SecondLink = links[comp_b]
jd.FirstOrigin = pts[pn]           # NXOpen.Point
jd.FirstVector = zd                # NXOpen.Direction
jd.Name = jn                       # 必填
joint = jb.Commit(); jb.Destroy()
ms.FixLinkToGround(links[ground_cn])          # 接地件
```

`JointDefine` 另供 `SecondOrigin`/`SecondVector`、`FirstCsys`/`SecondCsys`/`FirstMatrix`、`ExcludeRxConstraint`、`AxisType`、`LimitsDefined`；枚举在 `ufs.Motion`（`MotionType`/`VectorComponent`/`ReferenceFrame`/`FuncResultType`/`FuncComponentType`/`FuncRefFrameType`），`NXOpen.UF.UFMotion` 不可导入，`.NET` 枚举挂类上（SKILL.md §3 坑位 9/10）。

Slider：平移轴=关节局部 z 轴，两组向量对齐导轨，缺第二组报 `A NULL value was encountered`。r40/l120/e20：y 恒 20.000000 mm，x 偏差 ≤0.001316 mm，杆长 ≤0.001303 mm。

```python
jd.JointType = M.JointDefine.Type.Slider
jd.FirstLink, jd.SecondLink = links["FRAME"], links["SLIDER"]
jd.FirstOrigin = pts["B"]
jd.FirstVector = xdir                 # 关节局部 z 轴对到导轨 +X
jd.SecondOrigin = pts["B"]            # 与 FirstOrigin 同点
jd.SecondVector = xdir
jd.Name = "J_S"
```

装配 `Constraint.Type.Slider` 不可用（`not valid for this operation`），只在 Motion 域建；`Perpendicular` 须给第二组，`Atpoint`/`Cylindrical`/`Planar`/`Spherical`/`Universal` 给齐两组可提交。

Slider 可用 `TranslationAllowed`/`RotationAllowed` 显式限定允许的平移/转动。

### M.4 驱动

```python
jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
jdb.Name = "DRV_CRANK"                       # 必填
jdb.Joint.Value = joints["J_A"]
op = jdb.DriverMultiOperations.MotionEulerAngle1
op.TypeOption = M.DriverOperation.Type.Constant
op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
set_expr(sim_part, op.VelocityExpression, "%.1f" % OMEGA_DEG_S)   # deg/s
jdb.Commit(); jdb.Destroy()
```

- `OMEGA_DEG_S = rpm×6`（65 r/min→390 deg/s）；`VelocityExpression` 为 deg/s（按 rad/s 差 57.2958 倍），判据：360 deg/s、1 s、360 步→每帧 1.000000°。
- 转向：NX Euler 驱动的正值绕 +Z 为顺时针（+360 deg/s 使曲柄角递减）；不要按右手定则推断，换轴后以 frame 1（0 基）符号为准。行主序；角度用绝对角（相对角 `atan2(r[4],r[0])` 有相位伪偏差）。
- 绝对角=有符号物理角，勿 `abs()`/取反（与解析式冲突，致 14 mm 假偏差）；取 `T·[A_design,1]` 销坐标再 `atan2`。

### M.4a 齿轮连接件（Gear Coupler）

两转动副按传动比耦合（定轴轮系），不建齿面接触：

```python
cb = mm.Couplers.CreateCouplerGearBuilder(M.CouplerGear.Null)
cb.Name = "GEAR_MESH_i2"
cb.FirstJoint.Value = joints["J_IN"]       # 直接赋值无效，写 .Value
cb.SecondJoint.Value = joints["J_OUT"]
cb.FirstRadiusExpression.RightHandSide = "20.0"
cb.SecondRadiusExpression.RightHandSide = "40.0"
cb.RatioExpression.RightHandSide = "-0.5"  # 外啮合取负
cb.ContactPoint = sim_part.Points.CreatePoint(NXOpen.Point3d(20.0, 0.0, 60.0))
cb.Validate(); cb.Commit(); cb.Destroy()
```

`FirstRadius`/`SecondRadius` = 分度圆半径；`RatioExpression` 与半径比不一致时以谁为准未验证——两者写同一比，用输出转速判据。减速器 m=2、z20/z40：60 r/min → −30.0000 r/min，`RATIO_OUT_IN=−0.500000`。

### M.5 载荷：标量力矩（ScalarTorque）

```python
stb = mm.ScalarTorques.CreateScalarTorqueBuilder(M.ScalarTorque.Null)
stb.Name = "ST_J_D"
stb.TorqueType = M.ScalarTorqueBuilder.ScalarTorqueType.Joint   # 作用于运动副
stb.Joint.Value = joints["J_D"]
stb.ValueType = M.ForceValueTypes.Constant
stb.ApplicationType = M.ScalarTorqueBuilder.AppType.ActionReaction
set_expr(sim_part, stb.ValueExpression, "%.6f" % val)
stb.Commit(); stb.Destroy()
```

- mm 件 `ValueExpression` 按 **N·mm** 解释，非 N·m。判据：1608 → J_B=34.47 N（手算 34.93 N）；1.608 → 0.63 N；反力小 1000 倍先查此（`NM_TO_NMM=1000.0`）。
- NX12 `ValueExpression` 不能引用运动状态函数：`WZ`/`IF`/`TANH`/`SGN` 报 syntax error → `τ=−Mf·sgn(ω)` 无法表达。`CreateFunction` 注册的函数取不到引用（`stb.Function` 为 `None`）。变通：按 ω 符号拆 ±sgn 两工况；精确符号载荷走外部静定解算器（§M.8）。

### M.5a 连接件：弹簧 / 阻尼 / 衬套

`Springs`/`Dampers`/`Bushings`；无 `ScalarSprings` 等。

**弹簧**：

```python
b = mm.Springs.CreateSpringBuilder(M.Spring.Null)
b.Name = "PT_SPRING"
# 不设 AttachmentType：实例只读，赋值/读取均报错；不设也可提交
b.ActionLink.Value  = links[0]            # 只读容器，写 .Value
b.ReactionLink.Value = links[1]
b.ActionPoint   = pts[0]                  # 点/向量直接可写
b.ReactionPoint = pts[1]
set_expr(sim_part, b.StiffnessExpression, "10.0")
b.Validate(); b.Commit(); b.Destroy()
```

另可写 `CoefficientExpression`/`FreeLengthExpression`。

**阻尼**：

```python
d = mm.Dampers.CreateDamperBuilder(M.Damper.Null)
d.Name = "PT_DAMPER"
d.ActionLink.Value   = links[0]      # SelectObject，写 .Value
d.ReactionLink.Value = links[1]
d.ActionPoint, d.ReactionPoint = pts[0], pts[1]
set_expr(sim_part, d.CoefficientExpression, "1.0")
d.CoefficientType = NXOpen.Motion.ConnectorCoefficientTypes.Constant   # 必需项
d.Validate(); d.Commit()
```

`AttachmentType`（`M.ConnectorBuilderAttachmentType`：`Link`/`RevoluteJoint`/`SliderJoint`）不需设。

**衬套**：

```python
b = mm.Bushings.CreateBushingBuilder(M.Bushing.Null)
b.Name                            # AttributeError：无 Name
b.BushingDefine.Name = "PT_BUSH"   # 名称/连接在子对象
b.BushingDefine.ActionLink.Value = links[0]
b.BushingDefine.ReactionLink.Value = links[1]
b.BushingDefine.ActionPoint / ReactionPoint
b.BushingType = b.BushingTypes.General          # 枚举挂实例；M.BushingTypes 不存在
comp = b.BushingStiffnessCoefficients.GeneralTranslationalStiffnessCoefficients
tc   = b.BushingStiffnessCoefficients.GeneralTorsionalStiffnessCoefficients
for c in (comp, tc):
    for ax in ("X", "Y", "Z"):
        set_expr(sim_part, getattr(c, ax + "Expression"), "100.0")
    c.CoefficientsType = c.XCoefficientsType = NXOpen.Motion.ConnectorCoefficientTypes.Constant
# Orientation 要 NXMatrix（给 Direction 报 Expecting NXOpen.NXMatrix type）
xf   = sim_part.Xforms.CreateXformByPointXDirZDir(
           pts[0], xd, zd, NXOpen.SmartObject.UpdateOption.WithinModeling, 1.0)
csys = sim_part.CoordinateSystems.CreateCoordinateSystem(
           xf, NXOpen.SmartObject.UpdateOption.WithinModeling)
b.BushingDefine.Orientation = csys.Orientation
b.Validate(); b.Commit()
```

- 缺 `Orientation` → `A NULL value was encountered`；`Csys`/`Direction` 默认 `NoneType`。
- 系数容器：`GeneralTranslational*`/`GeneralTorsional*`（`CoefficientsType`/`X|Y|ZExpression`/`CurveProfile`/`Function`）、`Cylindrical*`（`Radial`/`Longitudinal`/`Torsional`/`Conical`）、`Spherical*`（`Radial`/`Conical`）；通用与圆柱/球形型不可混填；旧族 `BushingCoefficients` deprecated。
- 枚举：`BushingDefineOrientationTypes` 只列 `value`；`AngleCalculationOption`=`LargeAngle`/`SmallAngle`；`ForceCalculationOption`=`Abc`/`Bab`/`Standard`。
- 枚举访问器 0 参调用抛 `NXException: instances of NX enums can not be created` 并中断 journal；用模块级类。

### M.5b 后处理 / 干涉 / 自由度计数

`mm.PostProcess`：包络/序列/动画/干涉/测量/轨迹。

- `AskGrueblerCount()`：2 Link+1 转动副 → **7**（`6n−5j` 粗计数，非自由度；见 §M.8）。
- `InitInterferenceStruct()` 0 参（out 参数即返回值），字段 `Solid1`/`Solid2`；`CreateInterference(...)` 抛 `SystemError` → 用帧变换后处理。

### M.5c 驱动的种类上限

`jdb.DriverMultiOperations` 只有 `MotionEulerAngle1`/`MotionPointOnCurve`/`MotionTranslationZ`；超出回退 GUI 或运动状态函数（§M.5）。

`MotionTranslationZ`：沿**关节局部 z 轴**，非全局 Z；正速度沿 **−z_joint**，单位 = 部件长度单位/秒。判据：局部 z 对齐 +X、`VelocityExpression=10.0` 跑 1 s → `Tx=-10.0`；沿 +X 传负值。

### M.6 求解

```python
sb = mm.MotionSolutions.CreateSolutionBuilder(M.MotionSolution.Null)
sb.Name = "SOL_CASE"                         # 必填
sb.SolutionType = M.MotionSolutionBuilder.SolutionTypes.Normal
sb.AnalysisType = M.MotionSolutionBuilder.AnalysisTypes.Dynamic
sb.Step = nstep
set_expr(sim_part, sb.TimeExpression, "%.3f" % t_end)     # 终止时间
# sb.GravityVector 需要 NXOpen.Direction
sol = sb.Commit(); sb.Destroy()
sol.SolveNormalRunSolution()
```

`dt = t_end/nstep`；帧数 = nstep+1；帧索引 0 基，范围 `0..nfr-1`。**帧 0 = t=0 设计位姿（单位阵）**；`range(1,nfr+1)` 漏帧 0 且越界查询 `nfr`（返回末帧副本/归零值，误读为“末帧重复”）。

```python
for fr in range(nfr):          # 0 .. nfr-1，含 t=0 与 t=t_end
    r = ufs.Motion.AskLinkTransfromForGivenFrame(link.Tag, fr)
```

- 以 36 号用例（T=2 s、720 步）为例：`nfr=721`，frame 0 单位阵、frame 720 = t=2 s 末态，全有效，Δθ=0.5°/帧；一般地 `frame k ↔ t=k·T/nstep`。
- 不无条件剔尾帧；`0..nfr-1` 内相邻增量≈0 或位姿跳回设计态时才丢弃。
- 帧 k ↔ `t=k·dt`（0 基）；journal 内端点速度用单边差分，端点不参与精度判据。

### M.7 结果提取

```python
nfr = int(ufs.Motion.AskNumberOfAnimationFrames())

# 反力 / 力矩：返回 (帧数, [值...]) 二元组，取 [1]
r = ufs.Motion.AskForceResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)
r = ufs.Motion.AskTorqueResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)  # 驱动力矩

# 构件位姿（16 个 double = 4x4 行主序）
r = ufs.Motion.AskLinkTransfromForGivenFrame(link.Tag, frame)
```

- `AskLinkTransfromForGivenFrame`：2 参优先，3 参 `(tag, frame, [0.0]*12)` 备用；`frame` 0..nfr-1，帧 0=t=0。
- 16 值=4×4 **行主序**，平移 **3/7/11**；R22（10）恒 1.0、Tz（11）自检。绕轴角（相对设计位姿）：Z `atan2(r[4],r[0])`、Y `atan2(r[2],r[0])`、X `atan2(r[9],r[5])`；要绝对物理角，按 §M.4 取 `T·[设计点,1]` 再 `atan2`。
- 列主序（12/13/14）→ 杆长偏差 14.17 mm、铰点不共点；行主序 → 0.0013 mm。杆长/共点=判别器。
- `AskVelocity/AccelerationResults` 恒 0.0（静默失败），签名 `(tag, MotionType.ROTATION, VC.MAGNITUDE, RF.ABSOLUTE)`。
- 自算 ω/α：方位角中心差分，平面 `atan2(R[1,0],R[0,0])`；journal 内无 numpy，中心差分手写，端点用单边差分且不参与精度判据；宿主侧绘图可用 `np.gradient(..., edge_order=2)`。
- 线速度：平移 3/7/11 差分；内部帧 ≤0.0032 mm/s；**frame 1 含首步瞬态（0.2366 mm/s），判据从 frame 2 起**；端点单边差分不可判精度。
- 用 `range(nfr)`；1..nfr 越界返回末帧副本/归零值。勿用中位步长剔帧（四杆 dψ/dθ 0~0.565 rad/rad）。
- 传动角：首帧变换逆投设计态方向到各 Link 局部系（模长=杆长），各帧 R 旋转后求夹角。
- 帧变换：`world_k=T_k·[x_design,y_design,0,1]`，非先 T₀ 求逆再变换（后者铰点偏差 1.7 mm，改正后 2.4e-5 mm）。旋转不变量验不了平移；用共享铰点逐帧共点自检（≤1e-3 mm）。
- 差分前手写 unwrap（±180° 卷绕造假速率 357.8°/帧）；宿主侧可用 `np.unwrap`。

### M.8 静不定与反力伪影（本域最重要的一条）

**转动副描述平面机构静不定，反力不可直接用。**

平面 5 构件×7 转动副：`6×5−5×7=−5`。NX 打印 `Redundant constraints will be removed automatically, results may be not as expected.`。摇杆极限位（共线、雅可比近奇异）附近消去方式跳变，反力逐帧抖动（`J_D` 122/185 N，Z 向 ~1/~184 N）。

判伪：步长加密 4 倍（1080→4320）尖峰位置与幅值不变 → 冗余约束数值伪影；尖峰在死点邻域。

对策：静定平面刚体动力学模型——每构件 3 方程（2 平动+1 转动）→ `3n`；六杆 5 构件 15 方程/15 未知量（7 铰点×2+驱动力矩）；校核：解析偏差 `1e-15`、能量守恒 1.001(μ=0.4)/1.000(μ=0.8)、与 NX 非死点区偏差 0.02%~3.4%；坐标统一 SI，用实际 μ。

Kinematics 仍可用 NX（位姿/摆角/传动角偏差 ≤0.15°），只有反力不可信。四杆也静不定：`6×5−5×4=−2`，日志打印 `Starting redundant constraint check...`；判定按 6-3-5 空间计数；四杆反力只可验 API 通路。

### M.9 批处理多工况（并行）

`run_journal.exe` **不接收命令行参数** → 用环境变量传配置路径，输出名按配置名区分：

```python
CFG = os.environ.get("RUN141_CFG") or os.path.join(RESDIR, "load_case.json")
```

加 env 后可并行跑不同工况（独立进程）。Git Bash：`cd` 到 journal 目录后直接 `"<技能>\scripts\run_journal_batch.bat" <journal.py>`；**不要** `cmd //c "....bat a b"` 传尾参（吞参，静默不执行、退出码 0 无产物）。

### M.10 回归

```bash
python scripts\check_journal.py scripts\tests\18_motion_sim.py
scripts\run_journal_batch.bat C:\abs\...\scripts\tests\18_motion_sim.py C:\abs\...\scripts\tests\parts
scripts\run_journal_batch.bat C:\abs\...\scripts\tests\23_motion_connectors.py C:\abs\...\scripts\tests\parts
scripts\run_journal_batch.bat C:\abs\...\scripts\tests\36_motion_slider.py C:\abs\...\scripts\tests\parts
```

- **36 号**（滑动副）：r40/l120/e20，720 步；标志 `TEST36_DONE`+`BENCH_PASS`。判据：`0..720` 共 721 帧、x 偏差 ≤0.01 mm、y 恒 e、杆长 ≤0.01 mm、内部帧速度 ≤0.01 mm/s；杆长判据兼口径探针。
- **18 号**：`TEST18_DONE`+`BENCH_PASS`（非退出码，SKILL.md §6）。
- **23 号**：`TEST23_DONE`，14 项全过（连接件 0→1、衬套负对照、`NXMatrix`、结构体 out 参数、Gruebler 整数、驱动三项上限）。

用例 18：四杆 AB20/BC60/CD40/AD70（Grashof，AB 曲柄），检查速率+恒速、摆角 `60.0282°`（解析 `60.0218°`）、换向 2 次、反力通路；期望值来自外部解析解。反向验证：驱动 `360→2π` → 速率/摆角/换向 FAIL、反力 PASS；`CD 40→50` → 仅摆角 FAIL（`47.74°`）。

### 坑位对照（遇到 → 怎么做）

| 遇到 | 怎么做 |
| --- | --- |
| `AskVelocity/AccelerationResults` 全 0.0 | 静默失败；用帧变换中心差分 |
| `ValueExpression` 写 `WZ`/`IF`/`TANH`/`SGN` 报 syntax error | 符号载荷走外部解算器 |
| `CreateFunction()` 注册后取不到 | 用内置函数或运动状态函数 |
| `MassCenter` 传 `Point3d` 报类型错 | 传 `NXOpen.Point`；被吞则质心落原点 |
| NX 反力做强度校核 | 平面转动副静不定，死点邻域 5~10 倍伪尖峰；用静定解算器（§M.8） |
| 无几何 Link 用包络/干涉 | 无体可扫掠；用帧变换后处理 |
| `CreateInterference()` | 抛 `SystemError`；只有 `InitInterferenceStruct()` |
| `ScalarSprings`/`ScalarDampers`/`ScalarBushings` | 用 `Springs`/`Dampers`/`Bushings`（§M.5a） |
| 直接赋值 `b.ActionLink`、实例取 `AttachmentType` | 写 `.Value`；枚举在类上（§M.5a） |
| 阻尼器建不出来 | 缺 `CoefficientType = Constant`（§M.5a） |
| 衬套 Commit 报 `A NULL value` | 缺 `Orientation`，要 **NXMatrix**（§M.5a） |
| 衬套旧族/混填系数型 | deprecated / `mixed usage is not supported`（§M.5a） |
| 实例上 0 参调枚举访问器 | `instances of NX enums can not be created`（§M.5a） |
| 取连杆位姿 | 16 值=4×4 行主序，平移 3/7/11；R22（10）恒 1.0（§M.7） |
| 列主序解读，杆长/共点不符 | 平移误取 12/13/14 致 14 mm 漂移；改取 3/7/11（§M.7） |
| `range(1,nfr+1)` 遍历 | 0 基 `0..nfr-1`，帧 0 = t=0（§M.6） |
| 装配建 `Constraint.Type.Slider` | `not valid for this operation`；只在 Motion 域建（§M.3） |
| 滑动副 Commit 报 `A NULL value` | 补 `SecondOrigin`/`SecondVector`（§M.3） |
| `cb.FirstJoint = joint` 不生效 | `SelectObject` 写 `.Value`（§M.4a） |
| 齿轮传动比不对 | `RatioExpression` 与半径比同值；外啮合取负（§M.4a） |
