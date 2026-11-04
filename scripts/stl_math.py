# -*- coding: utf-8 -*-
"""STL 读取与截面几何（occupancy 与 render_stl 共用）"""
import math
import struct


# ---------------------------------------------------------------- STL 读取

def _read_stl_binary(data):
    if len(data) < 84:
        return None
    count = struct.unpack("<I", data[80:84])[0]
    if count <= 0 or 84 + 50 * count > len(data):
        return None
    tris = []
    off = 84
    for _ in range(count):
        vals = struct.unpack("<12f", data[off:off + 48])
        tris.append(([vals[0], vals[1], vals[2]],
                     [vals[3], vals[4], vals[5]],
                     [vals[6], vals[7], vals[8]],
                     [vals[9], vals[10], vals[11]]))
        off += 50
    return tris


def _read_stl_ascii(text):
    tris, nrm, verts = [], None, []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower() == "facet" and len(parts) >= 5:
            nrm = [float(parts[2]), float(parts[3]), float(parts[4])]
        elif parts[0].lower() == "vertex" and len(parts) >= 4:
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            if len(verts) == 3:
                tris.append((nrm or [0.0, 0.0, 0.0],
                             verts[0], verts[1], verts[2]))
                verts = []
    return tris


def read_stl_triangles(path):
    """读二进制/ASCII STL，返回 [(normal, v0, v1, v2)]。"""
    with open(path, "rb") as fh:
        data = fh.read()
    tris = _read_stl_binary(data)
    if tris is None:
        tris = _read_stl_ascii(data.decode("utf-8", "replace"))
    return tris


# ---------------------------------------------------------------- 截面几何

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
    """三角形与平面的交线段，每段方向取 d 使 d×面法向 指向截面法向正向；
    于是外法向网格（有符号体积为正）下外环面积为负、孔环为正。"""
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


# ---------------------------------------------------------------- 连通分量

def components(mesh, weld=1e-5):
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
