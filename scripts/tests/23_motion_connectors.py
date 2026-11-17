# -*- coding: utf-8 -*-
"""Test 23: NX Motion 连接件 / UF struct 命名 / 自由度计数 回归（NX12 批处理）。

守的是 motion.md §M.5a~§M.5c 的三条结论：

A) MotionManager 的连接件集合真名 = `Springs` / `Dampers` / `Bushings` / `ScalarForces` …
   `ScalarSprings` / `ScalarDampers` / `ScalarBushings` 与类 `ScalarSpring` 等**都不存在**。

B) 三种连接件都能建成：
   - 枚举 `AttachmentType` 挂在**类**上（`M.ConnectorBuilder.AttachmentType` 或 `M.AttachmentType`），
     实例上可读（返回枚举类），赋值报 AttributeError（只读）；
   - `ActionLink` / `ReactionLink` 是**只读容器**，必须写 `.Value`（SKILL.md 铁律 4）；
   - `ActionPoint` / `ReactionPoint` / `Name` 直接可写；
   - Commit 后各自集合计数 +1：弹簧 `Springs`、阻尼 `Dampers`、衬套 `Bushings`。
   - 阻尼器不设 `CoefficientType` 也能 Validate+Commit；
     衬套缺 `BushingDefine.Orientation` → "A NULL value was encountered"，而它要的是 **NXMatrix**
     （给 Direction 报 Expecting NXOpen.NXMatrix type），由部件坐标系 `csys.Orientation` 得到。

C) UF 接口的形状（SKILL.md §3 坑位 9）：
   - struct 类型是模块级 `NXOpen.UF.MotionInterference_Struct`，字段 `Solid1` / `Solid2`；
   - **out 参数即返回值**：`ufs.Motion.InitInterferenceStruct()` 是 0 参调用，传参必报错；
   - `ufs.Motion.AskGrueblerCount()` 返回整数；
   - `DriverMultiOperations` 只有三个驱动项：EulerAngle1 / PointOnCurve / TranslationZ。

D) Motion 域关节类型：`JointDefine.Type` 无 `Hinge` / `Ball`（铰链 = `Revolute`，
   球铰 = `Spherical`）；`AskSolverDofCount` 增量覆盖 Revolute +1、Slider +1、
   Cylindrical +2、Spherical +3、Universal +2、Planar +3、Fixed 0、Atpoint +3、
   Inline +4、Inplane +5、Orientation +3、Parallel +4、Perpendicular +5、
   Constantvelocity +2；Screw 与 Cylindrical 同对时把 2 收到 1。
   `ValueOf` 是内建方法不是枚举成员；Atpoint/Perpendicular/Constantvelocity
   的 Euler/TranslationZ 驱动均被拒。
"""
import math
import os
import sys

import NXOpen
import NXOpen.Motion as M
import NXOpen.UF

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
    # 第二个副：Slider（沿 z），只用于 MotionTranslationZ 驱动器的建法 gate；
    # 本用例不求解，所以与 J_AB 并存不会引入求解矛盾。
    jb2 = mm.Joints.CreateJointBuilder(M.Joint.Null)
    jd2 = jb2.JointDefine
    jd2.JointType = M.JointDefine.Type.Slider
    jd2.FirstLink = links["L1"]
    jd2.SecondLink = links["L2"]
    jd2.FirstOrigin = pts["B"]
    jd2.FirstVector = zd
    jd2.SecondOrigin = pts["B"]
    jd2.SecondVector = zd
    jd2.Name = "J_SLIDE"
    j_slide = jb2.Commit()
    jb2.Destroy()
    return sim_part, mm, links, pts, j_slide


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

    # ⚠ 实例上 AttachmentType 可读不可写：读取返回枚举类，赋值报 AttributeError。
    #   本配方就是"不设它"跑通的；这里守住"读得到、写不了"两条事实。
    read_ok = False
    try:
        read_ok = b.AttachmentType is not None
    except Exception:
        read_ok = False
    write_readonly = False
    try:
        b.AttachmentType = M.ConnectorBuilder.AttachmentType.Link
    except AttributeError:
        write_readonly = True
    check("REG_SPRING_ATTACHMENT_READONLY",
          read_ok and write_readonly,
          "AttachmentType 实例上可读、赋值只读（枚举 owner=%s）" % owner)

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
    这两个 SelectObject 一直在。`CoefficientType` 可省：不设它 Validate/Commit 均通过
    （探针 PROBE_DAMPER_NOCT_VALIDATE/COMMIT=OK）。
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


def translation_driver_case(mm, joint):
    """MotionTranslationZ 沿关节局部 z；这里只 gate builder/Validate/Commit，
    符号与 Tx=-10 需要求解后才能断言（见 motion.md 的未验证标注）。"""
    n0 = len(list(mm.JointDrivers))
    msg = "committed"
    try:
        jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
        jdb.Name = "DRV_TZ"
        jdb.Joint.Value = joint
        op = jdb.DriverMultiOperations.MotionTranslationZ
        op.TypeOption = M.DriverOperation.Type.Constant
        op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
        set_expr(op.VelocityExpression, "10.0")
        jdb.Validate()
        jdb.Commit()
        jdb.Destroy()
        n1 = len(list(mm.JointDrivers))
        check("REG_DRIVER_TRANSLATIONZ", n1 == n0 + 1,
              "joint drivers %d->%d (MotionTranslationZ)" % (n0, n1))
    except Exception as exc:
        msg = "%s: %s" % (type(exc).__name__, str(exc)[:110])
        check("REG_DRIVER_TRANSLATIONZ", False, msg)


def joint_types_case(session, ufs, mm, sim_part):
    """Motion 域关节类型的建法与自由度语义（`AskSolverDofCount` 增量）。

    `JointDefine.Type` 全表无 `Hinge` / `Ball`：
      - 铰链（hinge）= `Revolute`（16/18/36 号已验运动学）；
      - 球铰（ball）= `Spherical`（三转，去 3 个平动自由度）。
    已验增量：Cylindrical +2（1T+1R）、Spherical +3（3R）、Universal +2（2R）、
    Planar +3（1R+2T）、Fixed 0、Atpoint +3、Inline +4、Inplane +5、
    Orientation +3、Parallel +4、Perpendicular +5（两轴垂直）、
    Constantvelocity +2（两轴斜交）。Screw 必须与 Cylindrical 建在同一对
    link 上：Cylindrical +2、再加 Screw 后总 DOF 1（转动-平动耦合）。

    驱动接受度是类型相关的负向事实：Revolute 的 Euler/TranslationZ 都能提交；
    Atpoint/Perpendicular/Constantvelocity 两种驱动都被拒（`Math function
    definition is invalid`）。驱动能提交 ≠ 该自由度存在（Revolute 也接受
    TranslationZ），所以它只作负面清单，不作 DOF 判据。
    """
    check("REG_JOINT_NO_HINGE_BALL",
          not hasattr(M.JointDefine.Type, "Hinge")
          and not hasattr(M.JointDefine.Type, "Ball"),
          "Hinge=%s Ball=%s（铰链=Revolute，球铰=Spherical）"
          % (hasattr(M.JointDefine.Type, "Hinge"),
             hasattr(M.JointDefine.Type, "Ball")))

    def mk_link(name, cm):
        lb = mm.Links.CreateLinkBuilder(M.Link.Null)
        lb.Name = name
        lb.MassProperty.MassType = M.LinkMassProperty.MassPropertyType.UserDefined
        set_expr(lb.MassProperty.MassExpression, "0.010000")
        for ax in ("IxxExpression", "IyyExpression", "IzzExpression",
                   "IxyExpression", "IxzExpression", "IyzExpression"):
            set_expr(getattr(lb.MassProperty, ax), "1.000000")
        lb.MassProperty.MassCenter = cm
        l = lb.Commit()
        lb.Destroy()
        return l

    def pair(tag, jtype, idx, expect, v2=None):
        n0 = ufs.Motion.AskSolverDofCount()
        o = sim_part.Points.CreatePoint(
            NXOpen.Point3d(200.0 * idx, 500.0, 0.0))
        v = sim_part.Directions.CreateDirection(
            o, NXOpen.Vector3d(0.0, 0.0, 1.0))
        vv = v if v2 is None else sim_part.Directions.CreateDirection(
            o, NXOpen.Vector3d(*v2))
        g = mk_link("T23_%s_G" % tag, o)
        m = mk_link("T23_%s_M" % tag, o)
        session.MotionSession.FixLinkToGround(g)
        jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
        jd = jb.JointDefine
        jd.JointType = jtype
        jd.FirstLink = g
        jd.SecondLink = m
        jd.FirstOrigin = o
        jd.FirstVector = v
        jd.SecondOrigin = o
        jd.SecondVector = vv
        jd.Name = "J_" + tag
        j = jb.Commit()
        jb.Destroy()
        n1 = ufs.Motion.AskSolverDofCount()
        check("REG_JOINT_%s_DOF" % tag, n1 - n0 == expect,
              "solver_dof %r->%r delta=%r expect +%d"
              % (n0, n1, n1 - n0, expect))
        return j

    def driver(tag, j, opname, val=90.0):
        jdb = mm.JointDrivers.CreateJointDriverBuilder(M.JointDriver.Null)
        jdb.Name = "T23_DRV_%s_%s" % (tag, opname)
        jdb.Joint.Value = j
        op = getattr(jdb.DriverMultiOperations, opname)
        op.TypeOption = M.DriverOperation.Type.Constant
        op.IntegrationTypeOption = M.DriverOperation.IntegrationType.Velocity
        set_expr(op.VelocityExpression, "%.1f" % val)
        try:
            jdb.Commit()
            ok = True
            err = ""
        except Exception as exc:
            ok = False
            err = "%s: %s" % (type(exc).__name__,
                              str(exc).splitlines()[0][:70])
        jdb.Destroy()
        return ok, err

    j_cyl = pair("CYL", M.JointDefine.Type.Cylindrical, 1, 2)
    pair("SPH", M.JointDefine.Type.Spherical, 2, 3)
    pair("UNI", M.JointDefine.Type.Universal, 3, 2)
    pair("PLA", M.JointDefine.Type.Planar, 4, 3)
    pair("FIXED", M.JointDefine.Type.Fixed, 5, 0)
    j_atp = pair("ATPOINT", M.JointDefine.Type.Atpoint, 6, 3)
    pair("INLINE", M.JointDefine.Type.Inline, 7, 4)
    pair("INPLANE", M.JointDefine.Type.Inplane, 8, 5)
    pair("ORIENT", M.JointDefine.Type.Orientation, 9, 3)
    pair("PARALLEL", M.JointDefine.Type.Parallel, 10, 4)
    j_perp = pair("PERPEND", M.JointDefine.Type.Perpendicular, 11, 5,
                  v2=(1.0, 0.0, 0.0))
    _a = math.radians(30.0)
    j_cv = pair("CONSTV", M.JointDefine.Type.Constantvelocity, 12, 2,
                v2=(math.sin(_a), 0.0, math.cos(_a)))

    # 驱动控制：同款构建方式下 Revolute 的 Euler/TranslationZ 都能提交，
    # 证明后面的拒绝是关节类型相关，不是本用例的构建方式问题。
    j_rev = pair("REV_CTRL", M.JointDefine.Type.Revolute, 13, 1)
    pair("SLIDER", M.JointDefine.Type.Slider, 14, 1)
    ctrl_e, _ = driver("REV_CTRL", j_rev, "MotionEulerAngle1")
    ctrl_t, _ = driver("REV_CTRL", j_rev, "MotionTranslationZ")
    check("REG_JOINT_DRIVER_CTRL", ctrl_e and ctrl_t,
          "Revolute Euler=%s TranslationZ=%s" % (ctrl_e, ctrl_t))

    rejected = 0
    errs = []
    for tag, jj in (("ATPOINT", j_atp), ("PERPEND", j_perp),
                    ("CONSTV", j_cv)):
        for opname in ("MotionEulerAngle1", "MotionTranslationZ"):
            ok, err = driver(tag + "_REJ", jj, opname)
            if not ok:
                rejected += 1
                if err:
                    errs.append(err)
    check("REG_JOINT_DRIVER_REJECT", rejected == 6,
          "lower-pair drivers rejected %d/6%s"
          % (rejected, (" (" + errs[0] + ")") if errs else ""))

    # ValueOf 在 dir() 里但是内建方法，不是枚举成员（与装配层同坑）
    vof = getattr(M.JointDefine.Type, "ValueOf")
    jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
    try:
        jb.JointDefine.JointType = vof
        assign_failed = False
    except TypeError:
        assign_failed = True
    jb.Destroy()
    check("REG_JOINT_NO_VALUE_OF",
          type(vof).__name__ == "builtin_function_or_method" and assign_failed,
          "ValueOf type=%s assign_failed=%s"
          % (type(vof).__name__, assign_failed))

    # Screw：头文件要求与 Cylindrical 建在同一对 link 上
    n0 = ufs.Motion.AskSolverDofCount()
    o = sim_part.Points.CreatePoint(NXOpen.Point3d(200.0 * 20, 500.0, 0.0))
    v = sim_part.Directions.CreateDirection(
        o, NXOpen.Vector3d(0.0, 0.0, 1.0))
    g = mk_link("T23_SCREW_G", o)
    m = mk_link("T23_SCREW_M", o)
    session.MotionSession.FixLinkToGround(g)
    jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
    jd = jb.JointDefine
    jd.JointType = M.JointDefine.Type.Cylindrical
    jd.FirstLink = g
    jd.SecondLink = m
    jd.FirstOrigin = o
    jd.FirstVector = v
    jd.SecondOrigin = o
    jd.SecondVector = v
    jd.Name = "J_T23_SCREW_CYL"
    j_screw_cyl = jb.Commit()
    jb.Destroy()
    n1 = ufs.Motion.AskSolverDofCount()

    jb = mm.Joints.CreateJointBuilder(M.Joint.Null)
    jd = jb.JointDefine
    jd.JointType = M.JointDefine.Type.Screw
    jd.FirstLink = g
    jd.SecondLink = m
    jd.FirstOrigin = o
    jd.FirstVector = v
    jd.SecondOrigin = o
    jd.SecondVector = v
    jd.Name = "J_T23_SCREW"
    jd.MethodType = M.JointDefineScrewJointMethodType.Ratio
    jd.RatioType = M.JointDefineScrewJointRatioType.Expression
    set_expr(jd.ScrewRatioExpression, "2.0")
    ratio = float(jd.ScrewRatioExpression.RightHandSide)
    jb.Commit()
    jb.Destroy()
    n2 = ufs.Motion.AskSolverDofCount()
    check("REG_JOINT_SCREW_COUPLING",
          n1 - n0 == 2 and n2 - n0 == 1,
          "solver_dof base=%r +cyl=%r +screw=%r (expect +2 then +1)"
          % (n0, n1, n2))
    check("REG_JOINT_SCREW_RATIO", abs(ratio - 2.0) <= 1e-9,
          "ScrewRatioExpression=%r（导程 2 mm/rev）" % ratio)
    screw_drv, screw_err = driver("SCREW_CYL", j_screw_cyl,
                                  "MotionEulerAngle1", 360.0)
    check("REG_JOINT_SCREW_DRIVER", screw_drv,
          "cylindrical Euler driver %s%s"
          % ("committed" if screw_drv else "rejected",
             (" (" + screw_err + ")") if screw_err else ""))



def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    sim_part, mm, links, pts, j_slide = build_sim(session, ufs)
    say("sim=%s" % sim_part.Leaf)

    holders_case(mm)
    spring_case(mm, links, pts)
    damper_case(mm, links, pts)
    bushing_case(mm, links, pts, sim_part)
    uf_shape_case(ufs, mm)
    translation_driver_case(mm, j_slide)
    joint_types_case(session, ufs, mm, sim_part)

    ok = all(v for _, v in RESULTS)
    failed = [n for n, v in RESULTS if not v]
    say("TEST23_CASES=%d" % len(RESULTS))
    if not ok:
        say("TEST23_FAIL failed=%s" % failed)
        raise RuntimeError("test 23 failed: %s" % failed)
    say("TEST23_DONE")


if __name__ == "__main__":
    main()
