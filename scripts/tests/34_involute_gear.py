# -*- coding: utf-8 -*-
# Test 34: 渐开线直齿圆柱齿轮（nxlib.modeling.involute_gear）
#
# 覆盖：
#   * 表达式驱动规律曲线（压力角参数化——NX12 表达式无 atan/acos/asin/atan2，
#     见 modeling.md §4.1 硬限制）+ ZLaw 显式 Constant（默认缺常量表达式会报
#     "Expression does not exist for law"）
#   * 齿顶/齿根三点弧 + 径向连接线 + 全齿闭合轮廓一次 UF 拉伸 + 负向拉伸打孔
#   * gb_drawing.model_bbox 的 ufs.ModlGeneral.AskBoundingBox 主路线（纯回转体
#     无直边——直边回退会抛 "body has no edges"）
#
# 数值口径（独立解析积分）：
#   z=20 m=2 α=20° B=20 孔Ø20 → ra=22 rf=17.5；扣孔体积 18238.9 mm³，验收带 ±2%
#   （体积对齿数敏感 ~5%/齿，带内即钉死齿数与齿形）。
# 成功标志：TEST34_DONE 且无 _FAIL
import math
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
_p2 = os.path.join(_p, "gb_drawing.py")
if os.path.exists(_p2) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS, stage, check_finish
from nxlib.session import new_part, set_work, save_checked
from nxlib.modeling import involute_gear

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
PART = os.path.join(OUT_DIR, "t34_involute_gear.prt")

M, Z, ALPHA, B, DBORE = 2.0, 20, 20.0, 20.0, 20.0
RP = M * Z / 2.0
RA, RF = RP + M, RP - 1.25 * M
# 解析体积（渐开线齿面积分 + 扣孔，t8_truth.py 口径，20 万步）
V_ANALYTIC = 18238.9
V_BAND = (V_ANALYTIC * 0.98, V_ANALYTIC * 1.02)

if os.path.exists(PART):
    os.remove(PART)

session = NXOpen.Session.GetSession()
ufs = NXOpen.UF.UFSession.GetUFSession()
wp = set_work(new_part(path=PART))

res = {}


def s1():
    res.update(involute_gear(wp, M, Z, ALPHA, B, DBORE))


def s2():
    save_checked(PART)


# ---- 断言 ----
import gb_drawing  # noqa: E402  （scripts/ 在 sys.path；model_bbox 修正的回归载体）

stage("BUILD", s1)
stage("SAVE", s2)
check("SAVE_LANDED", os.path.exists(PART) and os.path.getsize(PART) > 0, PART)
body = res.get("body")
vol = res.get("volume", -1.0)
check("VOLUME", vol is not None and V_BAND[0] <= vol <= V_BAND[1],
      "%.4f in [%.1f, %.1f]" % (vol, V_BAND[0], V_BAND[1]))

# 圆柱面普查：孔 1 + 齿顶 Z + 齿根 Z
n_bore = n_tip = n_root = 0
for f in body.GetFaces():
    d = ufs.Modeling.AskFaceData(f.Tag)
    if d[0] == 16:
        if abs(d[4] - DBORE / 2.0) < 1e-6:
            n_bore += 1
        elif abs(d[4] - RA) < 1e-6:
            n_tip += 1
        elif abs(d[4] - RF) < 1e-6:
            n_root += 1
check("FACES", n_bore == 1 and n_tip == Z and n_root == Z,
      "bore=%d tip=%d root=%d (expect 1/%d/%d)" % (n_bore, n_tip, n_root, Z, Z))

# model_bbox（ModlGeneral 主路线）：纯回转体精确包盒
(mn, mx) = gb_drawing.model_bbox(body)
exp = (-RA, -RA, 0.0, RA, RA, B)
got = (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])
check("BBOX", all(abs(a - b) < 1e-6 for a, b in zip(got, exp)),
      "got %s expect %s" % (str(got), str(exp)))


# 齿顶/齿根弧半径（建模返回的 tag 逐个核对；字段名 radius/Radius 双探）
def _arc_radius(tag):
    ad = ufs.Curve.AskArcData(tag)
    for cand in ("radius", "Radius"):
        if hasattr(ad, cand):
            return getattr(ad, cand)
    return None


n_tip_arc = sum(1 for tg in res.get("tip_tags", [])
                if _arc_radius(tg) is not None and abs(_arc_radius(tg) - RA) < 1e-6)
n_root_arc = sum(1 for tg in res.get("root_tags", [])
                 if _arc_radius(tg) is not None and abs(_arc_radius(tg) - RF) < 1e-6)
check("ARCS", n_tip_arc == Z and n_root_arc == Z,
      "tip=%d/%d root=%d/%d" % (n_tip_arc, Z, n_root_arc, Z))

# 表达式联动口径：参数链存在（p_gear_m / p_rp / p_rb / p_smax）
names = [e.Name for e in wp.Expressions]
check("EXPR", all(n in names for n in ("p_gear_m", "p_gear_z", "p_rp", "p_rb", "p_smax")),
      "参数链 p_gear_*/p_rp/ra/rf/rb/p_smax 齐全")

# ---- 轮毂分支（减速器常用结构）：独立部件，避免表达式重名 ----
NO_HUB = os.path.join(OUT_DIR, "t34_gear_nohub.prt")
HUB_PART = os.path.join(OUT_DIR, "t34_gear_hub.prt")
for p in (NO_HUB, HUB_PART):
    if os.path.exists(p):
        os.remove(p)

wp0 = set_work(new_part(path=NO_HUB))
r0 = involute_gear(wp0, 1.0, 12, 20.0, 10.0, 5.0)
wp1 = set_work(new_part(path=HUB_PART))
r1 = involute_gear(wp1, 1.0, 12, 20.0, 10.0, 5.0,
                   hub_d=9.0, hub_len=14.0)
# 轮毂 r4.5 < 齿根圆 rf4.75：齿宽内完全埋在齿轮体内，只有两侧各伸出 2 mm
# 的环带是新增体积 → π*(4.5²−2.5²)*(14−10)，与齿形无关（独立解析）。
ring = math.pi * (4.5 ** 2 - 2.5 ** 2) * (14.0 - 10.0)
dv = r1["volume"] - r0["volume"]
check("HUB_BODY", len(list(wp1.Bodies)) == 1,
      "bodies=%d" % len(list(wp1.Bodies)))
check("HUB_VOLUME", abs(dv - ring) <= 0.01 * ring,
      "dv=%.3f expect ring=%.3f±1%%" % (dv, ring))

check_finish("TEST34_DONE", "TEST34")
