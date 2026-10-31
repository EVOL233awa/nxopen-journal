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

PLANE_DEPTH = 0.0137
AXIS_DEPTH = 0.0137
IOU_MIN = 0.95
AREA_ERR_MAX = 5.0


# ------------------------------------------------------------------ G8

def liveness(part, design=None, derived=None, factor=1.1):
    """G8 存活率，并按结构分组。

    design: {structure_id: [表达式名, ...]}；给了就逐结构核对“声明的设计
    参数都进了 survey”。漏声明/漏建都记 missing，不静默放过。

    `pass` 只在这三件事同时成立时为 True：survey 自身通过（单实体/0 告警/
    alive_ratio=1.0）、`missing` 为空、声明的设计参数没有 dead/broken/skipped。
    只取 `survey.pass` 会让“声明 10 条只建了 3 条”的交付件显示通过。
    derived 是不进编辑集的派生量，单列返回，不参与 pass。
    """
    survey = ms.expression_survey(part, factor=factor)
    live = dict((r["name"], r["delta_volume"]) for r in survey["live"])
    broken_names = set(b.get("name") for b in survey["broken"])
    out = {
        "survey": survey,
        "ratio": survey.get("alive_ratio", 0.0),
        "derived": list(derived or []),
        "structures": {},
        "missing": [],
        "declared_dead": [],
        "declared_broken": [],
        "declared_skipped": [],
    }
    if design is None:
        out["pass"] = bool(survey.get("pass", False))
        return out
    named = set(survey["named"])
    dead = set(survey["dead"])
    skipped = set(survey["skipped"])
    for sid, names in sorted(design.items()):
        live_n = [n for n in names if n in live]
        dead_n = [n for n in names if n in dead]
        broken_n = [n for n in names if n in broken_names]
        skipped_n = [n for n in names if n in skipped]
        missing = [n for n in names if n not in named]
        out["missing"].extend([{"structure": sid, "name": n}
                               for n in missing])
        out["declared_dead"].extend([{"structure": sid, "name": n}
                                     for n in dead_n])
        out["declared_broken"].extend([{"structure": sid, "name": n}
                                       for n in broken_n])
        out["declared_skipped"].extend([{"structure": sid, "name": n}
                                        for n in skipped_n])
        out["structures"][sid] = {
            "design": list(names),
            "live": live_n,
            "dead": dead_n,
            "broken": broken_n,
            "skipped": skipped_n,
            "missing": missing,
            "delta_volume": dict((n, round(live[n], 6)) for n in live_n),
        }
    out["pass"] = (bool(survey.get("pass", False)) and
                   not out["missing"] and
                   not out["declared_dead"] and
                   not out["declared_broken"] and
                   not out["declared_skipped"])
    out["structures_without_live"] = sorted(
        sid for sid, rec in out["structures"].items() if not rec["live"])
    return out


# ------------------------------------------------------------------ 局部性

def _mesh(part):
    """部件 → [(法向, v0, v1, v2)]（export_mesh 写 STL，read_stl 读回）。"""
    return ms.read_stl(ms.export_mesh(part))


def _state(part, body=None):
    """可复查的部件快照：体积 / 体数 / 面数 / 告警数。

    还原、包络扫描都在改完参数后比对这份快照；只看体积会漏掉“体数或面数
    变了但体积没变”的拓扑漂移。
    """
    bs = list(part.Bodies)
    if body is None and len(bs) == 1:
        body = bs[0]
    try:
        alerts = len(list(part.Features.GetAllPartFeaturesWithAlerts()))
    except Exception:
        alerts = -1
    return {
        "volume": (round(mdl.volume(part, body), 6)
                   if body is not None else None),
        "bodies": len(bs),
        "faces": (len(list(body.GetFaces())) if body is not None else 0),
        "alerts": alerts,
    }


def _state_matches(a, b, rel_tol=1e-6):
    """快照是否与基线一致（体积按相对容差，其余逐位）。"""
    if (a["bodies"] != b["bodies"] or a["faces"] != b["faces"] or
            a["alerts"] != b["alerts"]):
        return False
    if a["volume"] is None or b["volume"] is None:
        return a["volume"] == b["volume"]
    return abs(a["volume"] - b["volume"]) <= rel_tol * max(abs(b["volume"]), 1.0)


def _expr_map(part):
    out = {}
    for x in part.Expressions:
        try:
            lhs = x.Equation.split("=")[0].strip()
        except Exception:
            continue
        if lhs:
            out[lhs] = x
    return out


def _say(report, msg):
    if report is not None:
        try:
            report(msg)
        except Exception:
            pass


def locality(part, design, plan, factor=None, area_tol=1.0, rel_tol=0.005,
             primary=None, per_structure=None, factors=(1.10, 1.25, 1.50),
             report=None, base_mesh=None, min_area=1.0):
    """每结构改一条设计表达式，看主结构测站里谁跟着动。

    design: {structure_id: {"exprs": [...], "stations": [i, ...]}}（站集是
    本结构自己的 primary 站）。判定：主结构站里截面形状变化超过
    max(area_tol, rel_tol*面积) 的站必须 ⊆ 本结构站集；越界站记 outside。

    形状变化用对称差（union - inter，栅格量）而不是有向面积差：截面跨过
    合成裁剪面时轮廓开口，section_area 的带符号面积和会翻号，变化量变成
    噪声（实测 15 个未动站被误判成“变了”）。

    扰动倍率从 `factors` 由小到大扫（默认 1.10 → 1.25 → 1.50），**首个能
    分辨出变化**（有站越阈）的倍率即被采用并停止扫描；三个倍率都分辨不出
    该参数的影响时记 `inconclusive`，不静默判 pass。`factor` 给定则只用该
    单一倍率。

    `per_structure=None`（默认）测每个结构的全部设计表达式；显式给整数 N
    只测前 N 条，结果带 `partial=True` 说明代表集。

    测站筛选：参考侧轮廓开口（`section_outline(...)["open"] != 0`）或截面
    面积 < `min_area`（退化/近切）的站被剔除并记入 `excluded_stations`；
    这些站的对称差是量化噪声，不能当形状变化。

    单条表达式的 update 被 NX 回滚时记 error 并继续（部件已回到改前状态）；
    还原后校验体积/体数/面数/告警与基线一致，不一致直接抛错（部件已不可信）。
    `report` 是逐条进度回调（每个参数一行），整件长跑时用它落进度日志。
    """
    base = base_mesh if base_mesh is not None else _mesh(part)
    bs = list(part.Bodies)
    v0 = mdl.volume(part, bs[0]) if len(bs) == 1 else None
    if factor is not None:
        scan = [float(factor)]
    else:
        scan = [float(f) for f in factors]
    pool = list(primary) if primary is not None else None
    if pool is None:
        pool = list(range(len(plan["stations"] if isinstance(plan, dict)
                                 else plan)))
    stations = (plan["stations"] if isinstance(plan, dict) else plan)
    usable = []
    excluded = []
    for i in pool:
        st = stations[i]
        out = ms.section_outline(base, st["origin"], st["normal"])
        if int(out.get("open", 0)) > 0:
            excluded.append({"station": i, "reason": "open reference outline"})
        elif len(out["loops"]) == 0:
            excluded.append({"station": i, "reason": "empty reference section"})
        elif abs(out.get("area", 0.0)) < min_area:
            excluded.append({"station": i,
                             "reason": "degenerate/near-tangent section "
                                       "(area < %.3g)" % min_area})
        else:
            usable.append(i)
    _say(report, "locality: pool=%d usable=%d excluded=%d"
         % (len(pool), len(usable), len(excluded)))

    exprs = _expr_map(part)
    res = {}
    base_state = _state(part, bs[0] if len(bs) == 1 else None)
    for sid, rec in sorted(design.items()):
        names = rec.get("exprs") or []
        partial = per_structure is not None and len(names) > per_structure
        if per_structure is not None:
            names = names[:per_structure]
        own = set(rec.get("stations") or [])
        rows = []
        for name in names:
            e = exprs.get(name)
            if e is None:
                rows.append({"expr": name, "error": "expression not found"})
                continue
            rhs = e.RightHandSide
            try:
                val = float(rhs)
            except Exception:
                rows.append({"expr": name, "error": "non-numeric rhs"})
                continue
            row = {"expr": name, "partial": partial,
                   "factor_scan": list(scan), "factor_used": None,
                   "resolvable": False, "changed_stations": [], "outside": [],
                   "inconclusive": False}
            for fac in scan:
                e.RightHandSide = "%.6f" % (val * fac)
                rollback = None
                try:
                    errs = ms._do_update("loc_%s_%d" % (name, int(fac * 100)))
                except Exception as exc:
                    errs = None
                    rollback = str(exc).splitlines() or [""]
                if rollback is not None:
                    e.RightHandSide = rhs
                    try:
                        ms._do_update("loc_restore_%s" % name)
                    except Exception:
                        pass
                    row["error"] = "update rolled back: %s" % rollback[0]
                    row["factor_used"] = fac
                    row["inconclusive"] = True
                    break
                bsx = list(part.Bodies)
                v1 = (mdl.volume(part, bsx[0])
                      if len(bsx) == 1 else None)
                moved = _mesh(part)
                changed = []
                detail = {}
                for i in usable:
                    st = stations[i]
                    r = ms.section_iou(base, moved, st["origin"], st["normal"])
                    sym = r["area_union"] - r["area_inter"]
                    lim = max(area_tol,
                              rel_tol * max(abs(r["area_union"]), 1.0))
                    if sym > lim:
                        changed.append(i)
                        detail[i] = [round(sym, 2),
                                     (round(r["iou"], 4)
                                      if r["iou"] is not None else None)]
                # restore before deciding, and verify the part is intact
                e.RightHandSide = rhs
                ms._do_update("loc_restore_%s" % name)
                st_after = _state(part, bsx[0] if len(bsx) == 1 else None)
                if not _state_matches(st_after, base_state):
                    raise RuntimeError(
                        "locality restore failed for %s: %s vs %s"
                        % (name, st_after, base_state))
                row["factor_used"] = fac
                row["volume"] = [None if v0 is None else round(v0, 4),
                                 None if v1 is None else round(v1, 4)]
                if changed:
                    row["resolvable"] = True
                    row["changed_stations"] = changed
                    row["areas"] = detail
                    row["outside"] = [i for i in changed if i not in own]
                    row["pass"] = not row["outside"]
                    break
                # nothing moved at this factor: remember it and try a larger one
                row["last_factor_all_clean"] = fac
            if not row["resolvable"] and "error" not in row:
                row["inconclusive"] = True
                moved_volume = row.get("volume", [v0, v0])[1]
                row["reason"] = ("no station changed up to x%.2f "
                                 "(UNCOVERED or below resolution)"
                                 % scan[-1])
                if (v0 is not None and moved_volume is not None and
                        abs(moved_volume - v0) > 1e-4):
                    row["reason"] = ("volume moved but no station sampled it "
                                     "(UNCOVERED by the station set)")
            rows.append(row)
        res[sid] = rows
        _say(report, "locality: %s done (%d exprs, %d inconclusive)"
             % (sid, len(rows),
                len([r for r in rows if r.get("inconclusive")])))
    return {"structures": res, "usable_stations": usable,
            "excluded_stations": excluded, "factors": list(scan),
            "per_structure": per_structure}


# ------------------------------------------------------------------ 预算

def budget(part, structures, feature_factor=4.0, feature_offset=12):
    """G9 特征树预算 + 特征名到结构 id 的映射。

    `structures` 可以是冻结结构表（list of {id, ...}）或 `schema_skeleton`
    的输出 dict，也可以仍是结构数（int）。给表时除数量外还校验：
    每个结构 id 至少有一个以该 id 开头的特征名；空特征名一律记错。
    只传数字时结构数是调用方自证，报告里记 `structure_count_source=
    "caller-int"`，不当作已校验。
    """
    ids = []
    source = "caller-int"
    if isinstance(structures, dict):
        rows = structures.get("structures") or []
        ids = [s.get("id") for s in rows if s.get("id")]
        n = len(ids)
        source = "structure_table"
    elif isinstance(structures, (list, tuple)):
        ids = [s.get("id") for s in structures
               if isinstance(s, dict) and s.get("id")]
        n = len(ids)
        source = "structure_table"
    else:
        n = int(structures)
    g9 = ms.g9_structure(part, n, feature_factor, feature_offset)
    names = []
    unnamed = []
    for f in part.Features:
        try:
            nm = f.Name or ""
        except Exception:
            continue
        names.append(nm)
        if not nm.strip():
            unnamed.append(int(getattr(f, "Tag", 0)))
    unmapped = [sid for sid in ids
                if not any(nm.startswith(sid) for nm in names)]
    reasons = list(g9["reasons"])
    if unnamed:
        reasons.append("%d features have empty names" % len(unnamed))
    if unmapped:
        reasons.append("structures without a named feature: %s"
                       % ",".join(unmapped))
    return {
        "feature_count": g9["feature_count"],
        "feature_limit": g9["feature_limit"],
        "max_type_share": g9["max_type_share"],
        "max_type": g9["max_type"],
        "tree_depth": g9["tree_depth"],
        "features": len(names),
        "structure_count_source": source,
        "structure_ids": ids,
        "unnamed": unnamed,
        "unmapped_structures": unmapped,
        "pass": not reasons,
        "reasons": reasons,
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


def envelope(part, ref_box, tol=0.05, source="brep_body_box"):
    """G4 口径：包盒位置/尺寸偏差（对单实体）。

    阈值统一取 `tol`（默认 0.05 mm，与 references/reverse-engineering.md §4.1
    的默认档一致），位置与尺寸同限。`source` 记录数据来源（这里是 NX 的
    单实体包围盒），外部 QA 用导出 STL 顶点口径，两者不同源，报告里必须写清。
    """
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
            "position_limit": tol, "size_limit": tol, "source": source,
            "pass": pos <= tol and size_delta <= tol}


# ------------------------------------------------------------------ G1full

def _cut_plan(orig_mesh, plan, depth):
    """STL 回退路径的切站：平面站与轴站都沿法向偏移 `depth`。

    每个平面站记 `coplanar=True` 与 `offset_mm/offset_dir`：偏移本身是测量
    手段，不是几何事实，报告必须能看出这一站不是名义截面。材料侧由原件
    截面面积决定（只看原件），偏移方向取面积更大的一侧。
    """
    cut = []
    for st in plan["stations"]:
        origin = [float(x) for x in st["origin"]]
        normal = sk.normalize(st["normal"])
        sign = 1.0
        coplanar = st.get("kind") == "plane"
        if coplanar:
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
            "coplanar": coplanar,
            "offset_mm": depth,
            "offset_dir": sign,
        })
    return cut


def g1full(orig_part, built_part, plan, measure, fillet_faces,
           degenerate_offset=AXIS_DEPTH, iou_min=IOU_MIN,
           area_err_max_pct=AREA_ERR_MAX, meshes=None, hybrid=True):
    """全集站表截面比对：原件 vs 自建件，按 primary/fillet 分账。

    平面站默认走 **B-rep 精确截面**（`measure.station_report_hybrid`，站位取
    名义位置），与 `verify_parts` 的 G1 共用同一实现——旧版在这里用 STL 从面内
    0.5 mm 切，与文档 §4.1 的 B-rep 名义站口径不一致，同一件在两条 G1 下读数
    不同。只有部件读不到面表/非 solid 时才退回 STL，此时按 `degenerate_offset`
    (13.7 µm) 偏移并逐站记 `coplanar/offset_mm/offset_dir`。
    轴站本来就取在中段/端内缩处，沿用 13.7 µm 偏移避免共面三角。

    `primary` 为空的分母判**失败**（不是通过）；没量到的站分两类：
    `primary.instrument_errors`（原件有材料却没量到）不让 `gate_pass` 通过，
    `primary.plan_noise`（原件在该站没有材料，如同轴组面间空段）从分母里剔除
    并单列——这类站位对任何自建件都没有读数，若算作必须通过就把门变成永远
    过不去。`ratio` 用"有材料的站"作分母，`ratio_all_stations` 保留全站表
    口径；`plan_complete` 汇总站表截断、结构覆盖缺口与主站仪器误差。
    """
    if meshes is None:
        mo = _mesh(orig_part)
        mb = _mesh(built_part)
    else:
        mo, mb = meshes
    mode = "brep_plane"
    if hybrid:
        try:
            rep = ms.station_report_hybrid(mo, mb, orig_part, built_part, plan,
                                           iou_min, area_err_max_pct)
        except Exception:
            mode = "stl_offset"
            rep = ms.station_report(
                mo, mb,
                {"stations": _cut_plan(mo, plan, degenerate_offset),
                 "dropped": 0},
                iou_min, area_err_max_pct)
    else:
        mode = "stl_offset"
        rep = ms.station_report(
            mo, mb,
            {"stations": _cut_plan(mo, plan, degenerate_offset), "dropped": 0},
            iou_min, area_err_max_pct)
    stations = plan["stations"] if isinstance(plan, dict) else plan
    part_rows = rv.station_partition(measure, plan, fillet_faces)
    prim = [r["i"] for r in part_rows if r["class"] == "primary"]
    fil = [r["i"] for r in part_rows if r["class"] == "fillet"]
    failed = set(rep["failed"])
    # 两侧都空的站没有读数，分两类：`instrument_errors`（原件有材料却没量到，
    # 判定口径没补上）与 `plan_noise`（原件在该站确实没有材料，如同轴组各面
    # 之间的空段）。两者都不算 FAIL；仪器误差让门不通过，"站位空档"从分母里
    # 剔除（否则这类站位对任何自建件都不可达，门变成永远过不去）。
    unmeasured = set(rep.get("unmeasured", []))
    instrument = set(rep.get("instrument_errors", []))
    noise = set(rep.get("plan_noise", [])) or (unmeasured - instrument)
    prim_fail = [i for i in prim if i in failed]
    fil_fail = [i for i in fil if i in failed]
    prim_unmeasured = [i for i in prim if i in unmeasured]
    prim_instrument = [i for i in prim if i in instrument]
    prim_noise = [i for i in prim if i in noise]
    fil_unmeasured = [i for i in fil if i in unmeasured]
    fil_instrument = [i for i in fil if i in instrument]
    fil_noise = [i for i in fil if i in noise]
    prim_denom = len(prim) - len(prim_noise)
    fil_denom = len(fil) - len(fil_noise)
    prim_pass = len(prim) - len(prim_fail) - len(prim_unmeasured)
    fil_pass = len(fil) - len(fil_fail) - len(fil_unmeasured)
    coverage_missing = list(plan.get("missing") or []) \
        if isinstance(plan, dict) else []
    plan_complete = bool(rep.get("plan_complete", False)) and \
        not coverage_missing and not prim_instrument and bool(prim)
    return {
        "report": rep,
        "partition": part_rows,
        "primary": {"count": len(prim), "denominator": prim_denom,
                    "failed": prim_fail,
                    "unmeasured": prim_unmeasured,
                    "instrument_errors": prim_instrument,
                    "plan_noise": prim_noise,
                    "pass": prim_pass,
                    "ratio": (prim_pass / float(prim_denom)
                              if prim_denom else 0.0),
                    "ratio_all_stations": (prim_pass / float(len(prim))
                                           if prim else 0.0),
                    "empty_denominator": not prim,
                    "gate_pass": bool(prim) and not prim_fail
                    and not prim_instrument},
        "fillet": {"count": len(fil), "denominator": fil_denom,
                   "failed": fil_fail,
                   "unmeasured": fil_unmeasured,
                   "instrument_errors": fil_instrument,
                   "plan_noise": fil_noise,
                   "pass": fil_pass,
                   "ratio": (fil_pass / float(fil_denom)
                             if fil_denom else 0.0),
                   "empty_denominator": not fil},
        "iou_min": iou_min,
        "area_err_max_pct": area_err_max_pct,
        "plane_station_mode": mode,
        "degenerate_offset_mm": degenerate_offset,
        "station_count": len(stations),
        "denominator_version": (plan.get("generated_by")
                                if isinstance(plan, dict) else None)
        or "station_plan_full",
        "coverage_missing": coverage_missing,
        "unmeasured": sorted(unmeasured),
        "instrument_errors": sorted(instrument),
        "plan_noise": sorted(noise),
        "plan_measured_complete": rep.get("plan_measured_complete"),
        "plan_complete": plan_complete,
        "brep_plane_count": rep.get("brep_plane_count"),
        "stl_axis_count": rep.get("stl_axis_count"),
    }


# ------------------------------------------------------------------ 设计包络

def edit_envelope(part, names=None, factor_max=1.5, steps=None,
                  body=None):
    """逐参数测"能改到多远"，把超出设计范围与模型脆弱分开。

    `liveness` 只回答"改 10% 会不会动"，`locality` 只回答"动了谁"。两者都
    不回答"能改多少"：一个把孔半径从 40 改到 60（外径才 52.7）的失败，和
    一条撑不住 20% 的结构，在 ×1.1 普查里长得一模一样。这里对每条表达式
    按 `steps` 递增改值并 DoUpdate，记下**首次失败**的倍率，再还原。

    `steps` 缺省由 `factor_max` 推出（1.10…1.50 阶梯并保证含上界）；显式
    传入时 `factor_max` 取 `max(steps)`，两者不再可能不一致。每步还原后
    校验体积/体数/面数/告警与基线一致，不一致直接抛错。

    返回每项 {name, value, max_ok_factor, failed_at, bounded, trials}：
    `failed_at` 是**第一次失败**的倍率（None = 到扫描上界都没崩），
    `max_ok_factor` 是最后一次成功的倍率——报告据此判"超出物理范围"还是
    "结构脆弱"，不把两者混成一个 broken 计数。
    """
    bs = list(part.Bodies)
    if body is None:
        body = bs[0]
    v0 = mdl.volume(part, body)
    base_state = _state(part, body)
    if steps is None:
        steps = tuple(s for s in (1.10, 1.20, 1.25, 1.30, 1.35, 1.40, 1.45,
                                  1.50) if s <= factor_max)
        if not steps or steps[-1] < factor_max:
            steps = tuple(list(steps) + [factor_max])
    else:
        steps = tuple(steps)
        factor_max = max(steps)
    exprs = _expr_map(part)
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
            # restore, then verify the part came back to the baseline state
            e.RightHandSide = base
            try:
                ms._do_update("env_restore_%s_%d" % (name, int(fac * 100)))
            except Exception as exc:
                rec.setdefault("restore_failed_at", []).append(fac)
                raise RuntimeError(
                    "edit_envelope restore failed for %s at x%.2f: %s"
                    % (name, fac, exc))
            st = _state(part, body)
            if not _state_matches(st, base_state):
                raise RuntimeError(
                    "edit_envelope restore drifted for %s at x%.2f: %s vs %s"
                    % (name, fac, st, base_state))
            if not ok:
                # first factor that broke the model motion
                rec["failed_at"] = fac
                break
            last_ok = fac
        rec["max_ok_factor"] = last_ok
        if "failed_at" not in rec:
            rec["failed_at"] = None
        rec["bounded"] = rec["failed_at"] is None
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
