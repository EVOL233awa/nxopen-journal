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
# 判定口径的切站偏移：切平面与模型平面共面时三角面求交会漏/重算，平面站
# 必须离开面一个亚毫米量级；轴站也带同一偏移，避免擦到端面共面三角。
SECTION_CUT_DEPTH = 0.0137
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


def _is_auto_expression(name):
    """NX 自动表达式（p0/p1…）与 PI 不计入 G8 存活率。"""
    if not name:
        return True
    if name.upper() == "PI":
        return True
    if name[0] in ("p", "P"):
        return name[1:].isdigit()
    return False


def expression_survey(part, factor=1.1):
    """G8 可编辑性：逐条命名表达式 +factor、更新、量体积、还原。

    与 `references/modeling.md` §6 及冻结 edit_survey 同口径：自动表达式
    （p0/p1…）与 PI 不计；RHS 非数值的公式记录在 skipped，不参与存活率。
    每次改动都新建 undo mark 并 DoUpdate，还原后再更新一次并核对体积。
    只改内存中的部件，**不保存**；调用方应传入已建的输出件，且此时不要再
    保存该部件（否则参数试验的结果会进文件）。

    某个表达式更新失败只记录该条并继续测其余表达式，不因首个 broken 丢掉
    后面的证据；还原失败则抛错（部件已不可信，不能继续报存活率）。
    pass = 单实体 + 至少一个命名表达式 + 至少一条实测驱动几何 + 无死参数
    + 无更新异常/还原失败 + 无特征告警 + 存活率 1.0。
    """
    bodies = list(part.Bodies)
    v0 = part_volume(part)
    named = []
    seen = set()
    for e in part.Expressions:
        try:
            lhs = e.Equation.split("=")[0].strip()
        except Exception:
            continue
        if _is_auto_expression(lhs) or lhs in seen:
            continue
        seen.add(lhs)
        named.append((lhs, e))
    live, dead, broken, skipped = [], [], [], []
    for i, (name, e) in enumerate(named):
        try:
            rhs = e.RightHandSide
            val = float(rhs)
        except Exception:
            skipped.append(name)
            continue
        changed = False
        try:
            e.RightHandSide = "%.6f" % (val * factor)
            changed = True
            errs = _do_update("survey_%d" % i)
            d = part_volume(part) - v0
            if errs != 0:
                broken.append({"name": name, "errors": errs})
            elif abs(d) < 1e-4:
                dead.append(name)
            else:
                live.append({"name": name, "delta_volume": d})
        except Exception as exc:
            broken.append({"name": name, "exception": str(exc)[:300]})
        if not changed:
            continue
        try:
            e.RightHandSide = rhs
            errs2 = _do_update("restore_%d" % i)
            vr = part_volume(part)
        except Exception as exc:
            raise RuntimeError("expression restore failed for %s: %s" %
                               (name, exc))
        if errs2 != 0 or abs(vr - v0) > 1e-4 * max(abs(v0), 1.0):
            raise RuntimeError(
                "expression restore failed for %s: errors=%s volume=%.6f/%.6f" %
                (name, errs2, vr, v0))
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


def face_area(part, face):
    """单面面积（部件单位²）；读不到返回 None。

    走 `MeasureManager.NewFaceProperties`，返回对象的 `.Area` 就是面积。
    与包围盒乘积、UV 雅可比积分两条独立路径逐位一致（探针见 §10.1）。
    面积是平面族分带、板面积占比与平行面堆叠判据的共同输入：缺了它这些
    判据会静默退化成"面积恒 0"（比值恒 1.0），堆叠判据变成"偏置数 ≥ N
    就判堆叠"——这会误拒合法的多结构件。
    """
    try:
        m = part.MeasureManager.NewFaceProperties(_area_unit(part),
                                                  _length_unit(part),
                                                  0.99, [face])
        val = float(m.Area)
        if val != val or abs(val) == float("inf"):
            return None
        return val
    except Exception:
        return None


def _area_unit(part):
    uc = part.UnitCollection
    for name in ("SquareMilliMeter", "SquareMillimeter", "SquareMeter",
                 "SquareInch", "SquareMillimetre"):
        try:
            u = uc.FindObject(name)
            if u is not None:
                return u
        except Exception:
            continue
    raise RuntimeError("no area unit found in the part unit collection")


def _length_unit(part):
    uc = part.UnitCollection
    for name in ("MilliMeter", "Millimeter", "Meter", "Inch", "Millimetre"):
        try:
            u = uc.FindObject(name)
            if u is not None:
                return u
        except Exception:
            continue
    raise RuntimeError("no length unit found in the part unit collection")


def face_table(part, with_edges=False, with_area=True):
    """全量面表。with_edges=True 时每面带边（类型/长度/相邻面 tag），
    供同轴组的端面定位使用；with_area=True 时每面带 `area`（部件单位²）。

    面积默认读：结构推断的平面族分带、板面积占比与堆叠判据都以它为输入。
    """
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
            except Exception as exc:
                rec.update({"type": -1, "point": [0.0, 0.0, 0.0],
                            "dir": [0.0, 0.0, 1.0], "box": [0.0] * 6,
                            "radius": 0.0, "rad_data": 0.0, "norm_dir": 0,
                            "invalid": True,
                            "error": str(exc)[:200]})
            if with_area:
                rec["area"] = face_area(part, f)
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


def group_coaxial(faces, kind=CYLINDER, axis_digits=3, radius_digits=3,
                  cluster_tol=None):
    """把面表聚成同轴组。

    圆柱按 (轴, 半径) 分桶，圆锥按 (轴, 半角) 分桶；桶内再按到轴线的距离
    聚簇，距离上限取 2r+2（同一孔的上下两段圆柱不会被拆开，不同孔不会被
    并在一起），cluster_tol 给定时改用它。返回组的
    axis/point/extent/length/center/radius/faces。
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
        tol = cluster_tol if cluster_tol is not None else max(
            2.0 * max(abs(f.get("radius", 0.0)) for f in fs) + 2.0, 5.0)
        parent = list(range(len(fs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                if _line_dist(fs[i]["point"], d, fs[j]["point"]) <= tol:
                    union(i, j)
        by_root = {}
        for i in range(len(fs)):
            by_root.setdefault(find(i), []).append(fs[i])
        for cl_faces in by_root.values():
            cl = {"p0": list(cl_faces[0]["point"]), "faces": cl_faces}
            intervals = []
            for f in cl["faces"]:
                a, b = _project_extent(f["box"], cl["p0"], d)
                intervals.append({"faces": [f["tag"]],
                                  "extent": [a, b],
                                  "length": b - a})
            intervals.sort(key=lambda s: (s["extent"][0], s["extent"][1]))
            lo = min(s["extent"][0] for s in intervals)
            hi = max(s["extent"][1] for s in intervals)
            bx = [min(f["box"][k] for f in cl["faces"]) for k in range(3)] + \
                 [max(f["box"][k + 3] for f in cl["faces"]) for k in range(3)]
            mid = 0.5 * (lo + hi)
            groups.append({
                "kind": kind,
                "axis": d,
                "point": cl["p0"],
                "radius": abs(cl["faces"][0].get("radius", 0.0)),
                "half_angle_deg": math.degrees(cl["faces"][0].get("rad_data", 0.0)),
                "extent": [lo, hi],
                "length": hi - lo,
                "segments": intervals,
                "bbox": bx,
                "center": [cl["p0"][k] + d[k] * mid for k in range(3)],
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
    """圆柱组的孔参数：直径/轴/中心/轴向长度/端面。中心是组轴向中点
    （`group_coaxial` 给的轴线上一点），不是包盒中心（包盒在 `group["bbox"]`）。"""
    return {
        "diameter": 2.0 * group["radius"],
        "radius": group["radius"],
        "axis": group["axis"],
        "center": list(group["center"]),
        "length": group["length"],
        "extent": list(group["extent"]),
        "segments": list(group.get("segments", [])),
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
        "segments": list(group.get("segments", [])),
        "faces": list(group["faces"]),
    }


def _bbox_union(faces):
    return [min(f["box"][k] for f in faces) for k in range(3)] + \
           [max(f["box"][k + 3] for f in faces) for k in range(3)]


def torus_groups(faces, center_tol=40.0):
    """环面按 (major, minor) 分桶，桶内按包围盒就近聚簇。

    圆角的环面常被布尔切成多片，同一圆角带的分片包围盒彼此邻近；
    不同结构上的同参数环面（如两只耳的根部圆角）相距远，不会被并组。
    """
    picked = [f for f in faces if f.get("type") == TORUS]
    buckets = {}
    for f in picked:
        key = (round(f.get("radius", 0.0), 3), round(f.get("rad_data", 0.0), 3))
        buckets.setdefault(key, []).append(f)
    out = []
    for key, fs in buckets.items():
        clusters = []
        for f in fs:
            c = list(f["box"][:3]) + list(f["box"][3:])
            for cl in clusters:
                if math.sqrt(sum((cl["c"][i] - c[i]) ** 2
                                for i in range(6))) <= center_tol:
                    cl["faces"].append(f)
                    break
            else:
                clusters.append({"c": c, "faces": [f]})
        for cl in clusters:
            out.append({"major": key[0], "minor": key[1],
                        "nfaces": len(cl["faces"]),
                        "bbox": _bbox_union(cl["faces"]),
                        "faces": [f["tag"] for f in cl["faces"]]})
    return sorted(out, key=lambda r: (r["minor"], -r["major"]))


def plane_families(faces, digits=2):
    """平面按 (单位法向, 沿法向的偏置) 分族：共面片归一族，平行异面不并。"""
    picked = [f for f in faces if f.get("type") == PLANE]
    buckets = {}
    for f in picked:
        n = _canon(f.get("dir", [0.0, 0.0, 1.0]))
        off = _dot(f.get("point", [0.0, 0.0, 0.0]), n)
        key = (tuple(round(x, digits) for x in n), round(off, digits))
        buckets.setdefault(key, []).append(f)
    out = []
    for key, fs in buckets.items():
        out.append({"normal": list(key[0]), "offset": key[1],
                    "nfaces": len(fs), "bbox": _bbox_union(fs),
                    "faces": [x["tag"] for x in fs]})
    return sorted(out, key=lambda r: -r["nfaces"])


def structure_directory(faces, cluster_tol=None, axis_digits=3):
    """面表 → 结构目录：同轴圆柱/圆锥组、环面组、平面族。

    每组给几何参数（轴/参考点/半径/半角/轴向区间/包围盒/凹性/面 tag），是
    "每个功能面组只属于一个结构"的机器可读底表：孔/座/窗取 cylinders 与
    cones 的轴向区间，圆角面另由 `fillet_map` 按半径单列。
    cluster_tol 缺省交给 `group_coaxial` 的 2R+2 口径；显式给定时只用于
    测试/特殊件。
    """
    groups = group_coaxial(faces, CYLINDER, axis_digits=axis_digits,
                           cluster_tol=cluster_tol)
    groups += group_coaxial(faces, CONE, axis_digits=axis_digits,
                            cluster_tol=cluster_tol)
    torus_tol = 5.0 * (cluster_tol if cluster_tol is not None else 8.0)
    return {
        "cylinders": [g for g in groups if g["kind"] == CYLINDER],
        "cones": [g for g in groups if g["kind"] == CONE],
        "torus_groups": torus_groups(faces, torus_tol),
        "plane_families": plane_families(faces),
    }


def fillet_map(faces, radii=None, tol=0.002, max_ratio=0.25,
               min_faces=2):
    """面表 → 圆角地图：按半径的面组 + 每面支撑面（边邻接统计）。

    radii 给定时按该半径集合分桶（圆柱半径、环面 minor、球半径）；为 None
    时取"小半径"组自动识别：半径 ≤ max_ratio×最大面半径且至少 min_faces 个面。
    自动识别只是起点——倒角/小孔也会落进来，判据是支撑面：圆角面夹在两片
    支撑面之间，且支撑面的半径与它不同。
    """
    usable = [f for f in faces if f.get("type") in (CYLINDER, CONE, TORUS, 18)]
    by_tag = dict((f["tag"], f) for f in faces)
    if radii is None:
        hist = {}
        for f in usable:
            r = abs(f.get("radius", 0.0))
            hist[round(r, 3)] = hist.get(round(r, 3), 0) + 1
        rmax = max(hist) if hist else 0.0
        radii = sorted(r for r, n in hist.items()
                       if n >= min_faces and r <= max_ratio * rmax)
    out = []
    for r in radii:
        picked = []
        for f in usable:
            got = (abs(f.get("rad_data", 0.0)) if f["type"] == TORUS
                   else abs(f.get("radius", 0.0)))
            if abs(got - r) <= tol:
                picked.append(f)
        if not picked:
            continue
        supports = []
        for f in picked:
            cnt = {}
            for e in f.get("edges", []):
                for nt in e.get("faces", []):
                    if nt == f["tag"]:
                        continue
                    nf = by_tag.get(nt)
                    if nf is None:
                        continue
                    key = (nf["type"],
                           round(abs(nf.get("radius", 0.0)), 3),
                           round(abs(nf.get("rad_data", 0.0)), 3))
                    cnt[key] = cnt.get(key, 0) + 1
            supports.append({
                "tag": f["tag"], "type": f["type"],
                "bbox": list(f["box"]),
                "supports": ["%d/R%.3f/A%.3f x%d" % (k[0], k[1], k[2], v)
                             for k, v in sorted(cnt.items(),
                                                key=lambda kv: -kv[1])[:4]],
            })
        out.append({"radius": r, "nfaces": len(picked),
                    "bbox": _bbox_union(picked),
                    "faces": [f["tag"] for f in picked],
                    "face_supports": supports})
    return out


def _face_samples(part, face_tags, grid=3):
    """按 UV 参数采面点：中心点 + 3x3 网格。返回 {tag: (center, points)}。

    圆角面的 UV 范围可能包含修剪掉的角区；中心点始终在面上，网格点只作
    跑道长度方向的补充，不用于判定面是否存在。EvaluateFace 在 NX12 返回
    SrfPos；失败的面给空样本，不抛异常中断整表。
    """
    u = _ufs()
    out = {}
    for tag in face_tags:
        try:
            rng = [float(x) for x in u.Modeling.AskFaceUvMinmax(tag)]
        except Exception:
            out[tag] = (None, [])
            continue
        pts = []
        for i in range(grid):
            for j in range(grid):
                uv = [rng[0] + (rng[1] - rng[0]) * (i + 0.5) / grid,
                      rng[2] + (rng[3] - rng[2]) * (j + 0.5) / grid]
                try:
                    val = u.Modeling.EvaluateFace(tag, 1, uv)
                    p = [float(x) for x in val.SrfPos]
                except Exception:
                    continue
                if all(max(abs(p[k] - q[k]) for k in range(3)) > 1e-4
                       for q in pts):
                    pts.append(p)
        try:
            val = u.Modeling.EvaluateFace(
                tag, 1, [(rng[0] + rng[1]) * 0.5, (rng[2] + rng[3]) * 0.5])
            center = [float(x) for x in val.SrfPos]
        except Exception:
            center = pts[0] if pts else None
        out[tag] = (center, pts)
    return out


def _face_supports(f, by_tag):
    out = []
    seen = set()
    for e in f.get("edges", []):
        for t in e.get("faces", []):
            if t == f["tag"] or t in seen:
                continue
            s = by_tag.get(t)
            if s is not None:
                seen.add(t)
                out.append(s)
    return out


def _fillet_support(f, s, tol=0.002):
    """支撑面是否像圆角的邻面（而不是孔端面/同半径锥口）。"""
    ft = f.get("type")
    fr = abs(f.get("rad_data", 0.0)) if ft == TORUS else abs(f.get("radius", 0.0))
    st = s.get("type")
    if st in (CYLINDER, CONE, TORUS, 18):
        sr = (abs(s.get("rad_data", 0.0)) if st == TORUS
              else abs(s.get("radius", 0.0)))
        return abs(sr - fr) > max(3.0 * tol, 0.05)
    if st == PLANE:
        n = _canon(s.get("dir", [0.0, 0.0, 1.0]))
        ax = _canon(f.get("dir", [0.0, 0.0, 1.0]))
        return abs(_dot(n, ax)) < 0.5
    return False


def _face_is_fillet(f, by_tag):
    if f.get("type") not in (CYLINDER, TORUS, 18):
        return False
    supports = _face_supports(f, by_tag)
    return any(_fillet_support(f, s) for s in supports)


def fillet_run_samples(part, faces, radii, tol=0.002, grid=3,
                       fillet_only=True):
    """圆角面 → 同半径连通跑道 + UV 采样。

    与 `fillet_map` 的区别：按共享边把同半径圆角面并成连通跑道，并给每个
    面一个 UV 中心点和 3x3 样本。中心点用于跨件覆盖匹配，样本用于局部
    P95；跑道是报告单位，覆盖判定按面，不按面数比分母——同一几何换一种
    分段方式不应改变结论。

    `fillet_only=True` 时先用支撑面筛掉孔壁/凸台：孔壁的相邻平面法向沿
    孔轴，凸台两端也是端面；圆角至少有一个切向支撑（曲面，或法向垂直于
    圆角轴的平面）。
    """
    by_tag = dict((f["tag"], f) for f in faces)
    usable = [f for f in faces if f.get("type") in (CYLINDER, TORUS)]
    if fillet_only:
        usable = [f for f in usable if _face_is_fillet(f, by_tag)]
    picked = []
    for f in usable:
        got = (abs(f.get("rad_data", 0.0)) if f["type"] == TORUS
               else abs(f.get("radius", 0.0)))
        if any(abs(got - r) <= tol for r in radii):
            picked.append(f)
    by_tag = dict((f["tag"], f) for f in faces)
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    picked_tags = set(f["tag"] for f in picked)
    for f in picked:
        find(f["tag"])
        for e in f.get("edges", []):
            for t in e.get("faces", []):
                if t in picked_tags and t != f["tag"]:
                    other = by_tag.get(t)
                    if other is None:
                        continue
                    ra = (abs(other["rad_data"]) if other["type"] == TORUS
                          else abs(other["radius"]))
                    rb = (abs(f["rad_data"]) if f["type"] == TORUS
                          else abs(f["radius"]))
                    if abs(ra - rb) <= tol:
                        union(f["tag"], t)
    groups = {}
    for f in picked:
        groups.setdefault(find(f["tag"]), []).append(f)
    samples = _face_samples(part, [f["tag"] for f in picked], grid)
    runs = []
    for root, members in groups.items():
        centers = []
        pts = []
        for m in members:
            c, ps = samples.get(m["tag"], (None, []))
            if c:
                centers.append(c)
            pts.extend(ps)
        supporter = {}
        member_tags = set(m["tag"] for m in members)
        for m in members:
            for e in m.get("edges", []):
                for t in e.get("faces", []):
                    if t in member_tags:
                        continue
                    nf = by_tag.get(t)
                    if nf is None:
                        continue
                    key = "%d/R%.3f/A%.3f" % (
                        nf["type"], abs(nf.get("radius", 0.0)),
                        abs(nf.get("rad_data", 0.0)))
                    supporter[key] = supporter.get(key, 0) + 1
        runs.append({"radius": members[0].get(
            "rad_data") if members[0]["type"] == TORUS
            else members[0].get("radius"),
            "faces": [m["tag"] for m in members],
            "nfaces": len(members),
            "bbox": _bbox_union(members),
            "centers": centers, "samples": pts,
            "supports": sorted(supporter.items(),
                               key=lambda kv: -kv[1])[:6]})
    return runs


def fillet_coverage(ref_runs, built_runs, tol=0.10, run_frac=0.70,
                    radius_tol=0.025, coverage_min=0.70):
    """G7geo：参考圆角面中心 → 同半径建出面中心的最短距离。

    半径按 `radius_tol` 分池（默认 0.025 mm），不再用 0.001 mm 的字符串
    键把 0.01 mm 的合法偏差判成完全没建。返回面覆盖、跑道覆盖、逐半径
    P95 与半径误差；`pass` 要求覆盖/跑道覆盖 ≥0.70、半径误差 ≤0.025、
    P95 ≤0.10。分母是参考圆角面，不是面数比值。
    """
    pools = []
    for run in built_runs:
        pools.append({"radius": abs(float(run["radius"])),
                      "centers": list(run.get("centers", [])),
                      "samples": list(run.get("samples", []))})

    def matching(radius):
        return [p for p in pools
                if abs(p["radius"] - abs(float(radius))) <= radius_tol]

    def nearest(p, pts):
        best = 1e18
        for q in pts:
            d = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 +
                 (p[2] - q[2]) ** 2)
            if d < best:
                best = d
        return math.sqrt(best) if best < 1e18 else None

    rows = []
    hit = 0
    total = 0
    radius_errors = []
    p95_by_radius = {}
    for run in ref_runs:
        pool = matching(run["radius"])
        centers = [c for p in pool for c in p["centers"]]
        samples = [s for p in pool for s in p["samples"]]
        ds = [nearest(c, centers) for c in run.get("centers", [])] if centers else []
        good = [d for d in ds if d is not None and d <= tol]
        frac = len(good) / float(len(ds)) if ds else 0.0
        all_ds = []
        for p in run.get("samples", []):
            d = nearest(p, samples) if samples else None
            if d is not None:
                all_ds.append(d)
        all_ds.sort()
        p95 = (all_ds[min(len(all_ds) - 1,
                          int(round(0.95 * (len(all_ds) - 1))))]
               if all_ds else None)
        rerr = (min(abs(p["radius"] - abs(float(run["radius"])))
                    for p in pool) if pool else None)
        if rerr is not None:
            radius_errors.append(rerr)
        key = round(abs(float(run["radius"])), 3)
        if p95 is not None:
            p95_by_radius[key] = max(p95_by_radius.get(key, 0.0), p95)
        rows.append({"radius": run["radius"], "nfaces": run["nfaces"],
                     "bbox": run.get("bbox"), "coverage": frac,
                     "radius_error": rerr,
                     "p95": p95, "max": all_ds[-1] if all_ds else None})
        hit += len(good)
        total += len(ds)
    p95s = [r["p95"] for r in rows if r["p95"] is not None]
    p95s.sort()
    p95_max = max(p95s) if p95s else None
    radius_err_max = max(radius_errors) if radius_errors else None
    coverage = hit / float(total) if total else 0.0
    run_coverage = (sum(1 for r in rows if r["coverage"] >= run_frac) /
                    float(len(rows)) if rows else 0.0)
    ok = (bool(rows) and coverage >= coverage_min and
          run_coverage >= run_frac and radius_err_max is not None and
          radius_err_max <= radius_tol and p95_max is not None and
          p95_max <= tol)
    return {"tol": tol, "radius_tol": radius_tol,
            "coverage_min": coverage_min, "run_frac": run_frac,
            "coverage": coverage, "run_coverage": run_coverage,
            "radius_err_max": radius_err_max,
            "p95_median": (p95s[len(p95s) // 2] if p95s else None),
            "p95_max": p95_max, "p95_by_radius": p95_by_radius,
            "pass": ok, "runs": rows}


def g7_reachability(ref_runs, built_faces, radius_tol=0.025,
                    min_len_factor=0.5, ceiling_min=0.70):
    """G7 可达上限：参考圆角跑道数 / 参考圆角面数。

    一条参考跑道最多由一个解析面覆盖（`fillet_coverage` 按面 UV 中心匹配），
    所以覆盖上限就是跑道数/面数。不能拿建件边数当分子：110 特征的件有三
    千多条两面边，算出的 ceiling 恒为 1.0，把“不可达”伪装成可达。
    建件可滚边数只作诊断（恰好两面、长度 ≥ min_len_factor×R）。
    """
    groups = {}
    for run in ref_runs:
        r = abs(float(run["radius"]))
        key = None
        for k in groups:
            if abs(k - r) <= radius_tol:
                key = k
                break
        if key is None:
            key = r
            groups[key] = {"radius": r, "ref_faces": 0, "ref_runs": 0,
                           "eligible_runs": 0, "built_edges_eligible": 0,
                           "ceiling": 0.0}
        groups[key]["ref_faces"] += int(run.get("nfaces", 0))
        groups[key]["ref_runs"] += 1
    edges = []
    seen = set()
    for f in built_faces:
        for e in f.get("edges", []):
            tag = e.get("tag")
            if tag in seen:
                continue
            seen.add(tag)
            if len(e.get("faces", [])) != 2:
                continue
            ln = float(e.get("length", 0.0))
            if ln > 0.0:
                edges.append(ln)
    for g in groups.values():
        g["eligible_runs"] = g["ref_runs"]
        g["built_edges_eligible"] = sum(
            1 for ln in edges if ln >= min_len_factor * g["radius"])
        g["ceiling"] = (min(1.0, g["ref_runs"] / float(g["ref_faces"]))
                        if g["ref_faces"] else 0.0)
    ceilings = [g["ceiling"] for g in groups.values()]
    ceiling = min(ceilings) if ceilings else 1.0
    # `evidence` is the only thing that may set BLOCKED: an empty list means the
    # ceiling ratio is a diagnostic, not a verdict.  Per-runway unreachability
    # (support width below 2R+0.5, dihedral outside 20-160 deg, or an edge that
    # a previous blend consumed) is filled in by the transition planner
    # (references/reverse-engineering.md section 9); the ratio alone cannot
    # prove a runway unreachable.
    return {
        "groups": sorted(groups.values(), key=lambda r: -r["ref_faces"]),
        "ceiling": ceiling,
        "ceiling_min": ceiling_min,
        "min_len_factor": min_len_factor,
        "ceiling_basis": ("reference fillet runs / reference fillet faces "
                          "(diagnostic only)"),
        "blocked": False,
        "evidence": [],
        "eligible_edges_total": len(edges),
        "edge_length_min": min(edges) if edges else None,
    }


def _edge_vertices(edge):
    try:
        return [(float(v.X), float(v.Y), float(v.Z))
                for v in edge.GetVertices()]
    except Exception:
        return []


def g4_blocked_reason(part, axis_index, side, delta, limit,
                      corner_radius=3.175):
    """G4 不可达证据：极值顶点是否落在三面短边锐角上。

    只有当极值点同时邻接 ≥3 个面、最短邻边小于 0.5×R 时才记 BLOCKED；
    否则返回 blocked=False，让调用方继续判 FAIL。`projection_reduction_mm`
    是滚边能带来的包盒降低量；短边小于 0.5R 时按 0 记。
    """
    axis_names = ("x", "y", "z")
    target = float(delta)
    best = None
    for b in part.Bodies:
        for e in b.GetEdges():
            for p in _edge_vertices(e):
                v = p[axis_index]
                if side == "min":
                    score = v
                else:
                    score = -v
                if best is None or score < best[0]:
                    best = (score, p)
    if best is None:
        return {"blocked": False, "reason": "no vertices"}
    point = best[1]
    tol = 1e-3
    incident = []
    face_tags = set()
    for b in part.Bodies:
        for e in b.GetEdges():
            vs = _edge_vertices(e)
            if not any(math.sqrt(sum((q[k] - point[k]) ** 2
                                     for k in range(3))) <= tol for q in vs):
                continue
            try:
                length = float(e.GetLength())
            except Exception:
                length = 0.0
            tags = [int(f.Tag) for f in e.GetFaces()]
            face_tags.update(tags)
            incident.append({"edge": int(e.Tag), "length": length,
                             "faces": tags})
    min_edge = min([x["length"] for x in incident]) if incident else None
    normals = []
    u = _ufs()
    for tag in face_tags:
        try:
            d = u.Modeling.AskFaceData(tag)
            if int(d[0]) == PLANE:
                normals.append((tag, [float(x) for x in d[2]]))
        except Exception:
            continue
    angles = []
    for i in range(len(normals)):
        for j in range(i + 1, len(normals)):
            n0 = _canon(normals[i][1])
            n1 = _canon(normals[j][1])
            angles.append(round(math.degrees(math.acos(
                max(-1.0, min(1.0, abs(_dot(n0, n1)))))), 3))
    short = min_edge is not None and min_edge < 0.5 * corner_radius
    blocked = len(face_tags) >= 3 and short
    return {
        "blocked": blocked,
        "axis": axis_names[axis_index],
        "side": side,
        "delta_mm": target,
        "limit_mm": limit,
        "vertex": list(point),
        "faces": sorted(face_tags),
        "edge_lengths": [x["length"] for x in incident],
        "min_edge_mm": min_edge,
        "corner_radius_mm": corner_radius,
        "dihedral_angles_deg": angles,
        "projection_reduction_mm": 0.0 if blocked else None,
        "reason": ("three-face corner with adjacent edge <0.5R"
                   if blocked else "no three-face short-edge corner"),
    }


def _is_default_feature_name(name):
    """NX 自动特征名（`Extrude(3)` / `Revolve(1)` / `Boss(2)`）。

    这类名字不带结构 id，且空名同样是"没有结构归属"。只数特征总数的 G9
    会放过一整套默认名的 extrude 栈。
    """
    if not name:
        return True
    nm = name.strip()
    if not nm.endswith(")"):
        return False
    i = nm.rfind("(")
    if i <= 0:
        return False
    head = nm[:i]
    digits = nm[i + 1:-1]
    if not digits.isdigit():
        return False
    return head.replace("_", "").replace(" ", "").isalpha()


def g9_structure(part, structures, feature_factor=4.0, feature_offset=12,
                 type_share=0.50, max_depth=8, min_features_share=8):
    """G9 特征树结构：特征数/结构数同量级，禁止逐层截面站栈。

    `structures` 可以是结构数（int，调用方自证）或冻结结构表（list of
    {id,...}/`schema_skeleton` 的 dict）。给表时每个结构 id 必须至少有一个
    以该 id 开头的特征名，且特征不得为空名——只报特征数的 G9 会放过“74 个
    无名 extrude”的交付件。
    """
    ids = []
    source = "caller-int"
    if isinstance(structures, dict):
        ids = [s.get("id") for s in (structures.get("structures") or [])
               if s.get("id")]
        n_structures = len(ids)
        source = "structure_table"
    elif isinstance(structures, (list, tuple)):
        ids = [s.get("id") for s in structures
               if isinstance(s, dict) and s.get("id")]
        n_structures = len(ids)
        source = "structure_table"
    else:
        n_structures = int(structures)
    feats = list(part.Features)
    by_type = {}
    parents = {}
    names = []
    unnamed = []
    default_named = []
    for f in feats:
        try:
            typ = str(f.FeatureType)
        except Exception:
            typ = "?"
        by_type[typ] = by_type.get(typ, 0) + 1
        try:
            parents[int(f.Tag)] = [int(p.Tag) for p in f.GetParents()]
        except Exception:
            parents[int(f.Tag)] = []
        try:
            nm = f.Name or ""
        except Exception:
            nm = ""
        names.append(nm)
        if not nm.strip():
            unnamed.append(int(getattr(f, "Tag", 0)))
        elif _is_default_feature_name(nm):
            default_named.append(int(getattr(f, "Tag", 0)))
    memo = {}

    def depth(tag, stack):
        if tag in memo:
            return memo[tag]
        if tag in stack:
            return 0
        stack.add(tag)
        ps = parents.get(tag, [])
        d = 0 if not ps else 1 + max(depth(p, stack) for p in ps)
        stack.discard(tag)
        memo[tag] = d
        return d

    max_depth_seen = 0
    for f in feats:
        max_depth_seen = max(max_depth_seen, depth(int(f.Tag), set()))
    feature_count = len(feats)
    max_type = max(by_type.values()) if by_type else 0
    max_share = max_type / float(feature_count) if feature_count else 0.0
    station_types = ("EXTRUDE", "REVOLVE", "LOFT", "THROUGH_CURVES",
                     "SWEEP", "SWEPT")
    station_like = sum(n for t, n in by_type.items()
                       if any(t.upper().startswith(x) for x in station_types))
    limit = feature_factor * float(n_structures) + feature_offset
    station_stack = (feature_count > 24 and
                     station_like > 0.5 * feature_count)
    unmapped = [sid for sid in ids
                if not any(nm.startswith(sid) for nm in names)]
    reasons = []
    if feature_count > limit:
        reasons.append("features %d > %.1f" % (feature_count, limit))
    if feature_count >= min_features_share and max_share > type_share:
        reasons.append("max type share %.2f > %.2f" % (max_share, type_share))
    if max_depth_seen > max_depth:
        reasons.append("tree depth %d > %d" % (max_depth_seen, max_depth))
    if station_stack:
        reasons.append("station-like features %d/%d" %
                       (station_like, feature_count))
    if unnamed:
        reasons.append("%d features have empty names" % len(unnamed))
    elif feature_count >= min_features_share and \
            len(default_named) == feature_count:
        reasons.append("all %d features carry NX default names (no structure "
                       "mapping)" % feature_count)
    if unmapped:
        reasons.append("structures without a named feature: %s"
                       % ",".join(unmapped))
    return {
        "feature_count": feature_count,
        "structure_count": int(n_structures),
        "structure_count_source": source,
        "structure_ids": ids,
        "feature_limit": limit,
        "ratio": (feature_count / float(n_structures)
                  if n_structures else None),
        "max_type_share": max_share,
        "max_type": max(by_type, key=by_type.get) if by_type else None,
        "min_features_share": min_features_share,
        "station_like": station_like,
        "tree_depth": max_depth_seen,
        "types": by_type,
        "unnamed": unnamed,
        "default_named_count": len(default_named),
        "unmapped_structures": unmapped,
        "reasons": reasons,
        "pass": not reasons,
    }


def _exact_section_impl(part, origin, normal, tolerance, samples, body):
    ufs = _ufs()
    bodies = [body] if body is not None else list(part.Bodies)
    if not bodies:
        raise ValueError("part has no solid body")
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
    tol = float(tolerance)
    try:
        feat = ufs.Curve.SectionFromPlanes(gd, pd)
    except Exception:
        if tol >= 0.05:
            raise
        tol = 0.05
        gd.Tolerance = tol
        feat = ufs.Curve.SectionFromPlanes(gd, pd)
    _n, tags = ufs.Curve.AskFeatureCurves(feat)
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
    return {"origin": [float(v) for v in origin],
            "normal": _unit(normal),
            "curves": curves,
            "loops": loops,
            "open": len(open_gaps),
            "open_gaps": open_gaps}


def exact_section(part, origin, normal, tolerance=0.01, samples=65,
                  body=None):
    """B-rep 截面曲线（UF SectionFromPlanes），按端点串成闭环。

    返回每个原始段的三维采样点与按端点聚类的闭环；闭合环带绝对面积。
    每个环带 `gap`（首尾距离），`open_gaps` 汇总未闭环的缺口；缺口大于
    容差是真实开口/槽，不是拟合误差，不要靠放宽容差把它闭合成实体。
    0.01 mm 切不出时回退到 0.05 mm；无论成功/异常，临时截面特征和基准面
    都按 undo mark 回滚，不留在内存部件里。
    """
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                               "exact_section")
    try:
        return _exact_section_impl(part, origin, normal, tolerance, samples,
                                   body)
    finally:
        try:
            session.UndoToMark(mark, None)
        finally:
            try:
                session.DeleteUndoMark(mark, None)
            except Exception:
                pass


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
        "invalid_faces": sum(1 for f in faces if f.get("invalid")),
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
    """组轴向 1/3、2/3 截面上，组半径处是否有被外环包住的内环。

    返回 True/False/None：None 表示两个截面都没能量出来（不能当成“没有
    内环”），由 `hole_audit` 记入 unclassified，避免分母静默漏组。
    """
    d = group["axis"]
    p0 = group["point"]
    lo, hi = group["extent"]
    r0 = group["radius"]
    tan = math.tan(math.radians(group.get("half_angle_deg", 0.0)))
    ra, rb = r0 + tan * lo, r0 + tan * hi
    rmin, rmax = min(ra, rb), max(ra, rb)
    tol_r = max(0.01 * max(abs(rmin), abs(rmax), 1.0), 0.05)
    measured = 0
    for frac in (1.0 / 3.0, 2.0 / 3.0):
        t = lo + (hi - lo) * frac
        origin = [p0[k] + d[k] * t for k in range(3)]
        try:
            sec = exact_section(part, origin, d)
        except Exception:
            continue
        measured += 1
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
    return False if measured else None


def functional_hole_groups(measure, part):
    """圆柱/锥组中的功能孔：凹面，且轴向截面在组半径处出现内环。

    内环是被外轮廓包住的闭合环——孔壁/沉孔在截面里是独立整圆；内圆角、
    凸台、外轮廓转角在截面里只是外轮廓的一段弧，不产生内环。原件没有
    功能孔时 G2 记 N/A，不要求为了过门强行建这些结构。
    """
    return [g for g in measure["cylinders"] + measure["cones"]
            if g.get("concave") and _inner_ring(part, g) is True]


def _global_interval(group):
    """组的轴向区间（全局坐标）：point 是区间原点。"""
    base = _dot(group["point"], group["axis"])
    return base + group["extent"][0], base + group["extent"][1]


def _same_hole_axis(a, b, axis_tol_deg=1.0):
    ang = math.degrees(math.acos(
        min(1.0, abs(_dot(a["axis"], b["axis"])))))
    if ang > axis_tol_deg:
        return False
    return _perp_dist(a["center"], b["center"], a["axis"]) <= max(
        2.0 * max(abs(a["radius"]), abs(b["radius"])) + 2.0, 2.0)


def _interval_touch(a, b, gap=1.0):
    alo, ahi = _global_interval(a)
    blo, bhi = _global_interval(b)
    return min(ahi, bhi) - max(alo, blo) >= -gap


def hole_audit(measure, part):
    """G2 分母审计：功能孔 + 独立锥孔 + 未分类凹面组。

    `functional_hole_groups` 只收“凹面且截面有内环”的组，截面退化时会漏
    掉锥孔/盲孔。这里把同一根轴上的锥面先并到功能孔的口部（mouth_cone），
    没有对应圆柱的锥组记 tapered_hole（独立锥孔，必须计入 G2 分母），
    其余凹面圆柱/锥组记 unclassified（必须人工说明，不能静默丢掉）。
    """
    all_groups = list(measure.get("cylinders", [])) + \
        list(measure.get("cones", []))
    functional = functional_hole_groups(measure, part)
    functional_tags = set()
    for g in functional:
        functional_tags.update(g["faces"])
    mouth = []
    tapered = []
    unclassified = []
    for g in all_groups:
        if set(g["faces"]) & functional_tags:
            continue
        if g["kind"] == CONE:
            host = None
            for f in functional:
                if _same_hole_axis(g, f) and _interval_touch(g, f):
                    host = f
                    break
            rec = {"radius": g["radius"], "axis": g["axis"],
                   "center": g["center"], "length": g["length"],
                   "faces": g["faces"]}
            if host is not None:
                rec["attached_faces"] = host["faces"]
                mouth.append(rec)
            else:
                tapered.append(rec)
        elif g.get("concave"):
            ring = _inner_ring(part, g)
            rec = {"radius": g["radius"], "axis": g["axis"],
                   "center": g["center"], "length": g["length"],
                   "faces": g["faces"], "inner_ring": ring}
            if ring is True:
                functional.append(g)
                functional_tags.update(g["faces"])
            else:
                unclassified.append(rec)
    denominator = list(functional) + list(tapered)
    return {
        "functional": functional,
        "mouth_cones": mouth,
        "tapered_holes": tapered,
        "unclassified": unclassified,
        "all_groups": len(all_groups),
        "denominator": denominator,
        "total": len(denominator),
        "audit_total": len(denominator) + len(unclassified),
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
        seg_ok = True
        if kind == CONE:
            ok = ok and dha <= half_angle_tol
        else:
            ok = ok and abs(q["length"] - o["length"]) <= length_tol
            seg_ok = _segments_cover_match(o, q, length_tol)
            ok = ok and seg_ok
        out.append({
            "a": i, "b": j,
            "delta_radius": q["radius"] - o["radius"],
            "delta_length": q["length"] - o["length"],
            "delta_center": cd,
            "delta_axis_deg": ang,
            "delta_half_angle_deg": dha,
            "segments_match": seg_ok,
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
    out["segments"] = [{"faces": list(s.get("faces", [])),
                        "extent": [s["extent"][0] * scale,
                                   s["extent"][1] * scale],
                        "length": s["length"] * scale}
                       for s in group.get("segments", [])]
    out["ends"] = [(tag, t * scale) for tag, t in group.get("ends", [])]
    return out


def _merged_spans(segments):
    """同半径面段的轴向覆盖（合并重叠/相接区间）；缺 extent 时返回 None。"""
    spans = []
    for s in segments:
        ext = s.get("extent")
        if not ext or len(ext) != 2:
            return None
        lo, hi = float(ext[0]), float(ext[1])
        if hi < lo:
            lo, hi = hi, lo
        spans.append((lo, hi))
    spans.sort()
    out = []
    for lo, hi in spans:
        if out and lo <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _segments_cover_match(group_a, group_b, tol):
    """比同半径圆柱的绝对轴向覆盖，不比分段数、不按组原点平移。

    组的 extent 以各自 point 为原点，两侧 point 可能取在不同面上；先加
    `dot(point, axis)` 换到绝对轴向坐标。原件把一根圆柱按缝合边拆成两段、
    建件是一整面时，合并后覆盖相同；分界位置差 >tol 才是结构差。
    """
    segs_a = group_a.get("segments", [])
    segs_b = group_b.get("segments", [])
    if not segs_a or not segs_b:
        return True
    ma = _merged_spans(segs_a)
    mb = _merged_spans(segs_b)
    if ma is None or mb is None:
        la = sorted(s.get("length", 0.0) for s in segs_a)
        lb = sorted(s.get("length", 0.0) for s in segs_b)
        return (len(la) == len(lb) and
                all(abs(x - y) <= tol for x, y in zip(la, lb)))
    ax = group_a.get("axis") or [0.0, 0.0, 1.0]
    pa = group_a.get("point") or [0.0, 0.0, 0.0]
    pb = group_b.get("point") or [0.0, 0.0, 0.0]
    da = sum(float(pa[i]) * float(ax[i]) for i in range(3))
    db = sum(float(pb[i]) * float(ax[i]) for i in range(3))
    ma = [(lo + da, hi + da) for lo, hi in ma]
    mb = [(lo + db, hi + db) for lo, hi in mb]
    if len(ma) != len(mb):
        return False
    return all(abs(a0 - b0) <= tol and abs(a1 - b1) <= tol
               for (a0, a1), (b0, b1) in zip(ma, mb))


def _group_matches(g, ref, radius_tol, center_tol, axis_tol_deg):
    if g.get("kind") != ref.get("kind"):
        return False
    if abs(g["radius"] - ref["radius"]) > 2.0 * radius_tol:
        return False
    ang = math.degrees(math.acos(
        min(1.0, abs(_dot(g["axis"], ref["axis"])))))
    if ang > axis_tol_deg:
        return False
    cd = _perp_dist(g["center"], ref["center"], g["axis"])
    return cd <= max(center_tol, 2.0 * radius_tol)


def _subset_by_geometry(groups, ref, scale, radius_tol, center_tol,
                        axis_tol_deg):
    """按几何键筛组；返回 (命中的组, 没找到对应组的 ref)。

    不按 faces tag 做集合：面 tag 随重建顺序变化，tag 顺序一变就 N/A 是
    假通过。没找到的 ref 由调用方补进原件侧，交给 `_match_groups` 记
    unmatched_a。
    """
    if ref is None:
        return groups, []
    hit = []
    missing = []
    for r in ref:
        rr = _scale_group(r, scale)
        found = [g for g in groups
                 if _group_matches(g, rr, radius_tol, center_tol,
                                   axis_tol_deg)]
        if found:
            for g in found:
                if g not in hit:
                    hit.append(g)
        else:
            missing.append(r)
    return hit, missing


def compare_parts(path_a, path_b, radius_tol=0.025, center_tol=0.05,
                  axis_tol_deg=0.1, length_tol=0.1, half_angle_tol=0.1,
                  ref_a=None, ref_b=None, audit_a=None, audit_b=None):
    """原件/自建件的 G2 口径比对（长度容差按毫米，组先换算单位）。

    匹配条件：半径差 ≤2×radius_tol、轴角 ≤axis_tol_deg、孔心（垂直于轴的
    平面内）≤center_tol。逐项判定：圆柱看半径/孔心/轴/长度/分段，圆锥再加
    半角。`pass` 要求原件功能组没有未匹配项且每个 pair 都过阈值；
    `unmatched_a` 是“原件有、自建件没有”的结构，必须逐项建或写入简化清单；
    `strict_pass` 才要求双向都无未匹配项，`unmatched_b`（多出的圆角/凸台）
    只作复核。

    ref_a/ref_b 传入上一轮 measure_part 的组列表作为比对清单；不传时用
    `hole_audit` 的分母（功能孔 + 独立锥孔），不是只按 `_inner_ring` 筛的
    功能孔。筛选按几何键，不按 faces tag；ref 里有、建件里找不到的组会
    补进原件侧并记 unmatched_a，不会因为 tag 顺序变化变成 N/A。

    `applicable=False` 只在 ref_a 显式为空或原件确实没有孔时成立；此时
    `pass` 为 True，报告按 `verdict` 写 N/A 而不是通过。
    """
    a = measure_part(path_a)
    b = measure_part(path_b)
    if audit_a is None:
        audit_a = hole_audit(a, open_part(path_a))
    if audit_b is None:
        audit_b = hole_audit(b, open_part(path_b))
    if ref_a is None:
        ref_a = audit_a["denominator"]
    if ref_b is None and ref_a is not None:
        ref_b = ref_a
    ref_a = list(ref_a or [])
    ref_b = list(ref_b or [])
    ref_a_cyl = [r for r in ref_a if r.get("kind") == CYLINDER]
    ref_a_con = [r for r in ref_a if r.get("kind") == CONE]
    ref_b_cyl = [r for r in ref_b if r.get("kind") == CYLINDER]
    ref_b_con = [r for r in ref_b if r.get("kind") == CONE]

    a_cyl, miss_a_cyl = _subset_by_geometry(
        a["cylinders"], ref_a_cyl, a["length_scale"], radius_tol, center_tol,
        axis_tol_deg)
    a_con, miss_a_con = _subset_by_geometry(
        a["cones"], ref_a_con, a["length_scale"], radius_tol, center_tol,
        axis_tol_deg)
    b_cyl, miss_b_cyl = _subset_by_geometry(
        b["cylinders"], ref_b_cyl, b["length_scale"], radius_tol, center_tol,
        axis_tol_deg)
    b_con, miss_b_con = _subset_by_geometry(
        b["cones"], ref_b_con, b["length_scale"], radius_tol, center_tol,
        axis_tol_deg)
    a_cyl = list(a_cyl) + [_scale_group(r, a["length_scale"])
                           for r in miss_a_cyl]
    a_con = list(a_con) + [_scale_group(r, a["length_scale"])
                           for r in miss_a_con]
    if ref_b:
        b_cyl = list(b_cyl) + [_scale_group(r, b["length_scale"])
                               for r in miss_b_cyl]
        b_con = list(b_con) + [_scale_group(r, b["length_scale"])
                               for r in miss_b_con]
    cyl = _match_groups(a_cyl, b_cyl, CYLINDER, radius_tol, center_tol,
                        axis_tol_deg, length_tol, half_angle_tol)
    cones = _match_groups(a_con, b_con, CONE, radius_tol, center_tol,
                          axis_tol_deg, length_tol, half_angle_tol)
    applicable = bool(ref_a)
    groups_pass = (not cyl["unmatched_a"] and not cones["unmatched_a"] and
                   all(p["pass"] for p in cyl["pairs"] + cones["pairs"]))
    missing = [{"kind": r["kind"], "radius": r["radius"],
                "axis": list(r["axis"]), "center": list(r["center"]),
                "length": r["length"], "faces": list(r["faces"])}
               for r in miss_a_cyl + miss_a_con]
    return {
        "a": {"path": a["path"], "units": a["units"],
              "length_scale": a["length_scale"],
              "volume": a["volume"],
              "bodies": a["bodies"], "features": a["features"],
              "invalid_faces": a.get("invalid_faces", 0)},
        "b": {"path": b["path"], "units": b["units"],
              "length_scale": b["length_scale"],
              "volume": b["volume"],
              "bodies": b["bodies"], "features": b["features"],
              "invalid_faces": b.get("invalid_faces", 0)},
        "delta_volume": b["volume"] - a["volume"],
        "delta_volume_ratio": ((b["volume"] - a["volume"]) / a["volume"]
                               if a["volume"] else 0.0),
        "cylinders": cyl,
        "cones": cones,
        "applicable": applicable,
        "verdict": ("N/A" if not applicable else
                    ("PASS" if groups_pass else "FAIL")),
        "pass": groups_pass if applicable else True,
        "strict_pass": applicable and cyl["pass"] and cones["pass"],
        "ref_count": len(ref_a),
        "missing_groups": missing,
        "audit": {
            "a": {"functional": len(audit_a.get("functional", [])),
                  "tapered_holes": len(audit_a.get("tapered_holes", [])),
                  "mouth_cones": len(audit_a.get("mouth_cones", [])),
                  "unclassified": len(audit_a.get("unclassified", [])),
                  "total": audit_a.get("total", 0),
                  "audit_total": audit_a.get("audit_total", 0)},
            "b": {"functional": len(audit_b.get("functional", [])),
                  "tapered_holes": len(audit_b.get("tapered_holes", [])),
                  "mouth_cones": len(audit_b.get("mouth_cones", [])),
                  "unclassified": len(audit_b.get("unclassified", [])),
                  "total": audit_b.get("total", 0),
                  "audit_total": audit_b.get("audit_total", 0)},
        },
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
    return section_iou_pre(section_outline(mesh_a, origin, normal, weld),
                           mesh_b, origin, normal, step=step, weld=weld)


def section_iou_pre(oa, mesh_b, origin, normal, step=None, weld=1e-4):
    """同上，但基准侧轮廓由调用方预先算好。

    整件穿透筛查拿同一份基准网格、同一批站重复几十条参数；`section_iou`
    每条参数都把基准侧重切一遍，在 366 站 × 24k 三角面上是纯重复计算。
    基准侧轮廓按站固定，算一次即可复用。
    """
    ob = section_outline(mesh_b, origin, normal, weld)
    us, vs = [], []
    for out in (oa, ob):
        for loop in out["loops"]:
            for u, v in loop["pts"]:
                us.append(u)
                vs.append(v)
    if not us:
        # Neither side produced a loop.  IoU is undefined, not 1.0: an
        # empty/empty raster used to report a perfect match and pass a gate.
        return {"iou": None,
                "area_a": oa["area"], "area_b": ob["area"],
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0,
                "empty_a": not oa["loops"], "empty_b": not ob["loops"],
                "both_empty": True}
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
        "iou": ((area_inter / area_union) if area_union > 0.0 else None),
        "area_a": oa["area"],
        "area_b": ob["area"],
        "area_inter": area_inter,
        "area_union": area_union,
        "step": step,
        "empty_a": not oa["loops"],
        "empty_b": not ob["loops"],
        "both_empty": False,
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
        key = view.lower()
        if key == "iso":
            view = (1.0, 1.0, 1.0)
            e1, e2 = _basis(view)
            iu, iv = e1, e2
            nrm = _unit(view)
        else:
            try:
                iu, iv = _VIEWS[key]
            except KeyError:
                raise ValueError("unknown view %r; use top/front/side/iso "
                                 "or a normal vector" % (view,))
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
        return {"iou": 0.0, "area_a": 0.0, "area_b": 0.0,
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0,
                "empty": True}
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
    `dropped>0` 是预算截断（采样范围，不是几何剔除），complete=False。
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
        "complete": dropped == 0 and bool(clean),
    }


def _coplanar_faces(mesh, origin, normal, tol=1e-6):
    """网格里与切平面共面的三角面数：分辨"空截面"是共面伪影还是真空。

    STL 截面按"三角面跨过切平面"求交，共面三角面（三个顶点都落在平面上）
    既不跨过也不产生交线；面表平面站正好落在原件某个平面面上，于是量成
    空截面，而原件在该站其实有材料。这个计数只用于给空站分类，不参与
    形状判定。
    """
    n = _canon(normal)
    off = _dot(origin, n)
    cnt = 0
    for _, v0, v1, v2 in mesh:
        if (abs(_dot(v0, n) - off) <= tol and
                abs(_dot(v1, n) - off) <= tol and
                abs(_dot(v2, n) - off) <= tol):
            cnt += 1
    return cnt


def _material_side(faces, sources, normal):
    """平面站的材料侧：共面平面面的**外法向反向**就是材料侧。

    面表给的外法向背离材料，所以沿站位法向的偏移方向 = -外法向；站表源是
    `plane#k`（k 为面表里第 k 个平面面）。多个源面共面而方向不一致（薄壁两
    侧）、源面缺失或与站位法向不平行时返回 None，交回截面积判据。
    """
    if not faces:
        return None
    dirs = [f.get("dir") for f in faces if f.get("type") == PLANE]
    sign = None
    for s in sources:
        t = str(s)
        if not t.startswith("plane#"):
            continue
        try:
            k = int(t.split("#", 1)[1])
        except ValueError:
            return None
        if k < 0 or k >= len(dirs) or dirs[k] is None:
            return None
        d = _dot(dirs[k], normal)
        if abs(d) < 1e-6:
            return None
        cand = -1.0 if d > 0.0 else 1.0
        if sign is None:
            sign = cand
        elif sign != cand:
            return None
    return sign


def cut_stations(orig_mesh, plan, depth=SECTION_CUT_DEPTH, faces=None):
    """判定口径的切站：平面站与轴站都沿法向偏移 `depth`（默认 13.7 µm）。

    平面站与模型平面共面时 STL 求交会漏算/重算三角面，所以平面站必须离开
    面一个亚毫米量级；偏移是测量手段、不是几何事实，因此每站记
    `coplanar/offset_mm/offset_dir/offset_basis`，报告里能看出这一站不是
    名义截面、以及偏移方向凭什么定。

    偏移方向优先取几何事实：共面平面面的外法向反向（`offset_basis=
    "face_normal"`，需要 `faces` 面表）；面表缺失或源面方向冲突时退回原件
    截面积更大的那一侧（`offset_basis="section_area"`，只看原件）。
    """
    stations = plan["stations"] if isinstance(plan, dict) else plan
    cut = []
    for st in stations:
        origin = [float(x) for x in st["origin"]]
        normal = _unit(st["normal"])
        coplanar = st.get("kind") == "plane"
        sign = 1.0
        basis = None
        if coplanar:
            side = _material_side(faces, st.get("sources", []), normal)
            if side is not None:
                sign = side
                basis = "face_normal"
            else:
                plus = [o + depth * n for o, n in zip(origin, normal)]
                minus = [o - depth * n for o, n in zip(origin, normal)]
                a1 = section_area(orig_mesh, plus, normal)
                a2 = section_area(orig_mesh, minus, normal)
                sign = 1.0 if a1 >= a2 else -1.0
                basis = "section_area"
        cut.append({
            "origin": [o + sign * depth * n for o, n in zip(origin, normal)],
            "normal": list(normal),
            "sources": list(st.get("sources", [])),
            "kind": st.get("kind"),
            "sign": sign,
            "depth": depth,
            "coplanar": coplanar,
            "offset_mm": depth,
            "offset_dir": sign,
            "offset_basis": basis,
        })
    return cut


def cut_plan(orig_mesh, plan, depth=SECTION_CUT_DEPTH, faces=None):
    """切站后的站表，保留原站表的预算/覆盖字段（`dropped`/`missing`）。

    `station_report` 读 `dropped` 判 `plan_complete`；重造站表时丢掉这个
    字段会把预算截断洗成"覆盖完整"。
    """
    base = dict(plan) if isinstance(plan, dict) else {"stations": plan}
    base["stations"] = cut_stations(orig_mesh, plan, depth, faces)
    base.setdefault("dropped", 0)
    return base


def station_report(mesh_a, mesh_b, plan, iou_min=0.95,
                   area_err_max_pct=5.0, progress=None):
    """逐站截面 IoU / 面积差 / 缺料与多料面积；plan 取 station_plan 的返回值。

    `only_a` 是原件有、自建件缺的面积，`only_b` 是自建件多出的面积
    （单位随网格）。面积差只能说明总量，修结构时按 `only_a/only_b` 区分
    漏建与过建。

    每站四态：两侧截面都空 → `status="N/A"`（该站没有读数，既不判 PASS
    也不判 FAIL），并给出 `na_reason`：

    - `coplanar_section`：切平面与原件某个平面面共面，原件在那里**有材料**
      但 STL 求交看不到交线 —— 这是仪器限制，站表不能拿它当"没材料"；
    - `no_material`：剖面附近没有任何共面三角面，原件在该站确实没有材料 ——
      站位落在材料空档里，是站表噪声（如同轴组各面之间的空段），不进分母。

    判定口径的站表用 `cut_plan`（平面站与轴站都沿法向偏 13.7 µm、方向取
    材料侧）生成；直接拿名义站位切，平面站会落进 `coplanar_section`。
    `progress(i, n, mode)` 可选：逐站回调（长跑时打进度，避免看起来像卡死）。

    `pass` 只回答"有读数的站里有没有 FAIL"；`plan_measured_complete` 回答
    "原件有材料的站是否都量到了"（即无 `instrument_errors` 且未截断）；
    `plan_noise` 单列站位空档。判定链（`verify_parts` 的 G1、
    `audit.g1full`）按这两条分别处理，空站不会静默变成 PASS，也不会把
    不可达的站位算成必须通过。
    """
    stations = plan["stations"] if isinstance(plan, dict) else plan
    dropped = plan.get("dropped", 0) if isinstance(plan, dict) else 0
    rows = []
    failed = []
    na = []
    for i, st in enumerate(stations):
        if progress is not None:
            progress(i, len(stations), "stl")
        res = section_iou(mesh_a, mesh_b, st["origin"], st["normal"])
        aa, ab = res["area_a"], res["area_b"]
        if abs(aa) > 1e-9:
            err = abs(ab - aa) / abs(aa) * 100.0
        else:
            err = 0.0 if abs(ab) <= 1e-9 else 100.0
        na_reason = None
        if res.get("both_empty"):
            status = "N/A"
            ok = False
            na_reason = ("coplanar_section"
                         if _coplanar_faces(mesh_a, st["origin"],
                                            st["normal"]) else "no_material")
        else:
            ok = (res["iou"] is not None and res["iou"] >= iou_min and
                  err <= area_err_max_pct)
            status = "PASS" if ok else "FAIL"
        rows.append({
            "index": i,
            "origin": list(st["origin"]),
            "normal": list(st["normal"]),
            "sources": list(st.get("sources", [])),
            "kind": st.get("kind"),
            "section_mode": "stl",
            "coplanar": st.get("coplanar"),
            "offset_mm": st.get("offset_mm"),
            "offset_dir": st.get("offset_dir"),
            "offset_basis": st.get("offset_basis"),
            "iou": res["iou"],
            "area_a": aa,
            "area_b": ab,
            "area_inter": res["area_inter"],
            "area_union": res["area_union"],
            "only_a": max(0.0, aa - res["area_inter"]),
            "only_b": max(0.0, ab - res["area_inter"]),
            "area_err_pct": err,
            "status": status,
            "na_reason": na_reason,
            "pass": ok,
        })
        if status == "FAIL":
            failed.append(i)
        elif status == "N/A":
            na.append(i)
    coplanar = [r["index"] for r in rows
                if r["na_reason"] == "coplanar_section"]
    plan_noise = [r["index"] for r in rows
                  if r["na_reason"] == "no_material"]
    reasons = []
    if not rows:
        reasons.append("no stations")
    if dropped:
        reasons.append("%d stations skipped by budget (sampling)" % dropped)
    if failed:
        reasons.append("%d stations failed" % len(failed))
    if na:
        reasons.append("%d stations unmeasured (%d coplanar plane stations, "
                       "%d no material at the station)"
                       % (len(na), len(coplanar), len(plan_noise)))
    return {
        "stations": rows,
        "count": len(rows),
        "failed": failed,
        "na": na,
        "unmeasured": list(na),
        "instrument_errors": coplanar,
        "plan_noise": plan_noise,
        "measured_count": len(rows) - len(na),
        "dropped": dropped,
        "budget_skipped": dropped,
        "plan_complete": (bool(rows) and dropped == 0),
        "plan_measured_complete": (bool(rows) and dropped == 0
                                   and not coplanar),
        "iou_min": iou_min,
        "area_err_max_pct": area_err_max_pct,
        "reasons": reasons,
        "pass": bool(rows) and not failed,
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
        return {"iou": 0.0, "area_a": 0.0, "area_b": 0.0,
                "area_inter": 0.0, "area_union": 0.0, "step": 0.0,
                "empty": True}
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
    return {"iou": (inter / union if union > 0 else None),
            "area_a": aa * step, "area_b": ab * step,
            "area_inter": inter * step, "area_union": union * step,
            "step": step, "empty": False}


def brep_section_iou(part_a, part_b, origin, normal,
                     iou_min=0.95, area_err_max_pct=5.0, allow_open=False):
    """同站 B-rep 精确截面 IoU；用于面表平面站，避免 STL 共面切面伪影。

    未闭合环默认判失败：把它们隐式闭合会掩盖真实开口/槽。确实要量开口
    轮廓时才传 `allow_open=True`，报告里仍单列 `open_a/open_b`。
    """
    sa = exact_section(part_a, origin, normal)
    sb = exact_section(part_b, origin, normal)
    ca = _polygons_iou(_exact_loops_2d(sa, origin, normal),
                       _exact_loops_2d(sb, origin, normal))
    aa, ab = ca["area_a"], ca["area_b"]
    if abs(aa) > 1e-9:
        err = abs(ab - aa) / abs(aa) * 100.0
    else:
        err = 0.0 if abs(ab) <= 1e-9 else 100.0
    open_ok = allow_open or (sa["open"] == 0 and sb["open"] == 0)
    ok = (ca["iou"] is not None and ca["iou"] >= iou_min and
          err <= area_err_max_pct and open_ok and
          not ca.get("empty", False))
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
        "open_ok": open_ok,
        "gaps_a": list(sa["open_gaps"]),
        "gaps_b": list(sb["open_gaps"]),
        "pass": ok,
    }


def station_report_hybrid(mesh_a, mesh_b, part_a, part_b, plan,
                          iou_min=0.95, area_err_max_pct=5.0,
                          progress=None):
    """逐站截面：面表平面站用 B-rep 精确截面，其余站用 STL 截面。

    这是**可选口径**，不是默认判定口径：`UF SectionFromPlanes` 把剖面按面
    边界切成开口段，闭合环要靠端点串接重建；在导入体（无特征史、面片拼接
    密集）上会返回端点本应重合却串不成环的段，`brep_section_iou` 按开口
    判失败，于是每一站平面站都 FAIL —— 这是仪器限制，不是形状不对。要用
    这个口径必须先证明它在该件上可闭合（同一件自比对全 PASS、面积与 STL
    口径一致）；判定默认走 `cut_plan` + `station_report`（STL 偏移）。

    这里把平面站换成 B-rep 读数，剩下的空站按两类处理：**仪器误差**
    （`coplanar_section`：原件有材料却没量到，B-rep 也没补上）→ 判失败；
    **站表噪声**（`no_material`：原件在该站确实没有材料）→ 从"该量到的站"
    里剔除、单列 `plan_noise`，不让它把门卡成不可达。
    `progress(i, n, mode)` 逐站回调（B-rep 站比 STL 站便宜一两个量级）。
    """
    base = station_report(mesh_a, mesh_b, plan, iou_min, area_err_max_pct,
                          progress=progress)
    rows = base["stations"]
    stations = plan["stations"] if isinstance(plan, dict) else plan
    brep_count = 0
    for row in rows:
        st = stations[row["index"]]
        if not any(str(s).startswith("plane#")
                   for s in st.get("sources", [])):
            row["section_mode"] = "stl"
            continue
        if progress is not None:
            progress(row["index"], len(rows), "brep")
        row.update(brep_section_iou(part_a, part_b, st["origin"],
                                    st["normal"], iou_min,
                                    area_err_max_pct))
        row["section_mode"] = "brep"
        # the B-rep reading replaces the STL reading for this station, so the
        # coplanar reason goes with it
        row["na_reason"] = None
        row["status"] = "PASS" if row["pass"] else "FAIL"
        brep_count += 1
    # N/A 行（没有读数）不进 `failed`：它由 instrument_errors/plan_noise 分开
    # 记账，混进失败列表会让"站位空档"看起来像形状不对。
    failed = [r["index"] for r in rows
              if not r["pass"] and r.get("status") != "N/A"]
    na = [r["index"] for r in rows if r.get("status") == "N/A"]
    coplanar = [r["index"] for r in rows
                if r.get("status") == "N/A"
                and r.get("na_reason") == "coplanar_section"]
    plan_noise = [r["index"] for r in rows
                  if r.get("status") == "N/A"
                  and r.get("na_reason") == "no_material"]
    base["stations"] = rows
    base["failed"] = failed
    base["na"] = na
    base["unmeasured"] = list(na)
    base["instrument_errors"] = coplanar
    base["plan_noise"] = plan_noise
    base["measured_count"] = len(rows) - len(na)
    base["plan_measured_complete"] = bool(rows) and not coplanar
    # B-rep rows supersede the STL rows on plane stations, so the verdict is
    # recomputed from the final rows.  ANDing with the STL verdict let a
    # coplanar STL artefact veto a station the B-rep cut judged correct.
    # No-material stations carry no information about the built part's missing
    # material (the reference has nothing there to miss), so they are excluded
    # instead of blocking -- but they are always reported.
    base["pass"] = bool(rows) and not failed and not coplanar
    base["brep_plane_count"] = brep_count
    base["stl_axis_count"] = len(rows) - brep_count
    reasons = [r for r in base["reasons"]
               if "stations failed" not in r and "stations unmeasured" not in r]
    if failed:
        reasons.append("%d stations failed" % len(failed))
    if na:
        reasons.append("%d stations unmeasured (%d coplanar plane stations, "
                       "%d no material at the station)"
                       % (len(na), len(coplanar), len(plan_noise)))
    if plan_noise:
        reasons.append("%d stations are plan noise (no reference material)"
                       % len(plan_noise))
    base["reasons"] = reasons
    return base


def _bbox_axis_delta(bb_o, bb_b):
    """包盒逐轴残差：返回 (位置最差轴, 位置 delta, 尺寸最差轴, 尺寸 delta)。"""
    pos = [abs(bb_o[i] - bb_b[i]) for i in range(6)]
    pidx = max(range(6), key=lambda i: pos[i])
    pos_axis = pidx % 3
    pos_side = "min" if pidx < 3 else "max"
    size_o = [bb_o[i + 3] - bb_o[i] for i in range(3)]
    size_b = [bb_b[i + 3] - bb_b[i] for i in range(3)]
    size = [abs(size_o[i] - size_b[i]) for i in range(3)]
    sidx = max(range(3), key=lambda i: size[i])
    side_scores = (abs(bb_o[sidx] - bb_b[sidx]),
                   abs(bb_o[sidx + 3] - bb_b[sidx + 3]))
    size_side = "min" if side_scores[0] >= side_scores[1] else "max"
    return {
        "position_axis": pos_axis, "position_side": pos_side,
        "position_delta": pos[pidx],
        "size_axis": sidx, "size_side": size_side,
        "size_delta": size[sidx],
    }


def verify_parts(orig, built, samples=4000, max_stations=48,
                 radius_tol=0.025, center_tol=0.05, axis_tol_deg=0.1,
                 length_tol=0.1, half_angle_tol=0.1,
                 volume_pct=0.1, bbox_pos_mm=0.05, bbox_size_mm=0.05,
                 view_iou_min=0.99, rms_max=0.8, p95_max=1.8,
                 section_iou_min=0.95, section_area_pct=5.0,
                 section_mode="stl",
                 ref_a=None, ref_b=None, g7="auto", g7_radii=None,
                 g7_ceiling=None, g7_transitions=False, g9=True,
                 structure_count=None,
                 g8=True, design=None, derived=None, factor=1.1,
                 g9_feature_factor=4.0, g9_feature_offset=12,
                 g9_type_share=0.50, g9_depth=8, blocked_g4=True,
                 g4_corner_radius=None):
    """原件/自建件几何门 G0–G9 一次汇总（G2–G9 长度换算到毫米）。

    G0 要求两件都是单实体且面表可读；G1 默认走 STL 截面口径（平面站与轴站
    都按 `cut_plan` 偏 13.7 µm），空站表/两侧皆空的站判失败或 N/A，
    `max_stations` 预算截断只报 `budget_skipped`/`plan_complete`，但
    `plan_complete=false` 时 G1 **不通过**（未覆盖不等于覆盖）；`section_mode`
    可选 `"brep"` 走面表平面站的 B-rep 精确截面（见 `station_report_hybrid`
    的闭合限制，仅在自己件上证明可闭合时使用）；G2 用
    `hole_audit` 的分母（功能孔 + 独立锥孔），按几何键匹配；G3–G6 按毫米
    换算；G7 默认 `auto`（参考件有环面才计算，纯圆柱半径组只进
    `unjudged_radii`，需要判圆柱圆角时显式传 `g7_radii`），状态先看可达性
    证据再判覆盖，无逐跑道证据时不记 BLOCKED；G8 逐条改命名表达式量体积
    （`design` 给了就与声明对账，missing/dead/broken 任一非空即失败）；
    G9 默认开启，结构数只能来自结构表（缺省判 FAIL，不拿
    `structure_directory` 的逐面组数当分母）。每门带
    `status: PASS|FAIL|BLOCKED|N/A`；总 `pass` 只对全 PASS（或 N/A）为真，
    `delivery_pass` 在任一 BLOCKED 时为 false。
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
    if section_mode == "brep":
        sec = station_report_hybrid(mesh_o, mesh_b, part_o, part_b, plan,
                                    section_iou_min, section_area_pct)
    elif section_mode == "stl":
        sec = station_report(mesh_o, mesh_b,
                             cut_plan(mesh_o, plan, faces=mo["faces"]),
                             section_iou_min, section_area_pct)
    else:
        raise ValueError("unknown section_mode: %r" % (section_mode,))
    sec["caliber"] = ("brep_plane" if section_mode == "brep" else "stl_offset")
    sec["cut_depth_mm"] = (None if section_mode == "brep"
                           else SECTION_CUT_DEPTH)
    if abs(so - sb) > 1e-12:
        sec = station_report(mesh_o, mesh_b, plan, section_iou_min,
                             section_area_pct)
        sec["unit_mismatch"] = True
        sec["pass"] = False
        sec["reasons"].append("unit mismatch %s vs %s" %
                              (mo["units"], mb["units"]))
    if not sec.get("plan_complete", True):
        sec["pass"] = False
        sec["status"] = "FAIL"
        sec["reasons"] = list(sec.get("reasons", [])) + [
            "station plan incomplete (%d dropped, %d instrument errors): "
            "uncovered is not covered"
            % (sec.get("dropped", 0), len(sec.get("instrument_errors", [])))]
    sec.setdefault("status", "PASS" if sec.get("pass") else "FAIL")
    audit_o = hole_audit(mo, part_o)
    audit_b = hole_audit(mb, part_b)
    if ref_a is None:
        ref_a = audit_o["denominator"]
    cmp = compare_parts(orig, built, radius_tol, center_tol, axis_tol_deg,
                        length_tol, half_angle_tol, ref_a, ref_b,
                        audit_a=audit_o, audit_b=audit_b)
    vol_pct = abs(mb["volume"] - mo["volume"]) / mo["volume"] * 100.0 \
        if mo["volume"] else 100.0
    bb_o = mesh_bbox(mesh_o_mm)
    bb_b = mesh_bbox(mesh_b_mm)
    bd = _bbox_axis_delta(bb_o, bb_b)
    pos_d = bd["position_delta"]
    size_d = bd["size_delta"]
    views = {}
    for name in ("top", "front", "side"):
        views[name] = view_iou(mesh_o_mm, mesh_b_mm, name)
    views["iso"] = view_iou(mesh_o_mm, mesh_b_mm, [1.0, 1.0, 1.0])
    views_pass = all(v["iou"] >= view_iou_min for v in views.values())
    dev = mesh_deviation(mesh_o_mm, mesh_b_mm, samples, 0,
                         rms_max, p95_max)

    ref_radii = []
    unjudged_radii = []
    if g7 != "off":
        if g7_radii is not None:
            ref_radii = sorted(set(abs(float(r)) for r in g7_radii))
        else:
            # 只有环面（type 19）的 rad_data 一定是滚球圆角半径。圆柱半径
            # 里混着孔壁/凸台/外圆，全部入账会把 G7 分母灌到几百面、上限
            # 反而变松；纯圆柱半径组只作诊断。
            torus_hist = {}
            cyl_hist = {}
            for f in mo["faces"]:
                if f.get("type") == TORUS:
                    r = round(abs(f.get("rad_data", 0.0)), 3)
                    if r > 1e-6:
                        torus_hist[r] = torus_hist.get(r, 0) + 1
                elif f.get("type") == CYLINDER:
                    r = round(abs(f.get("radius", 0.0)), 3)
                    if r > 1e-6:
                        cyl_hist[r] = cyl_hist.get(r, 0) + 1
            ref_radii = sorted(torus_hist)
            # pure cylinder radii mix bore walls, bosses and outer diameters;
            # using them as the goal radius pool let G7 judge a part against
            # its own holes.  They stay diagnostics, and cylinder-based
            # fillets must be declared through g7_radii.
            unjudged_radii = sorted(set(cyl_hist) - set(ref_radii))
    ref_runs = []
    built_runs = []
    if ref_radii:
        ref_runs = fillet_run_samples(part_o, mo["faces"], ref_radii,
                                      fillet_only=True)
        built_runs = fillet_run_samples(part_b, mb["faces"], ref_radii,
                                        fillet_only=True)
    if g7 == "off" or not ref_runs:
        g7_gate = {"status": "N/A", "pass": True, "blocked": False,
                   "ref_radii": ref_radii,
                   "unjudged_radii": unjudged_radii,
                   "reason": ("g7 off" if g7 == "off"
                              else "no reference fillet runs")}
    else:
        cov = fillet_coverage(ref_runs, built_runs, tol=0.10,
                              run_frac=0.70, radius_tol=0.025)
        reach = g7_reachability(ref_runs, mb["faces"], radius_tol=0.025)
        if g7_ceiling is not None:
            # override the reported ceiling (diagnostic) only; it does not set
            # BLOCKED, which now requires per-runway topology evidence
            reach["ceiling"] = float(g7_ceiling)
            reach["override"] = True
        ref_faces = sum(r["nfaces"] for r in ref_runs)
        built_faces = sum(r["nfaces"] for r in built_runs)
        raw_cov = built_faces / float(ref_faces) if ref_faces else 0.0
        # BLOCKED needs explicit per-runway topology evidence that a runway is
        # unreachable; the ceiling ratio alone (runs/faces) says nothing about
        # whether a correct build can cover the fillet, and scoring it as
        # BLOCKED made the reference solution itself un-passable.
        evidence = [e for e in (reach.get("evidence") or []) if e.get("reason")]
        if g7_transitions:
            # nxlib.transitions 逐跑道判可达性（支撑面宽度 / 二面角），它是
            # 唯一被允许产出 BLOCKED 证据的来源；只作 opt-in，因为它要对每个
            # 跑道读支撑面几何，整件上开销明显
            import nxlib.transitions as _tr
            tplan = _tr.transitions_plan(
                part_o, mo, radii=ref_radii,
                fillet_faces=None)
            evidence = list(tplan.get("unreachable") or [])
            reach["transitions"] = {
                "status": tplan.get("status"),
                "by_mechanism": tplan.get("by_mechanism"),
                "run_count": tplan.get("run_count"),
                "reachable_count": tplan.get("reachable_count"),
            }
        if cov["pass"]:
            status = "PASS"
        elif evidence:
            status = "BLOCKED"
        else:
            status = "FAIL"
        g7_gate = {
            "status": status, "pass": status == "PASS",
            "blocked": status == "BLOCKED",
            "geo": cov,
            "raw": {"ref_faces": ref_faces, "built_faces": built_faces,
                    "coverage": raw_cov, "note": "report only"},
            "reach": reach,
            "unreachable_evidence": evidence,
            "ref_radii": ref_radii,
            "unjudged_radii": unjudged_radii,
                "reason": ("unreachable runways with evidence: %d"
                           % len(evidence) if status == "BLOCKED" else None),
        }

    # G8: every named expression must actually drive the model, and every
    # declared design parameter must be built.  Without this gate a delivery
    # full of dead parameters or literal-value features passes G0-G7.
    if g8:
        g8_survey = expression_survey(part_b, factor=factor)
        if isinstance(design, dict):
            declared_names = []
            for nm in design.values():
                declared_names.extend(nm)
        elif isinstance(design, (list, tuple)):
            declared_names = list(design)
        else:
            declared_names = []
        named_set = set(g8_survey["named"])
        dead_set = set(g8_survey["dead"])
        skipped_set = set(g8_survey["skipped"])
        broken_set = set(b.get("name") for b in g8_survey["broken"])
        missing = [n for n in declared_names if n not in named_set]
        declared_dead = [n for n in declared_names if n in dead_set]
        declared_broken = [n for n in declared_names if n in broken_set]
        declared_skipped = [n for n in declared_names if n in skipped_set]
        g8_pass = (bool(g8_survey.get("pass", False)) and not missing and
                   not declared_dead and not declared_broken and
                   not declared_skipped)
        g8_gate = {
            "status": "PASS" if g8_pass else "FAIL", "pass": g8_pass,
            "bodies": len(list(part_b.Bodies)),
            "alerts": len(g8_survey.get("alerts") or []),
            "named": len(g8_survey["named"]),
            "alive_ratio": g8_survey.get("alive_ratio"),
            "dead": g8_survey["dead"], "broken": g8_survey["broken"],
            "skipped": g8_survey["skipped"],
            "declared": declared_names, "missing": missing,
            "declared_dead": declared_dead, "declared_broken": declared_broken,
            "declared_skipped": declared_skipped,
            "derived": list(derived or []),
        }
    else:
        g8_gate = {"status": "N/A", "pass": True, "reason": "g8 off"}

    g4_axes = []
    g4_fail = pos_d > bbox_pos_mm or size_d > bbox_size_mm
    torus_counts = {}
    for f in mo["faces"]:
        if f.get("type") == TORUS:
            r = round(abs(f.get("rad_data", 0.0)), 3)
            if r > 1e-6:
                torus_counts[r] = torus_counts.get(r, 0) + 1
    if g4_corner_radius is not None:
        corner_r = float(g4_corner_radius)
        corner_basis = "explicit"
    elif torus_counts:
        corner_r = max(torus_counts, key=torus_counts.get)
        corner_basis = "dominant reference torus radius"
    elif ref_radii:
        corner_r = max(ref_radii)
        corner_basis = "largest reference fillet radius"
    else:
        corner_r = 3.175
        corner_basis = "default 3.175"
    if pos_d > bbox_pos_mm:
        ev = g4_blocked_reason(part_b, bd["position_axis"],
                               bd["position_side"], pos_d, bbox_pos_mm,
                               corner_r)
        ev["dimension"] = "position"
        ev["corner_radius_basis"] = corner_basis
        g4_axes.append(ev)
    if size_d > bbox_size_mm:
        ev = g4_blocked_reason(part_b, bd["size_axis"], bd["size_side"],
                               size_d, bbox_size_mm, corner_r)
        ev["dimension"] = "size"
        ev["corner_radius_basis"] = corner_basis
        g4_axes.append(ev)
    g4_blocked = (bool(blocked_g4) and bool(g4_axes) and
                  all(e.get("blocked") for e in g4_axes))
    if g4_fail and g4_blocked:
        g4_status = "BLOCKED"
    elif g4_fail:
        g4_status = "FAIL"
    else:
        g4_status = "PASS"

    structures = structure_count
    directory_count = None
    if structures is None:
        sd = structure_directory(mo["faces"])
        directory_count = (len(sd["cylinders"]) + len(sd["cones"]) +
                           len(sd["torus_groups"]))
    if g9 and structures is None:
        # 结构数只能来自结构表：structure_directory 会把每个圆角面
        # 单独成组（本机实测 280 组），当分母会让 G9 永远通过。
        g9_gate = {"status": "FAIL", "pass": False,
                   "structure_count": None,
                   "directory_count": directory_count,
                   "reasons": ["structure_count required (structure table)"]}
    elif g9:
        g9_gate = g9_structure(part_b, structures,
                               feature_factor=g9_feature_factor,
                               feature_offset=g9_feature_offset,
                               type_share=g9_type_share,
                               max_depth=g9_depth)
        g9_gate["directory_count"] = directory_count
        g9_gate["status"] = "PASS" if g9_gate["pass"] else "FAIL"
    else:
        g9_gate = {"status": "N/A", "pass": True,
                   "structure_count": structures,
                   "directory_count": directory_count}

    gates = {
        "G0": {"pass": (mo["bodies"] == 1 and mb["bodies"] == 1 and
                        mo.get("invalid_faces", 0) == 0 and
                        mb.get("invalid_faces", 0) == 0 and
                        bool(mesh_o and mesh_b)),
               "bodies": [mo["bodies"], mb["bodies"]],
               "invalid_faces": [mo.get("invalid_faces", 0),
                                 mb.get("invalid_faces", 0)]},
        "G1": sec,
        "G2": cmp,
        "G3": {"pass": vol_pct <= volume_pct, "diff_pct": vol_pct,
               "limit_pct": volume_pct},
        "G4": {"pass": not g4_fail, "status": g4_status,
               "position_delta_mm": pos_d, "size_delta_mm": size_d,
               "limits_mm": [bbox_pos_mm, bbox_size_mm],
               "corner_radius_mm": corner_r,
               "corner_radius_basis": corner_basis,
               "axes": g4_axes, "blocked": g4_blocked},
        "G5": {"pass": views_pass, "views": views,
               "iou_min": view_iou_min},
        "G6": dev,
        "G7": g7_gate,
        "G8": g8_gate,
        "G9": g9_gate,
    }
    for key, gate in gates.items():
        if "status" not in gate:
            gate["status"] = "PASS" if gate.get("pass") else "FAIL"
    statuses = dict((k, g["status"]) for k, g in gates.items())
    failed = [k for k, s in statuses.items() if s == "FAIL"]
    blocked = [k for k, s in statuses.items() if s == "BLOCKED"]
    if failed:
        overall = "FAIL"
    elif blocked:
        overall = "BLOCKED"
    else:
        overall = "PASS"
    return {
        "orig": {"path": mo["path"], "units": mo["units"],
                 "length_scale": so, "volume": mo["volume"],
                 "bodies": mo["bodies"],
                 "invalid_faces": mo.get("invalid_faces", 0)},
        "built": {"path": mb["path"], "units": mb["units"],
                  "length_scale": sb, "volume": mb["volume"],
                  "bodies": mb["bodies"],
                  "invalid_faces": mb.get("invalid_faces", 0)},
        "stations": plan,
        "gates": gates,
        "status": overall,
        "statuses": statuses,
        "blocked": blocked,
        "pass": overall == "PASS",
        "delivery_pass": overall == "PASS",
    }
