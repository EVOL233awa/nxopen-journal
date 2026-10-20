# -*- coding: utf-8 -*-
# Test 21: section view - the last drafting view type that 20_drafting_views.py
# does not reach.
#
# Recipe (measured, NX 12.0.0.27, headless batch):
#   svb = part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView.Null)
#   svb.ParentView.View.Value = <parent drafting view>      <-- the missing link
#   loc = svb.SectionLineSegments.SegmentLocation
#   loc.AddCutSegment(pA); loc.AddCutSegment(pB)   # NXOpen.Point objects whose
#                                                  # coordinates are MODEL space and
#                                                  # must fall inside the parent view
#   svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = Point3d(x, y, 0.0)
#   svb.ViewPlacement.Placement.Value = <point at the sheet location>
#   svb.Commit() -> NXOpen.Drawings.SectionView
#
# Why ParentView.View.Value and not ParentView.View = <view>:
#   ParentViewBuilder.View is read-only ("attribute 'View' ... is not writable"), but
#   the object it returns is an NXOpen.SelectObject, and SelectObject.Value is
#   documented as "Returns or sets the object being selected". Assigning the view to
#   that works and reading it back returns the view (measured type: BaseView).
#   Without it AddCutSegment raises "Invalid parent view for section line." - that
#   message is the negative control asserted in stage 2.
#
# Evidence that the result is a real section view rather than a projected one:
#   ufs.Draw.IsSxview(tag) is True
#   ufs.Draw.AskSxlineOfSxview(tag) returns a section line tag
#   ufs.Draw.AskSxsolidsOfSxview(tag, SXLINE_LEG1) reports >= 1 sectioned solid
#   the view's visible objects include a Hatch (crosshatch) object
#   AskVisibleObjects() >= 4 and IsOutOfDate is False
# Measured on a 120x80x12 plate with a D20 through hole: Hatch 1, DraftingCurve 8,
# 18 visible objects, Scale 1.1800 = the parent view's autoscale. The same recipe
# without a hole gave 16 visible objects (DraftingCurve 6) and still one Hatch --
# a plain solid still crosshatches, so the Hatch check alone does not prove the
# hole was cut; the DraftingCurve count is what moves (6 -> 8).
#
# Stepped section (measured on the same part, same sheet):
#   the section TYPE is a builder property, and the cut path is what makes it a
#   step:
#     svb.SectionViewType = SectionViewBuilder.SectionLineType.SimpleStepped
#       ^^ the property is SectionViewType. SectionViewBuilder.SectionLineType is
#          the enum itself (its members are reachable), and assigning to the
#          property name answers "attribute 'SectionLineType' is read-only"
#     svb.ParentView.View.Value = <the TOP view>   the cut path has to lie in the
#       parent's projection plane: a Z-shaped path in XY is refused on the Front
#       view with "Invalid point for section line" (measured), because a front
#       section line lies in XZ at a single Y
#     loc.AddCutSegment(p) x4                      the Z path, at mid-height
#   The type LABEL does not identify a stepped line: AskSxlineType returns
#   STEPPED_SXLINE (value 2) for the ordinary two-point section of stage 3 as
#   well. What actually differs in the data is the leg count from
#   AskSteppedSxline, whose 6th field is the number of leg segments and the 7th
#   the segment tags: 9 for the Z path against 5 for the straight one on this part
#   (measured), which is the check stage 5 asserts. SectionViewType.PointToPoint
#   with a two-point path is a different line again: FOLDED_SXLINE (value 7),
#   where AskFoldedSxline answers and AskSteppedSxline refuses.
#   SectionViewBuilder.SectionLineType is [Half, PointAndAngle, PointToPoint,
#   Revolved, SimpleStepped]. The UF entry point ufs.Draw.CreateSteppedSxview
#   exists and its docstring names UF_DRAW_create_stepped_sxview, with the
#   signature (dwgTag, sxviewScale, stepDir, arrowDir, pviewTag, numSxsegs,
#   steppedSxsegs, viewPlacementPt) - the steppedSxsegs argument is a UF_DRF_object
#   array, the same dead end as the other UF section routes recorded above.
#
# Dead ends recorded so they are not retried (see references/drafting.md
# B.4): cut points given in SHEET coordinates commit but leave the view out of date
# and empty; SectionViewMode.StandAlone dies with "Internal error: memory access
# violation"; the UF route (CreateSimpleSxview / CreateSxviewFromDmv) needs a
# UF_DRF_object cut object whose drawing position lies on the drawing, and the only
# shipped samples COPY one out of an existing section line.
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

from nxlib.testing import FAILED_STAGES, stage
from nxlib.modeling import find_planar_face
from nxlib.drafting import sxline_legs

# measured on this part: Right 13, Front 13, Top 14 visible objects
PARENT_VISIBLE_MIN = 10
# a strictly positive content check: 18 measured with the hole, 16 without it
SECTION_VISIBLE_MIN = 4
HATCH_MIN = 1
# the plate is 120 long with a D20 hole at x=60, so +/-30 spans the hole
HOLE_CENTRE_X = 60.0
CUT_HALF_SPAN = 30.0
CUT_Z = 6.0                 # mid-height: the cutting plane halves the through hole
PLACE_DROP = 70.0           # place the section view 70 mm below the parent view
PLACE_DROP_STEPPED = 140.0  # and the stepped one another 70 mm below that
PLACE_DROP_FOLDED = 210.0
# the stepped cut path: leg 1 runs along y=40 straight through the hole, steps at
# x=80 up to y=60, leg 2 carries on to x=110. All four points are inside the
# 120x80 plate, and every leg stays at mid-height.
STEP_PATH = ((20.0, 40.0), (80.0, 40.0), (80.0, 60.0), (110.0, 60.0))
POINT_TO_POINT_PATH = ((20.0, 30.0), (110.0, 30.0))
# measured SectionViewBuilder.SectionLineType members
SECTION_LINE_TYPES = ["Half", "PointAndAngle", "PointToPoint", "Revolved",
                      "SimpleStepped"]
# the hole's diameter must exist as a part expression BEFORE the hole feature is
# built: SetSimpleHole takes an expression NAME, so committing without it fails
# with "The specified expression variable does not exist" (measured)
HOLE_DIA = 20.0
PART_NAME = "sx21_plate.prt"


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    state = {}

    def s0_new_part():
        # FileNew refuses an existing name, so a rerun against a dirty parts
        # directory would fail for a reason that has nothing to do with section
        # views (the same class of trap that made 06 report a false green).
        target = os.path.abspath(PART_NAME)
        if os.path.exists(target):
            os.remove(target)
            print("REMOVED_STALE %s" % target)
        file_new = session.Parts.FileNew()
        file_new.Units = NXOpen.Part.Units.Millimeters
        file_new.TemplateFileName = "model-plain-1-mm-template.prt"
        file_new.NewFileName = PART_NAME
        file_new.UseBlankTemplate = False
        part = file_new.Commit()
        file_new.Destroy()
        # mirrored from 20_drafting_views.py: the work part and the display part are
        # set right after FileNew, before any feature is built
        session.Parts.SetWork(part)
        ufs.Part.SetDisplayPart(part.Tag)

        blk = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "120", "80", "12")
        blk.CommitFeature()
        blk.Destroy()

        body = None
        for b in part.Bodies:
            body = b
        if body is None:
            raise RuntimeError("no body after the block feature")
        top = find_planar_face(body, NXOpen.Point3d(HOLE_CENTRE_X, 40.0, 12.0), 1.0)
        bottom = find_planar_face(body, NXOpen.Point3d(HOLE_CENTRE_X, 40.0, 0.0), -1.0)
        if top is None or bottom is None:
            raise RuntimeError("through-hole faces not found")
        hole = part.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
        hole.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
        # SetSimpleHole takes an expression NAME, not a value, so the expression has
        # to exist first: creating the feature without it fails with "The specified
        # expression variable does not exist" (measured)
        part.Expressions.CreateSystemExpressionWithUnits(
            "HOLE_D = %.4f" % HOLE_DIA, part.UnitCollection.GetBase("Length"))
        hole.SetSimpleHole(NXOpen.Point3d(HOLE_CENTRE_X, 40.0, 12.0), False, top, "HOLE_D")
        hole.SetThruFace(bottom)
        hole.HoleLocation = NXOpen.Point3d(HOLE_CENTRE_X, 40.0, 12.0)
        hole.CommitFeature()
        hole.Destroy()
        # proving the hole was really cut matters: a plain solid crosshatches too, so
        # the Hatch check in stage 3 cannot tell a cut hole from an uncut one
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
        front = None
        top = None
        for v in list(sheet.GetDraftingViews()):
            n = len(v.AskVisibleObjects() or [])
            counts.append("%s:%d" % (v.Name, n))
            if n < PARENT_VISIBLE_MIN:
                raise RuntimeError("parent view %s has only %d visible objects"
                                   % (v.Name, n))
            if v.Name.startswith("Front"):
                front = v
            if v.Name.startswith("Top"):
                top = v
        if front is None:
            raise RuntimeError("Front view not found")
        if top is None:
            raise RuntimeError("Top view not found")
        state["part"] = part
        state["sheet"] = sheet
        state["front"] = front
        state["top"] = top
        state["ref"] = front.GetDrawingReferencePoint()
        print("PARENT_VISIBLE=%s cylinders=%d ref=(%.3f,%.3f) scale=%.4f"
              % (",".join(counts), cyl, state["ref"].X, state["ref"].Y, front.Scale))

    # Without the parent view the builder refuses the first cut point. Asserting
    # this keeps a future NX build that changes the rule from silently changing what
    # "create a section view" requires.
    def s1_negative_control():
        if "part" not in state:
            raise RuntimeError("new_part_with_hole did not finish, nothing to "
                               "exercise here")
        svb = state["part"].DraftingViews.CreateSectionViewBuilder(
            NXOpen.Drawings.SectionView.Null)
        try:
            loc = svb.SectionLineSegments.SegmentLocation
            pt = state["part"].Points.CreatePoint(
                NXOpen.Point3d(HOLE_CENTRE_X - CUT_HALF_SPAN, 40.0, CUT_Z))
            try:
                loc.AddCutSegment(pt)
            except Exception as exc:
                msg = str(exc)
                if "Invalid parent view" not in msg:
                    raise RuntimeError("unexpected failure with no parent view: "
                                       + msg)
                print("NEGATIVE_CONTROL_OK %s" % msg)
            else:
                raise RuntimeError(
                    "AddCutSegment accepted a cut point with no parent view set; the "
                    "documented requirement to set ParentView.View.Value first no "
                    "longer holds")
        finally:
            svb.Destroy()

    def s2_section_view():
        if "part" not in state:
            raise RuntimeError("new_part_with_hole did not finish; there is no "
                               "parent view to section")
        part = state["part"]
        ref = state["ref"]
        svb = part.DraftingViews.CreateSectionViewBuilder(
            NXOpen.Drawings.SectionView.Null)
        # The object returned by ParentView.View is a SelectObject; its Value is the
        # one writable slot for the parent view on this build.
        svb.ParentView.View.Value = state["front"]
        if svb.ParentView.View.Value is None:
            raise RuntimeError("the parent view assignment did not stick")

        loc = svb.SectionLineSegments.SegmentLocation
        for x in (HOLE_CENTRE_X - CUT_HALF_SPAN, HOLE_CENTRE_X + CUT_HALF_SPAN):
            loc.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(x, 40.0, CUT_Z)))
        npts = loc.Length
        if npts < 2:
            raise RuntimeError("the cut point list holds %s entries; both cut points "
                               "should have been accepted" % npts)

        svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = \
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP, 0.0)
        svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP, 0.0))
        view = svb.Commit()
        svb.Destroy()

        if not ufs.Draw.IsSxview(view.Tag):
            raise RuntimeError("committed object %s is not a section view" % view.Tag)
        sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
        if not sxline:
            raise RuntimeError("the section view has no section line attached")
        n, solids = ufs.Draw.AskSxsolidsOfSxview(view.Tag,
                                                 ufs.Draw.SxlineLeg.SXLINE_LEG1)
        if n < 1 or not solids:
            raise RuntimeError("the section view sectioned %s solid(s)" % n)

        state["sheet"].Open()
        vis = list(view.AskVisibleObjects() or [])
        kinds = {}
        for o in vis:
            k = type(o).__name__
            kinds[k] = kinds.get(k, 0) + 1
        if len(vis) < SECTION_VISIBLE_MIN:
            raise RuntimeError("section view %s has only %d visible objects"
                               % (view.Name, len(vis)))
        if kinds.get("Hatch", 0) < HATCH_MIN:
            raise RuntimeError("no Hatch object in the section view (kinds=%s); "
                               "without crosshatch this is not sectioned" % kinds)
        if view.IsOutOfDate:
            raise RuntimeError("section view %s is out of date" % view.Name)
        state["view"] = view
        state["kinds"] = kinds
        # what the plain section line calls itself, and how many legs it has: the
        # label turns out not to discriminate (see the stage 5 note), the leg count
        # does, so both are recorded here as the baseline.
        ST = ufs.Draw.SxlineType
        stype = ufs.Draw.AskSxlineType(sxline)
        legs = sxline_legs(ufs, sxline)
        state["simple_type"] = stype
        state["simple_legs"] = legs
        print("SECTION view=%s sxline=%s sxsolids=%d vis=%d hatch=%d kinds=%s "
              "| sxline_type=%s isStepped=%s isSimple=%s isFolded=%s legs=%d"
              % (view.Name, sxline, n, len(vis), kinds.get("Hatch", 0),
                 ",".join("%s:%d" % kv for kv in sorted(kinds.items())),
                 stype, stype == ST.STEPPED_SXLINE, stype == ST.SIMPLE_SXLINE,
                 stype == ST.FOLDED_SXLINE, legs))

    def s3_stepped_section():
        if "part" not in state:
            raise RuntimeError("new_part_with_hole did not finish; there is no "
                               "parent view to section")
        part = state["part"]
        ref = state["ref"]
        svb = part.DraftingViews.CreateSectionViewBuilder(
            NXOpen.Drawings.SectionView.Null)
        # the cut path lives in the projection plane of the parent view, so the
        # step is built on the TOP view: a Z-shaped path in XY at mid-height. The
        # same path on the Front view is refused with "Invalid point for section
        # line" (measured), because a front section line lies in XZ at one Y.
        svb.ParentView.View.Value = state["top"]
        # the property is SectionViewType; the class attribute of the same shape,
        # SectionViewBuilder.SectionLineType, is the enum itself, and assigning to
        # it answers "attribute 'SectionLineType' is read-only"
        SVB = NXOpen.Drawings.SectionViewBuilder
        svb.SectionViewType = SVB.SectionLineType.SimpleStepped
        if svb.SectionViewType != SVB.SectionLineType.SimpleStepped:
            raise RuntimeError("SectionViewType did not stick: %r"
                               % svb.SectionViewType)
        loc = svb.SectionLineSegments.SegmentLocation
        for x, y in STEP_PATH:
            loc.AddCutSegment(part.Points.CreatePoint(
                NXOpen.Point3d(x, y, CUT_Z)))
        svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = \
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP_STEPPED, 0.0)
        svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP_STEPPED, 0.0))
        view = svb.Commit()
        svb.Destroy()

        if not ufs.Draw.IsSxview(view.Tag):
            raise RuntimeError("committed object %s is not a section view"
                               % view.Tag)
        sxline = ufs.Draw.AskSxlineOfSxview(view.Tag)
        if not sxline:
            raise RuntimeError("the stepped view has no section line attached")
        stype = ufs.Draw.AskSxlineType(sxline)
        if stype != ufs.Draw.SxlineType.STEPPED_SXLINE:
            raise RuntimeError("the section line reports type %r, not "
                               "STEPPED_SXLINE" % stype)
        # the label alone is not proof (the plain section matches it), so the leg
        # count is read here and asserted against the plain one in stage 5
        legs = sxline_legs(ufs, sxline)
        try:
            ufs.Draw.AskSimpleSxline(sxline)
            raise RuntimeError("AskSimpleSxline accepted a stepped line; the "
                               "type check that makes these calls unambiguous is "
                               "gone")
        except RuntimeError:
            raise
        except Exception as exc:
            if "not correct type" not in str(exc):
                raise RuntimeError("AskSimpleSxline failed with %s, not the "
                                   "type check: %s" % (type(exc).__name__, exc))

        state["sheet"].Open()
        vis = list(view.AskVisibleObjects() or [])
        kinds = {}
        for o in vis:
            k = type(o).__name__
            kinds[k] = kinds.get(k, 0) + 1
        if len(vis) < SECTION_VISIBLE_MIN:
            raise RuntimeError("stepped view %s has only %d visible objects"
                               % (view.Name, len(vis)))
        if kinds.get("Hatch", 0) < HATCH_MIN:
            raise RuntimeError("no Hatch object in the stepped view (kinds=%s)"
                               % kinds)
        if view.IsOutOfDate:
            raise RuntimeError("stepped view %s is out of date" % view.Name)
        state["stepped"] = view
        state["stepped_legs"] = legs
        print("STEPPED view=%s sxline=%s type=%s legs=%d vis=%d hatch=%d "
              "kinds=%s"
              % (view.Name, sxline, stype, legs, len(vis),
                 kinds.get("Hatch", 0),
                 ",".join("%s:%d" % kv for kv in sorted(kinds.items()))))

    def s4_stepped_entrypoints():
        if "part" not in state:
            raise RuntimeError("new_part_with_hole did not finish")
        cls = NXOpen.Drawings.SectionViewBuilder.SectionLineType
        got = sorted(n for n in dir(cls) if not n.startswith("_")
                     and n != "ValueOf")
        if got != sorted(SECTION_LINE_TYPES):
            raise RuntimeError("SectionLineType members are %s, expected %s"
                               % (got, sorted(SECTION_LINE_TYPES)))
        if not hasattr(ufs.Draw, "CreateSteppedSxview"):
            raise RuntimeError("ufs.Draw.CreateSteppedSxview is missing on this "
                               "build")
        doc = ufs.Draw.CreateSteppedSxview.__doc__ or ""
        if "create_stepped_sxview" not in doc:
            raise RuntimeError("ufs.Draw.CreateSteppedSxview exists but its "
                               "docstring does not name "
                               "UF_DRAW_create_stepped_sxview: %r" % doc[:120])

        # PointToPoint is the neighbouring member, and it does NOT give a simple
        # section: a two-point path labelled PointToPoint commits as a folded line.
        # Asserting the exact type keeps the trap documented.
        part = state["part"]
        ref = state["ref"]
        svb = part.DraftingViews.CreateSectionViewBuilder(
            NXOpen.Drawings.SectionView.Null)
        svb.ParentView.View.Value = state["front"]
        svb.SectionViewType = cls.PointToPoint
        loc = svb.SectionLineSegments.SegmentLocation
        for x, y in POINT_TO_POINT_PATH:
            loc.AddCutSegment(part.Points.CreatePoint(
                NXOpen.Point3d(x, y, CUT_Z)))
        svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = \
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP_FOLDED, 0.0)
        svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(
            NXOpen.Point3d(ref.X, ref.Y - PLACE_DROP_FOLDED, 0.0))
        folded = svb.Commit()
        svb.Destroy()
        fline = ufs.Draw.AskSxlineOfSxview(folded.Tag)
        ftype = ufs.Draw.AskSxlineType(fline)
        if ftype != ufs.Draw.SxlineType.FOLDED_SXLINE:
            raise RuntimeError("SectionViewType.PointToPoint on a two-point cut "
                               "path committed a %r section line, not "
                               "FOLDED_SXLINE" % ftype)
        fdata = ufs.Draw.AskFoldedSxline(fline)
        if not fdata and fdata != 0:
            raise RuntimeError("AskFoldedSxline returned %r for a line that "
                               "reports itself as folded" % (fdata,))
        try:
            ufs.Draw.AskSteppedSxline(fline)
            raise RuntimeError("AskSteppedSxline accepted a folded line")
        except RuntimeError:
            raise
        except Exception as exc:
            if "not correct type" not in str(exc):
                raise RuntimeError("AskSteppedSxline failed with %s, not the "
                                   "type check: %s" % (type(exc).__name__, exc))
        # negative control for the type gate above: the two section lines built in
        # this run must not report the same type, otherwise SxlineType is not
        # telling stepped from folded at all. (The plain section of stage 3 reports
        # STEPPED_SXLINE as well, which is why the leg count below is the check
        # that actually carries weight.)
        simple_type = ufs.Draw.AskSxlineType(
            ufs.Draw.AskSxlineOfSxview(state["view"].Tag))
        stepped_type = ufs.Draw.SxlineType.STEPPED_SXLINE
        if ftype == stepped_type:
            raise RuntimeError("the folded line and the stepped line both report "
                               "%s, so that check proves nothing" % ftype)
        if state["stepped_legs"] <= state["simple_legs"]:
            raise RuntimeError("the Z-shaped cut path gave %d leg segment(s) and "
                               "the straight two-point path gave %d, so the step "
                               "did not reach the section line"
                               % (state["stepped_legs"], state["simple_legs"]))
        print("POINT_TO_POINT view=%s type=%s folded_len=%s | stepped view type=%s"
              " legs=%d | plain section type=%s legs=%d (the label does not "
              "separate them; the leg count does)"
              % (folded.Name, ftype, len(fdata) if hasattr(fdata, "__len__")
                 else "?", stepped_type, state["stepped_legs"], simple_type,
                 state["simple_legs"]))

    def s5_save():
        ufs.Part.Save()
        path = os.path.abspath(PART_NAME)
        if not os.path.exists(path):
            raise RuntimeError("Save() did not write " + path)
        size = os.path.getsize(path)
        if size <= 0:
            raise RuntimeError("the saved part is empty")
        print("PART=%s size=%d" % (path, size))

    stage("new_part_with_hole", s0_new_part)
    stage("no_parent_view_refused", s1_negative_control)
    stage("section_view", s2_section_view)
    stage("stepped_section", s3_stepped_section)
    stage("stepped_entrypoints", s4_stepped_entrypoints)
    stage("save_part", s5_save)

    if FAILED_STAGES:
        print("TEST21_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    view = state["view"]
    print("TEST21_DONE hatch=%d vis=%d scale=%.2f stepped_vis=%d"
          % (state["kinds"].get("Hatch", 0), len(view.AskVisibleObjects() or []),
             view.Scale, len(state["stepped"].AskVisibleObjects() or [])))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc()[-600:])
        print("TEST21_FAIL uncaught")
