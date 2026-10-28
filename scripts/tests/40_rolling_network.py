# -*- coding: utf-8 -*-
# Test 40: rolling-ball corner network -- analytic type16/19 faces.
#
# A reverse run rebuilds supports sharp first, then rolls every edge.  The
# built fillet face must be an analytic cylinder or torus, because the
# coverage gate matches faces by stored radius/rad_data:
#
#   straight edge   section = corner minus tangent circle, extruded along the
#                   edge -> type 16 with radius = roll radius.
#   circular rim    the roll centre is NOT the rim circle: it sits one roll
#                   radius inside the section.  A square-section ring revolved
#                   about that centre circle, four FaceBlends, and a split by
#                   one quarter band gives a type 19 face whose rad_data is the
#                   roll radius and whose major is the roll-centre radius.
#                   Both a Z rim and a 45 degree axis rim are checked.
#   horn rim        major == roll radius: the full square ring would cross the
#                   axis, so the outside ring (section from the axis out,
#                   outer corners blended) is used instead.
#
# The classification path must read the same face back: +-R offset collapse
# gives canal_circle, and rim_from_face returns the spine circle that a
# reverse run measured in the first place.
import math
import os

import NXOpen
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
from nxlib.modeling import block, boolean, volume
from nxlib.rolling import (apply_roll_general, classify_corner,
                           edge_geometry, rim_from_face, rim_roll_center)

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
EPS = 0.02


def cyl(wp, origin, direction, diameter, height):
    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Cylinder.Null)
    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
    cb.Diameter.RightHandSide = repr(float(diameter))
    cb.Height.RightHandSide = repr(float(height))
    cb.Origin = NXOpen.Point3d(*[float(v) for v in origin])
    cb.Direction = NXOpen.Vector3d(*[float(v) for v in direction])
    feat = cb.CommitFeature()
    cb.Destroy()
    return feat.GetBodies()[0]


def face_rows(part, body):
    u = NXOpen.UF.UFSession.GetUFSession()
    out = []
    for f in body.GetFaces():
        try:
            typ, pt, dr, box, rad, rdata, ndir = u.Modeling.AskFaceData(f.Tag)
            out.append({"face": f, "type": int(typ), "radius": float(rad),
                        "rad_data": float(rdata)})
        except Exception:
            pass
    return out


def pick_rim(body, radius, axis, axial, tol=0.05):
    ax = [float(v) for v in axis]
    for e in body.GetEdges():
        g = edge_geometry(e, 11)
        if not g.get("ok") or g.get("kind") != "circle":
            continue
        ci = g["circle"]
        if abs(ci["r"] - radius) > tol:
            continue
        h = sum(ci["center"][i] * ax[i] for i in range(3))
        if abs(h - axial) <= tol:
            return e
    return None


def check_rim(part, body, edge, radius, rim_r, tag):
    info = rim_roll_center(part, edge, radius, False)
    check(tag + "_CENTRE",
          info is not None and abs(info["major"] - (rim_r - radius)) < 0.01,
          "%s roll-centre major=%s want %.4f" %
          (tag, "%.4f" % info["major"] if info else "-", rim_r - radius))
    if info is None:
        return None
    exp = info["area"] * 2.0 * math.pi * info["r_centroid"]
    v0 = volume(part, body)
    res = apply_roll_general(part, body, edge, radius, add=False)
    check(tag + "_KIND", res.get("ok") and res.get("kind") == "circle_analytic",
          "%s kind=%s reason=%s" %
          (tag, res.get("kind"), str(res.get("reason"))[:80]))
    if not res.get("ok"):
        return None
    dv = v0 - volume(part, res["body"])
    check(tag + "_VOL", 0.4 * exp < dv < 1.3 * exp,
          "%s removed=%.2f expected=%.2f" % (tag, dv, exp))
    want_major = rim_r - radius + EPS
    bands = [r for r in face_rows(part, res["body"])
             if r["type"] == 19 and abs(r["rad_data"] - radius) < 1e-3]
    check(tag + "_TORUS", len(bands) == 1 and
          abs(bands[0]["radius"] - want_major) < 0.03,
          "%s type19 rad_data=%s major=%s want=%.3f" % (
              tag,
              ["%.4f" % b["rad_data"] for b in bands],
              ["%.4f" % b["radius"] for b in bands], want_major))
    return res, bands[0] if bands else None


def case_straight():
    part = new_part("t40_edge", os.path.join(OUT_DIR, "t40_edge.prt"))
    f = block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "80.0", "50.0", "16.0")
    body = f.GetBodies()[0]
    edge = None
    for e in body.GetEdges():
        vs = e.GetVertices()
        if len(vs) != 2:
            continue
        if (abs(vs[0].Z - 16.0) < 0.01 and abs(vs[1].Z - 16.0) < 0.01 and
                abs(vs[0].Y) < 0.01 and abs(vs[1].Y) < 0.01 and
                abs(abs(vs[0].X - vs[1].X) - 80.0) < 0.01):
            edge = e
            break
    check("T40_EDGE_FOUND", edge is not None, "straight top rim")
    if edge is None:
        return
    R = 4.0
    exp = (R * R - math.pi * R * R / 4.0) * 80.0
    v0 = volume(part, body)
    res = apply_roll_general(part, body, edge, R, add=False)
    check("T40_EDGE_KIND", res.get("ok") and res.get("kind") == "line",
          "kind=%s" % res.get("kind"))
    if not res.get("ok"):
        return
    dv = v0 - volume(part, res["body"])
    check("T40_EDGE_VOL", 0.7 * exp < dv < 1.3 * exp,
          "removed=%.2f expected=%.2f" % (dv, exp))
    faces = [r for r in face_rows(part, res["body"])
             if r["type"] == 16 and abs(r["radius"] - R) < 1e-3]
    check("T40_EDGE_CYL", len(faces) >= 1, "R%.1f cylinder faces=%d" %
          (R, len(faces)))


def case_z_rim():
    part = new_part("t40_z", os.path.join(OUT_DIR, "t40_z.prt"))
    flange = cyl(part, (0.0, 0.0, -20.0), (0.0, 0.0, 1.0), 120.0, 20.0)
    boss = cyl(part, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 16.0, 24.0)
    boolean(part, flange, boss, NXOpen.Features.Feature.BooleanType.Unite)
    body = [x for x in part.Bodies][0]
    rim = pick_rim(body, 8.0, (0.0, 0.0, 1.0), 24.0)
    check("T40_Z_FOUND", rim is not None, "Z free-end rim")
    if rim is None:
        return
    got = check_rim(part, body, rim, 2.0, 8.0, "T40_Z")
    if got is None:
        return
    res, band = got
    if band is None:
        return
    info = classify_corner(part, band["face"].Tag, 2.0)
    check("T40_Z_CLASS", info.get("ok") and
          info.get("kind") == "canal_circle" and
          abs(info["circle"]["r"] - band["radius"]) < 0.03 and
          info["thickness"] <= 0.005 * 2.0,
          "kind=%s spine=%s thick=%s" % (
              info.get("kind"),
              "%.4f" % info["circle"]["r"] if info.get("circle") else "-",
              "%.5f" % info.get("thickness", -1.0)))
    rim_info = rim_from_face(part, band["face"].Tag, 2.0)
    check("T40_Z_RIM", rim_info.get("ok") and rim_info.get("rim") is not None and
          abs(rim_info["rim"]["r"] - band["radius"]) < 0.03,
          "rim r=%s" % ("%.4f" % rim_info["rim"]["r"]
                        if rim_info.get("rim") else "-"))


def case_diag_rim():
    part = new_part("t40_diag", os.path.join(OUT_DIR, "t40_diag.prt"))
    ax = (0.7071067811865476, 0.7071067811865476, 0.0)
    flange = cyl(part, (-20.0 * ax[0], -20.0 * ax[1], 0.0), ax, 120.0, 20.0)
    boss = cyl(part, (0.0, 0.0, 0.0), ax, 38.1, 30.0)
    boolean(part, flange, boss, NXOpen.Features.Feature.BooleanType.Unite)
    body = [x for x in part.Bodies][0]
    edge = pick_rim(body, 19.05, ax, 30.0)
    check("T40_DIAG_FOUND", edge is not None, "diagonal free-end rim")
    if edge is None:
        return
    g = edge_geometry(edge, 11)
    check("T40_DIAG_AXIS",
          g.get("ok") and g["kind"] == "circle" and
          abs(abs(g["circle"]["axis"][0]) - 0.70710678) < 0.01 and
          abs(abs(g["circle"]["axis"][1]) - 0.70710678) < 0.01,
          "axis=%s" % (["%.3f" % v for v in g["circle"]["axis"]]
                       if g.get("ok") else "-"))
    check_rim(part, body, edge, 3.175, 19.05, "T40_DIAG")


def case_horn():
    part = new_part("t40_horn", os.path.join(OUT_DIR, "t40_horn.prt"))
    f = block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "60.0", "60.0", "10.0")
    body = f.GetBodies()[0]
    b = cyl(part, (30.0, 30.0, 10.0), (0.0, 0.0, 1.0), 12.7, 10.0)
    boolean(part, body, b, NXOpen.Features.Feature.BooleanType.Unite)
    body = [x for x in part.Bodies][0]
    rim = pick_rim(body, 6.35, (0.0, 0.0, 1.0), 20.0)
    check("T40_HORN_FOUND", rim is not None, "horn free-end rim")
    if rim is None:
        return
    info = rim_roll_center(part, rim, 3.175, False)
    check("T40_HORN_MAJOR",
          info is not None and abs(info["major"] - 3.175) < 0.01,
          "roll-centre major=%s (horn)" %
          ("%.4f" % info["major"] if info else "-"))
    if info is None:
        return
    exp = info["area"] * 2.0 * math.pi * info["r_centroid"]
    v0 = volume(part, body)
    res = apply_roll_general(part, body, rim, 3.175, add=False)
    check("T40_HORN_KIND",
          res.get("ok") and res.get("kind") == "circle_analytic",
          "kind=%s reason=%s" % (res.get("kind"),
                                 str(res.get("reason"))[:80]))
    if not res.get("ok"):
        return
    dv = v0 - volume(part, res["body"])
    check("T40_HORN_VOL", 0.4 * exp < dv < 1.3 * exp,
          "removed=%.2f expected=%.2f" % (dv, exp))
    bands = [r for r in face_rows(part, res["body"])
             if r["type"] == 19 and abs(r["rad_data"] - 3.175) < 1e-3]
    check("T40_HORN_TORUS", len(bands) == 1 and
          abs(bands[0]["radius"] - (3.175 + EPS)) < 0.03,
          "type19 rad_data=%s major=%s" % (
              ["%.4f" % b["rad_data"] for b in bands],
              ["%.4f" % b["radius"] for b in bands]))


def main():
    case_straight()
    case_z_rim()
    case_diag_rim()
    case_horn()
    failed = [n for n, v in RESULTS if not v]
    say("TEST40_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST40_FAIL failed=%s" % failed)
        return
    say("TEST40_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST40_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST40_FAIL uncaught")
