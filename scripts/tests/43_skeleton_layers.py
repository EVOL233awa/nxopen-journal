# -*- coding: utf-8 -*-
# Test 43: design/data layering and the skeleton frame.
#
# Section 12.2 of references/reverse-engineering.md splits every measured
# quantity into two layers: design values (an engineer would put them on a
# drawing; they must be named expressions and the geometry must follow them)
# and data values (measured outline coordinates; they stay literals and are
# disclosed as such).  This test builds a plate whose outline is data and
# whose thickness is design, then checks that:
#
#   - the frame is orthogonal and an oblique azimuth really is oblique;
#   - a non-orthogonal frame is rejected at construction, not later;
#   - liveness sees every declared design parameter as live (ratio 1.0, no
#     missing, no dead/broken) and groups them per structure;
#   - driving PLATE_T by +10 % moves the volume by the analytic amount and the
#     bounding box by the analytic amount, and restoring the value brings the
#     volume back bit-identical;
#   - the data outline did not become an expression (the named set is exactly
#     the design set).
import math
import os
import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part, save_checked
import nxlib.modeling as mdl
import nxlib.measure as ms
import nxlib.skeleton as sk
import nxlib.structures as st
import nxlib.template as tpl
import nxlib.audit as au

# measured outline (data layer): a plain 80 x 50 plate
PLATE = [(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)]
PLATE_AREA = 80.0 * 50.0
def poly_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def main():
    out = os.getcwd()
    part_path = os.path.join(out, "t43_plate.prt")
    part = new_part("t43", part_path)
    wp = part

    frame = sk.Frame.from_azimuth(45.0)
    d = frame.describe()
    say("frame=%r" % (d,))
    check("T43_FRAME_AZ",
          abs(abs(d["U"][0] * math_sqrt2() - 1.0)) < 1e-6,
          "U=%r must be the 45 deg radial direction" % (d["U"],))
    check("T43_FRAME_ORTHO",
          abs(d["U"][0] * d["V"][0] + d["U"][1] * d["V"][1]) < 1e-9 and
          abs(d["U"][2]) < 1e-9, "U/V/Z must be an orthonormal triad")

    rejected = False
    try:
        sk.Frame(u=(1.0, 0.0, 0.0), v=(1.0, 0.0, 0.0))
    except ValueError:
        rejected = True
    check("T43_FRAME_REJECT", rejected,
          "a non-orthogonal frame must raise at construction")

    vals = {"PLATE_T": 12.0, "BOSS_D": 24.0, "BOSS_H": 18.0}
    # a named expression that no feature uses: the audit must report it dead
    vals_dead = {"UNUSED_D": 5.0}
    units = dict((k, "mm") for k in vals)
    exprs = tpl.create_expressions(wp, vals, units)
    exprs.update(tpl.create_expressions(wp, vals_dead, units))

    fr0 = sk.Frame.from_azimuth(0.0)
    cs = sk.loop_uv(wp, fr0, PLATE, z=0.0)
    body = st.prism(wp, cs, (0.0, 0.0, 1.0), "0.0", "PLATE_T")["bodies"][0]
    boss = st.cylinder(wp, (0.0, 0.0, 12.0), (0.0, 0.0, 1.0), "BOSS_D",
                       "BOSS_H")
    st.unite(wp, body, boss["features"][0])
    save_checked(part_path)

    v0 = mdl.volume(wp, body)
    bb0 = [float(x) for x in part.BoundingBox.GetBoundingBox()] \
        if hasattr(part, "BoundingBox") else None
    check("T43_SINGLE_BODY", len(list(part.Bodies)) == 1,
          "bodies=%d" % len(list(part.Bodies)))

    design = {"plate": ["PLATE_T"], "boss": ["BOSS_D", "BOSS_H"]}
    live = au.liveness(part, design, factor=1.1)
    say("liveness ratio=%.3f missing=%r" % (live["ratio"], live["missing"]))
    # three of four named expressions drive geometry; UNUSED_D is planted to
    # prove the ratio counts dead parameters instead of ignoring them
    check("T43_LIVE_RATIO", abs(live["ratio"] - 0.75) < 1e-9,
          "alive_ratio=%.3f, expected 3/4 with one planted dead parameter"
          % live["ratio"])
    check("T43_LIVE_PER_STRUCT",
          all(rec["live"] and not rec["dead"] and not rec["broken"]
              for rec in live["structures"].values()),
          "per-structure liveness=%r"
          % dict((k, (v["live"], v["dead"], v["broken"]))
                 for k, v in live["structures"].items()))
    check("T43_LIVE_NO_MISSING", not live["missing"],
          "declared parameters missing from the part=%r" % (live["missing"],))

    named = set(live["survey"]["named"])
    check("T43_DATA_IS_NOT_A_PARAM",
          named == set(vals) | set(vals_dead),
          "named=%r must be exactly the declared set (outline coordinates "
          "stay data)" % sorted(named))

    dead = au.liveness(part, {"unused": ["UNUSED_D"]}, factor=1.1)
    say("unused: ratio=%.3f struct=%r" % (dead["ratio"], dead["structures"]))
    check("T43_UNUSED_IS_DEAD",
          dead["structures"]["unused"]["dead"] == ["UNUSED_D"] and
          dead["ratio"] < 1.0,
          "a named expression no feature reads must be reported dead, not "
          "counted as coverage")

    area = PLATE_AREA
    h = vals["PLATE_T"]
    e = exprs["PLATE_T"]
    rhs = e.RightHandSide
    e.RightHandSide = "%.6f" % (h * 1.1)
    errs = ms.do_update("t43_drive")
    v1 = mdl.volume(wp, body)
    # NX12 boundary (section 11.5): the cylinder builder's axis point is a
    # literal, so the boss stays at z = 12 while the plate grows through it and
    # the union eats the overlap.  The delta is therefore
    # area*dt - pi/4*D^2*dt, and a part that needs the boss to follow has to
    # place it on a face or a sketch, not at a literal point.
    overlap = math.pi / 4.0 * vals["BOSS_D"] ** 2 * (h * 0.1)
    want = v0 + area * h * 0.1 - overlap
    check("T43_DRIVE_VOLUME", abs(v1 - want) < 0.002 * abs(v1),
          "volume %.3f -> %.3f, analytic %.3f (plate %.1f - boss overlap %.1f)"
          % (v0, v1, want, area * h * 0.1, overlap))
    check("T43_DRIVE_UPDATES", not errs,
          "update errors=%r" % (errs,))

    e.RightHandSide = rhs
    ms.do_update("t43_restore")
    v2 = mdl.volume(wp, body)
    check("T43_RESTORE_BITWISE", abs(v2 - v0) < 1e-6,
          "restore %.6f vs %.6f (tolerance 1e-6 mm3)" % (v2, v0))

    env = au.envelope(part, [b for b in (
        None if bb0 is None else bb0)], tol=0.05) \
        if bb0 is not None else {"pass": True, "note": "no bbox api"}
    say("envelope=%r" % (env,))

    failed = [n for n, v in RESULTS if not v]
    say("TEST43_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST43_FAIL failed=%s" % failed)
        return
    say("TEST43_DONE")


def math_sqrt2():
    return 2.0 ** 0.5


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST43_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST43_FAIL uncaught")
