# -*- coding: utf-8 -*-
"""nxlib.measure —— 只读测量：面表、同轴分组、截面面积/IoU、原件与自建件比对。

两条数据链，都只读、都不保存：
  面表  UF_MODL_ask_face_data 给类型/轴/半径/半角/包盒，按同轴同半径聚成
        圆柱组、按同轴同半角聚成圆锥组；孔参数（直径/轴/长度/中心）由组
        的轴向区间给出。
  截面  DexManager STL 导出（弦高 0.01 mm）后用平面切三角网格，环按外法
        向定向：外环正面积、孔环负面积，净面积取代数和。同一函数既能量
        原件也能量自建件，所以自检闭环是"量原件 → 建 → 量自建件 → 比"。
  偏差  面积加权表面采样 + 精确点—三角面距离 + 均匀网格索引，两个方向
        分别给 RMS/P95；测站由面表平面族和孔/锥轴生成，逐站复算面积与
        IoU。`verify_parts` 把 G0–G6 汇总成一次调用。

约定：
  圆柱=16、圆锥=17、圆环=19、平面=22（Parasolid 面类型）。
  圆锥半角对外用度；UF 的 rad_data 是弧度。
  长度单位随部件（mm）。
"""
import bisect
import math
import os
import random
import struct
import tempfile

import NXOpen
import NXOpen.UF

CYLINDER = 16
CONE = 17
TORUS = 19
PLANE = 22

STL_CHORDAL_TOL = 0.01
_MESH_SEQ = [0]


def _ufs():
    return NXOpen.UF.UFSession.GetUFSession()


def part_length_scale(part):
    """部件长度单位到毫米的倍率；未知单位按 1.0 并返回 "unknown"。"""
    try:
        pu = part.PartUnits
        if pu == NXOpen.BasePart.Units.Inches:
            return "inch", 25.4
        if pu == NXOpen.BasePart.Units.Millimeters:
            return "mm", 1.0
    except Exception:
        pass
    return "unknown", 1.0


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else [0.0, 0.0, 0.0]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _canon(d):
    d = _unit(d)
    for c in d:
        if abs(c) > 1e-9:
            if c < 0.0:
                d = [-x for x in d]
            break
    return d


def _axis_key(d, digits=3):
    d = _canon(d)
    return (round(d[0], digits), round(d[1], digits), round(d[2], digits))


def _line_dist(p1, d, p2):
    v = _sub(p2, p1)
    return math.sqrt(max(0.0, _dot(v, v) - _dot(v, d) ** 2))


def _perp_dist(p1, p2, d):
    """两点差在垂直于 d 的平面上的投影长度（G2 孔心口径）。"""
    v = _sub(p2, p1)
    return math.sqrt(max(0.0, _dot(v, v) - _dot(v, d) ** 2))


def _project_extent(box, p0, d):
    lo, hi = 1e9, -1e9
    for sx in (box[0], box[3]):
        for sy in (box[1], box[4]):
            for sz in (box[2], box[5]):
                t = _dot(_sub([sx, sy, sz], p0), d)
                lo = min(lo, t)
                hi = max(hi, t)
    return lo, hi


def _kind_value(kind):
    if isinstance(kind, int):
        return kind
    name = str(kind).lower()
    if name.startswith("cyl"):
        return CYLINDER
    if name.startswith("cone"):
        return CONE
    if name.startswith("tor"):
        return TORUS
    if name.startswith("plane"):
        return PLANE
    raise ValueError("unknown face kind: %r" % (kind,))


def open_part(path):
    """只读打开部件并设为显示件；已打开则复用。调用方不得再 Save。"""
    path = os.path.abspath(path)
    s = NXOpen.Session.GetSession()
    for p in s.Parts:
        try:
            if os.path.normcase(os.path.abspath(p.FullPath)) == os.path.normcase(path):
                _ufs().Part.SetDisplayPart(p.Tag)
                return p
        except Exception:
            continue
    part, _ = s.Parts.Open(path)
    _ufs().Part.SetDisplayPart(part.Tag)
    return part


def part_volume(part):
    """全部实体的体积和（mm³）。"""
    uc = part.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter",
              "Kilogram", "MilliMeter", "Newton")]
    total = 0.0
    for b in part.Bodies:
        total += float(part.MeasureManager.NewMassProperties(
            units, [0.99], [b]).Volume)
    return total


def _do_update(tag):
    s = NXOpen.Session.GetSession()
    mark = s.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, tag)
    try:
        errs = s.UpdateManager.DoUpdate(mark)
    finally:
        try:
            s.DeleteUndoMark(mark, None)
        except Exception:
            pass
    return 0 if errs is None else int(errs)


def expression_survey(part, factor=1.1):
    """G8 可编辑性：逐条命名表达式 +factor、更新、量体积、还原。

    与 `references/modeling.md` §6 及冻结 edit_survey 同口径：自动表达式
    （p0/p1…）与 PI 不计；RHS 非数值的公式记录在 skipped，不参与存活率。
    每次改动都新建 undo mark 并 DoUpdate，还原后再更新一次并核对体积。
    只改内存中的部件，**不保存**；调用方应传入已建的输出件，且此时不要再
    保存该部件（否则参数试验的结果会进文件）。

    pass = 单实体 + 至少一个命名表达式 + 至少一条实测驱动几何 + 无死参数
    + 无更新异常/还原失败 + 无特征告警 + 存活率 1.0。
    """
    bodies = list(part.Bodies)
    v0 = part_volume(part)
    named = []
    for e in part.Expressions:
        try:
            lhs = e.Equation.split("=")[0].strip()
        except Exception:
            continue
        if lhs and lhs.upper() != "PI" and not lhs.lower().startswith("p"):
            named.append((lhs, e))
    live, dead, broken, skipped = [], [], [], []
    for i, (name, e) in enumerate(named):
        try:
            rhs = e.RightHandSide
            val = float(rhs)
        except Exception:
            skipped.append(name)
            continue
        try:
            e.RightHandSide = "%.6f" % (val * factor)
            errs = _do_update("survey_%d" % i)
            d = part_volume(part) - v0
            if errs != 0:
                broken.append({"name": name, "errors": errs})
            elif abs(d) < 1e-4:
                dead.append(name)
            else:
                live.append({"name": name, "delta_volume": d})
            e.RightHandSide = rhs
            errs2 = _do_update("restore_%d" % i)
            vr = part_volume(part)
            if errs2 != 0 or abs(vr - v0) > 1e-4 * max(abs(v0), 1.0):
                broken.append({"name": name + ":restore", "errors": errs2,
                               "volume": vr})
                break
        except Exception:
            broken.append({"name": name, "exception": True})
            break
    try:
        alerts = [{"tag": int(f.Tag), "name": f.Name,
                   "type": f.FeatureType}
                  for f in part.Features.GetAllPartFeaturesWithAlerts()]
    except Exception:
        alerts = [{"query_failed": True}]
    tested = len(live) + len(dead) + len(broken)
    ratio = (len(live) / float(tested)) if tested else 0.0
    return {
        "bodies": len(bodies),
        "volume": v0,
        "named": [n for n, _ in named],
        "live": live,
        "dead": dead,
        "broken": broken,
        "skipped": skipped,
        "alerts": alerts,
        "alive_ratio": ratio,
        "pass": (len(bodies) == 1 and bool(named) and bool(live) and
                 not dead and not broken and not alerts and ratio == 1.0),
    }


def face_table(part, with_edges=False):
    """全量面表。with_edges=True 时每面带边（类型/长度/相邻面 tag），
    供同轴组的端面定位使用。"""
    u = _ufs()
    rows = []
    for b in part.Bodies:
        for f in b.GetFaces():
            rec = {"tag": int(f.Tag)}
            try:
                typ, pt, dr, box, rad, rdata, ndir = u.Modeling.AskFaceData(f.Tag)
                rec.update({
                    "type": int(typ),
                    "point": [float(x) for x in pt],
                    "dir": [float(x) for x in dr],
                    "box": [float(x) for x in box],
                    "radius": float(rad),
                    "rad_data": float(rdata),
                    "norm_dir": int(ndir),
                })
            except Exception:
                rec.update({"type": -1, "point": [0.0, 0.0, 0.0],
                            "dir": [0.0, 0.0, 1.0], "box": [0.0] * 6,
                            "radius": 0.0, "rad_data": 0.0, "norm_dir": 0})
            if with_edges:
                edges = []
                try:
                    for e in f.GetEdges():
                        er = {"tag": int(e.Tag)}
                        try:
                            er["type"] = str(e.SolidEdgeType)
                        except Exception:
                            er["type"] = "?"
                        try:
                            er["length"] = float(e.GetLength())
                        except Exception:
                            er["length"] = 0.0
                        try:
                            er["faces"] = [int(x.Tag) for x in e.GetFaces()]
                        except Exception:
                            er["faces"] = []
                        edges.append(er)
                except Exception:
                    pass
                rec["edges"] = edges
            rows.append(rec)
    return rows


def group_coaxial(faces, kind=CYLINDER, axis_digits=3, radius_digits=3):
    """把面表聚成同轴组。

    圆柱按 (轴, 半径) 分桶，圆锥按 (轴, 半角) 分桶；桶内再按到轴线的距离
    聚簇，距离上限取 2r+2（同一孔的上下两段圆柱不会被拆开，不同孔不会被
    并在一起）。返回组的 axis/point/extent/length/center/radius/faces。
    """
    kind = _kind_value(kind)
    picked = [f for f in faces if f.get("type") == kind]
    buckets = {}
    for f in picked:
        if kind == CONE:
            key = (_axis_key(f["dir"], axis_digits),
                   round(f.get("rad_data", 0.0), 4))
        else:
            key = (_axis_key(f["dir"], axis_digits),
                   round(f.get("radius", 0.0), radius_digits))
        buckets.setdefault(key, []).append(f)

    groups = []
    for key, fs in buckets.items():
        d = _canon(fs[0]["dir"])
        tol = max(2.0 * max(abs(f.get("radius", 0.0)) for f in fs) + 2.0, 5.0)
        clusters = []
        for f in fs:
            for cl in clusters:
                if _line_dist(cl["p0"], d, f["point"]) <= tol:
                    cl["faces"].append(f)
                    break
            else:
                clusters.append({"p0": list(f["point"]), "faces": [f]})
        for cl in clusters:
            lo, hi = 1e9, -1e9
            for f in cl["faces"]:
                a, b = _project_extent(f["box"], cl["p0"], d)
                lo, hi = min(lo, a), max(hi, b)
            bx = [min(f["box"][k] for f in cl["faces"]) for k in range(3)] + \
                 [max(f["box"][k + 3] for f in cl["faces"]) for k in range(3)]
            groups.append({
                "kind": kind,
                "axis": d,
                "point": cl["p0"],
                "radius": abs(cl["faces"][0].get("radius", 0.0)),
                "half_angle_deg": math.degrees(cl["faces"][0].get("rad_data", 0.0)),
                "extent": [lo, hi],
                "length": hi - lo,
                "bbox": bx,
                "center": [0.5 * (bx[k] + bx[k + 3]) for k in range(3)],
                "concave": all(f.get("norm_dir") == -1 for f in cl["faces"]),
                "faces": [f["tag"] for f in cl["faces"]],
                "ends": _end_faces(cl["faces"], d, cl["p0"], faces),
            })
    return groups


def _end_faces(group_faces, d, p0, all_faces):
    """组内圆柱/圆锥经边邻接到的垂直平面，给出轴向坐标（孔端面）。"""
    if not group_faces or "edges" not in group_faces[0]:
        return []
    tags = set(f["tag"] for f in group_faces)
    by_tag = dict((f["tag"], f) for f in all_faces)
    ends = {}
    for f in group_faces:
        for e in f.get("edges", []):
            for nt in e.get("faces", []):
                if nt in tags:
                    continue
                nf = by_tag.get(nt)
                if nf is None or nf.get("type") != PLANE:
                    continue
                if abs(_dot(_unit(nf["dir"]), d)) < 0.99:
                    continue
                t = _dot(_sub(nf["point"], p0), d)
                ends[round(t, 4)] = (nt, round(t, 4))
    return [ends[k] for k in sorted(ends)]


def hole_params(group):
    """圆柱组的孔参数：直径/轴/中心/轴向长度/端面。中心取组包盒中心（G2 口径）。"""
    return {
        "diameter": 2.0 * group["radius"],
        "radius": group["radius"],
        "axis": group["axis"],
        "center": list(group["center"]),
        "length": group["length"],
        "extent": list(group["extent"]),
        "ends": list(group.get("ends", [])),
        "faces": list(group["faces"]),
    }


def cone_params(group):
    """圆锥组的参数：UF 参考半径、半角（度）、轴、轴向区间。"""
    return {
        "radius": group["radius"],
        "half_angle_deg": group["half_angle_deg"],
        "axis": group["axis"],
        "point": list(group["point"]),
        "center": list(group["center"]),
        "length": group["length"],
        "extent": list(group["extent"]),
        "faces": list(group["faces"]),
    }


def exact_section(part, origin, normal, tolerance=0.01, samples=65,
                  body=None):
    """B-rep 截面曲线（UF SectionFromPlanes），按端点串成闭环。

    返回每个原始段的三维采样点与按端点聚类的闭环；闭合环带绝对面积。
    每个环带 `gap`（首尾距离），`open_gaps` 汇总未闭环的缺口；缺口大于
    容差是真实开口/槽，不是拟合误差，不要靠放宽容差把它闭合成实体。
    只用于取重建轮廓：STL 切面只用于最终偏差核对。截面特征与临时基准面
    在取点后按 undo mark 回滚，不留在内存部件里；`body` 缺省取第一个实体。
    """
    ufs = _ufs()
    bodies = [body] if body is not None else list(part.Bodies)
    if not bodies:
        raise ValueError("part has no solid body")
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                               "exact_section")
    plane = part.Planes.CreatePlane(
        NXOpen.Point3d(*[float(v) for v in origin]),
        NXOpen.Vector3d(*[float(v) for v in _unit(normal)]),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    fd = NXOpen.UF.ModlCurveFitData_Struct()
    fd.CurveFitMethod = 0
    fd.MaximumDegree = 3
    fd.MaximumSegments = 1
    gd = NXOpen.UF.Curve.SectionGeneralData()
    gd.Objects = [int(b.Tag) for b in bodies]
    gd.NumObjects = len(bodies)
    gd.Associate = 1
    gd.Grouping = 0
    gd.JoinType = 0
    gd.Tolerance = float(tolerance)
    gd.CurveFitData = fd
    pd = NXOpen.UF.Curve.SectionPlanesData()
    pd.Planes = [plane.Tag]
    pd.NumPlanes = 1
    feat = ufs.Curve.SectionFromPlanes(gd, pd)
    _n, tags = ufs.Curve.AskFeatureCurves(feat)
    tol = float(tolerance)
    curves = []
    for tag in tags:
        pts = []
        for i in range(int(samples)):
            p = ufs.ModlGeneral.AskCurveProps(tag, i / float(samples - 1))[0]
            pts.append([float(p[0]), float(p[1]), float(p[2])])
        closed = math.sqrt(_dot(_sub(pts[0], pts[-1]),
                                _sub(pts[0], pts[-1]))) <= 2.0 * tol
        curves.append({"tag": int(tag), "pts": pts, "closed": closed})

    def key(p):
        return (int(round(p[0] / tol)), int(round(p[1] / tol)),
                int(round(p[2] / tol)))

    def gap(pts):
        d = _sub(pts[0], pts[-1])
        return math.sqrt(_dot(d, d))

    loops = []
    open_edges = []
    for i, c in enumerate(curves):
        if c["closed"]:
            loops.append({"pts": c["pts"], "closed": True, "gap": 0.0})
        else:
            open_edges.append(i)
    adj = {}
    for i in open_edges:
        c = curves[i]
        adj.setdefault(key(c["pts"][0]), []).append(i)
        adj.setdefault(key(c["pts"][-1]), []).append(i)
    used = set()

    def take_at(k, exclude):
        for i in adj.get(k, ()):
            if i not in used and i != exclude:
                return i
        return None

    for start in open_edges:
        if start in used:
            continue
        used.add(start)
        pts = list(curves[start]["pts"])
        k = key(pts[-1])
        while True:
            i = take_at(k, -1)
            if i is None:
                break
            used.add(i)
            ep = curves[i]["pts"]
            if key(ep[0]) == k:
                pts.extend(ep[1:])
            else:
                pts.extend(list(reversed(ep))[1:])
            k = key(pts[-1])
            if k == key(pts[0]):
                break
        if k != key(pts[0]):
            k = key(pts[0])
            while True:
                i = take_at(k, -1)
                if i is None:
                    break
                used.add(i)
                ep = curves[i]["pts"]
                if key(ep[-1]) == k:
                    pts = list(ep[:-1]) + pts
                else:
                    pts = list(reversed(ep))[:-1] + pts
                k = key(pts[0])
                if k == key(pts[-1]):
                    break
        loops.append({"pts": pts,
                      "closed": key(pts[0]) == key(pts[-1]),
                      "gap": gap(pts)})
    e1, e2 = _basis(normal)
    for lp in loops:
        pts = lp["pts"]
        uv = [(_dot(_sub(p, origin), e1), _dot(_sub(p, origin), e2))
              for p in pts]
        ar = 0.0
        for i in range(len(uv)):
            x0, y0 = uv[i]
            x1, y1 = uv[(i + 1) % len(uv)]
            ar += x0 * y1 - x1 * y0
        lp["area"] = 0.5 * ar
        lp["abs_area"] = abs(lp["area"])
    open_gaps = [l["gap"] for l in loops if not l["closed"]]
    try:
        session.UndoToMark(mark, None)
    finally:
        try:
            session.DeleteUndoMark(mark, None)
        except Exception:
            pass
    return {"origin": [float(v) for v in origin],
            "normal": _unit(normal),
            "curves": curves,
            "loops": loops,
            "open": len(open_gaps),
            "open_gaps": open_gaps}


def measure_part(path, with_edges=True):
    """只读量一个部件：体积/体数/特征数/面表/圆柱组/圆锥组。

    长度量随部件单位；`length_scale` 是换算到毫米的倍率，体积已按 mm³ 返回。
    """
    part = open_part(path)
    units, scale = part_length_scale(part)
    faces = face_table(part, with_edges=with_edges)
    return {
        "path": part.FullPath,
        "units": units,
        "length_scale": scale,
        "volume": part_volume(part),
        "bodies": len(list(part.Bodies)),
        "features": len(list(part.Features)),
        "faces": faces,
        "cylinders": group_coaxial(faces, CYLINDER),
        "cones": group_coaxial(faces, CONE),
    }


def _fit_circle(pts):
    """二维点集的圆心/半径/径向离散度（质心法，整圆才可靠）。"""
    n = len(pts)
    cu = sum(p[0] for p in pts) / float(n)
    cv = sum(p[1] for p in pts) / float(n)
    rs = [math.hypot(p[0] - cu, p[1] - cv) for p in pts]
    return cu, cv, sum(rs) / float(n), max(rs) - min(rs)


def _point_in_poly(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _inner_ring(part, group):
    """组轴向 1/3、2/3 截面上，组半径处是否有被外环包住的内环。"""
    d = group["axis"]
    p0 = group["point"]
    lo, hi = group["extent"]
    r0 = group["radius"]
    tan = math.tan(math.radians(group.get("half_angle_deg", 0.0)))
    ra, rb = r0 + tan * lo, r0 + tan * hi
    rmin, rmax = min(ra, rb), max(ra, rb)
    tol_r = max(0.01 * max(abs(rmin), abs(rmax), 1.0), 0.05)
    for frac in (1.0 / 3.0, 2.0 / 3.0):
        t = lo + (hi - lo) * frac
        origin = [p0[k] + d[k] * t for k in range(3)]
        try:
            sec = exact_section(part, origin, d)
        except Exception:
            continue
        e1, e2 = _basis(d)
        polys = []
        for lp in sec["loops"]:
            if not lp.get("closed"):
                continue
            pts = []
            for p in lp["pts"]:
                w = _sub(p, origin)
                pts.append((_dot(w, e1), _dot(w, e2)))
            if len(pts) >= 8:
                polys.append(pts)
        if len(polys) < 2:
            continue
        for i, pts in enumerate(polys):
            cu, cv, rfit, spread = _fit_circle(pts)
            if spread > max(0.05 * rfit, 0.5):
                continue
            if not (rmin - tol_r <= rfit <= rmax + tol_r):
                continue
            center3 = [origin[k] + cu * e1[k] + cv * e2[k]
                       for k in range(3)]
            w = _sub(center3, group["center"])
            h = _sub(w, [d[k] * _dot(w, d) for k in range(3)])
            if math.sqrt(_dot(h, h)) > max(0.05 * max(rfit, 1.0), 0.5):
                continue
            if any(j != i and _point_in_poly(pts[0], other)
                   for j, other in enumerate(polys)):
                return True
    return False


def functional_hole_groups(measure, part):
    """圆柱/锥组中的功能孔：凹面，且轴向截面在组半径处出现内环。

    内环是被外轮廓包住的闭合环——孔壁/沉孔在截面里是独立整圆；内圆角、
    凸台、外轮廓转角在截面里只是外轮廓的一段弧，不产生内环。原件没有
    功能孔时 G2 记 N/A，不要求为了过门强行建这些结构。
    """
    return [g for g in measure["cylinders"] + measure["cones"]
            if g.get("concave") and _inner_ring(part, g)]


def _match_groups(ga, gb, kind, radius_tol, center_tol, axis_tol_deg,
                  length_tol, half_angle_tol):
    used = set()
    pairs = []
    unmatched_a = []
    for i, o in enumerate(ga):
        best = None
        for j, q in enumerate(gb):
            if j in used:
                continue
            dr = abs(o["radius"] - q["radius"])
            if dr > 2.0 * radius_tol:
                continue
            ang = math.degrees(math.acos(
                min(1.0, abs(_dot(o["axis"], q["axis"])))))
            if ang > axis_tol_deg:
                continue
            cd = _perp_dist(o["center"], q["center"], o["axis"])
            if cd > center_tol:
                continue
            score = cd + dr + 0.1 * ang
            if best is None or score < best[0]:
                best = (score, j)
        if best is None:
            unmatched_a.append(i)
        else:
            used.add(best[1])
            pairs.append((i, best[1]))
    unmatched_b = [j for j in range(len(gb)) if j not in used]
    out = []
    for i, j in pairs:
        o, q = ga[i], gb[j]
        dr = abs(q["radius"] - o["radius"])
        ang = math.degrees(math.acos(min(1.0, abs(_dot(o["axis"], q["axis"])))))
        cd = _perp_dist(o["center"], q["center"], o["axis"])
        dha = abs(q["half_angle_deg"] - o["half_angle_deg"])
        ok = dr <= radius_tol and ang <= axis_tol_deg and cd <= center_tol
        if kind == CONE:
            ok = ok and dha <= half_angle_tol
        else:
            ok = ok and abs(q["length"] - o["length"]) <= length_tol
        out.append({
            "a": i, "b": j,
            "delta_radius": q["radius"] - o["radius"],
            "delta_length": q["length"] - o["length"],
            "delta_center": cd,
            "delta_axis_deg": ang,
            "delta_half_angle_deg": dha,
            "pass": ok,
            "a_group": o,
            "b_group": q,
        })
    return {
        "pairs": out,
        "unmatched_a": unmatched_a,
        "unmatched_b": unmatched_b,
        "pass": (not unmatched_a and not unmatched_b and
                 all(p["pass"] for p in out)),
    }


def _scale_group(group, scale):
    """组内长度量换到毫米；轴、半角与面 tag 不变。"""
    if scale == 1.0:
        return dict(group)
    out = dict(group)
    for key in ("radius", "length"):
        out[key] = group[key] * scale
    for key in ("point", "center", "bbox", "extent"):
        out[key] = [v * scale for v in group[key]]
    out["faces"] = list(group["faces"])
    out["ends"] = [(tag, t * scale) for tag, t in group.get("ends", [])]
    return out


def compare_parts(path_a, path_b, radius_tol=0.025, center_tol=0.05,
                  axis_tol_deg=0.1, length_tol=0.1, half_angle_tol=0.1,
                  ref_a=None, ref_b=None):
    """原件/自建件的 G2 口径比对（长度容差按毫米，组先换算单位）。

    匹配条件：半径差 ≤2×radius_tol、轴角 ≤axis_tol_deg、孔心（垂直于轴的
    平面内）≤center_tol。逐项判定：圆柱看半径/孔心/轴/长度，圆锥再加半角。
    `pass` 要求原件功能组没有未匹配项且每个 pair 都过阈值；`unmatched_a`
    是“原件有、自建件没有”的结构，必须逐项建或写入简化清单；`strict_pass`
    才要求双向都无未匹配项，`unmatched_b`（多出的圆角/凸台）只作复核。

    ref_a/ref_b 传入上一轮 measure_part 的组列表作为比对清单（按 faces
    tag 识别）。原件侧用 `functional_hole_groups`（截面内环筛出的功能孔）
    或孔表筛出比对清单再传 ref_a；圆角/凸台/外轮廓转角不计入。

    `applicable=False` 表示原件没有功能孔，G2 记 N/A；此时 `pass`
    仍为 True（空分母不阻塞整件），报告按 `verdict` 写 N/A 而不是通过。
    """
    a = measure_part(path_a)
    b = measure_part(path_b)

    def subset(groups, ref):
        if ref is None:
            return groups
        keys = set(tuple(g["faces"]) for g in ref)
        return [g for g in groups if tuple(g["faces"]) in keys]

    a_cyl = [_scale_group(g, a["length_scale"])
             for g in subset(a["cylinders"], ref_a)]
    a_con = [_scale_group(g, a["length_scale"])
             for g in subset(a["cones"], ref_a)]
    b_cyl = [_scale_group(g, b["length_scale"])
             for g in subset(b["cylinders"], ref_b)]
    b_con = [_scale_group(g, b["length_scale"])
             for g in subset(b["cones"], ref_b)]
    cyl = _match_groups(a_cyl, b_cyl, CYLINDER, radius_tol, center_tol,
                        axis_tol_deg, length_tol, half_angle_tol)
    cones = _match_groups(a_con, b_con, CONE, radius_tol, center_tol,
                          axis_tol_deg, length_tol, half_angle_tol)
    applicable = bool(a_cyl or a_con)
    groups_pass = (not cyl["unmatched_a"] and not cones["unmatched_a"] and
                   all(p["pass"] for p in cyl["pairs"] + cones["pairs"]))
    return {
        "a": {"path": a["path"], "units": a["units"],
              "length_scale": a["length_scale"],
              "volume": a["volume"],
              "bodies": a["bodies"], "features": a["features"]},
        "b": {"path": b["path"], "units": b["units"],
              "length_scale": b["length_scale"],
              "volume": b["volume"],
              "bodies": b["bodies"], "features": b["features"]},
        "delta_volume": b["volume"] - a["volume"],
        "delta_volume_ratio": ((b["volume"] - a["volume"]) / a["volume"]
                               if a["volume"] else 0.0),
        "cylinders": cyl,
        "cones": cones,
        "applicable": applicable,
        "verdict": ("N/A" if not applicable else
                    ("PASS" if groups_pass else "FAIL")),
        "pass": groups_pass,
        "strict_pass": cyl["pass"] and cones["pass"],
    }


def export_mesh(part, stl_path=None, chordal_tol=STL_CHORDAL_TOL):
    """把部件全部实体导出为二进制 STL；返回路径。只写 STL，不存部件。"""
    bodies = list(part.Bodies)
    if not bodies:
        raise ValueError("part has no solid body to export")
    if stl_path is None:
        _MESH_SEQ[0] += 1
        stl_path = os.path.join(
            tempfile.gettempdir(),
            "nxlib_measure_%d_%d.stl" % (os.getpid(), _MESH_SEQ[0]))
    stl_path = os.path.abspath(stl_path)
    if os.path.exists(stl_path):
        os.remove(stl_path)
    s = NXOpen.Session.GetSession()
    sc = s.DexManager.CreateStlCreator()
    sc.OutputFile = stl_path
    sc.ChordalTol = chordal_tol
    sc.ExportSelectionBlock.SetArray(bodies)
    sc.Commit()
    sc.Destroy()
    if not (os.path.exists(stl_path) and os.path.getsize(stl_path) > 0):
        raise RuntimeError("STL export produced no file: %s" % stl_path)
    return stl_path


def read_stl(path):
    """读二进制/ASCII STL，返回 [(法向, v0, v1, v2)]；法向缺失时由顶点补。"""
    with open(path, "rb") as fh:
        data = fh.read()
    tris = []
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if count > 0 and 84 + 50 * count <= len(data):
            off = 84
            for _ in range(count):
                vals = struct.unpack("<12f", data[off:off + 48])
                tris.append((list(vals[0:3]), list(vals[3:6]),
                             list(vals[6:9]), list(vals[9:12])))
                off += 50
            return _fix_normals(tris)
    text = data.decode("utf-8", "replace").splitlines()
    nrm, verts = None, []
    for line in text:
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower() == "facet" and len(parts) >= 5:
            nrm = [float(parts[2]), float(parts[3]), float(parts[4])]
        elif parts[0].lower() == "vertex" and len(parts) >= 4:
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            if len(verts) == 3:
                tris.append((nrm or [0.0, 0.0, 0.0], verts[0], verts[1], verts[2]))
                verts = []
    return _fix_normals(tris)


def _fix_normals(tris):
    out = []
    for nrm, v0, v1, v2 in tris:
        if _dot(nrm, nrm) < 1e-12:
            nrm = _cross(_sub(v1, v0), _sub(v2, v0))
        out.append((_unit(nrm), v0, v1, v2))
    return out


def mesh_bbox(mesh):
    """三角网格的轴对齐包盒 [xmin,ymin,zmin,xmax,ymax,zmax]（G4 口径）。"""
    if not mesh:
        raise ValueError("empty mesh")
    lo = [1e300, 1e300, 1e300]
    hi = [-1e300, -1e300, -1e300]
    for _, v0, v1, v2 in mesh:
        for v in (v0, v1, v2):
            for i in range(3):
                lo[i] = min(lo[i], v[i])
                hi[i] = max(hi[i], v[i])
    return [lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]]


def _basis(normal):
    n = _unit(normal)
    if abs(n[2]) > 0.9:
        e1 = [1.0, 0.0, 0.0]
        e2 = [0.0, 1.0, 0.0]
        if n[2] < 0.0:
            e2 = [0.0, -1.0, 0.0]
    else:
        e1 = _unit([-n[1], n[0], 0.0])
        e2 = _cross(n, e1)
    return e1, e2


def section_outline(mesh, origin, normal, weld=1e-4):
    """平面切网格，返回定向闭环。

    每条交线段按三角面外法向定向：dot(cross(d, n), tri_n) > 0，于是外环
    逆时针（正面积）、孔环顺时针（负面积）。返回
    {"loops":[{"pts":[(u,v)],"area":signed}], "area":净面积, "open":未闭合数}。
    """
    n = _unit(normal)
    e1, e2 = _basis(n)
    segments = []
    for nrm, v0, v1, v2 in mesh:
        vs = (v0, v1, v2)
        ds = [_dot(_sub(v, origin), n) for v in vs]
        pts = []
        for k in range(3):
            a, b = vs[k], vs[(k + 1) % 3]
            da, db = ds[k], ds[(k + 1) % 3]
            if (da > 0.0) != (db > 0.0):
                t = da / (da - db)
                pts.append([a[i] + t * (b[i] - a[i]) for i in range(3)])
        if len(pts) != 2:
            continue
        p, q = pts
        d = _sub(q, p)
        if _dot(d, d) < 1e-16:
            continue
        if _dot(_cross(d, n), nrm) < 0.0:
            p, q = q, p
        segments.append((p, q))

    def key(p):
        return (int(round(p[0] / weld)), int(round(p[1] / weld)),
                int(round(p[2] / weld)))

    adj = {}
    for si, (p, q) in enumerate(segments):
        adj.setdefault(key(p), []).append(si)
        adj.setdefault(key(q), []).append(si)

    used = set()
    loops = []
    open_count = 0
    for si in range(len(segments)):
        if si in used:
            continue
        used.add(si)
        chain = [segments[si][0], segments[si][1]]
        while True:
            k = key(chain[-1])
            nxt = None
            for sj in adj.get(k, []):
                if sj not in used:
                    nxt = sj
                    break
            if nxt is None:
                break
            used.add(nxt)
            a, b = segments[nxt]
            chain.append(b if key(a) == k else a)
            if key(chain[-1]) == key(chain[0]):
                break
        while True:
            k = key(chain[0])
            nxt = None
            for sj in adj.get(k, []):
                if sj not in used:
                    nxt = sj
                    break
            if nxt is None:
                break
            used.add(nxt)
            a, b = segments[nxt]
            chain.insert(0, a if key(b) == k else b)
            if key(chain[0]) == key(chain[-1]):
                break
        if key(chain[0]) != key(chain[-1]):
            open_count += 1
        pts = []
        for p in chain:
            uv = (_dot(_sub(p, origin), e1), _dot(_sub(p, origin), e2))
            if not pts or abs(uv[0] - pts[-1][0]) > 1e-9 or \
                    abs(uv[1] - pts[-1][1]) > 1e-9:
                pts.append(uv)
        area = 0.0
        for i in range(len(pts)):
            u0, v0 = pts[i]
            u1, v1 = pts[(i + 1) % len(pts)]
            area += u0 * v1 - u1 * v0
        loops.append({"pts": pts, "area": 0.5 * area})
    return {"loops": loops,
            "area": sum(loop["area"] for loop in loops),
            "open": open_count}


def section_area(mesh, origin, normal, weld=1e-4):
    """截面净面积（mm²）：外环正、孔环负。"""
    return section_outline(mesh, origin, normal, weld)["area"]


def _row_spans(loops, y):
    xs = []
    for loop in loops:
        pts = loop["pts"]
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    spans = []
    for i in range(0, len(xs) - 1, 2):
        if xs[i + 1] > xs[i]:
            spans.append((xs[i], xs[i + 1]))
    return spans


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _span_len(spans):
    return sum(b - a for a, b in spans)


def _span_inter(sa, sb):
    i = j = 0
    total = 0.0
    while i < len(sa) and j < len(sb):
        lo = max(sa[i][0], sb[j][0])
        hi = min(sa[i][1], sb[j][1])
        if hi > lo:
            total += hi - lo
        if sa[i][1] < sb[j][1]:
            i += 1
        else:
            j += 1
    return total


def section_iou(mesh_a, mesh_b, origin, normal, step=None, weld=1e-4):
    """两网格同一平面的截面 IoU（扫描线，行内精确）。"""
    oa = section_outline(mesh_a, origin, normal, weld)
    ob = section_outline(mesh_b, origin, normal, weld)
    us, vs = [], []
    for out in (oa, ob):
        for loop in out["loops"]:
            for u, v in loop["pts"]:
                us.append(u)
                vs.append(v)
    if not us:
        return {"iou": 1.0 if not ob["loops"] else 0.0,
                "area_a": oa["area"], "area_b": ob["area"],
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0}
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    diag = math.sqrt((umax - umin) ** 2 + (vmax - vmin) ** 2)
    if step is None:
        step = max(diag / 400.0, 0.05)
    nrows = max(1, int(math.ceil((vmax - vmin) / step)))
    inter = union = 0.0
    for iy in range(nrows):
        y = vmin + (iy + 0.5) * step
        sa = _merge(_row_spans(oa["loops"], y))
        sb = _merge(_row_spans(ob["loops"], y))
        ia = _span_inter(sa, sb)
        inter += ia
        union += _span_len(sa) + _span_len(sb) - ia
    area_inter = inter * step
    area_union = union * step
    return {
        "iou": (area_inter / area_union) if area_union > 0.0 else 1.0,
        "area_a": oa["area"],
        "area_b": ob["area"],
        "area_inter": area_inter,
        "area_union": area_union,
        "step": step,
    }


_VIEWS = {"top": (0, 1), "front": (0, 2), "side": (1, 2)}


def _project(mesh, iu, iv, nrm=None):
    out = []
    for _, v0, v1, v2 in mesh:
        if nrm is None:
            out.append(((v0[iu], v0[iv]), (v1[iu], v1[iv]),
                        (v2[iu], v2[iv])))
        else:
            out.append(((_dot(v0, iu), _dot(v0, iv)),
                        (_dot(v1, iu), _dot(v1, iv)),
                        (_dot(v2, iu), _dot(v2, iv))))
    return out


def _tri_span(tri, y):
    xs = []
    for k in range(3):
        a = tri[k]
        b = tri[(k + 1) % 3]
        if (a[1] > y) != (b[1] > y):
            xs.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
    if len(xs) < 2:
        return None
    return (min(xs), max(xs))


def view_iou(mesh_a, mesh_b, view="top", step=None):
    """两网格沿 view 方向的轮廓 IoU（三角面投影并集，扫描线）。

    view 取 "top"（u=x,v=y）、"front"（u=x,v=z）、"side"（u=y,v=z），
    或一个法向三元组（按该方向投影）。面积单位随部件。
    """
    if isinstance(view, str):
        iu, iv = _VIEWS[view.lower()]
        nrm = None
    else:
        e1, e2 = _basis(view)
        iu, iv = e1, e2
        nrm = _unit(view)
    pa = _project(mesh_a, iu, iv, nrm)
    pb = _project(mesh_b, iu, iv, nrm)
    us, vs = [], []
    for tri in pa + pb:
        for u, v in tri:
            us.append(u)
            vs.append(v)
    if not us:
        return {"iou": 1.0, "area_a": 0.0, "area_b": 0.0,
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0}
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    diag = math.sqrt((umax - umin) ** 2 + (vmax - vmin) ** 2)
    if step is None:
        step = max(diag / 400.0, 0.05)
    nrows = max(1, int(math.ceil((vmax - vmin) / step)))
    inter = union = 0.0
    area_a = area_b = 0.0
    for iy in range(nrows):
        y = vmin + (iy + 0.5) * step
        sa = _merge([s for s in (_tri_span(t, y) for t in pa) if s])
        sb = _merge([s for s in (_tri_span(t, y) for t in pb) if s])
        ia = _span_inter(sa, sb)
        inter += ia
        area_a += _span_len(sa)
        area_b += _span_len(sb)
        union += _span_len(sa) + _span_len(sb) - ia
    area_inter = inter * step
    area_union = union * step
    return {
        "iou": (area_inter / area_union) if area_union > 0.0 else 1.0,
        "area_a": area_a * step,
        "area_b": area_b * step,
        "area_inter": area_inter,
        "area_union": area_union,
        "step": step,
    }


def scale_mesh(mesh, factor):
    """把网格顶点乘一个长度倍率（单位换算用）；法向只重归一化。"""
    if factor == 1.0:
        return list(mesh)
    out = []
    for nrm, v0, v1, v2 in mesh:
        out.append((list(nrm),
                    [v0[i] * factor for i in range(3)],
                    [v1[i] * factor for i in range(3)],
                    [v2[i] * factor for i in range(3)]))
    return out


def sample_surface(mesh, count=4000, seed=0):
    """按面积加权在三角面上取点；同一 seed 与 count 输出逐点相同。"""
    if not mesh:
        return []
    areas = []
    total = 0.0
    for _, v0, v1, v2 in mesh:
        cr = _cross(_sub(v1, v0), _sub(v2, v0))
        ar = 0.5 * math.sqrt(_dot(cr, cr))
        total += ar
        areas.append(total)
    if total <= 1e-15:
        return []
    rnd = random.Random(seed)
    pts = []
    n = int(count)
    for _ in range(n):
        idx = bisect.bisect_left(areas, rnd.random() * total)
        if idx >= len(mesh):
            idx = len(mesh) - 1
        _, v0, v1, v2 = mesh[idx]
        u = rnd.random()
        v = rnd.random()
        if u + v > 1.0:
            u = 1.0 - u
            v = 1.0 - v
        d1 = _sub(v1, v0)
        d2 = _sub(v2, v0)
        pts.append([v0[i] + u * d1[i] + v * d2[i] for i in range(3)])
    return pts


def point_triangle_distance(p, v0, v1, v2):
    """点到三角面的精确最近距离（Ericson 区域判定）。"""
    ab = _sub(v1, v0)
    ac = _sub(v2, v0)
    ap = _sub(p, v0)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return math.sqrt(_dot(ap, ap))
    bp = _sub(p, v1)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return math.sqrt(_dot(bp, bp))
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        den = d1 - d3
        t = d1 / den if abs(den) > 1e-30 else 0.0
        q = [v0[i] + t * ab[i] for i in range(3)]
        return math.sqrt(_dot(_sub(p, q), _sub(p, q)))
    cp = _sub(p, v2)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return math.sqrt(_dot(cp, cp))
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        den = d2 - d6
        t = d2 / den if abs(den) > 1e-30 else 0.0
        q = [v0[i] + t * ac[i] for i in range(3)]
        return math.sqrt(_dot(_sub(p, q), _sub(p, q)))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        den = (d4 - d3) + (d5 - d6)
        t = (d4 - d3) / den if abs(den) > 1e-30 else 0.0
        q = [v1[i] + t * (v2[i] - v1[i]) for i in range(3)]
        return math.sqrt(_dot(_sub(p, q), _sub(p, q)))
    den = va + vb + vc
    if abs(den) < 1e-30:
        return min(_point_segment_distance(p, v0, v1),
                   _point_segment_distance(p, v1, v2),
                   _point_segment_distance(p, v2, v0))
    v = vb / den
    w = vc / den
    q = [v0[i] + ab[i] * v + ac[i] * w for i in range(3)]
    return math.sqrt(_dot(_sub(p, q), _sub(p, q)))


def _point_segment_distance(p, a, b):
    e = _sub(b, a)
    ee = _dot(e, e)
    if ee < 1e-30:
        return math.sqrt(_dot(_sub(p, a), _sub(p, a)))
    t = max(0.0, min(1.0, _dot(_sub(p, a), e) / ee))
    q = [a[i] + t * e[i] for i in range(3)]
    return math.sqrt(_dot(_sub(p, q), _sub(p, q)))


def _tri_bounds(tri):
    _, v0, v1, v2 = tri
    lo = [min(v0[i], v1[i], v2[i]) for i in range(3)]
    hi = [max(v0[i], v1[i], v2[i]) for i in range(3)]
    return lo, hi


def _mesh_grid(mesh, axis_cells=32):
    """按三角面包盒把索引装进均匀网格；返回网格查询所需的全部数据。"""
    if not mesh:
        return None
    boxes = [_tri_bounds(t) for t in mesh]
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    diag = math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))
    cell = max(diag / float(axis_cells), 1e-6)
    dims = [max(1, int(math.ceil((hi[i] - lo[i]) / cell))) for i in range(3)]
    grid = {}
    for idx, (blo, bhi) in enumerate(boxes):
        i0 = max(0, min(dims[0] - 1, int(math.floor((blo[0] - lo[0]) / cell))))
        i1 = max(0, min(dims[0] - 1, int(math.floor((bhi[0] - lo[0]) / cell))))
        j0 = max(0, min(dims[1] - 1, int(math.floor((blo[1] - lo[1]) / cell))))
        j1 = max(0, min(dims[1] - 1, int(math.floor((bhi[1] - lo[1]) / cell))))
        k0 = max(0, min(dims[2] - 1, int(math.floor((blo[2] - lo[2]) / cell))))
        k1 = max(0, min(dims[2] - 1, int(math.floor((bhi[2] - lo[2]) / cell))))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                for k in range(k0, k1 + 1):
                    grid.setdefault((i, j, k), []).append(idx)
    return {"mesh": mesh, "lo": lo, "hi": hi, "cell": cell,
            "dims": dims, "grid": grid}


def _axis_cell_distance(p, lo, cell, idx):
    c0 = lo + idx * cell
    c1 = c0 + cell
    if p < c0:
        return c0 - p
    if p > c1:
        return p - c1
    return 0.0


def _ring_lower_bound(p, ci, lo, cell, dims, r):
    """到 Chebyshev 环 r 的保守下界（环内至少有一轴落在 ci±r）。"""
    if r == 0:
        return math.sqrt(sum(_axis_cell_distance(p[i], lo[i], cell, ci[i]) ** 2
                             for i in range(3)))
    best = 1e300
    for axis in range(3):
        for side in (-r, r):
            idx = ci[axis] + side
            if 0 <= idx < dims[axis]:
                best = min(best, _axis_cell_distance(p[axis], lo[axis],
                                                     cell, idx))
    return best if best < 1e300 else 0.0


def _grid_distance(p, index):
    if index is None:
        return 0.0
    lo, _hi, cell, dims = (index["lo"], index["hi"], index["cell"],
                           index["dims"])
    ci = [max(0, min(dims[i] - 1, int(math.floor((p[i] - lo[i]) / cell))))
          for i in range(3)]
    best = 1e300
    maxr = max(dims) + 2
    for r in range(0, maxr + 1):
        if best < 1e300:
            bound = _ring_lower_bound(p, ci, lo, cell, dims, r)
            if bound > best:
                break
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                for dk in range(-r, r + 1):
                    if max(abs(di), abs(dj), abs(dk)) != r:
                        continue
                    i, j, k = ci[0] + di, ci[1] + dj, ci[2] + dk
                    if not (0 <= i < dims[0] and 0 <= j < dims[1] and
                            0 <= k < dims[2]):
                        continue
                    for idx in index["grid"].get((i, j, k), ()):
                        _, a, b, c = index["mesh"][idx]
                        d = point_triangle_distance(p, a, b, c)
                        if d < best:
                            best = d
    if best >= 1e300:
        for _, a, b, c in index["mesh"]:
            d = point_triangle_distance(p, a, b, c)
            if d < best:
                best = d
    return best


def _distance_stats(vals):
    vals = sorted(vals)
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": 0.0, "rms": 0.0, "p50": 0.0,
                "p95": 0.0, "max": 0.0}
    total = sum(vals)
    return {
        "n": n,
        "mean": total / n,
        "rms": math.sqrt(sum(v * v for v in vals) / n),
        "p50": vals[int(0.5 * (n - 1))],
        "p95": vals[int(0.95 * (n - 1))],
        "max": vals[-1],
    }


def mesh_deviation(mesh_a, mesh_b, samples=4000, seed=0,
                   rms_max=0.8, p95_max=1.8):
    """双向面积加权点—面偏差；两个方向都按同一采样口径统计。"""
    out = {}
    for label, src, dst in (("a_to_b", mesh_a, mesh_b),
                            ("b_to_a", mesh_b, mesh_a)):
        pts = sample_surface(src, count=samples, seed=seed)
        index = _mesh_grid(dst)
        vals = [_grid_distance(p, index) for p in pts]
        out[label] = _distance_stats(vals)
    ok = all(out[k]["rms"] <= rms_max and out[k]["p95"] <= p95_max
             for k in ("a_to_b", "b_to_a"))
    return {
        "a_to_b": out["a_to_b"],
        "b_to_a": out["b_to_a"],
        "rms_max": rms_max,
        "p95_max": p95_max,
        "pass": ok,
    }


def station_plan(measure, max_stations=48, offset_tol=1e-4):
    """由原件面表、孔/锥组生成测站（截面法向 + 位置）。

    平行平面族每个不同偏距一站；每个圆柱/圆锥组沿自身轴取根、中、端附近
    三站。站点以 (法向, 偏距) 去重。超过预算时先按法向族均匀保留平面站
    （占预算约六成），再按半径由大到小为每个轴组保留中点，最后才补端点；
    dropped>0 表示有边界未进入本次自检，complete=False。
    """
    faces = measure["faces"]
    groups = list(measure.get("cylinders", [])) + \
        list(measure.get("cones", []))
    acc = {}
    order = []

    def add(origin, normal, source, kind, role, group, radius):
        n = _canon(normal)
        off = _dot(origin, n)
        key = (_axis_key(n), round(off / max(offset_tol, 1e-9)))
        if key in acc:
            if source not in acc[key]["sources"]:
                acc[key]["sources"].append(source)
            if role == "mid":
                acc[key]["_mid"] = True
            if radius > acc[key]["_radius"]:
                acc[key]["_radius"] = radius
                acc[key]["_group"] = group
            return
        rec = {"origin": [off * n[i] for i in range(3)],
               "normal": list(n),
               "offset": off,
               "sources": [source],
               "kind": kind,
               "_role": role,
               "_mid": role == "mid",
               "_group": group,
               "_radius": radius}
        acc[key] = rec
        order.append(key)

    seen_planes = 0
    for f in faces:
        if f.get("type") != PLANE:
            continue
        add(f["point"], f["dir"], "plane#%d" % seen_planes,
            "plane", "plane", -1, 0.0)
        seen_planes += 1
    for gi, g in enumerate(groups):
        lo, hi = g["extent"]
        length = hi - lo
        if length <= 1e-6:
            continue
        inset = min(0.5, 0.1 * length)
        for role, t in (("end", lo + inset),
                        ("mid", 0.5 * (lo + hi)),
                        ("end", hi - inset)):
            origin = [g["point"][i] + t * g["axis"][i] for i in range(3)]
            add(origin, g["axis"], "axis#%d" % gi, "axis", role, gi,
                abs(g["radius"]))

    all_stations = [acc[k] for k in order]
    total = len(all_stations)
    dropped = 0
    if max_stations and total > max_stations:
        planes = [s for s in all_stations if s["kind"] == "plane"]
        axes = [s for s in all_stations if s["kind"] == "axis"]
        if axes:
            plane_budget = min(len(planes), max(1, int(max_stations * 0.6)))
        else:
            plane_budget = min(len(planes), int(max_stations))
        if len(planes) > plane_budget:
            step = float(len(planes)) / plane_budget
            planes = [planes[int(i * step)] for i in range(plane_budget)]
        axis_budget = max(0, int(max_stations) - len(planes))
        mids = sorted([s for s in axes if s["_mid"]],
                      key=lambda s: (-s["_radius"], s["_group"]))
        ends = sorted([s for s in axes if not s["_mid"]],
                      key=lambda s: (-s["_radius"], s["_group"], s["offset"]))
        take_mid = mids[:axis_budget]
        remain = axis_budget - len(take_mid)
        take_end = ends[:max(0, remain)]
        axes = take_mid + take_end
        stations = planes + axes
        dropped = total - len(stations)
    else:
        stations = all_stations
    stations.sort(key=lambda s: (tuple(s["normal"]), s["offset"]))
    plane_count = len([s for s in stations if s["kind"] == "plane"])
    axis_count = len(stations) - plane_count
    clean = []
    for s in stations:
        clean.append({"origin": s["origin"], "normal": s["normal"],
                      "offset": s["offset"], "sources": s["sources"],
                      "kind": s["kind"]})
    return {
        "stations": clean,
        "count": len(clean),
        "plane_count": plane_count,
        "axis_count": axis_count,
        "total": total,
        "dropped": dropped,
        "complete": dropped == 0,
    }


def station_report(mesh_a, mesh_b, plan, iou_min=0.95,
                   area_err_max_pct=5.0):
    """逐站截面 IoU / 面积差 / 缺料与多料面积；plan 取 station_plan 的返回值。

    `only_a` 是原件有、自建件缺的面积，`only_b` 是自建件多出的面积
    （单位随网格）。面积差只能说明总量，修结构时按 `only_a/only_b` 区分
    漏建与过建。
    """
    stations = plan["stations"] if isinstance(plan, dict) else plan
    rows = []
    failed = []
    for i, st in enumerate(stations):
        res = section_iou(mesh_a, mesh_b, st["origin"], st["normal"])
        aa, ab = res["area_a"], res["area_b"]
        if abs(aa) > 1e-9:
            err = abs(ab - aa) / abs(aa) * 100.0
        else:
            err = 0.0 if abs(ab) <= 1e-9 else 100.0
        ok = res["iou"] >= iou_min and err <= area_err_max_pct
        rows.append({
            "index": i,
            "origin": list(st["origin"]),
            "normal": list(st["normal"]),
            "sources": list(st.get("sources", [])),
            "iou": res["iou"],
            "area_a": aa,
            "area_b": ab,
            "area_inter": res["area_inter"],
            "area_union": res["area_union"],
            "only_a": max(0.0, aa - res["area_inter"]),
            "only_b": max(0.0, ab - res["area_inter"]),
            "area_err_pct": err,
            "pass": ok,
        })
        if not ok:
            failed.append(i)
    return {
        "stations": rows,
        "count": len(rows),
        "failed": failed,
        "iou_min": iou_min,
        "area_err_max_pct": area_err_max_pct,
        "pass": not failed,
    }


def _exact_loops_2d(sec, origin, normal):
    """B-rep 截面环投到测站平面二维坐标。"""
    e1, e2 = _basis(normal)
    polys = []
    for lp in sec["loops"]:
        pts = []
        for p in lp["pts"]:
            pts.append((_dot(_sub(p, origin), e1),
                        _dot(_sub(p, origin), e2)))
        if len(pts) < 3:
            continue
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        polys.append(pts)
    return polys


def _polygons_iou(pa, pb):
    """二维环集合的扫描线 IoU/面积；奇偶填充，孔环按内点消除。"""
    us, vs = [], []
    for poly in pa + pb:
        for u, v in poly:
            us.append(u)
            vs.append(v)
    if not us:
        return {"iou": 1.0, "area_a": 0.0, "area_b": 0.0,
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0}
    umin, umax = min(us), max(us)
    vmin, vmax = min(vs), max(vs)
    diag = math.sqrt((umax - umin) ** 2 + (vmax - vmin) ** 2)
    step = max(diag / 300.0, 0.02)
    nrows = max(1, int(math.ceil((vmax - vmin) / step)))
    inter = union = aa = ab = 0.0
    for iy in range(nrows):
        y = vmin + (iy + 0.5) * step
        sa = _merge(_row_spans([{"pts": poly} for poly in pa], y))
        sb = _merge(_row_spans([{"pts": poly} for poly in pb], y))
        ia = _span_inter(sa, sb)
        la = _span_len(sa)
        lb = _span_len(sb)
        aa += la
        ab += lb
        inter += ia
        union += la + lb - ia
    return {"iou": inter / union if union > 0 else 1.0,
            "area_a": aa * step, "area_b": ab * step,
            "area_inter": inter * step, "area_union": union * step,
            "step": step}


def brep_section_iou(part_a, part_b, origin, normal,
                     iou_min=0.95, area_err_max_pct=5.0):
    """同站 B-rep 精确截面 IoU；用于面表平面站，避免 STL 共面切面伪影。"""
    sa = exact_section(part_a, origin, normal)
    sb = exact_section(part_b, origin, normal)
    ca = _polygons_iou(_exact_loops_2d(sa, origin, normal),
                       _exact_loops_2d(sb, origin, normal))
    aa, ab = ca["area_a"], ca["area_b"]
    if abs(aa) > 1e-9:
        err = abs(ab - aa) / abs(aa) * 100.0
    else:
        err = 0.0 if abs(ab) <= 1e-9 else 100.0
    ok = ca["iou"] >= iou_min and err <= area_err_max_pct
    return {
        "iou": ca["iou"],
        "area_a": aa,
        "area_b": ab,
        "area_inter": ca["area_inter"],
        "area_union": ca["area_union"],
        "only_a": max(0.0, aa - ca["area_inter"]),
        "only_b": max(0.0, ab - ca["area_inter"]),
        "area_err_pct": err,
        "step": ca["step"],
        "open_a": sa["open"],
        "open_b": sb["open"],
        "gaps_a": list(sa["open_gaps"]),
        "gaps_b": list(sb["open_gaps"]),
        "pass": ok,
    }


def station_report_hybrid(mesh_a, mesh_b, part_a, part_b, plan,
                          iou_min=0.95, area_err_max_pct=5.0):
    """逐站截面：面表平面站用 B-rep 精确截面，其余站用 STL 截面。

    STL 切面在切平面与模型平面共面时会漏/重算三角面，不能把该站读数
    当形状判据；B-rep 原样站位（不偏移）才是平面站的判定口径。两者
    使用同一组阈值。
    """
    base = station_report(mesh_a, mesh_b, plan, iou_min, area_err_max_pct)
    rows = base["stations"]
    stations = plan["stations"] if isinstance(plan, dict) else plan
    brep_count = 0
    for row in rows:
        st = stations[row["index"]]
        if not any(str(s).startswith("plane#")
                   for s in st.get("sources", [])):
            row["section_mode"] = "stl"
            continue
        row.update(brep_section_iou(part_a, part_b, st["origin"],
                                    st["normal"], iou_min,
                                    area_err_max_pct))
        row["section_mode"] = "brep"
        brep_count += 1
    failed = [r["index"] for r in rows if not r["pass"]]
    base["stations"] = rows
    base["failed"] = failed
    base["pass"] = not failed
    base["brep_plane_count"] = brep_count
    base["stl_axis_count"] = len(rows) - brep_count
    return base


def verify_parts(orig, built, samples=4000, max_stations=48,
                 radius_tol=0.025, center_tol=0.05, axis_tol_deg=0.1,
                 length_tol=0.1, half_angle_tol=0.1,
                 volume_pct=0.1, bbox_pos_mm=0.05, bbox_size_mm=0.05,
                 view_iou_min=0.99, rms_max=0.8, p95_max=1.8,
                 section_iou_min=0.95, section_area_pct=5.0,
                 ref_a=None, ref_b=None):
    """原件/自建件几何门 G0–G6 一次汇总（G2–G6 长度换算到毫米）。

    G1 的面表平面站用 B-rep 精确截面复核，其余站用 STL 截面；两者阈值
    相同。G1 的站位取自原件面表，要求两件使用同一长度单位；G2–G6 会按
    各自 `length_scale` 换算到毫米。G7 圆角为报告项；G8 表达式存活与
    G9 结构语义仍需按 `modeling.md` §6 的编辑测试与特征树检查，本函数
    不作替代。
    """
    mo = measure_part(orig)
    mb = measure_part(built)
    part_o = open_part(orig)
    mesh_o = read_stl(export_mesh(part_o))
    part_b = open_part(built)
    mesh_b = read_stl(export_mesh(part_b))
    so, sb = mo["length_scale"], mb["length_scale"]
    if abs(so - sb) > 1e-12:
        print("WARN verify_parts: orig units=%s, built units=%s; "
              "G1 assumes the same length unit" % (mo["units"], mb["units"]))
    mesh_o_mm = scale_mesh(mesh_o, so)
    mesh_b_mm = scale_mesh(mesh_b, sb)

    plan = station_plan(mo, max_stations=max_stations)
    sec = station_report_hybrid(mesh_o, mesh_b, part_o, part_b, plan,
                                section_iou_min, section_area_pct)
    if ref_a is None:
        ref_a = functional_hole_groups(mo, part_o)
    cmp = compare_parts(orig, built, radius_tol, center_tol, axis_tol_deg,
                        length_tol, half_angle_tol, ref_a, ref_b)
    vol_pct = abs(mb["volume"] - mo["volume"]) / mo["volume"] * 100.0 \
        if mo["volume"] else 100.0
    bb_o = mesh_bbox(mesh_o_mm)
    bb_b = mesh_bbox(mesh_b_mm)
    pos_d = max(abs(bb_o[i] - bb_b[i]) for i in range(6))
    size_o = [bb_o[i + 3] - bb_o[i] for i in range(3)]
    size_b = [bb_b[i + 3] - bb_b[i] for i in range(3)]
    size_d = max(abs(size_o[i] - size_b[i]) for i in range(3))
    views = {}
    for name in ("top", "front", "side"):
        views[name] = view_iou(mesh_o_mm, mesh_b_mm, name)
    views["iso"] = view_iou(mesh_o_mm, mesh_b_mm, [1.0, 1.0, 1.0])
    views_pass = all(v["iou"] >= view_iou_min for v in views.values())
    dev = mesh_deviation(mesh_o_mm, mesh_b_mm, samples, 0,
                         rms_max, p95_max)
    gates = {
        "G0": {"pass": bool(mesh_o and mesh_b and mo["bodies"] and
                            mb["bodies"]),
               "bodies": [mo["bodies"], mb["bodies"]]},
        "G1": sec,
        "G2": cmp,
        "G3": {"pass": vol_pct <= volume_pct, "diff_pct": vol_pct,
               "limit_pct": volume_pct},
        "G4": {"pass": pos_d <= bbox_pos_mm and size_d <= bbox_size_mm,
               "position_delta_mm": pos_d, "size_delta_mm": size_d,
               "limits_mm": [bbox_pos_mm, bbox_size_mm]},
        "G5": {"pass": views_pass, "views": views,
               "iou_min": view_iou_min},
        "G6": dev,
    }
    return {
        "orig": {"path": mo["path"], "units": mo["units"],
                 "length_scale": so, "volume": mo["volume"],
                 "bodies": mo["bodies"]},
        "built": {"path": mb["path"], "units": mb["units"],
                  "length_scale": sb, "volume": mb["volume"],
                  "bodies": mb["bodies"]},
        "stations": plan,
        "gates": gates,
        "pass": all(gates[k]["pass"] for k in ("G0", "G1", "G2", "G3",
                                               "G4", "G5", "G6")),
    }
