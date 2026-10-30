# -*- coding: utf-8 -*-
# Test 44: the structure library (nxlib.structures) on a bracket.
#
# Section 12.4: builders take frame + parameters + data and never a part
# constant, so the same call sequence works for any bracket.  This test drives
# prism, cylinder, boolean unite, hole_cut, blend_try and trim_box on a plate
# with a boss, a through hole, a rounded edge and a trimmed corner, and checks
# the result analytically:
#
#   plate  80 x 50 x 12                       V1 = 48000
#   trim   envelope to v <= 15                V1' = 80*40*12 = 38400
#   boss   D 24, h 18 on the plate top        V2 = pi/4*24^2*18
#   hole   D 12 through plate + boss          V3 = pi/4*12^2*30
#   blend  R3 on the plate top rim            V5 in [0, ~(R^2 - pi R^2/4)*perimeter]
#
# Checks:
#   - one body, and the explicit and expression-driven booleans both work;
#   - volume equals V1 + V2 - V3 - V4 - V5 with V5 inside the blend's bound
#     (R^2 - pi R^2/4) * perimeter, i.e. the builders really cut what they say;
#   - blend_try returns a record instead of raising when the radius is too
#     large for the local faces (the undo-guarded path);
#   - budget() computes 4N+12 from the structure count, not from features.
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
import nxlib.skeleton as sk
import nxlib.structures as st
import nxlib.template as tpl
import nxlib.audit as au

PLATE = [(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)]
T = 12.0
BOSS_D, BOSS_H = 24.0, 18.0
HOLE_D = 12.0


def main():
    out = os.getcwd()
    part_path = os.path.join(out, "t44_bracket.prt")
    part = new_part("t44", part_path)
    wp = part
    vals = {"PLATE_T": T, "BOSS_D": BOSS_D, "BOSS_H": BOSS_H,
            "HOLE_D": HOLE_D, "FILLET_R": 3.0}
    units = dict((k, "mm") for k in vals)
    tpl.create_expressions(wp, vals, units)

    fr = sk.Frame.from_azimuth(0.0)
    body = st.prism(wp, sk.loop_uv(wp, fr, PLATE), (0.0, 0.0, 1.0),
                    "0.0", "PLATE_T")["bodies"][0]
    check("T44_PRISM", len(list(part.Bodies)) == 1,
          "prism must return exactly one body (bodies=%d)"
          % len(list(part.Bodies)))

    v_before_trim = mdl.volume(wp, body)
    box = st.trim_box(wp, body, fr, (-40.0, -25.0, 0.0), (40.0, 15.0, 0.0),
                      "0.0", "PLATE_T")
    v_after_trim = mdl.volume(wp, body)
    say("trim volume %.2f -> %.2f" % (v_before_trim, v_after_trim))
    check("T44_TRIM",
          abs((v_before_trim - v_after_trim) - 80.0 * 10.0 * T) < 1e-2,
          "envelope trim must remove %.1f mm3, removed %.3f"
          % (80.0 * 10.0 * T, v_before_trim - v_after_trim))
    check("T44_TRIM_RESULT", len(box.get("bodies") or []) == 1,
          "trim_box must report the tool body it intersected with")

    boss = st.cylinder(wp, (0.0, 0.0, T), (0.0, 0.0, 1.0), "BOSS_D",
                       "BOSS_H")
    st.unite(wp, body, boss["features"][0])
    check("T44_UNITE", len(list(part.Bodies)) == 1,
          "unite must leave one body (bodies=%d)" % len(list(part.Bodies)))

    st.hole_cut(wp, body, (0.0, 0.0, T + BOSS_H), (0.0, 0.0, -1.0),
                "HOLE_D", "40.0")

    # the boss's top rim: one closed circular edge, so the tangent chain has
    # no termination problem (a free plate corner does: two 90 deg edges)
    r_boss = BOSS_D / 2.0
    edges = st.edges_by(body, fr, lambda pts: all(
        abs(p[2] - (T + BOSS_H)) < 0.2 and
        abs(math.hypot(p[0], p[1]) - r_boss) < 0.3 for p in pts))
    say("rim edges=%d" % len(edges))
    rec = st.blend_try(wp, edges, "FILLET_R", tag="t44_rim")
    say("blend=%r" % (rec,))
    check("T44_BLEND_RETURNS", isinstance(rec, dict) and edges,
          "a closed circular rim must take R3 (edges=%d, record=%r)"
          % (len(edges), type(rec).__name__ if rec is not None else None))

    v = mdl.volume(wp, body)
    v_plate = 80.0 * 40.0 * T
    v_boss = math.pi / 4.0 * BOSS_D ** 2 * BOSS_H
    v_hole = math.pi / 4.0 * HOLE_D ** 2 * (T + BOSS_H)
    v_nom = v_plate + v_boss - v_hole
    v5 = v_nom - v
    perim = math.pi * BOSS_D
    v5_max = (3.0 ** 2 - math.pi * 3.0 ** 2 / 4.0) * perim
    say("volume=%.1f nominal=%.1f blend=%.1f (bound %.1f)"
        % (v, v_nom, v5, v5_max))
    check("T44_VOLUME", abs(v - v_nom) <= v5_max + 1.0,
          "volume %.1f vs nominal %.1f, blend %.1f outside [0, %.1f]"
          % (v, v_nom, v5, v5_max))
    check("T44_BLEND_REMOVES", 0.0 < v5 <= v5_max + 1.0,
          "a convex rim blend must remove (R^2 - pi R^2/4)*perimeter, removed "
          "%.1f of at most %.1f" % (v5, v5_max))

    too_big = st.blend_try(wp, edges[:2], "60.0", tag="t44_big")
    check("T44_BLEND_UNDO_GUARD", too_big is None,
          "an oversized radius must roll back and return None (got %r)"
          % (too_big,))
    check("T44_BLEND_ALIVE", len(list(part.Bodies)) == 1,
          "the rollback must leave the body intact (bodies=%d)"
          % len(list(part.Bodies)))

    bud = au.budget(part, 4)
    say("budget=%r" %
        dict((k, v) for k, v in bud.items() if not isinstance(v, (list, dict))))
    check("T44_BUDGET_LIMIT", abs(bud["feature_limit"] - 28.0) < 1e-9,
          "feature_limit must be 4N+12 = 28 for N=4 (got %r)"
          % bud["feature_limit"])

    save_checked(part_path)
    failed = [n for n, ok in RESULTS if not ok]
    say("TEST44_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST44_FAIL failed=%s" % failed)
        return
    say("TEST44_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST44_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST44_FAIL uncaught")
