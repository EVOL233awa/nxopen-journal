# ============================================================
# 08_editability_probe.py - editability / reviewability probe
# Opens a generated part and CHECKS (not just dumps):
#   1) feature tree is non-empty (history-based / parametric proof)
#   2) named expressions exist and are all readable (parameter proof)
#   3) every sketch is WellConstrained (fully constrained proof)
#   4) exactly one body
# Gate: prints TEST08_DONE when all checks hold, TEST08_FAIL <names> otherwise.
# Usage: run_journal_batch.bat scripts\tests\08_editability_probe.py <parts dir>
# NOTE: ASCII only (run from cmd / GBK batch env is fine, but keep comments ASCII)
# ============================================================
import os

import NXOpen
import NXOpen.UF

PART_PATH = os.path.join(os.path.dirname(__file__), "parts", "bracket.prt")

def main():
    theSession = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    part, load_status = theSession.Parts.Open(PART_PATH)
    ufs.Part.SetDisplayPart(part.Tag)
    print("EDIT_PROBE part=" + str(part.FullPath))

    checks = {}

    # 1) feature tree: every generated solid must be history-based features
    try:
        feats = part.Features.GetFeatures()
        print("EDIT_PROBE features=" + str(len(feats)))
        for f in feats:
            print("  FEAT name=" + str(f.GetFeatureName()) + " type=" + str(f.FeatureType))
        checks["features"] = len(feats) > 0
    except Exception as exc:
        print("EDIT_PROBE features=ERR " + str(exc))
        checks["features"] = False

    # 2) expressions: named top-level parameters must exist and be readable
    try:
        exprs = [e for e in part.Expressions]
        print("EDIT_PROBE expressions=" + str(len(exprs)))
        readable = 0
        for e in exprs:
            try:
                rhs = e.RightHandSide
                readable += 1
            except Exception:
                rhs = "?"
            print("  EXPR " + str(e.Name) + " = " + str(rhs))
        checks["expressions"] = len(exprs) > 0 and readable == len(exprs)
    except Exception as exc:
        print("EDIT_PROBE expressions=ERR " + str(exc))
        checks["expressions"] = False

    # 3) sketch status: must be WellConstrained (fully constrained)
    try:
        skts = [s for s in part.Sketches]
        print("EDIT_PROBE sketches=" + str(len(skts)))
        well = 0
        for s in skts:
            try:
                res = s.GetStatus()
                if isinstance(res, tuple):
                    status, dof = res[0], res[1]
                else:
                    status, dof = res, -1
                is_well = (status == NXOpen.Sketch.Status.WellConstrained)
                if is_well:
                    well += 1
                print("  SKETCH name=" + str(s.Name) + " status=" + str(status) +
                      " dof=" + str(dof) + " fully=" + str(is_well))
            except Exception as exc:
                print("  SKETCH name=" + str(s.Name) + " status=ERR " + str(exc))
        checks["sketches_well_constrained"] = len(skts) > 0 and well == len(skts)
    except Exception as exc:
        print("EDIT_PROBE sketches=ERR " + str(exc))
        checks["sketches_well_constrained"] = False

    # 4) bodies
    try:
        n_bodies = len([b for b in part.Bodies])
        print("EDIT_PROBE bodies=" + str(n_bodies))
        checks["single_body"] = (n_bodies == 1)
    except Exception as exc:
        print("EDIT_PROBE bodies=ERR " + str(exc))
        checks["single_body"] = False

    failed = sorted(k for k, v in checks.items() if not v)
    print("EDIT_PROBE checks=" + str(checks))
    if failed:
        print("TEST08_FAIL " + ",".join(failed))
    else:
        print("TEST08_DONE")

if __name__ == '__main__':
    main()
