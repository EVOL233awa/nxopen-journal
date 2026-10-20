# -*- coding: utf-8 -*-
# Test 17: NX12 装配约束的四条死路 + 一条正向对照（正式检查，已并入 RUN_TESTS.bat）
#
# 断言实测值；行为一旦变化即打 TEST17_FAIL 让套件变成 FAIL，迫使重新测量。
#
# 逐条判据（见 tests/README.md 的反向验证记录）：
#   1) 运动副枚举 Hinge/Cylindrical/Ball/Screw/Gear/RackPinion/Cable
#      赋值 ConstraintType 即抛 "not valid for this operation"
#      （NXOpen.xml 对这些枚举标注 "For internal use only"）。
#   2) Concentric（圆柱面）-> CannotSolve（参考被解析成 Line/Cylinder）。
#   3) Concentric（圆边）-> **报 Solved**，且 DOF 读数仍 3T+3R。
#      ⚠ **`Solved` + DOF 不变 都不能证明约束是否生效**，必须量几何：
#      圆边 Concentric 报 Solved、DOF 仍 3T+3R，但被约束件实际移动 25 mm、
#      孔轴落到目标轴上。可复现的危险只有这一条。
#   4) Fit 不等半径 -> InternallyInconsistent。
#   5) 正向对照：Fit 等半径 -> Solved 且件被拉到同轴（本文件靠它取得鉴别力：
#      如果 Fit 哪天失效，阶段 C 会 FAIL；只测死路的文件无法区分"死路"与"全坏"）。
#
# 方法学：被约束件一律故意移开再解算；每个阶段自建 Fix 固定接地件，
# 解算后量 GetPosition() 的位移（不用 DOF 当判据，DOF 在批处理下会滞后）。
#
# 成功标志：TEST17_DONE；任一阶段失败打 TEST17_FAIL stages=...
import os
import math
import traceback

import NXOpen
import NXOpen.Assemblies
import NXOpen.Features
import NXOpen.Positioning
import NXOpen.UF

HOLE_D = 10.0
HOLE_R = 5.0
BIG_D = 20.0
BIG_R = 10.0

# 死路 1：NXOpen.xml 标注 For internal use only 的运动副枚举
DEAD_TYPES = ("Hinge", "Cylindrical", "Ball", "Screw", "Gear",
              "RackPinion", "Cable")

# 组件放置：接地件在原点，被约束件故意移开（falsify 基线）
PLACE = {"m17_small": (0.0, 0.0, 0.0),
         "m17_big": (20.0, 15.0, 25.0),
         "m17_small2": (-30.0, 18.0, 12.0)}

MOVE_MIN = 1.0      # 位移超过此值才算"约束真的动了件"
ALIGN_TOL = 0.01    # 落到目标孔轴上（x/y 归零）的容差
REV_DEG = 12.0      # 拖动复验：绕孔轴转这个角度应当被允许
SLIDE_MM = 8.0      # 拖动复验：沿孔轴平移这个距离应当被拒绝（纯转动 0T+1R）

FAILED_STAGES = []


def stage(name, fn):
    try:
        r = fn()
        print("STAGE_OK " + name)
        return r
    except Exception as exc:
        FAILED_STAGES.append(name)
        print("STAGE_FAIL " + name + " :: " + str(exc))
        print(traceback.format_exc()[-500:])
        return None


def new_part(session, name):
    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.NewFileName = name + ".prt"
    fn.UseBlankTemplate = False
    part = fn.Commit()
    fn.Destroy()
    return part


def add_block(wp, origin, lengths):
    blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    blk.SetOriginAndLengths(
        NXOpen.Point3d(float(origin[0]), float(origin[1]), float(origin[2])),
        str(lengths[0]), str(lengths[1]), str(lengths[2]))
    feat = blk.CommitFeature()
    blk.Destroy()
    return feat


def find_planar_face(body, point, want_normal_z):
    ufs = NXOpen.UF.UFSession.GetUFSession()
    best = None
    best_dist = 1e18
    for face in body.GetFaces():
        data = ufs.Modeling.AskFaceData(face.Tag)
        ftype, fp, fdir = data[0], data[1], data[2]
        if ftype != 22:
            continue
        if abs(fdir[2] - want_normal_z) > 0.01:
            continue
        dist = abs((point.X - fp[0]) * fdir[0] + (point.Y - fp[1]) * fdir[1]
                   + (point.Z - fp[2]) * fdir[2])
        if dist < best_dist:
            best_dist = dist
            best = face
    return best


def add_thru_hole(wp, body, x, y, z_top, expr_name):
    top = find_planar_face(body, NXOpen.Point3d(x, y, z_top), 1.0)
    bottom = find_planar_face(body, NXOpen.Point3d(x, y, 0.0), -1.0)
    builder = wp.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
    builder.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
    builder.SetSimpleHole(NXOpen.Point3d(x, y, z_top), False, top, expr_name)
    builder.SetThruFace(bottom)
    builder.HoleLocation = NXOpen.Point3d(x, y, z_top)
    feat = builder.CommitFeature()
    builder.Destroy()
    return feat


def identity():
    m = NXOpen.Matrix3x3()
    m.Xx = 1.0
    m.Yy = 1.0
    m.Zz = 1.0
    return m


def hole_face(part, ufs, r_want):
    for b in part.Bodies:
        for f in b.GetFaces():
            data = ufs.Modeling.AskFaceData(f.Tag)
            if data[0] != 16:          # 16 = cylinder
                continue
            if abs(float(data[4]) - r_want) <= 0.1:
                return f
    return None


def hole_top_edge(part, ufs, r_want, z_top):
    """孔壁圆在顶面的那条边：整圆的两顶点与圆心重合（p1 == p2）。"""
    f = hole_face(part, ufs, r_want)
    if f is None:
        return None
    best = None
    for e in f.GetEdges():
        try:
            p1, p2 = e.GetVertices()
        except Exception:
            continue
        if abs(p1.X - p2.X) > 1e-6 or abs(p1.Y - p2.Y) > 1e-6 \
                or abs(p1.Z - p2.Z) > 1e-6:
            continue
        if best is None or abs(p1.Z - z_top) < abs(best[0] - z_top):
            best = (p1.Z, e)
    return best[1] if best else None


def solve_status(con):
    tbl = ["NewlyCreated", "Suppressed", "OutOfDate", "OverConstrained",
           "NotConsistentDims", "NotConsistentOther", "NotConsistentUnknown",
           "BetweenFixed", "NotSolved", "Solved", "CannotSolve", "Delayed",
           "IgnoredInArrangement", "InternallyInconsistent",
           "UnloadedGeometry", "PendingConvertedMc", "ConflictingWithWave",
           "InconsistentLimits", "BeyondLimits"]
    st = con.GetConstraintStatus()
    for nm in tbl:
        if st == getattr(NXOpen.Positioning.Constraint.SolverStatus, nm):
            return nm
    return "?%s" % st


def dof_of(comp):
    """仅打印用：DOF 在批处理下会滞后（§A.2 / §A.5），不作判据。"""
    try:
        d = comp.GetDegreesOfFreedom()
        return "%dT+%dR" % (d.NumTranslational, d.NumRotational)
    except Exception as exc:
        return "ERR:%s" % str(exc)[:40]


def rot_z(deg):
    a = math.radians(deg)
    m = NXOpen.Matrix3x3()
    m.Xx = math.cos(a)
    m.Xy = -math.sin(a)
    m.Yx = math.sin(a)
    m.Yy = math.cos(a)
    m.Zz = 1.0
    return m


def pose_of(comp):
    o, m = comp.GetPosition()
    return (o.X, o.Y, o.Z, math.degrees(math.atan2(m.Yx, m.Xx)))


def dev6(a, b):
    return max(abs(a[i] - b[i]) for i in range(len(a)))


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    # 幂等：清掉本用例旧产物（FileNew 不覆盖同名文件）
    for stale in list(PLACE) + ["m17_asm"]:
        sp = os.path.abspath(stale + ".prt")
        if os.path.exists(sp):
            os.remove(sp)

    def make_plate(name, hole_d):
        p = new_part(session, name)
        session.Parts.SetWork(p)
        ufs.Part.SetDisplayPart(p.Tag)
        body = add_block(p, (-50.0, -30.0, 0.0), (100.0, 60.0, 10.0))
        unit = p.UnitCollection.GetBase("Length")
        p.Expressions.CreateSystemExpressionWithUnits(
            "HOLE_D = %.4f" % hole_d, unit)
        add_thru_hole(p, body, 0.0, 0.0, 10.0, "HOLE_D")
        ufs.Part.Save()
        # Commit/Save 成功 != 落盘：文件存在且非空是唯一证据（SKILL.md §3）
        sp = os.path.abspath(name + ".prt")
        assert os.path.exists(sp) and os.path.getsize(sp) > 0, \
            "零件 %s 未落盘" % name
        return p

    # 两块 Ø10 孔的板（可配对做 Fit）+ 一块 Ø20 孔的板（不等半径对照）
    p_small = make_plate("m17_small", HOLE_D)
    p_big = make_plate("m17_big", BIG_D)
    p_small2 = make_plate("m17_small2", HOLE_D)

    asm = new_part(session, "m17_asm")
    session.Parts.SetWork(asm)
    ufs.Part.SetDisplayPart(asm.Tag)
    ca = asm.ComponentAssembly
    comp = {}
    for nm, p in (("m17_small", p_small), ("m17_big", p_big),
                  ("m17_small2", p_small2)):
        c, _ = ca.AddComponent(p.FullPath, "1", "MODEL",
                               NXOpen.Point3d(*PLACE[nm]), identity(), 1)
        c.SetName(nm)
        comp[nm] = c
    print("COMPS=%d" % len(ca.RootComponent.GetChildren()))

    # 孔面/孔边从零件读（局部几何），再用各自拥有者组件 FindOccurrence 取实例
    f_small = hole_face(p_small, ufs, HOLE_R)
    f_big = hole_face(p_big, ufs, BIG_R)
    f_small2 = hole_face(p_small2, ufs, HOLE_R)
    e_small = hole_top_edge(p_small, ufs, HOLE_R, 10.0)
    e_big = hole_top_edge(p_big, ufs, BIG_R, 10.0)
    print("GEO faces=%d/%d/%d edges=%d/%d"
          % (f_small is not None, f_big is not None, f_small2 is not None,
             e_small is not None, e_big is not None))
    if None in (f_small, f_big, f_small2, e_small, e_big):
        print("TEST17_FAIL 几何准备不全（孔面/孔边）")
        return

    pos = ca.Positioner
    pos.BeginAssemblyConstraints()

    def run_stage(name, ctype, refs, ground):
        """refs = [(comp, geom), ...]（geom 必须由该组件拥有）；ground 为接地件。

        每个阶段自建 Fix 固定接地件，因此各阶段互相独立、位移可归因。
        """
        snap = dict((nm, pose_of(comp[nm])) for nm in PLACE)
        con = None
        c_fix = None
        dof_after = {}
        try:
            c_fix = pos.CreateConstraint(True)
            c_fix.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
            c_fix.CreateConstraintReference(comp[ground], comp[ground],
                                            False, False, False)
            c_fix.SetName(name + "_FIX")
            con = pos.CreateConstraint(True)
            con.ConstraintType = ctype
            for c, g in refs:
                occ = c.FindOccurrence(g)
                if occ is None:
                    raise RuntimeError("FindOccurrence returned None")
                con.CreateConstraintReference(c, occ, False, False, False)
            con.SetName(name)
            mark = session.SetUndoMark(
                NXOpen.Session.MarkVisibility.Invisible, name)
            session.UpdateManager.DoUpdate(mark)
            net = pos.EstablishNetwork()
            net.AddConstraint(c_fix)
            net.AddConstraint(con)
            net.Solve()
            net.ApplyToModel()
            pos.ClearNetwork()
            st = solve_status(con)
            # DOF 必须在删约束之前读：删完再读必然是 3T+3R（测量伪影）
            for nm in PLACE:
                dof_after[nm] = dof_of(comp[nm])
        finally:
            for c in (c_fix, con):
                if c is not None:
                    try:
                        c.Persistent = False
                    except Exception:
                        pass
            try:
                pos.DeleteNonPersistentConstraints()
            except Exception:
                pass
        moved = {}
        for nm in PLACE:
            now = pose_of(comp[nm])
            moved[nm] = dev6(snap[nm], now)
            print("%s_MOVE %-11s dev=%.4f o=(%.3f,%.3f,%.3f) dof=%s"
                  % (name, nm, moved[nm], now[0], now[1], now[2],
                     dof_after.get(nm, "?")))
        return st, moved, pose_of(comp[ground])

    # ---- A) 圆边 Concentric：报 Solved，且件真的被拉到目标轴上 ----
    def stage_edge_concentric():
        st, moved, _ = run_stage(
            "CONC_EDGE", NXOpen.Positioning.Constraint.Type.Concentric,
            [(comp["m17_small"], e_small), (comp["m17_big"], e_big)],
            "m17_small")
        print("CONC_EDGE status=%s" % st)
        if st != "Solved":
            raise RuntimeError("edge concentric status %s != Solved" % st)
        if moved["m17_big"] <= MOVE_MIN:
            raise RuntimeError(
                "edge concentric did not move the part (dev=%.4f) - the "
                "documented 'Solved but constrains nothing' hazard is back; "
                "re-measure references/assembly.md A.5" % moved["m17_big"])
        print("CONC_EDGE_MOVED dev=%.4f (status alone would not show this)"
              % moved["m17_big"])
    stage("conc_edge", stage_edge_concentric)

    # ---- A2) 拖动复验：圆边 Concentric 是不是一个真转动副（0T+1R）？
    #      按本技能自己的方法学，静态 DOF 读数不算数 —— 必须拖动后量几何。
    #      纯转动的判据：绕轴转 REV_DEG 被允许，沿轴平移 SLIDE_MM 被拒绝。
    def stage_edge_revolute():
        c_fix = None
        con = None
        try:
            c_fix = pos.CreateConstraint(True)
            c_fix.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
            c_fix.CreateConstraintReference(comp["m17_small"], comp["m17_small"],
                                            False, False, False)
            c_fix.SetName("REV_FIX")
            con = pos.CreateConstraint(True)
            con.ConstraintType = NXOpen.Positioning.Constraint.Type.Concentric
            for c, g in ((comp["m17_small"], e_small), (comp["m17_big"], e_big)):
                occ = c.FindOccurrence(g)
                if occ is None:
                    raise RuntimeError("FindOccurrence returned None")
                con.CreateConstraintReference(c, occ, False, False, False)
            con.SetName("REV_edge")
            mark = session.SetUndoMark(
                NXOpen.Session.MarkVisibility.Invisible, "rev17")
            session.UpdateManager.DoUpdate(mark)
            net = pos.EstablishNetwork()
            net.AddConstraint(c_fix)
            net.AddConstraint(con)
            net.Solve()
            net.ApplyToModel()
            pos.ClearNetwork()
            st = solve_status(con)
            p0 = pose_of(comp["m17_big"])
            print("REV status=%s dof=%s pose=(%.3f,%.3f,%.3f,%.3f)"
                  % (st, dof_of(comp["m17_big"]), p0[0], p0[1], p0[2], p0[3]))
            if st != "Solved":
                raise RuntimeError("revolute probe status %s != Solved" % st)

            def drag(label, vec, mat):
                n = pos.EstablishNetwork()
                n.AddConstraint(c_fix)
                n.AddConstraint(con)
                n.NonMovingGroupGrounded = False
                n.BeginDrag()
                n.SetMovingGroup([comp["m17_big"]])
                n.DragByTransform(vec, mat)
                n.Solve()
                n.ApplyToModel()
                n.EndDrag()
                pos.ClearNetwork()
                return pose_of(comp["m17_big"])

            p1 = drag("rot", NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(REV_DEG))
            dang = abs(p1[3] - p0[3])
            lat = max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))
            print("REV_ROT dang=%.4f lateral=%.4f" % (dang, lat))
            if abs(dang - REV_DEG) > 0.5:
                raise RuntimeError("rotation about the hole axis was not free: "
                                   "dang=%.4f (asked %.1f)" % (dang, REV_DEG))
            if lat > ALIGN_TOL:
                raise RuntimeError("rotation dragged the axis sideways: %.4f" % lat)

            p2 = drag("slide", NXOpen.Vector3d(0.0, 0.0, SLIDE_MM), identity())
            dz = abs(p2[2] - p1[2])
            lat2 = max(abs(p2[0] - p1[0]), abs(p2[1] - p1[1]))
            print("REV_SLIDE dz=%.4f lateral=%.4f (pure revolute => dz ~ 0)"
                  % (dz, lat2))
            if dz > ALIGN_TOL:
                raise RuntimeError("axial slide was NOT resisted (dz=%.4f) - "
                                   "this is no longer a pure revolute 0T+1R" % dz)
            print("REV_HOLDS rot=%.1fdeg slide_rejected=%.1fmm" % (dang, SLIDE_MM))
        finally:
            for c in (c_fix, con):
                if c is not None:
                    try:
                        c.Persistent = False
                    except Exception:
                        pass
            try:
                pos.DeleteNonPersistentConstraints()
            except Exception:
                pass
    stage("edge_revolute", stage_edge_revolute)

    # ---- B) 圆柱面 Concentric：CannotSolve ----
    def stage_face_concentric():
        st, moved, _ = run_stage(
            "CONC_FACE", NXOpen.Positioning.Constraint.Type.Concentric,
            [(comp["m17_small"], f_small), (comp["m17_big"], f_big)],
            "m17_small")
        print("CONC_FACE status=%s" % st)
        if st != "CannotSolve":
            raise RuntimeError("face concentric status %s != CannotSolve" % st)
    stage("conc_face", stage_face_concentric)

    # ---- C) 正向对照：等半径 Fit 必须 Solved 且把件拉到同轴 ----
    def stage_fit_equal():
        st, moved, o_ground = run_stage(
            "FIT_EQUAL", NXOpen.Positioning.Constraint.Type.Fit,
            [(comp["m17_small"], f_small), (comp["m17_small2"], f_small2)],
            "m17_small")
        print("FIT_EQUAL status=%s" % st)
        if st != "Solved":
            raise RuntimeError("equal radius fit status %s != Solved" % st)
        if moved["m17_small2"] <= MOVE_MIN:
            raise RuntimeError("equal radius fit did not move the part "
                               "(dev=%.4f)" % moved["m17_small2"])
        o = pose_of(comp["m17_small2"])
        if abs(o[0] - o_ground[0]) > ALIGN_TOL or abs(o[1] - o_ground[1]) > ALIGN_TOL:
            raise RuntimeError("fit did not align the axes: small2=(%.4f,%.4f) "
                               "vs ground=(%.4f,%.4f)"
                               % (o[0], o[1], o_ground[0], o_ground[1]))
        print("FIT_EQUAL_ALIGNED dev=%.4f x=%.4f y=%.4f"
              % (moved["m17_small2"], o[0], o[1]))
    stage("fit_equal", stage_fit_equal)

    # ---- D) 不等半径 Fit：InternallyInconsistent ----
    def stage_fit_unequal():
        st, moved, _ = run_stage(
            "FIT_UNEQUAL", NXOpen.Positioning.Constraint.Type.Fit,
            [(comp["m17_small"], f_small), (comp["m17_big"], f_big)],
            "m17_small")
        print("FIT_UNEQUAL status=%s" % st)
        if st != "InternallyInconsistent":
            raise RuntimeError(
                "unequal radius fit status %s != InternallyInconsistent" % st)
    stage("fit_unequal", stage_fit_unequal)

    # ---- E) 死路 1：内部专用枚举赋值即抛（放最后，避免垃圾约束污染上面各阶段） ----
    def stage_dead_types():
        rejected = 0
        for nm in DEAD_TYPES:
            try:
                c = pos.CreateConstraint(True)
                c.ConstraintType = getattr(
                    NXOpen.Positioning.Constraint.Type, nm)
                print("DEAD_TYPE %-12s UNEXPECTED_ACCEPTED" % nm)
                c.Persistent = False
            except Exception as exc:
                msg = str(exc)
                ok = "not valid" in msg
                print("DEAD_TYPE %-12s %s"
                      % (nm, "EXPECTED_REJECTED" if ok else
                         "OTHER::" + msg[:70]))
                if ok:
                    rejected += 1
        print("DEAD_TYPES_REJECTED=%d/%d" % (rejected, len(DEAD_TYPES)))
        if rejected != len(DEAD_TYPES):
            raise RuntimeError("%d/%d internal-only enum types were rejected"
                               % (rejected, len(DEAD_TYPES)))
    stage("dead_types", stage_dead_types)

    pos.EndAssemblyConstraints()

    if FAILED_STAGES:
        print("TEST17_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    print("TEST17_DONE dead_types=%d fit_unequal=InternallyInconsistent "
          "conc_face=CannotSolve conc_edge=Solved" % len(DEAD_TYPES))


if __name__ == "__main__":
    main()
