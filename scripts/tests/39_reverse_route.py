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
from nxlib.modeling import block, boolean, blend_on_edges
from nxlib.measure import (CONE, CYLINDER, PLANE, TORUS, face_table,
                           fillet_map, hole_params, structure_directory)

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
    if rim:
        blend_on_edges(part, rim, BLEND_R)
    body = [b for b in part.Bodies][0]
    ufs.Part.Save()

    faces = face_table(part, with_edges=True)
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
