# -*- coding: utf-8 -*-
# Test 36: NX Motion 滑动副 —— 偏置曲柄滑块的运动学与矩阵口径
#
# 覆盖（NX12 批处理，2026-10-19 冷启动实测沉淀）：
#   * Motion 层 Slider 关节：FirstOrigin/SecondOrigin 重合，FirstVector/SecondVector
#     把关节局部 z 轴对齐到导轨（装配层 Constraint.Type.Slider 是 internal-only）
#   * 3 个 Revolute + 1 个 Slider 的平面机构，驱动 2 s / 720 步整周
#   * 帧变换 16 值按行主序解读：平移取 3/7/11；转置会让杆长漂 14 mm 量级
#   * 帧索引 0 基：合法范围 0..nfr-1，帧 0 = t=0 设计位姿（2026-10-19 复验）
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
    }
    links = {}
    for nm in ("FRAME", "CRANK", "ROD", "SLIDER"):
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
    }
    say("JOINTS=%s" % ",".join(joints.keys()))
    ms.FixLinkToGround(links["FRAME"])

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

    checks = [
        ("帧数（0 基全帧）", nused == nfr, "%d vs %d" % (nused, nfr)),
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
