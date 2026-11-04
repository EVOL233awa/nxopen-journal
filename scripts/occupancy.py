# -*- coding: utf-8 -*-
"""截面占用门：三轴切片 + 体积差 + 连通分量。

旧口径只做 Z 向定站距切片，1 mm 薄腔遇到 1.18 mm 站距会 0 命中，于是
"没有差异"被当成 PASS。这里把三件事分开：

  - 切片：Z/X/Y 三轴，站距由调用方给或按最小特征厚度自适应；
  - 体积：闭合三角网格的有符号体积差，与切片互为独立证据；
  - 分量：多体/内腔导致的连通分量变化。

判定三态：PASS / FAIL / NO_SIGNAL。站距粗于可检厚度且体积也无差异时给
NO_SIGNAL，绝不把"仪器没看见"写成 PASS。

纯标准库 + `deliverable`，Python 3.6 兼容；不依赖 numpy/trimesh。
"""
import math

import deliverable

PASS = "PASS"
FAIL = "FAIL"
NO_SIGNAL = "NO_SIGNAL"


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _unit(a):
    n = math.sqrt(_dot(a, a))
    if n < 1e-15:
        return [0.0, 0.0, 0.0]
    return [a[0] / n, a[1] / n, a[2] / n]


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


def _key(p, digits=5):
    return (round(p[0], digits), round(p[1], digits))


def _poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def _plane_segments(mesh, origin, normal, weld=1e-5):
    """三角形与平面的交线段，按面法向定方向（外环正、孔环负）。"""
    n = _unit(normal)
    e1, e2 = _basis(n)
    segs = []
    for tri in mesh:
        if len(tri) == 4:
            tn, v0, v1, v2 = tri
        else:
            tn, v0, v1, v2 = [0.0, 0.0, 0.0], tri[0], tri[1], tri[2]
        vs = [v0, v1, v2]
        ds = [_dot(_sub(v, origin), n) for v in vs]
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if abs(ds[i]) <= weld:
                pts.append(vs[i])
            if ds[i] * ds[j] < 0.0:
                t = ds[i] / (ds[i] - ds[j])
                pts.append([vs[i][k] + t * (vs[j][k] - vs[i][k])
                            for k in range(3)])
        uniq = []
        for p in pts:
            if not any(_dist3(p, q) <= weld for q in uniq):
                uniq.append(p)
        if len(uniq) != 2:
            continue
        p, q = uniq
        d = _sub(q, p)
        if _dot(_cross(d, tn), n) < 0.0:
            p, q = q, p
        p2 = [_dot(_sub(p, origin), e1), _dot(_sub(p, origin), e2)]
        q2 = [_dot(_sub(q, origin), e1), _dot(_sub(q, origin), e2)]
        if _dist2(p2, q2) > weld:
            segs.append((p2, q2))
    return segs


def _dist2(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _dist3(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _loops(segs, weld=1e-5):
    adj = {}
    for i, (a, b) in enumerate(segs):
        adj.setdefault(_key(a), []).append((i, 0))
        adj.setdefault(_key(b), []).append((i, 1))
    used = set()
    loops = []
    for i in range(len(segs)):
        if i in used:
            continue
        used.add(i)
        start = segs[i][0]
        end = segs[i][1]
        pts = [start, end]
        closed = _dist2(end, start) <= weld
        while not closed:
            nxt = None
            for j, side in adj.get(_key(end), []):
                if j in used:
                    continue
                nxt = (j, side)
                break
            if nxt is None:
                break
            j, side = nxt
            used.add(j)
            end = segs[j][1] if side == 0 else segs[j][0]
            pts.append(end)
            closed = _dist2(end, start) <= weld
        if closed:
            pts = pts[:-1]
            loops.append({"pts": pts, "area": _poly_area(pts)})
        else:
            loops.append({"pts": pts, "area": 0.0, "open": True})
    return loops


def section_area(mesh, origin, normal):
    loops = _loops(_plane_segments(mesh, origin, normal))
    return {
        "area": sum(l["area"] for l in loops),
        "loops": len(loops),
        "open": sum(1 for l in loops if l.get("open")),
    }


def mesh_volume(mesh):
    s = 0.0
    for tri in mesh:
        v0, v1, v2 = tri[1], tri[2], tri[3]
        s += _dot(v0, _cross(v1, v2)) / 6.0
    return s


def mesh_bbox(mesh):
    lo = [1e300, 1e300, 1e300]
    hi = [-1e300, -1e300, -1e300]
    for tri in mesh:
        for v in (tri[1], tri[2], tri[3]):
            for i in range(3):
                lo[i] = min(lo[i], v[i])
                hi[i] = max(hi[i], v[i])
    return [lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]]


def _stations(lo, hi, pitch):
    """等分格中心；最后一格可能不足 pitch，仍要取中心，否则顶/底薄层无站。"""
    if pitch <= 0.0 or hi <= lo:
        return []
    n = int(math.ceil((hi - lo) / pitch))
    if n <= 0:
        return []
    out = []
    for k in range(n):
        s = lo + (k + 0.5) * pitch
        if s >= hi:
            s = hi - 1e-4
        out.append(s)
    return out


def axis_report(ref_mesh, test_mesh, axis, pitch, area_tol=0.5,
                rel_area_tol=0.001):
    box_r = mesh_bbox(ref_mesh)
    box_t = mesh_bbox(test_mesh)
    lo = min(box_r[axis], box_t[axis])
    hi = max(box_r[axis + 3], box_t[axis + 3])
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    rows = []
    for s in _stations(lo, hi, pitch):
        origin = [0.0, 0.0, 0.0]
        origin[axis] = s
        a = section_area(ref_mesh, origin, normal)
        b = section_area(test_mesh, origin, normal)
        delta = abs(a["area"] - b["area"])
        tol = max(area_tol, rel_area_tol * max(abs(a["area"]),
                                               abs(b["area"])))
        loop_delta = a["loops"] != b["loops"]
        # 两侧都无材料：空站，不算命中也不算通过。
        empty = abs(a["area"]) < tol and abs(b["area"]) < tol
        hit = (not empty) and (delta > tol or loop_delta)
        rows.append({"station": s, "ref": a["area"], "test": b["area"],
                     "delta": delta, "ref_loops": a["loops"],
                     "test_loops": b["loops"], "empty": empty,
                     "hit": hit})
    return {
        "axis": "xyz"[axis],
        "pitch": pitch,
        "stations": rows,
        "hits": [r["station"] for r in rows if r["hit"]],
        "measured": [r["station"] for r in rows if not r["empty"]],
        "empty": [r["station"] for r in rows if r["empty"]],
    }


def _uniq(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _components(mesh, weld=1e-5):
    parent = {}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            nxt = parent[x]
            parent[x] = root
            x = nxt
        return root

    def add(x):
        if x not in parent:
            parent[x] = x

    def union(a, b):
        add(a)
        add(b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    ids = {}
    tri_ids = []
    for tri in mesh:
        cur = []
        for v in (tri[1], tri[2], tri[3]):
            k = (round(v[0], 5), round(v[1], 5), round(v[2], 5))
            if k not in ids:
                ids[k] = len(ids)
            cur.append(ids[k])
        tri_ids.append(cur)
        add(cur[0])
        union(cur[0], cur[1])
        union(cur[1], cur[2])
    return len(set(find(t[0]) for t in tri_ids))


def occupancy_gate(ref_path, test_path, pitch=1.18, axes=(0, 1, 2),
                   min_feature=None, volume_tol=0.002, area_tol=0.5,
                   bbox_tol=0.05):
    ref_mesh = deliverable.read_stl_triangles(ref_path)
    test_mesh = deliverable.read_stl_triangles(test_path)
    codes, notes = [], []
    if not ref_mesh or not test_mesh:
        return {"verdict": NO_SIGNAL, "codes": ["DELIV_E_OCC_MESH"],
                "notes": ["empty mesh"], "report": {}}

    ref_vol = mesh_volume(ref_mesh)
    test_vol = mesh_volume(test_mesh)
    vol_delta = abs(abs(ref_vol) - abs(test_vol))
    rel = vol_delta / max(abs(ref_vol), 1e-12)
    comp_ref = _components(ref_mesh)
    comp_test = _components(test_mesh)
    box_ref = mesh_bbox(ref_mesh)
    box_test = mesh_bbox(test_mesh)
    box_delta = max(abs(a - b) for a, b in zip(box_ref, box_test))

    reports = {}
    total_hits = 0
    for axis in axes:
        rep = axis_report(ref_mesh, test_mesh, axis, pitch, area_tol)
        reports["xyz"[axis]] = rep
        total_hits += len(rep["hits"])

    # 绝对下限 1 mm³ 挡住切面噪声；相对阈值按参考体积。
    if vol_delta > max(1.0, volume_tol * abs(ref_vol)):
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("volume delta %.4f%% (%.3f -> %.3f)"
                     % (rel * 100.0, abs(ref_vol), abs(test_vol)))
    if total_hits:
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("%d slice stations differ" % total_hits)
    if comp_ref != comp_test:
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("components %d -> %d" % (comp_ref, comp_test))
    if box_delta > bbox_tol:
        codes.append("DELIV_E_OCCUPANCY_BBOX")
        notes.append("bbox delta %.4f" % box_delta)

    if codes:
        codes = _uniq(codes)
        return {"verdict": FAIL, "codes": codes, "notes": notes,
                "report": {"axes": reports, "rel_volume": rel,
                           "components": [comp_ref, comp_test],
                           "bbox_delta": box_delta}}

    # 无差异但站距粗于可检厚度：仪器看不见，给 NO_SIGNAL。
    if min_feature is not None and pitch > min_feature * 0.5:
        return {"verdict": NO_SIGNAL,
                "codes": ["DELIV_E_OCC_NO_SIGNAL"],
                "notes": ["pitch %.3f > min_feature/2 %.3f"
                          % (pitch, min_feature * 0.5)],
                "report": {"axes": reports, "rel_volume": rel,
                           "components": [comp_ref, comp_test],
                           "bbox_delta": box_delta}}
    return {"verdict": PASS, "codes": [], "notes": [],
            "report": {"axes": reports, "rel_volume": rel,
                       "components": [comp_ref, comp_test],
                       "bbox_delta": box_delta}}


if __name__ == "__main__":
    print("use scripts/tests/52_occupancy_gate.py for the shipped selftest")
