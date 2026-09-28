# -*- coding: utf-8 -*-
# Test 16: 装配运动连接 —— Fit(圆柱面) 做转动副 + Bond 让附属件跟动 + 拖动验证
#
# 覆盖（NX12 批处理，2026-09-15 实测，源自四连杆机构的装配改造）：
#   * Fit 作用在**两个等半径圆柱孔面**上 = 唯一可用的转动副基元；
#     被约束件被故意移开后解算应弹回同轴（本测试通过与否可证伪：解算前
#     孔轴间距 36.05 mm，解算后应 ≈0）
#   * Bond = 附属件与宿主件构成刚性组，宿主被拖动时附属件跟动
#   * 拖动配方：EstablishNetwork → NonMovingGroupGrounded=False →
#     SetMovingGroup → DragByTransform → Solve → ApplyToModel → EndDrag
#   * Component.GetDegreesOfFreedom() 在批处理下**可用**（本测试把实测值
#     打印出来；旧笔记说"数值滞后"见 references/assembly-drafting.md §A.2）
#
# 死路（Concentric / Hinge / 不等半径 Fit）不放在本文件，见对应用例
#   scripts/tests/17_motion_deadends.py（2026-09-20 起为正式检查，含圆边 Concentric
#   的拖动复验：单约束即得纯转动 0T+1R）
#
# 成功标志：TEST16_DONE 且 BENCH_PASS
import math
import os

import NXOpen
import NXOpen.Assemblies
import NXOpen.Features
import NXOpen.Positioning
import NXOpen.UF


import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.session import new_part
from nxlib.modeling import add_thru_hole, block, find_planar_face

# 板件与孔（孔半径必须相等，Fit 才成立）
BASE_ORG = (-50.0, -30.0, 0.0)
BASE_L, BASE_W, BASE_T = 100.0, 60.0, 10.0
LINK_ORG = (-20.0, -12.0, 0.0)
LINK_L, LINK_W, LINK_T = 140.0, 24.0, 8.0
PIN_ORG = (-6.0, -6.0, 0.0)
PIN_L, PIN_W, PIN_H = 12.0, 12.0, 30.0
HOLE_D = 10.0
HOLE_R = HOLE_D / 2.0

# 装配放置：link 的孔轴故意偏离 base 的孔轴
BASE_AT = (0.0, 0.0, 0.0)
LINK_AT = (30.0, 20.0, 25.0)      # 孔轴 XY 偏 (30,20) -> 间距 36.055
PIN_AT = (40.0, 30.0, 12.0)

TOL = 0.01
DRAG_DEG = 5.0

PARTS = {
    "m16_base": (BASE_ORG, (BASE_L, BASE_W, BASE_T)),
    "m16_link": (LINK_ORG, (LINK_L, LINK_W, LINK_T)),
    "m16_pin": (PIN_ORG, (PIN_L, PIN_W, PIN_H)),
}


def identity():
    m = NXOpen.Matrix3x3()
    m.Xx = 1.0
    m.Yy = 1.0
    m.Zz = 1.0
    return m


def rot_z(deg):
    a = math.radians(deg)
    m = NXOpen.Matrix3x3()
    m.Xx, m.Xy, m.Xz = math.cos(a), math.sin(a), 0.0
    m.Yx, m.Yy, m.Yz = -math.sin(a), math.cos(a), 0.0
    m.Zx, m.Zy, m.Zz = 0.0, 0.0, 1.0
    return m


def cols(m):
    return ((m.Xx, m.Xy, m.Xz), (m.Yx, m.Yy, m.Yz), (m.Zx, m.Zy, m.Zz))


def to_local(o, m, p):
    """世界点 -> 组件局部坐标（列向量 = 局部轴，故用点积投影）"""
    c1, c2, c3 = cols(m)
    d = (p[0] - o.X, p[1] - o.Y, p[2] - o.Z)
    return (sum(d[i] * c1[i] for i in range(3)),
            sum(d[i] * c2[i] for i in range(3)),
            sum(d[i] * c3[i] for i in range(3)))


def xf(o, m, p):
    """组件局部点 -> 世界点（o 可以是 Point3d 或三元组）"""
    oo = (o.X, o.Y, o.Z) if hasattr(o, "X") else tuple(o)
    c1, c2, c3 = cols(m)
    return tuple(oo[i] + p[0] * c1[i] + p[1] * c2[i] + p[2] * c3[i]
                 for i in range(3))


def norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 1e-12 else (0.0, 0.0, 1.0)


def line_line_dist(p1, d1, p2, d2):
    d1, d2 = norm(d1), norm(d2)
    r = tuple(p2[i] - p1[i] for i in range(3))
    a = sum(d1[i] * d1[i] for i in range(3))
    b = sum(d1[i] * d2[i] for i in range(3))
    c = sum(d2[i] * d2[i] for i in range(3))
    d = sum(d1[i] * r[i] for i in range(3))
    e = sum(d2[i] * r[i] for i in range(3))
    den = a * c - b * b
    if abs(den) < 1e-12:
        rr = tuple(r[i] - d * d1[i] for i in range(3))
        return math.sqrt(sum(x * x for x in rr))
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    q1 = tuple(p1[i] + s * d1[i] for i in range(3))
    q2 = tuple(p2[i] + t * d2[i] for i in range(3))
    return math.sqrt(sum((q1[i] - q2[i]) ** 2 for i in range(3)))


def xfd(m, v):
    c1, c2, c3 = cols(m)
    return tuple(v[0] * c1[i] + v[1] * c2[i] + v[2] * c3[i] for i in range(3))


def hole_faces(part, ufs, r_want):
    """局部坐标下的圆柱孔面（半径按 r_want 筛）"""
    out = []
    for b in part.Bodies:
        for f in b.GetFaces():
            data = ufs.Modeling.AskFaceData(f.Tag)
            if data[0] != 16:          # 16 = cylindrical
                continue
            r = float(data[4])
            if abs(r - r_want) > 0.1:
                continue
            out.append((f, (float(data[1][0]), float(data[1][1]),
                            float(data[1][2])),
                        (float(data[2][0]), float(data[2][1]),
                         float(data[2][2]))))
    return out


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


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    parts = {}

    # 幂等：清掉本用例旧产物（FileNew 不覆盖，见 SKILL.md §3 坑位 2）
    for stale in list(PARTS) + ["m16_asm"]:
        sp = os.path.abspath(stale + ".prt")
        if os.path.exists(sp):
            os.remove(sp)

    # ---- 1) 建三个零件：两块带等半径孔的板 + 一根销 ----------
    for name, (org, lengths) in PARTS.items():
        p = new_part(name=name)
        session.Parts.SetWork(p)
        ufs.Part.SetDisplayPart(p.Tag)
        body = block(p, NXOpen.Point3d(*org), str(lengths[0]), str(lengths[1]), str(lengths[2]))
        unit = p.UnitCollection.GetBase("Length")
        p.Expressions.CreateSystemExpressionWithUnits(
            "HOLE_D = %.4f" % HOLE_D, unit)
        parts[name] = p
        if name != "m16_pin":
            add_thru_hole(p, body, 0.0, 0.0, lengths[2], "HOLE_D")
            hf = hole_faces(p, ufs, HOLE_R)
            print("PART %-8s bodies=%d hole_faces=%d"
                  % (name, len(list(p.Bodies)), len(hf)))
            if not hf:
                print("TEST16_FAIL 零件 %s 未生成 r=%.1f 孔面" % (name, HOLE_R))
                return
        ufs.Part.Save()
        # Commit/Save 成功 != 落盘：文件存在且非空是唯一证据（SKILL.md §3）
        sp_path = os.path.abspath(name + ".prt")
        assert os.path.exists(sp_path) and os.path.getsize(sp_path) > 0, \
            "零件 %s 未落盘" % name
    print("PARTS_OK")

    # ---- 2) 装配：base 固定，link 故意放偏，pin 挂在 link 旁 ----------
    asm = new_part(name="m16_asm")
    session.Parts.SetWork(asm)
    ufs.Part.SetDisplayPart(asm.Tag)
    ca = asm.ComponentAssembly
    place = {
        "m16_base": BASE_AT,
        "m16_link": LINK_AT,
        "m16_pin": PIN_AT,
    }
    comp = {}
    for name in PARTS:
        c, ls = ca.AddComponent(parts[name].FullPath, "1", "MODEL",
                                NXOpen.Point3d(*place[name]), identity(), 1)
        c.SetName(name)
        comp[name] = c
    print("COMPS=%d" % len(ca.RootComponent.GetChildren()))

    # 孔面局部几何（从零件读，避免依赖实例面）
    geo = {}
    for name in ("m16_base", "m16_link"):
        p = parts[name]
        ufs.Part.SetDisplayPart(p.Tag)
        hf = hole_faces(p, ufs, HOLE_R)
        geo[name] = hf[0]
    # 必须显式切回装配件：ufs.Part.Save() 保存的是**显示部件**，
    # 忘记切回会让结尾的保存静默写错对象（本用例 2026-09-15 实测踩到）
    ufs.Part.SetDisplayPart(asm.Tag)

    def axis_of(name):
        o, m = comp[name].GetPosition()
        _, lp, lv = geo[name]
        return xf(o, m, lp), xfd(m, lv)

    # ---- 3) 解算前：孔轴应明显错开（falsify 基线） ----------
    a1, d1 = axis_of("m16_base")
    a2, d2 = axis_of("m16_link")
    gap0 = line_line_dist(a1, d1, a2, d2)
    print("GAP_BEFORE_SOLVE=%.4f" % gap0)
    if gap0 < 1.0:
        print("TEST16_FAIL 初始位姿就同轴，无法证明 Fit 生效")
        return

    # ---- 4) 建约束：Fix(base) + Fit(两孔) + Bond(pin 挂 link) ----------
    pos = ca.Positioner
    pos.BeginAssemblyConstraints()
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "t16")

    c_fix = pos.CreateConstraint(True)
    c_fix.ConstraintType = NXOpen.Positioning.Constraint.Type.Fix
    c_fix.CreateConstraintReference(comp["m16_base"], comp["m16_base"],
                                    False, False, False)
    c_fix.SetName("FIX_base")

    c_fit = pos.CreateConstraint(True)
    c_fit.ConstraintType = NXOpen.Positioning.Constraint.Type.Fit
    for nm in ("m16_base", "m16_link"):
        f = geo[nm][0]
        c_fit.CreateConstraintReference(comp[nm], comp[nm].FindOccurrence(f),
                                        False, False, False)
    c_fit.SetName("REV_link")

    c_bond = pos.CreateConstraint(True)
    c_bond.ConstraintType = NXOpen.Positioning.Constraint.Type.Bond
    c_bond.CreateConstraintReference(comp["m16_pin"], comp["m16_pin"],
                                     False, False, False)
    c_bond.CreateConstraintReference(comp["m16_link"], comp["m16_link"],
                                     False, False, False)
    c_bond.SetName("BOND_pin")

    session.UpdateManager.DoUpdate(mark)
    cons = [c_fix, c_fit, c_bond]
    sts = {}
    for c in cons:
        sts[c.Name] = solve_status(c)
    print("STATUS_BEFORE_SOLVE=%s" % sts)

    # ---- 5) 解算：link 应弹回同轴 ----------
    net = pos.EstablishNetwork()
    for c in cons:
        net.AddConstraint(c)
    err = net.Solve()
    net.ApplyToModel()
    pos.ClearNetwork()
    print("SOLVE_ERR=%s" % err)

    a1, d1 = axis_of("m16_base")
    a2, d2 = axis_of("m16_link")
    gap1 = line_line_dist(a1, d1, a2, d2)
    o_link, _ = comp["m16_link"].GetPosition()
    print("GAP_AFTER_SOLVE=%.4f  (was %.4f)" % (gap1, gap0))
    print("LINK_ORIGIN_AFTER=(%.4f, %.4f, %.4f)"
          % (o_link.X, o_link.Y, o_link.Z))

    dof = comp["m16_link"].GetDegreesOfFreedom()
    print("LINK_DOF=%dT+%dR" % (dof.NumTranslational, dof.NumRotational))

    sts = {}
    all_solved = True
    for c in cons:
        sts[c.Name] = solve_status(c)
        if sts[c.Name] != "Solved":
            all_solved = False
    print("STATUS_AFTER_SOLVE=%s" % sts)

    fit_ok = (gap1 <= TOL) and all_solved
    print("FIT_REVOLUTE=%s" % ("PASS" if fit_ok else "FAIL"))

    # ---- 6) 拖动：绕自身原点转 5°（link 原点在孔轴上 = 绕铰轴转），
    #         pin 应跟随（在 link 局部坐标里的位姿不变） ----------
    o_pin0, _ = comp["m16_pin"].GetPosition()
    o_l0, m_l0 = comp["m16_link"].GetPosition()
    pin_local_before = to_local(o_l0, m_l0,
                                (o_pin0.X, o_pin0.Y, o_pin0.Z))
    print("PIN_LOCAL_BEFORE=(%.4f, %.4f, %.4f)" % pin_local_before)

    net = pos.EstablishNetwork()
    for c in cons:
        net.AddConstraint(c)
    net.NonMovingGroupGrounded = False
    net.BeginDrag()
    net.SetMovingGroup([comp["m16_link"]])
    net.DragByTransform(NXOpen.Vector3d(0.0, 0.0, 0.0), rot_z(DRAG_DEG))
    err2 = net.Solve()
    net.ApplyToModel()
    net.EndDrag()
    pos.ClearNetwork()
    print("DRAG_ERR=%s" % err2)

    o_link2, m_link2 = comp["m16_link"].GetPosition()
    ang = math.degrees(math.atan2(m_link2.Yx, m_link2.Xx)) \
        - math.degrees(math.atan2(m_l0.Yx, m_l0.Xx))
    ang = (ang + 180.0) % 360.0 - 180.0
    print("LINK_ROTATED=%.4f deg (requested %.1f)" % (ang, DRAG_DEG))

    a1, d1 = axis_of("m16_base")
    a2, d2 = axis_of("m16_link")
    gap2 = line_line_dist(a1, d1, a2, d2)
    print("GAP_AFTER_DRAG=%.4f" % gap2)

    o_pin1, _ = comp["m16_pin"].GetPosition()
    o_l1, m_l1 = comp["m16_link"].GetPosition()
    pin_local_after = to_local(o_l1, m_l1, (o_pin1.X, o_pin1.Y, o_pin1.Z))
    dev = max(abs(pin_local_after[i] - pin_local_before[i])
              for i in range(3))
    print("PIN_LOCAL_AFTER=(%.4f, %.4f, %.4f) dev=%.5f"
          % (pin_local_after[0], pin_local_after[1], pin_local_after[2], dev))

    drag_ok = (abs(ang) > DRAG_DEG * 0.9) and (gap2 <= TOL) and (dev <= TOL)
    print("DRAG_AND_BOND=%s" % ("PASS" if drag_ok else "FAIL"))
    pos.EndAssemblyConstraints()

    # ---- 7) 结论 ----------
    if fit_ok and drag_ok:
        # 显式保存装配件（不依赖"显示部件是谁"）；SaveComponents=True 让
        # 改过位姿的组件一并落盘
        asm.Save(NXOpen.BasePart.SaveComponents.TrueValue,
                 NXOpen.BasePart.CloseAfterSave.FalseValue)
        asm_path = os.path.abspath("m16_asm.prt")
        assert os.path.exists(asm_path) and os.path.getsize(asm_path) > 0, \
            "装配件 m16_asm 未落盘"
        print("ASM_SAVED bytes=%d" % os.path.getsize(asm_path))
        print("BENCH_PASS")
    else:
        print("BENCH_FAIL fit=%s drag=%s" % (fit_ok, drag_ok))
    print("TEST16_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print(traceback.format_exc())
        print("TEST16_EXC")
