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


def _explained_offsets(band, area_share=0.05, thickness_share=0.02):
    """同法向的多层平面是否有结构解释。True = 有解释（不判堆叠）。

    逐片堆叠的指纹是**同一个轮廓按恒定节距复制**，所以要同时满足两条：
    相邻层面积几乎相同（比 ≥ 1-area_share）**且**层间厚度几乎恒定
    （两两差 ≤ thickness_share）。只看面积不够：扇形/斜臂上的一组台阶面
    面积量级也相近（实测 401–1617 mm²，相邻比对 0.52–0.99），按"面积相近"
    判会把原件自己的 45° 臂台阶族判成逐片堆叠，连带整族不出结构。

    判据：按偏移排序找最长的一条"面积与厚度同时一致"的连续链；
    链长 ≥ `STACK_OFFSETS` 才判无结构解释（返回 False）。
    层面积从 `pairs` 取——`offsets` 只是偏移值列表，没有各自的面积。
    """
    pairs = sorted(band.get("pairs") or [], key=lambda p: p["lo"])
    if len(pairs) + 1 < STACK_OFFSETS:
        return True
    run = 1
    for i in range(1, len(pairs)):
        a = max(float(pairs[i - 1].get("area") or 0.0), 1e-9)
        b = max(float(pairs[i].get("area") or 0.0), 1e-9)
        ta = max(abs(float(pairs[i - 1].get("thickness") or 0.0)), 1e-9)
        tb = max(abs(float(pairs[i].get("thickness") or 0.0)), 1e-9)
        same_area = min(a, b) / max(a, b) >= 1.0 - area_share
        same_pitch = (abs(ta - tb) / max(ta, tb) <= thickness_share)
        if same_area and same_pitch:
            run += 1
            if run >= STACK_OFFSETS:
                return False      # 同轮廓等节距的层链够长 → 无结构解释
        else:
            run = 1
    return True                   # 至少有一处换轮廓或换节距 → 有结构解释


def _bands(families):
    """平面族 → 厚度带：**一个族最多一条带**，取面积最大的那一对偏置。

    旧实现给每一对相邻偏置都出一条带，于是按"面与面的几何距离"而不是
    "结构语义"出板：L 形件 X 方向的 0/10/125 三个偏置变成两块板，六角头的
    三个相邻侧面变成两块板，方管壁厚与总宽变成两块板。真实的板只有一个
    厚度方向，其余同法向偏置是**同一个体的轮廓范围**（外轮廓跨度、台阶
    高度），不是第二块板。

    判据：同一法向族里，板厚方向的那一对是**面积最大**的一对（宽面面积远
    大于侧面/端面）。其余相邻对被记为 `spare`，由调用方决定它们是否有
    结构解释——不静默丢弃，也不自动变成板。

    返回每族一条：
      normal / offsets / faces / thickness / pair(选中那对) / pairs(全部) /
      n_offsets / spare(未选中的相邻对)
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
        chosen = max(pairs, key=lambda p: (p.get("area") or 0.0,
                                           -abs(p["thickness"])))
        spare = [p for p in pairs if p is not chosen]
        bands.append({"normal": fam["normal"], "offsets": offs,
                      "levels": [{"offset": o["offset"], "faces": o["faces"],
                                  "area": o.get("area", 0.0)}
                                 for o in fam["offsets"]],
                      "faces": sorted(set(t for o in fam["offsets"]
                                          for t in o["faces"])),
                      "pairs": pairs, "pair": chosen, "spare": spare,
                      "thickness": chosen["thickness"],
                      "pair_area": _round(chosen.get("area") or 0.0),
                      "max_pair_area": _round(max(p.get("area") or 0.0
                                                  for p in pairs)),
                      "n_offsets": len(offs)})
    bands.sort(key=lambda b: (-(b["pair"].get("area") or 0.0), b["normal"]))
    return bands


# ------------------------------------------------------------------- 回转体

def _revolved_structures(measure, fillet_radii=None):
    """同轴组 → 回转结构行：同一根轴上多半径台阶 → `revolved_profile`。

    `measure.group_coaxial` 按 (轴, 半径) 分桶，所以一根两阶轴会给出两个组、
    每组只有一段——直接按组出行就永远选不到 `revolved_profile`，而台阶轴的
    正解是分段回转（z 带堆叠会多出段间台阶面）。这里先按**轴线**把组并成
    一根轴，再数这根轴上的不同半径：多半径即台阶轴，一段半径才是筒/孔。
    """
    radii = set(_round(abs(float(r))) for r in (fillet_radii or []))
    groups = []
    for gi, g in enumerate(measure.get("cylinders", [])):
        r = _round(abs(float(g.get("radius", 0.0))))
        if r in radii:
            continue
        row = {"radius": r, "source": "cylinders#%d" % gi,
               "faces": sorted(int(t) for t in g.get("faces", [])),
               "extent": [_round(v) for v in g.get("extent", [])],
               "length": _round(g.get("length", 0.0)),
               "concave": bool(g.get("concave")),
               "axis": [_round(v) for v in g.get("axis", [])],
               "point": [_round(v) for v in g.get("point", [])]}
        for grp in groups:
            # 只并**同一类**：凸台外圆与孔壁常常同轴（凸台围着孔），把它们
            # 并成一根轴会让台阶数变成 3、把凸台算进孔链，随后孔链去重又把
            # 凸台整个吞掉——凸台在报告里就消失了
            if grp[0]["concave"] == row["concave"] and                     _same_axis(grp[0], row):
                grp.append(row)
                break
        else:
            groups.append([row])

    rows = []
    for grp in groups:
        grp.sort(key=lambda s: (s["extent"][0] if s["extent"] else 0.0,
                                -s["radius"]))
        radii_in = sorted(set(s["radius"] for s in grp))
        faces = sorted(set(t for s in grp for t in s["faces"]))
        axis = grp[0]["axis"]
        # 轴向区间取整根轴的并集：单看某一段会把台阶轴的行程报短
        lo = min((s["extent"] or [0.0])[0] for s in grp)
        hi = max((s["extent"] or [0.0])[-1] for s in grp)
        steps = len(radii_in)
        role = "bore" if all(s["concave"] for s in grp) else "hub"
        rows.append({
            "role": role,
            "template": "revolved_profile" if steps > 1 else "cylinder",
            "axis": axis,
            "point": grp[0]["point"],
            "radius": max(radii_in),
            "radii": radii_in,
            "extent": [lo, hi],
            "length": _round(hi - lo),
            "evidence_faces": faces,
            "segments": len(grp),
            "sources": [s["source"] for s in grp],
            "source": grp[0]["source"],
            "confidence": "high" if faces else "low",
        })
    for gi, g in enumerate(measure.get("cones", [])):
        rows.append({
            "role": "cone",
            "template": "drafted_bore",
            "axis": [_round(v) for v in g.get("axis", [])],
            "point": [_round(v) for v in g.get("point", [])],
            "radius": _round(abs(float(g.get("radius", 0.0)))),
            "radii": [_round(abs(float(g.get("radius", 0.0))))],
            "half_angle_deg": _round(g.get("half_angle_deg", 0.0)),
            "extent": [_round(v) for v in g.get("extent", [])],
            "length": _round(g.get("length", 0.0)),
            "evidence_faces": sorted(int(t) for t in g.get("faces", [])),
            "segments": 1,
            "sources": ["cones#%d" % gi],
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
    """需要面采样的结构（眼/耳）：给出 part 才判，否则进 unresolved。

    触发面不再要求"属于孔链"：眼端的孔可能没被孔审计收进分母（薄壁、盲
    孔、切在斜面上），按孔链筛选会把眼整个跳过——而跳过在报告里与"没有眼"
    长得一样。判据改成"这个圆柱面是不是一根孔轴"，用面自身的轴线取截面，
    再看外轮廓是否呈双瓣。
    """
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
    seen_axes = []
    for f in faces:
        if f.get("type") != ms.CYLINDER:
            continue
        r = abs(float(f.get("radius", 0.0) or 0.0))
        if r <= 0.0:
            continue
        if fillet_radii and any(abs(r - abs(float(x))) <= 1e-6
                                for x in fillet_radii):
            continue
        axis = _norm(f.get("dir", [0.0, 0.0, 1.0]))
        # one fit per axis: the two lobe cylinders and the hole share it
        if any(_angle_deg(axis, a) <= COAXIAL_TOL_DEG for a in seen_axes):
            continue
        seen_axes.append(axis)
        fit = _arc_fit(part, f, axis)
        if fit["lobes"] >= 2:
            structures.setdefault("eyes", []).append({
                "role": "eye",
                "template": "eye_2lobe",
                "axis": [_round(v) for v in axis],
                "lobes": fit["lobes"],
                "residual_mm": _round(fit["residual"]),
                "lobe_radii": [_round(v) for v in fit.get("radii") or []],
                "evidence_faces": [int(f.get("tag", -1))],
                "confidence": ("high" if fit["residual"] <= ARC_FIT_TOL_MM
                               else "low"),
            })
    # 返回值就是结构行本身：早先这里恒返回 []，于是眼被判出来了却当成
    # "没有结构"丢掉——判据全对、交付为空，比判错更难发现
    return list(structures.get("eyes") or []), unresolved


RING_SAMPLES = 360          # 等弧长重采样点数（1 点 = 1 度）
ARC_WINDOW_DEG = 20.0       # 局部圆拟合窗口的角跨度
ARC_MIN_SPAN_DEG = 15.0     # 一段圆弧至少覆盖多少度才算结构特征


def _resample_by_length(ring, n):
    """闭合折线按等弧长重采样成 n 点（点距均匀，窗口跨度才可用角度表示）。"""
    seg = []
    total = 0.0
    for i in range(len(ring)):
        a0, b0 = ring[i]
        a1, b1 = ring[(i + 1) % len(ring)]
        d = math.hypot(a1 - a0, b1 - b0)
        seg.append(((a0, b0), (a1, b1), d))
        total += d
    if total <= 0.0:
        return list(ring)
    out = []
    step = total / float(n)
    acc = 0.0
    k = 0
    for j in range(n):
        target = step * j
        while k < len(seg) - 1 and acc + seg[k][2] < target:
            acc += seg[k][2]
            k += 1
        d = seg[k][2]
        t = 0.0 if d <= 1e-12 else (target - acc) / d
        t = max(0.0, min(1.0, t))
        a0, b0 = seg[k][0]
        a1, b1 = seg[k][1]
        out.append((a0 + t * (a1 - a0), b0 + t * (b1 - b0)))
    return out


def _arc_fit(part, face, hole_axis, window=None):
    """孔端外轮廓的瓣拟合：把轮廓拆成"等半径圆弧簇"，数有几瓣。

    为什么不用绕轴射线扇：射线扇量的是"该角度上最远的边界"，而耳端背后就是
    整条臂，同一根射线会先穿 lobe 再打到几十毫米外的臂侧壁，半径序列没有
    平台（一测就是一串连续值）。结构事实是**轮廓由 N 段圆弧组成**：双瓣耳端
    是两段等半径圆弧（瓣心对称于孔轴）加两段直壁。所以这里直接做圆弧提取：

    1. 取过孔轴的截面，保留闭合外环的点（内环是孔，不参与）；
    2. 每点用相邻 `window` 个点做最小二乘圆拟合，得到局部圆心/半径/残差；
    3. 残差小的点按 (圆心, 半径) 聚簇，每簇还要有足够的角跨度才算一段圆弧
       （短弧可能只是直线段的数值抖动）；
    4. 半径相近的簇 → 同一个"瓣半径"；瓣心相对孔轴成对称两处 → 双瓣。

    返回 lobes（等半径圆弧簇数）、radius（瓣半径）、centers（瓣心相对孔轴的
    偏移）、span_deg（各簇角度覆盖）。判定用 lobes 与对称性，构建期再由
    `eye_2lobe` 从截面取瓣心实际位置。
    """
    d = _norm(hole_axis if hole_axis else face.get("dir", [0.0, 0.0, 1.0]))
    p = [float(x) for x in (face.get("point") or [0.0, 0.0, 0.0])]
    r_hole = abs(float(face.get("radius", 0.0) or 0.0))
    empty = {"lobes": 0, "residual": 0.0, "radius": 0.0, "radii": [],
             "centers": [], "span_deg": []}
    try:
        sec = ms.exact_section(part, p, d)
    except Exception:
        return empty
    e1, e2 = ms._basis(d)
    rings = []
    for lp in sec.get("loops") or []:
        pts = lp.get("pts") or []
        if not lp.get("closed") or len(pts) < 24:
            continue
        uv = []
        for q in pts:
            w = [q[k] - p[k] for k in range(3)]
            uv.append((sum(w[k] * e1[k] for k in range(3)),
                       sum(w[k] * e2[k] for k in range(3))))
        rings.append(uv)
    if not rings:
        return empty
    # 截面里既有孔环也有外轮廓：取**点最多**的那一圈当外轮廓（孔环是整圆、
    # 外轮廓带直壁，两者点数不一定谁多，所以之外还要比长度）。这里用绝对
    # 弧长最长的环——外轮廓永远比孔长。
    def ring_len(uv):
        tot = 0.0
        for i in range(len(uv)):
            a0, b0 = uv[i]
            a1, b1 = uv[(i + 1) % len(uv)]
            tot += math.hypot(a1 - a0, b1 - b0)
        return tot
    rings.sort(key=lambda uv: -ring_len(uv))
    outer = rings[0]
    n = len(outer)
    half = int(window if window else ARC_WINDOW_DEG) // 2

    def fit_circle(idx):
        xs = [outer[i % n] for i in idx]
        m = float(len(xs))
        sx = sum(q[0] for q in xs) / m
        sy = sum(q[1] for q in xs) / m
        suu = sum((q[0] - sx) ** 2 for q in xs)
        svv = sum((q[1] - sy) ** 2 for q in xs)
        suv = sum((q[0] - sx) * (q[1] - sy) for q in xs)
        suuu = sum((q[0] - sx) ** 3 for q in xs)
        svvv = sum((q[1] - sy) ** 3 for q in xs)
        suvv = sum((q[0] - sx) * (q[1] - sy) ** 2 for q in xs)
        svuu = sum((q[1] - sy) * (q[0] - sx) ** 2 for q in xs)
        det = suu * svv - suv * suv
        if abs(det) < 1e-12:
            return None
        a = 0.5 * (suuu + suvv)
        b = 0.5 * (svvv + svuu)
        uc = (a * svv - b * suv) / det
        vc = (b * suu - a * suv) / det
        r = math.sqrt(uc * uc + vc * vc + (suu + svv) / m)
        if r <= 0.0:
            return None
        res = 0.0
        for q in xs:
            res = max(res, abs(math.hypot(q[0] - (sx + uc),
                                          q[1] - (sy + vc)) - r))
        return (sx + uc, sy + vc, r, res)

    # 先按**弧长**重采样：截面曲线是 `SectionFromPlanes` 拟合出来的多段样条，
    # 每段给 65 个采样点，所以点的疏密随曲率变化。按点数开窗口会在样条的
    # 陡段只跨极短弧长——近直的三点拟合能给出半径任意的"圆"且残差极小，
    # 于是每个窗口各自成簇。按等弧长重采样后窗口才有固定的角度含义。
    ring = _resample_by_length(outer, RING_SAMPLES)
    n = len(ring)
    outer = ring

    local = []
    for i in range(n):
        idx = [i + k - half
               for k in range(int(window if window else ARC_WINDOW_DEG))]
        f = fit_circle(idx)
        if f is not None and f[3] <= max(0.05, 0.01 * f[2]):
            local.append((i, f[0], f[1], f[2]))

    if not local:
        return empty
    # 按 (圆心, 半径) 聚簇，容差是**相对值**：半径 2%、圆心 5% 环径。不能按
    # 样本极差定容差——环上总有几处窗口跨在直壁上，拟合出半径几十的"大圆"，
    # 极差被它撑开，于是任何两个样本都算同类，每个点各自成簇。
    r_ring = max(math.hypot(a, b) for (a, b) in outer)
    clusters = []
    for rec in local:
        placed = False
        for cl in clusters:
            cx = sum(r[1] for r in cl) / float(len(cl))
            cy = sum(r[2] for r in cl) / float(len(cl))
            cr = sum(r[3] for r in cl) / float(len(cl))
            if (abs(cr - rec[3]) <= max(0.02 * cr, 0.05) and
                    math.hypot(cx - rec[1], cy - rec[2])
                    <= max(0.05 * r_ring, 0.5)):
                cl.append(rec)
                placed = True
                break
        if not placed:
            clusters.append([rec])
    arcs = []
    for cl in clusters:
        idx = sorted(set(r[0] for r in cl))
        if len(idx) < 3:
            continue
        span = 360.0 * float(len(idx)) / float(n)
        if span < ARC_MIN_SPAN_DEG:
            continue
        cx = sum(r[1] for r in cl) / float(len(cl))
        cy = sum(r[2] for r in cl) / float(len(cl))
        cr = sum(r[3] for r in cl) / float(len(cl))
        arcs.append({"center": (round(cx, 4), round(cy, 4)),
                     "radius": round(cr, 4), "span_deg": round(span, 2),
                     "points": len(idx)})
    if not arcs:
        return empty
    # 瓣 = 与最长弧同半径的弧（每个瓣就是一段这样的圆弧）
    base = max(arcs, key=lambda a: a["span_deg"])
    same = [a for a in arcs
            if abs(a["radius"] - base["radius"]) <= max(
                0.02 * base["radius"], 0.05)]
    offsets = [math.hypot(a["center"][0], a["center"][1]) for a in same]
    return {"lobes": len(same),
            "residual": 0.0,
            "radius": base["radius"],
            "radii": sorted(set(a["radius"] for a in arcs)),
            "centers": [a["center"] for a in same],
            "center_offsets": [round(o, 4) for o in offsets],
            "span_deg": [a["span_deg"] for a in same],
            "arcs": arcs,
            "hole_radius": r_hole}



# --------------------------------------------------------------- 变截面臂

SHAPE_SIMILARITY = 0.06        # 归一化轮廓的逐点半径相对差上限（相似判据）


def _ring_radii_profile(pts3, n_out=24):
    """三维闭环 → 归一化的"到形心距离"序列（只留形状，去掉位置与尺度）。"""
    if not pts3:
        return None
    ring = _resample_by_length([(p[0], p[1]) for p in pts3], n_out)
    cx = sum(p[0] for p in ring) / float(len(ring))
    cy = sum(p[1] for p in ring) / float(len(ring))
    rs = [math.hypot(p[0] - cx, p[1] - cy) for p in ring]
    ref = sum(rs) / float(len(rs))
    if ref <= 0.0:
        return None
    return [r / ref for r in rs]


def _sections_similar(a, b, tol):
    """两张截面是否"同一轮廓按比例缩放"（拔模/缩放）而不是形状变了。

    做法：各自归一化到平均半径 1，逐点比半径序列。拔模体的两张截面是同一条
    轮廓的相似形，归一化后逐点重合；变截面臂的端面长宽比不同，归一化后仍
    有明显差异。相位的选择取最小残差的那个循环移位（两截面起点可能不同）。
    """
    ra = _ring_radii_profile(a)
    rb = _ring_radii_profile(b)
    if ra is None or rb is None:
        return False
    n = len(ra)
    worst = None
    for shift in range(n):
        d = max(abs(ra[i] - rb[(i + shift) % n]) for i in range(n))
        worst = d if worst is None else min(worst, d)
    return worst is not None and worst <= tol



def _loft_structures(measure, part, bands):
    """沿"行程"方向截面面积变化的体 → 放样臂，不是等截面板。

    为什么不能只看平面族：一块板的两侧宽平面面积相近、行程方向的截面不变；
    变截面臂的端面会形成一条"厚度"带（那是行程不是壁厚），而它的侧壁可能
    是直纹平面、B 曲面或样条，按面型判会漏。真正区分两者的是**截面面积随
    行程的变化**：板在 1/6 与 5/6 处面积几乎相同，臂会差出一截。

    行程方向取平面族里偏置数最多那一族（板/臂的端面与分界都在这个法向上），
    两张截面各取在 1/6 与 5/6 处，避开根部过渡与端部圆角。面积比 > 1+2%
    （`BAND_AREA_TOL`）即判变截面。

    只做判定、不改几何：截面张数由构建阶段按实测分界补，builder 不猜。
    """
    if part is None or not bands:
        return [], []
    out = []
    used = set()
    for band in bands:
        if band["n_offsets"] >= STACK_OFFSETS and not _explained_offsets(band):
            continue          # 平行面堆叠已经另有拒收，不再重复判
        d = _norm(band["normal"])
        offs = [o for o in band["offsets"]]
        if len(offs) < 2:
            continue
        lo, hi = min(offs), max(offs)
        if hi - lo <= 0.0:
            continue
        areas, shape = [], []
        for frac in (1.0 / 6.0, 5.0 / 6.0):
            t = lo + (hi - lo) * frac
            o = [d[k] * t for k in range(3)]
            try:
                sec = ms.exact_section(part, o, d)
            except Exception:
                areas, shape = [], []
                break
            closed = [lp for lp in sec["loops"] if lp.get("closed")]
            areas.append(sum(abs(lp.get("abs_area") or 0.0)
                             for lp in closed))
            if closed:
                big = max(closed, key=lambda lp: abs(lp.get("abs_area") or 0.0))
                shape.append(big.get("pts") or [])
        if len(shape) != 2 or min(areas) <= 0.0:
            continue
        ratio = max(areas) / min(areas)
        if ratio < 1.0 + BAND_AREA_TOL:
            continue
        # 拔模体也是"截面面积随行程变"：它的两张截面**形状相似**（同一条
        # 轮廓按比例缩放），面积比只反映收缩率。真正的变截面臂两张截面的
        # 形状本身不同（长宽比变）。区分靠相似度：把两张截面各自归一化到
        # 同一面积后，若逐点重合就是拔模/缩放，否则才是变截面。
        if _sections_similar(shape[0], shape[1], SHAPE_SIMILARITY):
            continue
        # 臂的证据是**沿行程方向的两张端面**，不是整条带的所有平面面。
        # 旧实现把 band["faces"]（整族全部面）都算作臂的证据，于是这块板的
        # 上下宽面被臂认领，板行随即"证据为空"而整行消失——原件上板行全灭、
        # 只剩臂，就是这个原因。这里只认最外侧两个偏置上的面。
        end_faces = []
        for o in band.get("levels") or []:
            if abs(o["offset"] - lo) <= 1e-6 or abs(o["offset"] - hi) <= 1e-6:
                end_faces.extend(o["faces"])
        faces = sorted(set(end_faces))
        used.update(faces)
        out.append({
            "role": "arm",
            "template": "section_loft",
            "axis": [_round(v) for v in d],
            "sections": 2,
            "area_lo": _round(min(areas)),
            "area_hi": _round(max(areas)),
            "area_ratio": _round(ratio),
            "evidence_faces": faces,
            "boundary_faces": [],
            "confidence": "high" if ratio > 1.05 else "low",
        })
    return out, []


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
            "radius": g.get("radius"),
            "radii": list(g.get("radii") or []),
            "half_angle_deg": g.get("half_angle_deg"),
            "axis": g.get("axis"),
            "extent": g.get("extent"),
            "length": g.get("length"),
            "segments": g.get("segments"),
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
        if n_off >= STACK_OFFSETS and not _explained_offsets(band):
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
        pair = band["pair"]
        if pair["thickness"] > 0.0:
            # 一个平面族只出一条厚度带：板厚方向是面积最大的那一对（宽面）。
            # 其余相邻对是同一个体的轮廓范围/台阶，不是第二块板。
            if not (max_pair_area > 0.0 and pair.get("area", 0.0) <
                    BAND_AREA_SHARE * max_pair_area):
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
        # 未选中的相邻对不是第二块板，但它们是**未被解释的面组**：登记下来，
        # 让调用方知道这些面还没有结构归属，而不是静默丢掉。
        for p in band["spare"]:
            if p["thickness"] <= 0.0:
                continue
            unresolved.append({
                "reason": ("extra offset pair on normal %r at %.3f..%.3f "
                           "(thickness %.3f): same-family offsets that are "
                           "not the plate thickness band -- outline extent or "
                           "a step, needs an explicit structure decision"
                           % (band["normal"], p["lo"], p["hi"],
                              p["thickness"])),
                "evidence_faces": list(p["faces"]),
                "next_probe": ("decide whether these faces belong to the "
                               "plate outline or to a separate structure "
                               "(boss/step/arm); do not emit a second plate"),
                "kind": "unclaimed_offsets",
            })

    # 变截面臂：沿板带行程方向取两张截面，面积随行程变 → 放样。
    # 放在板之后：臂的两端端面本来就形成一条"厚度"带，那是臂的行程而不是
    # 壁厚，所以要用截面面积随行程的变化来决定它是板还是臂。
    lofted, loft_unresolved = _loft_structures(measure, part, bands)
    unresolved.extend(loft_unresolved)
    loft_faces = set(t for r in lofted for t in r["evidence_faces"])
    if lofted:
        # 只把**被臂认领的面**从板上摘掉，不要因为一两面重叠就删掉整块板。
        # 旧实现按"任一面重叠即整行删除"，一块 12 面的大板只要有一个面被
        # 臂的端面截面用到就整行消失——原件上板行全灭就是这个原因。
        kept = []
        for r in rows:
            ev = [int(t) for t in r.get("evidence_faces") or []]
            rest = [t for t in ev if t not in loft_faces]
            if not rest:
                continue
            if len(rest) != len(ev):
                r = dict(r)
                r["evidence_faces"] = rest
                r["shared_with_arm"] = [t for t in ev if t in loft_faces]
            kept.append(r)
        rows = kept
    for r in lofted:
        rows.append({
            "id": nid("ARM"),
            "role": r["role"],
            "template": r["template"],
            "frame": frame,
            "evidence_faces": r["evidence_faces"],
            "boundary_faces": [],
            "axis": r["axis"],
            "sections": r["sections"],
            "area_lo": r["area_lo"],
            "area_hi": r["area_hi"],
            "area_ratio": r["area_ratio"],
            "design_params": ["ARM_L"],
            "data_refs": ["ARM_SECTIONS"],
            "depends_on": [],
            "build_order": 0,
            "expected_face_types": [],
            "validation_stations": [],
            "confidence": r["confidence"],
            "status": "planned",
        })

    sampled, sampled_unresolved = _sampled_structures(
        measure, part, {"holes": chains}, fillet_radii)
    for row in sampled:
        row.setdefault("frame", frame)
        row["id"] = nid("EYE")
        row.setdefault("boundary_faces", [])
        row.setdefault("design_params", ["%s_R" % row["id"],
                                         "%s_T" % row["id"]])
        row.setdefault("data_refs", ["EYE_LOBES", "EYE_PLAN"])
        row.setdefault("depends_on", [])
        row["build_order"] = 0
        row.setdefault("expected_face_types", [ms.CYLINDER])
        row.setdefault("validation_stations", [])
        row.setdefault("status", "planned")
        rows.append(row)
    unresolved.extend(sampled_unresolved)
    if not rows:
        unresolved.append({
            "reason": "no structure could be inferred from the measurement",
            "evidence_faces": [],
            "next_probe": "check the face table (types/radii) before building",
        })

    order = {"plate": 0, "hub": 1, "bore": 2, "cone": 3, "hole_chain": 4,
             "arm": 5, "eye": 6}
    rows.sort(key=lambda r: (order.get(r["role"], 9), r["evidence_faces"],
                             r["id"]))
    for i, row in enumerate(rows):
        row["build_order"] = i

    # ---- 面归属对账：每一张面都必须有结构解释，否则显式登记。
    # 旧实现只处理 PLANE/CYLINDER/CONE/TORUS，SPHERE(18)/B_SURFACE(23)/
    # BLEND(43) 既没有角色也不进 unresolved——球面、环面、自由曲面在结构表
    # 里完全消失，而报告看起来"完整"。这里把未归属面按类型与半径分组点名。
    claimed = set()
    for row in rows:
        claimed.update(int(t) for t in (row.get("evidence_faces") or []))
    for u in unresolved:
        claimed.update(int(t) for t in (u.get("evidence_faces") or []))
    unclaimed = [f for f in measure.get("faces", [])
                 if int(f.get("tag", -1)) not in claimed]
    if unclaimed:
        by_kind = {}
        for f in unclaimed:
            typ = int(f.get("type", -1))
            rad = _round(abs(float(f.get("rad_data") or f.get("radius") or 0.0)))
            key = (typ, rad)
            by_kind.setdefault(key, []).append(int(f.get("tag", -1)))
        for (typ, rad), tags in sorted(by_kind.items()):
            unresolved.append({
                "reason": ("%d face(s) of type %d (radius %s) have no "
                           "structure: this face type is not modelled by any "
                           "template yet" % (len(tags), typ, rad)),
                "evidence_faces": sorted(tags),
                "next_probe": ("decide a template for face type %d; if the "
                               "type is a free-form/blend surface, either "
                               "reproduce it by measured sections or declare "
                               "it as a listed simplification"
                               % typ),
                "kind": "unclaimed_faces",
                "face_type": typ,
                "radius": rad,
            })
    result_counts_roles = dict(graph["counts"])

    counts = {}
    for row in rows:
        counts[row["template"]] = counts.get(row["template"], 0) + 1
    result = {
        "structures": rows,
        "unresolved": unresolved,
        "counts": counts,
        "counts_roles": result_counts_roles,
        "claimed_faces": len(claimed),
        "unclaimed_faces": len(unclaimed),
        "face_coverage": (_round(len(claimed) /
                                 float(len(measure.get("faces") or [1])))),
        "planar_families": [{"normal": fam["normal"], "count": fam["count"],
                             "offsets": [o["offset"] for o in fam["offsets"]]}
                            for fam in families],
        "bands": [{"normal": b["normal"], "offsets": b["offsets"],
                   "n_offsets": b["n_offsets"],
                   "thickness": b["thickness"],
                   "pair_area": b["pair_area"],
                   "max_pair_area": b["max_pair_area"],
                   "spare_pairs": len(b["spare"])} for b in bands],
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
