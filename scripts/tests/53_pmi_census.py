# -*- coding: utf-8 -*-
"""Test 53: PMI 按子类型族计数，不按泛型。

NX 写 `FLATNESS_TOLERANCE` 等具体子类型，`GEOMETRIC_TOLERANCE` 恒为 0；
PmiData/Annotations 开关关掉时连子类型也没有。本用例固定这三条，并要求
0.05 的公差值真的落进 STEP。

出口 TEST53_DONE。
"""
import os
import sys

import NXOpen
import NXOpen.Annotations

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

import deliverable as d
from nxlib import exchange, modeling
from nxlib import session as S
from nxlib.testing import check, check_finish, say

BASE = os.getcwd()


def add_flatness(part, body, value="0.05"):
    ufs = NXOpen.UF.UFSession.GetUFSession()
    top = None
    for f in body.GetFaces():
        data = ufs.Modeling.AskFaceData(f.Tag)
        if data[0] == 22 and data[2][2] > 0.9:
            top = f
            break
    am = part.Annotations
    builder = am.CreatePmiFeatureControlFrameBuilder(
        NXOpen.Annotations.Fcf.Null)
    db = am.CreateFeatureControlFrameDataBuilder(
        NXOpen.Annotations.FeatureControlFrameData.Null)
    db.ToleranceValue = value
    db.ZoneShape = \
        NXOpen.Annotations.FeatureControlFrameDataBuilder.ToleranceZoneShape.NotSet
    builder.Characteristic = \
        NXOpen.Annotations.FeatureControlFrameBuilder.FcfCharacteristic.Flatness
    builder.FeatureControlFrameDataList.SetContents([db])
    builder.AssociatedObjects.Objects.Add(top)
    builder.Origin.OriginPoint = NXOpen.Point3d(20.0, 12.5, 20.0)
    builder.Validate()
    fcf = builder.Commit()
    builder.Destroy()
    return fcf


def main():
    path = os.path.join(BASE, "pmi53.prt")
    part = S.new_part(path=path)
    modeling.block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "25", "10")
    body = modeling.bodies(part)[0]
    fcf = add_flatness(part, body)
    S.save()
    say("FCF tag=%s fcfs=%d pmis=%d"
        % (getattr(fcf, "Tag", None), len(list(part.Annotations.Fcfs)),
           len(list(part.PmiManager.Pmis))))

    on = os.path.join(BASE, "pmi53_on.stp")
    exchange.export_step(part, on, "ap242", pmi=True, annotations=True)
    c_on = d.step_census(on)
    with open(on, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    r_on = d.pmi_gate(c_on, {"FLATNESS_TOLERANCE": 1,
                             "GEOMETRIC_ITEM_SPECIFIC_USAGE": 2})
    say("PMI_ON %s" % d.format_result("gate", r_on))
    say("PMI_ON types=%r measure=%s"
        % (c_on["pmi"], "LENGTH_MEASURE(0.05)" in text.replace(" ", "")))
    check("T53_PMI_SUBTYPE",
          r_on["verdict"] == "PASS"
          and c_on["pmi"].get("FLATNESS_TOLERANCE") == 1
          and c_on["pmi"].get("GEOMETRIC_ITEM_SPECIFIC_USAGE", 0) >= 2,
          "pmi=%r" % (c_on["pmi"],))
    has_value = "LENGTH_MEASURE(0.05)" in text.replace(" ", "")
    check("T53_PMI_VALUE", has_value,
          "LENGTH_MEASURE(0.05) " + ("found" if has_value else "missing"))

    off = os.path.join(BASE, "pmi53_off.stp")
    exchange.export_step(part, off, "ap242", pmi=False, annotations=False)
    c_off = d.step_census(off)
    r_off = d.pmi_gate(c_off, {"FLATNESS_TOLERANCE": 1})
    say("PMI_OFF types=%r %s" % (c_off["pmi"], d.format_result("gate", r_off)))
    check("T53_PMI_OFF",
          r_off["verdict"] == "FAIL"
          and c_off["pmi"].get("FLATNESS_TOLERANCE", 0) == 0,
          "pmi=%r" % (c_off["pmi"],))

    return check_finish("TEST53_DONE", "TEST53")


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as exc:
        import traceback
        say("TEST53_EXC " + repr(exc))
        say(traceback.format_exc()[-600:])
        raise
    sys.exit(0 if ok else 1)
