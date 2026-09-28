# -*- coding: utf-8 -*-
"""14 方块布尔静默失败回归（2026-09-15 实测）。

证明两件事（这是 references/modeling.md §2.1 新配方的依据）：
  1. BlockFeatureBuilder 的 BooleanOption 在 NX12 批处理下被**静默忽略**——
     求差不生效、体数从 1 变 2，无任何异常。用体数断言暴露它。
  2. SetBooleanOperationAndTarget 才真正生效——体数保持 1。

同时核验 Point3d/Vector3d 的 float 参数要求。
成功标志：BLOCK_BOOL_OK / POINT_TYPE_OK / VEC_TYPE_OK / TEST14_DONE，退出码 0；
失败打印 TEST14_FAIL 并抛异常（令牌与退出码同时失败）。

# check_journal: allow-probes  （本文件故意写错以演示坑位，静态检查豁免）
"""
import os
import sys
import traceback

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.modeling import block, bodies
from nxlib.session import new_part

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.abspath(os.path.join(HERE, "parts", "blk_bool.prt"))
P2 = os.path.abspath(os.path.join(HERE, "parts", "blk_bool2.prt"))


def main():
    print("=== TEST14 START ===")

    # --- 类型要求：Point3d / Vector3d 必须传 float ---
    try:
        NXOpen.Point3d(0, 0, 0)
        print("POINT_TYPE_OK=False (int 被接受，与预期不符)")
    except TypeError as exc:
        print("POINT_TYPE_OK=True (int 被拒: %s)" % exc)
    try:
        NXOpen.Vector3d(1, 0, 0)
        print("VEC_TYPE_OK=False (int 被接受，与预期不符)")
    except TypeError as exc:
        print("VEC_TYPE_OK=True (int 被拒: %s)" % exc)

    wp = new_part(path=P)

    # --- 1) BooleanOption 静默失败 ---
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
    n1 = len(bodies(wp))
    tgt = bodies(wp)[0]
    cut = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    cut.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
    cut.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
    cut.BooleanOption.SetTargetBodies([tgt])
    cut.CommitFeature()
    cut.Destroy()
    n2 = len(bodies(wp))
    silently_ignored = (n2 == n1 + 1)

    # --- 2) SetBooleanOperationAndTarget 生效（必须用另一个未打开的路径，FileNew 不覆盖） ---
    wp2 = new_part(path=P2)
    block(wp2, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
    m1 = len(bodies(wp2))
    tgt2 = bodies(wp2)[0]
    cut2 = wp2.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    cut2.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
    cut2.SetBooleanOperationAndTarget(
        NXOpen.Features.Feature.BooleanType.Subtract, tgt2)
    cut2.CommitFeature()
    cut2.Destroy()
    m2 = len(bodies(wp2))
    really_subtracted = (m2 == m1)

    print("BooleanOption: bodies %d -> %d (silently_ignored=%s)" % (n1, n2, silently_ignored))
    print("SetBooleanOperationAndTarget: bodies %d -> %d (subtracted=%s)" % (m1, m2, really_subtracted))

    # 体积校验：切块 20x20x30 从 z=-5 起，与 20 高块的交集高度只有 20，
    # 实际切除 20*20*20=8000（不是 12000）。120000-8000=112000。
    uc = wp2.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
    vol = wp2.MeasureManager.NewMassProperties(units, [0.99], bodies(wp2)).Volume
    expect = 120000.0 - 20.0 * 20.0 * 20.0
    print("V=%.3f expect=%.1f" % (vol, expect))

    ok = silently_ignored and really_subtracted and abs(vol - expect) < 1e-3
    print("BLOCK_BOOL_OK=%s" % ok)
    if not ok:
        print("TEST14_FAIL")
        raise RuntimeError("block boolean regression failed")
    print("TEST14_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("TEST14_FATAL:\n" + traceback.format_exc())
        raise
