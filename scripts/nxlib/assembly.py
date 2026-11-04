# -*- coding: utf-8 -*-
"""nxlib.assembly —— 装配配方标准层（权威来源：04/10 号已验收用例逐字平移）。

覆盖：组件添加（AddComponent 固定参数口径）、单位阵、原型面按轴查找、
Touch 约束网络（10 号 s3 决定性配方：约束必须先 DoUpdate 再进网络求解）。

已知限制（10 号实测）：Constraint.Type 属性只读（用 ConstraintType）；
Distance 偏置用 con.Expression.RightHandSide = "50"（实测生效并回读 50），
con.OffsetRightHandSide setter 不可用（传 str 报 Not yet implemented、
传 float 报类型错）。定位仍走 AddComponent placement 或 Touch 对。
"""
import NXOpen
import NXOpen.Positioning
import NXOpen.UF

from .session import _ufs


def ufs():
    return _ufs()


def identity_matrix():
    """单位姿态阵（04/10 号口径）。"""
    m = NXOpen.Matrix3x3()
    m.Xx = 1.0
    m.Yy = 1.0
    m.Zz = 1.0
    return m


def add_component(assy, part_path, origin, layer=1):
    """按绝对坐标加组件（AddComponent(path, "1", "MODEL", origin, 单位阵, layer)）。

    实参第 2 位是引用集名、第 3 位是组件名（已核对；第 4 位起未逐位验证）。
    这里沿 04/10 号验收过的写法传 ("1", "MODEL")：`"1"` 作引用集名是非法值、
    被静默回退成 MODEL，`"MODEL"` 落到组件名上——功能可用，但没真正指定引用集。
    要显式写就传 (path, "MODEL", "LINK_A", ...)，组件名也可加完后 SetName()。

    返回 (component, status)。
    """
    ca = assy.ComponentAssembly
    return ca.AddComponent(part_path, "1", "MODEL", origin, identity_matrix(), layer)


def preload_components(session, assy):
    """预载装配全部子件。

    组件体惰性加载：重开装配后 component.Prototype 下的实例体不自动进入
    上下文，干涉检查/约束读回前不预载则 SimpleInterference 空跑
    （实测 inst_bodies=0）。返回子件 .prt 路径列表；已加载的子件再 Open 抛
    "File already exists"，按幂等跳过。载入成功与否只能看 Parts.Open 的
    loadStatus.NumberUnloadedParts（component.Prototype 对未加载组件也返回
    占位对象且不抛异常），非 0 即抛错，不让调用方在空跑上继续。
    """
    opened = []
    children = assy.ComponentAssembly.RootComponent.GetChildren()
    for c in children:
        proto = c.Prototype
        fp = getattr(proto, "FullPath", None) if proto is not None else None
        if not (fp and fp.lower().endswith(".prt")
                and fp.lower() != assy.FullPath.lower()):
            continue
        try:
            _, load_status = session.Parts.Open(fp)   # 1 参数，返回 (part, loadStatus)
        except Exception as exc:
            # 已加载的子件再 Open 抛 "File already exists"，属幂等，跳过；其余异常
            # 是预载真失败，冒泡——吞掉会让后续干涉检查空跑
            if "file already exists" not in str(exc).lower():
                raise
            continue
        if load_status.NumberUnloadedParts:
            raise RuntimeError(
                "preload_components: %s 未完全载入（NumberUnloadedParts=%d）"
                % (fp, load_status.NumberUnloadedParts))
        opened.append(fp)
    return opened


def find_proto_face(part, axis, sign):
    """在部件原型体上找指定轴+符号的法线平面（10 号口径；axis="X"/"Y"/"Z"）。"""
    u = ufs()
    k = {"X": 0, "Y": 1, "Z": 2}[axis]
    for b in part.Bodies:
        for f in b.GetFaces():
            d = u.Modeling.AskFaceData(f.Tag)
            if d[0] != 22:
                continue
            if d[2][k] * sign > 0.9:
                return f
    return None


def touch_pair(session, assy, comp_movable, face_movable, comp_base, face_base, name):
    """Touch 约束对 + 网络求解（10 号 s3 决定性配方）。

    约束必须先 DoUpdate 提交再进网络求解，否则 solve 返回 OK 但组件不动。
    Invisible 标记在 finally 内删除，与 SKILL.md §3 的配对要求一致。
    """
    occ_movable = comp_movable.FindOccurrence(face_movable)
    occ_base = comp_base.FindOccurrence(face_base)
    pos = assy.ComponentAssembly.Positioner
    pos.BeginAssemblyConstraints()
    mark = None
    try:
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "nxlib_touch")
        con = pos.CreateConstraint(True)
        con.ConstraintType = NXOpen.Positioning.Constraint.Type.Touch
        con.CreateConstraintReference(comp_movable, occ_movable, False, False, False)
        con.CreateConstraintReference(comp_base, occ_base, False, False, False)
        session.UpdateManager.DoUpdate(mark)
        net = pos.EstablishNetwork()
        net.AddConstraint(con)
        err = net.Solve()
        net.ApplyToModel()
        con.SetName(name)
        pos.ClearNetwork()
    finally:
        try:
            pos.EndAssemblyConstraints()
        finally:
            if mark is not None:
                session.DeleteUndoMark(mark, "nxlib_touch")
    return err
