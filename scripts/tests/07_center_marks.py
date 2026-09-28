# -*- coding: utf-8 -*-
# Test 07: center marks and 2D centerlines in headless batch (requires
# bracket.prt from 01_bracket.py; builds its own sheet and views, saves nothing).
#
# History, because this file used to be an expected-failure probe:
#   2026-08-22 / 2026-09-18  "annotation objects cannot be created in batch"  -> wrong
#   2026-09-18  "root cause: the sheet was never Open()ed"  -> also wrong
#   2026-09-20  measured root cause: CenterMarkBuilder fails as soon as one
#               builder carries 3 or more locations.
#                  n=1 -> OK   n=2 -> OK   n=3 -> 1175305
#                  n=4 -> 1175305         n=8 -> 1175307
#                with one builder per location: 4/4 marks created. sheet.Open()
#                is NOT required (verified both on a sheet saved as current and
#                on a sheet inserted in this session).
# The case therefore gates the working recipe and re-measures the rejection, so
# a future NX build that changes the behaviour shows up as CENTERMARK_MULTI=...
# in the log instead of passing silently.
import os
import sys

import NXOpen
import NXOpen.Annotations
import NXOpen.Drawings
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import FAILED_STAGES, stage

PART = os.path.abspath("bracket.prt")
SHEET_NAME = "SHT_CM"
HOLE_R = 4.0
# one builder carrying this many locations is expected to be rejected
MULTI_N = 3


def main():
    s = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part, _ = s.Parts.Open(PART)
    ufs.Part.SetDisplayPart(part.Tag)
    body = [b for b in part.Bodies][0]

    def make_sheet():
        names = set(sh.Name for sh in part.DrawingSheets)
        if SHEET_NAME not in names:
            part.DrawingSheets.InsertSheet(
                SHEET_NAME, NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
                1.0, 1.0, NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle)
        sheet = [sh for sh in part.DrawingSheets if sh.Name == SHEET_NAME][0]
        if not list(sheet.GetDraftingViews()):
            svb = part.DraftingViews.CreateStandardViewsBuilder()
            svb.Part = part
            svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Drawing
            svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
            svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
            svb.Autoscale = True
            svb.Commit()
            svb.Destroy()
        return sheet
    sheet = stage("sheet_and_views", make_sheet)
    if sheet is None:
        print("TEST07_FAIL no_sheet")
        return

    views = {v.Name.split("@")[0].upper(): v for v in sheet.GetDraftingViews()}
    if "TOP" not in views:
        print("TEST07_FAIL no_top_view")
        return
    vtop = views["TOP"]

    def hole_circles():
        """Near-end circle of every Ø8 hole: match p1 == p2 (a full circle
        reports its centre twice), keep the larger z of the two wall circles."""
        by_xy = {}
        for face in body.GetFaces():
            if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
                continue
            try:
                r = abs(ufs.Modeling.AskFaceData(face.Tag)[4])
            except Exception:
                continue
            if abs(r - HOLE_R) > 0.01:
                continue
            for e in face.GetEdges():
                p1, p2 = e.GetVertices()
                if abs(p1.X - p2.X) > 0.05 or abs(p1.Y - p2.Y) > 0.05:
                    continue
                key = (round(p1.X, 3), round(p1.Y, 3))
                if key not in by_xy or p1.Z > by_xy[key][0].Z:
                    by_xy[key] = (p1, e)
        items = [by_xy[k] for k in sorted(by_xy)]
        print("HOLE_CIRCLES=%d" % len(items))
        if len(items) != 4:
            raise RuntimeError("expected 4 hole circles, got %d" % len(items))
        return items
    holes = stage("resolve_holes", hole_circles)
    if holes is None:
        print("TEST07_FAIL resolve_holes")
        return

    def one_builder(items):
        cmb = part.Annotations.Centerlines.CreateCenterMarkBuilder(
            NXOpen.Annotations.CenterMark.Null)
        for p, e in items:
            cmb.Locations.Add(e, vtop, NXOpen.Point3d(p.X, p.Y, p.Z))
        try:
            cmb.Commit()
            return True
        except Exception:
            return False
        finally:
            try:
                cmb.Destroy()
            except Exception:
                pass

    def multi_location_note():
        """Report (do not gate) the multi-location behaviour: it is the reason
        this file was an expected-failure probe for a month."""
        got = one_builder(holes[:MULTI_N])
        print("CENTERMARK_MULTI n=%d %s"
              % (MULTI_N, "accepted" if got else "rejected"))
        if got:
            print("CENTERMARK_MULTI_CHANGED re-measure references/assembly-drafting.md B.2")
    stage("multi_location_note", multi_location_note)

    def per_builder_recipe():
        ok = 0
        for p, e in holes:
            cmb = part.Annotations.Centerlines.CreateCenterMarkBuilder(
                NXOpen.Annotations.CenterMark.Null)
            cmb.Locations.Add(e, vtop, NXOpen.Point3d(p.X, p.Y, p.Z))
            try:
                cmb.Commit()
                ok += 1
            except Exception as exc:
                print("CENTERMARK_FAIL at (%.1f,%.1f) :: %s"
                      % (p.X, p.Y, str(exc)[:120]))
            finally:
                cmb.Destroy()
        print("CENTERMARK_PER_BUILDER=%d/4" % ok)
        if ok != 4:
            raise RuntimeError("only %d of 4 center marks created" % ok)
    stage("center_marks", per_builder_recipe)

    def centerline_2d():
        (pa, ea), (pb, eb) = holes[0], holes[1]
        c2 = part.Annotations.Centerlines.CreateCenterline2dBuilder(
            NXOpen.Annotations.Centerline2d.Null)
        c2.Type = c2.Types.ByPoints
        c2.Point1.SetValue(ea, vtop, NXOpen.Point3d(pa.X, pa.Y, pa.Z))
        c2.Point2.SetValue(eb, vtop, NXOpen.Point3d(pb.X, pb.Y, pb.Z))
        c2.Commit()
        c2.Destroy()
        print("CENTERLINE2D_OK")
    stage("centerline_2d", centerline_2d)

    if FAILED_STAGES:
        print("TEST07_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    print("TEST07_DONE marks=4")


if __name__ == "__main__":
    main()
