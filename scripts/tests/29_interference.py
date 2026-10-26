# -*- coding: utf-8 -*-
# Test 29: interference between solids, by geometric intersection.
#
# references/assembly.md A.3 records that the ClearanceSets route has
# no creation entry in batch; the replacement measured here is geometry:
#
#   1. boolean intersection -- CUBES = A INTERSECT B, exactly and cheaply:
#        tool = part.Features.CreateBlockFeatureBuilder(Feature.Null)
#        tool.SetOriginAndLengths(...)
#        tool.SetBooleanOperationAndTarget(
#            NXOpen.Features.Feature.BooleanType.Intersect, body_a)
#        tool.CommitFeature()
#      Two 10 mm cubes overlapping by 5 mm leave ONE body whose volume is
#      5*10*10 = 500 mm^3 (measured 500.000), so the intersection volume is the
#      interference volume. A non-overlapping pair is refused outright with
#      NXException "Tool body completely outside target body" -- a clean
#      negative, not a silent empty body.
#
#   2. GeometricAnalysis.SimpleInterference -- the built-in check, used as an
#      independent verdict on the same geometry:
#        si = part.AnalysisManager.CreateSimpleInterferenceObject()
#        si.FirstBody.Value = a          <- FirstBody is a SelectObject; the
#        si.SecondBody.Value = b            attribute itself is NOT writable
#        res = si.PerformCheck()         <- SimpleInterference.Result
#        pairs = si.GetInterferenceResults()   -> [Face, Face]
#      Verdicts measured: InterferenceExists with 2 faces when they overlap,
#      NoInterference with an empty list when they are apart. res.value is an
#      int (2 / 0), so compare against the enum, not against a string.
#
# The volume expectation is analytic, which is what makes this a gate rather
# than a smoke test: getting 500 mm^3 requires the boolean to have cut exactly
# the shared 5 mm slab.
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricAnalysis
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part
from nxlib.modeling import block, volume

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
CUBE = 10.0
OVERLAP = 5.0
EXPECT_VOL = OVERLAP * CUBE * CUBE          # 500 mm^3
VOL_TOL = 1e-3
ZERO_VOL = 1e-6

def intersect_case(part, target, tool_origin):
    """Boolean-intersect a cube at tool_origin into target. Returns (ok, detail)."""
    tool = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    tool.SetOriginAndLengths(NXOpen.Point3d(*tool_origin),
                             "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    tool.SetBooleanOperationAndTarget(
        NXOpen.Features.Feature.BooleanType.Intersect, target)
    try:
        tool.CommitFeature()
        tool.Destroy()
    except Exception as exc:
        tool.Destroy()
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:200])
    bodies = [b for b in part.Bodies]
    return True, "bodies=%d volumes=%s" % (len(bodies),
                                           ["%.6f" % volume(part, b) for b in bodies])


def main():
    ufs = NXOpen.UF.UFSession.GetUFSession()
    SI = NXOpen.GeometricAnalysis.SimpleInterference
    # (part, abspath)登记表：每个用例建件后登记，末尾统一"显示中保存"（见末尾注释）
    open_parts = []
    # FileNew().Commit() 会按 NewFileName 直接落盘（实测 112KB 模板件），撞名即抛
    # "File already exists" —— 开工先清掉上一轮残留
    for stale in ("t29_overlap", "t29_outside", "t29_touch", "t29_simple",
                  "t29_simple_none"):
        stale_path = os.path.abspath(stale + ".prt")
        if os.path.exists(stale_path):
            os.remove(stale_path)

    # ------------------------------------------------- 1) overlapping pair
    part = new_part(name="t29_overlap")
    open_parts.append((part, os.path.abspath("t29_overlap.prt")))
    block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    a = [b for b in part.Bodies][0]
    say("OVERLAP volume before=%.3f" % volume(part, a))
    ok, detail = intersect_case(part, a, (OVERLAP, 0.0, 0.0))
    got = volume(part, [b for b in part.Bodies][0]) if ok else -1.0
    check("REG_INTERSECT_VOLUME", ok and abs(got - EXPECT_VOL) < VOL_TOL,
          "A(10^3) INTERSECT tool at x=%.0f -> %.6f mm^3, analytic %.1f (%s)"
          % (OVERLAP, got, EXPECT_VOL, detail))
    ufs.Part.Save()

    # ------------------------------------------------- 2) fully outside pair
    part2 = new_part(name="t29_outside")
    open_parts.append((part2, os.path.abspath("t29_outside.prt")))
    block(part2, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    a2 = [b for b in part2.Bodies][0]
    ok2, detail2 = intersect_case(part2, a2, (2.0 * CUBE, 0.0, 0.0))
    check("REG_OUTSIDE_REFUSED", (not ok2) and "outside" in detail2.lower(),
          "intersection of non-overlapping cubes -> %s" % detail2)

    # ------------------------------------------------- 3) face-touching pair
    # the boundary between "no interference" and "interference": the shared face
    # has area but no volume, so the honest outcome is either a refusal or a
    # zero-volume result. Both are acceptable; a positive volume is not.
    part3 = new_part(name="t29_touch")
    open_parts.append((part3, os.path.abspath("t29_touch.prt")))
    block(part3, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    a3 = [b for b in part3.Bodies][0]
    ok3, detail3 = intersect_case(part3, a3, (CUBE, 0.0, 0.0))
    if ok3:
        v3 = volume(part3, [b for b in part3.Bodies][0])
        zero = abs(v3) < ZERO_VOL
    else:
        v3 = -1.0
        zero = True
    check("REG_TOUCH_NO_VOLUME", zero,
          "cubes sharing one face -> %s (volume %.6f, must be either refused or "
          "zero volume)" % (detail3, v3))

    # ------------------------------------- 4) SimpleInterference, same geometry
    part4 = new_part(name="t29_simple")
    open_parts.append((part4, os.path.abspath("t29_simple.prt")))
    block(part4, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    block(part4, NXOpen.Point3d(OVERLAP, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    two = [b for b in part4.Bodies]
    si = part4.AnalysisManager.CreateSimpleInterferenceObject()
    fb = si.FirstBody
    check("REG_SI_SELECTOR", type(fb).__name__ == "SelectObject",
          "FirstBody is %s whose .Value is the writable slot (assigning "
          "FirstBody itself raises 'not writable')" % type(fb).__name__)
    si.FirstBody.Value = two[0]
    si.SecondBody.Value = two[1]
    res = si.PerformCheck()
    check("REG_SI_INTERFERENCE", res == SI.Result.InterferenceExists,
          "PerformCheck=%r (value=%r) on two cubes overlapping by %.0f mm"
          % (res, getattr(res, "value", "?"), OVERLAP))
    pairs = si.GetInterferenceResults()
    kinds = sorted(set(type(x).__name__ for x in pairs)) if pairs else []
    check("REG_SI_RESULT_PAIRS", len(pairs) == 2 and kinds == ["Face"],
          "GetInterferenceResults -> %d object(s) %s" % (len(pairs), kinds))
    si.Reset()
    si.Destroy()

    # ------------------------------------------------- 5) SimpleInterference, no
    part5 = new_part(name="t29_simple_none")
    open_parts.append((part5, os.path.abspath("t29_simple_none.prt")))
    block(part5, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    block(part5, NXOpen.Point3d(2.0 * CUBE, 0.0, 0.0), "%.1f" % CUBE, "%.1f" % CUBE, "%.1f" % CUBE)
    far = [b for b in part5.Bodies]
    si2 = part5.AnalysisManager.CreateSimpleInterferenceObject()
    si2.FirstBody.Value = far[0]
    si2.SecondBody.Value = far[1]
    res2 = si2.PerformCheck()
    pairs2 = si2.GetInterferenceResults()
    check("REG_SI_NONE", res2 == SI.Result.NoInterference and len(pairs2) == 0,
          "PerformCheck=%r (value=%r) results=%d on cubes %.0f mm apart"
          % (res2, getattr(res2, "value", "?"), len(pairs2), 2.0 * CUBE))
    si2.Reset()
    si2.Destroy()

    # ufs.Part.Save() writes the DISPLAY part only, and each FileNew case made the
    # part it had just created the display part -- so the parts of the middle three
    # cases were never written and the files simply did not exist (measured
    # : t29_outside/t29_touch/t29_simple = 0 bytes). Save every part
    # while it is the display part, then check each file.
    sizes = []
    for saved_part, saved_path in open_parts:
        ufs.Part.SetDisplayPart(saved_part.Tag)
        ufs.Part.Save()
        sizes.append((saved_path,
                      os.path.getsize(saved_path) if os.path.exists(saved_path) else 0))
    check("REG_ARTIFACTS_LANDED", all(s > 100000 for _, s in sizes),
          "each part saved while displayed; " +
          " ".join("%s=%d" % (os.path.basename(p), s) for p, s in sizes))

    failed = [n for n, v in RESULTS if not v]
    say("TEST29_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST29_FAIL failed=%s" % failed)
        return
    say("TEST29_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST29_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST29_FAIL uncaught")
