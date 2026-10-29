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
