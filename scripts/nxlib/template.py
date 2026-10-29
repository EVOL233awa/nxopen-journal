# -*- coding: utf-8 -*-
"""nxlib.template —— 参数化模板层：schema/参数表 → 表达式 → 特征 → 局部编辑检查。

逆向重建的两种产出形态不同：逐结构手工建出的是"过程式 journal"（改一个尺寸
等于重建），参数化模板产出的是"设计意图"（尺寸是命名表达式、派生约束写成公式、
修改走 DoUpdate）。这一层只放与零件无关的机制，零件常数留在调用方的 schema 里：

    doc = template.load_json("schema.json")        # 结构表 + 参数表
    values, units = template.param_table(pdoc)     # {名: 值} / {名: "mm"|"deg"}
    exprs = template.create_expressions(wp, values, units)
    template.derived(wp, "W_LEN", "L_LEN / 2", "Length")   # 派生约束
    ...
    cell = template.edit_check(wp, exprs["L_LEN"], +2.0)   # 编辑-测量-还原

判定口径（与 references/reverse-engineering.md 的参数化模板章节一致）：
  - 参数必须落成命名表达式，派生量必须写成公式（改父参数时子量跟着走）；
  - 一次参数改动只允许影响本结构；edit_check 返回的 bbox/体积/面数差异是
    局部性证据，不是"看起来对"；
  - 告警必须按特征逐个读原文（`alerts`），空告警才算更新成功；
  - 还原后体积/面数必须逐位复原：对不上说明更新过程中几何被重写，
    该参数不适合直接驱动。

实测边界（NX12 批处理，见 references/reverse-engineering.md §11）：
  - 圆柱/圆锥 builder 的轴向点与方向是字面值，改半径不会移动轴心；
    需要"半径变、相切关系不变"时，把相切关系写成派生表达式，或改用
    圆角特征由半径表达式驱动（模板件里根部圆角就是这么处理的）。
  - 边圆角的边引用是拓扑引用：上游尺寸改变重建了那条边，圆角会留下
    "blend edges consumed" 告警且会存盘。先把上游写成派生约束让边不动，
    再考虑把该边排除出圆角集合。
"""
import json

import NXOpen


def load_json(path):
    """读 schema / 参数表 JSON（UTF-8）。"""
    with open(path, "r") as fh:
        return json.load(fh)


def param_table(doc):
    """参数文档 → ({名: 值}, {名: "mm"|"deg"|"unit"}）。

    接受两种布局：
      1) {"structures": [{"id":..., "parameters": [{name,value,unit}, ...]}]}
         （extract_params.py 的输出）
      2) {"name": value, ...}（手写的最小参数表，单位统一按 mm）
    列表/向量值跳过（轴向量不进表达式表，由调用方按几何用）。
    """
    values = {}
    units = {}
    if isinstance(doc, dict) and "structures" in doc:
        for st in doc["structures"]:
            for rec in st.get("parameters", []):
                v = rec.get("value")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    values[rec["name"]] = float(v)
                    units[rec["name"]] = rec.get("unit", "mm")
    else:
        for k, v in doc.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values[k] = float(v)
                units[k] = "mm"
    return values, units


def _unit_for(units, name):
    u = units.get(name, "mm")
    if u == "deg":
        return "Angle"
    if u in ("unit", "ratio", ""):
        return None
    return "Length"


def create_expressions(wp, values, units, skip=()):
    """为每个标量参数建命名表达式，返回 {名: Expression}。

    长度按 Length、角度按 Angle 建；无单位量（"unit"/"ratio"）走
    `CreateSystemExpression("Number", ...)` —— NX12 的
    `GetBase("Number")` 会报 "First parameter is invalid"。
    """
    out = {}
    number = []
    for name in sorted(values):
        if name in skip:
            continue
        u = _unit_for(units, name)
        if u is None:
            number.append((name, values[name]))
            continue
        out[name] = wp.Expressions.CreateSystemExpressionWithUnits(
            name + " = " + repr(float(values[name])),
            wp.UnitCollection.GetBase(u))
    for name, val in number:
        out[name] = wp.Expressions.CreateSystemExpression(
            "Number", name + " = " + repr(float(val)))
    return out


def derived(wp, name, formula, unit_name="Length"):
    """派生表达式：`name = formula`。unit_name=None 走无单位 Number。

    参数之间的约束（相切、等宽、偏置）必须写在这里，不要用两次字面值：
    字面值只在建件那一刻相等，改动父参数后约束就断了。
    """
    text = name + " = " + formula
    if unit_name is None:
        return wp.Expressions.CreateSystemExpression("Number", text)
    return wp.Expressions.CreateSystemExpressionWithUnits(
        text, wp.UnitCollection.GetBase(unit_name))


def build_order(schema):
    """schema 的建件顺序（缺省按 structures 列表顺序）。"""
    order = schema.get("build_order")
    if order:
        return list(order)
    return [st["id"] for st in schema.get("structures", [])]


def structure(schema, sid):
    for st in schema.get("structures", []):
        if st.get("id") == sid:
            return st
    raise KeyError("structure %s not in schema" % sid)


def structure_params(schema, sid):
    """某结构的参数名 → 值（模板注册表里的参数列表）。"""
    return dict(structure(schema, sid).get("parameters", {}))


def structure_template(schema, sid):
    return structure(schema, sid).get("template")


def alerts(part):
    """全部带告警特征：`[{"tag","type","msg"}]`，msg 是原始告警文本。"""
    out = []
    for f in part.Features.GetAllPartFeaturesWithAlerts():
        msgs = []
        try:
            msgs = [str(m) for m in f.GetFeatureWarningMessages()]
        except Exception as exc:
            msgs = ["query_fail:%s" % exc]
        out.append({"tag": int(f.Tag), "type": str(f.FeatureType),
                    "msg": " | ".join(msgs)})
    return out


def update_part(wp, tag):
    """DoUpdate 一次；返回错误数（0 = 无回滚）。"""
    sess = NXOpen.Session.GetSession()
    mark = sess.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, tag)
    try:
        errs = sess.UpdateManager.DoUpdate(mark)
    finally:
        try:
            sess.DeleteUndoMark(mark, None)
        except Exception:
            pass
    return 0 if errs is None else int(errs)


def snapshot(part):
    """体积/实体数/面数/包盒/告警的一次读数，用于编辑前后对比。"""
    uc = part.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter", "Kilogram",
              "MilliMeter", "Newton")]
    vol = 0.0
    nfaces = 0
    lo = [1e18, 1e18, 1e18]
    hi = [-1e18, -1e18, -1e18]
    bodies = list(part.Bodies)
    ufs = NXOpen.UF.UFSession.GetUFSession()
    for b in bodies:
        vol += float(part.MeasureManager.NewMassProperties(
            units, [0.99], [b]).Volume)
        for f in b.GetFaces():
            nfaces += 1
            box = ufs.Modeling.AskFaceData(f.Tag)[3]
            for i in range(3):
                lo[i] = min(lo[i], box[i])
                hi[i] = max(hi[i], box[i + 3])
    return {"volume": round(vol, 6), "bodies": len(bodies), "faces": nfaces,
            "bbox": [round(x, 4) for x in lo + hi], "alerts": alerts(part)}


def diff_snapshot(base, cur):
    """两次 snapshots 的结构化差异：只列变化项，便于逐格记矩阵。"""
    out = {}
    for k in ("volume", "bodies", "faces"):
        if base[k] != cur[k]:
            out[k] = [base[k], cur[k]]
    moved = [(i, round(cur["bbox"][i] - base["bbox"][i], 4))
             for i in range(6)
             if abs(cur["bbox"][i] - base["bbox"][i]) > 1e-4]
    if moved:
        out["bbox_moved"] = moved
    if cur["alerts"]:
        out["alerts"] = cur["alerts"]
    return out


def edit_check(wp, expr, delta, tag="template_edit", probe=None):
    """改一个表达式 → 更新 → 读数 → 还原 → 再读数。

    返回 dict：`update_errors`、`volume_delta`、`edited_diff`、
    `restored_volume_equal`、`restored_faces_equal`、`restored_alerts`；
    传了 `probe` 时还会带 `probe_result`（编辑态下的额外读数，例如派生量
    是否真的跟着走——这些量在还原后就看不到了）。
    `restored_*` 全 True 且两端无告警，才算这个参数可被直接驱动。
    """
    old = expr.RightHandSide
    base = snapshot(wp)
    expr.RightHandSide = "%.6f" % (float(old) + delta)
    errs = update_part(wp, tag + "_e")
    edited = snapshot(wp)
    probe_result = probe(wp) if probe is not None else None
    expr.RightHandSide = old
    errs2 = update_part(wp, tag + "_r")
    back = snapshot(wp)
    return {"param": expr.Equation.split("=")[0].strip(), "delta": delta,
            "probe_result": probe_result,
            "update_errors": errs, "restore_errors": errs2,
            "volume_delta": round(edited["volume"] - base["volume"], 6),
            "edited_diff": diff_snapshot(base, edited),
            "restored_volume_equal":
                abs(back["volume"] - base["volume"]) < 1e-6,
            "restored_faces_equal": back["faces"] == base["faces"],
            "restored_alerts": back["alerts"]}


def edit_matrix(wp, exprs, plan, tag="template_edit"):
    """按 `[(参数名, 幅度)]` 跑 edit_check，返回逐格结果列表。"""
    cells = []
    for name, delta in plan:
        if name not in exprs:
            cells.append({"param": name, "delta": delta,
                          "missing_expression": True})
            continue
        cells.append(edit_check(wp, exprs[name], delta, tag))
    return cells


def clean_cells(cells):
    """矩阵里"0 错误、0 告警、还原逐位一致"的格数 / 总格数。"""
    ok = 0
    for c in cells:
        if c.get("missing_expression"):
            continue
        if (c["update_errors"] == 0 and not c["edited_diff"].get("alerts")
                and c["restored_volume_equal"] and c["restored_faces_equal"]
                and not c["restored_alerts"]):
            ok += 1
    return ok, len(cells)
