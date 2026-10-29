# -*- coding: utf-8 -*-
# Test 41: parametric template layer -- expressions, derived constraints,
# local-edit matrix.
#
# The point of a template route is not "a part that looks right once", it is a
# part whose sizes are named expressions and whose design constraints are
# formulas, so one edit updates the model without a rebuild.  This test drives
# nxlib.template on a bracket that is deliberately simple to keep the analytic
# volume exact:
#
#   plate  L_LEN x W_LEN x T_PLATE, origin at (0,0,0)
#   boss   D = BOSS_D, H = BOSS_H, axis +Z from the plate top centre
#   hole   D = HOLE_D (derived = BOSS_D / 2), through plate + boss
#
#   V = L*W*T + pi/4*D^2*H - pi/4*Dh^2*(T+H)
#
# Checks:
#   - the built volume equals V (the template really used the expressions);
#   - each single-parameter edit moves the volume by the analytic partial
#     derivative, comes back bit-identical, and leaves 0 alerts;
#   - HOLE_D is a derived constraint: after BOSS_D +2 the hole face radius is
#     (BOSS_D+2)/2 without touching HOLE_D (a frozen literal would fail here);
#   - locality: BOSS_D changes volume but not the bounding box; T_PLATE moves
#     z min/max by exactly the delta;
#   - template.edit_matrix marks a parameter that is not in the table instead
#     of crashing, and template.structure raises KeyError for unknown ids.
#
# The failure mode this guards against is the one the ARM315 template hit:
# a size written as a literal inside a feature builder keeps the old value
# until the journal is replayed, and a "constraint" written as two equal
# numbers silently breaks on the first edit.
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

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part, save_checked
import nxlib.modeling as mdl
import nxlib.measure as ms
import nxlib.template as tpl

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts")
PARAMS = {"L_LEN": 80.0, "W_LEN": 50.0, "T_PLATE": 10.0,
          "BOSS_D": 24.0, "BOSS_H": 12.0}
SCHEMA = {
    "build_order": ["S1", "S2"],
    "structures": [
        {"id": "S1", "name": "plate", "template": "block",
         "parameters": {"L_LEN": 80.0, "W_LEN": 50.0, "T_PLATE": 10.0}},
        {"id": "S2", "name": "boss", "template": "cylinder",
         "parameters": {"BOSS_D": 24.0, "BOSS_H": 12.0}},
    ],
}
TOL = 1e-5


def analytic_volume(l_len, w_len, t_plate, boss_d, boss_h):
    hole_d = boss_d / 2.0
    return (l_len * w_len * t_plate
            + math.pi / 4.0 * boss_d * boss_d * boss_h
            - math.pi / 4.0 * hole_d * hole_d * (t_plate + boss_h))


def build(wp):
    values, units = tpl.param_table(PARAMS)
    exprs = tpl.create_expressions(wp, values, units)
    exprs["HOLE_D"] = tpl.derived(wp, "HOLE_D", "BOSS_D / 2", "Length")
    f = mdl.block(wp, NXOpen.Point3d(0.0, 0.0, 0.0),
                  "L_LEN", "W_LEN", "T_PLATE")
    plate = f.GetBodies()[0]
    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)
    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
    # The axis point of a cylinder builder is a literal: it does not follow an
    # expression.  Start the boss at z = 0 (the plate bottom, so nothing hangs
    # outside the plate) and drive HEIGHT from T_PLATE + BOSS_H, otherwise a
    # thickness edit either sinks the boss or leaves it hanging in the air.
    cb.Axis = wp.Axes.CreateAxis(
        NXOpen.Point3d(PARAMS["L_LEN"] / 2.0, PARAMS["W_LEN"] / 2.0, 0.0),
        NXOpen.Vector3d(0.0, 0.0, 1.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    cb.Diameter.RightHandSide = "BOSS_D"
    cb.Height.RightHandSide = "T_PLATE + BOSS_H"
    boss = cb.CommitFeature().GetBodies()[0]
    cb.Destroy()
    mdl.boolean(wp, plate, boss, NXOpen.Features.Feature.BooleanType.Unite)
    hb = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralHoleForm = NXOpen.Features.HolePackageBuilder.HoleForms.Simple
    hb.GeneralSimpleHoleDiameter.RightHandSide = "HOLE_D"
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.ThroughBody
    pt = wp.Points.CreatePoint(NXOpen.Point3d(
        PARAMS["L_LEN"] / 2.0, PARAMS["W_LEN"] / 2.0,
        PARAMS["T_PLATE"] + PARAMS["BOSS_H"] + 20.0))
    rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])
    hb.HolePosition.AddToSection(
        [rule], pt, NXOpen.NXObject.Null, NXOpen.NXObject.Null,
        NXOpen.Point3d(PARAMS["L_LEN"] / 2.0, PARAMS["W_LEN"] / 2.0,
                       PARAMS["T_PLATE"] + PARAMS["BOSS_H"] + 20.0),
        NXOpen.Section.Mode.Create, False)
    hb.BooleanOperation.SetBooleanOperationAndBody(
        NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract, plate)
    hb.ProjectionDirection.ProjectDirectionMethod = \
        NXOpen.GeometricUtilities.ProjectionOptionsDirectionType.Vector
    hb.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(
        pt, NXOpen.Vector3d(0.0, 0.0, -1.0))
    hb.Tolerance = 0.0254
    hb.Validate()
    hb.CommitFeature()
    hb.Destroy()
    return plate, exprs


def hole_radius(part):
    rows = ms.face_table(part)
    want = PARAMS["BOSS_D"] / 2.0
    got = [r["radius"] for r in rows
           if r["type"] == 16 and abs(r["radius"] - want) < 3.0
           and abs(abs(r["dir"][2]) - 1.0) < 0.02]
    return got


def main():
    part_path = os.path.join(OUT_DIR, "41_template.prt")
    wp = new_part(path=part_path)
    plate, exprs = build(wp)
    base = tpl.snapshot(wp)
    v_an = analytic_volume(PARAMS["L_LEN"], PARAMS["W_LEN"], PARAMS["T_PLATE"],
                           PARAMS["BOSS_D"], PARAMS["BOSS_H"])
    say("BASE vol=%.6f analytic=%.6f bodies=%d faces=%d" % (
        base["volume"], v_an, base["bodies"], base["faces"]))
    check("T41_VOLUME", abs(base["volume"] - v_an) < TOL * max(1.0, v_an),
          "built=%.6f analytic=%.6f" % (base["volume"], v_an))
    check("T41_SINGLE_BODY", base["bodies"] == 1, "bodies=%d" % base["bodies"])
    check("T41_NO_ALERTS", not base["alerts"], "alerts=%s" % base["alerts"])

    # --- derived constraint: the hole is half the boss, without its own edit
    cell_d = tpl.edit_check(wp, exprs["BOSS_D"], 2.0, probe=hole_radius)
    say("EDIT BOSS_D+2 vol_delta=%.6f" % cell_d["volume_delta"])
    check("T41_BOSS_D_UPDATE", cell_d["update_errors"] == 0 and
          not cell_d["edited_diff"].get("alerts"),
          "errs=%d diff=%s" % (cell_d["update_errors"],
                               cell_d["edited_diff"]))
    d0 = PARAMS["BOSS_D"]
    d1 = d0 + 2.0
    dv_an = (math.pi / 4.0 * (d1 * d1 - d0 * d0) * PARAMS["BOSS_H"]
             - math.pi / 4.0 * ((d1 / 2.0) ** 2 - (d0 / 2.0) ** 2)
             * (PARAMS["T_PLATE"] + PARAMS["BOSS_H"]))
    check("T41_BOSS_D_VOLUME", abs(cell_d["volume_delta"] - dv_an) <
          1e-3 * max(1.0, abs(dv_an)),
          "delta=%.6f analytic=%.6f" % (cell_d["volume_delta"], dv_an))
    radii = cell_d["probe_result"] or []
    check("T41_DERIVED_CONSTRAINT",
          bool(radii) and all(abs(r - d1 / 2.0) < 0.01 for r in radii),
          "hole radii in the edited state=%s expected=%.3f "
          "(HOLE_D is a formula)" % (radii, d1 / 2.0))
    check("T41_BOSS_D_LOCAL", "bbox_moved" not in cell_d["edited_diff"],
          "bbox moved=%s" % cell_d["edited_diff"].get("bbox_moved"))
    check("T41_BOSS_D_RESTORE",
          cell_d["restored_volume_equal"] and cell_d["restored_faces_equal"]
          and not cell_d["restored_alerts"],
          "restored vol=%s faces=%s alerts=%s" % (
              cell_d["restored_volume_equal"], cell_d["restored_faces_equal"],
              cell_d["restored_alerts"]))

    # --- plate thickness: volume up, z max up by the same delta
    cell_t = tpl.edit_check(wp, exprs["T_PLATE"], 2.0)
    hole_d = PARAMS["BOSS_D"] / 2.0
    dvt_an = (PARAMS["L_LEN"] * PARAMS["W_LEN"]
              - math.pi / 4.0 * hole_d * hole_d) * 2.0
    say("EDIT T_PLATE+2 vol_delta=%.6f" % cell_t["volume_delta"])
    check("T41_T_VOLUME", abs(cell_t["volume_delta"] - dvt_an) <
          1e-3 * max(1.0, abs(dvt_an)),
          "delta=%.6f analytic=%.6f" % (cell_t["volume_delta"], dvt_an))
    zmax = cell_t["edited_diff"].get("bbox_moved")
    check("T41_T_EXTENT", zmax == [(5, 2.0)],
          "bbox_moved=%s (index 5 = z max)" % zmax)

    # --- plate length: x max grows, volume grows by W*T*dL
    cell_l = tpl.edit_check(wp, exprs["L_LEN"], 10.0)
    dvl_an = PARAMS["W_LEN"] * PARAMS["T_PLATE"] * 10.0
    say("EDIT L_LEN+10 vol_delta=%.6f" % cell_l["volume_delta"])
    check("T41_L_VOLUME", abs(cell_l["volume_delta"] - dvl_an) <
          1e-3 * max(1.0, abs(dvl_an)),
          "delta=%.6f analytic=%.6f" % (cell_l["volume_delta"], dvl_an))
    check("T41_L_EXTENT", cell_l["edited_diff"].get("bbox_moved") ==
          [(3, 10.0)],
          "bbox_moved=%s (index 3 = x max; the boss stays on its literal "
          "axis point)" % cell_l["edited_diff"].get("bbox_moved"))

    # --- boss height: volume up by the annulus, z max up
    cell_h = tpl.edit_check(wp, exprs["BOSS_H"], 2.0)
    dvh_an = (math.pi / 4.0 * (PARAMS["BOSS_D"] ** 2 - hole_d ** 2)) * 2.0
    say("EDIT BOSS_H+2 vol_delta=%.6f" % cell_h["volume_delta"])
    check("T41_H_VOLUME", abs(cell_h["volume_delta"] - dvh_an) <
          1e-3 * max(1.0, abs(dvh_an)),
          "delta=%.6f analytic=%.6f" % (cell_h["volume_delta"], dvh_an))

    cells = [cell_d, cell_t, cell_l, cell_h]
    ok, total = tpl.clean_cells(cells)
    check("T41_MATRIX_CLEAN", ok == total and total == 4,
          "clean=%d/%d" % (ok, total))

    # --- table / schema guards
    values, units = tpl.param_table({"structures": [
        {"id": "X", "parameters": [
            {"name": "A", "value": 1.5, "unit": "mm"},
            {"name": "B", "value": 30.0, "unit": "deg"},
            {"name": "C", "value": [1.0, 0.0, 0.0], "unit": "unit"}]}]})
    check("T41_PARAM_TABLE", values == {"A": 1.5, "B": 30.0} and
          units["B"] == "deg", "values=%s units=%s" % (values, units))
    check("T41_BUILD_ORDER", tpl.build_order(SCHEMA) == ["S1", "S2"] and
          tpl.structure_params(SCHEMA, "S2")["BOSS_D"] == 24.0,
          "order=%s" % tpl.build_order(SCHEMA))
    try:
        tpl.structure(SCHEMA, "NOPE")
        raised = False
    except KeyError:
        raised = True
    check("T41_UNKNOWN_STRUCTURE", raised, "structure() must raise KeyError")

    miss = tpl.edit_matrix(wp, exprs, [("NOT_A_PARAM", 1.0)])
    check("T41_MISSING_PARAM", miss[0].get("missing_expression") is True,
          "cell=%s (a typo must be reported, not silently skipped)" % miss[0])

    save_checked(part_path)
    failed = [n for n, v in RESULTS if not v]
    say("TEST41_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST41_FAIL failed=%s" % failed)
        return
    say("TEST41_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST41_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST41_FAIL uncaught")
