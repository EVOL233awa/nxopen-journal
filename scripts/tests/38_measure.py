# -*- coding: utf-8 -*-
# Test 38: read-only measurement chain on a controlled solid.
#
# nxlib.measure has two data chains and this case pins both with analytic
# expectations, so a silent regression cannot pass as "some numbers":
#
#   faces   UF_MODL_ask_face_data -> group_coaxial -> hole_params/cone_params
#           A 100x60x20 block with a D20 boss, a D10 through hole through the
#           boss, a second D10 hole with a 90-degree countersink and an R2
#           blend on the first hole's top edge must yield: cylinder group
#           D10/L30 centred at the boss axis, cone group half-angle 45 deg,
#           and one torus face from the blend.
#
#   section DexManager STL (chordal 0.01) -> plane cut -> oriented loops
#           At z=10 the section is the block minus two D10 holes:
#           6000 - 2*pi*25 = 5842.92 mm^2. The same mesh against itself must
#           give IoU 1.0, which is the zero-difference check for the
#           original-vs-rebuilt comparison a reverse-engineering run needs.
#
#   compare measure_part twice on the same file: every cylinder/cone group
#           pairs with itself, so all deltas are zero and nothing is
#           unmatched. That is the exact assertion a self-check makes after
#           a rebuild.
#
#   deviation area-weighted surface samples -> exact point-triangle distance
#           A plane lifted 2 mm gives RMS/P95 2.0 in both directions; the same
#           mesh against itself gives zero, and the same seed reproduces the
#           sample set.
#
#   stations plane families and cylinder/cone axes from the face table ->
#           section IoU per station. The controlled part must yield the block
#           bottom/top, boss top and the hole axes, and every self station
#           must pass. verify_parts composes G0-G6 in one call.
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
from nxlib.modeling import block, boolean, blend_on_edges, expressions
from nxlib.measure import (CYLINDER, CONE, TORUS, PLANE, compare_parts,
                           exact_section, export_mesh, expression_survey,
                           face_table, group_coaxial, hole_params,
                           cone_params, measure_part, mesh_bbox, read_stl,
                           mesh_deviation, sample_surface, section_area,
                           section_iou, station_plan, station_report,
                           verify_parts, view_iou)

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
NULL = NXOpen.NXObject.Null

BLOCK_X, BLOCK_Y, BLOCK_Z = 100.0, 60.0, 20.0
BOSS_R, BOSS_H = 10.0, 10.0
HOLE_R = 5.0
HOLE_A = (30.0, 30.0)
HOLE_B = (70.0, 30.0)
CS_DIA = 20.0
CS_DEPTH = 5.0
BLEND_R = 2.0
SECTION_Z = 10.0
EXPECT_AREA = (BLOCK_X * BLOCK_Y - 2.0 * math.pi * HOLE_R ** 2)


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


def countersink(wp, body, point, direction, hole_diameter, cs_diameter,
                angle, hole_depth):
    """Countersink form: entry cone from cs_diameter down to hole_diameter."""
    hb = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralHoleForm = \
        NXOpen.Features.HolePackageBuilder.HoleForms.Countersink
    hb.GeneralCountersinkHoleDiameter.RightHandSide = _rhs(hole_diameter)
    hb.GeneralCountersinkDiameter.RightHandSide = _rhs(cs_diameter)
    hb.GeneralCountersinkAngle.RightHandSide = _rhs(angle)
    hb.GeneralCountersinkHoleDepth.RightHandSide = _rhs(hole_depth)
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.Value
    _commit_hole(hb, wp, body, point, direction)


def cylinder_body(wp, origin, height, diameter, direction):
    """Standalone cylinder solid (CylinderBuilder); caller unites it."""
    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Cylinder.Null)
    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
    cb.Diameter.RightHandSide = repr(float(diameter))
    cb.Height.RightHandSide = repr(float(height))
    cb.Origin = NXOpen.Point3d(*[float(v) for v in origin])
    cb.Direction = NXOpen.Vector3d(*[float(v) for v in direction])
    cb.CommitFeature()
    cb.Destroy()
    bodies = [b for b in wp.Bodies]
    if len(bodies) != 2:
        raise RuntimeError("cylinder builder produced %d bodies" % len(bodies))
    return bodies[-1]


def _line_dist(p1, d, p2):
    v = [p2[i] - p1[i] for i in range(3)]
    t = sum(v[i] * d[i] for i in range(3))
    return math.sqrt(max(0.0, sum(x * x for x in v) - t * t))


def find_hole_face(part, xy, radius):
    """Cylinder face of the hole at xy with the given radius."""
    u = NXOpen.UF.UFSession.GetUFSession()
    best = None
    for b in part.Bodies:
        for f in b.GetFaces():
            typ, pt, dr, box, rad, rdata, ndir = u.Modeling.AskFaceData(f.Tag)
            if typ != CYLINDER or abs(abs(rad) - radius) > 0.01:
                continue
            n = math.sqrt(sum(x * x for x in dr))
            d = [x / n for x in dr] if n else [0.0, 0.0, 1.0]
            pd = _line_dist(pt, d, [xy[0], xy[1], pt[2]])
            if pd <= 0.05 and (best is None or pd < best[0]):
                best = (pd, f)
    return best[1] if best else None


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part_path = os.path.abspath(os.path.join(OUT_DIR, "t38_measure.prt"))
    stl_path = os.path.abspath(os.path.join(OUT_DIR, "t38_measure.stl"))
    for p in (part_path, stl_path):
        if os.path.exists(p):
            os.remove(p)

    part = new_part(path=part_path)
    block(part, NXOpen.Point3d(0.0, 0.0, 0.0),
          "%.1f" % BLOCK_X, "%.1f" % BLOCK_Y, "%.1f" % BLOCK_Z)
    body = [b for b in part.Bodies][0]

    boss = cylinder_body(part, (HOLE_A[0], HOLE_A[1], BLOCK_Z),
                         BOSS_H, 2.0 * BOSS_R, (0.0, 0.0, 1.0))
    boolean(part, body, boss, NXOpen.Features.Feature.BooleanType.Unite)
    body = [b for b in part.Bodies][0]
    say("BUILT boss volume=%.3f" % part.MeasureManager.NewMassProperties(
        [part.UnitCollection.FindObject(n) for n in
         ("SquareMilliMeter", "CubicMilliMeter", "Kilogram",
          "MilliMeter", "Newton")], [0.99], [body]).Volume)

    # D10 through the boss and the block
    hb = part.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralSimpleHoleDiameter.RightHandSide = _rhs(2.0 * HOLE_R)
    hb.GeneralSimpleHoleDepth.RightHandSide = _rhs(BLOCK_Z + BOSS_H)
    hb.GeneralTipAngle.RightHandSide = "118.0"
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.ThroughBody
    _commit_hole(hb, part, body, (HOLE_A[0], HOLE_A[1], BLOCK_Z + BOSS_H),
                 (0.0, 0.0, -1.0))
    body = [b for b in part.Bodies][0]

    # D10 through the block + 90-degree countersink
    hb = part.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    hb.Type = NXOpen.Features.HolePackageBuilder.Types.GeneralHole
    hb.GeneralSimpleHoleDiameter.RightHandSide = _rhs(2.0 * HOLE_R)
    hb.GeneralSimpleHoleDepth.RightHandSide = _rhs(BLOCK_Z)
    hb.GeneralTipAngle.RightHandSide = "118.0"
    hb.HoleDepthLimitOption = \
        NXOpen.Features.HolePackageBuilder.HoleDepthLimitOptions.ThroughBody
    _commit_hole(hb, part, body, (HOLE_B[0], HOLE_B[1], BLOCK_Z),
                 (0.0, 0.0, -1.0))
    body = [b for b in part.Bodies][0]
    countersink(part, body, (HOLE_B[0], HOLE_B[1], BLOCK_Z),
                (0.0, 0.0, -1.0), 2.0 * HOLE_R, CS_DIA, 90.0, CS_DEPTH + 1.0)
    body = [b for b in part.Bodies][0]

    # R2 blend on the first hole's top edge -> torus face
    face = find_hole_face(part, HOLE_A, HOLE_R)
    check("REG_HOLE_FACE", face is not None,
          "cylinder face R%.1f on the boss axis found=%s" % (HOLE_R, face is not None))
    edges = []
    if face is not None:
        for e in face.GetEdges():
            p0, p1 = e.GetVertices()
            if max(p0.Z, p1.Z) > BLOCK_Z + BOSS_H - 0.1:
                edges.append(e)
    check("REG_TOP_EDGE", len(edges) == 1,
          "top circular edge on the D10 hole: %d found" % len(edges))
    if edges:
        blend_on_edges(part, edges, BLEND_R)
    body = [b for b in part.Bodies][0]

    ufs.Part.Save()
    check("REG_SAVED", os.path.exists(part_path) and
          os.path.getsize(part_path) > 100000,
          "part saved while displayed: %d bytes" %
          (os.path.getsize(part_path) if os.path.exists(part_path) else 0))

    # ---------------------------------------------------------- face table
    faces = face_table(part, with_edges=True)
    types = sorted(set(f["type"] for f in faces))
    say("FACES=%d types=%s" % (len(faces), types))
    check("REG_FACE_TYPES", CYLINDER in types and CONE in types and
          PLANE in types, "face types present=%s" % (types,))
    check("REG_TORUS_FACE", TORUS in types,
          "blend R%.1f produced torus face: types=%s" % (BLEND_R, types))

    cyl = group_coaxial(faces, CYLINDER)
    hole = None
    for g in cyl:
        if abs(g["radius"] - HOLE_R) > 0.01:
            continue
        c = g["center"]
        if math.hypot(c[0] - HOLE_A[0], c[1] - HOLE_A[1]) < 0.05:
            hole = g
            break
    check("REG_CYL_GROUP", hole is not None,
          "R%.1f cylinder groups=%d, boss-axis group found=%s" %
          (HOLE_R, len(cyl), hole is not None))
    if hole is not None:
        hp = hole_params(hole)
        wall = BLOCK_Z + BOSS_H - BLEND_R
        check("REG_HOLE_PARAMS",
              abs(hp["diameter"] - 2.0 * HOLE_R) < 0.01 and
              abs(hp["length"] - wall) < 0.01 and
              abs(hp["center"][2] - 0.5 * wall) < 0.01 and
              abs(abs(hp["axis"][2]) - 1.0) < 1e-6,
              "hole D=%.4f wall L=%.4f center=%s axis=%s" %
              (hp["diameter"], hp["length"],
               ["%.3f" % v for v in hp["center"]],
               ["%.4f" % v for v in hp["axis"]]))

    cones = group_coaxial(faces, CONE)
    check("REG_CONE_GROUP", len(cones) == 1,
          "cone groups=%d" % len(cones))
    if cones:
        cp = cone_params(cones[0])
        check("REG_CONE_PARAMS",
              abs(abs(cp["half_angle_deg"]) - 45.0) < 0.5 and
              abs(cp["length"] - CS_DEPTH) < 0.05 and
              HOLE_R - 0.1 <= cp["radius"] <= CS_DIA / 2.0 + 0.1,
              "cone half=%.4f deg L=%.4f r=%.4f" %
              (cp["half_angle_deg"], cp["length"], cp["radius"]))

    # ------------------------------------------------------ section checks
    export_mesh(part, stl_path)
    mesh = read_stl(stl_path)
    say("STL=%s tris=%d" % (os.path.basename(stl_path), len(mesh)))
    bbox = mesh_bbox(mesh)
    expect_bbox = [0.0, 0.0, 0.0, BLOCK_X, BLOCK_Y, BLOCK_Z + BOSS_H]
    check("REG_MESH_BBOX",
          max(abs(bbox[i] - expect_bbox[i]) for i in range(6)) <= 0.01,
          "STL bbox=%s expected=%s" %
          (["%.3f" % v for v in bbox], ["%.3f" % v for v in expect_bbox]))
    area = section_area(mesh, (0.0, 0.0, SECTION_Z), (0.0, 0.0, 1.0))
    check("REG_SECTION_AREA", abs(area - EXPECT_AREA) <= 0.005 * EXPECT_AREA,
          "z=%.1f section area=%.3f analytic=%.3f (err %.4f%%)" %
          (SECTION_Z, area, EXPECT_AREA,
           100.0 * (area - EXPECT_AREA) / EXPECT_AREA))
    iou = section_iou(mesh, mesh, (0.0, 0.0, SECTION_Z), (0.0, 0.0, 1.0))
    check("REG_SECTION_IOU_SELF", abs(iou["iou"] - 1.0) < 1e-9,
          "same mesh vs itself IoU=%.12f (step=%.3f)" %
          (iou["iou"], iou["step"]))
    top = view_iou(mesh, mesh, "top")
    check("REG_VIEW_IOU", abs(top["iou"] - 1.0) < 1e-9 and
          abs(top["area_a"] - EXPECT_AREA) <= 0.005 * EXPECT_AREA,
          "top view IoU=%.12f area=%.3f analytic=%.3f (step=%.3f)" %
          (top["iou"], top["area_a"], EXPECT_AREA, top["step"]))

    # ------------------------------------------------------ self compare
    cmp = compare_parts(part_path, part_path)
    deltas = []
    all_pairs_pass = True
    for key in ("cylinders", "cones"):
        for pair in cmp[key]["pairs"]:
            deltas.extend((abs(pair["delta_radius"]), abs(pair["delta_length"]),
                           pair["delta_center"], pair["delta_axis_deg"],
                           pair["delta_half_angle_deg"]))
            all_pairs_pass = all_pairs_pass and pair["pass"]
    check("REG_COMPARE_SELF",
          cmp["pass"] and all_pairs_pass and
          cmp["cylinders"]["unmatched_a"] == [] and
          cmp["cylinders"]["unmatched_b"] == [] and
          cmp["cones"]["unmatched_a"] == [] and
          cmp["cones"]["unmatched_b"] == [] and
          abs(cmp["delta_volume"]) < 1e-6 and
          (not deltas or max(deltas) < 1e-6),
          "self compare: cyl=%d pairs, cone=%d pairs, unmatched=%d/%d, "
          "max delta=%.9f, dV=%.9f, pass=%s" %
          (len(cmp["cylinders"]["pairs"]), len(cmp["cones"]["pairs"]),
           len(cmp["cylinders"]["unmatched_a"]) + len(cmp["cones"]["unmatched_a"]),
           len(cmp["cylinders"]["unmatched_b"]) + len(cmp["cones"]["unmatched_b"]),
           max(deltas) if deltas else 0.0, cmp["delta_volume"], cmp["pass"]))

    mp = measure_part(part_path)
    check("REG_UNITS",
          mp["units"] == "mm" and abs(mp["length_scale"] - 1.0) < 1e-12,
          "units=%s scale=%.6f" % (mp["units"], mp["length_scale"]))
    inv = mp["cylinders"] + mp["cones"]
    cmp_inv = compare_parts(part_path, part_path, ref_a=inv)
    check("REG_COMPARE_INVENTORY",
          cmp_inv["pass"] and
          len(cmp_inv["cylinders"]["pairs"]) == len(mp["cylinders"]) and
          len(cmp_inv["cones"]["pairs"]) == len(mp["cones"]),
          "inventory compare: %d cyl + %d cone groups, pass=%s" %
          (len(cmp_inv["cylinders"]["pairs"]),
           len(cmp_inv["cones"]["pairs"]), cmp_inv["pass"]))

    # ------------------------------------------------- deviation + stations
    pts_a = sample_surface(mesh, count=300, seed=11)
    pts_b = sample_surface(mesh, count=300, seed=11)
    pts_c = sample_surface(mesh, count=300, seed=12)
    check("REG_SAMPLE_SEED",
          len(pts_a) == 300 and pts_a == pts_b and pts_a != pts_c,
          "deterministic samples=%d, different seed differs=%s" %
          (len(pts_a), pts_a != pts_c))
    dev_self = mesh_deviation(mesh, mesh, samples=800)
    check("REG_DEVIATION_SELF",
          dev_self["pass"] and dev_self["a_to_b"]["max"] < 1e-8 and
          dev_self["b_to_a"]["max"] < 1e-8,
          "self deviation max %.3e / %.3e" %
          (dev_self["a_to_b"]["max"], dev_self["b_to_a"]["max"]))
    nrm = [0.0, 0.0, 1.0]
    plane_a = [(nrm, [0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0])]
    plane_b = [(nrm, [0.0, 0.0, 2.0], [10.0, 0.0, 2.0], [0.0, 10.0, 2.0])]
    dev_shift = mesh_deviation(plane_a, plane_b, samples=600, seed=5)
    check("REG_DEVIATION_SHIFT",
          abs(dev_shift["a_to_b"]["rms"] - 2.0) < 1e-6 and
          abs(dev_shift["b_to_a"]["p95"] - 2.0) < 1e-6,
          "2 mm plane shift: rms %.6f/%.6f p95 %.6f/%.6f" %
          (dev_shift["a_to_b"]["rms"], dev_shift["b_to_a"]["rms"],
           dev_shift["a_to_b"]["p95"], dev_shift["b_to_a"]["p95"]))

    plan = station_plan(mp)
    normals = [tuple(round(v, 3) for v in s["normal"])
               for s in plan["stations"]]
    check("REG_STATION_PLAN",
          plan["count"] >= 7 and plan["axis_count"] >= 3 and
          (0.0, 0.0, 1.0) in normals and
          any(abs(s["offset"]) < 1e-6 for s in plan["stations"]),
          "stations=%d plane=%d axis=%d normals=%s" %
          (plan["count"], plan["plane_count"], plan["axis_count"],
           sorted(set(normals))))
    rep = station_report(mesh, mesh, plan)
    check("REG_STATION_SELF",
          rep["pass"] and rep["count"] == plan["count"] and
          all(abs(r["iou"] - 1.0) < 1e-9 and
              r["only_a"] <= max(1.0, 0.01 * abs(r["area_a"])) and
              r["only_b"] <= max(1.0, 0.01 * abs(r["area_b"]))
              for r in rep["stations"]),
          "self station report count=%d failed=%d max only=%.3e/%.3e" %
          (rep["count"], len(rep["failed"]),
           max(r["only_a"] for r in rep["stations"]),
           max(r["only_b"] for r in rep["stations"])))

    ver = verify_parts(part_path, part_path, samples=800, max_stations=48)
    check("REG_VERIFY_SELF",
          ver["pass"] and ver["gates"]["G1"]["pass"] and
          ver["gates"]["G2"]["pass"] and ver["gates"]["G6"]["pass"],
          "verify_parts self: gates=%s stations=%d" %
          (dict((k, ver["gates"][k]["pass"]) for k in
                ("G0", "G1", "G2", "G3", "G4", "G5", "G6")),
           ver["stations"]["count"]))

    fake_faces = [{"type": PLANE, "point": [0.0, 0.0, float(i)],
                   "dir": [0.0, 0.0, 1.0]} for i in range(40)]
    fake_groups = [{"point": [float(i), 0.0, 0.0], "axis": [1.0, 0.0, 0.0],
                    "extent": [0.0, 20.0], "radius": 1.0 + i,
                    "faces": [i]} for i in range(20)]
    thin = station_plan({"faces": fake_faces, "cylinders": fake_groups,
                         "cones": []}, max_stations=12)
    check("REG_STATION_BUDGET",
          thin["count"] <= 12 and thin["plane_count"] >= 1 and
          thin["axis_count"] >= 1 and not thin["complete"] and
          thin["dropped"] > 0,
          "budget=12 stations=%d plane=%d axis=%d dropped=%d" %
          (thin["count"], thin["plane_count"], thin["axis_count"],
           thin["dropped"]))

    # B-rep section, not STL: block minus two D10 holes at z=10.
    bs = exact_section(part, (0.0, 0.0, SECTION_Z), (0.0, 0.0, 1.0))
    closed = sorted([l for l in bs["loops"] if l["closed"]],
                    key=lambda l: -l["abs_area"])
    check("REG_EXACT_SECTION",
          len(closed) == 3 and
          abs(closed[0]["abs_area"] - BLOCK_X * BLOCK_Y) <= 0.01 and
          all(abs(l["abs_area"] - math.pi * HOLE_R ** 2) <= 0.5
              for l in closed[1:]) and
          not bs["open_gaps"] and
          all(l["gap"] < 1e-6 for l in closed),
          "B-rep section loops=%d areas=%s open=%d gaps=%s" %
          (len(closed), ["%.3f" % l["abs_area"] for l in closed],
           bs["open"], bs["open_gaps"]))

    # Editability: one named expression must drive real geometry, restore to
    # the same volume, and the part must stay single-body/alive.
    expressions(part, [("TEST_L", 20.0)])
    before = set(b.Tag for b in part.Bodies)
    block(part, NXOpen.Point3d(90.0, 10.0, 0.0), "TEST_L", "20.0", "18.0")
    extra = [b for b in part.Bodies if b.Tag not in before][0]
    body = [b for b in part.Bodies if b.Tag in before][0]
    boolean(part, body, extra, NXOpen.Features.Feature.BooleanType.Unite)
    survey = expression_survey(part)
    check("REG_EXPRESSION_SURVEY",
          survey["pass"] and survey["named"] == ["TEST_L"] and
          [x["name"] for x in survey["live"]] == ["TEST_L"] and
          not survey["dead"] and not survey["broken"],
          "survey named=%s live=%d dead=%d ratio=%.2f bodies=%d" %
          (survey["named"], len(survey["live"]), len(survey["dead"]),
           survey["alive_ratio"], survey["bodies"]))

    failed = [n for n, v in RESULTS if not v]
    say("TEST38_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST38_FAIL failed=%s" % failed)
        return
    say("TEST38_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST38_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST38_FAIL uncaught")
