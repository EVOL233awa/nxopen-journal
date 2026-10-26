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
from nxlib.assembly import add_component, preload_components

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
BASE_PRT = os.path.join(OUT_DIR, "t35_base.prt")
PIN_PRT = os.path.join(OUT_DIR, "t35_pin.prt")
ASM_PRT = os.path.join(OUT_DIR, "t35_asm.prt")

for fp in (BASE_PRT, PIN_PRT, ASM_PRT):
    if os.path.exists(fp):
        os.remove(fp)

session = NXOpen.Session.GetSession()
ufs = NXOpen.UF.UFSession.GetUFSession()
check("PARTS", True, "t35_base / t35_pin / t35_asm")


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


stage("BUILD_BASE", s_base)
stage("BUILD_PIN", s_pin)
stage("BUILD_ASM", s_asm)

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

check_finish("TEST35_DONE", "TEST35")
