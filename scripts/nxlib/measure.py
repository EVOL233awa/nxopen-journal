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
        if pu == NXOpen.Part.Units.Inches:
            return "inch", 25.4
        if pu == NXOpen.Part.Units.Millimeters:
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
    lo, hi, cell, dims = (index["lo"], index["hi"], index["cell"],
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


def station_plan(measure, max_stations=96, offset_tol=1e-4):
    """由原件面表、孔/锥组生成测站（截面法向 + 位置）。

    平行平面族每个不同偏距一站；每个圆柱/圆锥组沿自身轴取根、中、端附近
    三站。站点以 (法向, 偏距) 去重；超过预算时保留全部孔站，再按偏距均匀
    保留平面站，并在 dropped 中记数。
    """
    faces = measure["faces"]
    groups = list(measure.get("cylinders", [])) + \
        list(measure.get("cones", []))
    acc = {}
    order = []

    def axis_key(d):
        d = _canon(d)
        return (round(d[0], 3), round(d[1], 3), round(d[2], 3))

    def add(origin, normal, source):
        n = _canon(normal)
        off = _dot(origin, n)
        key = (axis_key(n), round(off / max(offset_tol, 1e-9)))
        if key in acc:
            if source not in acc[key]["sources"]:
                acc[key]["sources"].append(source)
            return
        rec = {"origin": [off * n[i] for i in range(3)],
               "normal": list(n),
               "offset": off,
               "sources": [source],
               "kind": "plane" if source.startswith("plane") else "axis"}
        acc[key] = rec
        order.append(key)

    seen_planes = 0
    for f in faces:
        if f.get("type") != PLANE:
            continue
        add(f["point"], f["dir"], "plane#%d" % seen_planes)
        seen_planes += 1
    for gi, g in enumerate(groups):
        lo, hi = g["extent"]
        length = hi - lo
        if length <= 1e-6:
            continue
        inset = min(0.5, 0.1 * length)
        for t in (lo + inset, 0.5 * (lo + hi), hi - inset):
            origin = [g["point"][i] + t * g["axis"][i] for i in range(3)]
            add(origin, g["axis"], "axis#%d" % gi)

    stations = [acc[k] for k in order]
    plane_count = len([s for s in stations if s["kind"] == "plane"])
    dropped = 0
    if max_stations and len(stations) > max_stations:
        axis = [s for s in stations if s["kind"] == "axis"]
        plane = [s for s in stations if s["kind"] == "plane"]
        keep_plane = max(0, int(max_stations) - len(axis))
        if keep_plane < len(plane):
            step = float(len(plane)) / max(1, keep_plane)
            plane = [plane[int(i * step)] for i in range(keep_plane)]
        stations = plane + axis
        dropped = plane_count + len(axis) - len(stations)
        plane_count = len(plane)
    stations.sort(key=lambda s: (tuple(s["normal"]), s["offset"]))
    return {
        "stations": stations,
        "count": len(stations),
        "plane_count": plane_count,
        "axis_count": len(stations) - plane_count,
        "dropped": dropped,
    }


def station_report(mesh_a, mesh_b, plan, iou_min=0.95,
                   area_err_max_pct=5.0):
    """逐站截面 IoU / 面积差；plan 取 station_plan 的返回值或其 stations。"""
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


def verify_parts(orig, built, samples=4000, max_stations=96,
                 radius_tol=0.025, center_tol=0.05, axis_tol_deg=0.1,
                 length_tol=0.1, half_angle_tol=0.1,
                 volume_pct=0.1, bbox_pos_mm=0.05, bbox_size_mm=0.05,
                 view_iou_min=0.99, rms_max=0.8, p95_max=1.8,
                 section_iou_min=0.95, section_area_pct=5.0):
    """原件/自建件几何门 G0–G6 一次汇总（长度统一到毫米）。

    G7 圆角为报告项；G8 表达式存活与 G9 结构语义仍需按 `modeling.md` §6
    的编辑测试与特征树检查，本函数不作替代。
    """
    mo = measure_part(orig)
    mb = measure_part(built)
    part_o = open_part(orig)
    mesh_o = read_stl(export_mesh(part_o))
    part_b = open_part(built)
    mesh_b = read_stl(export_mesh(part_b))
    so, sb = mo["length_scale"], mb["length_scale"]
    mesh_o_mm = scale_mesh(mesh_o, so)
    mesh_b_mm = scale_mesh(mesh_b, sb)

    plan = station_plan(mo, max_stations=max_stations)
    sec = station_report(mesh_o, mesh_b, plan, section_iou_min,
                         section_area_pct)
    cmp = compare_parts(orig, built, radius_tol, center_tol, axis_tol_deg,
                        length_tol, half_angle_tol)
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
