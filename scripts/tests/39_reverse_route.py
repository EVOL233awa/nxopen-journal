# -*- coding: utf-8 -*-
# Test 39: reverse-engineering route -- structure directory and fillet map.
#
# A reverse run starts from a measured face table, not from a feature tree, so
# the two questions it must answer before any modelling are "which faces form
# one functional structure" and "which faces are fillets, of what radius".
# nxlib.measure answers both as pure functions over the face table:
#
#   structure_directory  coaxial cylinder/cone groups, torus groups and plane
#                        families.  The controlled part below (80x50x16 block,
#                        D16 boss 8 high, D10 through hole on the boss axis,
#                        D6 hole with a 90 degree countersink) must give: a D16
#                        group spanning the boss only, a D10 group spanning
#                        block+boss, a cone group at 45 degrees half angle, and
#                        plane families at z=0/16/24.
#
#   fillet_map           faces bucketed by roll radius, each with its support
#                        faces.  The R2 blend on the boss top rim must come out
#                        as one type-19 face whose stored radius is the torus
#                        major radius (8-2), not the roll radius: the roll
#                        radius lives in rad_data, which is the convention that
#                        makes a radius sweep usable.  Its supports must name
#                        the boss wall (16/R8) and a plane (22).
#
# The radius sweep must also surface a hole wall at its own radius; that is
# correct behaviour, and the supports are what separates a blend from a bore
# (the bore's supports are both planes, the blend's include a curved face).
#
# The same controlled part carries the open-chain cutter: a straight convex
# rim is rolled with roll_edge/apply_roll (section = corner minus tangent
# circle, extruded along the edge) and must remove (R^2 - pi*R^2/4) * L and
# leave a cylinder of exactly the roll radius.
#   Radius entry: face_blend passes str(radius), so a named expression string
#   reaches CircularCrossSection.SetRadius unquoted; this test uses a numeric
#   BLEND_R and does not exercise the expression path.
import math
import os

import NXOpen
import NXOpen.Features
import NXOpen.UF


import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part
from nxlib.modeling import (apply_roll, block, boolean, face_blend_edge,
                            volume)
from nxlib.measure import (CYLINDER, TORUS, compare_parts, face_table,
                           fillet_coverage, fillet_map, fillet_run_samples,
                           g7_reachability, g9_structure, hole_audit,
                           hole_params, measure_part, station_report,
                           structure_directory, view_iou)

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
NULL = NXOpen.NXObject.Null

BLOCK = (80.0, 50.0, 16.0)
BOSS_R, BOSS_H = 8.0, 8.0
BOSS_XY = (25.0, 25.0)
HOLE_R = 5.0
CS_R, CS_ANGLE = 9.0, 90.0
CS_HOLE_R = 3.0
CS_XY = (60.0, 25.0)
CS_HOLE_DEPTH = 12.0  # must exceed the countersink depth (CS_R - CS_HOLE_R)
BLEND_R = 2.0


def _rhs(v):
    return v if isinstance(v, str) else repr(float(v))


def _commit_hole(hb, wp, body, point, direction):
    pt = wp.Points.CreatePoint(NXOpen.Point3d(*[float(v) for v in point]))
    rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])
    hb.HolePosition.AddToSection([rule], pt, NULL, NULL,
                                 NXOpen.Point3d(*[float(v) for v in point]),
                                 NXOpen.Section.Mode.Create, False)
    hb.BooleanOperation.SetBooleanOperationAndBody(
        NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract, body)
    hb.ProjectionDirection.ProjectDirectionMethod = \
        NXOpen.GeometricUtilities.ProjectionOptionsDirectionType.Vector
    hb.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(
        pt, NXOpen.Vector3d(*[float(v) for v in direction]))
    hb.Tolerance = 0.0254
    hb.Validate()
    hb.CommitFeature()
    hb.Destroy()


def simple_hole(wp, body, point, direction, diameter):
    hb = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralHoleForm = NXOpen.Features.HolePackageBuilder.HoleForms.Simple
    hb.GeneralSimpleHoleDiameter.RightHandSide = _rhs(diameter)
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.ThroughBody
    _commit_hole(hb, wp, body, point, direction)


def countersink(wp, body, point, direction, hole_diameter, cs_diameter,
                angle, depth):
    hb = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralHoleForm = \
        NXOpen.Features.HolePackageBuilder.HoleForms.Countersink
    hb.GeneralCountersinkHoleDiameter.RightHandSide = _rhs(hole_diameter)
    hb.GeneralCountersinkDiameter.RightHandSide = _rhs(cs_diameter)
    hb.GeneralCountersinkAngle.RightHandSide = _rhs(angle)
    hb.GeneralCountersinkHoleDepth.RightHandSide = _rhs(depth)
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.Value
    _commit_hole(hb, wp, body, point, direction)


def boss(wp, body, origin, diameter, height, direction):
    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Cylinder.Null)
    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
    cb.Diameter.RightHandSide = repr(float(diameter))
    cb.Height.RightHandSide = repr(float(height))
    cb.Origin = NXOpen.Point3d(*[float(v) for v in origin])
    cb.Direction = NXOpen.Vector3d(*[float(v) for v in direction])
    cb.CommitFeature()
    cb.Destroy()
    extra = [b for b in wp.Bodies if b.Tag != body.Tag]
    boolean(wp, body, extra[0], NXOpen.Features.Feature.BooleanType.Unite)
    return body


def _group_at(directory, kind, radius, radius_tol=0.01):
    for g in directory[kind]:
        if abs(g["radius"] - radius) <= radius_tol:
            return g
    return None


def main():
    part_path = os.path.join(OUT_DIR, "t39_reverse_route.prt")
    part = new_part("t39", part_path)
    wp = part
    ufs = NXOpen.UF.UFSession.GetUFSession()

    f = block(wp, NXOpen.Point3d(0.0, 0.0, 0.0),
              repr(BLOCK[0]), repr(BLOCK[1]), repr(BLOCK[2]))
    body = f.GetBodies()[0]
    boss(wp, body, (BOSS_XY[0], BOSS_XY[1], BLOCK[2]),
         "%.4f" % (2.0 * BOSS_R), repr(BOSS_H), (0.0, 0.0, 1.0))
    simple_hole(wp, body, (BOSS_XY[0], BOSS_XY[1], BLOCK[2] + BOSS_H),
                (0.0, 0.0, -1.0), 2.0 * HOLE_R)
    countersink(wp, body, (CS_XY[0], CS_XY[1], BLOCK[2]), (0.0, 0.0, -1.0),
                2.0 * CS_HOLE_R, 2.0 * CS_R, CS_ANGLE, CS_HOLE_DEPTH)
    body = [b for b in part.Bodies][0]

    # R2 roll on the boss top rim: the fixture every reverse run needs, an
    # open rim that a blend can still close because it is a full circle.
    rim = []
    for e in body.GetEdges():
        p0, p1 = e.GetVertices()
        if not (abs(p0.Z - (BLOCK[2] + BOSS_H)) < 0.01 and
                abs(p1.Z - (BLOCK[2] + BOSS_H)) < 0.01):
            continue
        r = math.hypot(p0.X - BOSS_XY[0], p0.Y - BOSS_XY[1])
        if abs(r - BOSS_R) < 0.01:
            rim.append(e)
    check("REG_RIM_EDGE", len(rim) == 1,
          "boss top circular edge found=%d" % len(rim))
    blend_ok = False
    blend_rev = None
    if rim:
        try:
            _, blend_rev = face_blend_edge(part, rim[0], BLEND_R)
            blend_ok = True
        except Exception as exc:
            say("REG_FACE_BLEND_FAIL %s" % str(exc)[:200])
    check("REG_FACE_BLEND", blend_ok,
          "FaceBlend on boss rim ok=%s rev=%s" % (blend_ok, blend_rev))
    body = [b for b in part.Bodies][0]

    # Straight convex rim: the open-chain cutter.  An EdgeBlend cannot
    # terminate on an open chain, so the roll is a tool: section = corner
    # minus the tangent circle, extruded past both ends, subtracted.  A 90
    # degree edge of length L with roll R removes (R^2 - pi*R^2/4) * L.
    ROLL_R = 4.0
    edge = None
    for e in body.GetEdges():
        vs = e.GetVertices()
        if len(vs) != 2:
            continue
        if (abs(vs[0].Z - BLOCK[2]) < 0.01 and abs(vs[1].Z - BLOCK[2]) < 0.01
                and abs(vs[0].Y) < 0.01 and abs(vs[1].Y) < 0.01
                and abs(abs(vs[0].X - vs[1].X) - BLOCK[0]) < 0.01):
            edge = e
            break
    check("REG_ROLL_EDGE", edge is not None, "straight top rim found")
    roll_ok = False
    if edge is not None:
        exp = (ROLL_R * ROLL_R - math.pi * ROLL_R * ROLL_R / 4.0) * BLOCK[0]
        v0 = volume(part, body)
        roll_ok, body = apply_roll(part, body, edge, ROLL_R)
        dv = v0 - volume(part, body)
        check("REG_ROLL_CUT", roll_ok and 0.7 * exp < dv < 1.3 * exp,
              "roll ok=%s dv=%.1f expected=%.1f" % (roll_ok, dv, exp))
    ufs.Part.Save()
    assert os.path.exists(part_path) and os.path.getsize(part_path) > 0, \
        "save did not land: %s" % part_path

    faces = face_table(part, with_edges=True)
    roll_faces = [f for f in faces
                  if f["type"] == CYLINDER and abs(f["radius"] - ROLL_R) < 0.01]
    check("REG_ROLL_FACE", roll_ok and len(roll_faces) >= 1,
          "R%.1f roll cylinder faces=%d" % (ROLL_R, len(roll_faces)))
    d = structure_directory(faces, cluster_tol=8.0)

    boss_group = _group_at(d, "cylinders", BOSS_R)
    check("REG_STRUCT_BOSS", boss_group is not None and
          abs(boss_group["length"] - (BOSS_H - BLEND_R)) < 0.01,
          "boss group R%.1f length=%.3f" %
          (BOSS_R, boss_group["length"] if boss_group else -1.0))

    hole_group = _group_at(d, "cylinders", HOLE_R)
    hp = hole_params(hole_group) if hole_group else None
    check("REG_STRUCT_HOLE",
          hp is not None and abs(hp["diameter"] - 2.0 * HOLE_R) < 0.01 and
          abs(hp["length"] - (BLOCK[2] + BOSS_H)) < 0.01 and
          abs(abs(hp["axis"][2]) - 1.0) < 1e-6,
          "hole group D=%s L=%s axis=%s" %
          ("%.3f" % hp["diameter"] if hp else "-",
           "%.3f" % hp["length"] if hp else "-",
           ["%.3f" % v for v in hp["axis"]] if hp else "-"))

    cone = None
    for g in d["cones"]:
        if abs(abs(g["half_angle_deg"]) - CS_ANGLE * 0.5) < 0.05:
            cone = g
            break
    check("REG_STRUCT_CONE", cone is not None,
          "cone group half_angle=%s (want %.1f)" %
          ("%.3f" % cone["half_angle_deg"] if cone else "-", CS_ANGLE * 0.5))

    zplanes = [p for p in d["plane_families"]
               if abs(abs(p["normal"][2]) - 1.0) < 1e-3]
    offsets = sorted(round(abs(p["offset"]), 2) for p in zplanes)
    check("REG_STRUCT_PLANES", offsets == [0.0, BLOCK[2], BLOCK[2] + BOSS_H],
          "z plane family offsets=%s" % (offsets,))

    torus = [g for g in d["torus_groups"]
             if abs(g["major"] - (BOSS_R - BLEND_R)) < 0.01 and
             abs(g["minor"] - BLEND_R) < 0.01]
    check("REG_STRUCT_TORUS", torus and torus[0]["nfaces"] >= 1,
          "torus group R%.3f faces=%s" %
          (BOSS_R - BLEND_R, torus[0]["nfaces"] if torus else "-"))

    # Fillet map: the roll radius is rad_data, the stored radius is the major
    # radius.  Both must be reported, and the supports must name the two faces
    # the roll sits between.
    fmap = fillet_map(faces, radii=[BLEND_R])
    group = fmap[0] if fmap else None
    face_rec = None
    if group:
        for s in group["face_supports"]:
            if abs(s["bbox"][5] - (BLOCK[2] + BOSS_H)) < 1.0:
                face_rec = s
                break
    check("REG_FILLET_FOUND", group is not None and group["nfaces"] >= 1 and
          face_rec is not None,
          "R%.1f fillet faces=%s" %
          (BLEND_R, group["nfaces"] if group else "-"))
    sup = " ".join(face_rec["supports"]) if face_rec else ""
    check("REG_FILLET_SUPPORTS",
          ("16/R%.3f" % BOSS_R) in sup and ("22/" in sup),
          "roll supports=%s" % (sup or "-"))

    by_tag = dict((f["tag"], f) for f in faces)
    roll = [f for f in faces
            if f["type"] == TORUS and abs(abs(f["rad_data"]) - BLEND_R) < 0.002]
    check("REG_FILLET_RAD_DATA",
          len(roll) == 1 and abs(roll[0]["radius"] - (BOSS_R - BLEND_R)) < 0.01,
          "roll faces=%d stored radius=%s (major), rad_data=%s" %
          (len(roll), "%.3f" % roll[0]["radius"] if roll else "-",
           "%.3f" % roll[0]["rad_data"] if roll else "-"))

    # Run-level geometry (G7geo): the same two blends must form two runs with
    # UV-center samples, and comparing the set with itself must be 100%
    # covered.  Face-count ratios are segmentation dependent; this is not.
    rr = fillet_run_samples(part, faces, [BLEND_R, ROLL_R])
    cov = fillet_coverage(rr, rr)
    sample_ok = all(r["centers"] and r["samples"] for r in rr)
    check("REG_FILLET_RUNS", len(rr) >= 2 and sample_ok,
          "runs=%d faces=%d centers/samples=%s" %
          (len(rr), sum(r["nfaces"] for r in rr), sample_ok))
    check("REG_FILLET_COVER_SELF",
          abs(cov["coverage"] - 1.0) < 1e-9 and
          abs(cov["run_coverage"] - 1.0) < 1e-9 and
          cov["p95_max"] is not None and cov["p95_max"] < 1e-6,
          "self coverage=%.3f run=%.3f p95_max=%s" %
          (cov["coverage"], cov["run_coverage"], cov["p95_max"]))

    # A bore is a cylinder at its own radius and is expected to appear when
    # that radius is swept; its supports are both planes, which is how a
    # directory builder tells a bore from a roll without guessing.
    bore = fillet_map(faces, radii=[CS_HOLE_R])
    bore_sup = " ".join(" ".join(s["supports"])
                        for g in bore for s in g["face_supports"])
    check("REG_BORE_VS_ROLL",
          bool(bore_sup) and "16/" not in bore_sup and "19/" not in bore_sup,
          "bore supports=%s (a bore is swept by its own radius; unlike a roll "
          "its neighbours are cones/planes, never a cylinder or torus)"
          % (bore_sup or "-"))

    check("REG_SINGLE_BODY", len(list(part.Bodies)) == 1 and
          all(t in by_tag for t in by_tag),
          "bodies=%d faces=%d types=%s" %
          (len(list(part.Bodies)), len(faces),
           sorted(set(f["type"] for f in faces))))

    # Concave rim: a pocket floor is rolled by uniting the same tool.  The
    # detector must read the two faces as concave (each face lies on the void
    # side of the other); the volume must grow by the same corner-minus-circle
    # section times the edge length.
    part2 = new_part("t39c", os.path.join(OUT_DIR,
                                         "t39_reverse_roll_concave.prt"))
    f2 = block(part2, NXOpen.Point3d(0.0, 0.0, 0.0),
               "40.0", "40.0", "10.0")
    body2 = f2.GetBodies()[0]
    pf = block(part2, NXOpen.Point3d(10.0, 10.0, 6.0),
               "20.0", "20.0", "6.0")
    boolean(part2, body2, pf.GetBodies()[0],
            NXOpen.Features.Feature.BooleanType.Subtract)
    body2 = [b for b in part2.Bodies][0]
    CONC_R = 3.0
    cedge = None
    for e in body2.GetEdges():
        vs = e.GetVertices()
        if len(vs) != 2:
            continue
        if (abs(vs[0].Y - 10.0) < 0.01 and abs(vs[1].Y - 10.0) < 0.01
                and abs(vs[0].Z - 6.0) < 0.01 and abs(vs[1].Z - 6.0) < 0.01
                and abs(abs(vs[0].X - vs[1].X) - 20.0) < 0.01):
            cedge = e
            break
    check("REG_CONC_EDGE", cedge is not None, "pocket floor rim found")
    conc_ok = False
    if cedge is not None:
        exp2 = (CONC_R * CONC_R - math.pi * CONC_R * CONC_R / 4.0) * 20.0
        w0 = volume(part2, body2)
        conc_ok, body2 = apply_roll(part2, body2, cedge, CONC_R)
        dv2 = volume(part2, body2) - w0
        check("REG_CONC_ADD", conc_ok and 0.7 * exp2 < dv2 < 1.3 * exp2,
              "concave ok=%s dv=%.2f expected=%.2f" %
              (conc_ok, dv2, exp2))
    cfaces = face_table(part2, with_edges=False)
    check("REG_CONC_FACE",
          conc_ok and any(f["type"] == CYLINDER and
                          abs(f["radius"] - CONC_R) < 0.01 for f in cfaces),
          "concave roll cylinder faces=%d" %
          sum(1 for f in cfaces
              if f["type"] == CYLINDER and abs(f["radius"] - CONC_R) < 0.01))
    check("REG_CONC_BODY", len(list(part2.Bodies)) == 1,
          "concave bodies=%d" % len(list(part2.Bodies)))

    # Negative paths: a false PASS is worse than a false FAIL, so the gates
    # that used to pass on empty input are exercised on empty/degenerate data.
    meas = measure_part(part_path)
    audit = hole_audit(meas, part)
    check("REG_HOLE_AUDIT", audit["total"] >= 2 and
          len(audit["denominator"]) >= 1,
          "hole audit total=%d denominator=%d" %
          (audit["total"], len(audit["denominator"])))

    empty = station_report([], [], {"stations": [], "dropped": 0})
    check("REG_G1_EMPTY", not empty["pass"] and "no stations" in empty["reasons"],
          "empty station plan pass=%s reasons=%s" %
          (empty["pass"], empty["reasons"]))

    vi = view_iou([], [], "top")
    check("REG_VIEW_EMPTY", vi["iou"] == 0.0 and vi.get("empty") is True,
          "empty view iou=%s empty=%s" % (vi["iou"], vi.get("empty")))

    # 一条跑道对数万个参考面时 ceiling 必趋 0，但那是诊断值：判 BLOCKED 需要
    # 逐跑道的拓扑证据（支撑面宽度/二面角/边已被消费），比例本身证明不了不可达。
    reach = g7_reachability([{"radius": BLEND_R, "nfaces": 10000}], faces)
    say("g7 reach ceiling=%.4f blocked=%s evidence=%r"
        % (reach["ceiling"], reach["blocked"], reach["evidence"]))
    check("REG_G7_CEILING",
          reach["blocked"] is False and reach["evidence"] == [] and
          reach["ceiling"] < 0.70 and
          "diagnostic" in reach["ceiling_basis"],
          "ceiling must stay a diagnostic: ceiling=%.4f blocked=%s "
          "evidence=%r basis=%r" %
          (reach["ceiling"], reach["blocked"], reach["evidence"],
           reach["ceiling_basis"]))

    structures = (len(d["cylinders"]) + len(d["cones"]) +
                  len(d["torus_groups"]))
    g9_loose = g9_structure(part, 100)
    g9_tight = g9_structure(part, structures, feature_factor=0.1,
                            feature_offset=0)
    say("g9 loose=%r tight=%r"
        % (g9_loose["reasons"], g9_tight["reasons"]))
    # 只报特征数的 G9 会放过"11 个无名 extrude"：名字缺失本身就要 FAIL，
    # 预算超限要单独给出"features N > limit"的原因。
    check("REG_G9_NAMES_REQUIRED",
          not g9_loose["pass"] and
          any("names" in r for r in g9_loose["reasons"]),
          "unnamed features must fail G9: %r" % (g9_loose["reasons"],))
    check("REG_G9_LIMIT",
          not g9_tight["pass"] and
          g9_tight["feature_count"] > g9_tight["feature_limit"] and
          any("features" in r for r in g9_tight["reasons"]),
          "loose pass=%s tight pass=%s limit=%.1f reasons=%s" %
          (g9_loose["pass"], g9_tight["pass"], g9_tight["feature_limit"],
           g9_tight["reasons"]))

    rev = list(reversed(audit["denominator"]))
    cmp_rev = compare_parts(part_path, part_path, ref_a=rev)
    check("REG_COMPARE_ORDER", cmp_rev["applicable"] and cmp_rev["pass"] and
          not cmp_rev["missing_groups"],
          "reversed ref groups=%d applicable=%s pass=%s missing=%d" %
          (len(rev), cmp_rev["applicable"], cmp_rev["pass"],
           len(cmp_rev["missing_groups"])))

    failed = [n for n, v in RESULTS if not v]
    say("TEST39_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST39_FAIL failed=%s" % failed)
        return
    say("TEST39_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST39_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST39_FAIL uncaught")
