# -*- coding: utf-8 -*-
"""审计层：活性、局部性、预算、全集站表 G1full、包络偏差。

全部只读（不保存部件）；`liveness` 与 `locality` 会在内存里改表达式并逐条
还原，和 `measure.expression_survey` 同口径——调用方不要在这些函数之后再
保存该部件。

站表分类（primary/fillet）来自 `reverse.station_partition`，是**开工前**按
原件定的分母，不由构建结果决定；G1full 的硬门只算 primary，fillet 站进
G7 跑道账本。
"""
import nxlib.measure as ms
import nxlib.modeling as mdl
import nxlib.reverse as rv
import nxlib.skeleton as sk

PLANE_DEPTH = 0.5
AXIS_DEPTH = 0.0137
IOU_MIN = 0.95
AREA_ERR_MAX = 5.0


# ------------------------------------------------------------------ G8

def liveness(part, design=None, factor=1.1):
    """G8 存活率，并按结构分组。

    design: {structure_id: [表达式名, ...]}；给了就逐结构核对“声明的设计
    参数都进了 survey”。漏声明/漏建都记 missing，不静默放过。
    """
    survey = ms.expression_survey(part, factor=factor)
    live = dict((r["name"], r["delta_volume"]) for r in survey["live"])
    out = {
        "survey": survey,
        "ratio": survey.get("alive_ratio", 0.0),
        "pass": survey.get("pass", False),
        "structures": {},
        "missing": [],
    }
    if design is None:
        return out
    named = set(survey["named"])
    for sid, names in sorted(design.items()):
        live_n = [n for n in names if n in live]
        dead_n = [n for n in names if n in survey["dead"]]
        broken_n = [n for n in names if any(
            b.get("name") == n for b in survey["broken"])]
        skipped_n = [n for n in names if n in survey["skipped"]]
        missing = [n for n in names if n not in named]
        out["missing"].extend([{"structure": sid, "name": n}
                               for n in missing])
        out["structures"][sid] = {
            "design": list(names),
            "live": live_n,
            "dead": dead_n,
            "broken": broken_n,
            "skipped": skipped_n,
            "missing": missing,
            "delta_volume": dict((n, round(live[n], 6)) for n in live_n),
        }
    return out


# ------------------------------------------------------------------ 局部性

def _mesh(part):
    """部件 → [(法向, v0, v1, v2)]（export_mesh 写 STL，read_stl 读回）。"""
    return ms.read_stl(ms.export_mesh(part))


def locality(part, design, plan, factor=1.5, area_tol=1.0, rel_tol=0.005,
             primary=None, per_structure=1):
    """每结构改一条设计表达式，看主结构测站里谁跟着动。

    design: {structure_id: {"exprs": [...], "stations": [i, ...]}}（站集是
    本结构自己的 primary 站）。判定：主结构站里截面形状变化超过
    max(area_tol, rel_tol*面积) 的站必须 ⊆ 本结构站集；越界站记 outside。

    形状变化用对称差（union - inter，栅格量）而不是有向面积差：截面跨过
    合成裁剪面时轮廓开口，section_area 的带符号面积和会翻号，变化量变成
    噪声（实测 15 个未动站被误判成“变了”）。

    扰动用 ×factor：扫描线截面的量化噪声约等于周长×步长/2，4000 mm² 截面
    上约 30 mm²；locality 测的是“这个参数有没有牵动别的结构”，不是灵敏度；
    灵敏度看 G8 体积增量。changed 为空但体积动了，说明该结构的特征没有站
    采样到（UNCOVERED），不是局部性通过，按覆盖缺口上报。
    细长/微小特征的局部性不靠截面判定（见 references/modeling.md）。
    单条表达式的 update 被 NX 回滚时记 error 并继续（部件已回到改前状态）；
    还原失败直接抛错（部件已不可信）。
    """
    base = _mesh(part)
    bs = list(part.Bodies)
    v0 = mdl.volume(part, bs[0]) if len(bs) == 1 else None
    res = {}
    for sid, rec in sorted(design.items()):
        exprs = rec.get("exprs") or []
        own = set(rec.get("stations") or [])
        rows = []
        for name in exprs[:per_structure]:
            e = None
            for x in part.Expressions:
                try:
                    lhs = x.Equation.split("=")[0].strip()
                except Exception:
                    continue
                if lhs == name:
                    e = x
                    break
            if e is None:
                rows.append({"expr": name, "error": "expression not found"})
                continue
            rhs = e.RightHandSide
            try:
                val = float(rhs)
            except Exception:
                rows.append({"expr": name, "error": "non-numeric rhs"})
                continue
            e.RightHandSide = "%.6f" % (val * factor)
            try:
                errs = ms._do_update("loc_" + name)
            except Exception as exc:
                # NX undid the update: the parameter cannot drive the model at
                # this factor.  Record it and restore instead of aborting the
                # whole audit -- the part is back at the pre-change state.
                e.RightHandSide = rhs
                try:
                    ms._do_update("loc_restore_" + name)
                except Exception:
                    pass
                rows.append({"expr": name,
                             "error": "update rolled back: %s"
                                      % (str(exc).splitlines() or [""])[0],
                             "volume": [None if v0 is None else round(v0, 4),
                                        None]})
                continue
            bs = list(part.Bodies)
            v1 = mdl.volume(part, bs[0]) if len(bs) == 1 else None
            moved = _mesh(part)
            rep = ms.station_report(base, moved, plan, IOU_MIN, AREA_ERR_MAX)
            pool = set(primary) if primary is not None else None
            changed = []
            detail = {}
            for r in rep["stations"]:
                if pool is not None and r["index"] not in pool:
                    continue
                sym = r["area_union"] - r["area_inter"]
                lim = max(area_tol, rel_tol * max(abs(r["area_union"]), 1.0))
                if sym > lim:
                    changed.append(r["index"])
                    detail[r["index"]] = [round(sym, 2), round(r["iou"], 4)]
            outside = [i for i in changed if i not in own]
            rows.append({"expr": name, "errors": errs,
                         "volume": [None if v0 is None else round(v0, 4),
                                    None if v1 is None else round(v1, 4)],
                         "changed_stations": changed,
                         "areas": detail, "outside": outside,
                         "pass": bool(changed) and not outside})
            e.RightHandSide = rhs
            ms._do_update("loc_restore_" + name)
        res[sid] = rows
    return res


# ------------------------------------------------------------------ 预算

def budget(part, n_structures, feature_factor=4.0, feature_offset=12):
    g9 = ms.g9_structure(part, n_structures, feature_factor, feature_offset)
    names = []
    for f in part.Features:
        try:
            names.append(f.Name)
        except Exception:
            continue
    return {
        "feature_count": g9["feature_count"],
        "feature_limit": g9["feature_limit"],
        "max_type_share": g9["max_type_share"],
        "max_type": g9["max_type"],
        "tree_depth": g9["tree_depth"],
        "features": len(names),
        "pass": g9["pass"],
        "reasons": g9["reasons"],
    }


# ------------------------------------------------------------------ 汇总

def summary(part):
    bs = list(part.Bodies)
    body = bs[0] if len(bs) == 1 else None
    box = mdl.body_box(part, body) if body is not None else None
    try:
        alerts = [{"name": f.Name, "type": f.FeatureType}
                  for f in part.Features.GetAllPartFeaturesWithAlerts()]
    except Exception:
        alerts = None
    return {
        "bodies": len(bs),
        "volume": (mdl.volume(part, body) if body is not None else None),
        "bbox": [round(x, 6) for x in box] if box else None,
        "faces": (len(list(body.GetFaces())) if body is not None else 0),
        "features": len(list(part.Features)),
        "alerts": alerts,
        "single_solid": len(bs) == 1,
    }


def envelope(part, ref_box, tol=0.05):
    """G4 口径：包盒位置/尺寸偏差（对单实体）。"""
    s = summary(part)
    box = s["bbox"]
    if not box:
        return {"error": "no single body"}
    pos = max(abs(box[i] - ref_box[i]) for i in (0, 1, 2, 3, 4, 5))
    size_ref = [ref_box[3] - ref_box[0], ref_box[4] - ref_box[1],
                ref_box[5] - ref_box[2]]
    size = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
    size_delta = max(abs(size[i] - size_ref[i]) for i in range(3))
    return {"bbox": box, "ref": [round(float(x), 6) for x in ref_box],
            "position_delta": round(pos, 6), "size_delta": round(size_delta, 6),
            "position_limit": 0.1, "size_limit": 0.3,
            "pass": pos <= 0.1 and size_delta <= 0.3}


# ------------------------------------------------------------------ G1full

def _cut_plan(orig_mesh, plan, plane_depth):
    cut = []
    for st in plan["stations"]:
        origin = [float(x) for x in st["origin"]]
        normal = sk.normalize(st["normal"])
        depth = plane_depth if st.get("kind") == "plane" else AXIS_DEPTH
        sign = 1.0
        if st.get("kind") == "plane":
            plus = [o + depth * n for o, n in zip(origin, normal)]
            minus = [o - depth * n for o, n in zip(origin, normal)]
            a1 = ms.section_area(orig_mesh, plus, normal)
            a2 = ms.section_area(orig_mesh, minus, normal)
            sign = 1.0 if a1 >= a2 else -1.0
        cut.append({
            "origin": [o + sign * depth * n for o, n in zip(origin, normal)],
            "normal": list(normal),
            "sources": list(st.get("sources", [])),
            "kind": st.get("kind"),
            "sign": sign,
            "depth": depth,
        })
    return cut


def g1full(orig_part, built_part, plan, measure, fillet_faces,
           plane_depth=PLANE_DEPTH, iou_min=IOU_MIN,
           area_err_max_pct=AREA_ERR_MAX, meshes=None):
    """全集站表截面比对：原件 vs 自建件，按 primary/fillet 分账。

    平面站从面内 0.5 mm 切（面本身是退化截面，13.7 um 切到的是边界薄片）；
    材料侧由原件截面面积决定（只看原件）。轴站本来就取在中段/端内缩处，
    沿用 13.7 um 偏移避免共面三角。
    """
    if meshes is None:
        mo = _mesh(orig_part)
        mb = _mesh(built_part)
    else:
        mo, mb = meshes
    cuts = _cut_plan(mo, plan, plane_depth)
    rep = ms.station_report(mo, mb, {"stations": cuts, "dropped": 0},
                            iou_min, area_err_max_pct)
    part_rows = rv.station_partition(measure, plan, fillet_faces)
    prim = [r["i"] for r in part_rows if r["class"] == "primary"]
    fil = [r["i"] for r in part_rows if r["class"] == "fillet"]
    failed = set(rep["failed"])
    prim_fail = [i for i in prim if i in failed]
    fil_fail = [i for i in fil if i in failed]
    return {
        "report": rep,
        "partition": part_rows,
        "primary": {"count": len(prim), "failed": prim_fail,
                    "pass": len(prim) - len(prim_fail),
                    "ratio": ((len(prim) - len(prim_fail)) / float(len(prim))
                              if prim else 0.0),
                    "gate_pass": not prim_fail},
        "fillet": {"count": len(fil), "failed": fil_fail,
                   "pass": len(fil) - len(fil_fail),
                   "ratio": ((len(fil) - len(fil_fail)) / float(len(fil))
                             if fil else 0.0)},
        "iou_min": iou_min,
        "area_err_max_pct": area_err_max_pct,
        "plane_depth": plane_depth,
    }


# ------------------------------------------------------------------ 设计包络

def edit_envelope(part, names=None, factor_max=1.5, steps=(1.10, 1.20, 1.25, 1.30,
                                                     1.35, 1.40, 1.45),
             body=None):
    """逐参数测"能改到多远"，把超出设计范围与模型脆弱分开。

    `liveness` 只回答"改 10% 会不会动"，`locality` 只回答"动了谁"。两者都
    不回答"能改多少"：一个把孔半径从 40 改到 60（外径才 52.7）的失败，和
    一条撑不住 20% 的结构，在 ×1.1 普查里长得一模一样。这里对每条表达式
    按 steps 递增改值并 DoUpdate，记下最后一个仍然 update_errors==0 的倍率，
    再还原。

    返回每项 {name, value, max_ok_factor, failed_at, trials}：
    `max_ok_factor` 等于 factor_max 说明到扫描上界都没崩（参数本身不脆），
    小于上界则给出第一次失败的位置与原文——报告据此判"超出物理范围"还是
    "结构脆弱"，不把两者混成一个 broken 计数。
    """
    bs = list(part.Bodies)
    if body is None:
        body = bs[0]
    v0 = mdl.volume(part, body)
    exprs = {}
    for e in part.Expressions:
        try:
            lhs = e.Equation.split("=")[0].strip()
        except Exception:
            continue
        if lhs:
            exprs[lhs] = e
    if names is None:
        names = sorted(exprs)
    out = []
    for name in names:
        e = exprs.get(name)
        rec = {"name": name, "trials": []}
        if e is None:
            rec["error"] = "expression not found"
            out.append(rec)
            continue
        base = e.RightHandSide
        try:
            val = float(base)
        except Exception:
            rec["error"] = "non-numeric rhs"
            out.append(rec)
            continue
        rec["value"] = val
        last_ok = None
        for fac in steps:
            ok = True
            try:
                e.RightHandSide = "%.6f" % (val * fac)
                errs = ms._do_update("env_%s_%d" % (name, int(fac * 100)))
                v1 = mdl.volume(part, body)
                if errs:
                    ok = False
                rec["trials"].append({"factor": fac, "errors": errs,
                                      "delta_volume": v1 - v0})
            except Exception as exc:
                ok = False
                rec["trials"].append({
                    "factor": fac, "errors": "exception",
                    "detail": str(exc).splitlines()[0][:160]})
            finally:
                try:
                    e.RightHandSide = base
                    ms._do_update("env_restore_%s_%d"
                                  % (name, int(fac * 100)))
                except Exception:
                    rec.setdefault("restore_failed_at", []).append(fac)
            if not ok:
                break
            last_ok = fac
        rec["max_ok_factor"] = last_ok
        rec["failed_at"] = None if last_ok == steps[-1] else last_ok
        out.append(rec)
    return {"rows": out, "v0": v0, "v1": mdl.volume(part, body),
            "factor_max": max(steps), "steps": list(steps)}


def edit_envelope_summary(env):
    """把 `edit_envelope` 的输出折成可判的三档。

    - `bounded`：到扫描上界都没崩，参数本身不脆；
    - `narrow`：在上界以下崩了，给出倍率——这一档才是"结构脆弱"；
    - `stuck`：连 ×1.10 都不过。
    `narrow`/`stuck` 都要在报告里逐条写倍率与原文，不能用总数代替。
    """
    bounded, narrow, stuck = [], [], []
    for r in env.get("rows") or []:
        if r.get("error"):
            stuck.append({"name": r["name"], "why": r["error"]})
            continue
        top = r.get("max_ok_factor")
        if top is None:
            stuck.append({"name": r["name"], "why": "no factor resolved"})
        elif r["failed_at"] is None:
            bounded.append(r["name"])
        else:
            narrow.append({"name": r["name"], "max_ok_factor": top,
                           "failed_at": r["failed_at"]})
    return {"bounded": bounded, "narrow": narrow, "stuck": stuck,
            "pass": not stuck}
