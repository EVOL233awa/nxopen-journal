# -*- coding: utf-8 -*-
"""Test 23: NX Motion 连接件 / UF struct 命名 / 自由度计数 回归（NX12 批处理）。

守的是 motion.md §M.5a~§M.5c 的三条结论：

A) MotionManager 的连接件集合真名 = `Springs` / `Dampers` / `Bushings` / `ScalarForces` …
   `ScalarSprings` / `ScalarDampers` / `ScalarBushings` 与类 `ScalarSpring` 等**都不存在**。

B) 三种连接件都能建成：
   - 枚举 `AttachmentType` 挂在**类**上（`M.ConnectorBuilder.AttachmentType` 或 `M.AttachmentType`），
     在实例上取会 AttributeError；
   - `ActionLink` / `ReactionLink` 是**只读容器**，必须写 `.Value`（SKILL.md 铁律 4）；
   - `ActionPoint` / `ReactionPoint` / `Name` 直接可写；
   - Commit 后各自集合计数 +1：弹簧 `Springs`、阻尼 `Dampers`、衬套 `Bushings`。
   - 阻尼器缺 `CoefficientType = Constant` → "A NULL value was encountered"；
     衬套缺 `BushingDefine.Orientation` → 同一个 "A NULL value"，而它要的是 **NXMatrix**
     （给 Direction 报 Expecting NXOpen.NXMatrix type），由部件坐标系 `csys.Orientation` 得到。

C) UF 接口的形状（SKILL.md §3 坑位 9）：
   - struct 类型是模块级 `NXOpen.UF.MotionInterference_Struct`，字段 `Solid1` / `Solid2`；
   - **out 参数即返回值**：`ufs.Motion.InitInterferenceStruct()` 是 0 参调用，传参必报错；
   - `ufs.Motion.AskGrueblerCount()` 返回整数；
   - `DriverMultiOperations` 只有三个驱动项：EulerAngle1 / PointOnCurve / TranslationZ。
"""
import os
import sys

import NXOpen
import NXOpen.Motion as M
import NXOpen.UF


import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS

HERE = os.path.dirname(__file__)
PARTS = os.path.join(HERE, "parts")
MASTER = os.path.join(PARTS, "t23_connectors.prt")

def set_expr(expr, value):
    expr.RightHandSide = str(value)


def build_sim(session, ufs):
    if not os.path.isdir(PARTS):
        os.makedirs(PARTS)
    if os.path.exists(MASTER):
        os.remove(MASTER)
    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.UseBlankTemplate = False
    fn.NewFileName = MASTER
    fn.Commit()
    fn.Destroy()
    master = session.Parts.Work
    ms = session.MotionSession
    ms.CreateSimulation(master)
    sim_part = None
    for p in session.Parts:
        if p is not None and (p.FullPath or "").lower().endswith(".sim"):
            sim_part = p
            break
    ms.InitializeSimulation(sim_part)
    ufs.Part.SetDisplayPart(sim_part.Tag)
    session.Parts.SetWork(sim_part)
    mm = sim_part.MotionManager
    pts = {"A": sim_part.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0)),
           "B": sim_part.Points.CreatePoint(NXOpen.Point3d(20.0, 0.0, 0.0)),
           "C": sim_part.Points.CreatePoint(NXOpen.Point3d(60.0, 0.0, 0.0)),
           "Cm1": sim_part.Points.CreatePoint(NXOpen.Point3d(10.0, 0.0, 0.0)),
           "Cm2": sim_part.Points.CreatePoint(NXOpen.Point3d(40.0, 0.0, 0.0))}
    links = {}
    for name, cmkey in (("L1", "Cm1"), ("L2", "Cm2")):
        lb = mm.Links.CreateLinkBuilder(M.Link.Null)
        lb.Name = name
        lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
        set_expr(lb.MassProperty.MassExpression, "0.010000")
        for ax in ("IxxExpression", "IyyExpression", "IzzExpression",
                   "IxyExpression", "IxzExpression", "IyzExpression"):
            set_expr(getattr(lb.MassProperty, ax), "1.000000")
        lb.MassProperty.MassCenter = pts[cmkey]      # ⚠ 必须 NXOpen.Point
        links[name] = lb.Commit()
        lb.Destroy()
    zd = sim_part.Directions.CreateDirection(pts["A"], NXOpen.Vector3d(0.0, 0.0, 1.0))
    jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
    jd = jb.JointDefine
    jd.JointType = M.JointDefine.Type.Revolute
    jd.FirstLink = links["L1"]
    jd.SecondLink = links["L2"]
    jd.FirstOrigin = pts["B"]
    jd.FirstVector = zd
    jd.Name = "J_AB"
    jb.Commit()
    jb.Destroy()
    return sim_part, mm, links, pts


def holders_case(mm):
    present = ("Springs", "Dampers", "Bushings", "ScalarForces", "VectorForces",
               "BodyContacts", "CurveContacts", "AnalyticalContacts",
               "ControlInputs", "PlantInputs", "PMDCMotors", "FlexBodies")
    missing = [n for n in present if getattr(mm, n, None) is None]
    absent_ok = [n for n in ("ScalarSprings", "ScalarDampers", "ScalarBushings")
                 if not hasattr(mm, n)]
    check("REG_CONNECTOR_HOLDERS", not missing and len(absent_ok) == 3,
          "missing=%s scalar_absent=%s" % (missing, absent_ok))
    check("REG_NO_SCALAR_CLASSES",
          not any(hasattr(M, n) for n in ("ScalarSpring", "ScalarDamper", "ScalarBushing")),
          "M.ScalarSpring/Damper/Bushing 均不存在")


def spring_case(mm, links, pts):
    n0 = len([x for x in mm.Springs])
    b = mm.Springs.CreateSpringBuilder(M.Spring.Null)

    owner = None
    for name, holder in (("M", M), ("M.ConnectorBuilder", getattr(M, "ConnectorBuilder", None))):
        if holder is not None and hasattr(holder, "AttachmentType"):
            owner = name
            break
    check("REG_SPRING_ENUM_OWNER", owner is not None, "AttachmentType owner=%s" % owner)
    if owner is None:
        b.Destroy()
        return

    # ⚠ 实例上 AttachmentType 是只读：赋值/读取都报 AttributeError（枚举类本身存在，
    #   但不需要设，本配方就是"不设它"跑通的）。这里守住"它仍是只读"这一事实。
    read_only = False
    try:
        b.AttachmentType = M.ConnectorBuilder.AttachmentType.Link
    except AttributeError:
        read_only = True
    check("REG_SPRING_ATTACHMENT_READONLY", read_only,
          "AttachmentType 实例上只读（枚举 owner=%s）" % owner)

    b.Name = "REG_SPRING"
    b.ActionLink.Value = links["L1"]         # ⚠ 只读容器：写 .Value
    b.ReactionLink.Value = links["L2"]
    b.ActionPoint = pts["B"]
    b.ReactionPoint = pts["C"]
    set_expr(b.StiffnessExpression, "10.0")
    set_expr(b.CoefficientExpression, "10.0")
    set_expr(b.FreeLengthExpression, "10.0")
    b.Validate()
    b.Commit()
    b.Destroy()
    n1 = len([x for x in mm.Springs])
    check("REG_SPRING_COMMIT", n1 == n0 + 1, "springs %d->%d" % (n0, n1))


def damper_case(mm, links, pts):
    """阻尼器（打通）。

    旧记录"DamperBuilder 没有 ActionLink/ReactionLink，连接关系无入口"是**读错日志**：
    这两个 SelectObject 一直在，真正缺的是 `CoefficientType = Constant`
    （不设它 Validate 报 "A NULL value was encountered"）。
    """
    d = mm.Dampers.CreateDamperBuilder(M.Damper.Null)
    n0 = len([x for x in mm.Dampers])
    try:
        d.Name = "REG_DAMPER"
        d.ActionLink.Value = links["L1"]
        d.ReactionLink.Value = links["L2"]
        d.ActionPoint = pts["B"]
        d.ReactionPoint = pts["C"]
        set_expr(d.CoefficientExpression, "1.0")
        d.CoefficientType = NXOpen.Motion.ConnectorCoefficientTypes.Constant
        d.Validate()
        d.Commit()
        n1 = len([x for x in mm.Dampers])
        check("REG_DAMPER_COMMIT", n1 == n0 + 1, "dampers %d->%d" % (n0, n1))
    except Exception as exc:
        check("REG_DAMPER_COMMIT", False, "%s: %s" % (type(exc).__name__,
                                                      str(exc)[:110]))
    d.Destroy()


def make_csys(part, pts):
    """部件坐标系：衬套的 Orientation 要 NXMatrix，只能由它取（Direction 不行）。"""
    xd = part.Directions.CreateDirection(pts["A"], NXOpen.Vector3d(1.0, 0.0, 0.0))
    zd = part.Directions.CreateDirection(pts["A"], NXOpen.Vector3d(0.0, 0.0, 1.0))
    xf = part.Xforms.CreateXformByPointXDirZDir(
        pts["A"], xd, zd, NXOpen.SmartObject.UpdateOption.WithinModeling, 1.0)
    return part.CoordinateSystems.CreateCoordinateSystem(
        xf, NXOpen.SmartObject.UpdateOption.WithinModeling)


def bushing_defs(b, links, pts):
    b.BushingDefine.Name = "REG_BUSH"
    b.BushingDefine.ActionLink.Value = links["L1"]
    b.BushingDefine.ReactionLink.Value = links["L2"]
    b.BushingDefine.ActionPoint = pts["B"]
    b.BushingDefine.ReactionPoint = pts["C"]
    b.BushingType = b.BushingTypes.General
    CC = NXOpen.Motion.ConnectorCoefficientTypes
    comp = b.BushingStiffnessCoefficients.GeneralTranslationalStiffnessCoefficients
    tc = b.BushingStiffnessCoefficients.GeneralTorsionalStiffnessCoefficients
    for c in (comp, tc):
        for ax in ("X", "Y", "Z"):
            set_expr(getattr(c, ax + "Expression"), "100.0")
        c.CoefficientsType = CC.Constant
        c.XCoefficientsType = CC.Constant


def bushing_case(mm, links, pts, sim_part):
    """衬套（打通）：真正缺的那一项是 `BushingDefine.Orientation`，
    而且它要的是 **NXMatrix**（给 Direction 报 Expecting NXOpen.NXMatrix type），
    来源是部件坐标系的 `csys.Orientation`。不设它 → Commit 报 "A NULL value"。
    """
    b = mm.Bushings.CreateBushingBuilder(M.Bushing.Null)
    bushing_defs(b, links, pts)
    msg = "committed"
    try:
        b.Validate()
        b.Commit()
    except Exception as exc:
        msg = "%s: %s" % (type(exc).__name__, str(exc)[:90])
    b.Destroy()
    check("REG_BUSHING_ORIENTATION_REQUIRED", "NULL" in msg,
          "不给 Orientation 时：%s" % msg)

    csys = make_csys(sim_part, pts)
    check("REG_BUSHING_CSYS_MATRIX",
          type(csys.Orientation).__name__ == "NXMatrix",
          "csys.Orientation 类型=%s" % type(csys.Orientation).__name__)

    b = mm.Bushings.CreateBushingBuilder(M.Bushing.Null)
    n0 = len([x for x in mm.Bushings])
    try:
        bushing_defs(b, links, pts)
        b.BushingDefine.Orientation = csys.Orientation
        b.Validate()
        b.Commit()
        n1 = len([x for x in mm.Bushings])
        check("REG_BUSHING_COMMIT", n1 == n0 + 1, "bushings %d->%d" % (n0, n1))
    except Exception as exc:
        check("REG_BUSHING_COMMIT", False, "%s: %s" % (type(exc).__name__,
                                                       str(exc)[:110]))
    b.Destroy()


def uf_shape_case(ufs, mm):
    try:
        st = NXOpen.UF.MotionInterference_Struct()
        fields = sorted(n for n in dir(st) if not n.startswith("_"))
        check("REG_UF_STRUCT_NAME", fields == ["Solid1", "Solid2"], "fields=%s" % fields)
    except Exception as exc:
        check("REG_UF_STRUCT_NAME", False, "%s: %s" % (type(exc).__name__, exc))

    got = ufs.Motion.InitInterferenceStruct()          # ⚠ 0 参：out 参数是返回值
    check("REG_UF_OUTPARAM_IS_RETURN", got is not None,
          "InitInterferenceStruct() -> %s" % type(got).__name__)
    try:
        ufs.Motion.InitInterferenceStruct(got)
        raised = False
    except Exception:
        raised = True
    check("REG_UF_OUTPARAM_REJECTS_ARG", raised,
          "传 1 个实参被拒（out 参数不能当入参传）")

    n = ufs.Motion.AskGrueblerCount()
    check("REG_GRUEBLER_INT", isinstance(n, int) and n >= 0, "AskGrueblerCount()=%r" % n)

    jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
    ops = sorted(n for n in dir(jdb.DriverMultiOperations)
                 if not n.startswith("_") and n not in ("Null", "Tag"))
    jdb.Destroy()
    check("REG_DRIVER_OPS",
          ops == ["MotionEulerAngle1", "MotionPointOnCurve", "MotionTranslationZ"],
          "DriverMultiOperations=%s (+Tag)" % ops)


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    sim_part, mm, links, pts = build_sim(session, ufs)
    say("sim=%s" % sim_part.Leaf)

    holders_case(mm)
    spring_case(mm, links, pts)
    damper_case(mm, links, pts)
    bushing_case(mm, links, pts, sim_part)
    uf_shape_case(ufs, mm)

    ok = all(v for _, v in RESULTS)
    failed = [n for n, v in RESULTS if not v]
    say("TEST23_CASES=%d" % len(RESULTS))
    if not ok:
        say("TEST23_FAIL failed=%s" % failed)
        raise RuntimeError("test 23 failed: %s" % failed)
    say("TEST23_DONE")


if __name__ == "__main__":
    main()
