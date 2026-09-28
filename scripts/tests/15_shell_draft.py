# -*- coding: utf-8 -*-
"""Test 15: Shell + Draft 完整配方回归（NX12 批处理实测）。

证明两件事（体积与解析值严格比对，非"看体数"）：
  A) ShellBuilder：Tolerance 默认 0.0 必须显式设；Body + SetDefaultThickness(str)
     + RemovedFacesCollector(SC 收集器)；100x60x20 移除顶面、壁厚 2.0
     -> V = 120000 - 96*56*18 = 23232.000
  B) DraftBuilder：AngleTolerance 默认 0.0 必须显式设；关键 API 事实
     - Method 属性只读 -> 用 DraftIsoclineOrTruedraft 设 TrueDraft
     - StationaryReference 只读 -> 用 StationaryEntity，且必须传 Face 对象
       （传 SC 收集器报 "First parameter is invalid"，不给报 "Draft reference is missing"）
     - 拔模角经 FaceSetAngleExpressionList.Append(
         wp.CreateExpressionCollectorSet(collector, "5", "", 0))
     - 100x60x20 四侧面拔模、StationaryEntity=底面、Direction=+Z：
       正角收缩  V = 120000 - 64000t + (32000/3)t^2  , t = tan(角)
       负角张开  V = 120000 + 64000t + (32000/3)t^2

2026-09-24 起通用配方（new_part/bodies/面过滤/收集器/体积/落盘断言）走 nxlib。
"""
import math
import os
import sys

import NXOpen
import NXOpen.Features

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.modeling import block, bodies, face_collector, planar_faces, volume
from nxlib.session import new_part, save_checked

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts")

VOL_BLOCK = 120000.0                       # 100*60*20
VOL_SHELL = VOL_BLOCK - 96.0 * 56.0 * 18.0  # 移顶面壁厚 2.0 -> 23232.0


def shell_case():
    wp = new_part(path=os.path.join(OUT_DIR, "t15_shell.prt"))
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
    body = bodies(wp)[-1]
    top = planar_faces(wp, body, lambda n: n[2] > 0.9)
    assert len(top) == 1, "expected 1 top face, got %d" % len(top)

    sb = wp.Features.CreateShellBuilder(NXOpen.Features.Feature.Null)
    sb.Tolerance = 0.01                       # 默认 0.0，不改会报 Tolerance error
    sb.Body = body
    sb.SetDefaultThickness("2.0")
    col = face_collector(wp, top)
    sb.RemovedFacesCollector = col
    sb.CommitFeature()
    sb.Destroy()
    col.Destroy()

    feats = [f.FeatureType for f in wp.Features.GetFeatures()]
    vol = volume(wp, bodies(wp)[0])
    ok = ("SHELL" in feats and len(bodies(wp)) == 1
          and abs(vol - VOL_SHELL) < 1e-3)
    print("SHELL vol=%.3f expect=%.3f feat=%s" % (vol, VOL_SHELL, feats))
    save_checked(os.path.join(OUT_DIR, "t15_shell.prt"))
    return ok


def draft_case(angle_deg, path_name):
    wp = new_part(path=os.path.join(OUT_DIR, path_name))
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
    body = bodies(wp)[-1]
    sides = planar_faces(wp, body, lambda n: abs(n[2]) < 0.1)
    bottom = planar_faces(wp, body, lambda n: n[2] < -0.9)
    assert len(sides) == 4 and len(bottom) == 1, "faces sides=%d bottom=%d" % (
        len(sides), len(bottom))

    db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)
    db.AngleTolerance = 0.5                   # 默认 0.0，不改会报 Angle tolerance is too small
    db.DistanceTolerance = 0.001
    db.TypeOfDraft = NXOpen.Features.DraftBuilder.Type.Face
    db.DraftIsoclineOrTruedraft = NXOpen.Features.DraftBuilder.Method.TrueDraft   # Method 只读
    db.Direction = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    db.StationaryEntity = bottom[0]            # 必须传 Face，不能传 SC 收集器
    ecs = wp.CreateExpressionCollectorSet(
        face_collector(wp, sides), str(angle_deg), "", 0)      # 单位参数用空串
    db.FaceSetAngleExpressionList.Append(ecs)
    db.CommitFeature()
    db.Destroy()

    t = math.tan(math.radians(angle_deg))      # 带符号：正角收缩、负角张开
    expect = VOL_BLOCK - 64000.0 * t + (32000.0 / 3.0) * t * t
    feats = [f.FeatureType for f in wp.Features.GetFeatures()]
    vol = volume(wp, bodies(wp)[0])
    ok = ("DRAFT" in feats and len(bodies(wp)) == 1 and abs(vol - expect) < 1e-3)
    print("DRAFT a=%s vol=%.4f expect=%.4f feat=%s" % (angle_deg, vol, expect, feats))
    save_checked(os.path.join(OUT_DIR, path_name))
    return ok


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    ok_shell = shell_case()
    ok_shrink = draft_case(5, "t15_draft_shrink.prt")
    ok_grow = draft_case(-5, "t15_draft_grow.prt")
    ok = ok_shell and ok_shrink and ok_grow
    print("TEST15_OK=%s" % ok)
    if not ok:
        print("TEST15_FAIL")
        raise RuntimeError(
            "shell/draft regression failed (shell=%s shrink=%s grow=%s)"
            % (ok_shell, ok_shrink, ok_grow))
    print("TEST15_DONE")


if __name__ == "__main__":
    main()
