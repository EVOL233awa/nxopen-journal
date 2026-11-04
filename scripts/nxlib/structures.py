# -*- coding: utf-8 -*-
"""构造层：参数/数据分离的通用 builder。

每个 builder 只吃 (frame/轴, design 表达式名, data 字面量)，不写零件常数：

* ``expr`` 参数一律是**命名表达式名**（"T_PLATE"），由特征输入消费 → 改值可
  驱动（G8 存活）；
* ``data`` 参数一律是实测字面量（轮廓点、实测轴、实测位置），不建表达式。

builder 返回 ``{"features": [...], "bodies": [...]}``，布尔目标由调用方持有；
不在这里做全局体查找。
"""
import math

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
import NXOpen.UF

import nxlib.modeling as mdl
import nxlib.skeleton as sk
from .session import _ufs as _uf

NULL = NXOpen.Features.Feature.Null


def bodies_of(feature):
    return list(feature.GetBodies())


def first_body(feature):
    bs = bodies_of(feature)
    if not bs:
        raise RuntimeError("feature %s produced no body" % feature.FeatureType)
    return bs[0]


def _vec3(direction):
    """Vector3d / (x,y,z) 统一成三元组。"""
    if hasattr(direction, "X"):
        return (float(direction.X), float(direction.Y), float(direction.Z))
    return (float(direction[0]), float(direction[1]), float(direction[2]))


def _tool(feature_or_body):
    """feature 或 body 都能当布尔的工具体。"""
    if hasattr(feature_or_body, "GetBodies"):
        return first_body(feature_or_body)
    return feature_or_body


def _result(features):
    bs = []
    for f in features:
        bs.extend(bodies_of(f))
    return {"features": list(features), "bodies": bs}


# ------------------------------------------------------------------ 布尔

def boolean(wp, target, tool, op):
    return mdl.boolean(wp, target, tool, op)


def cut(wp, target, feature):
    return boolean(wp, target, _tool(feature),
                   NXOpen.Features.Feature.BooleanType.Subtract)


def unite(wp, target, feature):
    return boolean(wp, target, _tool(feature),
                   NXOpen.Features.Feature.BooleanType.Unite)


def intersect(wp, target, tool_body):
    return boolean(wp, target, tool_body,
                   NXOpen.Features.Feature.BooleanType.Intersect)


# ------------------------------------------------------------------ 棱柱/回转

def prism(wp, curves, direction, d0, d1, help_pt=None):
    """闭合轮廓沿 direction 从 d0 拉到 d1（d0/d1 可传表达式名）。"""
    hp = help_pt if help_pt is not None else NXOpen.Point3d(0.0, 0.0, 0.0)
    f = mdl.extrude_along(wp, curves, _vec3(direction), d1, d0, hp)
    return _result([f])


def revolve(wp, curves, axis_pt, axis_dir, a0="0.0", a1="360.0"):
    """闭合轮廓绕轴回转 a0..a1 度（可传表达式名；UF 路线，NX12 批处理可用）。"""
    feats = _uf().Modl.CreateRevolved(
        [c.Tag for c in curves], [str(a0), str(a1)],
        [axis_pt[0], axis_pt[1], axis_pt[2]],
        [axis_dir[0], axis_dir[1], axis_dir[2]],
        NXOpen.UF.ModlFeatureSigns.NULLSIGN)
    out = [NXOpen.TaggedObjectManager.GetTaggedObject(t) for t in feats]
    return _result(out)


def cylinder(wp, p, direction, dia_expr, height_expr):
    """表达式驱动的圆柱实体（直径/高度）。"""
    cb = wp.Features.CreateCylinderBuilder(NULL)
    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
    cb.Axis = sk.axis(wp, p, direction)
    cb.Diameter.RightHandSide = dia_expr
    cb.Height.RightHandSide = height_expr
    f = cb.CommitFeature()
    cb.Destroy()
    return _result([f])


def cone(wp, p, direction, base_dia_expr, top_dia_expr, height_expr):
    """表达式驱动的圆锥实体（两端直径 + 高度）。"""
    cb = wp.Features.CreateConeBuilder(NXOpen.Features.Cone.Null)
    cb.Type = NXOpen.Features.ConeBuilder.Types.DiametersAndHeight
    cb.Axis = sk.axis(wp, p, direction)
    cb.BaseDiameter.RightHandSide = base_dia_expr
    cb.TopDiameter.RightHandSide = top_dia_expr
    cb.Height.RightHandSide = height_expr
    f = cb.CommitFeature()
    cb.Destroy()
    return _result([f])


# ------------------------------------------------------------------ 边缘选择

def edges_by(body, frame, pred):
    """按框架局部坐标筛选边：pred([(u,v,z), ...]) -> bool。"""
    out = []
    for e in body.GetEdges():
        vs = [frame.to_local((p.X, p.Y, p.Z)) for p in e.GetVertices()]
        if vs and pred(vs):
            out.append(e)
    return out


def face_loop_edges(body, ftype, direction, on_point, tol=0.08):
    """找满足 (类型, 法向, 过点) 的面，取它的一圈边（用于环状倒圆）。"""
    u = _uf()
    out = []
    for f in body.GetFaces():
        try:
            d = u.Modeling.AskFaceData(f.Tag)
        except Exception:
            continue
        if ftype is not None and int(d[0]) != ftype:
            continue
        fd = d[2]
        if direction is not None and any(
                abs(fd[i] - direction[i]) > tol for i in range(3)):
            continue
        if on_point is not None:
            dist = sum((on_point[i] - d[1][i]) * fd[i] for i in range(3))
            if abs(dist) > tol:
                continue
        out.extend(list(f.GetEdges()))
    return out


# ------------------------------------------------------------------ 圆角

def blend_edges(wp, edges, radius_expr):
    """切线链倒圆（radius_expr 可传表达式名）。"""
    rule = wp.ScRuleFactory.CreateRuleEdgeMultipleSeedTangent(edges, 1.0, True)
    col = wp.ScCollectors.CreateCollector()
    col.ReplaceRules([rule], False)
    b = wp.Features.CreateEdgeBlendBuilder(NULL)
    b.AddChainset(col, str(radius_expr))
    f = b.CommitFeature()
    b.Destroy()
    col.Destroy()
    return _result([f])


def blend_try(wp, edges, radius_expr, tag="blend"):
    """带 undo 保护的倒圆：失败回滚并返回 None（不留告警/诊断）。"""
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, tag)
    try:
        res = blend_edges(wp, edges, radius_expr)
        session.DeleteUndoMark(mark, tag)
        return res
    except Exception:
        session.UndoToMark(mark, tag)
        session.DeleteUndoMark(mark, tag)
        return None


# ------------------------------------------------------------------ 孔

def hole_cut(wp, target, p, direction, dia_expr, depth_expr, back=2.0):
    """沿 direction 的圆柱孔（从 p 退回 back 起钻 depth）。"""
    d = sk.normalize(direction)
    p0 = (p[0] - back * d[0], p[1] - back * d[1], p[2] - back * d[2])
    tool = cylinder(wp, p0, d, dia_expr, depth_expr)
    cut(wp, target, tool["features"][0])
    return tool


def hole_ring(wp, target, frame, pcd, angles_deg, dia_expr, depth_expr, z):
    """环状孔列：孔位（pcd/角度）是实测 data，孔径/深度绑表达式。"""
    out = []
    for a in angles_deg:
        rad = math.radians(a)
        p = frame.pt(pcd * math.cos(rad), pcd * math.sin(rad), z)
        res = hole_cut(wp, target, (p.X, p.Y, p.Z), frame.Z,
                       dia_expr, depth_expr)
        out.extend(res["features"])
    return {"features": out, "bodies": []}


# ------------------------------------------------------------------ 包络

def trim_box(wp, target, frame, lo, hi, z0, z1):
    """用框架 (u,v) 矩形包络沿 frame.Z 拉伸裁掉多余材料（G4 修形）。

    包络坐标与起止是实测 data；裁剪本身是布尔求交，不引入表达式。
    """
    lo = [float(x) for x in lo]
    hi = [float(x) for x in hi]
    cs = sk.loop_uv(wp, frame, [(lo[0], lo[1]), (hi[0], lo[1]),
                                (hi[0], hi[1]), (lo[0], hi[1])])
    tool = prism(wp, cs, sk.normalize(frame.Z), z0, z1)
    intersect(wp, target, tool["bodies"][0])
    return tool


# ================================================================== 结构级
#
# 上面是原语（一个棱柱、一个圆柱、一次布尔），下面是**结构**：一个结构一个
# builder，返回体/特征/账本三件东西，调用方只持目标体。
#
# 为什么要这一层：只有原语时，一个"厚度随 z 分段变化"的铸造体只能写成
# N 条 z 带棱柱逐段 unite——每段带出 4 个侧面 + 段间台阶面，面数按段数线
# 性膨胀，而形状精度仍受段高限制（实测某件 9 段带出 74 特征/10 773 面，
# 原件 998 面）。结构级 builder 把它写成**一条解析轮廓的一条特征**：
# 台阶在轮廓里，台阶面自然只在半径变化处出现。
#
# 参数口径不变：expr 参数一律命名表达式名，data 参数一律实测字面量。

def _named(feature, name):
    """特征可见名 = 结构 id（逐个结构审计/归因的锚点）。"""
    if name and feature is not None:
        try:
            feature.SetName(str(name))
        except Exception:
            pass
    return feature


def _centroid_pt(wp, frame, pts_uv, z=0.0):
    n = float(len(pts_uv))
    u = sum(p[0] for p in pts_uv) / n
    v = sum(p[1] for p in pts_uv) / n
    return frame.pt(u, v, z)


def _extrude_z(wp, curves, frame, z0, z1, help_pt, draft_expr=None):
    """沿 frame.Z 拉伸（可选拔模），z0/z1 可传表达式名；返回 feature。

    SimpleFromStart 的起剖面在 z0，正角度向 z1 端收缩。拔模只设角度不设
    类型时提交成功、无告警、体积与直壁逐位相同，所以类型与角度必须一起设。
    """
    direction = sk.normalize(frame.Z)
    if draft_expr is None:
        return mdl.extrude_along(wp, curves, direction, z1, z0, help_pt)
    section = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
    rule = wp.ScRuleFactory.CreateRuleCurveDumb(curves)
    section.AddToSection([rule], NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                         NXOpen.NXObject.Null, help_pt,
                         NXOpen.Section.Mode.Create, False)
    b = wp.Features.CreateExtrudeBuilder(NULL)
    b.Section = section
    b.Direction = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(direction[0], direction[1], direction[2]),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    b.Limits.StartExtend.Value.RightHandSide = str(z0)
    b.Limits.EndExtend.Value.RightHandSide = str(z1)
    b.Draft.DraftOption = \
        NXOpen.GeometricUtilities.SimpleDraft.SimpleDraftType.SimpleFromStart
    b.Draft.SetDraftAngle(str(draft_expr))
    f = b.CommitFeature()
    b.Destroy()
    section.Destroy()
    return f


def plate_2p5d(wp, frame, plan_uv, z0, z1, name="PLATE", draft_expr=None,
               help_pt=None):
    """2.5D 板：一条平面轮廓 + 拉伸厚度（+ 可选拔模角），一个特征。

    plan_uv: [(u,v)] 实测轮廓（data 层）；
    z0/z1:  起止（可传表达式名，T_PLATE 这类设计参数就是这里进来的）；
    draft_expr: 拔模角表达式名（Angle），正值向拉伸端收缩。

    拔模必须走 `Draft.DraftOption` + `SetDraftAngle`：只设角度不设类型时
    提交成功、无告警、体积与直壁逐位相同。
    """
    cs = sk.loop_uv(wp, frame, plan_uv)
    hp = help_pt if help_pt is not None else _centroid_pt(wp, frame, plan_uv)
    f = _extrude_z(wp, cs, frame, z0, z1, hp, draft_expr)
    return {"features": [_named(f, name)], "bodies": bodies_of(f)}


def _expr_number(wp, v):
    """数值或表达式名 → float。

    轮廓点必须落成实际坐标，回转而特征参数可以吃名字（`Diameter.
    RightHandSide = "D_HOLE"`）。因此轮廓里的设计量只能在建体时求值：
    体建成后它仍由表达式驱动，改动会跟着重算，但 builder 当下需要数字。
    未知名字直接报错，不猜成 0。
    """
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            pass
        for e in wp.Expressions:
            try:
                lhs = e.Equation.split("=")[0].strip()
            except Exception:
                continue
            if lhs == v:
                try:
                    return float(e.RightHandSide)
                except Exception:
                    raise ValueError(
                        "expression %r has a non-numeric right-hand side %r"
                        % (v, e.RightHandSide))
        raise ValueError("revolved_profile: unknown expression %r" % (v,))
    return float(v)


def revolved_profile(wp, profile_tr, axis_pt=(0.0, 0.0, 0.0),
                     axis_dir=(0.0, 0.0, 1.0), name="REVOLVE",
                     radials=None, unite=True):
    """(轴向 t, 半径 r) 轮廓 → 分段凸锥台 → 回转并合并成一个体。

    profile_tr: [(t, r)]，t 沿 axis_dir、r 为到轴的垂直距离；两项都可以是
    数值或表达式名（表达式在建体时求值，之后仍由它驱动几何）；
    r == 0 的点在轴上（锥尖），相邻两点可都在轴上（该段跳过）。

    为什么按段回转：360° 也能吃单调的带台阶/凹陷整条轮廓（体积等于解析值），
    但整条只出一条特征；切成单调段后逐段回转再合并，每段一条特征，台阶落在
    段界上不被平滑掉，也不产生 z 带棱柱的段间台阶面。自交或越过旋转轴的轮廓
    在两种路线下都报 "Cannot create Swept geometry"。
    每段一条特征，特征名 `<name>_S<i>`。

    radials: 每段用的径向（与 axis_dir 垂直），默认取同一稳定径向；相邻
    段的径向平面不同不影响 360° 回转的结果。

    返回 {"features", "bodies", "segments": [{"t0","r0","t1","r1"}]}。
    """
    a = sk.normalize(axis_dir)
    o = (float(axis_pt[0]), float(axis_pt[1]), float(axis_pt[2]))
    r_dir = sk.normalize(radials) if radials is not None else sk.perpendicular(a)
    feats, segs = [], []
    for i in range(len(profile_tr) - 1):
        t0, r0 = _expr_number(wp, profile_tr[i][0]), \
            _expr_number(wp, profile_tr[i][1])
        t1, r1 = _expr_number(wp, profile_tr[i + 1][0]), \
            _expr_number(wp, profile_tr[i + 1][1])
        if abs(t1 - t0) < 1e-9 or (r0 <= 1e-9 and r1 <= 1e-9):
            continue

        def at(t, r):
            return NXOpen.Point3d(o[0] + t * a[0] + r * r_dir[0],
                                  o[1] + t * a[1] + r * r_dir[1],
                                  o[2] + t * a[2] + r * r_dir[2])

        ring = [at(t0, 0.0), at(t0, r0), at(t1, r1), at(t1, 0.0)]
        dedup = [ring[0]]
        for p in ring[1:]:
            q = dedup[-1]
            if abs(p.X - q.X) + abs(p.Y - q.Y) + abs(p.Z - q.Z) > 1e-9:
                dedup.append(p)
        if len(dedup) > 1:
            first, last = dedup[0], dedup[-1]
            if (abs(first.X - last.X) + abs(first.Y - last.Y)
                    + abs(first.Z - last.Z)) < 1e-9:
                dedup.pop()
        if len(dedup) < 3:
            continue
        cs = [wp.Curves.CreateLine(dedup[k], dedup[(k + 1) % len(dedup)])
              for k in range(len(dedup))]
        res = revolve(wp, cs, o, a, "0.0", "360.0")
        _named(res["features"][0], "%s_S%d" % (name, len(segs)))
        feats.extend(res["features"])
        segs.append({"t0": t0, "r0": r0, "t1": t1, "r1": r1})
    if not feats:
        raise RuntimeError("revolved_profile: no segment had positive extent")
    bs = []
    for f in feats:
        bs.extend(bodies_of(f))
    if unite and len(bs) > 1:
        target = bs[0]
        for b in bs[1:]:
            boolean(wp, target, b,
                    NXOpen.Features.Feature.BooleanType.Unite)
        bs = [target]
    return {"features": feats, "bodies": bs, "segments": segs}


def drafted_bore(wp, target, p, direction, dia_a_expr, dia_b_expr,
                 length_expr, name="BORE"):
    """锥孔：从 p 沿 direction 走 length，入口 dia_a、末端 dia_b（都是直径表达式）。

    半角由这三条量决定，报告里按 atan((ra-rb)/L) 复算——不把它写成第四条
    表达式，因为它不是设计意图，是前三条的后果。

    返回的 `bodies` 是工具体，求差后被 target 吞并，再读它的体积得 0；
    要记工具体积就在调用本函数前读。
    """
    d = sk.normalize(direction)
    p0 = (float(p.X) if hasattr(p, "X") else float(p[0]),
          float(p.Y) if hasattr(p, "Y") else float(p[1]),
          float(p.Z) if hasattr(p, "Z") else float(p[2]))
    tool = cone(wp, p0, d, dia_a_expr, dia_b_expr, length_expr)
    _named(tool["features"][0], name)
    cut(wp, target, tool["features"][0])
    return tool


def hole_set(wp, target, positions, direction, dia_expr, depth_expr,
             name="HOLES", back=2.0):
    """一组同径孔：孔位是实测 data，孔径/深度是设计表达式。

    与 `hole_ring` 的差别是孔位不由极坐标生成——通孔、斜孔、非整圆布孔
    都能用，孔位表原样进报告。
    """
    feats = []
    for i, p in enumerate(positions):
        res = hole_cut(wp, target, p, direction, dia_expr, depth_expr, back)
        _named(res["features"][0], "%s_%02d" % (name, i))
        feats.extend(res["features"])
    return {"features": feats, "bodies": [], "count": len(feats)}


def pocket_intersect(wp, target, frame, profile_uz, plan_uv, v_span, z_span,
                     name="POCKET", help_sec=None, help_plan=None):
    """口部型腔 = 侧视轮廓棱柱 ∩ 俯视轮廓棱柱，再对 target 求差。

    台阶腔/清角腔的侧面与底面不能用一个棱柱表达（一个沿 V 拉、一个沿 Z
    拉），求交才是两条实测轮廓同时成立的地方；先求交再求差，与"两次求差"
    的体积相同但只在交集边界上生成面。

    profile_uz: [(u, z)] 在 v=0 平面（data）；plan_uv: [(u, v)] 在 z=0 平面（data）。
    help_sec / help_plan: 各自截面的料内参考点，按 (u, z) / (u, v) 给。
    """
    v = sk.normalize(frame.V)
    z = sk.normalize(frame.Z)
    if help_sec is not None:
        hp1 = frame.pt(help_sec[0], 0.0, help_sec[1])
    else:
        hu = sum(p[0] for p in profile_uz) / float(len(profile_uz))
        hz = sum(p[1] for p in profile_uz) / float(len(profile_uz))
        hp1 = frame.pt(hu, 0.0, hz)
    p1 = prism(wp, sk.loop_uz(wp, frame, profile_uz, 0.0), v,
               str(-float(v_span)), str(float(v_span)), hp1)
    _named(p1["features"][0], name + "_SEC")
    if help_plan is not None:
        hp2 = frame.pt(help_plan[0], help_plan[1], 0.0)
    else:
        hp2 = _centroid_pt(wp, frame, plan_uv, 0.0)
    p2 = prism(wp, sk.loop_uv(wp, frame, plan_uv, 0.0), z,
               str(z_span[0]), str(z_span[1]), hp2)
    _named(p2["features"][0], name + "_PLAN")
    b1 = p1["bodies"][0]
    intersect(wp, b1, p2["bodies"][0])
    _named(p1["features"][0], name + "_VOID")
    cut(wp, target, p1["features"][0])
    return {"features": p1["features"] + p2["features"], "bodies": [b1]}


def fillet_run(wp, edges, radius_expr, name="FILLET", edges_id=None,
               radius_mm=None, min_len_factor=0.5):
    """逐边倒圆 + 逐边账本（G7 跑道账本的最小形态）。

    `blend_try` 失败只给 None，账本拿不到原因就无法回答"这条跑道为什么
    不可达"。这里自己开 undo mark：失败回滚并把原文留在 `msg`，成功记
    `ok` 与半径。**一条失败不影响后续边**——跑道账本就是逐条记账。

    edges_id: 可传入与 edges 对齐的 id 列表（例如跑道号），默认用下标。
    radius_mm + `fillet_feasible`: 给数值半径时先做前置判定，把"半径过大/
    支撑面太窄/边太短"与"边已被上一条圆角消费"分开写进 `reason`；不给就
    只记 NX 原文。
    返回 {"features", "bodies", "ledger": [{id, ok, radius, msg, reason}]}。
    """
    session = NXOpen.Session.GetSession()
    out, bs = [], []
    ledger = []
    ids = list(edges_id) if edges_id is not None else list(range(len(edges)))
    for e, eid in zip(edges, ids):
        tag = "%s_%s" % (name, eid)
        pre = (fillet_feasible(e, float(radius_mm), min_len_factor)
               if radius_mm is not None else None)
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, tag)
        try:
            res = blend_edges(wp, [e], radius_expr)
            session.DeleteUndoMark(mark, tag)
            out.extend(res["features"])
            bs.extend(res["bodies"])
            ledger.append({"id": eid, "ok": True, "radius": str(radius_expr),
                           "msg": "", "precheck": pre, "reason": ""})
        except Exception as exc:
            msg = str(exc).splitlines()
            first = (msg[0] if msg else "")[:200]
            try:
                session.UndoToMark(mark, tag)
                session.DeleteUndoMark(mark, tag)
            except Exception:
                pass
            reason = first
            if pre is not None and not pre["ok"]:
                reason = "%s (precheck: %s)" % (pre["reason"], first)
            ledger.append({"id": eid, "ok": False, "radius": str(radius_expr),
                           "msg": first, "precheck": pre, "reason": reason})
    return {"features": out, "bodies": bs, "ledger": ledger,
            "pass": all(r["ok"] for r in ledger) if ledger else False}


def _face_width(face, d, p0):
    """面在垂直于边方向上的宽度：面边界顶点到该边所在直线的最大垂距。

    圆角要在两侧支撑面上各吃掉一个 R，支撑面比 R 窄时 NX 只回一句
    `Radius is too large`——真正的原因是支撑面宽度，前置判定要能说出来。
    用边界顶点的垂距估计（矩形面精确；曲面面是近似上界）。
    """
    best = 0.0
    for e in face.GetEdges():
        for v in e.GetVertices():
            q = _pt3(v)
            w = (q[0] - p0[0], q[1] - p0[1], q[2] - p0[2])
            t = w[0] * d[0] + w[1] * d[1] + w[2] * d[2]
            perp = math.sqrt(max(0.0, w[0] ** 2 + w[1] ** 2 + w[2] ** 2
                                 - t * t))
            if perp > best:
                best = perp
    return best


def fillet_feasible(edge, radius_mm, min_len_factor=0.5,
                    dihedral_range=(20.0, 160.0)):
    """倒圆可行性前置判定：边长 / 支撑面宽度与半径 / 二面角，逐条给原因。

    判据（都用面表与边几何，不试错）：
      * 边长 < min_len_factor×R：这条边容不下一个常半径圆角；
      * 支撑面宽度 < R：圆角要在两侧面各吃掉一个 R，面比 R 窄时 NX 只回
        `Radius is too large`；
      * 支撑面里有圆柱/圆锥且 R > 支撑半径：原因是支撑面曲率；
      * 两邻面都是平面且二面角在 `dihedral_range` 之外（近共面或尖角）：
        常半径滚球在这里要么退化要么需要不等半径过渡。
    返回 {"ok","reason","length","width_mm","dihedral_deg","support_radii"}；
    读不到面/边时 ok 记 None 并写"无法判定"，不假装通过。
    """
    u = _uf()
    faces = list(edge.GetFaces())
    radii, normals, types = [], [], []
    for f in faces:
        try:
            typ, _pt, dr, _box, rad, _rdata, _ndir = u.Modeling.AskFaceData(f.Tag)
        except Exception:
            return {"ok": None, "reason": "face data unreadable",
                    "length": None, "width_mm": None, "dihedral_deg": None,
                    "support_radii": []}
        types.append(int(typ))
        normals.append(_vec3(dr))
        if int(typ) in (16, 17):
            radii.append(abs(float(rad)))
    try:
        length = float(edge.GetLength())
    except Exception:
        length = None
    width = None
    try:
        verts = [_pt3(v) for v in edge.GetVertices()]
        if len(verts) >= 2:
            d = _unit3(verts[0], verts[-1])
            widths = [_face_width(f, d, verts[0]) for f in faces]
            width = min(widths) if widths else None
    except Exception:
        width = None
    dihedral = None
    if len(normals) == 2:
        dp = sum(normals[0][i] * normals[1][i] for i in range(3))
        dp = max(-1.0, min(1.0, dp))
        dihedral = 180.0 - math.degrees(math.acos(dp))
    reason = ""
    if length is None or width is None:
        reason = "edge or face geometry unreadable"
    elif length < min_len_factor * radius_mm:
        reason = ("edge %.3f too short for R%.3f (needs >= %.3f)"
                  % (length, radius_mm, min_len_factor * radius_mm))
    elif radius_mm > width + 1e-9:
        reason = ("R%.3f exceeds support width %.3f"
                  % (radius_mm, width))
    elif radii and radius_mm > min(radii) + 1e-9:
        reason = ("R%.3f exceeds support radius %.3f"
                  % (radius_mm, min(radii)))
    elif dihedral is not None and not (dihedral_range[0] <= dihedral
                                       <= dihedral_range[1]):
        reason = ("dihedral %.2f deg outside %.0f-%.0f"
                  % (dihedral, dihedral_range[0], dihedral_range[1]))
    return {"ok": reason == "", "reason": reason, "length": length,
            "width_mm": width, "dihedral_deg": dihedral,
            "support_radii": radii, "support_types": types}


# ================================================================== 结构级（第二批）
#
# 这一批对着已交付件的失败模式写：孔链被建成一条等径直孔（G2 三处孔长差
# 1.0–1.3 mm）→ `hole_chain` 逐段切除 + 逐刀回读新增面；耳端按销轴方向棱柱
# 外推（外角 +1.013 mm）→ `eye_2lobe`/`clevis` 用相切圆瓣而不是外推；按包围
# 盒或区域大盒修边 → `trim_planes` 按实测平面裁；圆角不可达只有 NX 原文、
# 分不清"半径过大"和"边已被消费" → `fillet_feasible` 前置判定。

def _pt3(p):
    if hasattr(p, "X"):
        return (float(p.X), float(p.Y), float(p.Z))
    return (float(p[0]), float(p[1]), float(p[2]))


def _dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                     + (a[2] - b[2]) ** 2)


def _unit3(a, b):
    d = _dist3(a, b)
    if d < 1e-9:
        raise ValueError("degenerate segment: p0 == p1")
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d, (b[2] - a[2]) / d)


CYLINDER_TYPE = 16
CONE_TYPE = 17


def face_signature(body):
    """{tag: (type, radius, rad_data)}：逐刀断言新增面用，不读全量面表。"""
    u = _uf()
    sig = {}
    for f in body.GetFaces():
        try:
            typ, _pt, _dr, _box, rad, rdata, _ndir = \
                u.Modeling.AskFaceData(f.Tag)
        except Exception:
            continue
        sig[int(f.Tag)] = (int(typ), abs(float(rad)), float(rdata))
    return sig


def added_faces(before, after):
    """新增面 [{tag, type, radius, rad_data}]（按 tag 排序，便于逐刀对账）。"""
    return [{"tag": t, "type": v[0], "radius": v[1], "rad_data": v[2]}
            for t, v in sorted(after.items()) if t not in before]


def hole_chain(wp, target, segments, name="HOLECHAIN", back=1.5, tol=0.05,
               angle_tol_deg=0.5, verify=True):
    """同轴/异轴孔链：逐段独立切除，逐刀回读新增面并断言类型/半径/半角。

    segments 每段：入口/出口端点是实测 data，直径是设计表达式名，`*_mm` 是
    建表达式时用的数值（用来对账"声明值 vs 建出值"）：

      {"kind": "cylinder", "p0": (x,y,z), "p1": (x,y,z),
       "dia": "D_HOLE", "dia_mm": 10.0}
      {"kind": "cone", "p0": ..., "p1": ...,
       "dia_a": "D_IN", "dia_a_mm": 5.0, "dia_b": "D_OUT", "dia_b_mm": 7.0}

    为什么逐段：两段孔建成一条等径直孔时孔径对、孔长会差，而"看起来是孔"
    过不了 G2 的逐段长度比对。逐段切除让每段保留自己的直径与轴向区间，
    `checks` 逐刀给出证据（新增面类型/半径或半角），不靠"没报错"判定。

    外伸：圆柱两端各外伸 `back`（直径不变，通孔端不留薄壁）；圆锥只在出口
    按同一半角继续外伸——在入口外伸会像倒角一样削掉口部材料。
    """
    feats, bs, checks = [], [], []
    for i, seg in enumerate(segments):
        kind = str(seg.get("kind", "cylinder"))
        p0, p1 = _pt3(seg["p0"]), _pt3(seg["p1"])
        d = _unit3(p0, p1)
        length = _dist3(p0, p1)
        before = face_signature(target) if verify else {}
        if kind == "cylinder":
            start = (p0[0] - back * d[0], p0[1] - back * d[1],
                     p0[2] - back * d[2])
            tool = cylinder(wp, start, d, seg["dia"],
                            "%.6f" % (length + 2.0 * back))
            expect_type = CYLINDER_TYPE
        elif kind == "cone":
            ra = float(seg["dia_a_mm"]) / 2.0
            rb = float(seg["dia_b_mm"]) / 2.0
            k = (rb - ra) / length
            tool = cone(wp, p0, d, seg["dia_a"],
                        "%.6f" % (2.0 * (rb + k * back)),
                        "%.6f" % (length + back))
            expect_type = CONE_TYPE
        else:
            raise ValueError("unknown hole segment kind: %r" % (kind,))
        _named(tool["features"][0], "%s_%02d" % (name, i))
        cut(wp, target, tool["features"][0])
        feats.extend(tool["features"])
        bs.extend(tool["bodies"])
        row = {"segment": i, "kind": kind, "length": length, "ok": None,
               "added": [], "expect_type": expect_type, "reason": ""}
        if verify:
            added = added_faces(before, face_signature(target))
            row["added"] = [{"tag": a["tag"], "type": a["type"]}
                            for a in added]
            typed = [a for a in added if a["type"] == expect_type]
            if not typed:
                row["ok"] = False
                row["reason"] = ("no new type-%d face (added types %r)"
                                 % (expect_type,
                                    [a["type"] for a in added]))
            elif kind == "cylinder":
                want = float(seg["dia_mm"]) / 2.0
                got = min(typed, key=lambda a: abs(a["radius"] - want))
                row["ok"] = abs(got["radius"] - want) <= tol
                row["reason"] = ("new face radius %.4f vs declared %.4f"
                                 % (got["radius"], want))
                row["face_tag"] = got["tag"]
            else:
                # UF 圆锥面的 rad_data 符号约定未验证（实测一个收口锥报的是
                # 正半角），所以按半角**大小**对账，符号只打印出来备查。
                want = math.atan2(abs(float(seg["dia_b_mm"])
                                      - float(seg["dia_a_mm"])) / 2.0, length)
                got = min(typed, key=lambda a: abs(abs(a["rad_data"]) - want))
                row["ok"] = (abs(abs(got["rad_data"]) - want)
                             <= math.radians(angle_tol_deg))
                row["reason"] = ("new face half angle %.4f deg (signed %.4f) "
                                 "vs declared %.4f deg"
                                 % (math.degrees(abs(got["rad_data"])),
                                    math.degrees(got["rad_data"]),
                                    math.degrees(want)))
                row["face_tag"] = got["tag"]
        checks.append(row)
    bad = [c for c in checks if c["ok"] is False]
    return {"features": feats, "bodies": bs, "checks": checks,
            "count": len(checks), "pass": bool(checks) and not bad}


def eye_2lobe(wp, frame, lobe_uv, r_eye_expr, r_eye_mm, plan_uv,
              thickness_expr, name="EYE", tol=0.05):
    """双瓣耳端：平台轮廓（data）+ 两个圆瓣圆柱（半径是设计表达式），合并成一体。

    lobe_uv: [(u, +h), (u, -h)] 两瓣心（实测 data，h 是瓣心到孔轴的横向距离）；
    plan_uv: 平台闭合轮廓（实测 data，两侧直壁 |v| = W = h + R_EYE）；
    r_eye_expr / r_eye_mm: 圆瓣半径的表达式名与建表达式用的数值；
    thickness_expr: 厚度表达式（平台与两瓣共用同一厚度）；
    轮廓平面与圆瓣起点都在框架 z=0 平面，拉伸到 thickness_expr——要偏移
    就让 `frame.origin` 抬到起始面，builder 不藏第二个起点。

    为什么这样建：耳端外边界是"两条直壁 + 两个同半径圆瓣"，按销轴方向把
    孔侧棱柱外推会造出一个不存在的外角（实测某件外角多出 1.013 mm）。
    相切条件 `W = h + R_EYE` 是这套构造成立的判据，`checks` 把它算出来，
    不平（切）就会在直壁与圆瓣之间留下台阶或假外角。
    """
    n0 = len(list(wp.Bodies))
    plate = prism(wp, sk.loop_uv(wp, frame, plan_uv), sk.normalize(frame.Z),
                  "0.0", thickness_expr)
    _named(plate["features"][0], name + "_PLATE")
    target = plate["bodies"][0]
    feats = list(plate["features"])
    for j, (u, v) in enumerate(lobe_uv):
        p = frame.pt(float(u), float(v), 0.0)
        lobe = cylinder(wp, (p.X, p.Y, p.Z), sk.normalize(frame.Z),
                        "2*%s" % (r_eye_expr,), thickness_expr)
        _named(lobe["features"][0], "%s_LOBE%d" % (name, j))
        feats.extend(lobe["features"])
        unite(wp, target, lobe["features"][0])
    w_half = max(abs(float(p[1])) for p in plan_uv)
    h_lobe = max(abs(float(p[1])) for p in lobe_uv)
    gap = abs(w_half - (h_lobe + float(r_eye_mm)))
    feats_sig = face_signature(target)
    lobes_built = [t for t, v in feats_sig.items()
                   if v[0] == CYLINDER_TYPE
                   and abs(v[1] - float(r_eye_mm)) <= tol]
    checks = {
        "tangency_gap_mm": gap,
        "tangent": gap <= tol,
        "w_half": w_half,
        "h_lobe": h_lobe,
        "lobe_faces": sorted(lobes_built),
        "bodies": len(list(wp.Bodies)),
        "single_body_build": len(list(wp.Bodies)) == n0 + 1,
    }
    return {"features": feats, "bodies": [target], "checks": checks,
            "tangent_ok": gap <= tol}


def clevis(wp, frame, plan_uv, thickness_expr, thickness_mm, slot,
           name="CLEVIS", tol=0.05):
    """叉耳：平台轮廓 + 一条开口槽（槽在实测位置，宽度按声明值复算）。

    slot: {"u0": 槽底 u（data）, "u1": 槽口外 u（data，取到轮廓外）,
           "w_mm": 声明槽宽, "margin_mm": 刀具在厚度方向的外伸（默认 2）}
    槽的刀具体用实测轮廓坐标（曲线吃不了表达式），所以槽宽本身是**数据**：
    能驱动的设计参数是耳板厚度（`thickness_expr`）；要槽宽可驱动需要带对称
    偏置的拉伸（NX12 未验证），在报告里按"不可编辑结构"记，不冒充 G8。
    返回 checks：单实体、新增面里两条侧壁的间距 = 声明槽宽、槽底方向正确。
    """
    n0 = len(list(wp.Bodies))
    plate = prism(wp, sk.loop_uv(wp, frame, plan_uv), sk.normalize(frame.Z),
                  "0.0", thickness_expr)
    _named(plate["features"][0], name + "_PLATE")
    target = plate["bodies"][0]
    margin = float(slot.get("margin_mm", 2.0))
    w = float(slot["w_mm"]) / 2.0
    rect_uv = [(float(slot["u0"]), -w), (float(slot["u1"]), -w),
               (float(slot["u1"]), w), (float(slot["u0"]), w)]
    before = face_signature(target)
    tool = prism(wp, sk.loop_uv(wp, frame, rect_uv), sk.normalize(frame.Z),
                 "%.6f" % (-margin),
                 "%.6f" % (float(thickness_mm) + margin),
                 help_pt=frame.pt(float(slot["u0"]) + 1.0, 0.0,
                                  float(thickness_mm) / 2.0))
    _named(tool["features"][0], name + "_SLOT")
    cut(wp, target, tool["features"][0])
    added = added_faces(before, face_signature(target))
    faces_by_tag = dict((int(f.Tag), f) for f in target.GetFaces())
    walls, bottoms = [], []
    for a in added:
        if a["type"] != 22:
            continue
        f = faces_by_tag.get(a["tag"])
        if f is None:
            continue
        d = _uf().Modeling.AskFaceData(f.Tag)
        loc = frame.to_local(d[1])
        # 法向是**方向**，不能走 to_local（那是给点用的：to_local(p+d) 里
        # p 没被减掉，法向会被点坐标淹掉，槽端面会被当成侧壁）
        nd = _vec3(d[2])
        nrm = (sk.dot(nd, frame.U), sk.dot(nd, frame.V),
               sk.dot(nd, frame.Z))
        # 侧壁外法向沿 ±V（指向槽内），槽底/槽端外法向沿 ±U
        axis = max(range(3), key=lambda k: abs(nrm[k]))
        if axis == 1:
            walls.append(round(loc[1], 6))
        elif axis == 0:
            bottoms.append(round(loc[0], 6))
    spacing = (max(walls) - min(walls)) if len(walls) >= 2 else None
    checks = {
        "added": [{"tag": a["tag"], "type": a["type"]} for a in added],
        "wall_v": sorted(walls),
        "wall_spacing_mm": spacing,
        "wall_spacing_ok": (spacing is not None
                            and abs(spacing - float(slot["w_mm"])) <= 2.0 * tol),
        "bottom_u": sorted(bottoms),
        "bodies": len(list(wp.Bodies)),
        "single_body_build": len(list(wp.Bodies)) == n0 + 1,
    }
    return {"features": list(plate["features"]) + list(tool["features"]),
            "bodies": [target], "checks": checks}


def trim_planes(wp, target, trims, name="TRIM", span=1000.0):
    """按实测平面裁掉多余材料（替代"按包围盒/区域大盒修边"）。

    trims: [{"point": (x,y,z), "normal": (nx,ny,nz), "keep": "above"|"below"}]
      keep="above" 保留法向正侧：刀具从平面沿 -normal 拉 `span`，反之亦然。

    每刀后记体数与体积：修边不该产生第二个实体（不连通就说明刀切过了头），
    也不该什么都没切掉（方向选反）或把整件切光。返回 `checks` 逐刀给证据。
    """
    feats, checks = [], []
    for i, t in enumerate(trims):
        # 体数必须在造刀具**之前**数：刀具是独立体，布尔求差后才被吞并，
        # 造完再数会把"工具体还在"读成"修边多出一个体"。
        v_before = mdl.volume(wp, target)
        n_before = len(list(wp.Bodies))
        p = _pt3(t["point"])
        n = sk.normalize(t["normal"])
        keep = str(t.get("keep", "above")).lower()
        if keep not in ("above", "below"):
            raise ValueError("trim keep must be 'above' or 'below'")
        sign = -1.0 if keep == "above" else 1.0
        u = sk.perpendicular(n)
        frame = sk.Frame(p, u, sk.cross(n, u), n)
        half = float(span) / 2.0
        rect = [(-half, -half), (half, -half), (half, half), (-half, half)]
        direction = (sign * n[0], sign * n[1], sign * n[2])
        tool = prism(wp, sk.loop_uv(wp, frame, rect), direction, "0.0",
                     "%.6f" % float(span), help_pt=frame.pt(0.0, 0.0, 0.0))
        _named(tool["features"][0], "%s_%02d" % (name, i))
        try:
            cut(wp, target, tool["features"][0])
            n_after = len(list(wp.Bodies))
            # 方向选反会把整件切掉：那时体已不存在，体积按 0 记，别去读死体
            v_after = mdl.volume(wp, target) if n_after else 0.0
            removed = v_before - v_after
            reason = ""
            if n_after != n_before:
                reason = "body count %d -> %d" % (n_before, n_after)
            elif removed <= 1e-9:
                reason = "removed nothing (keep side reversed?)"
            elif removed >= (v_before - 1e-9):
                reason = "removed the whole body"
            checks.append({
                "index": i, "keep": keep, "removed": removed,
                "bodies": n_after, "ok": reason == "", "reason": reason,
            })
            feats.extend(tool["features"])
        except Exception as exc:
            # 目标体整个落在刀具里时布尔直接拒绝——"Target body completely
            # inside tool body" 就是保留侧选反的指纹，原文照记，不吞不重试
            first = (str(exc).splitlines() or [""])[0][:200]
            checks.append({
                "index": i, "keep": keep, "removed": 0.0,
                "bodies": len(list(wp.Bodies)), "ok": False,
                "reason": "boolean rejected: %s" % first,
            })
    return {"features": feats, "bodies": [target], "checks": checks,
            "pass": all(c["ok"] for c in checks) if checks else False}


# ------------------------------------------------------------ 斜切/曲面端壁

def profile_uz_curves(wp, frame, segs):
    """(u,z) 混合段剖面 → 曲线列表：直线段是 {"line": [p0, p1]}，圆弧段是
    {"arc": [center, radius, a0_deg, a1_deg]}（角度在 (u,z) 平面内，逆时针）。

    为什么需要：按采样点连折线时，一段 R8 的端壁会变成 24 个小平面，"曲端壁"
    最后全是平面，面型对不上、圆角也挂不上去。这里让圆弧以**一条圆弧曲线**
    进剖面，拉伸出来才是圆柱面。
    """
    out = []
    for seg in segs:
        if "line" in seg:
            p0, p1 = seg["line"]
            out.append(wp.Curves.CreateLine(
                frame.pt(float(p0[0]), 0.0, float(p0[1])),
                frame.pt(float(p1[0]), 0.0, float(p1[1]))))
        elif "arc" in seg:
            c, r, a0, a1 = seg["arc"]
            u_dir = frame.vec(1.0, 0.0, 0.0)
            z_dir = frame.vec(0.0, 0.0, 1.0)
            out.append(wp.Curves.CreateArc(
                frame.pt(float(c[0]), 0.0, float(c[1])),
                NXOpen.Vector3d(u_dir[0], u_dir[1], u_dir[2]),
                NXOpen.Vector3d(z_dir[0], z_dir[1], z_dir[2]),
                float(r), math.radians(float(a0)), math.radians(float(a1))))
        else:
            raise ValueError("profile segment needs 'line' or 'arc': %r" % (seg,))
    return out


def sweep_trim(wp, target, frame, profile_uz, v_span, name="SWEEPTRIM",
               keep="above", extra_mm=0.0, profile_segs=None):
    """按测量侧视轮廓扫掠切端壁：端壁不必是平面（斜切、带弧、台阶端面）。

    `trim_planes` 只能按单个平面裁；端面一旦是斜切带圆角、或沿臂长方向带
    台阶，就得用轮廓。做法：侧视轮廓 (u, z) 在 v=0 平面上闭合成环，沿 ±V
    拉成棱柱，再从 target 上求差。

    profile_uz 是**要保留的一侧**的边界轮廓（(u,z)，逆时针），
    `keep="above"` 表示轮廓围住的区域保留、棱柱体是刀；`keep="below"` 反过来
    用一个大矩形减去轮廓得到刀具。v_span 给 [v0, v1]，两端各外伸 extra_mm，
    保证切透；外伸量不要太大——刀具越长，NX 在窄壁处的求交越容易报
    intersection gaps。

    端壁带弧时用 `profile_segs`（`{"line":...}` / `{"arc":...}` 混合段）：
    折线剖面会把一段弧切成几十个小平面，端壁面型就不是柱面了。

    为什么不复用 `pocket_intersect`：那是"侧视 ∩ 俯视"的腔体；端壁是
    "侧视沿 V 全宽切穿"，用求交会把端壁削成腔。

    `checks` 记：体数（不该变）、去料体积、新增面类型（斜平面端壁只多平面，
    带弧端壁会多柱面）。
    """
    n0 = len(list(wp.Bodies))
    v0 = mdl.volume(wp, target)
    before = face_signature(target)
    v_lo = float(v_span[0]) - float(extra_mm)
    v_hi = float(v_span[1]) + float(extra_mm)
    direction = sk.normalize(frame.V)
    if str(keep).lower() == "above":
        if profile_segs is not None:
            # 混合段剖面：圆弧段保持解析，端壁才是曲面
            cs = profile_uz_curves(wp, frame, profile_segs)
        else:
            cs = sk.loop_uz(wp, frame, profile_uz, 0.0)
        hp = frame.pt(sum(p[0] for p in profile_uz) / float(len(profile_uz)),
                      0.0,
                      sum(p[1] for p in profile_uz) / float(len(profile_uz)))
        tool = prism(wp, cs, direction, "%.6f" % v_lo, "%.6f" % v_hi,
                     help_pt=hp)
    else:
        # keep="below"：刀具 = 侧视大矩形 − 轮廓。先建矩形棱柱，再用轮廓
        # 棱柱从它身上切掉——这样刀具本身就是 target 外的区域
        us = [float(p[0]) for p in profile_uz]
        zs = [float(p[1]) for p in profile_uz]
        pad = max(max(us) - min(us), max(zs) - min(zs)) * 2.0 + 10.0
        big = [(min(us) - pad, min(zs) - pad), (max(us) + pad, min(zs) - pad),
               (max(us) + pad, max(zs) + pad), (min(us) - pad, max(zs) + pad)]
        tool = prism(wp, sk.loop_uz(wp, frame, big, 0.0), direction,
                     "%.6f" % v_lo, "%.6f" % v_hi,
                     help_pt=frame.pt(min(us) - pad + 1.0, 0.0,
                                      min(zs) - pad + 1.0))
        inner = prism(wp, sk.loop_uz(wp, frame, profile_uz, 0.0), direction,
                      "%.6f" % (v_lo - 1.0), "%.6f" % (v_hi + 1.0),
                      help_pt=frame.pt(
                          sum(p[0] for p in profile_uz)
                          / float(len(profile_uz)), 0.0,
                          sum(p[1] for p in profile_uz)
                          / float(len(profile_uz))))
        _named(inner["features"][0], name + "_HOLE")
        cut(wp, tool["bodies"][0], inner["features"][0])
        _named(tool["features"][0], name + "_TOOL")
    _named(tool["features"][0], name)
    try:
        cut(wp, target, tool["features"][0])
    except Exception as exc:
        # 刀具整个在目标体外 = 轮廓没盖住料：这是"端壁位置选错"的指纹，
        # 原文照记，不吞不重试
        first = (str(exc).splitlines() or [""])[0][:200]
        return {"features": list(tool["features"]), "bodies": [],
                "checks": {"removed": 0.0, "bodies": len(list(wp.Bodies)),
                           "ok": False, "added_types": [],
                           "reason": "boolean rejected: %s" % first},
                "pass": False}
    v1 = mdl.volume(wp, target)
    n1 = len(list(wp.Bodies))
    added = added_faces(before, face_signature(target))
    types = sorted(set(a["type"] for a in added))
    removed = v0 - v1
    # `n0` counts bodies before the tool was built.  A successful cut swallows
    # the tool, so n1 must return to n0; a leftover tool body means the cut
    # did not consume it and is a defect, not a pass.
    checks = {
        "added_types": types,
        "added_count": len(added),
        "removed": removed,
        "bodies": n1,
        "bodies_before": n0,
        "single_body_build": n1 == n0,
        "ok": (n1 == n0) and removed > 1e-9,
    }
    if not checks["ok"]:
        checks["reason"] = ("body count %d -> %d" % (n0, n1)
                            if n1 != n0 else "removed nothing")
    return {"features": list(tool["features"]), "bodies": [target],
            "checks": checks, "pass": checks["ok"]}


# ------------------------------------------------------------------ 变截面臂

def _point_in_ring(p, ring):
    """射线法判点是否在闭合折线内（环可以凹，不要求星形）。"""
    x, y = float(p[0]), float(p[1])
    inside = False
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def _resample_ring(pts_uv, n, phase=0, center=None):
    """闭合轮廓 → 等角 N 点：绕参考点取射线，每角取边界交点。

    为什么不用弧长等分：相邻截面拓扑不同（一边是直壁+圆角，另一边是样条）
    时弧长参数化的对应点会漂，放样自交。等角参数化的索引就是角度，与起点
    无关；代价是只对星形截面保形。

    `center` 缺省取顶点平均；顶点平均不是面积形心，C/L/U 形的平均值常落在
    开口里，所以先判参考点是否在料内，不在就报错（"参考点选错"与"形状凹"
    是两回事，混在一起无法归因）。

    非星形截面**抛错**，不静默填凹口：每条射线与边界的交点必须恰好一个
    （两个共点算一个，顶点处的两条边就是这么数的）。射线进出两次说明参考
    点看不到那片料，"最外交点"会落到凹口另一侧的壁上——放样出来就是自交
    或把凹口填平。凹口要么放样后切，要么换一条沿轮廓的定位线做参数化。
    """
    cen = ((float(center[0]), float(center[1])) if center is not None
           else (sum(p[0] for p in pts_uv) / float(len(pts_uv)),
                 sum(p[1] for p in pts_uv) / float(len(pts_uv))))
    if not _point_in_ring(cen, pts_uv):
        # 顶点平均不是面积形心：C/L/U 形的平均顶点常落在开口里。参考点不在
        # 料内时射线参数化没有定义，必须先说清是"参考点选错"而不是"形状不好"
        raise ValueError(
            "resample: reference point (%.3f, %.3f) is outside the ring; "
            "pass a point that lies inside the section" % cen)
    span = max(max(abs(p[0] - cen[0]), abs(p[1] - cen[1])) for p in pts_uv)
    eps = max(span * 1e-7, 1e-12)
    out = []
    for k in range(int(n)):
        a = 2.0 * math.pi * (k + float(phase)) / float(n)
        dx, dy = math.cos(a), math.sin(a)
        hits = []
        for i in range(len(pts_uv)):
            x0, y0 = pts_uv[i]
            x1, y1 = pts_uv[(i + 1) % len(pts_uv)]
            ex, ey = x1 - x0, y1 - y0
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = ((x0 - cen[0]) * ey - (y0 - cen[1]) * ex) / den
            s = ((x0 - cen[0]) * dy - (y0 - cen[1]) * dx) / den
            if t <= 0.0 or s < 0.0 or s > 1.0:
                continue
            if not hits or abs(t - hits[-1]) > eps:
                hits.append(t)
        if len(hits) > 1:
            raise ValueError(
                "resample: non-star ring at angle %.4f deg (%d boundary "
                "crossings); cut the notch after the loft instead"
                % (math.degrees(a), len(hits)))
        if not hits:
            raise ValueError("resample: no boundary crossing at angle %.4f deg"
                             % math.degrees(a))
        out.append((cen[0] + hits[0] * dx, cen[1] + hits[0] * dy))
    return out


def section_loft(wp, sections, name="LOFT", body_preference=True):
    """结构分界截面 → 一张放样实体（变截面臂的唯一正解，不是 z 带堆叠）。

    sections 每张：{"plane": (origin, normal), "uv": [(u, v)]} —— 平面按
    实测法向/原点（data），`uv` 是该平面内绕形心等角参数化的轮廓点
    （`_resample_ring` 的输出，或调用方自己按同一角度表采的点）。所有截面
    必须先归一到**同一 N**，否则放样的对应点会扭。

    截面基向量不是各算各的：`sk.perpendicular(normal)` 对相邻法向会跳到
    不同的参考轴，索引相同但方向不同，放样照样是扭的。这里从首张截面取
    (u, v)，往后逐张把 u 投影到本截面平面再正交化（法向转 <90° 时索引
    连续）；相邻法向转得太多就无法保持对应，由调用方负责插中间截面。

    为什么必须查体积：对应关系扭曲时 `ThroughCurves` 仍然提交，得到
    `IsSolidBody=True`、体积 0 的自交实体；截面 IoU 还能到 0.99。所以
    `checks` 里既记实体性也记体积，体积 0 即失败。

    首末截面外侧各加一张等形平移截面可压住端部塌陷；需要时由调用方把平移
    截面一起放进 `sections`，builder 不自己猜外延量。
    """
    if len(sections) < 2:
        raise ValueError("section_loft needs >= 2 sections")
    counts = set(len(s["uv"]) for s in sections)
    if len(counts) != 1:
        raise ValueError("sections must share one resampled count: %r"
                         % (sorted(counts),))
    n = counts.pop()
    curves = []
    prev_u = None
    for sec in sections:
        origin, normal = sec["plane"]
        origin = _pt3(origin)
        nrm = sk.normalize(normal)
        if prev_u is None:
            u = sk.perpendicular(nrm)
        else:
            w = sk.dot(prev_u, nrm)
            u = sk.normalize([prev_u[i] - w * nrm[i] for i in range(3)])
        v = sk.cross(nrm, u)
        prev_u = u
        pts = []
        for (a, b) in sec["uv"]:
            pts.append(NXOpen.Point3d(origin[0] + a * u[0] + b * v[0],
                                      origin[1] + a * u[1] + b * v[1],
                                      origin[2] + a * u[2] + b * v[2]))
        curves.extend([wp.Curves.CreateLine(pts[k], pts[(k + 1) % n])
                       for k in range(n)])
    secs = wp.Sections.CreateSectionsUsingCurves(
        curves, NXOpen.SectionCollection.LoopOption.Separate, 0.01, 0.01, 0.5)
    tb = wp.Features.CreateThroughCurvesBuilder(NULL)
    if body_preference:
        tb.BodyPreference = \
            NXOpen.Features.ThroughCurvesBuilder.BodyPreferenceTypes.Solid
    for sec in secs:
        tb.SectionsList.Append(sec)
    tb.Validate()
    f = tb.CommitFeature()
    tb.Destroy()
    bs = bodies_of(f)
    _named(f, name)
    body = bs[0] if bs else None
    vol = mdl.volume(wp, body) if body is not None else 0.0
    sheet = bool(body.IsSheetBody) if body is not None else True
    nf = len(list(body.GetFaces())) if body is not None else 0
    checks = {
        "sections": len(sections),
        "ring_points": n,
        "bodies": len(bs),
        "is_solid": (not sheet) and len(bs) == 1,
        "volume": vol,
        "faces": nf,
        "features": 1,
    }
    return {"features": [f], "bodies": bs, "checks": checks,
            "pass": checks["is_solid"] and vol > 1e-6}


# ------------------------------------------------------------------ 拔模窗口

def window_cut(wp, target, frame, plan_uv, z0, z1, name="WINDOW",
               draft_expr=None):
    """窗口/袋的切除体：一平面轮廓 + 拉伸（可带拔模），再对 target 求差。

    与 `pocket_intersect` 的分工：那是"侧视 ∩ 俯视"的双轮廓腔；窗口只需要
    一个平面轮廓沿自身法向切透，侧壁由拔模角决定（铸造窗口的常见形态：口
    大底小）。`draft_expr` 给表达式名时走 `plate_2p5d` 的拔模路径——只设
    角度不设类型在 NX12 是静默无效，所以这里不提供"只给角度"的入口。

    为什么不在这里做口部圆角：圆角必须在减料之后按支撑面宽度前置判定
    （`fillet_feasible`），且支撑面宽度 < 2R 时会失败；把它塞进这个函数
    会让失败原因和窗口本身混在一起。调用方在 `cut` 之后单独跑 `fillet_run`。

    `checks` 记：单实体、去掉的体积、新增面类型（平面窗口应只多平面与锥面）。
    """
    n0 = len(list(wp.Bodies))
    v0 = mdl.volume(wp, target)
    before = face_signature(target)
    # 刀具与求差要一起回滚：布尔被拒时刀具体留在部件里（体数 +1），
    # 下次读体数就会把"上次失败的刀具体"算成本次的成功
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                              name)
    try:
        tool = plate_2p5d(wp, frame, plan_uv, str(z0), str(z1),
                          name=name + "_TOOL", draft_expr=draft_expr)
        tf = tool["features"][0]
        cut(wp, target, tf)
    except Exception as exc:
        # 刀具整个在目标体外时 NX12 直接拒绝布尔（"completely outside"）：
        # 这是"窗口位置选错"的指纹，原文照记，不吞不重试
        first = (str(exc).splitlines() or [""])[0][:200]
        try:
            session.UndoToMark(mark, name)
            session.DeleteUndoMark(mark, name)
        except Exception:
            pass
        return {"features": [], "bodies": [],
                "checks": {"removed": 0.0,
                           "bodies": len(list(wp.Bodies)),
                           "single_body_build": True, "ok": False,
                           "added_types": [],
                           "reason": "boolean rejected: %s" % first},
                "pass": False}
    session.DeleteUndoMark(mark, name)
    v1 = mdl.volume(wp, target)
    n1 = len(list(wp.Bodies))
    added = added_faces(before, face_signature(target))
    types = sorted(set(a["type"] for a in added))
    removed = v0 - v1
    checks = {
        "added": [{"tag": a["tag"], "type": a["type"],
                   "radius": round(a["radius"], 6)} for a in added],
        "added_types": types,
        "removed": removed,
        "bodies": n1,
        "single_body_build": n1 == n0,
        "ok": (n1 == n0) and removed > 1e-9,
    }
    if not checks["ok"]:
        checks["reason"] = ("body count %d -> %d" % (n0, n1)
                            if n1 != n0 else "removed nothing")
    return {"features": list(tool["features"]), "bodies": [target],
            "checks": checks, "pass": checks["ok"]}
