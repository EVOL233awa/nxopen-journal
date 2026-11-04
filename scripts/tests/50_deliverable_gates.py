# -*- coding: utf-8 -*-
"""Test 50: 交付件门必须拦得住空骨架/开口 STL/缺 PMI。

用例自己建件并导出，再用 scripts/deliverable.py 的离线普查判定。四个
负控刻意复现真实假通过：

  - 不设 ObjectTypes.Solids：合法 2 KB AP242、日志成功、零 B-rep；
  - AP214 不设 SettingsFile：同样是空骨架；
  - STL 去掉一个三角面：文件仍能读、体积仍在，但不再水密；
  - 关掉 PmiData/Annotations：STEP 里没有 FLATNESS_TOLERANCE。

判定出口：TEST50_DONE；失败由 check_finish 打 TEST50_FAIL checks=...
"""
import os
import struct
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
from nxlib import exchange, measure, modeling
from nxlib import session as S
from nxlib.testing import check, check_finish, say

BASE = os.getcwd()


def build_part(name):
    path = os.path.join(BASE, name + ".prt")
    part = S.new_part(path=path)
    modeling.block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "25", "10")
    body = modeling.bodies(part)[0]
    modeling.add_thru_hole(part, body, 20.0, 12.5, 10.0, "8")
    S.save()
    return part, path


def add_flatness(part, body, value="0.05"):
    ufs = NXOpen.UF.UFSession.GetUFSession()
    top = None
    for f in body.GetFaces():
        data = ufs.Modeling.AskFaceData(f.Tag)
        if data[0] == 22 and data[2][2] > 0.9:
            top = f
            break
    if top is None:
        raise RuntimeError("no top face")
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


def drop_one_triangle(src, dst):
    with open(src, "rb") as fh:
        data = fh.read()
    count = struct.unpack("<I", data[80:84])[0]
    body = data[84:84 + 50 * (count - 1)]
    with open(dst, "wb") as fh:
        fh.write(data[:80])
        fh.write(struct.pack("<I", count - 1))
        fh.write(body)
    return count - 1


def main():
    part, part_path = build_part("deliv50")
    body = modeling.bodies(part)[0]
    facts = exchange.part_facts(part)
    say("FACTS " + str(facts))
    check("T50_FACTS", facts["bodies"] == 1 and facts["faces"] == 7
          and facts["edges"] == 14, str(facts))

    # 正控：AP242 实体导出
    stp = os.path.join(BASE, "deliv50_242.stp")
    exchange.export_step(part, stp, "ap242")
    census = d.step_census(stp)
    res = d.step_gate(census, facts, schema="AP242")
    say("STEP242 n=%d solids=%d faces=%d edges=%d %s"
        % (census["n_entities"], census["solid_breps"],
           census["advanced_faces"], census["edge_curves"],
           d.format_result("gate", res)))
    check("T50_STEP242", res["verdict"] == "PASS", str(res))

    # 负控 1：ObjectTypes.Solids 关掉 = 合法空骨架
    empty = os.path.join(BASE, "deliv50_empty.stp")
    exchange.export_step(part, empty, "ap242", solids=False)
    c_empty = d.step_census(empty)
    r_empty = d.step_gate(c_empty, facts, schema="AP242")
    say("STEP_EMPTY n=%d solids=%d %s"
        % (c_empty["n_entities"], c_empty["solid_breps"],
           d.format_result("gate", r_empty)))
    check("T50_EMPTY_REJECT",
          r_empty["verdict"] == "FAIL" and "DELIV_E_STEP_EMPTY" in r_empty["codes"],
          str(r_empty))

    # 负控 2：AP214 不给 SettingsFile = 空骨架；给了 def 才出几何
    a214_bad = os.path.join(BASE, "deliv50_214_bad.stp")
    exchange.export_step(part, a214_bad, "ap214", strict_settings=False)
    c_bad = d.step_census(a214_bad)
    r_bad = d.step_gate(c_bad, facts)
    check("T50_AP214_DEFAULT",
          r_bad["verdict"] == "FAIL" and c_bad["solid_breps"] == 0,
          str(r_bad))
    a214 = os.path.join(BASE, "deliv50_214.stp")
    exchange.export_step(part, a214, "ap214", strict_settings=True)
    c_214 = d.step_census(a214)
    r_214 = d.step_gate(c_214, facts, schema="AUTOMOTIVE_DESIGN")
    check("T50_AP214_DEF", r_214["verdict"] == "PASS", str(r_214))

    # STL 正控 + 开口负控
    stl = os.path.join(BASE, "deliv50.stl")
    measure.export_mesh(part, stl, chordal_tol=0.01)
    c_stl = d.stl_census(stl)
    r_stl = d.stl_gate(c_stl, facts)
    say("STL tris=%d watertight=%s euler=%s genus=%s %s"
        % (c_stl["triangles"], c_stl["watertight"], c_stl["euler"],
           c_stl["genus"], d.format_result("gate", r_stl)))
    check("T50_STL_TOPOLOGY", r_stl["verdict"] == "PASS", str(r_stl))
    open_stl = os.path.join(BASE, "deliv50_open.stl")
    drop_one_triangle(stl, open_stl)
    r_open = d.stl_gate(d.stl_census(open_stl), facts)
    check("T50_STL_OPEN",
          r_open["verdict"] == "FAIL" and "DELIV_E_STL_OPEN" in r_open["codes"],
          str(r_open))

    # PMI 正控 + 关掉 PMI 的负控
    add_flatness(part, body)
    S.save()
    pmi_stp = os.path.join(BASE, "deliv50_pmi.stp")
    exchange.export_step(part, pmi_stp, "ap242", pmi=True, annotations=True)
    c_pmi = d.step_census(pmi_stp)
    r_pmi = d.pmi_gate(c_pmi, {"FLATNESS_TOLERANCE": 1})
    say("PMI pmi=%r %s" % (c_pmi["pmi"], d.format_result("gate", r_pmi)))
    check("T50_PMI_SUBTYPE",
          r_pmi["verdict"] == "PASS"
          and c_pmi["pmi"].get("FLATNESS_TOLERANCE", 0) >= 1,
          str(c_pmi["pmi"]))
    no_pmi = os.path.join(BASE, "deliv50_nopmi.stp")
    exchange.export_step(part, no_pmi, "ap242", pmi=False, annotations=False)
    c_no = d.step_census(no_pmi)
    r_no = d.pmi_gate(c_no, {"FLATNESS_TOLERANCE": 1})
    check("T50_PMI_OFF",
          r_no["verdict"] == "FAIL"
          and c_no["pmi"].get("FLATNESS_TOLERANCE", 0) == 0,
          str(c_no["pmi"]))

    return check_finish("TEST50_DONE", "TEST50")


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as exc:
        import traceback
        say("TEST50_EXC " + repr(exc))
        say(traceback.format_exc()[-600:])
        raise
    sys.exit(0 if ok else 1)
