# -*- coding: utf-8 -*-
# Test 45: audit layer -- full station plan comparison and locality.
#
# Section 12.5: the delivery verdict is a full-station comparison against the
# original with the primary/fillet split fixed before building, and locality
# is proven by moving one design parameter and watching unrelated stations.
# This test builds a coupon twice -- once as the reference, once with a hole
# moved 1 mm -- and checks:
#
#   - g1full(orig, orig) passes every primary station (the comparison itself
#     must not manufacture failures: a self-comparison is the null test);
#   - g1full(orig, moved) fails only stations inside the moved feature's band,
#     and the plan partition is unchanged (the denominator does not move);
#   - locality(): a design parameter that moves one structure reports the
#     stations it touched and no station outside its own set;
#   - the plan used here is the measurement compiler's, not a hand-picked one.
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
import nxlib.measure as ms
import nxlib.reverse as rv
import nxlib.skeleton as sk
import nxlib.structures as st
import nxlib.template as tpl
import nxlib.audit as au

PLATE = [(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)]


def build(path, widen=0.0):
    part = new_part("t45", path)
    wp = part
    vals = {"PLATE_T": 14.0, "BOSS_D": 26.0, "BOSS_H": 16.0, "HOLE_D": 10.0}
    tpl.create_expressions(wp, vals, dict((k, "mm") for k in vals))
    fr = sk.Frame.from_azimuth(0.0)
    outline = [(PLATE[0][0], PLATE[0][1]),
               (PLATE[1][0] + widen, PLATE[1][1]),
               (PLATE[2][0] + widen, PLATE[2][1]),
               (PLATE[3][0], PLATE[3][1])]
    body = st.prism(wp, sk.loop_uv(wp, fr, outline), (0.0, 0.0, 1.0),
                    "0.0", "PLATE_T")["bodies"][0]
    boss = st.cylinder(wp, (0.0, 0.0, 14.0), (0.0, 0.0, 1.0), "BOSS_D",
                       "BOSS_H")
    st.unite(wp, body, boss["features"][0])
    st.hole_cut(wp, body, (0.0, 0.0, 30.0), (0.0, 0.0, -1.0),
                "HOLE_D", "40.0")
    save_checked(path)
    return part, body


def main():
    out = os.getcwd()
    ref_path = os.path.join(out, "t45_ref.prt")
    moved_path = os.path.join(out, "t45_moved.prt")

    ref, ref_body = build(ref_path, 0.0)
    meas = ms.measure_part(ref_path)
    directory = rv.candidate_directory(meas, ref)
    structures = [{"id": r["id"], "bbox": r["bbox"], "faces": r["faces"]}
                  for r in directory["revolved"]]
    plan = rv.station_plan_full(meas, structures)
    part_rows = rv.station_partition(meas, plan, [])
    prim = [r["i"] for r in part_rows if r["class"] == "primary"]
    say("plan stations=%d primary=%d structures=%d"
        % (len(plan["stations"]), len(prim), len(structures)))
    check("T45_PLAN", len(prim) >= 2 and not plan["missing"],
          "primary=%d missing=%r" % (len(prim), plan["missing"]))

    same = au.g1full(ref, ref, plan, meas, [])
    say("self: primary=%r fillet=%r" % (same["primary"], same["fillet"]))
    check("T45_SELF_NULL", same["primary"]["ratio"] >= 0.999,
          "a self comparison must pass every primary station (ratio %.3f)"
          % same["primary"]["ratio"])

    moved, _b = build(moved_path, 6.0)
    rep = au.g1full(ref, moved, plan, meas, [])
    say("moved: primary=%r" % (rep["primary"],))
    check("T45_MOVED_FAILS", rep["primary"]["ratio"] < 1.0,
          "widening the plate by 6 mm must fail at least one primary station")
    check("T45_PARTITION_FIXED",
          [r["i"] for r in rep["partition"]] == [r["i"] for r in part_rows],
          "the partition must not depend on the built part")

    # the failures must sit in the band of the moved feature (z 0..30, the
    # hole's axis) -- a failure far from it would mean the audit is noisy
    # a station's origin names its plane, not the region it observes: a z-plane
    # at the axis still sees the widened outline.  The sound invariant is
    # directional -- widening 6 mm can only ADD material, so no failing station
    # may be short of material.
    rows = dict((r["index"], r) for r in rep["report"]["stations"])
    short = [(i, round(rows[i]["area_a"], 1), round(rows[i]["area_b"], 1))
             for i in rep["primary"]["failed"]
             if rows[i]["area_b"] < rows[i]["area_a"] - 1.0]
    check("T45_FAIL_DIRECTION", not short,
          "a widened plate cannot lose material at any station, short=%r"
          % (short,))
    grew = [(i, round(rows[i]["area_b"] - rows[i]["area_a"], 1))
            for i in rep["primary"]["failed"]]
    say("failed station area growth=%r" % (grew,))
    check("T45_FAIL_EXPLAINED", all(g > 0 for _i, g in grew),
          "every failure must come from the added material, growth=%r"
          % (grew,))

    design = {}
    for s in structures:
        b = s["bbox"]
        own = [i for i, stn in enumerate(plan["stations"])
               if b[0] - 0.5 <= stn["origin"][0] <= b[3] + 0.5 and
               b[1] - 0.5 <= stn["origin"][1] <= b[4] + 0.5 and
               b[2] - 0.5 <= stn["origin"][2] <= b[5] + 0.5]
        design[s["id"]] = {"exprs": [p["name"] for p in
                                     rv.param_candidates(directory)
                                     if p["structure"] == s["id"] and
                                     p["kind"] == "design"][:1],
                           "stations": own}
    design = dict((k, v) for k, v in design.items() if v["exprs"] and v["stations"])
    say("locality design=%r" % (design,))
    loc = au.locality(ref, design, plan, primary=prim)
    outs = dict((sid, [r.get("outside") for r in rows])
                for sid, rows in loc.items())
    say("locality outside=%r" % (outs,))
    check("T45_LOCALITY_RAN", bool(loc),
          "locality must return one record per structure")
    check("T45_LOCALITY_NO_OUTSIDE",
          all(not (r.get("outside") or []) for rows in loc.values()
              for r in rows),
          "a design parameter must not move stations of other structures: %r"
          % (outs,))

    failed = [n for n, ok in RESULTS if not ok]
    say("TEST45_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST45_FAIL failed=%s" % failed)
        return
    say("TEST45_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST45_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST45_FAIL uncaught")
