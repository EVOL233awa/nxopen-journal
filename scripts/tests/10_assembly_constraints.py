# -*- coding: utf-8 -*-
# Test J: assembly mating constraints (Touch), occurrence faces via
#         FindOccurrence, constraint network solve, DOF query, refset switch.
# Covers: ComponentAssembly.Positioner, BeginAssemblyConstraints,
#         CreateConstraint(True), ComponentConstraint.ConstraintType,
#         CreateConstraintReference(movable comp, occurrence face),
#         Network.Solve, Component.GetDegreesOfFreedom,
#         ComponentAssembly.ReplaceReferenceSet.
# Known limits (NX12 Python wrapper, tested): Constraint.Type property is
#         read-only (use ConstraintType); Distance offset setter is
#         "Not yet implemented" (position via AddComponent placement or
#         Touch pairs instead).
import math
import os
import sys

import NXOpen
import NXOpen.Assemblies
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.assembly import add_component, find_proto_face, touch_pair
from nxlib.modeling import block
from nxlib.session import new_part, set_work
from nxlib.testing import stage


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    for stale in ("asmc_base.prt", "asmc_pin.prt", "asmc_assy.prt",
                  "asmc_rail.prt", "asmc_slider.prt", "asmc_slide.prt"):
        sp = os.path.abspath(stale)
        if os.path.exists(sp):
            os.remove(sp)

    state = {}

    def s1():
        base = new_part(name="asmc_base")
        set_work(base)
        blk_base = block(base, NXOpen.Point3d(0.0, 0.0, 0.0), "120", "80", "10")
        blk_base.SetName("BaseBlock")
        ufs.Part.Save()
        pin = new_part(name="asmc_pin")
        set_work(pin)
        blk_pin = block(pin, NXOpen.Point3d(0.0, 0.0, 0.0), "12", "12", "40")
        blk_pin.SetName("PinBlock")
        ufs.Part.Save()
        state["base"] = base
        state["pin"] = pin
        state["base_top"] = find_proto_face(base, "Z", 1)
        state["pin_bottom"] = find_proto_face(pin, "Z", -1)

        # 双平面 Touch 滑块试件：导轨 100x20x10 + 滑块 10x10x10
        rail = new_part(name="asmc_rail")
        set_work(rail)
        block(rail, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "20", "10")
        ufs.Part.Save()
        slider = new_part(name="asmc_slider")
        set_work(slider)
        block(slider, NXOpen.Point3d(0.0, 0.0, 0.0), "10", "10", "10")
        ufs.Part.Save()
        state["rail"] = rail
        state["slider"] = slider
        state["rail_top"] = find_proto_face(rail, "Z", 1)
        state["rail_side"] = find_proto_face(rail, "Y", 1)
        state["slider_bottom"] = find_proto_face(slider, "Z", -1)
        state["slider_side"] = find_proto_face(slider, "Y", -1)
        print("PROTO_FACES=" + str(state["base_top"] is not None) + "/" +
              str(state["pin_bottom"] is not None) + "/" +
              str(None not in (state["rail_top"], state["rail_side"],
                               state["slider_bottom"], state["slider_side"])))
    stage("components", s1)

    def s2():
        assy = new_part(name="asmc_assy")
        set_work(assy)
        ufs.Part.SetDisplayPart(assy.Tag)
        c1, st1 = add_component(assy, state["base"].FullPath, NXOpen.Point3d(0.0, 0.0, 0.0))
        c2, st2 = add_component(assy, state["pin"].FullPath, NXOpen.Point3d(40.0, 30.0, 30.0))
        state["assy"] = assy
        state["c1"] = c1
        state["c2"] = c2
        print("COMPS=" + str(len(assy.ComponentAssembly.RootComponent.GetChildren())))
    stage("assembly", s2)

    def s3():
        err = touch_pair(session, state["assy"], state["c2"], state["pin_bottom"],
                         state["c1"], state["base_top"], "PinOnBase_Touch")
        print("SOLVE_ERR=" + str(err))
    stage("touch_constraint", s3)

    def s4():
        pos2 = state["c2"].GetPosition()
        dof = state["c2"].GetDegreesOfFreedom()
        n_dof = dof.NumTranslational + dof.NumRotational
        print("PIN_POS_Z=%.3f" % pos2[0].Z)
        print("PIN_DOF=" + str(n_dof))
        # pin placed at z=30 (bottom face), must be moved onto base top z=10
        if abs(pos2[0].Z - 10.0) < 1e-6:
            print("CONSTRAINT_PASS")
        else:
            print("CONSTRAINT_FAIL")
        ca = state["assy"].ComponentAssembly
        ca.ReplaceReferenceSet(state["c2"], "Entire Part")
        print("REFSET=" + state["c2"].ReferenceSet)
    stage("verify_and_refset", s4)

    # ---- A.3 组件阵列：线性方向 + 默认份数 → 子件数按份数增 ----
    def s5():
        assy = state["assy"]
        ca = assy.ComponentAssembly
        n0 = len(list(ca.RootComponent.GetChildren()))
        b = ca.CreateComponentPatternBuilder(
            NXOpen.Assemblies.ComponentPattern.Null)
        ps = b.PatternService
        ps.PatternType = ps.PatternEnum.Linear
        rd = ps.RectangularDefinition
        rd.XDirection = assy.Directions.CreateDirection(
            assy.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0)),
            NXOpen.Vector3d(1.0, 0.0, 0.0))
        b.ComponentPatternSet.Add(state["c2"])
        # NCopies 是 Expression（读回来不能 int()）；当前模式默认 2 份。
        copies_expr = rd.XSpacing.NCopies
        copies = int(round(float(
            str(getattr(copies_expr, "RightHandSide", copies_expr)))))
        b.Validate()
        b.Commit()
        b.Destroy()
        n1 = len(list(ca.RootComponent.GetChildren()))
        print("COMPONENT_PATTERN copies=%d children=%d->%d"
              % (copies, n0, n1))
        if n1 != n0 + copies - 1:
            raise RuntimeError(
                "component pattern added %d children, expected %d "
                "(copies=%d)" % (n1 - n0, copies - 1, copies))
    stage("component_pattern", s5)

    # ---- A.1 MoveComponent：t 是增量、R 绕全局原点 ----
    def s6():
        ca = state["assy"].ComponentAssembly
        c2 = state["c2"]

        def ident():
            m = NXOpen.Matrix3x3()
            m.Xx = 1.0
            m.Yy = 1.0
            m.Zz = 1.0
            return m

        def rot_z(deg):
            a = math.radians(deg)
            m = NXOpen.Matrix3x3()
            m.Xx = math.cos(a)
            m.Xy = -math.sin(a)
            m.Yx = math.sin(a)
            m.Yy = math.cos(a)
            m.Zz = 1.0
            return m

        def move(t, r):
            mark = session.SetUndoMark(
                NXOpen.Session.MarkVisibility.Invisible, "move10")
            ca.MoveComponent(c2, t, r)
            session.UpdateManager.DoUpdate(mark)
            return c2.GetPosition()[0]

        o0 = c2.GetPosition()[0]
        o1 = move(NXOpen.Vector3d(5.0, 0.0, 0.0), ident())
        if abs((o1.X - o0.X) - 5.0) > 1e-6 \
                or abs(o1.Y - o0.Y) > 1e-6 or abs(o1.Z - o0.Z) > 1e-6:
            raise RuntimeError("MoveComponent(+5x) is not incremental: "
                               "(%.4f,%.4f,%.4f)->(%.4f,%.4f,%.4f)"
                               % (o0.X, o0.Y, o0.Z, o1.X, o1.Y, o1.Z))
        o2 = move(NXOpen.Vector3d(0.0, 7.0, 0.0), ident())
        if abs((o2.Y - o1.Y) - 7.0) > 1e-6:
            raise RuntimeError("MoveComponent(+7y) is not incremental: "
                               "%.4f->%.4f" % (o1.Y, o2.Y))
        o3 = move(NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(90.0))
        # rot_z(90) 按列写法传入，应用后是 -90°（assembly.md A.1 的方向约定：
        # +X -> -Y）。枢轴仍是全局原点：(x,y) -> (y,-x)。
        if abs(o3.X - o2.Y) > 1e-6 or abs(o3.Y + o2.X) > 1e-6 \
                or abs(o3.Z - o2.Z) > 1e-6:
            raise RuntimeError(
                "MoveComponent rotation is not about the global origin: "
                "(%.4f,%.4f)->(%.4f,%.4f), expected (%.4f,%.4f)"
                % (o2.X, o2.Y, o3.X, o3.Y, o2.Y, -o2.X))
        print("MOVE_COMPONENT incremental_ok pivot=global "
              "p0=(%.3f,%.3f) p1=(%.3f,%.3f) p2=(%.3f,%.3f) "
              "p3=(%.3f,%.3f)"
              % (o0.X, o0.Y, o1.X, o1.Y, o2.X, o2.Y, o3.X, o3.Y))
    stage("move_component_semantics", s6)

    # ---- A.2 移动副替代路线：两组平面 Touch → 只剩沿 X 平移 ----
    def s7():
        slide_assy = new_part(name="asmc_slide")
        set_work(slide_assy)
        ufs.Part.SetDisplayPart(slide_assy.Tag)
        rc, _ = add_component(slide_assy, state["rail"].FullPath,
                              NXOpen.Point3d(0.0, 0.0, 0.0))
        sc, _ = add_component(slide_assy, state["slider"].FullPath,
                              NXOpen.Point3d(40.0, 25.0, 10.0))
        state["slide_assy"] = slide_assy
        state["slide_rail"] = rc
        state["slide_comp"] = sc
        print("SLIDER_COMPS=2")
    stage("slider_two_plane_touch", s7)

    def s8():
        slide_assy = state["slide_assy"]
        comp = state["slide_comp"]
        rail = state["slide_rail"]
        pos = slide_assy.ComponentAssembly.Positioner
        pos.BeginAssemblyConstraints()
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Invisible, "slide10")
        net = None
        try:
            def mk_touch(movable, mface, base, bface, name):
                con = pos.CreateConstraint(True)
                con.ConstraintType = NXOpen.Positioning.Constraint.Type.Touch
                con.CreateConstraintReference(
                    movable, movable.FindOccurrence(mface), False, False, False)
                con.CreateConstraintReference(
                    base, base.FindOccurrence(bface), False, False, False)
                con.SetName(name)
                return con

            # 两条约束一次进同一网络：先 DoUpdate 提交，再 AddConstraint 求解
            # （与 touch_pair 同一时序；分两次建网络会让旧约束不参与拖动）
            con_fix = pos.CreateConstraint(True)
            con_fix.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
            con_fix.CreateConstraintReference(rail, rail, False, False, False)
            con_fix.SetName("Fix_Rail")
            con_z = mk_touch(comp, state["slider_bottom"], rail,
                             state["rail_top"], "Slide_Z")
            con_y = mk_touch(comp, state["slider_side"], rail,
                             state["rail_side"], "Slide_Y")
            session.UpdateManager.DoUpdate(mark)
            net = pos.EstablishNetwork()
            net.AddConstraint(con_fix)
            net.AddConstraint(con_z)
            net.AddConstraint(con_y)
            err = net.Solve()
            if err is not None:
                raise RuntimeError("two-plane Touch solve failed: %r" % (err,))
            net.ApplyToModel()
            p = comp.GetPosition()[0]
            p0 = (p.X, p.Y, p.Z)
            st = [c.GetConstraintStatus() for c in (con_fix, con_z, con_y)]
            dof = comp.GetDegreesOfFreedom()
            print("SLIDER_TOUCH pos=(%.3f,%.3f,%.3f) dof=%dT+%dR status=%r"
                  % (p0 + (dof.NumTranslational, dof.NumRotational,
                           [getattr(x, "value", None) for x in st])))
            grounded_default = net.NonMovingGroupGrounded
            net.NonMovingGroupGrounded = True
            grounded_set = net.NonMovingGroupGrounded
            net.NonMovingGroupGrounded = False

            # ⚠ DragByTranslation 在批处理里只搬组件位姿，随后 Solve 不回收
            #   越界位移（约束仍报 Solved）；改用 MoveComponent + 重建网络
            #   Solve 验证两条平面约束确实在拦 Y/Z。
            ident = NXOpen.Matrix3x3()
            ident.Xx = 1.0
            ident.Yy = 1.0
            ident.Zz = 1.0

            def move_and_resolve(vec):
                pos.ClearNetwork()
                m = session.SetUndoMark(
                    NXOpen.Session.MarkVisibility.Invisible, "slide_move")
                ca = slide_assy.ComponentAssembly
                ca.MoveComponent(comp, NXOpen.Vector3d(*vec), ident)
                session.UpdateManager.DoUpdate(m)
                session.DeleteUndoMark(m, "slide_move")
                net2 = pos.EstablishNetwork()
                net2.AddConstraint(con_fix)
                net2.AddConstraint(con_z)
                net2.AddConstraint(con_y)
                e = net2.Solve()
                net2.ApplyToModel()
                q = comp.GetPosition()[0]
                return e, (q.X, q.Y, q.Z)

            e1, p1 = move_and_resolve((5.0, 0.0, 0.0))
            e2, p2 = move_and_resolve((0.0, 5.0, 0.0))
            e3, p3 = move_and_resolve((0.0, 0.0, 5.0))
        finally:
            if net is not None:
                pos.ClearNetwork()
            pos.EndAssemblyConstraints()
            session.DeleteUndoMark(mark, "slide10")

        def delta(a, b):
            return tuple(a[i] - b[i] for i in range(3))

        d1 = delta(p1, p0)
        d2 = delta(p2, p1)
        d3 = delta(p3, p2)
        print("SLIDER_DRAG dX=%r dY=%r dZ=%r errs=%r/%r/%r"
              % (d1, d2, d3, e1, e2, e3))
        print("NONMOVING_GROUP_GROUNDED default=%r set=%r"
              % (grounded_default, grounded_set))
        ok = (e1 is None and e2 is None and e3 is None
              and abs(d1[0] - 5.0) <= 0.01 and abs(d1[1]) <= 0.01
              and abs(d1[2]) <= 0.01
              and all(abs(v) <= 0.01 for v in d2)
              and all(abs(v) <= 0.01 for v in d3))
        if not ok:
            raise RuntimeError("two-plane Touch slider moved off the rail: "
                               "%r/%r/%r" % (d1, d2, d3))
        if grounded_default is not False or grounded_set is not True:
            raise RuntimeError("NonMovingGroupGrounded default/set mismatch: "
                               "%r/%r" % (grounded_default, grounded_set))
    stage("slider_drag_and_grounded", s8)

    # ufs.Part.Save() 只保存显示部件；s7 已把显示件切到 asmc_slide，
    # 两个装配都显式保存，避免保存静默落到新件
    for key in ("assy", "slide_assy"):
        state[key].Save(NXOpen.BasePart.SaveComponents.TrueValue,
                        NXOpen.BasePart.CloseAfterSave.FalseValue)
    for key in ("assy", "slide_assy"):
        fp = state[key].FullPath
        assert os.path.exists(fp) and os.path.getsize(fp) > 0, \
            "save did not land: %s" % fp
    print("ASM_CONSTR_DONE")


if __name__ == "__main__":
    main()
