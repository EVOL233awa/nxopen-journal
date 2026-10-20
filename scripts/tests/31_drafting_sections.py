# -*- coding: utf-8 -*-
# Test 31: the section-view variants test 21 does not reach -- half section,
# revolved section, and the unfolded toggle.
#
# Measured, NX 12.0.0.27, headless batch. Part: 120x80x12 plate with a
# D20 through hole at (60,40), A4 sheet, standard Base views (Front/Top/Right),
# cut plane at z=6 (mid height, halves the through hole).
#
# HALF SECTION
#   svb.SectionViewType = SectionViewBuilder.SectionLineType.Half
#   svb.ParentView.View.Value = <Front view>
#   cut path = 3 points forming an L in the parent's projection plane:
#     (20,40,6) -> (60,40,6) -> (60,40,12)   leg through the hole axis, then
#                                            perpendicular out to the top face
#   Commit() gives a real section view: AskSxlineType -> HALF_SXLINE (value 4),
#   AskHalfSxline answers with 8 fields (the 6th is the segment count 3, the 7th is
#   the tag list length 3 -- and the straight 2-point path below reads 8 as well)
#   while every other Ask*Sxline refuses with "Section line is not correct type.",
#   AskSxsolidsOfSxview -> 1, 18 visible objects (DraftingCurve 8 + Hatch 1),
#   IsOutOfDate False. The tuple width is NOT a fixed constant, so the check here
#   is a lower bound (>= 7) plus the field positions that are actually read.
#   A straight 2-point path under the same label also commits (17 visible
#   objects, DraftingCurve 7), so the label alone does not check the path shape.
#   In both cases the segment list reads back Length=3: Length counts segment
#   ends, not the points handed in (a 2-point path still reported 3, and the
#   revolved legs read back 2 per point added).
#
# REVOLVED SECTION
#   segs = svb.SectionLineSegments          (NXOpen.Drawings.SectionLineSegmentsBuilder)
#   segs.RotationPoint = <NXOpen.Point>     <- a Point, NOT a Point3d: assigning a
#     Point3d raises TypeError "Expecting NXOpen.Point type, found NXOpen.Point3d"
#     (measured). Leaving it unset is what made an earlier probe report a dead end:
#     the default rotation point coincides with the bend point and AddCutSegment
#     raises NXException "Rotation and bend points cannot be coincident."
#   segs.SegmentLocation.AddCutSegment(...)            leg 1: (20,40,6) -> (60,40,6)
#   segs.SegmentLocationForSecondLeg.AddCutSegment(..) leg 2: (60,70,6)   at 90 deg
#   Commit() -> REVOLVED_SXLINE (value 3), AskRevolvedSxline answers with 11 fields
#   in this configuration (2 + 1 cut points; the 8th is the leg-segment count, read
#   as 4, and the two legs' SegmentLocation.Length read 4 and 2), AskSxsolidsOfSxview
#   -> 2 or 3 depending on how many legs cross material, Hatch 1, IsOutOfDate False.
#
# UNFOLDED (the ViewUnfolded toggle)
#   svb.ViewUnfolded = True commits (readback True, and CreateFolded flips from its
#   default True to False), but the section line stays REVOLVED_SXLINE and the
#   per-object readings are identical to the folded control (4 visible objects,
#   DraftingCurve 3 + Hatch 1, same leg vectors and leg count). The one measured
#   difference is the exported sheet, and that byte count floats with the view
#   names and view count on the sheet (three measured pairs: 18372/18414,
#   18248/18077, 18246/18077 -- the order is not even stable), so the assertion
#   below is only "both exports are real content and are not byte identical".
#   So the assertions here are: the toggle sticks, the view is a valid section, and
#   the two exports are both real content yet not byte identical. The section-line
#   TYPE cannot be used to check unfolding -- ufs.Draw.SxlineType carries
#   UNFOLDED_SXLINE, but neither SectionViewBuilder.SectionLineType (Half /
#   PointAndAngle / PointToPoint / Revolved / SimpleStepped) nor
#   Drawings.SectionLineBuilder.Types (Half / HalfPictorial / Oriented / Pictorial /
#   PointAndAngle / PointToPoint / Revolved / SimpleOrStepped) has an unfolded
#   member, and ufs.Draw.AskUnfoldedSxline refuses both lines here with
#   "Section line is not correct type." The UF entry ufs.Draw.CreateUnfoldedSxview
#   exists but belongs to the UF section routes already recorded as needing a
#   UF_DRF_object cut object.
import os
import sys
import traceback

import NXOpen
import NXOpen.Drawings
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import FAILED_STAGES, say, stage
from nxlib.modeling import find_planar_face
from nxlib.drafting import (
    add_cut_points, export_pdf, new_section_view, sxline_type_name, view_kinds,
)

PART_NAME = "sx31_plate.prt"
HOLE_CENTRE_X = 60.0
HOLE_DIA = 20.0
PLATE_X, PLATE_Y, PLATE_Z = 120.0, 80.0, 12.0
CUT_Z = 6.0
PLACE_DROP = 70.0
PARENT_VISIBLE_MIN = 10
SECTION_VISIBLE_MIN = 4
HATCH_MIN = 1
PDF_MIN_BYTES = 5000          # a blank A4 sheet exports as 917 bytes (measured, test 20)

HALF_PATH = ((20.0, 40.0, CUT_Z), (60.0, 40.0, CUT_Z), (60.0, 40.0, PLATE_Z))
HALF_STRAIGHT_PATH = ((20.0, 40.0, CUT_Z), (110.0, 40.0, CUT_Z))
REVOLVED_LEG1 = ((20.0, 40.0, CUT_Z), (60.0, 40.0, CUT_Z))
REVOLVED_LEG2 = ((60.0, 70.0, CUT_Z),)
ROTATION_POINT = (0.0, 0.0, CUT_Z)
# the member list measured on this build; the class attribute of the same shape is
# the enum itself, while the writable property is SectionViewType
SECTION_LINE_TYPES = ["Half", "PointAndAngle", "PointToPoint", "Revolved",
                      "SimpleStepped"]
# ufs.Draw.SxlineType as measured; only the first five are reachable from the
# .NET section-view builder
UF_SXLINE_TYPES = ["BREAKLINE", "FOLDED_SXLINE", "HALF_SXLINE", "REVOLVED_SXLINE",
                   "SIMPLE_SXLINE", "STEPPED_SXLINE", "UNFOLDED_SXLINE"]


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    SVB = NXOpen.Drawings.SectionViewBuilder
    state = {}

    def s0_new_part():
        target = os.path.abspath(PART_NAME)
        if os.path.exists(target):
            os.remove(target)
        fn = session.Parts.FileNew()
        fn.Units = NXOpen.Part.Units.Millimeters
        fn.TemplateFileName = "model-plain-1-mm-template.prt"
        fn.NewFileName = PART_NAME
        fn.UseBlankTemplate = False
        part = fn.Commit()
        fn.Destroy()
        session.Parts.SetWork(part)
        ufs.Part.SetDisplayPart(part.Tag)

        blk = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0),
                                "%.1f" % PLATE_X, "%.1f" % PLATE_Y,
                                "%.1f" % PLATE_Z)
        blk.CommitFeature()
        blk.Destroy()
        body = None
        for b in part.Bodies:
            body = b
        if body is None:
            raise RuntimeError("no body after the block feature")
        top = find_planar_face(body,
                               NXOpen.Point3d(HOLE_CENTRE_X, 40.0, PLATE_Z), 1.0)
        bottom = find_planar_face(body,
                                  NXOpen.Point3d(HOLE_CENTRE_X, 40.0, 0.0), -1.0)
        if top is None or bottom is None:
            raise RuntimeError("through-hole faces not found")
        part.Expressions.CreateSystemExpressionWithUnits(
            "HOLE_D = %.4f" % HOLE_DIA, part.UnitCollection.GetBase("Length"))
        hole = part.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
        hole.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
        hole.SetSimpleHole(NXOpen.Point3d(HOLE_CENTRE_X, 40.0, PLATE_Z), False,
                           top, "HOLE_D")
        hole.SetThruFace(bottom)
        hole.HoleLocation = NXOpen.Point3d(HOLE_CENTRE_X, 40.0, PLATE_Z)
        hole.CommitFeature()
        hole.Destroy()
        cyl = 0
        for f in body.GetFaces():
            if ufs.Modeling.AskFaceData(f.Tag)[0] == 16:      # 16 = cylindrical
                cyl += 1
        if cyl < 1:
            raise RuntimeError("the hole feature committed but the body has no "
                               "cylindrical face; nothing was cut")

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
        counts = []
        for v in list(sheet.GetDraftingViews()):
            n = len(v.AskVisibleObjects() or [])
            counts.append("%s:%d" % (v.Name, n))
            if n < PARENT_VISIBLE_MIN:
                raise RuntimeError("parent view %s has only %d visible objects"
                                   % (v.Name, n))
            if v.Name.startswith("Front"):
                state["front"] = v
            if v.Name.startswith("Top"):
                state["top"] = v
        if "front" not in state or "top" not in state:
            raise RuntimeError("Front/Top parent views not found")
        state["part"] = part
        state["sheet"] = sheet
        state["ref"] = state["front"].GetDrawingReferencePoint()
        say("PARENTS=%s cylinders=%d ref=(%.3f,%.3f)"
            % (",".join(counts), cyl, state["ref"].X, state["ref"].Y))

    def s1_enum_members():
        got = sorted(n for n in dir(SVB.SectionLineType) if not n.startswith("_")
                     and n != "ValueOf")
        if got != sorted(SECTION_LINE_TYPES):
            raise RuntimeError("SectionViewBuilder.SectionLineType members are %s, "
                               "expected %s" % (got, sorted(SECTION_LINE_TYPES)))
        uf = sorted(n for n in dir(ufs.Draw.SxlineType)
                    if not n.startswith("_") and n != "ValueOf")
        if uf != sorted(UF_SXLINE_TYPES):
            raise RuntimeError("ufs.Draw.SxlineType members are %s, expected %s"
                               % (uf, sorted(UF_SXLINE_TYPES)))
        say("ENUMS builder=%s uf=%s" % (got, uf))

    def s2_half_section():
        part = state["part"]
        ref = state["ref"]
        svb = new_section_view(part, state["front"], SVB.SectionLineType.Half,
                              NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP, 0.0))
        try:
            n_in = add_cut_points(part, svb.SectionLineSegments.SegmentLocation,
                                  HALF_PATH)
            view = svb.Commit()
        finally:
            svb.Destroy()
        if not ufs.Draw.IsSxview(view.Tag):
            raise RuntimeError("committed %s is not a section view" % view.Tag)
        sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
        if not sxline:
            raise RuntimeError("the half section has no section line attached")
        stype = ufs.Draw.AskSxlineType(sxline)
        if stype != ufs.Draw.SxlineType.HALF_SXLINE:
            raise RuntimeError("the half section reports %s, not HALF_SXLINE"
                               % sxline_type_name(ufs, stype))
        half = ufs.Draw.AskHalfSxline(sxline)
        if not hasattr(half, "__len__") or len(half) < 7:
            raise RuntimeError("AskHalfSxline returned %r" % (half,))
        try:
            ufs.Draw.AskSteppedSxline(sxline)
            raise RuntimeError("AskSteppedSxline accepted a half section line")
        except RuntimeError:
            raise
        except Exception as exc:
            if "not correct type" not in str(exc):
                raise RuntimeError("AskSteppedSxline failed with %s, not the type "
                                   "check: %s" % (type(exc).__name__, exc))
        n, solids = ufs.Draw.AskSxsolidsOfSxview(view.Tag,
                                                 ufs.Draw.SxlineLeg.SXLINE_LEG1)
        vis, kinds = view_kinds(state["sheet"], view)
        if n < 1 or not solids:
            raise RuntimeError("the half section sectioned %s solid(s)" % n)
        if len(vis) < SECTION_VISIBLE_MIN:
            raise RuntimeError("the half section has only %d visible objects"
                               % len(vis))
        if kinds.get("Hatch", 0) < HATCH_MIN:
            raise RuntimeError("no Hatch in the half section (kinds=%s)" % kinds)
        if view.IsOutOfDate:
            raise RuntimeError("half section %s is out of date" % view.Name)
        state["half_vis"] = len(vis)
        state["half_fields"] = len(half)
        say("HALF view=%s type=%s sxline_fields=%d segs=%s tags=%d vis=%d hatch=%d "
            "kinds=%s cut_list_len=%s"
            % (view.Name, sxline_type_name(ufs, stype), len(half), half[5],
               len(half[6]), len(vis), kinds.get("Hatch", 0),
               ",".join("%s:%d" % kv for kv in sorted(kinds.items())), n_in))

    def s3_half_straight_path_also_commits():
        # documents that the label alone does not pin the path shape: a straight
        # two-point path under the Half label commits as a half section too
        part = state["part"]
        ref = state["ref"]
        svb = new_section_view(part, state["front"], SVB.SectionLineType.Half,
                              NXOpen.Point3d(ref.X, ref.Y - 2.0 * PLACE_DROP, 0.0))
        try:
            n_in = add_cut_points(part, svb.SectionLineSegments.SegmentLocation,
                                  HALF_STRAIGHT_PATH)
            view = svb.Commit()
        finally:
            svb.Destroy()
        sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
        stype = ufs.Draw.AskSxlineType(sxline)
        vis, kinds = view_kinds(state["sheet"], view)
        if stype != ufs.Draw.SxlineType.HALF_SXLINE:
            raise RuntimeError("a straight path under the Half label reports %s, "
                               "which changes what the label means"
                               % sxline_type_name(ufs, stype))
        # the AskHalfSxline tuple is not a fixed width: record the two readings side
        # by side so the reference file can state which path gives which length
        half = ufs.Draw.AskHalfSxline(sxline)
        state["half_straight_fields"] = len(half)
        say("HALF_STRAIGHT view=%s type=%s fields=%d segs=%s tags=%d cut_list_len=%s "
            "vis=%d kinds=%s"
            % (view.Name, sxline_type_name(ufs, stype), len(half), half[5],
               len(half[6]), n_in, len(vis),
               ",".join("%s:%d" % kv for kv in sorted(kinds.items()))))

    def s4_revolved_section():
        part = state["part"]
        ref = state["ref"]
        svb = new_section_view(part, state["top"], SVB.SectionLineType.Revolved,
                              NXOpen.Point3d(ref.X, ref.Y - 3.0 * PLACE_DROP, 0.0))
        try:
            segs = svb.SectionLineSegments
            # the rotation point is a Point object, not a Point3d: the Point3d
            # assignment must raise, otherwise a later NX build changed the type
            try:
                # 故意写错并断言必抛（静态检查的负向对照，故带豁免标记）
                segs.RotationPoint = NXOpen.Point3d(*ROTATION_POINT)  # check_journal: expected-raise
                raise RuntimeError("SectionLineSegments.RotationPoint accepted a "
                                   "Point3d; the measured type requirement is gone")
            except RuntimeError:
                raise
            except Exception as exc:
                if "NXOpen.Point" not in str(exc):
                    raise RuntimeError("RotationPoint rejected a Point3d with %s, "
                                       "not the type check: %s"
                                       % (type(exc).__name__, exc))
            segs.RotationPoint = part.Points.CreatePoint(
                NXOpen.Point3d(*ROTATION_POINT))
            n1 = add_cut_points(part, segs.SegmentLocation, REVOLVED_LEG1)
            n2 = add_cut_points(part, segs.SegmentLocationForSecondLeg,
                                REVOLVED_LEG2)
            view = svb.Commit()
        finally:
            svb.Destroy()
        if not ufs.Draw.IsSxview(view.Tag):
            raise RuntimeError("committed %s is not a section view" % view.Tag)
        sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
        stype = ufs.Draw.AskSxlineType(sxline)
        if stype != ufs.Draw.SxlineType.REVOLVED_SXLINE:
            raise RuntimeError("the revolved section reports %s, not "
                               "REVOLVED_SXLINE" % sxline_type_name(ufs, stype))
        rev = ufs.Draw.AskRevolvedSxline(sxline)
        if not hasattr(rev, "__len__") or len(rev) < 8:
            raise RuntimeError("AskRevolvedSxline returned %r" % (rev,))
        n, solids = ufs.Draw.AskSxsolidsOfSxview(view.Tag,
                                                 ufs.Draw.SxlineLeg.SXLINE_LEG1)
        vis, kinds = view_kinds(state["sheet"], view)
        if n < 1 or not solids:
            raise RuntimeError("the revolved section sectioned %s solid(s)" % n)
        if kinds.get("Hatch", 0) < HATCH_MIN:
            raise RuntimeError("no Hatch in the revolved section (kinds=%s)"
                               % kinds)
        if view.IsOutOfDate:
            raise RuntimeError("revolved section %s is out of date" % view.Name)
        state["revolved_folded"] = view
        state["revolved_vis"] = len(vis)
        say("REVOLVED view=%s type=%s fields=%d leg_segs=%s sxsolids=%d leg1_len=%s"
            " leg2_len=%s vis=%d hatch=%d kinds=%s"
            % (view.Name, sxline_type_name(ufs, stype), len(rev), rev[7], n, n1,
               n2, len(vis), kinds.get("Hatch", 0),
               ",".join("%s:%d" % kv for kv in sorted(kinds.items()))))

    def s5_revolved_without_rotation_point():
        # negative control: with RotationPoint left unset the rotation point
        # defaults onto the bend point and the first cut point is refused
        part = state["part"]
        ref = state["ref"]
        svb = part.DraftingViews.CreateSectionViewBuilder(
            NXOpen.Drawings.SectionView.Null)
        try:
            svb.ParentView.View.Value = state["top"]
            svb.SectionViewType = SVB.SectionLineType.Revolved
            segs = svb.SectionLineSegments
            try:
                add_cut_points(part, segs.SegmentLocation, REVOLVED_LEG1)
                raise RuntimeError("a revolved section accepted a cut path with no "
                                   "rotation point set; the measured trap no "
                                   "longer holds")
            except RuntimeError:
                raise
            except Exception as exc:
                if "Rotation and bend points cannot be coincident" not in str(exc):
                    raise RuntimeError("unexpected failure with no rotation point: "
                                       "%s: %s" % (type(exc).__name__, exc))
                say("ROTATION_POINT_REQUIRED %s" % str(exc)[:90])
        finally:
            svb.Destroy()

    def s6_unfolded_toggle():
        part = state["part"]
        sizes = {}
        for label, unfolded, sheet_name, pdf in (
                ("folded", False, "SHT_FOLD", "sx31_folded.pdf"),
                ("unfolded", True, "SHT_UNFOLD", "sx31_unfolded.pdf")):
            sheet = part.DrawingSheets.InsertSheet(
                sheet_name, NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
                1.0, 1.0,
                NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle)
            sheet.Open()
            std = part.DraftingViews.CreateStandardViewsBuilder()
            std.Part = part
            std.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
            std.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
            std.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
            std.Autoscale = True
            std.Commit()
            std.Destroy()
            sheet.Open()
            parent = None
            for v in sheet.GetDraftingViews():
                if v.Name.startswith("Top"):
                    parent = v
            if parent is None:
                raise RuntimeError("no Top view on %s" % sheet_name)
            ref = parent.GetDrawingReferencePoint()
            svb = new_section_view(part, parent, SVB.SectionLineType.Revolved,
                                  NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP, 0.0))
            try:
                svb.ViewUnfolded = unfolded
                if bool(svb.ViewUnfolded) != bool(unfolded):
                    raise RuntimeError("ViewUnfolded did not stick: %r"
                                       % svb.ViewUnfolded)
                segs = svb.SectionLineSegments
                segs.RotationPoint = part.Points.CreatePoint(
                    NXOpen.Point3d(*ROTATION_POINT))
                add_cut_points(part, segs.SegmentLocation, REVOLVED_LEG1)
                add_cut_points(part, segs.SegmentLocationForSecondLeg, REVOLVED_LEG2)
                view = svb.Commit()
                create_folded = svb.CreateFolded
            finally:
                svb.Destroy()
            sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
            stype = ufs.Draw.AskSxlineType(sxline)
            if stype != ufs.Draw.SxlineType.REVOLVED_SXLINE:
                raise RuntimeError("the %s view reports %s, not REVOLVED_SXLINE"
                                   % (label, sxline_type_name(ufs, stype)))
            vis, kinds = view_kinds(sheet, view)
            if view.IsOutOfDate:
                raise RuntimeError("the %s view is out of date" % label)
            size = export_pdf(part, sheet, os.path.abspath(pdf))
            if size < PDF_MIN_BYTES:
                raise RuntimeError("the %s sheet exported %d bytes; a blank A4 "
                                   "sheet is 917 bytes" % (label, size))
            sizes[label] = size
            say("UNFOLDED_%s view=%s type=%s ViewUnfolded=%r CreateFolded=%r vis=%d "
                "kinds=%s pdf=%d"
                % (label.upper(), view.Name, sxline_type_name(ufs, stype),
                   unfolded, create_folded, len(vis),
                   ",".join("%s:%d" % kv for kv in sorted(kinds.items())), size))
        if sizes["folded"] == sizes["unfolded"]:
            raise RuntimeError("the folded and unfolded sheets exported the same "
                               "%d bytes: the toggle no longer changes the drawing"
                               % sizes["folded"])
        state["fold_sizes"] = sizes

    def s7_save():
        ufs.Part.Save()
        path = os.path.abspath(PART_NAME)
        if not os.path.exists(path):
            raise RuntimeError("Save() did not write " + path)
        if os.path.getsize(path) <= 0:
            raise RuntimeError("the saved part is empty")
        say("PART=%s size=%d" % (path, os.path.getsize(path)))

    stage("new_part_with_hole", s0_new_part)
    stage("section_line_enums", s1_enum_members)
    stage("half_section", s2_half_section)
    stage("half_straight_path", s3_half_straight_path_also_commits)
    stage("revolved_section", s4_revolved_section)
    stage("rotation_point_required", s5_revolved_without_rotation_point)
    stage("unfolded_toggle", s6_unfolded_toggle)
    stage("save_part", s7_save)

    if FAILED_STAGES:
        say("TEST31_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    sizes = state["fold_sizes"]
    # ⚠ AskVisibleObjects() 只对"当前显示"的视图有效；汇总行要在用例开始时读同一张图纸
    #   上有多个视图，而 s6 新建的视图已经把它顶掉，事后重读会报 The view is not displayed。
    say("TEST31_DONE half_vis=%d half_fields=%d/%d revolved_vis=%d pdf_folded=%d "
        "pdf_unfolded=%d"
        % (state["half_vis"], state["half_fields"], state["half_straight_fields"],
           state["revolved_vis"], sizes["folded"], sizes["unfolded"]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say(traceback.format_exc()[-600:])
        say("TEST31_FAIL uncaught")
