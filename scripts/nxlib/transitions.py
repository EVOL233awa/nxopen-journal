# -*- coding: utf-8 -*-
"""过渡规划：参考圆角跑道 → 机制决策 + 逐跑道账本。

与 `nxlib.structures.fillet_run` 的分工：那边**执行**倒圆并记账，这里**决定
用哪种机制**、以及为什么不可达。为什么单独一层：

* `fillet_run` 只有拿到边才知道能不能倒；跑道的不可达原因是拓扑的（支撑面
  太窄、二面角超出范围、开链端点在棱上、闭合整圆要走面圆角），这些判据要
  在有支撑面几何的时候就下，而不是试一把失败再归因。
* G7 的 BLOCKED 只允许在逐跑道有拓扑证据时使用（见
  `references/reverse-engineering.md` §4.1）。这个模块产出的 `evidence`
  就是那份证据；没有证据的跑道一律 FAIL，不许写成 BLOCKED。

机制选择只用支撑面构成判（不写零件常数）：

* 两侧都是解析面（平面/柱/锥/环）且都相切 → `face_blend`（NX 的面圆角，
  半径随支撑面走，比边圆角稳）；
* 平面-平面开链 → `roll_edge/apply_roll`（`EdgeBlend` 在开放链上会留
  `Unable to terminate the blend faces`）；
* 闭合整圆（跑道首尾相接且支撑是同一对） → `rolling.apply_roll_general`；
* 支撑面之一是管道/球角 → §9.7 的球角；
* 其余 → `measured_section`（按测量截面重建长条，§9.8）。

不可达判据（每条都写进 `reason`）：

* 支撑面宽度 < R（圆角要在两侧各吃掉一个 R，撑不住就 NX 报
  `Radius is too large`，真正的原因是宽度）；
* 二面角不在 20°–160°（更尖的边倒圆会自交，更平的边没有料可去）。

跑道长度（容不容得下一个常半径圆角）不在这里判：`plan_runway` 的判据里
没有那条边的长度（run 行虽带 `samples`/`bbox`，计划层没把它做成长度判据），
所以它不产出 length 原因；那一档由 `structures.fillet_feasible` 的
`min_len_factor=0.5` 按边几何给。

只读：不吃 part 的写操作，不建几何、不改表达式。
"""
import math

import nxlib.measure as ms
import nxlib.reverse as rv

# 通用阈值（不含任何零件量值）
DIHEDRAL_RANGE = (20.0, 160.0)


def _round(v, nd=6):
    """定量输出：-0.0 归一（判据 JSON 要可复现）。"""
    r = round(float(v), nd)
    return 0.0 if r == 0.0 else r


def _dot(a, b):
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _unit(v):
    """单位向量；零向量返回零向量。"""
    n = math.sqrt(sum(float(x) ** 2 for x in v))
    return [float(x) / n for x in v] if n > 1e-12 else [0.0, 0.0, 0.0]


def _dihedral(face_a, face_b):
    """平面-平面支撑的二面角（度）；调用点只传 PLANE 型支撑，其余 None。"""
    ta = face_a.get("type")
    tb = face_b.get("type")
    na = face_a.get("dir") or [0.0, 0.0, 1.0]
    nb = face_b.get("dir") or [0.0, 0.0, 1.0]
    if ta == ms.PLANE and tb == ms.PLANE:
        d = abs(sum(float(na[i]) * float(nb[i]) for i in range(3)))
        d = max(-1.0, min(1.0, d))
        return 180.0 - math.degrees(math.acos(d))
    return None


def _support_face(f, g, radius):
    """邻面是否可能是跑道支撑面：曲面留给同半径筛，平面按与跑道轴的几何关系判。

    柱/锥跑道的支撑平面与跑道轴平行（法向垂直于轴）；环面跑道的支撑平面
    垂直于环轴，且与环面中心面相距一个管半径（即圆角半径）。
    平面端面因此被排除：它与柱/锥轴不垂直、与环轴不平行。
    """
    gt = g.get("type")
    if gt in (ms.CYLINDER, ms.CONE, ms.TORUS, ms.SPHERE):
        return True
    if gt != ms.PLANE:
        return False
    n = _unit(g.get("dir") or [0.0, 0.0, 1.0])
    ax = _unit(f.get("dir") or [0.0, 0.0, 1.0])
    along = abs(_dot(n, ax))
    ft = f.get("type")
    if ft in (ms.CYLINDER, ms.CONE):
        return along < 0.5
    if ft == ms.TORUS:
        if abs(along - 1.0) > 0.01:
            return False
        gp = g.get("point") or [0.0, 0.0, 0.0]
        fp = f.get("point") or [0.0, 0.0, 0.0]
        gap = abs(_dot(n, [float(gp[i]) - float(fp[i]) for i in range(3)]))
        return abs(gap - radius) <= 0.05
    return False


def _face_width(face):
    """面在自身平面内的较小跨度：包围盒两维投影到面内后取小值。

    平面的包围盒有一个维度是法向厚度（≈0），另两维就是面内跨度。不能用
    "排序后取中间值"：那要求包围盒恰好轴对齐，而斜置的窄壁排序后可能把
    真实的窄边排到最小位当成"法向厚度"丢掉（`[-5,0,0,5,2,10]` 这样的壁，
    三个维度 2/10/10，排序后丢掉的是真实的 2）。

    所以按面法向去掉法向分量：把包围盒的三个边长分别投影到面内两轴，取
    两个面内跨度里的小值。这个估计**不是上界**：轴对齐矩形面精确、曲面偏大，
    但斜置窄壁会严重低估——实测 10 mm 宽的 45° 支撑算得 2.93 mm（`dims[i]`
    取的是包围盒全局轴跨度，乘 `1-|n[i]|` 把斜面的面内长度也压掉了）。因此
    它只用于"宽度是否撑得住 R"这一档粗判；边界上的跑道必须回到
    `structures.fillet_feasible` 按边几何复算。
    """
    box = face.get("box")
    n = face.get("dir")
    if not box or not n:
        return None
    norm = math.sqrt(sum(float(x) ** 2 for x in n))
    if norm <= 1e-12:
        return None
    n = [float(x) / norm for x in n]
    dims = [abs(box[3] - box[0]), abs(box[4] - box[1]), abs(box[5] - box[2])]
    # 每个轴向上的边长在法向上的占比：越接近法向，越不代表面内跨度
    in_plane = [dims[i] * (1.0 - abs(n[i])) for i in range(3)]
    in_plane = [d for d in in_plane if d > 1e-9]
    return min(in_plane) if in_plane else None


def plan_runway(run, faces_by_tag, radius=None):
    """一条参考跑道 → 机制 + 可达性 + 证据。

    run: `measure.fillet_run_samples` 的一行（radius/nfaces/faces/centers/
         samples/supports/bbox）。
    faces_by_tag: 参考件的面表字典，用来读支撑面的几何。
    """
    r = abs(float(radius if radius is not None else run.get("radius") or 0.0))
    out = {
        "radius": round(r, 6),
        "nfaces": int(run.get("nfaces", 0)),
        "faces": [int(t) for t in (run.get("faces") or [])],
        "mechanism": None,
        "reachable": True,
        "reasons": [],
        "supports": [],
        "evidence": None,
    }
    sup = list(run.get("supports") or [])
    sup_recs = []
    for key, count in sup:
        parts = str(key).split("/")
        try:
            ftype = int(parts[0])
        except (ValueError, IndexError):
            ftype = None
        srad = None
        for p in parts[1:]:
            if p.startswith("R"):
                try:
                    srad = float(p[1:])
                except ValueError:
                    srad = None
        sup_recs.append({"key": key, "type": ftype, "radius": srad,
                         "count": int(count)})
    out["supports"] = sup_recs

    # 宽度与二面角：只用能读到的支撑面几何判
    runway_faces = set(int(t) for t in (run.get("faces") or []))
    sup_faces = []
    seen = set()
    for tag in (run.get("faces") or []):
        f = faces_by_tag.get(int(tag))
        if f is None:
            continue
        for e in f.get("edges", []):
            for t in e.get("faces", []):
                t = int(t)
                if t in seen or t in runway_faces:
                    continue
                g = faces_by_tag.get(t)
                if g is not None and _support_face(f, g, r):
                    seen.add(t)
                    sup_faces.append(g)

    # 支撑面里必须剔除**同半径延续**：一条圆角被布尔切成两段时，两段半径
    # 与圆心几乎重合，同半径的两段会互相成为"邻面"，于是二面角算出 180°
    # （共面），把它当成拓扑不可达就把每条被切开的圆角都判成 BLOCKED。判据
    # 用半径而非类型：环面（type 19）只是圆角的一种表达，圆角也可能是同半径
    # 的圆柱面（§9.2）。
    supports_only = []
    for f in sup_faces:
        if int(f.get("tag", -1)) in runway_faces:
            continue
        fr = (abs(float(f.get("rad_data") or 0.0))
              if f.get("type") == ms.TORUS
              else abs(float(f.get("radius") or 0.0)))
        if fr > 0.0 and ms.same_radius_continuation(fr, r):
            continue          # 同半径延续，不是支撑面
        supports_only.append(f)
    widths = [w for w in (_face_width(f) for f in supports_only) if w]
    if widths and r > 0.0:
        # 一个滚球圆角只需要**两侧各一条**撑得住的面，不是要求每个邻面都宽。
        # 一条跑道的邻面常常有几十个（尽端面、侧壁、相邻跑道），按"最窄的
        # 那个邻面"判会把绝大多数跑道判成障碍：实测 114 条里 88 条被这样标
        # 记，而其中 43 条其实有两条合格支撑。
        #
        # 每个支撑面要承担一个 roll 半径，所以门槛是 R（不是 2R：
        # 那个两倍半径的余量是给"每个面都要独立撑 2R"的误读，与
        # `structures.fillet_feasible` 的单面判据一致）。
        need = r
        adequate = [w for w in widths if w >= need]
        if len(adequate) < 2:
            out["reachable"] = False
            out["reasons"].append(
                "only %d support(s) wide enough (%.3f each, need %d "
                "supports each >= R = %.3f); widest=%.3f"
                % (len(adequate),
                   max(adequate) if adequate else 0.0, 2,
                   need, max(widths)))
        out["support_widths"] = [_round(w) for w in sorted(widths, reverse=True)]
        out["support_need"] = _round(need)

    plane_sups = [f for f in supports_only if f.get("type") == ms.PLANE]
    if len(plane_sups) >= 2:
        ang = _dihedral(plane_sups[0], plane_sups[1])
        if ang is not None:
            lo, hi = DIHEDRAL_RANGE
            if not (lo <= ang <= hi):
                out["reachable"] = False
                out["reasons"].append(
                    "dihedral %.2f deg outside [%.0f, %.0f]"
                    % (ang, lo, hi))

    # 机制选择
    closed = bool(run.get("closed"))
    n_plane = len([f for f in sup_faces if f.get("type") == ms.PLANE])
    n_curved = len([f for f in sup_faces
                    if f.get("type") in (ms.CYLINDER, ms.CONE, ms.TORUS)])
    if closed and len(sup_faces) >= 2 and r > 0.0:
        mech = "roll_general"
    elif n_plane == 2 and n_curved == 0:
        mech = "roll_edge"
    elif n_plane >= 1 and n_curved >= 1:
        mech = "face_blend"
    elif n_curved >= 2:
        mech = "face_blend"
    else:
        mech = "measured_section"
    out["mechanism"] = mech

    # 不可达分两档，只有第二档能进 G7 的 BLOCKED：
    #
    #  * 宽度不足是**构建约束**——NX 的圆角要在支撑面上各吃掉一个 R，支撑比
    #    R 窄时倒不出来。但参考件自己的圆角已经存在，所以"宽度不足"证明
    #    的是"复刻难"而不是"这处圆角物理上不可达"。这一档记 `build_obstacle`，
    #    是构建阶段的行动项（改支撑/改刀），不构成 BLOCKED 证据。
    #  * 二面角越界是**拓扑不可达**——近共面缝、相切缝无论用什么机制都不该
    #    倒，这才是 BLOCKED 的证据。
    if not out["reachable"]:
        topo = [x for x in out["reasons"] if x.startswith("dihedral")]
        out["build_obstacle"] = {
            "runway_faces": out["faces"],
            "radius": out["radius"],
            "reason": "; ".join(out["reasons"]),
            "supports": [s["key"] for s in sup_recs],
        }
        if topo:
            out["evidence"] = {
                "runway_faces": out["faces"],
                "radius": out["radius"],
                "reason": "; ".join(topo),
                "supports": [s["key"] for s in sup_recs],
            }
    return out


def transitions_plan(part, measure, radii=None, fillet_faces=None):
    """整件过渡计划：每条跑道一行，带机制/可达性/证据 + 汇总。

    返回：
      runs: [{radius, nfaces, faces, mechanism, reachable, reasons, evidence}]
      by_mechanism: {机制: 跑道数}
      unreachable: 有拓扑证据的不可达跑道（`evidence` 非空）
      status: "ok" / "unreachable" / "empty"
    """
    faces = measure.get("faces", [])
    faces_by_tag = dict((int(f.get("tag", -1)), f) for f in faces)
    use_radii = list(radii) if radii is not None else \
        [r for r in (rv.fillet_radius_seed(faces) or [])]
    if not use_radii:
        return {"runs": [], "by_mechanism": {}, "unreachable": [],
                "status": "empty", "radii": []}
    ref_runs = ms.fillet_run_samples(part, faces, use_radii, fillet_only=True)
    if fillet_faces:
        keep = set(int(t) for t in fillet_faces)
        ref_runs = [r for r in ref_runs
                    if set(int(t) for t in r["faces"]) & keep]
    rows = [plan_runway(r, faces_by_tag) for r in ref_runs]
    by_mech = {}
    for row in rows:
        by_mech[row["mechanism"]] = by_mech.get(row["mechanism"], 0) + 1
    unreachable = [r for r in rows if r.get("evidence")]
    obstacles = [r for r in rows if r.get("build_obstacle")]
    return {
        "radii": sorted(round(abs(float(x)), 6) for x in use_radii),
        "runs": rows,
        "run_count": len(rows),
        "by_mechanism": by_mech,
        "unreachable": unreachable,
        "build_obstacles": obstacles,
        "reachable_count": len(rows) - len(obstacles),
        "status": ("unreachable" if unreachable else
                   ("obstructed" if obstacles else
                    ("ok" if rows else "empty"))),
    }
