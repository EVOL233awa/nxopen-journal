# -*- coding: utf-8 -*-
"""nxlib.reverse —— 逆向测量编译层（只读，不建几何、不保存部件）。

把面表/同轴组/平面族/圆角图/孔审计编译成五张可冻结的表：

  candidate_directory  功能面组候选（回转组、平面带、圆角半径组、环面组、孔）
  param_candidates     逐结构参数候选，带 kind(design/data)/source/confidence
  station_plan_full    全集测站（不截断）+ 结构覆盖检查
  interface_table      孔/锥/座锥分母（hole_audit 的机器可读投影）
  runway_table         圆角跑道、支撑对、可达上限、方法建议

自动化等级是"候选 + 人工确认"：candidate_directory 不猜结构名，只给证据和
稳定 id；冻结结构表由 validate_structure_table 校验面 tag、包围盒、面积与
重叠。所有输出只依赖测量值，同一部件重跑应逐项一致。
"""
import math

from . import measure as ms


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else [0.0, 0.0, 0.0]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _perp_dist(p1, p2, d):
    v = _sub(p2, p1)
    return math.sqrt(max(0.0, _dot(v, v) - _dot(v, d) ** 2))


def _bbox_union(rows):
    if not rows:
        return None
    box = [1e18, 1e18, 1e18, -1e18, -1e18, -1e18]
    for f in rows:
        b = f.get("box")
        if not b:
            continue
        for i in range(3):
            box[i] = min(box[i], b[i])
            box[i + 3] = max(box[i + 3], b[i + 3])
    return box


def _face_tags(rows):
    return [int(f["tag"]) for f in rows]


def _group_by_coaxial(groups, axis_tol_deg=0.5, line_tol=2.0):
    """并查集：同轴（方向夹角 + 点到轴线距离）的柱/锥组归一族。"""
    parent = list(range(len(groups)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(groups)):
        gi = groups[i]
        for j in range(i + 1, len(groups)):
            gj = groups[j]
            c = abs(_dot(gi["axis"], gj["axis"]))
            ang = math.degrees(math.acos(min(1.0, c)))
            if ang > axis_tol_deg:
                continue
            if _perp_dist(gi["point"], gj["point"], gi["axis"]) > \
                    line_tol + max(gi["radius"], gj["radius"]):
                continue
            union(i, j)
    out = {}
    for i in range(len(groups)):
        out.setdefault(find(i), []).append(i)
    return list(out.values())


def candidate_directory(measure, part=None, fillet_radii=None, audit=None):
    """面表 → 功能面组候选。

    返回 dict：
      revolved  [{id, role, face_kind, axis, point, radius, half_angle_deg,
                  extent, length, center, bbox, faces, concave, coaxial}]
      bands     [{id, normal, offset, thickness_after, bbox, faces, nfaces}]
      fillets   [{id, radius, nfaces, bbox, faces, face_supports}]
      torus     [{id, major, minor, nfaces, bbox, faces}]
      holes     [{id, role, radius, axis, center, length, faces, confidence}]
      counts    {...}
    """
    faces = measure["faces"]
    groups = list(measure.get("cylinders", [])) + list(measure.get("cones", []))
    coax = _group_by_coaxial(groups)
    coax_of = {}
    for k, idxs in enumerate(coax):
        for i in idxs:
            coax_of[i] = k

    revolved = []
    for i, g in enumerate(groups):
        role = "boss"
        if g.get("concave"):
            role = "bore"
        rec = {
            "id": "R%03d" % (i + 1),
            "role": role,
            "face_kind": "cylinder" if g["kind"] == ms.CYLINDER else "cone",
            "axis": [round(x, 6) for x in g["axis"]],
            "point": [round(x, 6) for x in g["point"]],
            "radius": round(float(g["radius"]), 6),
            "half_angle_deg": round(float(g.get("half_angle_deg", 0.0)), 6),
            "extent": [round(float(x), 6) for x in g["extent"]],
            "length": round(float(g.get("length", 0.0)), 6),
            "center": [round(float(x), 6) for x in g.get("center", g["point"])],
            "bbox": [round(float(x), 6) for x in g.get("bbox", [])],
            "faces": [int(x) for x in g["faces"]],
            "concave": bool(g.get("concave")),
            "coaxial_group": coax_of.get(i, -1),
        }
        revolved.append(rec)

    planes = ms.plane_families(faces)
    by_normal = {}
    for p in planes:
        key = tuple(round(x, 3) for x in p["normal"])
        by_normal.setdefault(key, []).append(p)
    bands = []
    for key, rows in sorted(by_normal.items()):
        rows.sort(key=lambda r: r["offset"])
        for k, p in enumerate(rows):
            nxt = rows[k + 1]["offset"] if k + 1 < len(rows) else None
            bands.append({
                "id": "B%03d_%02d" % (len(bands) + 1, k + 1),
                "normal": list(key),
                "offset": round(float(p["offset"]), 6),
                "thickness_after": (round(float(nxt - p["offset"]), 6)
                                    if nxt is not None else None),
                "bbox": [round(float(x), 6) for x in p["bbox"]],
                "faces": [int(x) for x in p["faces"]],
                "nfaces": int(p["nfaces"]),
            })

    fillets = []
    try:
        fmap = ms.fillet_map(faces, radii=fillet_radii)
    except Exception:
        fmap = []
    for k, r in enumerate(fmap):
        fillets.append({
            "id": "F%03d" % (k + 1),
            "radius": round(float(r["radius"]), 6),
            "nfaces": int(r["nfaces"]),
            "bbox": [round(float(x), 6) for x in r["bbox"]],
            "faces": [int(x) for x in r["faces"]],
            "face_supports": r["face_supports"],
        })

    torus = []
    for k, t in enumerate(ms.torus_groups(faces)):
        torus.append({
            "id": "T%03d" % (k + 1),
            "major": round(float(t["major"]), 6),
            "minor": round(float(t["minor"]), 6),
            "nfaces": int(t["nfaces"]),
            "bbox": [round(float(x), 6) for x in t["bbox"]],
            "faces": [int(x) for x in t["faces"]],
        })

    holes = []
    if part is not None:
        if audit is None:
            audit = ms.hole_audit(measure, part)
        for k, g in enumerate(audit["denominator"]):
            holes.append({
                "id": "H%03d" % (k + 1),
                "role": "hole" if g.get("kind") == ms.CYLINDER else "tapered_hole",
                "radius": round(float(g["radius"]), 6),
                "axis": [round(float(x), 6) for x in g["axis"]],
                "center": [round(float(x), 6) for x in g["center"]],
                "length": round(float(g["length"]), 6),
                "faces": [int(x) for x in g["faces"]],
                "confidence": "high",
            })
        for k, g in enumerate(audit["unclassified"]):
            holes.append({
                "id": "U%03d" % (k + 1),
                "role": "unclassified",
                "radius": round(float(g["radius"]), 6),
                "axis": [round(float(x), 6) for x in g["axis"]],
                "center": [round(float(x), 6) for x in g["center"]],
                "length": round(float(g["length"]), 6),
                "faces": [int(x) for x in g["faces"]],
                "confidence": "low",
            })

    return {
        "revolved": revolved,
        "bands": bands,
        "fillets": fillets,
        "torus": torus,
        "holes": holes,
        "counts": {
            "faces": len(faces),
            "revolved": len(revolved),
            "coaxial_groups": len(coax),
            "bands": len(bands),
            "fillet_radius_groups": len(fillets),
            "torus_groups": len(torus),
            "holes": len([h for h in holes if h["confidence"] == "high"]),
            "unclassified": len([h for h in holes if h["confidence"] == "low"]),
        },
    }


def param_candidates(directory):
    """候选参数：design 可进命名表达式，data 只作测量数据。

    只从解析量取：半径、轴向长度、平面偏置、相邻偏置厚度、孔半径/深。
    data 分级（不伪装成可驱动参数）：
      - 轮廓/轴方向/轴位置/包围盒；
      - 圆锥半角默认 data：它常是"两端半径 + 长度"的结果量，只有当用户
        显式声明角度为设计意图时才是 design（用 `design_cones` 列入）；
      - 平面偏置默认 design（厚度方向常由设计驱动），但两侧都是数据定位时
        由调用方降级（`data_planes`）。

    同名参数只保留一条（同一功能组同时以 revolved 与 holes 出现时不再生成
    两个冲突名字）；每条带 `derived_from`（结果量的来源参数名列表），供
    template.validate_schema 拒绝把 derived 当独立参数。
    """
    rows = []
    seen = {}

    def add(name, value, unit, kind, source, confidence, structure,
            derived_from=None):
        if name in seen:
            rec = seen[name]
            if structure not in rec["structures"]:
                rec["structures"].append(structure)
            rec["alias_of"] = rec.get("alias_of") or []
            return rec
        rec = {"name": name, "value": value, "unit": unit, "kind": kind,
               "source": source, "confidence": confidence,
               "structure": structure, "structures": [structure],
               "derived_from": list(derived_from or [])}
        seen[name] = rec
        rows.append(rec)
        return rec

    for r in directory["revolved"]:
        sid = r["id"]
        add(sid + "_R", r["radius"], "mm", "design",
            "face_group %s" % sid, "high", sid)
        if abs(r["half_angle_deg"]) > 1e-9:
            # result quantity (two radii + length determine it), so data
            add(sid + "_HA", r["half_angle_deg"], "deg", "data",
                "face_group %s" % sid, "medium", sid,
                derived_from=[sid + "_R", sid + "_L"])
        add(sid + "_L", abs(r["extent"][1] - r["extent"][0]), "mm", "design",
            "face_group %s" % sid, "high", sid)
        add(sid + "_AXIS", r["axis"], "unit", "data",
            "face_group %s" % sid, "high", sid)
        add(sid + "_POS", r["point"], "mm", "data",
            "face_group %s" % sid, "high", sid)
    for b in directory["bands"]:
        sid = b["id"]
        add(sid + "_OFF", b["offset"], "mm", "design",
            "plane_family %s" % sid, "high", sid)
        if b["thickness_after"] is not None:
            add(sid + "_T", b["thickness_after"], "mm", "design",
                "plane_family %s" % sid, "high", sid,
                derived_from=[sid + "_OFF"])
        add(sid + "_BBOX", b["bbox"], "mm", "data",
            "plane_family %s" % sid, "high", sid)
    for h in directory["holes"]:
        if h["confidence"] != "high":
            continue
        sid = h["id"]
        add(sid + "_R", h["radius"], "mm", "design",
            "hole_audit %s" % sid, "high", sid)
        add(sid + "_L", h["length"], "mm", "design",
            "hole_audit %s" % sid, "high", sid)
        add(sid + "_AXIS", h["axis"], "unit", "data",
            "hole_audit %s" % sid, "high", sid)
        add(sid + "_CTR", h["center"], "mm", "data",
            "hole_audit %s" % sid, "high", sid)
    return rows


def _plane_bbox_hit(normal, offset, bbox):
    """平面是否与轴对齐包围盒相交（用 8 个角的法向投影区间判）。

    比"过世界原点的投影点是否落在盒内"正确：后者对远离原点的结构会给假
    missing/假覆盖率，且与"结构有没有被切到"无关。
    """
    if not bbox:
        return None
    lo = bbox[:3]
    hi = bbox[3:]
    proj = []
    for k in range(8):
        proj.append(sum(normal[i] * (hi[i] if (k >> i) & 1 else lo[i])
                        for i in range(3)))
    return min(proj) - 1e-9 <= offset <= max(proj) + 1e-9


def station_plan_full(measure, structures=None, fillet_faces=None,
                      min_families=2):
    """全集测站（不截断）+ 按结构几何的覆盖检查。

    structures: [{id, bbox, faces}]。覆盖用**面归属**判：测站的 `sources`
    （`plane#<N>` / `axis#<gi>`）解析回面 tag / 同轴组，再看该站是否被结构
    面集合解释；`bbox_plane_hit` 另作诊断（平面是否与结构盒相交）。
    每个结构至少一站、整表至少跨 `min_families` 个平面族（法向族），
    `missing` 非空 → `complete=False`——覆盖缺口不是通过。
    """
    plan = ms.station_plan(measure, max_stations=0)
    out = dict(plan)
    out["budget_truncated"] = False
    faces = measure["faces"]

    # plane#N -> face tag (N counts PLANE faces in face-list order)
    plane_tag = []
    for f in faces:
        if f.get("type") == ms.PLANE:
            plane_tag.append(int(f["tag"]))
    groups = list(measure.get("cylinders", [])) + \
        list(measure.get("cones", []))
    group_faces = [set(int(t) for t in g["faces"]) for g in groups]

    fillet_faces = set(int(t) for t in (fillet_faces or ()))

    def stations_of(face_set):
        ids = []
        for i, st in enumerate(out["stations"]):
            for s in st.get("sources", []):
                if s.startswith("plane#"):
                    k = int(s.split("#")[1])
                    if k < len(plane_tag) and plane_tag[k] in face_set:
                        ids.append(i)
                        break
                elif s.startswith("axis#"):
                    gi = int(s.split("#")[1])
                    if gi < len(group_faces) and group_faces[gi] and \
                            group_faces[gi] <= face_set:
                        ids.append(i)
                        break
        return ids

    fam_of = {}
    for i, st in enumerate(out["stations"]):
        key = ms._axis_key(st["normal"])
        fam_of[i] = key
        if st.get("kind") == "axis":
            gis = [int(s.split("#")[1]) for s in st.get("sources", [])
                   if s.startswith("axis#")]
            if gis and all(gi < len(group_faces) and group_faces[gi] and
                           group_faces[gi] <= fillet_faces for gi in gis):
                st["primary_fillet_class"] = "fillet"
            else:
                st["primary_fillet_class"] = "primary"
        else:
            st["primary_fillet_class"] = "primary"
        st["station_kind"] = st.get("kind")

    overall_families = sorted(set(fam_of.values()))
    out["plane_families"] = overall_families
    out["families_ok"] = len(overall_families) >= min_families
    out["min_families"] = min_families
    if not structures:
        out["structure_coverage"] = {}
        out["missing"] = []
        out["complete"] = bool(out["stations"])
        out["plan_quality_ok"] = out["complete"] and out["families_ok"]
        return out

    cover = {}
    detail = {}
    for s in structures:
        sid = s.get("id")
        fs = set(int(t) for t in (s.get("faces") or ()))
        ids = stations_of(fs) if fs else []
        cover[sid] = len(ids)
        hits = 0
        for i in ids:
            st = out["stations"][i]
            st.setdefault("structures", []).append(sid)
        if s.get("bbox"):
            for st in out["stations"]:
                n = _unit([float(x) for x in st["normal"]])
                off = _dot([float(x) for x in st["origin"]], n)
                if _plane_bbox_hit(n, off, [float(x) for x in s["bbox"]]):
                    hits += 1
        fams = sorted(set(fam_of[i] for i in ids))
        detail[sid] = {"stations": ids, "n_stations": len(ids),
                       "plane_families": fams,
                       "n_families": len(fams),
                       "bbox_plane_hit": hits,
                       "has_faces": bool(fs)}
    out["structure_coverage"] = cover
    out["structure_detail"] = detail
    missing = sorted([k for k, v in cover.items() if v == 0])
    out["missing"] = missing
    out["missing_families"] = sorted(
        [k for k, v in detail.items() if v["n_families"] < min_families])
    # complete = every structure is sampled by at least one station;
    # families_ok = the table spans enough normal families that a shape error
    # cannot hide in a degenerate one-family plan.  Reported separately: a part
    # with a single plane family is fully covered yet still a weak plan.
    out["complete"] = bool(out["stations"]) and not missing
    out["plan_quality_ok"] = out["complete"] and out["families_ok"]
    return out


def interface_table(measure, part, audit=None):
    """孔/锥/座锥分母的机器可读投影（含未分类，不静默丢）。"""
    if audit is None:
        audit = ms.hole_audit(measure, part)
    rows = []
    for k, g in enumerate(audit["denominator"]):
        rows.append({
            "id": "H%03d" % (k + 1),
            "role": "hole" if g.get("kind") == ms.CYLINDER else "tapered_hole",
            "radius": round(float(g["radius"]), 6),
            "axis": [round(float(x), 6) for x in g["axis"]],
            "center": [round(float(x), 6) for x in g["center"]],
            "length": round(float(g["length"]), 6),
            "faces": [int(x) for x in g["faces"]],
            "confidence": "high",
        })
    for k, g in enumerate(audit["unclassified"]):
        rows.append({
            "id": "U%03d" % (k + 1),
            "role": "unclassified",
            "radius": round(float(g["radius"]), 6),
            "axis": [round(float(x), 6) for x in g["axis"]],
            "center": [round(float(x), 6) for x in g["center"]],
            "length": round(float(g["length"]), 6),
            "faces": [int(x) for x in g["faces"]],
            "confidence": "low",
        })
    return {
        "rows": rows,
        "denominator": audit["total"],
        "unclassified": len(audit["unclassified"]),
        "mouth_cones": audit["mouth_cones"],
    }


def fillet_radius_seed(faces, max_ratio=0.25, min_faces=2):
    """圆角半径候选：环面 minor 半径 + 小半径圆柱（支撑过滤在后面做）。

    环面 minor 是圆角/过渡面的直接证据；直边圆角在原件上常被布尔切成圆柱
    面，所以再补"数量 ≥ min_faces 且 ≤ max_ratio×最大圆柱半径"的圆柱半径。
    孔壁/凸台会在 fillet_run_samples(fillet_only=True) 里被支撑面筛掉。
    """
    seed = set()
    hist = {}
    rmax = 0.0
    for f in faces:
        if f.get("type") == ms.TORUS:
            r = abs(float(f.get("rad_data", 0.0)))
            if r > 1e-6:
                seed.add(round(r, 3))
        elif f.get("type") == ms.CYLINDER:
            r = abs(float(f.get("radius", 0.0)))
            if r > 1e-6:
                hist[round(r, 3)] = hist.get(round(r, 3), 0) + 1
                rmax = max(rmax, r)
    if seed:
        # 同族的直边段可能被布尔切成圆柱面：只补与环面 minor 同半径的圆柱。
        for r, n in hist.items():
            if any(abs(r - t) <= 0.05 for t in seed):
                seed.add(r)
        return sorted(seed)
    for r, n in hist.items():
        if n >= min_faces and r <= max_ratio * rmax:
            seed.add(r)
    return sorted(seed)


def runway_table(part, faces, radii=None):
    """圆角跑道表：同半径连通跑道 + 支撑对 + G7 可达上限 + 方法建议。

    可达上限沿用 measure.g7_reachability 的口径：一条跑道最多由一个解析面
    覆盖，所以 ceiling = 跑道数 / 圆角面数。方法建议只是路由起点，实际提交
    仍按 0 告警/0 回滚/还原逐位验证。
    """
    use_radii = list(radii) if radii is not None else fillet_radius_seed(faces)
    fmap = ms.fillet_map(faces, radii=use_radii)
    runs = (ms.fillet_run_samples(part, faces, use_radii,
                                  fillet_only=True) if use_radii else [])
    total_faces = sum(int(r["nfaces"]) for r in runs)
    rows = []
    for k, r in enumerate(runs):
        sup = r.get("supports", [])
        sup_types = [s[0].split("/")[0] for s in sup]
        if r["nfaces"] <= 2 and "22" in sup_types:
            method = "face_blend"
        elif r["radius"] and r["nfaces"] >= 2 and len(sup) >= 2:
            method = "face_blend_or_roll"
        else:
            method = "transition"
        rows.append({
            "id": "W%03d" % (k + 1),
            "radius": round(float(r["radius"]), 6),
            "nfaces": int(r["nfaces"]),
            "bbox": [round(float(x), 6) for x in r["bbox"]],
            "faces": [int(x) for x in r["faces"]],
            "supports": sup,
            "method_suggestion": method,
            "status": "UNASSESSED",
        })
    return {
        "radii": [round(float(x), 6) for x in use_radii],
        "runs": rows,
        "run_count": len(rows),
        "fillet_faces": total_faces,
        "ceiling": (float(len(rows)) / total_faces if total_faces else 0.0),
        "radius_groups": fmap,
    }


def fillet_group_indexes(measure, fillet_faces):
    """面全部落在圆角带内的柱/锥组索引（组序 = cylinders 后接 cones）。

    测站分类只认这条规则：一个轴站的源组全是圆角带组时，它切的是圆角带
    截面，归 G7 跑道账本；否则归主结构截面。
    """
    groups = list(measure.get("cylinders", [])) + list(measure.get("cones", []))
    fillet_faces = set(int(t) for t in (fillet_faces or ()))
    out = []
    for gi, g in enumerate(groups):
        fs = set(int(t) for t in g["faces"])
        if fs and fs <= fillet_faces:
            out.append(gi)
    return out


def station_partition(measure, plan, fillet_faces):
    """测站 → (primary|fillet, 依据)。轴站源组全在圆角带内才记 fillet。"""
    fillet_groups = set(fillet_group_indexes(measure, fillet_faces))
    stations = plan["stations"] if isinstance(plan, dict) else plan
    out = []
    for i, st in enumerate(stations):
        gis = [int(s.split("#")[1]) for s in st.get("sources", [])
               if s.startswith("axis#")]
        cls = "primary"
        basis = "plane station" if st.get("kind") == "plane" else "axis station"
        if st.get("kind") == "axis" and gis and \
                all(gi in fillet_groups for gi in gis):
            cls = "fillet"
            basis = "all source groups are fillet bands"
        out.append({"i": i, "class": cls, "source_groups": gis,
                    "basis": basis})
    return out


def validate_structure_table(structures, measure, tol=0.05,
                             allow_unassigned=None):
    """冻结结构表校验：面 tag 存在、bbox 可复算、结构间不重叠、面无遗漏。

    返回 {errors, warnings, rows, unassigned, complete}。**errors 是硬错误**：
    未知面、面被两个结构同时占用、bbox 与实测差 > tol、结构无面、以及
    未被任何结构解释的功能面（`allow_unassigned` 可显式列出允许豁免的面，
    例如测量辅助面）。把未分配面只写成 warnings，会让"结构覆盖大量为空"
    照样通过验证。
    """
    faces = measure["faces"]
    by_tag = dict((f["tag"], f) for f in faces)
    errors = []
    warnings = []
    used = {}
    rows = []
    for s in structures:
        tags = [int(t) for t in s.get("faces", [])]
        missing = [t for t in tags if t not in by_tag]
        if missing:
            errors.append({"structure": s.get("id"), "missing_faces": missing[:20],
                           "n_missing": len(missing)})
        present = [by_tag[t] for t in tags if t in by_tag]
        for t in tags:
            if t in used:
                errors.append({"structure": s.get("id"),
                               "face_overlap": t,
                               "other": used[t]})
            else:
                used[t] = s.get("id")
        bbox = _bbox_union(present)
        declared = s.get("bbox")
        bbox_delta = None
        if declared and bbox:
            bbox_delta = max(abs(declared[i] - bbox[i]) for i in range(6))
            if bbox_delta > tol:
                errors.append({"structure": s.get("id"),
                               "bbox_delta": round(bbox_delta, 6)})
        rows.append({"id": s.get("id"), "faces": len(tags),
                     "bbox": bbox,
                     "bbox_delta": (round(bbox_delta, 6)
                                    if bbox_delta is not None else None)})
        if not tags:
            errors.append({"structure": s.get("id"), "reason": "no faces"})
    exempt = set(int(t) for t in (allow_unassigned or ()))
    unassigned = sorted(set(by_tag) - set(used) - exempt)
    if unassigned:
        errors.append({"reason": "faces not assigned to any structure",
                       "count": len(unassigned),
                       "sample": unassigned[:20]})
    if exempt:
        warnings.append({"reason": "faces explicitly exempted",
                         "count": len(exempt & set(by_tag)),
                         "sample": sorted(exempt & set(by_tag))[:20]})
    return {"errors": errors, "warnings": warnings, "rows": rows,
            "assigned_faces": len(used), "total_faces": len(faces),
            "unassigned": unassigned, "complete": not errors}


def validate_feature_mapping(part, structures):
    """特征名 → 结构 id 的映射校验（G9 的分母来源）。

    每个结构 id 至少要有一个以该 id 开头的特征名；空特征名记错。只数特征
    总数会让"74 个无名 extrude"通过。
    """
    ids = []
    for s in structures or []:
        if isinstance(s, dict) and s.get("id"):
            ids.append(s["id"])
    names = []
    unnamed = []
    for f in part.Features:
        try:
            nm = f.Name or ""
        except Exception:
            nm = ""
        names.append(nm)
        if not nm.strip():
            unnamed.append(int(getattr(f, "Tag", 0)))
    unmapped = [sid for sid in ids
                if not any(nm.startswith(sid) for nm in names)]
    errors = []
    if unnamed:
        errors.append({"reason": "features with empty names",
                       "count": len(unnamed), "sample": unnamed[:20]})
    if unmapped:
        errors.append({"reason": "structures without a named feature",
                       "structures": unmapped})
    return {"errors": errors, "structure_ids": ids,
            "mapped": len(ids) - len(unmapped), "unmapped": unmapped,
            "unnamed": unnamed, "feature_count": len(names),
            "complete": not errors}


def schema_skeleton(structures, params, build_order=None):
    """结构表 + 参数候选 → schema 骨架（design 进 parameters，data 进 data）。"""
    by_struct = {}
    for p in params:
        by_struct.setdefault(p.get("structure", ""), []).append(p)
    out = {"units": "mm", "structures": [], "build_order": list(build_order or [])}
    for s in structures:
        sid = s.get("id")
        ps = by_struct.get(sid, [])
        out["structures"].append({
            "id": sid,
            "name": s.get("name", sid),
            "template": s.get("template", "unassigned"),
            "depends_on": list(s.get("depends_on", [])),
            "bbox": s.get("bbox"),
            "parameters": [p["name"] for p in ps if p["kind"] == "design"],
            "data": [p["name"] for p in ps if p["kind"] == "data"],
        })
    if not out["build_order"]:
        out["build_order"] = [s["id"] for s in out["structures"]]
    return out
