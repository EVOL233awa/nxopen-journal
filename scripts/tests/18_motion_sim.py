# -*- coding: utf-8 -*-
# Test 18: NX Motion 运动仿真 —— 平面四杆（曲柄摇杆）的运动副/驱动/求解/结果提取
#
# 覆盖（NX12 批处理，实测，源自四连杆机构的载荷用例）：
#   * MotionSession.CreateSimulation → 认领 .sim 部件 → InitializeSimulation
#   * 无几何 Link（Geometries 留空 + MassType=UserDefined）+ 用户定义质量/惯量
#   * 转动副 JointDefine（JointType=Revolute, FirstLink/SecondLink/FirstOrigin/
#     FirstVector/Name）+ FixLinkToGround
#   * 关节驱动（MotionEulerAngle1, Type=Constant, IntegrationType=Velocity, deg/s）
#   * 运动求解（MotionSolutionBuilder Normal/Dynamic + Step + TimeExpression）
#   * 结果提取：AskNumberOfAnimationFrames / AskForceResults /
#     AskLinkTransfromForGivenFrame（2 参优先，3 参回退）
#
# 检查只卡「运动学」（可靠）：曲柄恒速特性（每帧转角恒定）、摇杆摆角 60.02°、
#   每转换向 2 次。
#   注：曲柄判据用「每帧步长恒定」而非「总转角=360°」—— 帧索引 0 基（0..nfr-1），
#   0 与 nfr-1 都是合法端点；用步长判据不依赖端点是否被截断。
# ⚠ 反力**不作物理判据**：4 个转动副描述平面四杆同样属静不定
#   （6×3 − 5×4 = −2），摇杆极限位（曲柄与连杆共线）邻域反力可能是冗余约束伪影。
#   本用例只校验反力 API 通路（返回条数、数值有限非空）。物理可信的反力须改用
#   静定平面刚体动力学模型另解 —— 见 references/motion.md §M.8。
# ⚠ 不要用 AskVelocityResults/AskAccelerationResults（实测全返回 0.0）。
#
# 解析预期由本文件外的整周独立扫描算出（Grashof: 20+70=90 ≤ 60+40=100，AB 为曲柄）。
#
# 成功标志：TEST18_DONE 且 BENCH_PASS
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

# ---------------- 机构几何（曲柄摇杆四杆，全部 mm） ----------------
AB, BC, CD, AD = 20.0, 60.0, 40.0, 70.0
A = (0.0, 0.0)
D = (AD, 0.0)
B0 = (AB, 0.0)
# C 由 |BC|=60 与 |CD|=40 两圆交解得（取 +h 分支，需与工程初始位形一致）
# 注：不用 math.dist —— NX 12 内嵌 journal 解释器实测为 Python 3.6（<3.8），无该函数。
_d = math.hypot(D[0] - B0[0], D[1] - B0[1])
_a = (BC ** 2 - CD ** 2 + _d ** 2) / (2.0 * _d)
_h = math.sqrt(BC ** 2 - _a ** 2)
_ux, _uy = (D[0] - B0[0]) / _d, (D[1] - B0[1]) / _d
C0 = (B0[0] + _a * _ux - _h * _uy, B0[1] + _a * _uy + _h * _ux)

P = {"A": A, "B": B0, "C": C0, "D": D}
LINK_DEF = [("机架", "A", "D"), ("曲柄", "A", "B"),
            ("连接杆", "B", "C"), ("摇杆", "C", "D")]
JOINT_DEF = [("J_A", "机架", "曲柄", "A"), ("J_B", "曲柄", "连接杆", "B"),
             ("J_C", "连接杆", "摇杆", "C"), ("J_D", "摇杆", "机架", "D")]
GROUND = "机架"
LAM = 0.5                      # kg/m 等效线密度（等效均质细杆）

OMEGA_DEG_S = 360.0            # 曲柄恒速 1 转/秒
T_END = 1.0
NSTEP = 360

# ---------------- 解析预期与容差 ----------------
EXP_CRANK_ROT = 360.0
EXP_ROCKER_SPAN = 60.0218
EXP_REVERSALS = 2
TOL_CRANK = 2.0
TOL_SPAN = 2.0

MASTER = "m18_asm.prt"
LOG = os.path.join(os.getcwd(), "test18_log.txt")


def set_expr(part, expr, value):
    try:
        expr.RightHandSide = str(value)
        try:
            part.Expressions.Edit(expr, str(value))
        except Exception:
            pass
        return True
    except Exception:
        return False


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


def link_len(a, b):
    return math.hypot(P[b][0] - P[a][0], P[b][1] - P[a][1])   # 3.6 无 math.dist


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

    # ---- 1. 建主部件并建立仿真 ----
    fileNew = theSession.Parts.FileNew()
    fileNew.Units = NXOpen.Part.Units.Millimeters
    fileNew.TemplateFileName = "model-plain-1-mm-template.prt"
    fileNew.NewFileName = MASTER
    fileNew.UseBlankTemplate = False
    master = fileNew.Commit()
    fileNew.Destroy()
    say("MASTER=%s" % master.Leaf)

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
        say("TEST18_DONE")
        return
    ms.InitializeSimulation(sim_part)
    ufs.Part.SetDisplayPart(sim_part.Tag)
    theSession.Parts.SetWork(sim_part)
    mm = sim_part.MotionManager
    say("SIM=%s" % sim_part.Leaf)

    # ---- 2. 铰点与质心点（MassCenter 必须在建 Link 之前创建）----
    pts = {pn: sim_part.Points.CreatePoint(NXOpen.Point3d(x, y, 0.0))
           for pn, (x, y) in P.items()}
    cm = {}
    for cn, j1, j2 in LINK_DEF:
        xc = 0.5 * (P[j1][0] + P[j2][0])
        yc = 0.5 * (P[j1][1] + P[j2][1])
        cm[cn] = sim_part.Points.CreatePoint(NXOpen.Point3d(xc, yc, 0.0))

    # ---- 3. Link（无几何 + 用户定义质量/惯量，各向同性）----
    links = {}
    for cn, j1, j2 in LINK_DEF:
        L = link_len(j1, j2)
        mass = LAM * L * 1e-3
        inert = mass * L ** 2 / 12.0            # kg·mm²
        lb = mm.Links.CreateLinkBuilder(M.Link.Null)
        lb.Name = "L_" + cn
        lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
        set_expr(sim_part, lb.MassProperty.MassExpression, "%.6f" % mass)
        for ax in ("IxxExpression", "IyyExpression", "IzzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "%.6f" % inert)
        for ax in ("IxyExpression", "IxzExpression", "IyzExpression"):
            set_expr(sim_part, getattr(lb.MassProperty, ax), "0.0")
        lb.MassProperty.MassCenter = cm[cn]
        links[cn] = lb.Commit()
        lb.Destroy()
        say("  Link %-4s L=%7.3f m=%.6f kg I=%.6f kg·mm²"
            % (cn, L, mass, inert))
    say("LINKS=%d" % len(links))

    # ---- 4. 转动副（轴线平行 Z）----
    zd = sim_part.Directions.CreateDirection(pts["A"], NXOpen.Vector3d(0.0, 0.0, 1.0))
    joints = {}
    for jn, c1, c2, pn in JOINT_DEF:
        jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
        jd = jb.JointDefine
        jd.JointType = M.JointDefine.Type.Revolute
        jd.FirstLink = links[c1]
        jd.SecondLink = links[c2]
        jd.FirstOrigin = pts[pn]
        jd.FirstVector = zd
        jd.Name = jn
        joints[jn] = jb.Commit()
        jb.Destroy()
    for cn, j1, j2 in LINK_DEF:
        if cn == GROUND:
            ms.FixLinkToGround(links[cn])
    say("JOINTS=%d FIX=1" % len(joints))

    # ---- 5. 驱动（曲柄恒速）----
    jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    jdb.Name = "DRV_CRANK"
    jdb.Joint.Value = joints["J_A"]
    op = jdb.DriverMultiOperations.MotionEulerAngle1
    op.TypeOption = M.DriverOperation.Type.Constant
    op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
    set_expr(sim_part, op.VelocityExpression, "%.1f" % OMEGA_DEG_S)
    jdb.Commit()
    jdb.Destroy()
    say("DRIVER OK %.1f deg/s" % OMEGA_DEG_S)

    # ---- 6. 求解 ----
    sb = mm.MotionSolutions.CreateSolutionBuilder(M.MotionSolution.Null)
    sb.Name = "SOL_TEST18"
    sb.SolutionType = M.MotionSolutionBuilder.SolutionTypes.Normal
    sb.AnalysisType = M.MotionSolutionBuilder.AnalysisTypes.Dynamic
    sb.Step = NSTEP
    set_expr(sim_part, sb.TimeExpression, "%.3f" % T_END)
    sol = sb.Commit()
    sb.Destroy()
    sol.SolveNormalRunSolution()
    nfr = int(ufs.Motion.AskNumberOfAnimationFrames())
    say("SOLVE OK FRAMES=%d" % nfr)

    # ---- 7. 结果提取：反力（只验通路）----
    VC = ufs.Motion.VectorComponent
    RF = ufs.Motion.ReferenceFrame
    nforce = 0
    force_finite = True
    for jn in joints:
        for vc in ("MAGNITUDE", "XCOMPONENT", "YCOMPONENT", "ZCOMPONENT"):
            try:
                r = ufs.Motion.AskForceResults(joints[jn].Tag, getattr(VC, vc), RF.ABSOLUTE)
                vals = [float(v) for v in r[1]]
                nforce += 1
                for v in vals:
                    if math.isnan(v) or math.isinf(v):
                        force_finite = False
                if vc == "MAGNITUDE":
                    say("  %s |F|max=%.4f N (n=%d)" % (jn, max(vals), len(vals)))
            except Exception as e:
                say("  FORCE %s|%s FAIL %s"
                    % (jn, vc, str(e).splitlines()[0][:70]))
    say("FORCES ok=%d/%d finite=%s" % (nforce, 4 * len(joints), force_finite))

    # ---- 8. 结果提取：位姿（2 参优先，3 参回退）----
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

    def link_angles(cn):
        vals = []
        for fr in range(nfr):                 # 0 基：0..nfr-1，含 t=0 与 t=t_end
            r = extract_tf(links[cn].Tag, fr)
            if r is None:
                continue
            vals.append(math.atan2(r[4], r[0]))      # R[1,0]=r[4], R[0,0]=r[0]
        return vals

    crank_raw = unwrap(link_angles("曲柄"))
    rocker_raw = unwrap(link_angles("摇杆"))
    if len(crank_raw) < 10 or len(rocker_raw) < 10:
        say("FAIL 位姿提取不足: crank=%d rocker=%d"
            % (len(crank_raw), len(rocker_raw)))
        say("BENCH_FAIL")
        say("TEST18_DONE")
        return
    say("FRAMES_EXTRACTED crank=%d rocker=%d" % (len(crank_raw), len(rocker_raw)))
    if len(crank_raw) != len(rocker_raw):
        say("FAIL 两杆帧数不一致，无法逐帧对照")
        say("BENCH_FAIL")
        say("TEST18_DONE")
        return

    # 恒速驱动：真实步长应 = 360°/(nfr-1)。整周 360° 由 nfr-1 个步长覆盖。
    per_frame_rad = (2.0 * math.pi) / float(nfr - 1)
    crank = crank_raw
    rocker = rocker_raw
    nused = min(len(crank), len(rocker))
    crank, rocker = crank[:nused], rocker[:nused]
    per_frame = math.degrees(per_frame_rad)
    say("FRAMES_USED=%d" % nused)

    # 恒速检验：每个相邻步长都应等于「指令速率换算到每帧」的值。
    # ⚠ 这里的期望值由**指令**速率（OMEGA_DEG_S=360 °/s）与仿真时长 T_END 算出，
    #   不取自 NX 返回的位姿本身 —— 否则就是拿数据验数据（自洽检查无判别力）。
    #   该判据同时是「驱动单位陷阱」的探针：若 VelocityExpression 被按 rad/s 解释，
    #   实测每帧转角会是 57.2958° 而非 1.0°，立即 FAIL。
    cmd_per_frame = OMEGA_DEG_S * T_END / float(nfr - 1)
    c_abs = [abs(math.degrees(crank[i + 1] - crank[i]))
             for i in range(nused - 1)]
    c_dev = max(abs(s - cmd_per_frame) for s in c_abs) if c_abs else 9.99
    c_mean = sum(c_abs) / len(c_abs) if c_abs else 0.0
    crank_rot = math.degrees(crank[-1] - crank[0])

    rocker_span = math.degrees(max(rocker) - min(rocker))
    diffs = [rocker[i + 1] - rocker[i] for i in range(nused - 1)]
    revs = sum(1 for i in range(len(diffs) - 1)
               if diffs[i] * diffs[i + 1] < 0.0)

    say("CRANK_STEP_DEG: mean=%.6f max_dev=%.6f  (指令速率每帧应为 %.6f)"
        % (c_mean, c_dev, cmd_per_frame))
    say("CRANK_ROT_DEG=%.4f  (%d 帧覆盖 %d 个步长)"
        % (crank_rot, nused, nused - 1))
    say("ROCKER_SPAN_DEG=%.4f  (解析预期 %.4f±%.1f)"
        % (rocker_span, EXP_ROCKER_SPAN, TOL_SPAN))
    say("ROCKER_REVERSALS=%d  (解析预期 %d)" % (revs, EXP_REVERSALS))

    # ---- 8b. 落盘逐帧曲线数据（供人查看与出图，不作判据）----
    # 曲线图要看的是「从动件怎么动」，判据看的是上面的数值；两者同源但用途不同，
    # 所以这里只落盘，不参与 PASS/FAIL。
    csv_path = os.path.join(os.getcwd(), "m18_motion.csv")
    try:
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("# case 18: planar four-bar (crank-rocker), NX Motion solve\n")
            f.write("# crank %.1f deg/s constant, %d steps over %.1f s\n"
                    % (OMEGA_DEG_S, NSTEP, T_END))
            f.write("# angles: unwrapped, degrees, frame 0 = t=0\n")
            f.write("# frame,time_s,crank_deg,rocker_deg\n")
            for i in range(nused):
                t = T_END * i / float(nused - 1) if nused > 1 else 0.0
                f.write("%d,%.6f,%.6f,%.6f\n"
                        % (i, t, math.degrees(crank[i]),
                           math.degrees(rocker[i])))
        say("CSV %s rows=%d" % (os.path.basename(csv_path), nused))
    except Exception as exc:
        say("CSV SKIP %s: %s" % (type(exc).__name__, str(exc)[:50]))

    # ---- 9. 检查 ----
    checks = [
        ("曲柄速率+恒速", c_dev <= 0.01 and abs(c_mean - cmd_per_frame) <= 0.01,
         "mean=%.6f dev=%.6f° vs 指令 %.6f°" % (c_mean, c_dev, cmd_per_frame)),
        ("摇杆摆角", abs(rocker_span - EXP_ROCKER_SPAN) <= TOL_SPAN,
         "%.4f vs %.2f±%.1f" % (rocker_span, EXP_ROCKER_SPAN, TOL_SPAN)),
        ("摇杆每转换向次数", revs == EXP_REVERSALS,
         "%d vs %d" % (revs, EXP_REVERSALS)),
        ("反力数据通路", force_finite and nforce == 4 * len(joints),
         "ok=%d/%d finite=%s" % (nforce, 4 * len(joints), force_finite)),
    ]
    allok = True
    for name, ok, detail in checks:
        allok = allok and ok
        say("  [%s] %-18s %s" % ("PASS" if ok else "FAIL", name, detail))

    say("BENCH_PASS" if allok else "BENCH_FAIL")
    say("TEST18_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("EXCEPTION:\n%s" % traceback.format_exc())
        say("BENCH_FAIL")
        say("TEST18_DONE")
        raise
