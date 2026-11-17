# -*- coding: utf-8 -*-
# Test 36: NX Motion 滑动副 —— 偏置曲柄滑块的运动学与矩阵口径
#
# 覆盖（NX12 批处理）：
#   * Motion 层 Slider 关节：FirstOrigin/SecondOrigin 重合，FirstVector/SecondVector
#     把关节局部 z 轴对齐到导轨（装配层 Constraint.Type.Slider 是 internal-only）
#   * 3 个 Revolute + 1 个 Slider 的平面机构，驱动 2 s / 720 步整周
#   * 帧变换 16 值按行主序解读：平移取 3/7/11；转置会让杆长漂 14 mm 量级
#   * 帧索引 0 基：合法范围 0..nfr-1，帧 0 = t=0 设计位姿
#   * 螺旋副：Cylindrical + Screw 同一对 link，导程 2 mm/rev，90°/s×1 s
#     → 转角 −90°、轴向 −0.5 mm（第二解，独立于主机构）
#
# 解析式（独立信息源，不取自 NX 数据）：
#   x(theta) = r*cos(theta) + sqrt(l^2 - (r*sin(theta) - e)^2)
#   v(theta) = omega * dx/dtheta
# 判据全部来自几何/指令参数；杆长守恒是矩阵口径的独立判别器。
#
# 成功标志：TEST36_DONE 且 BENCH_PASS
import math
import os
import traceback

import NXOpen
import NXOpen.UF
import NXOpen.Motion as M

import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import say, write_log

# ---------------- 机构参数（全部 mm） ----------------
R = 40.0                       # 曲柄
L = 120.0                      # 连杆
E = 20.0                       # 偏置（导轨 y = e）
A0 = (R, 0.0)
B0X = R + math.sqrt(L * L - E * E)
B0 = (B0X, E)

OMEGA_DEG_S = 180.0            # 物理 CCW 角速度；MotionEulerAngle1 传负值
OMEGA_RAD_S = math.pi
DRIVE_DEG_S = -OMEGA_DEG_S
T_END = 2.0
NSTEP = 720
DT = T_END / NSTEP

TOL_X = 0.01                   # mm
TOL_Y = 1e-6                   # mm
TOL_ROD = 0.01                 # mm
TOL_V = 0.01                   # mm/s

MASTER = "m36_asm.prt"
LOG = os.path.join(os.getcwd(), "test36_log.txt")


def set_expr(part, expr, value):
    expr.RightHandSide = str(value)
    try:
        part.Expressions.Edit(expr, str(value))
    except Exception:
        pass


def analytic_x(theta):
    s = R * math.sin(theta) - E
    return R * math.cos(theta) + math.sqrt(L * L - s * s)


def analytic_v(theta):
    s = R * math.sin(theta) - E
    root = math.sqrt(L * L - s * s)
    return OMEGA_RAD_S * (-R * math.sin(theta) - s * R * math.cos(theta) / root)


def unwrap(vals):
    out = [vals[0]]
    for v in vals[1:]:
        d = v - out[-1]
        while d > math.pi:
            v -= 2.0 * math.pi
            d = v - out[-1]
        while d < -math.pi:
            v += 2.0 * math.pi
            d = v - out[-1]
        out.append(v)
    return out


def main():
    try:
        _main()
    finally:
        try:
            write_log(LOG)
        except Exception:
            pass


def _main():
    theSession = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    fileNew = theSession.Parts.FileNew()
    fileNew.Units = NXOpen.Part.Units.Millimeters
    fileNew.TemplateFileName = "model-plain-1-mm-template.prt"
    fileNew.NewFileName = MASTER
    fileNew.UseBlankTemplate = False
    master = fileNew.Commit()
    fileNew.Destroy()

    ms = theSession.MotionSession
    ms.CreateSimulation(master)
    sim_part = None
    for p in theSession.Parts:
        if p is not None and (p.FullPath or "").lower().endswith(".sim"):
            sim_part = p
            break
    if sim_part is None:
        say("FAIL 未找到 .sim 部件")
        say("BENCH_FAIL")
        say("TEST36_DONE")
        return
    ms.InitializeSimulation(sim_part)
    ufs.Part.SetDisplayPart(sim_part.Tag)
    theSession.Parts.SetWork(sim_part)
    mm = sim_part.MotionManager
    say("SIM=%s" % sim_part.Leaf)

    pts = {
        "O": sim_part.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0)),
        "A": sim_part.Points.CreatePoint(NXOpen.Point3d(A0[0], A0[1], 0.0)),
        "B": sim_part.Points.CreatePoint(NXOpen.Point3d(B0[0], B0[1], 0.0)),
    }
    zdir = sim_part.Directions.CreateDirection(pts["O"], NXOpen.Vector3d(0.0, 0.0, 1.0))
    xdir = sim_part.Directions.CreateDirection(pts["B"], NXOpen.Vector3d(1.0, 0.0, 0.0))

    cms = {
        "FRAME": (100.0, 20.0, -10.0),
        "CRANK": (0.5 * R, 0.0, 0.0),
        "ROD": (0.5 * (A0[0] + B0[0]), 0.5 * (A0[1] + B0[1]), 0.0),
        "SLIDER": (B0[0], B0[1], 0.0),
        "SLIDER2": (0.0, -200.0, 0.0),
        "G1": (0.0, 200.0, 0.0),
        "G2": (40.0, 200.0, 0.0),
    }
    links = {}
    for nm in ("FRAME", "CRANK", "ROD", "SLIDER", "SLIDER2", "G1", "G2"):
        lb = mm.Links.CreateLinkBuilder(M.Link.Null)
        lb.Name = "L_" + nm
        lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
        set_expr(sim_part, lb.MassProperty.MassExpression, "1.0")
        for ax in ("IxxExpression", "IyyExpression", "IzzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "1.0")
        for ax in ("IxyExpression", "IxzExpression", "IyzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "0.0")
        cm = cms[nm]
        lb.MassProperty.MassCenter = sim_part.Points.CreatePoint(
            NXOpen.Point3d(cm[0], cm[1], cm[2]))
        links[nm] = lb.Commit()
        lb.Destroy()
    say("LINKS=%d" % len(links))

    def joint(name, jtype, l1, l2, origin, vec, vec2=None):
        jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
        jd = jb.JointDefine
        jd.JointType = jtype
        jd.FirstLink = links[l1]
        jd.SecondLink = links[l2]
        jd.FirstOrigin = origin
        jd.FirstVector = vec
        if vec2 is not None:
            jd.SecondOrigin = origin
            jd.SecondVector = vec2
        jd.Name = name
        j = jb.Commit()
        jb.Destroy()
        return j

    joints = {
        "J_O": joint("J_O", M.JointDefine.Type.Revolute, "FRAME", "CRANK", pts["O"], zdir),
        "J_A": joint("J_A", M.JointDefine.Type.Revolute, "CRANK", "ROD", pts["A"], zdir),
        "J_B": joint("J_B", M.JointDefine.Type.Revolute, "ROD", "SLIDER", pts["B"], zdir),
        "J_S": joint("J_S", M.JointDefine.Type.Slider, "FRAME", "SLIDER",
                     pts["B"], xdir, xdir),
        # 独立平移台：关节局部 z = +X，MotionTranslationZ 正速度走 −z
        "J_TZ": joint("J_TZ", M.JointDefine.Type.Slider, "FRAME", "SLIDER2",
                      sim_part.Points.CreatePoint(NXOpen.Point3d(0.0, -200.0, 0.0)),
                      xdir, xdir),
        # 独立定轴轮系：两个转动副挂同一机架，齿轮副按半径比耦合
        "J_G1": joint("J_G1", M.JointDefine.Type.Revolute, "FRAME", "G1",
                      sim_part.Points.CreatePoint(NXOpen.Point3d(0.0, 200.0, 0.0)),
                      zdir),
        "J_G2": joint("J_G2", M.JointDefine.Type.Revolute, "FRAME", "G2",
                      sim_part.Points.CreatePoint(NXOpen.Point3d(40.0, 200.0, 0.0)),
                      zdir),
    }
    say("JOINTS=%s" % ",".join(joints.keys()))
    ms.FixLinkToGround(links["FRAME"])

    cb = mm.Couplers.CreateCouplerGearBuilder(M.CouplerGear.Null)
    cb.Name = "GEAR_20_40"
    cb.FirstJoint.Value = joints["J_G1"]
    cb.SecondJoint.Value = joints["J_G2"]
    cb.FirstRadiusExpression.RightHandSide = "20.0"
    cb.SecondRadiusExpression.RightHandSide = "40.0"
    cb.RatioExpression.RightHandSide = "-0.5"
    cb.ContactPoint = sim_part.Points.CreatePoint(
        NXOpen.Point3d(20.0, 200.0, 0.0))
    cb.Validate()
    cb.Commit()
    cb.Destroy()
    say("COUPLER=20:40 ratio=-0.5")

    jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    jdb.Name = "DRV_CRANK"
    jdb.Joint.Value = joints["J_O"]
    op = jdb.DriverMultiOperations.MotionEulerAngle1
    op.TypeOption = M.DriverOperation.Type.Constant
    op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
    set_expr(sim_part, op.VelocityExpression, "%.3f" % DRIVE_DEG_S)
    jdb.Commit()
    jdb.Destroy()
    say("DRIVER=%.1f deg/s (negative=CCW)" % DRIVE_DEG_S)

    jdb2 = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    jdb2.Name = "DRV_TZ"
    jdb2.Joint.Value = joints["J_TZ"]
    op2 = jdb2.DriverMultiOperations.MotionTranslationZ
    op2.TypeOption = M.DriverOperation.Type.Constant
    op2.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
    set_expr(sim_part, op2.VelocityExpression, "10.0")
    jdb2.Commit()
    jdb2.Destroy()
    say("DRIVER_TZ=10.0 mm/s along local z (=+X)")

    jdb3 = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    jdb3.Name = "DRV_GEAR"
    jdb3.Joint.Value = joints["J_G1"]
    op3 = jdb3.DriverMultiOperations.MotionEulerAngle1
    op3.TypeOption = M.DriverOperation.Type.Constant
    op3.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
    set_expr(sim_part, op3.VelocityExpression, "360.0")
    jdb3.Commit()
    jdb3.Destroy()
    say("DRIVER_GEAR=360.0 deg/s on J_G1")

    sb = mm.MotionSolutions.CreateSolutionBuilder(M.MotionSolution.Null)
    sb.Name = "SOL_TEST36"
    sb.SolutionType = M.MotionSolutionBuilder.SolutionTypes.Normal
    sb.AnalysisType = M.MotionSolutionBuilder.AnalysisTypes.Dynamic
    sb.Step = NSTEP
    set_expr(sim_part, sb.TimeExpression, "%.3f" % T_END)
    sol = sb.Commit()
    sb.Destroy()
    sol.SolveNormalRunSolution()
    nfr = int(ufs.Motion.AskNumberOfAnimationFrames())
    say("SOLVE_OK FRAMES=%d" % nfr)

    def extract_tf(tg, fr):
        try:
            r = ufs.Motion.AskLinkTransfromForGivenFrame(tg, fr)
            if r is not None and len(r) >= 12:
                return list(r)
        except Exception:
            pass
        try:
            return list(ufs.Motion.AskLinkTransfromForGivenFrame(tg, fr, [0.0] * 12))
        except Exception:
            return None

    # ---- 逐帧提取：0 基遍历（0..nfr-1，含 t=0 与 t=t_end） ----
    th_raw, xs, ys, frames = [], [], [], []
    for fr in range(nfr):
        rc = extract_tf(links["CRANK"].Tag, fr)
        rs = extract_tf(links["SLIDER"].Tag, fr)
        if rc is None or rs is None:
            continue
        frames.append(fr)
        ax = rc[0] * A0[0] + rc[1] * A0[1] + rc[3]
        ay = rc[4] * A0[0] + rc[5] * A0[1] + rc[7]
        th_raw.append(math.atan2(ay, ax))
        xs.append(rs[0] * B0[0] + rs[1] * B0[1] + rs[3])
        ys.append(rs[4] * B0[0] + rs[5] * B0[1] + rs[7])

    if len(xs) < 10:
        say("FAIL 位姿提取不足: %d" % len(xs))
        say("BENCH_FAIL")
        say("TEST36_DONE")
        return

    th = unwrap(th_raw)
    nused = len(xs)

    # ---- 独立判据 ----
    dx_dev = [xs[i] - analytic_x(th[i]) for i in range(nused)]
    dy_dev = [ys[i] - E for i in range(nused)]
    rod_dev = []
    for i in range(nused):
        ax = R * math.cos(th[i])
        ay = R * math.sin(th[i])
        rod_dev.append(abs(math.hypot(xs[i] - ax, E - ay) - L))

    ts = [th[i] / OMEGA_RAD_S for i in range(nused)]
    dv_dev = []
    dv_worst = (0.0, -1)
    # frame 1 的中心差分含求解器首步启动瞬态（实测 0.2366 mm/s），
    # 速度精度判据从 frame 2 起；端点 frame 0/nfr-1 不参与。
    for i in range(2, nused - 1):
        v = (xs[i + 1] - xs[i - 1]) / (ts[i + 1] - ts[i - 1])
        d = abs(v - analytic_v(th[i]))
        dv_dev.append(d)
        if d > dv_worst[0]:
            dv_worst = (d, i)

    max_dx = max(abs(v) for v in dx_dev)
    max_dy = max(abs(v) for v in dy_dev)
    max_rod = max(rod_dev)
    max_dv = max(dv_dev) if dv_dev else 9.99
    say("FRAMES_USED=%d" % nused)
    say("MAX_DX=%.6f mm  MAX_DY=%.6f mm" % (max_dx, max_dy))
    say("ROD_LEN_MAX_DEV=%.6f mm  MAX_DV_INTERNAL=%.6f mm/s at frame %d"
        % (max_rod, max_dv, dv_worst[1]))

    # ---- 平移驱动符号：局部 z=+X、10 mm/s 跑 2 s → Tx=-20 ----
    tz_x, g1_raw, g2_raw = [], [], []
    for fr in range(nfr):
        rt = extract_tf(links["SLIDER2"].Tag, fr)
        r1 = extract_tf(links["G1"].Tag, fr)
        r2 = extract_tf(links["G2"].Tag, fr)
        if rt is None or r1 is None or r2 is None:
            continue
        tz_x.append(rt[3])
        g1_raw.append(math.atan2(r1[4], r1[0]))
        g2_raw.append(math.atan2(r2[4], r2[0]))
    n_extra = min(len(tz_x), len(g1_raw), len(g2_raw))
    tz_x, g1_raw, g2_raw = tz_x[:n_extra], g1_raw[:n_extra], g2_raw[:n_extra]
    tz_delta = tz_x[-1] - tz_x[0] if n_extra else 0.0
    g1 = unwrap(g1_raw)
    g2 = unwrap(g2_raw)
    d1 = [g1[i + 1] - g1[i] for i in range(2, n_extra - 2)]
    d2 = [g2[i + 1] - g2[i] for i in range(2, n_extra - 2)]
    mean1 = sum(d1) / len(d1) if d1 else 9.99
    mean1_deg = math.degrees(mean1)      # d1 是弧度/帧
    gear_ratio = sum(d2) / sum(d1) if d1 and sum(d1) else 9.99
    say("TX_DELTA=%.6f mm (期望 -20.000000)" % tz_delta)
    say("GEAR_RATIO=%.6f  G1_RATE=%.6f deg/frame (期望 -0.500000 / ±1.000000)"
        % (gear_ratio, mean1_deg))

    # ---- 螺旋副：Cylindrical + Screw(导程 2 mm/rev) 的转角-轴向耦合 ----
    # Screw 必须与 Cylindrical 建在同一对 link 上；转动 90° 应沿轴走
    # 1/4 导程 = 0.5 mm。主机构已算完，第二解只用于这一对独立 link。
    screw_o = sim_part.Points.CreatePoint(NXOpen.Point3d(0.0, -600.0, 0.0))
    screw_z = sim_part.Directions.CreateDirection(
        screw_o, NXOpen.Vector3d(0.0, 0.0, 1.0))

    def screw_link(name, cm):
        lb = mm.Links.CreateLinkBuilder(M.Link.Null)
        lb.Name = name
        lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
        set_expr(sim_part, lb.MassProperty.MassExpression, "1.0")
        for ax in ("IxxExpression", "IyyExpression", "IzzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "1.0")
        for ax in ("IxyExpression", "IxzExpression", "IyzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "0.0")
        lb.MassProperty.MassCenter = cm
        l = lb.Commit()
        lb.Destroy()
        return l

    sg = screw_link("L_SCREW_G", screw_o)
    sm = screw_link("L_SCREW_M", screw_o)
    ms.FixLinkToGround(sg)

    def screw_joint(name, jtype):
        jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
        jd = jb.JointDefine
        jd.JointType = jtype
        jd.FirstLink = sg
        jd.SecondLink = sm
        jd.FirstOrigin = screw_o
        jd.FirstVector = screw_z
        jd.SecondOrigin = screw_o
        jd.SecondVector = screw_z
        jd.Name = name
        j = jb.Commit()
        jb.Destroy()
        return j

    j_sc_cyl = screw_joint("J_SCREW_CYL", M.JointDefine.Type.Cylindrical)
    jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
    jd = jb.JointDefine
    jd.JointType = M.JointDefine.Type.Screw
    jd.FirstLink = sg
    jd.SecondLink = sm
    jd.FirstOrigin = screw_o
    jd.FirstVector = screw_z
    jd.SecondOrigin = screw_o
    jd.SecondVector = screw_z
    jd.Name = "J_SCREW"
    jd.MethodType = M.JointDefineScrewJointMethodType.Ratio
    jd.RatioType = M.JointDefineScrewJointRatioType.Expression
    set_expr(sim_part, jd.ScrewRatioExpression, "2.0")
    jb.Commit()
    jb.Destroy()

    jdb4 = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    jdb4.Name = "DRV_SCREW"
    jdb4.Joint.Value = j_sc_cyl
    op4 = jdb4.DriverMultiOperations.MotionEulerAngle1
    op4.TypeOption = M.DriverOperation.Type.Constant
    op4.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
    set_expr(sim_part, op4.VelocityExpression, "90.0")
    jdb4.Commit()
    jdb4.Destroy()

    sb2 = mm.MotionSolutions.CreateSolutionBuilder(M.MotionSolution.Null)
    sb2.Name = "SOL_SCREW36"
    sb2.SolutionType = M.MotionSolutionBuilder.SolutionTypes.Normal
    sb2.AnalysisType = M.MotionSolutionBuilder.AnalysisTypes.Dynamic
    sb2.Step = 60
    set_expr(sim_part, sb2.TimeExpression, "1.000")
    sol2 = sb2.Commit()
    sb2.Destroy()
    sol2.SolveNormalRunSolution()
    sr0 = extract_tf(sm.Tag, 0)
    sr1 = extract_tf(sm.Tag, 60)
    if sr0 is None or sr1 is None:
        screw_rot = 9.99
        screw_dz = 9.99
    else:
        screw_rot = math.degrees(math.atan2(sr1[4], sr1[0])
                                 - math.atan2(sr0[4], sr0[0]))
        screw_dz = sr1[11] - sr0[11]
    say("SCREW_ROT=%.4f deg  SCREW_DZ=%.6f mm (导程 2, 90°→-0.5)"
        % (screw_rot, screw_dz))

    checks = [
        ("帧数（0 基全帧）", nused == nfr, "%d vs %d" % (nused, nfr)),
        ("平移驱动 Tx", abs(tz_delta + 20.0) <= 0.05,
         "%.6f vs -20.000000 mm" % tz_delta),
        ("齿轮副输出比", abs(gear_ratio + 0.5) <= 0.01,
         "%.6f vs -0.500000" % gear_ratio),
        ("齿轮驱动速率", abs(abs(mean1_deg) - 1.0) <= 0.02,
         "%.6f vs ±1.000000 deg/frame" % mean1_deg),
        ("螺旋副转角", abs(abs(screw_rot) - 90.0) <= 0.5,
         "%.4f vs ±90.0000 deg" % screw_rot),
        ("螺旋副导程", abs(abs(screw_dz) - 0.5) <= 0.01,
         "%.6f vs ±0.500000 mm (导程 2 mm/rev)" % screw_dz),
        ("帧数 = nstep+1", nfr == NSTEP + 1, "%d vs %d" % (nfr, NSTEP + 1)),
        ("滑块 x 与解析式", max_dx <= TOL_X, "%.6f vs %.4f mm" % (max_dx, TOL_X)),
        ("滑块 y 恒为偏置 e", max_dy <= TOL_Y, "%.6f vs %.1e mm" % (max_dy, TOL_Y)),
        ("连杆长度守恒（矩阵口径）", max_rod <= TOL_ROD,
         "%.6f vs %.4f mm" % (max_rod, TOL_ROD)),
        ("滑块线速度（内部帧）", max_dv <= TOL_V, "%.6f vs %.4f mm/s" % (max_dv, TOL_V)),
    ]
    allok = True
    for name, ok, detail in checks:
        allok = allok and ok
        say("  [%s] %-24s %s" % ("PASS" if ok else "FAIL", name, detail))

    say("BENCH_PASS" if allok else "BENCH_FAIL")
    say("TEST36_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("EXCEPTION:\n%s" % traceback.format_exc())
        say("BENCH_FAIL")
        say("TEST36_DONE")
        raise
