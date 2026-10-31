# -*- coding: utf-8 -*-
# Test 46: design-declaration reconciliation and the edit envelope.
#
# Section 11.3 asks for a +10% census over every named expression, and section
# 12.5 asks for the per-structure check. Both count only the expressions that
# were actually built, so a part that declares ten design parameters and never
# creates them scores a perfect 1.0 -- which is exactly what a real delivery did
# this round. This test plants that defect and requires the audit layer to
# report it, then exercises edit_envelope on a parameter with room and one that
# runs out of it:
#
#   - declared-but-not-created parameters land in `missing`, not in the ratio;
#   - a parameter with headroom resolves to the sweep bound; one whose value
#     drives a dimension negative stops inside the sweep, and the stopping trial
#     carries the verbatim failure;
#   - every trial is restored, so the volume comes back bit-identical.
#
# The narrow parameter feeds a diameter formula (BOSS_D - 2*RECESS_R) rather than
# a blend radius: a blend that fails to build turns the parameter dead, and a
# dead parameter proves nothing about the envelope.
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
import nxlib.skeleton as sk
import nxlib.structures as st
import nxlib.template as tpl
import nxlib.audit as au

PLATE = [(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)]


def build_part(path):
    """Plate + boss; the boss diameter is a formula with no room at x2.0."""
    part = new_part("t46", path)
    wp = part
    vals = {"PLATE_T": 14.0, "BOSS_D": 26.0, "BOSS_H": 30.0, "RECESS_R": 8.0}
    units = dict((k, "mm") for k in vals)
    tpl.create_expressions(wp, vals, units)
    fr = sk.Frame.from_azimuth(0.0)
    body = st.prism(wp, sk.loop_uv(wp, fr, PLATE, z=0.0), (0.0, 0.0, 1.0),
                    "0.0", "PLATE_T")["bodies"][0]
    # BOSS_D - 2*RECESS_R is 10 mm now; at RECESS_R x1.5 it is -4 mm, which no
    # cylinder feature can resolve, so the update rolls back exactly like a real
    # dimension colliding with its neighbour.
    boss = st.cylinder(wp, (0.0, 0.0, 14.0), (0.0, 0.0, 1.0),
                       "BOSS_D - 2*RECESS_R", "BOSS_H")
    st.unite(wp, body, boss["features"][0])
    save_checked(path)
    return part, body


def main():
    path = os.path.join(_here, "parts", "t46_edit_envelope.prt")
    part, body = build_part(path)
    say("built %s volume=%.6f" % (path, mdl.volume(part, body)))

    # ---- 1. declared but never created is missing, not a silent 1.0
    design = {"plate": ["PLATE_T"], "boss": ["BOSS_D", "BOSS_H"],
              "boss_formula": ["RECESS_R"],
              "ghost": ["GHOST_W", "GHOST_H"]}
    live = au.liveness(part, design, factor=1.1)
    missing = sorted((m["structure"], m["name"]) for m in live["missing"])
    say("liveness ratio=%.4f missing=%r" % (live["ratio"], missing))
    check("T46_RATIO_IGNORES_GHOST", abs(live["ratio"] - 1.0) < 1e-9,
          "alive_ratio counts created expressions only: %.4f" % live["ratio"])
    check("T46_GHOSTS_ARE_MISSING",
          missing == [("ghost", "GHOST_H"), ("ghost", "GHOST_W")],
          "declared-but-not-created parameters must be reported missing: %r"
          % (missing,))
    check("T46_STRUCTURE_LISTS_GHOSTS",
          live["structures"]["ghost"]["missing"] == ["GHOST_W", "GHOST_H"]
          and not live["structures"]["ghost"]["live"],
          "the per-structure record must carry its own missing list: %r"
          % (live["structures"]["ghost"],))
    check("T46_MISSING_BLOCKS_LIVENESS", live["pass"] is False,
          "a declared-but-missing parameter must fail liveness, not only be "
          "listed: pass=%r" % live["pass"])
    check("T46_FORMULA_PARAM_IS_LIVE",
          live["structures"]["boss_formula"]["live"] == ["RECESS_R"],
          "a parameter consumed inside another's formula must still read live: %r"
          % (live["structures"]["boss_formula"],))

    # ---- 2. the envelope separates "has room" from "runs out of room"
    env = au.edit_envelope(part, ["PLATE_T", "RECESS_R", "BOSS_H"],
                           steps=(1.10, 1.20, 1.30, 1.40, 1.50, 1.75, 2.00))
    rows = dict((r["name"], r) for r in env["rows"])
    say("envelope: %r" % dict((n, (r.get("max_ok_factor"),
                                  r.get("failed_at"))) for n, r in rows.items()))
    check("T46_ROOMY_PARAM_REACHES_BOUND",
          rows["PLATE_T"]["failed_at"] is None
          and rows["PLATE_T"]["max_ok_factor"] == 2.00,
          "a plate thickness has no upper neighbour, it must survive the sweep: %r"
          % (rows["PLATE_T"],))
    check("T46_NARROW_PARAM_STOPS",
          rows["RECESS_R"]["failed_at"] is not None
          and rows["RECESS_R"]["max_ok_factor"] < 2.00,
          "a formula that goes negative must stop inside the sweep: %r"
          % (rows["RECESS_R"],))
    detail = [t for t in rows["RECESS_R"]["trials"] if t.get("detail")]
    say("narrow stop detail=%r" % (detail[:1],))
    check("T46_NARROW_HAS_TEXT", bool(detail),
          "the stopping trial must carry the verbatim failure: %r" % (detail,))
    # failed_at is the FIRST failing factor, max_ok_factor the last success:
    # the old code stored the last success as failed_at, so a report could not
    # tell "still fine at 1.45" from "broke at 1.50"
    check("T46_FIRST_BREAK_FACTOR",
          rows["RECESS_R"]["failed_at"] > rows["RECESS_R"]["max_ok_factor"],
          "failed_at must be the first failing factor, not the last success: %r"
          % (rows["RECESS_R"],))
    check("T46_BOUNDED_FLAG",
          rows["PLATE_T"]["bounded"] is True and
          rows["RECESS_R"]["bounded"] is False,
          "the bounded flag must follow failed_at: %r"
          % ([(n, r.get("bounded")) for n, r in rows.items()],))

    summary = au.edit_envelope_summary(env)
    say("summary bounded=%r narrow=%r stuck=%r"
        % (summary["bounded"], [n["name"] for n in summary["narrow"]],
           summary["stuck"]))
    check("T46_SUMMARY_BOUNDED",
          sorted(summary["bounded"]) == ["BOSS_H", "PLATE_T"],
          "bounded bucket=%r" % (summary["bounded"],))
    check("T46_SUMMARY_NARROW",
          [n["name"] for n in summary["narrow"]] == ["RECESS_R"],
          "narrow bucket=%r" % (summary["narrow"],))
    check("T46_SUMMARY_PASS_FLAG", summary["pass"] is True,
          "nothing got stuck, so the summary must not fail: %r" % (summary,))

    # ---- 3. every trial restored: the part must come back bit-identical
    check("T46_RESTORE_EXACT", abs(env["v0"] - env["v1"]) < 1e-6,
          "volume before=%.6f after=%.6f" % (env["v0"], env["v1"]))

    failed = [n for n, ok in RESULTS if not ok]
    # ---- locality: coverage declaration and the whole-part screen
    # A partial run must say so: "locality passed" when 3 of 40 parameters were
    # measured reads identically to a full sweep in a report.
    loc_plan = {"stations": [{"origin": [0.0, 0.0, 7.0],
                              "normal": [0.0, 0.0, 1.0]}]}
    loc = au.locality(part, {"plate": {"exprs": ["PLATE_T"], "stations": [0]},
                             "boss": {"exprs": ["BOSS_D", "BOSS_H"],
                                      "stations": [0]}},
                      loc_plan, per_structure=1)
    say("locality coverage=%r pass=%r" % (loc["coverage"], loc["pass"]))
    check("T46_LOCALITY_COVERAGE_PARTIAL",
          loc["coverage"]["partial"] is True and
          loc["coverage"]["measured_exprs"] == 2 and
          loc["coverage"]["designed_exprs"] == 3,
          "a per_structure limit must be declared, not silently passed: %r"
          % (loc["coverage"],))
    check("T46_LOCALITY_PARTIAL_NOT_PASS", loc["pass"] is False,
          "a partial sweep cannot report pass: %r" % (loc["pass"],))

    full = au.locality(part, {"plate": {"exprs": ["PLATE_T"],
                                        "stations": [0]}},
                       loc_plan)
    say("locality full=%r" % ({k: full[k] for k in
                               ("pass", "outside_count",
                                "inconclusive_count")},))
    check("T46_LOCALITY_FULL_COVERAGE",
          full["coverage"]["partial"] is False,
          "an unrestricted run must declare full coverage: %r"
          % (full["coverage"],))

    scr = au.locality_screen(part, loc_plan,
                             {"plate": {"exprs": ["PLATE_T"]},
                              "boss": {"exprs": ["BOSS_D"]}})
    say("screen=%r" % ({"checked": scr["checked"],
                        "uncovered": scr["uncovered"]},))
    # A horizontal slice at z=7 crosses the plate at a constant outline, so a
    # plate THICKNESS change moves the station at z=7 not at all (the profile
    # at that height is identical); BOSS_D at z=7 is inside the boss's height
    # range, so it does move.  That asymmetry is exactly what the screen is
    # for: "no station moved" means the station set cannot see that parameter,
    # and a per-parameter sweep alone would report it as inconclusive without
    # saying which parameters are unmeasurable by construction.
    check("T46_SCREEN_FINDS_COVERAGE",
          scr["checked"] == 2 and
          all("changed_stations" in r for r in scr["rows"]),
          "the screen must report per-parameter station coverage: %r"
          % ([(r["expr"], r.get("changed_stations")) for r in scr["rows"]],))
    # the height is what makes the difference: a thickness change is invisible
    # to a slice that never enters or leaves the material
    say("screen uncovered=%r (expected: thickness changes are invisible to a "
        "mid-slab slice)" % (scr["uncovered"],))
    check("T46_SCREEN_UNCOVERED_DECLARED",
          scr["pass"] is (len(scr["uncovered"]) == 0),
          "pass must follow the uncovered list, not be hardwired: %r"
          % ({"pass": scr["pass"], "uncovered": scr["uncovered"]},))

    say("TEST46_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST46_STOP failed=%s" % failed)
        return
    say("TEST46_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST46_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST46_STOP uncaught")
