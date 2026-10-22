# -*- coding: utf-8 -*-
"""nxlib.measure —— 只读测量：面表、同轴分组、截面面积/IoU、原件与自建件比对。

两条数据链，都只读、都不保存：
  面表  UF_MODL_ask_face_data 给类型/轴/半径/半角/包盒，按同轴同半径聚成
        圆柱组、按同轴同半角聚成圆锥组；孔参数（直径/轴/长度/中心）由组
        的轴向区间给出。
  截面  DexManager STL 导出（弦高 0.01 mm）后用平面切三角网格，环按外法
        向定向：外环正面积、孔环负面积，净面积取代数和。同一函数既能量
        原件也能量自建件，所以自检闭环是"量原件 → 建 → 量自建件 → 比"。

约定：
  圆柱=16、圆锥=17、圆环=19、平面=22（Parasolid 面类型）。
  圆锥半角对外用度；UF 的 rad_data 是弧度。
  长度单位随部件（mm）。
"""
import math
import os
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


def measure_part(path, with_edges=True):
    """只读量一个部件：体积/体数/特征数/面表/圆柱组/圆锥组。"""
    part = open_part(path)
    faces = face_table(part, with_edges=with_edges)
    return {
        "path": part.FullPath,
        "volume": part_volume(part),
        "bodies": len(list(part.Bodies)),
        "features": len(list(part.Features)),
        "faces": faces,
        "cylinders": group_coaxial(faces, CYLINDER),
        "cones": group_coaxial(faces, CONE),
    }


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


def compare_parts(path_a, path_b, radius_tol=0.025, center_tol=0.05,
                  axis_tol_deg=0.1, length_tol=0.1, half_angle_tol=0.1,
                  ref_a=None, ref_b=None):
    """原件/自建件的 G2 口径比对。

    匹配条件：半径差 ≤2×radius_tol、轴角 ≤axis_tol_deg、孔心（垂直于轴的
    平面内）≤center_tol。逐项判定：圆柱看半径/孔心/轴/长度，圆锥再加半角。
    `pass` 只有在两组都无未匹配项且每个 pair 都过阈值时为真；`unmatched_a`
    是“原件有、自建件没有”的结构，必须逐项建或写入简化清单。

    ref_a/ref_b 传入上一轮 measure_part 的组列表作为比对清单（按 faces
    tag 识别）。原件侧应先用截面圆孔环筛出功能孔清单再传 ref_a；不筛时
    圆角/凸台的圆柱组也会算进未匹配项。
    """
    a = measure_part(path_a)
    b = measure_part(path_b)

    def subset(groups, ref):
        if ref is None:
            return groups
        keys = set(tuple(g["faces"]) for g in ref)
        return [g for g in groups if tuple(g["faces"]) in keys]

    cyl = _match_groups(subset(a["cylinders"], ref_a),
                        subset(b["cylinders"], ref_b), CYLINDER,
                        radius_tol, center_tol, axis_tol_deg,
                        length_tol, half_angle_tol)
    cones = _match_groups(subset(a["cones"], ref_a),
                          subset(b["cones"], ref_b), CONE,
                          radius_tol, center_tol, axis_tol_deg,
                          length_tol, half_angle_tol)
    return {
        "a": {"path": a["path"], "volume": a["volume"],
              "bodies": a["bodies"], "features": a["features"]},
        "b": {"path": b["path"], "volume": b["volume"],
              "bodies": b["bodies"], "features": b["features"]},
        "delta_volume": b["volume"] - a["volume"],
        "delta_volume_ratio": ((b["volume"] - a["volume"]) / a["volume"]
                               if a["volume"] else 0.0),
        "cylinders": cyl,
        "cones": cones,
        "pass": cyl["pass"] and cones["pass"],
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
