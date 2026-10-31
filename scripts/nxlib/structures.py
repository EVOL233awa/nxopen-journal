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

NULL = NXOpen.Features.Feature.Null


def _uf():
    return NXOpen.UF.UFSession.GetUFSession()


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
    f = mdl._extrude_along(wp, curves, _vec3(direction), d1, d0, hp)
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
    direction = sk.normalize(frame.Z)
    hp = help_pt if help_pt is not None else _centroid_pt(wp, frame, plan_uv)
    if draft_expr is None:
        f = mdl._extrude_along(wp, cs, direction, z1, z0, hp)
        return {"features": [_named(f, name)], "bodies": bodies_of(f)}
    section = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
    rule = wp.ScRuleFactory.CreateRuleCurveDumb(cs)
    section.AddToSection([rule], NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                         NXOpen.NXObject.Null, hp, NXOpen.Section.Mode.Create,
                         False)
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
    return {"features": [_named(f, name)], "bodies": bodies_of(f)}


def revolved_profile(wp, profile_tr, axis_pt=(0.0, 0.0, 0.0),
                     axis_dir=(0.0, 0.0, 1.0), name="REVOLVE",
                     radials=None, unite=True):
    """(轴向 t, 半径 r) 轮廓 → 分段凸锥台 → 回转并合并成一个体。

    profile_tr: [(t, r)]，t 沿 axis_dir、r 为到轴的垂直距离；
    r == 0 的点在轴上（锥尖），相邻两点可都在轴上（该段跳过）。

    为什么按段回转：360° 回转只吃凸轮廓，带台阶/凹陷的整条轮廓报
    "Cannot create Swept geometry"；把轮廓切成单调段后逐段回转再合并，
    台阶位置不被平滑掉，也不产生 z 带棱柱的段间台阶面。
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
        t0, r0 = float(profile_tr[i][0]), float(profile_tr[i][1])
        t1, r1 = float(profile_tr[i + 1][0]), float(profile_tr[i + 1][1])
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


def fillet_run(wp, edges, radius_expr, name="FILLET", edges_id=None):
    """逐边倒圆 + 逐边账本（G7 跑道账本的最小形态）。

    `blend_try` 失败只给 None，账本拿不到原因就无法回答"这条跑道为什么
    不可达"。这里自己开 undo mark：失败回滚并把原文留在 `msg`，成功记
    `ok` 与半径。**一条失败不影响后续边**——跑道账本就是逐条记账。

    edges_id: 可传入与 edges 对齐的 id 列表（例如跑道号），默认用下标。
    返回 {"features", "bodies", "ledger": [{id, ok, radius, msg}]}。
    """
    session = NXOpen.Session.GetSession()
    out, bs = [], []
    ledger = []
    ids = list(edges_id) if edges_id is not None else list(range(len(edges)))
    for e, eid in zip(edges, ids):
        tag = "%s_%s" % (name, eid)
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, tag)
        try:
            res = blend_edges(wp, [e], radius_expr)
            session.DeleteUndoMark(mark, tag)
            out.extend(res["features"])
            bs.extend(res["bodies"])
            ledger.append({"id": eid, "ok": True, "radius": str(radius_expr),
                           "msg": ""})
        except Exception as exc:
            msg = str(exc).splitlines()
            try:
                session.UndoToMark(mark, tag)
                session.DeleteUndoMark(mark, tag)
            except Exception:
                pass
            ledger.append({"id": eid, "ok": False, "radius": str(radius_expr),
                           "msg": (msg[0] if msg else "")[:200]})
    return {"features": out, "bodies": bs, "ledger": ledger,
            "pass": all(r["ok"] for r in ledger) if ledger else False}
