# -*- coding: utf-8 -*-
# Test 35: 装配子件预载 + 干涉检查（nxlib.assembly.preload_components）
#
# 覆盖：
#   * preload_components：收集子件路径并 session.Parts.Open 预载（已加载子件
#     抛 "File already exists" 被吞掉，幂等可重入）——组件体惰性加载下
#     SimpleInterference 不预载会空跑（inst_bodies=0）
#   * 预载后实例体可访问（Prototype.Bodies + FindOccurrence 口径；
#     asm.Bodies 在批处理重开装配下恒为 0，不可用）
#   * GetPosition 读回组件位姿（add_component 显式坐标口径）
#   * SimpleInterference 负例：间隙布置（pin 悬空 5mm）→ 干涉结果 0 对面
#     （⚠ 重合面/零间隙会报"接触=干涉"，语义见 assembly.md）
#   * 嵌套装配：preload_components 只覆盖直接子件；对子装配递归调用后孙件可读
#   * 装配图：standard_views(bbox=assembly_bbox(...)) 在无自有实体的装配件上
#     建出三视图，内容框不越图幅
#
# 成功标志：TEST35_DONE 且无 _FAIL
import os
import sys

import NXOpen
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, stage, check_finish
from nxlib.session import new_part, set_work, save_checked
from nxlib.modeling import block, bodies
from nxlib.assembly import add_component, preload_components, preload_tree
from nxlib import measure
from stl_math import mesh_volume, topology
import gb_drawing as gb

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
BASE_PRT = os.path.join(OUT_DIR, "t35_base.prt")
PIN_PRT = os.path.join(OUT_DIR, "t35_pin.prt")
ASM_PRT = os.path.join(OUT_DIR, "t35_asm.prt")
CAP_PRT = os.path.join(OUT_DIR, "t35_cap.prt")
SUB_PRT = os.path.join(OUT_DIR, "t35_sub.prt")
TOP_PRT = os.path.join(OUT_DIR, "t35_top.prt")

for fp in (BASE_PRT, PIN_PRT, ASM_PRT, CAP_PRT, SUB_PRT, TOP_PRT):
    if os.path.exists(fp):
        os.remove(fp)

session = NXOpen.Session.GetSession()
ufs = NXOpen.UF.UFSession.GetUFSession()
check("PARTS", True, "t35_base / t35_pin / t35_asm / t35_cap / t35_sub / t35_top")


def s_base():
    wp = set_work(new_part(path=BASE_PRT))
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "40", "10")
    assert len(bodies(wp)) == 1
    save_checked(BASE_PRT)


def s_pin():
    wp = set_work(new_part(path=PIN_PRT))
    arc = wp.Curves.CreateArc(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0),
        5.0, 0.0, 2.0 * 3.141592653589793)
    from nxlib.modeling import extrude
    extrude(wp, [arc], "20")
    assert len(bodies(wp)) == 1
    save_checked(PIN_PRT)


def s_asm():
    wp = set_work(new_part(path=ASM_PRT))
    add_component(wp, BASE_PRT, NXOpen.Point3d(0.0, 0.0, 0.0))
    # pin 底在 z=15，base 顶在 z=10 —— 悬空 5mm，无接触无重叠
    add_component(wp, PIN_PRT, NXOpen.Point3d(20.0, 20.0, 15.0))
    wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue)
    save_checked(ASM_PRT)


def s_cap():
    wp = set_work(new_part(path=CAP_PRT))
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "20", "20", "10")
    assert len(bodies(wp)) == 1
    save_checked(CAP_PRT)


def s_sub():
    wp = set_work(new_part(path=SUB_PRT))
    add_component(wp, BASE_PRT, NXOpen.Point3d(0.0, 0.0, 0.0))
    add_component(wp, PIN_PRT, NXOpen.Point3d(20.0, 20.0, 15.0))
    wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue)
    save_checked(SUB_PRT)


def s_top():
    wp = set_work(new_part(path=TOP_PRT))
    add_component(wp, SUB_PRT, NXOpen.Point3d(0.0, 0.0, 0.0))
    add_component(wp, CAP_PRT, NXOpen.Point3d(0.0, 30.0, 10.0))
    wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue)
    save_checked(TOP_PRT)


stage("BUILD_BASE", s_base)
stage("BUILD_PIN", s_pin)
stage("BUILD_ASM", s_asm)
stage("BUILD_CAP", s_cap)
stage("BUILD_SUB", s_sub)
stage("BUILD_TOP", s_top)


def s_load_options():
    """`LoadOptions.Save` 写出的 def 必须带三种加载方式的键；跨会话读回
    需要重启 NX（RUN_TESTS 单进程内不验），这里只 gate 写回格式。"""
    def_path = os.path.join(OUT_DIR, "t35_load.def")
    if os.path.exists(def_path):
        os.remove(def_path)
    session.Parts.LoadOptions.Save(def_path)
    assert os.path.exists(def_path) and os.path.getsize(def_path) > 0,         "LoadOptions.Save wrote no file: %s" % def_path
    with open(def_path, "r", encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    keys = [k for k in ("load_as_saved", "load_from_dir",
                        "load_from_search_dirs") if k in txt]
    print("LOAD_OPTIONS_DEF bytes=%d keys=%s" % (len(txt), keys))
    if not txt or not keys:
        raise RuntimeError("LoadOptions.Save wrote no load-option keys")

    # 同会话 Save/Restore 往返（跨进程差分由 verify_load_options.py 守）
    lo = session.Parts.LoadOptions
    orig = lo.ComponentLoadMethod.value
    lo.ComponentLoadMethod = NXOpen.LoadOptions.LoadMethod.SearchDirectories
    changed = lo.ComponentLoadMethod.value
    lo.Restore(def_path)
    restored = lo.ComponentLoadMethod.value
    print("LOAD_OPTIONS_RESTORE changed=%r restored=%r orig=%r"
          % (changed, restored, orig))
    if changed == orig or restored != orig:
        raise RuntimeError("LoadOptions Save/Restore round-trip failed: "
                           "%r -> %r -> %r" % (orig, changed, restored))


stage("LOAD_OPTIONS_DEF", s_load_options)

# ---- 重开装配并预载 ----
res = {}


def s_reopen():
    # 重开前先关会话内全部已加载 part：本会话刚建过装配，直接 Open 报
    # "File already exists"（preload_components 对子件吞同一异常，顶层装配须
    # 显式关）。.NET session.Parts.CloseAll 在 NX12 Python 包装里参数枚举
    # 校验报错（实测），走 ufs.Part.CloseAll() 无参路线
    ufs.Part.CloseAll()
    opened = session.Parts.Open(ASM_PRT)
    asm = opened[0] if isinstance(opened, tuple) else opened
    ufs.Part.SetDisplayPart(asm.Tag)
    res["asm"] = asm
    res["paths"] = preload_components(session, asm)


stage("REOPEN_PRELOAD", s_reopen)

got = sorted(os.path.basename(p) for p in res.get("paths", []))
check("PRELOAD_PATHS", got == ["t35_base.prt", "t35_pin.prt"], str(got))

asm = res.get("asm")
children = list(asm.ComponentAssembly.RootComponent.GetChildren())


def _origin(c):
    gp = c.GetPosition()
    # NX12 Python 包装 GetPosition 返回 (Point3d, Matrix3x3) 位姿对
    if isinstance(gp, tuple) and gp and isinstance(gp[0], NXOpen.Point3d):
        return (gp[0].X, gp[0].Y, gp[0].Z)
    if isinstance(gp, tuple):
        return tuple(float(v) for v in gp)
    return (gp.X, gp.Y, gp.Z)


pos_ok = len(children) == 2
detail = []
inst_bodies = []
for c in children:
    fp = os.path.basename(str(c.Prototype.FullPath))
    o = _origin(c)
    detail.append("%s@(%.4f,%.4f,%.4f)" % (fp, o[0], o[1], o[2]))
    if fp == "t35_base.prt":
        pos_ok = pos_ok and all(abs(v) < 1e-6 for v in o)
    elif fp == "t35_pin.prt":
        pos_ok = pos_ok and all(abs(a - b) < 1e-6 for a, b in zip(o, (20.0, 20.0, 15.0)))
    else:
        pos_ok = False
    # 实例体路线（T2 实测口径）：asm.Bodies 批处理重开下恒为 0，
    # 须 Prototype.Bodies + FindOccurrence
    proto_bodies = [b for b in c.Prototype.Bodies]
    if proto_bodies:
        inst = c.FindOccurrence(proto_bodies[0])
        if inst is not None:
            inst_bodies.append(inst)
check("POSITIONS", pos_ok, " ".join(detail))
check("INST_BODIES", len(inst_bodies) == 2,
      "occurrence bodies=%d (expect 2; Prototype+FindOccurrence 口径)" % len(inst_bodies))


def s_interference():
    if len(inst_bodies) != 2:
        res["si"] = -1
        res["pairs"] = -1
        return
    si = asm.AnalysisManager.CreateSimpleInterferenceObject()
    si.FirstBody.Value = inst_bodies[0]
    si.SecondBody.Value = inst_bodies[1]
    res["si"] = si.PerformCheck()
    res["pairs"] = len(si.GetInterferenceResults())
    si.Reset()
    si.Destroy()


stage("INTERFERENCE", s_interference)
check("NO_INTERFERENCE", res.get("pairs") == 0,
      "PerformCheck=%s result_pairs=%s (expect 0 pairs, 悬空布置)"
      % (str(res.get("si")), str(res.get("pairs"))))

# 幂等：二次预载不再新增（已加载子件的 Open 异常被吞）
res["paths2"] = preload_components(session, asm)
check("PRELOAD_IDEMPOTENT", len(res["paths2"]) == 0,
      "second call opened=%d (expect 0)" % len(res["paths2"]))

# ---- 嵌套装配：直接子件 / 孙件 ----
def _walk(comp, parent_origin, depth=0, out=None):
    """组件树 → [(prototype, world_origin, depth)]；位置逐级相加。"""
    out = out if out is not None else []
    proto = comp.Prototype
    o = _origin(comp)
    world = tuple(parent_origin[i] + o[i] for i in range(3))
    out.append((proto, world, depth))
    ca = getattr(proto, "ComponentAssembly", None) if proto is not None else None
    root = getattr(ca, "RootComponent", None) if ca is not None else None
    if root is not None:
        for ch in root.GetChildren():
            _walk(ch, world, depth + 1, out)
    return out


def s_nested():
    ufs.Part.CloseAll()
    opened = session.Parts.Open(TOP_PRT)
    top = opened[0] if isinstance(opened, tuple) else opened
    ufs.Part.SetDisplayPart(top.Tag)
    res["top"] = top
    res["top_paths"] = preload_components(session, top)


stage("NESTED_REOPEN_PRELOAD", s_nested)

top = res.get("top")
top_children = list(top.ComponentAssembly.RootComponent.GetChildren()) if top else []
direct = sorted(os.path.basename(str(c.Prototype.FullPath)) for c in top_children)
check("NESTED_DIRECT_CHILDREN", direct == ["t35_cap.prt", "t35_sub.prt"], str(direct))

sub_comp = [c for c in top_children
            if os.path.basename(str(c.Prototype.FullPath)) == "t35_sub.prt"]
sub_proto = sub_comp[0].Prototype if sub_comp else None


def _grand_children():
    if sub_proto is None or getattr(sub_proto, "ComponentAssembly", None) is None:
        return None
    return list(sub_proto.ComponentAssembly.RootComponent.GetChildren())


def _grand_counts():
    kids = _grand_children()
    if kids is None:
        return None
    out = {}
    for c in kids:
        out[os.path.basename(str(c.Prototype.FullPath))] = len(
            list(c.Prototype.Bodies))
    return out


before = _grand_counts()
res["grand_before"] = before
if before is None:
    check("NESTED_GRANDCHILDREN", False,
          "subassembly prototype has no ComponentAssembly after preload")
else:
    opened3 = preload_tree(session, sub_proto)
    after = _grand_counts()
    res["grand_after"] = after
    got3 = sorted(os.path.basename(p) for p in opened3)
    check("NESTED_GRANDCHILDREN",
          after is not None and after
          and all(n > 0 for n in after.values())
          and got3 == ["t35_base.prt", "t35_pin.prt"],
          "direct-children-before=%r preload_tree=%s after=%r"
          % (before, got3, after))

# ---- 装配图：standard_views(bbox=...)，装配件无自有实体 ----
def s_assembly_drawing():
    if top is None:
        raise RuntimeError("top assembly missing")
    nodes = []
    for c in top.ComponentAssembly.RootComponent.GetChildren():
        _walk(c, (0.0, 0.0, 0.0), 0, nodes)
    boxes = []
    for proto, world, _depth in nodes:
        if proto is None:
            continue
        for b in proto.Bodies:
            mn, mx = gb.model_bbox(b)
            boxes.append(((mn[0] + world[0], mn[1] + world[1],
                           mn[2] + world[2]),
                          (mx[0] + world[0], mx[1] + world[1],
                           mx[2] + world[2])))
    if not boxes:
        raise RuntimeError("no component bodies for the assembly bbox")
    bbox = ((min(b[0][0] for b in boxes), min(b[0][1] for b in boxes),
             min(b[0][2] for b in boxes)),
            (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes),
             max(b[1][2] for b in boxes)))
    sheet = gb.new_sheet(top, "SHT_ASM", "A4")
    views = gb.standard_views(top, sheet, bbox=bbox, scale=1.0, size="A4")
    counts = {}
    for k in ("FRONT", "TOP", "RIGHT"):
        cb = gb.content_bbox(views[k], bbox[0], bbox[1])
        if cb[0] < 0.0 or cb[1] < 0.0 or cb[2] > 297.0 or cb[3] > 210.0:
            raise RuntimeError("assembly view %s content out of sheet: %r"
                               % (k, cb))
        n = len(views[k].AskVisibleObjects() or [])
        counts[k] = n
        if n < 1:
            raise RuntimeError("assembly view %s is empty" % k)
    res["asm_bbox"] = bbox
    return counts


draw_counts = stage("ASSEMBLY_DRAWING", s_assembly_drawing)
check("ASM_DRAWING_VIEWS", bool(draw_counts) and len(draw_counts) == 3,
      "bbox=%r visible=%r" % (res.get("asm_bbox"), draw_counts))


# ---- 装配件 STL：无自有实体 → scope=auto 走 EntirePart ----
def s_export_assembly():
    if top is None:
        raise RuntimeError("top assembly missing")
    stl = os.path.join(OUT_DIR, "t35_top.stl")
    path = measure.export_mesh(top, stl, scope="auto")
    mesh = measure.read_stl(path)
    topo = topology(mesh)
    bbox = measure.mesh_bbox(mesh)
    res["stl_mesh"] = mesh
    res["stl_bbox"] = bbox
    res["stl_volume"] = abs(mesh_volume(mesh))
    return topo


stl_topo = stage("ASSEMBLY_EXPORT_STL", s_export_assembly)
if stl_topo:
    exp = ((0.0, 0.0, 0.0), (40.0, 50.0, 35.0))
    got = res.get("stl_bbox") or [0.0] * 6
    bbox_ok = all(abs(got[i] - exp[0][i]) <= 0.05 for i in range(3)) and         all(abs(got[i + 3] - exp[1][i]) <= 0.05 for i in range(3))
    vol_ok = abs(res.get("stl_volume", 0.0) - 21570.796) <= 0.02 * 21570.796
    check("ASM_EXPORT_STL",
          stl_topo.get("components") == 3 and bbox_ok and vol_ok
          and len(res.get("stl_mesh") or []) > 0,
          "components=%s bbox=%r volume=%.3f (expect 3 / %r / 21570.796±2%%)"
          % (stl_topo.get("components"), got, res.get("stl_volume", 0.0), exp))

check_finish("TEST35_DONE", "TEST35")
