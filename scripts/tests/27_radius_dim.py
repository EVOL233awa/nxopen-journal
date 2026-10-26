# -*- coding: utf-8 -*-
# Test 27: UF radius dimension -- what the call actually requires.
#
# The probe recorded "CreateRadiusDim needs a genuine arc edge; the
# D10 hole only offers two circle edges, no candidate" and never called the
# function. That record was a probe artefact: the probe filtered candidates by
# radius and bailed before the call. Measured again (NX 12.0.0.27,
# headless batch), on a plate that carries BOTH kinds of circular edge:
#
#   ufs.Drf.CreateRadiusDim(uf_obj(edge, view, assoc, dwg_xy), ufs.Drf.Text(),
#                           [org_x, org_y, 0.0])
#
#   fillet arc  (R10, quarter circle, two distinct vertices) -> RadiusDimension,
#               ComputedSize 10.0000, text "10"
#   hole circle (R10, p1 == p2 == centre)                    -> RadiusDimension,
#               ComputedSize 10.0000, text "10"
#   straight edge                                            -> refused
#
# So the requirement is a CIRCULAR edge, not specifically an arc: the full
# circle of a hole carries a radius dimension as happily as a fillet arc. The
# distinction that matters for picking a candidate is
# edge.SolidEdgeType == NXOpen.Edge.EdgeType.Circular (a straight edge of the
# same cylindrical face is EdgeType.Linear and reports the same face radius if
# the radius is read off the face instead of the edge -- the trap).
import os
import sys

import NXOpen
import NXOpen.Drawings
import NXOpen.Features
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part
from nxlib.modeling import ARC_TOL, block, classify_edges

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts")
PART = os.path.join(OUT_DIR, "t27_radius_dim.prt")

HOLE_X = 40.0
HOLE_Y = 40.0
HOLE_D = 20.0
FILLET_R = 10.0
PLATE_L = 120.0
PLATE_W = 80.0
PLATE_H = 12.0


def main():
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part = new_part(path=PART)
    block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "%.1f" % PLATE_L, "%.1f" % PLATE_W,
          "%.1f" % PLATE_H)
    body = [b for b in part.Bodies][0]

    # ---- R10 fillet on the vertical corner edge at (PLATE_L, PLATE_W)
    corner = []
    for e in body.GetEdges():
        try:
            p1, p2 = e.GetVertices()
        except Exception:
            continue
        if (abs(p1.X - PLATE_L) < ARC_TOL and abs(p1.Y - PLATE_W) < ARC_TOL
                and abs(p2.X - PLATE_L) < ARC_TOL and abs(p2.Y - PLATE_W) < ARC_TOL):
            corner.append(e)
    check("REG_CORNER_EDGE", len(corner) == 1,
          "vertical corner edges at (%.0f,%.0f) = %d" % (PLATE_L, PLATE_W, len(corner)))
    rule = part.ScRuleFactory.CreateRuleEdgeDumb([corner[0]])
    col = part.ScCollectors.CreateCollector()
    col.ReplaceRules([rule], False)
    eb = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    eb.AddChainset(col, "%.4f" % FILLET_R)
    blend = eb.CommitFeature()
    eb.Destroy()
    col.Destroy()
    check("REG_FILLET_COMMITTED", blend is not None, "feature=%s" % blend)

    # ---- D20 through hole: same nominal radius as the fillet, on purpose
    body = [b for b in part.Bodies][0]
    top = None
    bottom = None
    for f in body.GetFaces():
        d = ufs.Modeling.AskFaceData(f.Tag)
        if d[0] != 22:
            continue
        if abs(d[2][2] - 1.0) < 0.01 and top is None:
            top = f
        if abs(d[2][2] + 1.0) < 0.01:
            bottom = f
    part.Expressions.CreateSystemExpressionWithUnits(
        "R27_HOLE_D = %.4f" % HOLE_D, part.UnitCollection.GetBase("Length"))
    hb = part.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
    hb.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
    hb.SetSimpleHole(NXOpen.Point3d(HOLE_X, HOLE_Y, PLATE_H), False, top, "R27_HOLE_D")
    hb.SetThruFace(bottom)
    hb.HoleLocation = NXOpen.Point3d(HOLE_X, HOLE_Y, PLATE_H)
    hb.CommitFeature()
    hb.Destroy()

    # ---- candidates
    body = [b for b in part.Bodies][0]
    cand = classify_edges(body)
    arcs = [c for c in cand if c[4] == "arc" and abs(c[0] - FILLET_R) < 0.01]
    circles = [c for c in cand if c[4] == "circle" and abs(c[0] - FILLET_R) < 0.01]
    lines = [c for c in cand if c[4] == "line"]
    say("CANDIDATES arcs=%d circles=%d lines=%d" % (len(arcs), len(circles), len(lines)))
    for tag, lst in (("ARC", arcs), ("CIRCLE", circles), ("LINE", lines)):
        for r, e, p1, p2, kind in lst:
            say("CAND %s r=%.3f tag=%s p1=(%.3f,%.3f,%.3f) p2=(%.3f,%.3f,%.3f)"
                % (tag, r, e.Tag, p1.X, p1.Y, p1.Z, p2.X, p2.Y, p2.Z))
    check("REG_ARC_EDGE_FOUND", len(arcs) >= 1,
          "%d partial-circle edge(s) of R%.0f" % (len(arcs), FILLET_R))
    check("REG_CIRCLE_EDGE_FOUND", len(circles) >= 1,
          "%d full-circle edge(s) of R%.0f" % (len(circles), FILLET_R))
    check("REG_LINE_EDGE_FOUND", len(lines) >= 1,
          "%d straight edges on the cylindrical faces (the radius-only filter "
          "picked these up)" % len(lines))

    # ---- drawing
    sheet = part.DrawingSheets.InsertSheet(
        "SHT1", NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4, 1.0, 1.0,
        NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle)
    sheet.Open()
    svb = part.DraftingViews.CreateStandardViewsBuilder()
    svb.Part = part
    svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
    svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
    svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
    svb.Autoscale = True
    svb.Commit()
    svb.Destroy()
    sheet.Open()
    vtop = None
    for v in sheet.GetDraftingViews():
        if v.Name.upper().startswith("TOP"):
            vtop = v
    check("REG_TOP_VIEW", vtop is not None, "views=%s"
          % [v.Name for v in sheet.GetDraftingViews()])
    ufs.Draw.SetViewScale(vtop.Tag, 1.0)

    def map_pt(xyz):
        try:
            r = ufs.View.MapModelToDrawing(vtop.Tag, list(xyz))
            c = r[1] if isinstance(r, tuple) else r
            if hasattr(c, "__len__") and len(c) >= 2:
                return float(c[0]), float(c[1])
        except Exception as exc:
            say("MAP_FAIL %s :: %s" % (str(xyz), str(exc)[:120]))
        ref = vtop.GetDrawingReferencePoint()
        return ref.X + xyz[0], ref.Y + xyz[1]

    ATC = NXOpen.UF.Drf.AssocType

    def uf_obj(edge, assoc, dwg_xy):
        o = ufs.Drf.Object()
        ufs.Drf.InitObjectStructure(o)
        o.ObjectAssocType = getattr(ATC, assoc)
        o.ObjectTag = edge.Tag
        o.ObjectViewTag = vtop.Tag
        o.AssocDwgPos = [float(dwg_xy[0]), float(dwg_xy[1])]
        return o

    def dims():
        return dict((int(d.Tag), d) for d in part.Dimensions)

    def radius_dim(label, edge, assoc, dwg_xy, org):
        """Returns (ok, detail). Only a RadiusDimension counts as success."""
        before = dims()
        try:
            r = ufs.Drf.CreateRadiusDim(uf_obj(edge, assoc, dwg_xy),
                                        ufs.Drf.Text(), list(org))
        except Exception as exc:
            return False, "refused: %s: %s" % (type(exc).__name__, str(exc)[:160])
        after = dims()
        new = [after[t] for t in after if t not in before]
        kinds = sorted(set(type(d).__name__ for d in new))
        if len(new) != 1 or kinds != ["RadiusDimension"]:
            return False, "created %d object(s) kinds=%s ret=%s" % (len(new), kinds, r)
        d = new[0]
        try:
            main, dual = d.GetDimensionText()
            text = main[0] if main else ""
        except Exception as exc:
            text = "text? %s" % str(exc)[:60]
        ok = (abs(d.ComputedSize - FILLET_R) < 0.01 and str(text).strip() == "10")
        return ok, ("tag=%s computed=%.4f text=%r" % (d.Tag, d.ComputedSize, text))

    ref = vtop.GetDrawingReferencePoint()
    lane = ref.Y - 30.0

    r, e, p1, p2, kind = arcs[0]
    mid = map_pt(((p1.X + p2.X) / 2.0, (p1.Y + p2.Y) / 2.0, p1.Z))
    ok, detail = radius_dim("arc", e, "ARC_CENTER", mid,
                            (mid[0] + 18.0, mid[1] + 18.0, 0.0))
    check("REG_RADIUS_ARC_DIM", ok, detail)

    r, e, p1, p2, kind = circles[0]
    c = map_pt((p1.X, p1.Y, p1.Z))
    ok, detail = radius_dim("circle", e, "ARC_CENTER", c,
                            (c[0] + 30.0, c[1] + 30.0, 0.0))
    check("REG_RADIUS_CIRCLE_DIM", ok,
          "%s (falsifies 'needs a genuine arc edge', not a circle)" % detail)

    r, e, p1, p2, kind = lines[0]
    start = map_pt((p1.X, p1.Y, p1.Z))
    before = dims()
    line_refused = False
    line_msg = ""
    try:
        ufs.Drf.CreateRadiusDim(uf_obj(e, "END_POINT", start), ufs.Drf.Text(),
                                [lane, lane, 0.0])
        after = dims()
        new = [after[t] for t in after if t not in before]
        line_refused = (len(new) == 0)
        line_msg = "no dimension created (returned without a dimension)"
    except Exception as exc:
        line_refused = True
        line_msg = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    check("REG_RADIUS_LINE_REFUSED", line_refused,
          "straight edge -> %s" % line_msg)

    kinds = {}
    for d in part.Dimensions:
        k = type(d).__name__
        kinds[k] = kinds.get(k, 0) + 1
    say("DIM_KINDS %s" % sorted(kinds.items()))
    check("REG_TWO_RADIUS_DIMS", kinds.get("RadiusDimension", 0) == 2,
          "RadiusDimension=%d (expected exactly the arc and the circle)"
          % kinds.get("RadiusDimension", 0))

    ufs.Part.Save()
    size = os.path.getsize(PART) if os.path.exists(PART) else 0
    check("REG_ARTIFACTS_LANDED", size > 0, "PART=%s size=%d" % (PART, size))

    failed = [n for n, v in RESULTS if not v]
    say("TEST27_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST27_FAIL failed=%s" % failed)
        return
    say("TEST27_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST27_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST27_FAIL uncaught")
