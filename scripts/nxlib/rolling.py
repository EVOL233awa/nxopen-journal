# -*- coding: utf-8 -*-
"""nxlib.rolling —— 滚球圆角的截面刀与 B 类角面判定。

三种在 NX12 批处理里实测走通的构造（见 references/reverse-engineering.md §9）：

  roll_edge_general  直边：截面 = 角区 − 滚圆，沿边拉伸。支撑面可以是平面、
                     圆柱、圆锥或环面，只要两支撑法向沿边不变（直边是支撑面
                     的直纹）。凸边 Subtract、凹边 Unite；刀面是 type16/17
                     圆柱/圆锥，能被 G7 认成建出的圆角面。
  roll_rim           圆边（凸台口、孔口、环面角）：同一截面绕边圆心轴旋转。
                     环面半径 R、主半径 = 滚球中心圆半径（≠ 边圆半径），刀面是
                     精确 type19，rad_data = R；喇叭环面（主半径 = R）同样可建，
                     但只对部分弧旋转，整圈会自交。
  classify_corner    B 类角面：沿 ±法向偏置 R，薄的一侧坍缩成脊线；判类取点云
                     第三主成分 thickness：≤0.005·R 且圆残差 ≤1e-9 判精确管道，
                     0.005–0.05·R 判近似角片，>0.05·R 判未知，s[0]/s[1]≤0.01 判球。

坐标与符号约定：
  - 截面的 2D 原点在边上，e1/e2 由两支撑法向和边切向构造（与 roll_edge 同）。
  - `add=False` 是凸边（从材料上切掉角区），`add=True` 是凹边（把角区补上）。
  - 圆边旋转角 `a0/a1` 从边拟合圆的平面基向量量起；整圈边用 0–360。
"""

import math

import NXOpen
import NXOpen.UF

import nxlib.modeling as mdl
from .session import _cross as _session_cross, _dot, _sub as _session_sub, _ufs, _unit as _session_unit


def _sub(a, b):
    return tuple(_session_sub(a, b))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    v = _session_unit(a, zero="none")
    return tuple(v) if v is not None else None


def _cross(a, b):
    return tuple(_session_cross(a, b))


def _as_tuple(p):
    # UF 查询返回 list；NXOpen.Point3d 只能按属性取，不能下标
    try:
        return (float(p[0]), float(p[1]), float(p[2]))
    except TypeError:
        return (float(p.X), float(p.Y), float(p.Z))


# ------------------------------------------------------------------ 拟合
def _jacobi_eig(a):
    a = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(60):
        off = sum(a[i][j] * a[i][j] for i in range(3) for j in range(3)
                  if i != j)
        if off < 1e-24:
            break
        for p in range(3):
            for q in range(p + 1, 3):
                if abs(a[p][q]) < 1e-20:
                    continue
                theta = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
                c, s = math.cos(theta), math.sin(theta)
                for k in range(3):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(3):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(3):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    return sorted(((a[i][i], [v[0][i], v[1][i], v[2][i]]) for i in range(3)),
                  key=lambda t: -t[0])


def pca(points):
    n = len(points)
    c = [sum(p[i] for p in points) / n for i in range(3)]
    cov = [[0.0] * 3 for _ in range(3)]
    for p in points:
        q = _sub(p, c)
        for i in range(3):
            for j in range(3):
                cov[i][j] += q[i] * q[j] / n
    eig = _jacobi_eig(cov)
    axes = [_unit(e[1]) for e in eig]
    proj = [_dot(_sub(p, c), axes[0]) for p in points]
    return {"center": c, "s": [math.sqrt(max(0.0, e[0])) for e in eig],
            "axes": axes,
            "span1": (max(proj) - min(proj)) if proj else 0.0}


def _solve3(a, b):
    a = [row[:] for row in a]
    b = list(b)
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(a[r][i]))
        if abs(a[piv][i]) < 1e-14:
            return None
        if piv != i:
            a[i], a[piv] = a[piv], a[i]
            b[i], b[piv] = b[piv], b[i]
        for r in range(i + 1, 3):
            f = a[r][i] / a[i][i]
            for c in range(i, 3):
                a[r][c] -= f * a[i][c]
            b[r] -= f * b[i]
    x = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        s = b[i] - sum(a[i][j] * x[j] for j in range(i + 1, 3))
        x[i] = s / a[i][i]
    return x


def circle_fit2(pts):
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    syy = sum(p[1] * p[1] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    sx3 = sum(p[0] ** 3 for p in pts)
    sy3 = sum(p[1] ** 3 for p in pts)
    sx2y = sum(p[0] * p[0] * p[1] for p in pts)
    sxy2 = sum(p[0] * p[1] * p[1] for p in pts)
    a = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    b = [sx3 + sxy2, sx2y + sy3, sxx + syy]
    x = _solve3(a, b)
    if x is None:
        return {"ok": False, "reason": "singular"}
    cx, cy = x[0] * 0.5, x[1] * 0.5
    r2 = x[2] + cx * cx + cy * cy
    if r2 <= 0:
        return {"ok": False, "reason": "negative r2"}
    r = math.sqrt(r2)
    ds = [math.hypot(p[0] - cx, p[1] - cy) - r for p in pts]
    return {"ok": True, "c": [cx, cy], "r": r,
            "rms": math.sqrt(sum(d * d for d in ds) / n),
            "max": max(abs(d) for d in ds)}


def fit_circle3d(points):
    """3D 点云 → 平面 + 圆。返回 center/axis/r/rms/span_deg/a0/a1。"""
    pc = pca(points)
    # axes are sorted by descending eigenvalue; the plane normal is the
    # smallest one, the two in-plane directions are the first two.
    o = pc["axes"][2]
    e1 = pc["axes"][0]
    e2 = _cross(o, e1)
    uv = [(_dot(_sub(p, pc["center"]), e1),
           _dot(_sub(p, pc["center"]), e2)) for p in points]
    fit = circle_fit2(uv)
    if not fit["ok"]:
        return {"ok": False, "reason": fit.get("reason")}
    c3 = _add(pc["center"],
              _add(_mul(e1, fit["c"][0]), _mul(e2, fit["c"][1])))
    ang = [math.atan2(p[1] - fit["c"][1], p[0] - fit["c"][0]) for p in uv]
    # unwrap so the samples describe one contiguous arc
    unwrapped = [ang[0]]
    for a in ang[1:]:
        d = a - unwrapped[-1]
        while d > math.pi:
            d -= 2.0 * math.pi
        while d < -math.pi:
            d += 2.0 * math.pi
        unwrapped.append(unwrapped[-1] + d)
    return {"ok": True, "center": c3, "axis": o, "r": fit["r"],
            "rms": fit["rms"], "plane_rms": pc["s"][2],
            "span_deg": math.degrees(max(unwrapped) - min(unwrapped)),
            "a0": min(unwrapped), "a1": max(unwrapped),
            "e1": e1, "e2": e2}


def fit_line3d(points):
    pc = pca(points)
    d = pc["axes"][0]
    c = pc["center"]
    ts = [_dot(_sub(p, c), d) for p in points]
    dev = max(_norm(_sub(p, _add(c, _mul(d, t))))
              for p, t in zip(points, ts))
    return {"ok": dev < 1e-4, "direction": d, "point": c,
            "length": max(ts) - min(ts), "dev": dev,
            "p0": _add(c, _mul(d, min(ts))),
            "p1": _add(c, _mul(d, max(ts)))}


# ------------------------------------------------------------------ 面/边取数
def face_normal_at(part, face, point):
    """点到面的 UV 投影 + AskFaceProps 法向。NX12 的 EvaluateFace.SrfNormal 全零。"""
    u = _ufs()
    try:
        parm, foot = u.Modeling.AskFaceParm2(int(face.Tag), list(point))
    except Exception:
        return None, None
    try:
        props = u.Modeling.AskFaceProps(int(face.Tag), list(parm))
    except Exception:
        return None, None
    n = _unit(_as_tuple(props[5]))
    return n, [float(parm[0]), float(parm[1])]


def face_samples(part, face_tag, grid=7):
    """UV 网格采样：点 + 法向。B 面判定与角片分类都用它。"""
    u = _ufs()
    rng = [float(x) for x in u.Modeling.AskFaceUvMinmax(int(face_tag))]
    out = []
    for i in range(grid):
        for j in range(grid):
            uv = [rng[0] + (rng[1] - rng[0]) * (i + 0.5) / grid,
                  rng[2] + (rng[3] - rng[2]) * (j + 0.5) / grid]
            try:
                props = u.Modeling.AskFaceProps(int(face_tag), uv)
            except Exception:
                continue
            p = _as_tuple(props[0])
            n = _unit(_as_tuple(props[5]))
            if n is None:
                continue
            out.append({"uv": uv, "p": p, "n": n})
    return out


def edge_points(edge, n=9):
    u = _ufs()
    pts = []
    for i in range(n):
        t = 0.02 + 0.96 * i / (n - 1.0)
        try:
            pts.append(_as_tuple(u.ModlGeneral.AskCurveProps(int(edge.Tag), t)[0]))
        except Exception:
            continue
    return pts


def edge_geometry(edge, n=9):
    pts = edge_points(edge, n)
    if len(pts) < 5:
        return {"ok": False, "reason": "short samples %d" % len(pts)}
    ln = fit_line3d(pts)
    if ln["ok"]:
        return {"ok": True, "kind": "line", "line": ln, "points": pts}
    ci = fit_circle3d(pts)
    if ci["ok"] and ci["rms"] < 0.01 and ci["plane_rms"] < 0.01:
        closed = False
        try:
            per = 2.0 * math.pi * ci["r"]
            closed = per > 1e-6 and abs(edge.GetLength() - per) < 0.01 * per
        except Exception:
            pass
        ci.update({"ok": True, "kind": "circle", "closed": closed})
        if closed:
            ci["span_deg"] = 360.0
        return {"ok": True, "kind": "circle", "circle": ci,
                "points": pts, "closed": closed}
    return {"ok": False, "reason": "neither line nor circle"}


def edge_faces(edge):
    return [f for f in edge.GetFaces()]


def edge_mid(pts):
    return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


# ------------------------------------------------------------------ 截面
def _to3(base, e1, e2, xy):
    return NXOpen.Point3d(base[0] + xy[0] * e1[0] + xy[1] * e2[0],
                          base[1] + xy[0] * e1[1] + xy[1] * e2[1],
                          base[2] + xy[0] * e1[2] + xy[1] * e2[2])


def _profile_curves(wp, sec, base):
    e1, e2 = sec["e1"], sec["e2"]
    r = sec["radius"]
    c_out = sec["c_out"]
    ox, oy = sec["ox"], sec["oy"]
    a0, a1 = sec["arc_a0"], sec["arc_a1"]
    p_arc0 = (ox + r * math.cos(a0), oy + r * math.sin(a0))
    p_arc1 = (ox + r * math.cos(a1), oy + r * math.sin(a1))
    line0 = wp.Curves.CreateLine(_to3(base, e1, e2, c_out),
                                 _to3(base, e1, e2, p_arc0))
    arc = wp.Curves.CreateArc(_to3(base, e1, e2, (ox, oy)),
                              NXOpen.Vector3d(*e1),
                              NXOpen.Vector3d(*e2),
                              float(r), a0, a1)
    line1 = wp.Curves.CreateLine(_to3(base, e1, e2, p_arc1),
                                 _to3(base, e1, e2, c_out))
    return [line0, arc, line1], _to3(base, e1, e2, (ox, oy))


def _revolve_uf(wp, curves, center, axis, a0, a1):
    uf = _ufs()
    before = set(int(b.Tag) for b in wp.Bodies)
    uf.Modl.CreateRevolved([c.Tag for c in curves],
                           ["%.9f" % math.degrees(a0),
                            "%.9f" % math.degrees(a1)],
                           [float(v) for v in center],
                           [float(v) for v in axis],
                           NXOpen.UF.ModlFeatureSigns.NULLSIGN)
    new = [b for b in wp.Bodies if int(b.Tag) not in before]
    return new[0] if new else None


# ------------------------------------------------------------------ 刀
def roll_edge_general(wp, edge, radius, add=None, min_len=None):
    """直边截面刀：返回 (feature, area, expected_volume) 或 None。

    与 modeling.roll_edge 的差别：不要求两面是平面，法向取边中点处的面法向；
    支撑面沿边法向不变（直纹）时截面恒定。曲面支撑的直边也走这里。
    """
    pts = edge_points(edge, 7)
    if len(pts) < 5:
        return None
    geo = edge_geometry(edge)
    if not geo.get("ok") or geo["kind"] != "line":
        return None
    ln = geo["line"]
    p0, p1 = ln["p0"], ln["p1"]
    ln_len = ln["length"]
    if ln_len < (4.0 * radius if min_len is None else min_len):
        return None
    dv = _unit(_sub(p1, p0))
    mid = edge_mid(pts)
    fs = edge_faces(edge)
    if len(fs) != 2:
        return None
    nrm = []
    for f in fs:
        n, _ = face_normal_at(wp, f, mid)
        if n is None or abs(_dot(n, dv)) > 0.5:
            return None
        nrm.append(n)
    if add is None:
        return None
    sec = mdl.section_profile(nrm[0], nrm[1], dv, radius, add)
    if not sec["ok"]:
        return None
    ee = min(0.8, 0.25 * ln_len)
    base = _sub(p0, _mul(dv, ee))
    curves, help_pt = _profile_curves(wp, sec, base)
    try:
        feat = mdl.extrude_along(wp, curves, dv, repr(ln_len + 2.0 * ee),
                                 repr(ee), help_pt)
    except Exception:
        return None
    return feat, sec["area"], sec["area"] * ln_len


def roll_rim(wp, edge, radius, add=None, span_override=None,
             overlap_deg=0.25):
    """圆边截面刀：返回 (body, area, expected_volume) 或 None。

    截面在边起点处构造，绕边拟合圆的轴旋转。喇叭环面（主半径 = R）整圈
    旋转会自交，必须按边的实际弧段旋转；`span_override` 可强制角段。
    """
    pts = edge_points(edge, 11)
    if len(pts) < 7:
        return None
    geo = edge_geometry(edge, 11)
    if not geo.get("ok") or geo["kind"] != "circle":
        return None
    ci = geo["circle"]
    if ci["r"] < radius * 0.2:
        return None
    if ci["r"] <= radius + 1e-6:
        # 喇叭环：截面绕边轴整圈会跨轴自交，必须走 analytic/horn 外侧环。
        return None
    # 边的起点/切向；闭合边用角度 0 处。切向取拟合圆在该点的解析方向，
    # 不用 pts[0]→pts[1] 的弦（11 点整圈时弦与切向差约 16°）。
    fs = edge_faces(edge)
    if len(fs) != 2:
        return None
    station = pts[0]
    radial = _sub(station, ci["center"])
    tangent = _unit(_cross(ci["axis"], radial))
    if tangent is None:
        return None
    chord = _sub(pts[1], pts[0])
    if _dot(tangent, chord) < 0.0:
        tangent = _mul(tangent, -1.0)
    nrm = []
    for f in fs:
        n, _ = face_normal_at(wp, f, station)
        if n is None or abs(_dot(n, tangent)) > 0.5:
            return None
        nrm.append(n)
    if add is None:
        return None
    sec = mdl.section_profile(nrm[0], nrm[1], tangent, radius, add)
    if not sec["ok"]:
        return None
    # 喇叭环（滚球中心主半径 = R）：截面绕边轴整圈会跨轴自交，必须走
    # analytic 的外侧环。判据在滚球中心上，不在锐边半径上。
    ax = _unit(ci["axis"])
    c3 = _as_tuple(_to3(station, sec["e1"], sec["e2"],
                        (sec["ox"], sec["oy"])))
    rel = _sub(c3, ci["center"])
    maj = _norm(_sub(rel, _mul(ax, _dot(rel, ax))))
    if maj <= radius + 1e-6:
        return None
    a0 = ci["a0"]
    a1 = ci["a1"]
    if span_override is not None:
        a0, a1 = math.radians(span_override[0]), math.radians(span_override[1])
    if geo.get("closed") or (a1 - a0) > math.radians(359.0):
        span = 2.0 * math.pi
    else:
        # the profile sits at pts[0]; CreateRevolved sweeps from the
        # profile plane, so the sweep is the arc span, not [a0, a1].
        span = max(0.0, a1 - a0) + 2.0 * math.radians(overlap_deg)
    curves, _ = _profile_curves(wp, sec, station)
    try:
        body = _revolve_uf(wp, curves, ci["center"], ci["axis"], 0.0, span)
    except Exception:
        return None
    if body is None or body.IsSheetBody:
        return None
    arc_len = ci["r"] * max(1e-6, span)
    return body, sec["area"], sec["area"] * arc_len


def apply_roll_general(wp, body, edge, radius, add=None):
    """在已建实体上滚一条边：圆边走 roll_rim，直边走 roll_edge_general。

    返回 {"ok", "kind", "area", "dv", "body"}。凸凹不明时先试 `add`，体积
    变化符号不对就把这一刀回滚、换另一侧重试。每次尝试独立 undo mark。
    """
    session = NXOpen.Session.GetSession()
    geo = edge_geometry(edge)
    kind = geo.get("kind") if geo.get("ok") else None
    if kind is None:
        return {"ok": False, "reason": "edge not line/circle"}
    if kind == "circle" and add is not True:
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Invisible, "roll_rim_analytic")
        try:
            res = roll_rim_analytic(wp, body, edge, radius)
        except Exception:
            res = {"ok": False, "reason": "analytic raised"}
        if res.get("ok"):
            session.DeleteUndoMark(mark, None)
            return {"ok": True, "kind": "circle_analytic",
                    "add": False, "area": None, "dv": -res["removed"],
                    "body": res["body"]}
        keep_tag = body.Tag
        session.UndoToMark(mark, None)
        session.DeleteUndoMark(mark, None)
        body = next((b for b in wp.Bodies
                     if not b.IsSheetBody and b.Tag == keep_tag), body)
    trials = [add] if add is not None else [False, True]
    for wants_add in trials:
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                                   "roll_general")
        res = (roll_rim(wp, edge, radius, wants_add) if kind == "circle"
               else roll_edge_general(wp, edge, radius, wants_add))
        if res is None:
            session.DeleteUndoMark(mark, None)
            continue
        tool, area, exp = res
        tool_body = tool if kind == "circle" else tool.GetBodies()[0]
        v0 = mdl.volume(wp, body)
        op = (NXOpen.Features.Feature.BooleanType.Unite if wants_add
              else NXOpen.Features.Feature.BooleanType.Subtract)
        try:
            mdl.boolean(wp, body, tool_body, op)
        except Exception:
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
            continue
        v1 = mdl.volume(wp, body)
        dv = v1 - v0
        if wants_add:
            good = 0.65 * exp <= dv <= 1.35 * exp
        else:
            good = -1.35 * exp <= dv <= -0.65 * exp
        if not good:
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
            continue
        session.DeleteUndoMark(mark, None)
        bodies = [b for b in wp.Bodies if not b.IsSheetBody]
        # the boolean consumes the tool; the target is the only solid left
        # apart from unrelated bodies, so re-fetch by the largest overlap
        body = bodies[0] if len(bodies) == 1 else body
        return {"ok": True, "kind": kind, "add": wants_add,
                "area": area, "dv": dv, "body": body}
    return {"ok": False, "reason": "both signs rejected"}


# ------------------------------------------------------------------ B 类角面
def classify_corner(part, face_tag, radius, grid=7):
    """±R 偏置坍缩判类：canal_circle / canal_line / canal_approx / sphere。

    返回 dict：sign、locus（偏置点）、pca、circle（中心/轴/半径/角度）、
    sphere（球拟合）、thickness（第三主成分 RMS）。判据：
      thickness ≤ 0.005·R：s[0]、s[1] 均 ≤ 0.01 → 球；否则圆拟合 rms ≤ 1e-9 →
      canal_circle，再否则 → canal_approx；0.005·R < thickness ≤ 0.05·R →
      canal_approx；thickness > 0.05·R → unknown。
    """
    samples = face_samples(part, face_tag, grid)
    if len(samples) < 9:
        return {"ok": False, "reason": "samples %d" % len(samples)}
    best = None
    for sign in (1.0, -1.0):
        locus = [_add(s["p"], _mul(s["n"], sign * radius)) for s in samples]
        pc = pca(locus)
        thick = pc["s"][2]
        if best is None or thick < best["thickness"]:
            best = {"sign": sign, "locus": locus, "pca": pc,
                    "thickness": thick}
    pc = best["pca"]
    out = {"ok": True, "sign": best["sign"], "thickness": pc["s"][2],
           "s": pc["s"], "pca": pc, "locus": best["locus"],
           "radius": radius, "samples": samples}
    thick = pc["s"][2]
    if thick <= 0.005 * radius:
        if pc["s"][0] <= 0.01 and pc["s"][1] <= 0.01:
            out["kind"] = "sphere"
            out["sphere"] = {"center": pc["center"], "r": radius}
            return out
        ci = fit_circle3d(best["locus"])
        if ci["ok"] and ci["rms"] <= 1e-9:
            out["kind"] = "canal_circle"
            out["circle"] = ci
            return out
        out["kind"] = "canal_approx"
        out["circle"] = ci if ci["ok"] else None
        out["reason"] = "circle residual %.3e" % (ci.get("rms", -1.0)
                                                  if ci["ok"] else -1.0)
        return out
    if thick <= 0.05 * radius:
        ci = fit_circle3d(best["locus"])
        out["kind"] = "canal_approx"
        out["circle"] = ci if ci["ok"] else None
        return out
    out["kind"] = "unknown"
    out["reason"] = "thickness %.4f > 0.05R" % thick
    return out


def rim_from_face(part, face_tag, radius, grid=7):
    """B 类角面 → 可直接喂给 roll_rim 的圆边参数（只用于测量/报告）。"""
    info = classify_corner(part, face_tag, radius, grid)
    if not info.get("ok") or info["kind"] != "canal_circle":
        return info
    ci = info["circle"]
    info["rim"] = {"center": ci["center"], "axis": ci["axis"],
                   "r": ci["r"], "span_deg": ci["span_deg"],
                   "a0_deg": math.degrees(ci["a0"]),
                   "a1_deg": math.degrees(ci["a1"])}
    return info


# ------------------------------------------------------------------ 解析环面
def torus_ring(wp, center, axis, major, radius, eps=0.02):
    """方截面环（4 条母线旋转）+ 4 条圆边 FaceBlend → 解析环面实体。

    截面半高 = radius + eps，中心在 major；四条圆角后得到四个 type19 面带：
    外/内 × 上/下，主半径 major±eps、rad_data = radius。eps 必须 >0：正好
    等于半高时有一条边的圆角会因零宽面被拒。
    """
    ax = _unit(axis)
    if ax is None:
        return None
    ref = (1.0, 0.0, 0.0) if abs(ax[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _unit(_cross(ref, ax))
    if u is None:
        return None
    half = radius + eps
    c = [float(v) for v in center]
    pts = []
    for (dr, da) in ((-half, -half), (half, -half), (half, half), (-half, half)):
        pts.append(NXOpen.Point3d(
            c[0] + (major + dr) * u[0] + da * ax[0],
            c[1] + (major + dr) * u[1] + da * ax[1],
            c[2] + (major + dr) * u[2] + da * ax[2]))
    before = set(b.Tag for b in wp.Bodies)
    curves = [wp.Curves.CreateLine(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    ring = _revolve_uf(wp, curves, center, axis, 0.0, 2.0 * math.pi)
    if ring is None or ring.IsSheetBody:
        return None
    from nxlib.modeling import face_blend_edge
    for e in ring.GetEdges():
        if e.SolidEdgeType == NXOpen.Edge.EdgeType.Circular:
            try:
                face_blend_edge(wp, e, radius)
            except Exception:
                for b in list(wp.Bodies):
                    if b.Tag not in before:
                        try:
                            b.Feature.Delete()
                        except Exception:
                            pass
                return None
    return ring


def torus_ring_outer(wp, center, axis, major, radius, eps=0.02):
    """喇叭环面（主半径 = 滚球半径）的外侧环：截面从轴线起，只倒外角。

    方截面 [0, major+radius+eps] × ±（radius+eps）绕轴旋转；内侧不越轴，
    只 FaceBlend 外侧上下两条圆边。得到的两条 type19 面带在
    major+eps、轴向 ±eps，其中面向角区的一条可直接分割实体。用于
    `torus_ring` 会跨轴自交的喇叭情形（major ≈ radius）。
    """
    ax = _unit(axis)
    if ax is None:
        return None
    ref = (1.0, 0.0, 0.0) if abs(ax[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _unit(_cross(ref, ax))
    if u is None:
        return None
    half = radius + eps
    c = [float(v) for v in center]
    ro = major + half
    pts = []
    for (dr, da) in ((0.0, -half), (ro, -half), (ro, half), (0.0, half)):
        pts.append(NXOpen.Point3d(
            c[0] + dr * u[0] + da * ax[0],
            c[1] + dr * u[1] + da * ax[1],
            c[2] + dr * u[2] + da * ax[2]))
    before = set(b.Tag for b in wp.Bodies)
    curves = [wp.Curves.CreateLine(pts[i], pts[(i + 1) % 4])
              for i in range(4)]
    ring = _revolve_uf(wp, curves, center, axis, 0.0, 2.0 * math.pi)
    if ring is None or ring.IsSheetBody:
        return None
    from nxlib.modeling import face_blend_edge
    got = 0
    for e in ring.GetEdges():
        if e.SolidEdgeType != NXOpen.Edge.EdgeType.Circular:
            continue
        g = edge_geometry(e, 11)
        if not g.get("ok") or g["kind"] != "circle":
            continue
        if g["circle"]["r"] < 0.5 * ro:
            continue
        try:
            face_blend_edge(wp, e, radius)
        except Exception:
            for b in list(wp.Bodies):
                if b.Tag not in before:
                    try:
                        b.Feature.Delete()
                    except Exception:
                        pass
            return None
        got += 1
    if got:
        return ring
    for b in list(wp.Bodies):
        if b.Tag not in before:
            try:
                b.Feature.Delete()
            except Exception:
                pass
    return None


def _band_faces(part, body, radius, tol=0.05):
    u = _ufs()
    out = []
    for f in body.GetFaces():
        try:
            typ, pt, dr, box, rad, rdata, ndir = u.Modeling.AskFaceData(f.Tag)
        except Exception:
            continue
        if int(typ) != 19 or abs(float(rdata) - radius) > tol:
            continue
        out.append({"face": f, "major": float(rad),
                    "box": [float(x) for x in box]})
    return out


def split_by_face(wp, body, face):
    """SplitBodyBuilder(FaceOrPlane) 用一张面分割实体；返回 feature。"""
    sb = wp.Features.CreateSplitBodyBuilder(NXOpen.Features.SplitBody.Null)
    sb.TargetBody.SetArray([body])
    bt = sb.BooleanTool
    bt.ToolOption = \
        NXOpen.GeometricUtilities.BooleanToolBuilder.BooleanToolType.FaceOrPlane
    col = bt.FacePlaneTool.ToolFaces.FaceCollector
    col.ReplaceRules([wp.ScRuleFactory.CreateRuleFaceDumb([face])], False)
    sb.Tolerance = 0.01
    feat = sb.CommitFeature()
    sb.Destroy()
    return feat


def rim_roll_center(part, edge, radius, add=False):
    """锐边 + 滚球半径 → 滚球中心圆与截面量（Pappus 体积基准）。

    滚球中心由两面法向在边起点处解析求得（与 `modeling.section_profile` 同一套
    截面）；直纹支撑上截面恒定，中心绕边轴成一圆，主半径 = 中心到边轴的
    垂距，不是锐边半径。返回 center/axis/major/area/r_centroid。
    """
    geo = edge_geometry(edge, 11)
    if not geo.get("ok") or geo["kind"] != "circle":
        return None
    ci = geo["circle"]
    pts = geo.get("points") or []
    fs = edge_faces(edge)
    if len(pts) < 5 or len(fs) != 2:
        return None
    station = pts[0]
    ax = _unit(ci["axis"])
    if ax is None:
        return None
    # 弦方向在圆上偏离局部切向（1/10 圈约 17°），截面会跟着转，滚球中心
    # 离开径向平面；用拟合圆在该点的解析切向。
    rel0 = _sub(station, ci["center"])
    rel0 = _sub(rel0, _mul(ax, _dot(rel0, ax)))
    tangent = _unit(_cross(ax, rel0))
    if tangent is None:
        return None
    if _dot(tangent, _sub(pts[1], pts[0])) < 0.0:
        tangent = _mul(tangent, -1.0)
    nrm = []
    for f in fs:
        n, _ = face_normal_at(part, f, station)
        if n is None or abs(_dot(n, tangent)) > 0.5:
            return None
        nrm.append(n)
    sec = mdl.section_profile(nrm[0], nrm[1], tangent, radius, add)
    if not sec.get("ok"):
        return None
    c3 = _as_tuple(_to3(station, sec["e1"], sec["e2"],
                          (sec["ox"], sec["oy"])))
    rel = _sub(c3, ci["center"])
    h = _dot(rel, ax)
    rad = _sub(rel, _mul(ax, h))
    maj = _norm(rad)
    if maj < 1e-6:
        return None
    aa, a1 = sec["arc_a0"], sec["arc_a1"]
    poly = [sec["c_out"],
            (sec["ox"] + radius * math.cos(aa),
             sec["oy"] + radius * math.sin(aa))]
    for j in range(1, 16):
        a = aa + (a1 - aa) * j / 16.0
        poly.append((sec["ox"] + radius * math.cos(a),
                     sec["oy"] + radius * math.sin(a)))
    poly.append((sec["ox"] + radius * math.cos(a1),
                 sec["oy"] + radius * math.sin(a1)))
    ar = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        cr = x0 * y1 - x1 * y0
        ar += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    ar *= 0.5
    if abs(ar) < 1e-12:
        return None
    cen2 = (cx / (6.0 * ar), cy / (6.0 * ar))
    cc3 = _as_tuple(_to3(station, sec["e1"], sec["e2"], cen2))
    crel = _sub(cc3, ci["center"])
    crad = _sub(crel, _mul(ax, _dot(crel, ax)))
    corner = _unit(_sub(station, c3))
    return {"ok": True,
            "center": _add(ci["center"], _mul(ax, h)),
            "axis": ax, "major": maj, "area": abs(ar),
            "r_centroid": _norm(crad), "corner_dir": corner,
            "rad_dir": _mul(rad, 1.0 / maj), "station": station,
            "rolling_center": c3}


def roll_rim_analytic(wp, body, edge, radius, eps=0.02):
    """非喇叭环面圆边的 G7 可见路线：方截面环 → FaceBlend → 面带分割实体。

    环面必须建在**滚球中心圆**上（`rim_roll_center`），不是锐边圆上；建在
    锐边圆上的环带只与壁擦切，分割报“工具体完全在目标体外”。四个四分之一
    环带按“指向角区”排序逐个试分，用 Pappus 体积筛掉切错象限的结果；每次
    尝试独立 undo mark，失败原实体不动。只处理凸边（减料）；凹边返回失败。
    多实体件直接拒绝：后续按体积挑最大体并删除其余体会误删无关体。
    """
    others = [b for b in wp.Bodies
              if not b.IsSheetBody and b.Tag != body.Tag]
    if others:
        return {"ok": False,
                "reason": "multiple solid bodies: %d" % (len(others) + 1)}
    info = rim_roll_center(wp, edge, radius, False)
    if info is None:
        return {"ok": False, "reason": "roll center failed"}
    maj = info["major"]
    if maj - (radius + eps) <= 0.0:
        # 喇叭环面：整环会跨轴自交；角区朝外时只建外侧环（截面从轴线起）
        dr = _dot(info["corner_dir"], info["rad_dir"])
        if dr <= 0.1:
            return {"ok": False, "reason": "horn inward major=%.3f" % maj}
        ring = torus_ring_outer(wp, info["center"], info["axis"],
                                maj, radius, eps)
        if ring is None:
            return {"ok": False, "reason": "horn outer ring failed"}
    else:
        ring = torus_ring(wp, info["center"], info["axis"], maj, radius, eps)
        if ring is None:
            return {"ok": False, "reason": "torus ring failed"}
    bands = _band_faces(wp, ring, radius)
    if not bands:
        try:
            ring.Feature.Delete()
        except Exception:
            pass
        return {"ok": False, "reason": "no type19 band"}
    ax = info["axis"]
    cd = info["corner_dir"]
    cr = _dot(cd, info["rad_dir"])
    ca = _dot(cd, ax)
    hb = _dot(info["center"], ax)

    def score(b):
        c = [0.5 * (b["box"][i] + b["box"][i + 3]) for i in range(3)]
        zb = _dot(c, ax)
        sr = 1.0 if b["major"] > maj else -1.0
        sa = 1.0 if zb > hb else -1.0
        return -(sr * cr + sa * ca)

    order = sorted(bands, key=score)
    exp = info["area"] * 2.0 * math.pi * info["r_centroid"]
    session = NXOpen.Session.GetSession()
    ring_tag = ring.Tag
    v0 = mdl.volume(wp, body)
    for pick in order:
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                                   "rim_analytic_split")
        try:
            split_by_face(wp, body, pick["face"])
        except Exception:
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
            continue
        solids = [b for b in wp.Bodies
                  if not b.IsSheetBody and b.Tag != ring_tag]
        keep = max(solids, key=lambda b: mdl.volume(wp, b))
        removed = v0 - mdl.volume(wp, keep)
        if not (0.2 * exp < removed < 1.5 * exp):
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
            continue
        session.DeleteUndoMark(mark, None)
        for b in solids:
            if b.Tag != keep.Tag:
                try:
                    b.Feature.Delete()
                except Exception:
                    pass
        return {"ok": True, "body": keep, "face_major": pick["major"],
                "removed": removed, "expected": exp}
    try:
        ring.Feature.Delete()
    except Exception:
        pass
    return {"ok": False, "reason": "no band split accepted"}
