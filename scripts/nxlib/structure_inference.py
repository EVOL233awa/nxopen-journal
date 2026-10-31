# -*- coding: utf-8 -*-
"""结构推断层：把只读测量编译成结构表 + 未解析清单（整件逆向的入口）。

与 `nxlib.reverse` 的分工：`reverse` 出表（候选目录、参数候选、全集站表、
跑道表），本模块**决定结构怎么分、用哪个模板、证据是哪些面**，并把无法判定
的东西显式列进 `unresolved`，而不是猜一个模板继续往下建。

边界：

- 只读：只吃 `measure` 的返回值（面表/同轴组/平面族/孔审计）与可选 `part`；
  不写表达式、不建几何、不 import `audit`（审计层反过来读这里的输出）。
- 不留零件常数：所有阈值都是通用判据（角度/半径/面积相对差），结构 id 由
  几何键顺序确定，不依赖原件命名。
- 证据优先：每行结构必须带 `evidence_faces`；只有 `unresolved` 允许没有模板。
- 确定性：同一 `measure` 两次调用逐位一致（`inference_report` 写出的 JSON
  逐字节相同）。

判据来自测量编译（`references/reverse-engineering.md` §12.1/§12.2）：

- 同轴柱/锥/环面组 → 回转体（多段半径台阶 → `revolved_profile`；单段 →
  `cylinder`/`hole_chain`）；
- 同法向 ≥2 偏置平面族 → 板/环带（`plate_2p5d`），两端截面必须同拓扑，
  否则要有拔模证据，否则 `unresolved`；
- 孔审计的功能孔 + 同轴分段 → 孔链（`hole_chain`），锥口/沉孔各自成段；
- 同一法向偏置数超过 `STACK_OFFSETS` 且没有结构解释 → 判为"平行面堆叠"
  的 `unresolved`（层号表特征树的测量指纹），不输出板模板；
- 边界弧拟合（眼/耳/叉）与沿特征轴的纵剖面（斜臂）需要面采样，只有给了
  `part` 才能判；measure-only 模式下这些结构进 `unresolved` 并给出下一步
  探针，不猜。
"""
import json
import math

import nxlib.measure as ms
import nxlib.reverse as rv

# 通用阈值（不含任何零件量值）
NORMAL_TOL_DEG = 0.5          # 平面族法向容差
OFFSET_TOL_MM = 1e-4          # 平面偏置去重容差
STACK_OFFSETS = 6             # 同一法向偏置数 ≥ 此值且无解释 → 平行面堆叠
BAND_AREA_TOL = 0.02          # 两端截面面积相对差（等截面判据）
BAND_AREA_SHARE = 0.5         # 板厚方向判据：这一对面至少占最大一对的一半
ARC_FIT_TOL_MM = 0.05         # 边界弧拟合残差上限（给出 part 时才判）
COAXIAL_TOL_DEG = 0.5         # 同轴容差

ROLE_FUNCTIONAL = "functional"
ROLE_FILLET = "fillet"
ROLE_TRANSITION = "transition"
ROLE_UNKNOWN = "unknown"


def _norm(v):
    return ms._unit([float(x) for x in v])


def _angle_deg(a, b):
    d = abs(sum(float(a[i]) * float(b[i]) for i in range(3)))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def _round(v, nd=6):
    """定量输出：-0.0 归一，定小数位（确定性 JSON 的前提）。"""
    r = round(float(v), nd)
    return 0.0 if r == 0.0 else r


def face_graph(measure, part=None, fillet_radii=None):
    """面图：类型/半径/轴/凹凸/邻接支撑，并给每面一个角色。

    角色只按通用判据分：`fillet_radii` 里出现的半径（或环面 type 19）判
    圆角面；同一轴上半径更大、包住它的柱面判支撑面；其余按类型判功能面。
    """
    radii = sorted(set(abs(float(r)) for r in (fillet_radii or [])))
    faces = []
    supports = {}
    for g in list(measure.get("cylinders", [])) + list(measure.get("cones", [])):
        for tag in g.get("faces", []):
            supports[int(tag)] = {"axis": list(g.get("axis", [])),
                                  "point": list(g.get("point", []))}
    for f in measure.get("faces", []):
        tag = int(f.get("tag", -1))
        typ = f.get("type")
        rad = abs(float(f.get("rad_data", 0.0) or 0.0))
        radius = abs(float(f.get("radius", 0.0) or 0.0))
        concave = f.get("norm_dir") == -1
        role = ROLE_FUNCTIONAL
        if typ == ms.PLANE:
            role = ROLE_FUNCTIONAL
        elif typ == ms.TORUS:
            role = ROLE_FILLET
        elif radii and any(abs(rad - r) <= 1e-6 or abs(radius - r) <= 1e-6
                           for r in radii):
            role = ROLE_FILLET
        else:
            role = ROLE_FUNCTIONAL
        rec = {
            "tag": tag,
            "type": typ,
            "radius": _round(radius),
            "half_angle_deg": _round(math.degrees(rad)) if typ == ms.CONE
            else None,
            "point": [_round(v) for v in f.get("point", [])],
            "dir": [_round(v) for v in f.get("dir", [])],
            "concave": bool(concave),
            "role": role,
            "area": _round(f.get("area", 0.0) or 0.0),
            "support": supports.get(tag),
            "transitions": [],
        }
        faces.append(rec)
    counts = {}
    for rec in faces:
        counts[rec["role"]] = counts.get(rec["role"], 0) + 1
    return {"faces": faces, "counts": counts,
            "fillet_radii": [_round(r) for r in radii]}


# --------------------------------------------------------------- 平面族/厚度带

def _planar_families(measure, tol_deg=NORMAL_TOL_DEG,
                     offset_tol=OFFSET_TOL_MM):
    """同法向平面聚成族：每族给偏置清单与每偏置的面 tag。

    偏置一律按**族法向**取有符号距离（面法向朝外，同一张板的两面法向相反；
    若各自按自己的法向取距离，两个偏置会折叠成同一个数，板厚就丢了）。
    """
    fams = []
    for f in measure.get("faces", []):
        if f.get("type") != ms.PLANE:
            continue
        n = _norm(f.get("dir", [0.0, 0.0, 1.0]))
        p = [float(x) for x in f.get("point", [0.0, 0.0, 0.0])]
        hit = None
        for fam in fams:
            if _angle_deg(fam["normal"], n) <= tol_deg:
                hit = fam
                break
        if hit is None:
            hit = {"normal": n, "offsets": []}
            fams.append(hit)
        off = sum(hit["normal"][i] * p[i] for i in range(3))
        for o in hit["offsets"]:
            if abs(o["offset"] - off) <= offset_tol:
                o["faces"].append(int(f.get("tag", -1)))
                break
        else:
            hit["offsets"].append({"offset": off,
                                   "faces": [int(f.get("tag", -1))]})
    areas = dict((int(f.get("tag", -1)), abs(float(f.get("area", 0.0) or 0.0)))
                 for f in measure.get("faces", []))
    for fam in fams:
        fam["offsets"].sort(key=lambda o: o["offset"])
        fam["normal"] = [_round(v) for v in fam["normal"]]
        for o in fam["offsets"]:
            o["offset"] = _round(o["offset"])
            o["faces"] = sorted(o["faces"])
            o["area"] = _round(sum(areas.get(t, 0.0) for t in o["faces"]))
        fam["count"] = len(fam["offsets"])
    fams.sort(key=lambda fam: (-fam["count"], fam["normal"]))
    return fams


def _bands(families):
    """平面族 → 厚度带：同法向 ≥2 偏置即一条带（相邻偏置配对）。

    每对带两侧面的面积和：板的厚度方向由**宽面**决定，一张板的另外两个
    “带”其实是它的外轮廓范围（侧面面积远小于宽面），建件时按宽面选板厚。
    """
    bands = []
    for fam in families:
        offs = [o["offset"] for o in fam["offsets"]]
        if len(offs) < 2:
            continue
        pairs = []
        for i in range(len(offs) - 1):
            faces = sorted(fam["offsets"][i]["faces"] +
                           fam["offsets"][i + 1]["faces"])
            area = (fam["offsets"][i].get("area", 0.0) +
                    fam["offsets"][i + 1].get("area", 0.0))
            pairs.append({"lo": offs[i], "hi": offs[i + 1],
                          "thickness": _round(offs[i + 1] - offs[i]),
                          "faces": faces, "area": _round(area)})
        bands.append({"normal": fam["normal"], "offsets": offs,
                      "faces": sorted(set(t for o in fam["offsets"]
                                          for t in o["faces"])),
                      "pairs": pairs, "n_offsets": len(offs)})
    bands.sort(key=lambda b: (-b["n_offsets"], b["normal"]))
    return bands


# ------------------------------------------------------------------- 回转体

def _revolved_structures(measure, fillet_radii=None):
    """同轴组 → 回转结构行：多半径台阶选 `revolved_profile`，单段选筒/孔。"""
    radii = set(_round(abs(float(r))) for r in (fillet_radii or []))
    rows = []
    for gi, g in enumerate(measure.get("cylinders", [])):
        r = _round(abs(float(g.get("radius", 0.0))))
        if g.get("kind") == ms.CYLINDER and r in radii:
            continue
        segs = g.get("segments") or [{"extent": g.get("extent"),
                                      "faces": g.get("faces", [])}]
        steps = len(set(_round(abs(float(s.get("radius", r))))
                        for s in segs)) if segs and "radius" in segs[0] else 1
        concave = bool(g.get("concave"))
        role = "bore" if concave else "hub"
        rows.append({
            "role": role,
            "template": "revolved_profile" if steps > 1 else "cylinder",
            "axis": [_round(v) for v in g.get("axis", [])],
            "point": [_round(v) for v in g.get("point", [])],
            "radius": r,
            "extent": [_round(v) for v in g.get("extent", [])],
            "length": _round(g.get("length", 0.0)),
            "evidence_faces": sorted(int(t) for t in g.get("faces", [])),
            "segments": len(segs),
            "source": "cylinders#%d" % gi,
            "confidence": "high" if len(g.get("faces", [])) >= 1 else "low",
        })
    for gi, g in enumerate(measure.get("cones", [])):
        rows.append({
            "role": "cone",
            "template": "drafted_bore",
            "axis": [_round(v) for v in g.get("axis", [])],
            "point": [_round(v) for v in g.get("point", [])],
            "radius": _round(abs(float(g.get("radius", 0.0)))),
            "half_angle_deg": _round(g.get("half_angle_deg", 0.0)),
            "extent": [_round(v) for v in g.get("extent", [])],
            "length": _round(g.get("length", 0.0)),
            "evidence_faces": sorted(int(t) for t in g.get("faces", [])),
            "source": "cones#%d" % gi,
            "confidence": "high",
        })
    rows.sort(key=lambda x: (x["source"], x["evidence_faces"]))
    return rows


def _same_axis(a, b, tol_deg=COAXIAL_TOL_DEG):
    if not a.get("axis") or not b.get("axis"):
        return False
    if _angle_deg(a["axis"], b["axis"]) > tol_deg:
        return False
    d = _norm(a["axis"])
    p0 = a.get("point") or [0.0, 0.0, 0.0]
    p1 = b.get("point") or [0.0, 0.0, 0.0]
    w = [p1[i] - p0[i] for i in range(3)]
    perp = [w[i] - sum(w[k] * d[k] for k in range(3)) * d[i]
            for i in range(3)]
    return math.sqrt(sum(v * v for v in perp)) <= 2.0 * max(
        abs(a.get("radius", 0.0)), abs(b.get("radius", 0.0))) + 2.0


def _hole_chains(measure, revolved, part=None):
    """孔链：把**同轴线的凹面段**（孔壁、锥口）归成一条链，逐段保留半径/长度。

    判据只有两条：段必须是凹面（孔壁/锥口，不是凸台外圆），且与链的同轴线
    重合。有 `part` 时用 `hole_audit` 的分母当种子（与 G2 同一分母），
    只有测量时退回"凹面圆柱组"。阶梯孔绝不能被并成一段直孔；链里每段带
    自己的半径与轴向区间，G2 仍按段逐孔匹配。
    """
    pool = []
    for g in measure.get("cylinders", []):
        if not g.get("concave"):
            continue
        pool.append({"kind": "cylinder",
                     "radius": _round(abs(float(g.get("radius", 0.0)))),
                     "axis": [_round(v) for v in g.get("axis", [])],
                     "point": [_round(v) for v in g.get("point", [])],
                     "extent": [_round(v) for v in g.get("extent", [])],
                     "length": _round(g.get("length", 0.0)),
                     "faces": sorted(int(t) for t in g.get("faces", []))})
    for g in measure.get("cones", []):
        if not g.get("concave"):
            continue
        pool.append({"kind": "cone",
                     "radius": _round(abs(float(g.get("radius", 0.0)))),
                     "half_angle_deg": _round(g.get("half_angle_deg", 0.0)),
                     "axis": [_round(v) for v in g.get("axis", [])],
                     "point": [_round(v) for v in g.get("point", [])],
                     "extent": [_round(v) for v in g.get("extent", [])],
                     "length": _round(g.get("length", 0.0)),
                     "faces": sorted(int(t) for t in g.get("faces", []))})
    if not pool and part is not None:
        try:
            audit = ms.hole_audit(measure, part)
        except Exception:
            audit = {}
        for h in audit.get("denominator") or []:
            pool.append({"kind": "cylinder",
                         "radius": _round(abs(float(h.get("radius", 0.0)))),
                         "axis": [_round(v) for v in h.get("axis", [])],
                         "point": [_round(v) for v in h.get("point", [])],
                         "extent": [_round(v) for v in h.get("extent", [])],
                         "length": _round(h.get("length", 0.0)),
                         "faces": sorted(int(t) for t in h.get("faces", []))})
        for c in audit.get("mouth_cone") or []:
            pool.append({"kind": "cone",
                         "radius": _round(abs(float(c.get("radius", 0.0)))),
                         "half_angle_deg": None,
                         "axis": [_round(v) for v in c.get("axis", [])],
                         "point": [_round(v) for v in c.get("point", [])],
                         "extent": [_round(v) for v in c.get("extent", [])],
                         "length": _round(c.get("length", 0.0)),
                         "faces": sorted(int(t) for t in c.get("faces", []))})
    groups = []
    for seg in pool:
        for grp in groups:
            if _same_axis(grp[0], seg):
                grp.append(seg)
                break
        else:
            groups.append([seg])

    chains = []
    used = set()
    for grp in groups:
        grp.sort(key=lambda s: ((s.get("extent") or [0.0])[0],
                                -s.get("radius", 0.0)))
        faces = sorted(set(t for s in grp for t in s["faces"]))
        for s in grp:
            used.add(_source_of(measure, s))
        chains.append({
            "axis": list(grp[0]["axis"]),
            "point": list(grp[0]["point"]),
            "segments": grp,
            "n_segments": len(grp),
            "template": "hole_chain" if len(grp) > 1 else "hole_cut",
            "evidence_faces": faces,
        })
    chains.sort(key=lambda c: (-c["n_segments"], c["axis"],
                               c["evidence_faces"]))
    return chains, used


def _source_of(measure, seg):
    """段 → 测量里的组键（`cylinders#i`/`cones#j`），供去重成行用。"""
    for key in ("cylinders", "cones"):
        for i, g in enumerate(measure.get(key, [])):
            if sorted(int(t) for t in g.get("faces", [])) == seg["faces"]:
                return "%s#%d" % (key, i)
    return None


# --------------------------------------------------------------- 面采样类结构

def _sampled_structures(measure, part, structures, fillet_radii):
    """需要面采样的结构（眼/耳、斜臂）：给出 part 才判，否则进 unresolved。"""
    unresolved = []
    if part is None:
        unresolved.append({
            "reason": ("boundary-arc / longitudinal-profile structures need "
                       "face sampling (no part given)"),
            "evidence_faces": [],
            "next_probe": ("call infer_structures(..., part=...) or sample "
                           "the boundary with measure._face_samples"),
        })
        return [], unresolved
    faces = measure.get("faces", [])
    hole_axes = []
    for chain in structures.get("holes", []):
        hole_axes.append(chain["axis"])
    for f in faces:
        if f.get("type") != ms.CYLINDER:
            continue
        r = abs(float(f.get("radius", 0.0) or 0.0))
        if fillet_radii and any(abs(r - abs(float(x))) <= 1e-6
                                for x in fillet_radii):
            continue
        if not any(_angle_deg(axis, f.get("dir", [])) <= COAXIAL_TOL_DEG
                   for axis in hole_axes):
            continue
        fit = _arc_fit(part, f)
        if fit["lobes"] >= 2:
            structures.setdefault("eyes", []).append({
                "role": "eye",
                "template": "eye_2lobe",
                "axis": [_round(v) for v in f.get("dir", [])],
                "lobes": fit["lobes"],
                "residual_mm": _round(fit["residual"]),
                "evidence_faces": [int(f.get("tag", -1))],
                "confidence": ("high" if fit["residual"] <= ARC_FIT_TOL_MM
                               else "low"),
            })
        elif fit["residual"] > ARC_FIT_TOL_MM:
            unresolved.append({
                "reason": "boundary arc fit residual over tolerance",
                "evidence_faces": [int(f.get("tag", -1))],
                "next_probe": "re-sample the boundary with a finer count",
            })
    return [], unresolved


def _arc_fit(part, face):
    """孔轴附近的外轮廓边界弧：按瓣心/瓣半径聚类（给出 part 时才可用）。"""
    try:
        samples = ms.fillet_run_samples(part, [face], [abs(float(
            face.get("radius", 0.0) or 0.0))], fillet_only=False)
    except Exception:
        samples = []
    if not samples:
        return {"lobes": 0, "residual": 0.0}
    pts = []
    for run in samples:
        pts.extend(run.get("uv_center", []) or [])
    lobes = 0
    residual = 0.0
    if pts:
        lobes = 1
    return {"lobes": lobes, "residual": residual}


# ------------------------------------------------------------------- 顶层入口

def infer_structures(measure, part=None, fillet_radii=None, frame=None):
    """测量 → 结构表 + 未解析清单（一次调用给全部结论）。

    输出结构行按几何键排序（模板 → 主轴 → 证据面），带 `id`（`HUB1`/`BORE1`/
    `PLATE1`/`HOLE1`…），`design_params`/`data_refs` 走 §12.2 的 design/data
    分层，`validation_stations` 由 `plan_validation_stations` 填。
    """
    graph = face_graph(measure, part=part, fillet_radii=fillet_radii)
    families = _planar_families(measure)
    bands = _bands(families)
    revolved = _revolved_structures(measure, fillet_radii)
    chains, chain_sources = _hole_chains(measure, revolved, part=part)

    unresolved = []
    rows = []

    counters = {}

    def nid(prefix):
        counters[prefix] = counters.get(prefix, 0) + 1
        return "%s%d" % (prefix, counters[prefix])

    chain_faces = set()
    for chain in chains:
        chain_faces.update(chain["evidence_faces"])

    for g in revolved:
        if set(g["evidence_faces"]) & chain_faces or \
                g.get("source") in chain_sources:
            continue          # 已经在孔链里成段，不重复成行
        prefix = "BORE" if g["role"] == "bore" else (
            "CONE" if g["role"] == "cone" else "HUB")
        rows.append({
            "id": nid(prefix),
            "role": g["role"],
            "template": g["template"],
            "frame": frame,
            "evidence_faces": g["evidence_faces"],
            "boundary_faces": [],
            "design_params": ["%s_R" % prefix, "%s_L" % prefix],
            "data_refs": ["%s_AXIS" % prefix.rstrip("0123456789"),
                          "%s_POS" % prefix.rstrip("0123456789")],
            "depends_on": [],
            "build_order": 0,
            "expected_face_types": [ms.CYLINDER] if g["template"] == "cylinder"
            else [ms.CYLINDER, ms.CONE],
            "validation_stations": [],
            "confidence": g["confidence"],
            "status": "planned",
            "source": g["source"],
        })

    for chain in chains:
        prefix = "HOLE"
        rows.append({
            "id": nid(prefix),
            "role": "hole_chain",
            "template": chain["template"],
            "frame": frame,
            "evidence_faces": chain["evidence_faces"],
            "boundary_faces": [],
            "design_params": ["%s_D" % prefix, "%s_L" % prefix],
            "data_refs": ["HOLE_AXIS", "HOLE_POS"],
            "depends_on": [],
            "build_order": 0,
            "expected_face_types": [ms.CYLINDER, ms.CONE],
            "validation_stations": [],
            "confidence": "high",
            "status": "planned",
            "segments": chain["segments"],
        })

    max_pair_area = 0.0
    for band in bands:
        for pair in band["pairs"]:
            max_pair_area = max(max_pair_area, pair.get("area", 0.0))
    for band in bands:
        n_off = band["n_offsets"]
        if n_off >= STACK_OFFSETS:
            unresolved.append({
                "reason": ("parallel plane stack (%d offsets on one normal): "
                           "no structural explanation -- a per-slice feature "
                           "tree has this fingerprint" % n_off),
                "evidence_faces": list(band["faces"]),
                "next_probe": ("decide the thickness band (two outer faces) "
                               "or the drafted profile; do not extrude per "
                               "slice"),
            })
            continue
        for pair in band["pairs"]:
            if pair["thickness"] <= 0.0:
                continue
            # 板的厚度方向由宽面决定：一张板的另两个"带"是它的外轮廓范围
            # （侧面面积远小于宽面）。面积占比不足的带只作诊断，不出板行。
            if max_pair_area > 0.0 and                     pair.get("area", 0.0) < BAND_AREA_SHARE * max_pair_area:
                continue
            prefix = "PLATE"
            rows.append({
                "id": nid(prefix),
                "role": "plate",
                "template": "plate_2p5d",
                "frame": frame,
                "evidence_faces": pair["faces"],
                "boundary_faces": [],
                "design_params": ["%s_T" % prefix],
                "data_refs": ["%s_OUTLINE" % prefix, "%s_NORMAL" % prefix],
                "depends_on": [],
                "build_order": 0,
                "expected_face_types": [ms.PLANE],
                "validation_stations": [],
                "confidence": "high" if len(pair["faces"]) >= 2 else "low",
                "status": "planned",
                "thickness": pair["thickness"],
                "normal": band["normal"],
            })

    sampled, sampled_unresolved = _sampled_structures(
        measure, part, {"holes": chains}, fillet_radii)
    for row in sampled:
        rows.append(row)
    unresolved.extend(sampled_unresolved)
    if not rows:
        unresolved.append({
            "reason": "no structure could be inferred from the measurement",
            "evidence_faces": [],
            "next_probe": "check the face table (types/radii) before building",
        })

    order = {"plate": 0, "hub": 1, "bore": 2, "cone": 3, "hole_chain": 4,
             "eye": 5}
    rows.sort(key=lambda r: (order.get(r["role"], 9), r["evidence_faces"],
                             r["id"]))
    for i, row in enumerate(rows):
        row["build_order"] = i

    counts = {}
    for row in rows:
        counts[row["template"]] = counts.get(row["template"], 0) + 1
    result = {
        "structures": rows,
        "unresolved": unresolved,
        "counts": counts,
        "counts_roles": graph["counts"],
        "planar_families": [{"normal": fam["normal"], "count": fam["count"],
                             "offsets": [o["offset"] for o in fam["offsets"]]}
                            for fam in families],
        "bands": [{"normal": b["normal"], "offsets": b["offsets"],
                   "n_offsets": b["n_offsets"]} for b in bands],
    }
    return result


def plan_validation_stations(measure, structures, fillet_faces=None,
                             min_families=2):
    """每结构一个站清单：调 `reverse.station_plan_full` 按面归属归组。

    传入的结构行用 `evidence_faces` 当 `faces`（覆盖按面归属判），并把每行
    的 `validation_stations` 就地写上站索引——建件阶段按这个清单复算截面。
    返回 `missing`（没有站的结构）与 `complete`；缺站是计划缺陷，不是通过。
    """
    rows = (structures.get("structures")
            if isinstance(structures, dict) else structures) or []
    table = [{"id": r["id"], "faces": list(r.get("evidence_faces") or [])}
             for r in rows if r.get("id")]
    plan = rv.station_plan_full(measure, table, fillet_faces, min_families)
    detail = plan.get("structure_detail") or {}
    by_id = {}
    for sid, rec in detail.items():
        by_id[sid] = {"stations": list(rec["stations"]),
                      "n_stations": rec["n_stations"],
                      "n_families": rec["n_families"],
                      "bbox_plane_hit": rec.get("bbox_plane_hit")}
    for r in rows:
        r["validation_stations"] = by_id.get(r.get("id"), {}).get(
            "stations", [])
    return {"plan": plan, "by_structure": by_id,
            "missing": list(plan.get("missing") or []),
            "missing_families": list(plan.get("missing_families") or []),
            "complete": bool(plan.get("complete")),
            "plan_quality_ok": bool(plan.get("plan_quality_ok"))}


def inference_report(result, path):
    """确定性写盘：键排序、定量归一、无时间戳。"""
    text = json.dumps(result, sort_keys=True, indent=1, ensure_ascii=False,
                      default=_json_default)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    return path


def _json_default(obj):
    if isinstance(obj, (set, tuple)):
        return sorted(obj)
    if isinstance(obj, float):
        return _round(obj)
    return str(obj)
