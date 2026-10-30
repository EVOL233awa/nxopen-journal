# -*- coding: utf-8 -*-
# Test 42: reverse measurement compiler -- the five frozen tables.
#
# The compiler route (references/reverse-engineering.md section 12) only works
# if the tables are decided before the model is built: structure rows must
# carry evidence, design parameters must be separated from data, the station
# plan must not be truncated, and the primary/fillet split must be the
# denominator from then on.  This test builds a two-structure coupon, compiles
# the tables from it, and checks those invariants plus determinism.
#
#   plate  80 x 50 x 12, corner at (-40,-25,0)
#   boss   D = 24, h = 18, axis +Z from the plate top centre
#   hole   D = 12 through plate + boss
#
# Checks:
#   - candidate_directory finds the boss and the hole with face tags;
#   - param_candidates tags every row design or data, design rows numeric,
#     axis/position rows data (a direction is never a driving parameter);
#   - validate_structure_table accepts the frozen table (face tags exist, no
#     face claimed twice, recomputed bbox matches);
#   - station_plan_full returns budget_truncated False and covers every
#     structure (missing empty);
#   - station_partition covers the plan one-to-one and is stable across two
#     calls (the denominator cannot move once results are seen);
#   - schema_skeleton keeps design and data apart per structure.
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

PLATE = [(-40.0, -25.0), (40.0, -25.0), (40.0, 25.0), (-40.0, 25.0)]


def build(part_path):
    part = new_part("t42", part_path)
    wp = part
    vals = {"PLATE_T": 12.0, "BOSS_D": 24.0, "BOSS_H": 18.0, "HOLE_D": 12.0}
    units = {"PLATE_T": "mm", "BOSS_D": "mm", "BOSS_H": "mm", "HOLE_D": "mm"}
    exprs = tpl.create_expressions(wp, vals, units)
    frame = sk.Frame.from_azimuth(0.0)
    cs = sk.loop_uv(wp, frame, PLATE, z=0.0)
    body = st.prism(wp, cs, (0.0, 0.0, 1.0), "0.0", "PLATE_T")["bodies"][0]
    boss = st.cylinder(wp, (0.0, 0.0, 12.0), (0.0, 0.0, 1.0),
                       "BOSS_D", "BOSS_H")
    st.unite(wp, body, boss["features"][0])
    st.hole_cut(wp, body, (0.0, 0.0, 30.0), (0.0, 0.0, -1.0),
                "HOLE_D", "40.0")
    say("built bodies=%d" % len(list(part.Bodies)))
    save_checked(part_path)
    return part, exprs


def main():
    part_path = os.path.join(os.getcwd(), "t42_coupon.prt")
    part, _exprs = build(part_path)
    meas = ms.measure_part(part_path)
    directory = rv.candidate_directory(meas, part)

    say("counts=%r" % (directory.get("counts"),))
    check("T42_REVOLVED", len(directory["revolved"]) >= 2,
          "revolved=%d (boss OD and bore must both be groups)"
          % len(directory["revolved"]))
    check("T42_HOLES", len(directory["holes"]) >= 1,
          "holes=%d" % len(directory["holes"]))
    check("T42_EVIDENCE",
          all(r.get("faces") for r in directory["revolved"]) and
          all(h.get("faces") for h in directory["holes"]),
          "every structure row must carry face tags")

    params = rv.param_candidates(directory)
    kinds = sorted(set(p["kind"] for p in params))
    design = [p for p in params if p["kind"] == "design"]
    bad = [p["name"] for p in design
           if not isinstance(p["value"], (int, float))]
    axis_data = [p for p in params if p["name"].endswith(("_AXIS", "_POS",
                                                         "_CTR"))]
    say("params=%d design=%d kinds=%r" % (len(params), len(design), kinds))
    check("T42_PARAM_LAYERS", kinds == ["data", "design"] and not bad,
          "kinds=%r numeric_design_failures=%r" % (kinds, bad))
    check("T42_PARAM_UNITS",
          all(p.get("unit") in ("mm", "deg", "unit") for p in params),
          "units=%r" % sorted(set(p.get("unit") for p in params)))
    check("T42_AXIS_IS_DATA",
          all(p["kind"] == "data" for p in axis_data),
          "axis/position candidates must not be driving parameters")

    structures = [{"id": r["id"], "name": r["role"], "bbox": r["bbox"],
                   "faces": r["faces"], "template": "revolved_hub"}
                  for r in directory["revolved"]]
    val = rv.validate_structure_table(structures, meas)
    check("T42_STRUCT_VALID", not val["errors"],
          "errors=%r" % (val["errors"][:2],))
    check("T42_STRUCT_FACES",
          all(r["faces"] > 0 for r in val["rows"]),
          "rows=%r" % (val["rows"],))

    plan = rv.station_plan_full(meas, structures)
    say("plan stations=%d missing=%r" % (len(plan["stations"]), plan["missing"]))
    check("T42_PLAN_NOTRUNC", plan.get("budget_truncated") is False,
          "the full plan must not be budget truncated")
    check("T42_PLAN_COVERS", not plan["missing"],
          "structures without a station=%r" % (plan["missing"],))
    check("T42_PLAN_NONEMPTY", len(plan["stations"]) >= 2,
          "stations=%d" % len(plan["stations"]))

    p1 = rv.station_partition(meas, plan, [])
    p2 = rv.station_partition(meas, plan, [])
    check("T42_PARTITION_1TO1", len(p1) == len(plan["stations"]),
          "%d rows for %d stations" % (len(p1), len(plan["stations"])))
    check("T42_PARTITION_CLASS",
          set(r["class"] for r in p1) <= set(["primary", "fillet"]),
          "classes=%r" % sorted(set(r["class"] for r in p1)))
    check("T42_PARTITION_STABLE", p1 == p2,
          "the denominator must not move between calls")

    schema = rv.schema_skeleton(structures, params)
    ids = [s["id"] for s in schema["structures"]]
    check("T42_SCHEMA_IDS", ids == [s["id"] for s in structures],
          "ids=%r" % (ids,))
    check("T42_SCHEMA_LAYERS",
          all(set(s["parameters"]).isdisjoint(s["data"])
              for s in schema["structures"]),
          "design and data names must not overlap")
    check("T42_SCHEMA_ORDER", len(schema["build_order"]) == len(ids),
          "build_order=%r" % (schema["build_order"],))

    failed = [n for n, v in RESULTS if not v]
    say("TEST42_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST42_FAIL failed=%s" % failed)
        return
    say("TEST42_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST42_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST42_FAIL uncaught")
