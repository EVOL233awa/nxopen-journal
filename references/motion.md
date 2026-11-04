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

- 结果只在 `.sim` 读：`links`/`joints` 属 sim_part；`theSession.Parts` 直接迭代（无 `ToArray()`，SKILL.md §3 路线约束 4）。
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
- 取各向同性 `Ixx=Iyy=Izz=m·L²/12`。⚠ "`Ixx`/`Iyy`=0 而 `Izz`≠0 → 面外反力伪尖峰"**不成立**：平面惯量置 0 与非各向同性设置的反力结果在 6 位小数内完全一致，别把它当失败模式。自检：质心全在原点即中招（`MassCenter` 被 try/except 吞掉 → 落原点）。

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
jd.Name = jn                       # 可省：NX 自动命名 J002（要按名字查找才写）
joint = jb.Commit(); jb.Destroy()
ms.FixLinkToGround(links[ground_cn])          # 接地件
```

`JointDefine` 另供 `SecondOrigin`/`SecondVector`、`FirstCsys`/`SecondCsys`/`FirstMatrix`、`ExcludeRxConstraint`、`AxisType`、`LimitsDefined`；枚举在 `ufs.Motion`（`MotionType`/`VectorComponent`/`ReferenceFrame`/`FuncResultType`/`FuncComponentType`/`FuncRefFrameType`），`NXOpen.UF.UFMotion` 不可导入，`.NET` 枚举挂类上。

Slider：平移轴=关节局部 z 轴，两组向量对齐导轨（`SecondOrigin` 与 `FirstOrigin` 同点、`SecondVector` 同向）。**缺第二组也能提交并求解**（不报 `A NULL value was encountered`），但几何是否如预期须用位姿/自由度判据核，不能只看 `Commit` 成功。判据：非滑动方向坐标恒定，x 与杆长偏差 ≤0.01 mm。

```python
jd.JointType = M.JointDefine.Type.Slider
jd.FirstLink, jd.SecondLink = links["FRAME"], links["SLIDER"]
jd.FirstOrigin = pts["B"]
jd.FirstVector = xdir                 # 关节局部 z 轴对到导轨 +X
jd.SecondOrigin = pts["B"]            # 与 FirstOrigin 同点
jd.SecondVector = xdir
jd.Name = "J_S"
```

装配 `Constraint.Type.Slider` 不可用（`not valid for this operation`，与 `Hinge`/`Cylindrical`/`Ball` 一批 internal-only，见 assembly.md §A.2），铰链只在 Motion 域建。

`JointDefine.Type` 另列 `Perpendicular`/`Atpoint`/`Cylindrical`/`Planar`/`Spherical`/`Universal` 等（文档原口径：`Perpendicular` 须给第二组，其余给齐两组可提交）——⚠ 整句**未全验**：`Perpendicular` 的三种给法（给齐两组 / 只给第二向量 / 给第二矩阵）均 `Commit` 成功，其余类型**未验证**。第二组本身**不是提交门槛**：`Perpendicular` 三种给法都能提交；Slider 不给 `SecondOrigin`/`SecondVector` 也能提交并求解（两处是不同对象，别合并读）。

关节定义这一族的 `A NULL value was encountered` 出自**矩阵入口** `FirstMatrix` 那一支，不是"缺第二组"（衬套缺 `Orientation` 会报同一文本，是另一处，见 §M.5a）。

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
- 转向：NX Euler 驱动的正值绕 +Z 为顺时针（+360 deg/s 使曲柄角递减）；不要按右手定则推断，换轴后以 frame 1（0 基）符号为准。行主序；相对角 `atan2(r[4],r[0])` 的相位偏移是**常数**（本机构恒 97.18°），在摆角/速率差分中完全抵消——"相位伪偏差"不会污染派生量，"必须用绝对角"只是可读性选择，不是判据需要。
- 绝对角=有符号物理角，勿 `abs()`/取反（与解析式冲突，造成假偏差）；取 `T·[A_design,1]` 销坐标再 `atan2`。

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

`FirstRadius`/`SecondRadius` = 分度圆半径；**半径比为准、`RatioExpression` 被忽略**：半径 20:40 时写 `-0.3`，输出仍按 −0.5 走；比值与自己给的不一致也不报错。仍建议两者写同一比，用输出转速判据。

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

- mm 件 `ValueExpression` 按 **N·mm** 解释，非 N·m。判据：反力与手算同量级；反力小 1000 倍先查此（`NM_TO_NMM=1000.0`）。
- NX12 `ValueExpression` 不能引用运动状态函数：`WZ`/`IF`/`TANH`/`SGN` 报 syntax error → `τ=−Mf·sgn(ω)` 无法表达。`CreateFunction` 注册的函数取不到引用（`stb.Function` 为 `None`）。变通：按 ω 符号拆 ±sgn 两工况；精确符号载荷走外部静定解算器（§M.8）。

### M.5a 连接件：弹簧 / 阻尼 / 衬套

`Springs`/`Dampers`/`Bushings`；无 `ScalarSprings` 等。

**弹簧**：

```python
b = mm.Springs.CreateSpringBuilder(M.Spring.Null)
b.Name = "PT_SPRING"
# 不设 AttachmentType（可省）：赋值报 AttributeError（只读），读取正常返回枚举类
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
d.CoefficientType = NXOpen.Motion.ConnectorCoefficientTypes.Constant   # 可省：缺它也能 Validate+Commit
d.Validate(); d.Commit()
```

⚠ 阻尼/衬套真正的失败条件是 `ActionPoint`/`ReactionPoint` **两点重合**（退化几何）→ `NXException: An invalid tag was passed to a function`，与 `CoefficientType` 无关。

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
- 枚举：`BushingDefineOrientationTypes`=`Csys`/`Vector`；`AngleCalculationOption`=`LargeAngle`/`SmallAngle`；`ForceCalculationOption`=`Abc`/`Bab`/`Standard`。
- 枚举访问器 0 参调用抛 `NXException: instances of NX enums can not be created` 并中断 journal；用模块级类。

### M.5b 后处理 / 干涉 / 自由度计数

后处理类是 **`theSession.MotionSession.PostProcess`**（`theSession` 上有该属性；`sim_part.MotionManager` 上**没有**）。包络/序列/动画/干涉/测量/轨迹的接口名在，但**不能当配方直接用**：`CreateSequence()` 抛 `SystemError: ... returned NULL without setting an error`，`CreateEnvelope()` 要 `IPostControl`（journal 里取不到，传 `None` 报 `Expecting NXOpen.Motion.IPostControl type, found NoneType`）→ 结果提取走 §M.7 的帧变换；干涉走本节下面的 UF 路线（`InitInterferenceStruct`）。

- `AskGrueblerCount()`：`6n−5j` 粗计数，非自由度；见 §M.8。
- `InitInterferenceStruct()` 0 参（out 参数即返回值），字段 `Solid1`/`Solid2`；`CreateInterference(...)` 抛 `SystemError` → 用帧变换后处理。

### M.5c 驱动选型

`jdb.DriverMultiOperations` 用 `MotionEulerAngle1`/`MotionPointOnCurve`/`MotionTranslationZ`；其余驱动走 GUI 或运动状态函数（§M.5）。

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

`dt = t_end/nstep`；帧数 = nstep+1；帧索引 0 基，范围 `0..nfr-1`。**帧 0 = t=0 设计位姿（单位阵）**；`range(1,nfr+1)` 漏帧 0 且越界查询 `nfr`（返回**设计态/单位阵**，不是末帧副本，误读为"末帧重复/归零"）。

```python
for fr in range(nfr):          # 0 .. nfr-1，含 t=0 与 t=t_end
    r = ufs.Motion.AskLinkTransfromForGivenFrame(link.Tag, fr)
```

- 帧 k ↔ `t=k·T/nstep`（0 基），末帧 t=T 有效；不无条件剔尾帧，只有相邻增量≈0 或位姿跳回设计态时才丢弃。
- journal 内端点速度用单边差分，端点不参与精度判据。

### M.7 结果提取

```python
nfr = int(ufs.Motion.AskNumberOfAnimationFrames())

# 反力 / 力矩：返回 (帧数, [值...]) 二元组，取 [1]
r = ufs.Motion.AskForceResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)
r = ufs.Motion.AskTorqueResults(joint.Tag, VC.MAGNITUDE, RF.ABSOLUTE)  # 驱动力矩

# 构件位姿（16 个 double = 4x4 行主序）
r = ufs.Motion.AskLinkTransfromForGivenFrame(link.Tag, frame)
```

- `AskLinkTransfromForGivenFrame`：**只有 2 参形式** `(tag, frame)`；3 参 `(tag, frame, [0.0]*12)` **不存在**，传第三参抛 `SyntaxError: Function takes 2 arguments, 3 passed.`。`frame` 0..nfr-1，帧 0=t=0。
- 16 值=4×4 **行主序**，平移 **3/7/11**；`r[10]` 只在**绕 Z 转的平面机构**里恒 1.0；绕 Y/X 时 `r[10]=cosθ`（本项目几何上恰读到 −2.7e-8），别按 0/1 判形态、别当通用自检；`Tz`（11）同理只在平面机构为 0。绕轴角（相对设计位姿）：Z `atan2(r[4],r[0])`、Y `atan2(r[2],r[0])`、X `atan2(r[9],r[5])`；要绝对物理角，按 §M.4 取 `T·[设计点,1]` 再 `atan2`。
- 列主序（12/13/14）→ 杆长与铰点共点严重不符；行主序 → 一致。杆长/共点=判别器。
- `AskVelocity/AccelerationResults(tag, MotionType.ROTATION|TRANSLATION, VC.MAGNITUDE, RF.ABSOLUTE)` 对 **Link 与 Joint tag 都返回逐帧值**（曲柄 ROTATION 6.28334 rad/s 对 360 °/s 指令；曲柄质心 TRANSLATION 62.83 mm/s = ωr；ω²r = 394.78 mm/s²），读数为 0 的只有**物理上就该为 0** 的情形——接地件与驱动关节。**四个实参缺一不可**：缺 `MotionType` 的 3 参写法抛 `type object 'NXOpen.UF.MotionVectorComponent' has no attribute 'ROTATION'`。帧变换中心差分可作交叉校验（见下），但不必当唯一路线。
- 自算 ω/α：方位角中心差分，平面 `atan2(R[1,0],R[0,0])`；journal 内无 numpy，中心差分手写，端点用单边差分且不参与精度判据；宿主侧绘图可用 `np.gradient(..., edge_order=2)`。
- 线速度：平移 3/7/11 差分；内部帧接近 0；**frame 1 含首步瞬态，判据从 frame 2 起**；端点单边差分不可判精度。
- 用 `range(nfr)`；越界查 `nfr` 返回**设计态/单位阵**（不是末帧副本）、负索引返回垃圾值。勿用中位步长剔帧（会误删变速段）。
- 传动角：首帧变换逆投设计态方向到各 Link 局部系（模长=杆长），各帧 R 旋转后求夹角。
- 帧变换：`world_k=T_k·[x_design,y_design,0,1]`（直接乘设计点即可；"先 T₀ 求逆再变换引入铰点偏差"**不成立**——两条路径共点误差逐位相同）。旋转不变量验不了平移；用共享铰点逐帧共点自检——⚠ **阈值随步长变化，不能写成固定值**：360/720/1440 步分别 1.5e-3 / 3.9e-4 / 9.7e-5 mm，判据须与步长一起定。
- 差分前手写 unwrap（±180° 卷绕会造假速率）；宿主侧可用 `np.unwrap`。

### M.8 静不定与反力伪影（本域最重要的一条）

**转动副描述平面机构静不定，反力不可直接用。**

平面 5 构件×7 转动副：`6×5−5×7=−5`。NX 打印 `Redundant constraints will be removed automatically, results may be not as expected.`。摇杆极限位（共线、雅可比近奇异）附近消去方式跳变，反力逐帧抖动数倍。

尖峰在死点邻域（摇杆极限位、雅可比近奇异）出现。⚠ "步长加密后尖峰位置与幅值不变 → 判为数值伪影"这条判伪规则**不能用**：360→720→1440 步加密时 J_B 尖峰为 `127.8658 @ t=0.7333` → `105.8240 @ t=0.9847` → `105.3866 @ t=0.7299`（幅值降 17.5%，且峰位在 720 步跳到 0.985、1440 步又回 0.730）——位置与幅值都不是不变量，按它判会把真峰值也当伪影。

对策：静定平面刚体动力学模型——每构件 3 方程（2 平动+1 转动）→ `3n`；六杆 5 构件 15 方程/15 未知量（7 铰点×2+驱动力矩）；校核：解析偏差接近机器精度、能量守恒、与 NX 非死点区偏差在个位百分比内；坐标统一 SI，用实际 μ。

Kinematics 仍可用 NX（位姿/摆角/传动角偏差 ≤0.15°），只有反力不可信。四杆也静不定：`6×3−5×4=−2`，日志打印 `Starting redundant constraint check...`；判定按 6-3-5 空间计数；四杆反力只可验 API 通路。

### M.9 批处理多工况（并行）

`run_journal.exe` 只接收 `.bat` 传入的 journal 路径，**不转发额外参数** → 用环境变量传配置路径，输出名按配置名区分：

```python
CFG = os.environ.get("RUN141_CFG") or os.path.join(RESDIR, "load_case.json")
```

加 env 后可并行跑不同工况（独立进程）。Git Bash：`cd` 到 journal 目录后直接 `"<技能>\scripts\run_journal_batch.bat" <journal.py>`。**传尾参没问题**：`cmd //c "....bat <journal> <workdir> EXTRA"` 照常执行、有产物、退出码 0（多余参数被 bat 丢弃，不会静默不执行）。两个真坑：① **单斜杠** `cmd /c` 且**不加** `MSYS_NO_PATHCONV=1` 时退出码 1、报错、无产物（成因未确证）；② 一旦加了 `MSYS_NO_PATHCONV=1`，参数不再被改写，bat/journal/workdir 必须写成 `C:\...` 形式——写成 `/c/...` 形式时 cmd 报"系统找不到指定的路径。"且无任何产物。可用写法：`MSYS_NO_PATHCONV=1 cmd /c "<C:\abs\...\run_journal_batch.bat> <C:\abs\...\journal.py> <C:\abs\...\workdir>"`。

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

用例 18：四杆 AB20/BC60/CD40/AD70（Grashof，AB 曲柄），检查速率+恒速、摆角 `60.0282°`（解析 `60.0218°`）、换向 2 次、反力通路；期望值来自外部解析解。反向验证：驱动 `360→2π` → **摆角/换向 FAIL、速率 PASS**（速率判据的期望值由 `OMEGA_DEG_S` 现算）、反力 PASS；`CD 40→50` → 仅摆角 FAIL（`47.74°`）。

### 结果读取约束（跨域通用）

- 帧索引 0 基 `0..nfr-1`，帧 0 = t=0；不要用 `range(1,nfr+1)`。
- 位姿 16 值是 4×4 **行主序**，平移取 3/7/11；取 12/13/14 会得到与该连杆**设计原点距**同量级的偏差（40/60/63 mm 级，随杆长而变），不是固定的"14 mm 级"。
- `MassCenter` 传 `NXOpen.Point`，不是 `Point3d`；被 try/except 吞掉会让质心落原点。
- `AskVelocity/AccelerationResults` 对 Link/Joint 都返回逐帧值（接地件与驱动关节为 0 属物理正确）；4 参签名缺 `MotionType` 会 `AttributeError`（§M.7）。
- 平面转动副静不定，反力不做强度判据；用静定解算器（§M.8）。
- 步长扫描（0.5/1/2°）：摇杆摆角 60.0234/60.0282/60.0186°，极差 0.0096°，按 `60.02±0.05°` 判；反力 max 相对极差 J_A 60.7%、J_B 89.8%，跨步长不可比，只做 `NSTEP=360` 的同一步数快照（同一步数复跑 6 位小数一致）。
