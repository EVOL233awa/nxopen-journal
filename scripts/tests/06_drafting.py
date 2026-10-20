# -*- coding: utf-8 -*-
# Test E: drafting (insert A4 sheet + standard views)
# Covers: Parts.Open + SetDisplayPart, DrawingSheetCollection.InsertSheet,
#         StandardViewsBuilder (3 views), view content
# NOTE: this case builds only the sheet and the three views. Annotations are
#   covered by 07_center_marks.py (center marks / 2D centerlines) and
#   19_drafting_annotation.py (dims / note / label / table / PDF export). Both
#   work in headless batch; the old "annotation objects are not creatable in
#   batch" note and its first replacement root cause are both retracted in
#   references/drafting.md B.2.
# FIXED: this case used StandardViewsBuilder.View.Drawing and
#   asserted only a view count, so it stayed green while creating three EMPTY
#   views (AskVisibleObjects()=0, blank plot). View.Base is the correct enum.
#   Measured on this build: Base gives 13/13/15 visible objects on the three
#   standard views, Drawing gives 0/0/0. The content assertion below is what
#   catches that; 20_drafting_views.py gates the pair apart explicitly.
import os
import sys

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

PART_PATH = os.path.abspath("bracket.prt")

# measured on bracket.prt: Front/Right 13, Top 15
VIEW_VISIBLE_MIN = 8


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part, status = session.Parts.Open(PART_PATH)
    ufs.Part.SetDisplayPart(part.Tag)
    print("OPEN_OK")

    # Precondition: a journal must never die without printing a verdict, so
    # state the requirement instead of tripping over a duplicate sheet name
    # later. Running this case twice against the same parts directory used to
    # end in an uncaught InsertSheet failure with no TEST06_* line at all.
    if len([s for s in part.DrawingSheets]) != 0:
        print("TEST06_FAIL pre_existing_sheet: this case expects a part without "
              "a drawing sheet; run 01_bracket.py on a fresh parts directory")
        return

    sheet = None

    def s0():
        # Blank every datum before any view exists: the parts carry the
        # template's datum coordinate system, and its datum axes project into
        # every drafting view as stray arrowheads (measured on the
        # plotted PDF). Blanked objects do not plot.
        n = 0
        for o in part.Datums:
            if not o.IsBlanked:
                o.Blank()
                n += 1
        print("BLANKED_DATUMS=%d" % n)
        return n
    stage("blank_datums", s0)

    def s1():
        sh = part.DrawingSheets.InsertSheet(
            "SHT1",
            NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
            1.0, 1.0,
            NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle,
        )
        sh.Open()
        print("SHEETS=" + str(len([s for s in part.DrawingSheets])))
        return sh
    stage("insert_sheet", s1)
    for sh in part.DrawingSheets:
        sheet = sh

    def s2():
        svb = part.DraftingViews.CreateStandardViewsBuilder()
        svb.Part = part
        # View.Base, not View.Drawing: Drawing produces empty 2D views
        svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
        svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
        svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
        svb.Autoscale = True
        svb.Commit()
        svb.Destroy()
        # Open() makes this sheet current; AskVisibleObjects on a view of a
        # non-current sheet raises "The view is not displayed" (measured)
        sheet.Open()
        views = list(sheet.GetDraftingViews())
        counts = []
        for v in views:
            n = len(v.AskVisibleObjects() or [])
            counts.append("%s:%d" % (v.Name, n))
            if n < VIEW_VISIBLE_MIN:
                raise RuntimeError("view %s has only %d visible objects; the "
                                   "views are empty" % (v.Name, n))
        print("VIEWS=%d VISIBLE=%s" % (len(views), ",".join(counts)))
    stage("standard_views", s2)

    # ------------------------------------------------------------- placement
    # The builder scatters the standard set on its own, which reads as a draft,
    # not a drawing.  Pin every view to sheet mm and 1:1: front above top (the
    # first-angle arrangement), side view in the free upper-right corner, so
    # 19_drafting_annotation.py can hang dimensions and the title block off
    # fixed coordinates.  The bracket is symmetric in x, so the view NX calls
    # RIGHT carries the same content a left-side view would.
    #
    # SetDrawingReferencePoint anchors the model point NX picked at creation,
    # not the view's content centre (measured from the plotted PDF:
    # each view's content landed a constant 4-5 mm off the requested point),
    # so the constants below carry that per-view offset pre-subtracted and the
    # content centres land at front (95,150), top (95,90), right (230,150).
    LAYOUT = {"FRONT": (95.0, 155.0), "TOP": (95.0, 94.0), "RIGHT": (234.0, 150.0)}

    def s3():
        sheet.Open()
        placed = []
        for v in sheet.GetDraftingViews():
            key = v.Name.split("@")[0].upper()
            if key not in LAYOUT:
                continue
            ufs.Draw.SetViewScale(v.Tag, 1.0)
            v.SetDrawingReferencePoint(NXOpen.Point3d(
                LAYOUT[key][0], LAYOUT[key][1], 0.0))
            ref = v.GetDrawingReferencePoint()
            _, sc = ufs.Draw.AskViewScale(v.Tag)
            placed.append("%s@(%.1f,%.1f)x%.2f" % (key, ref.X, ref.Y, sc))
            if abs(ref.X - LAYOUT[key][0]) > 0.01 or abs(ref.Y - LAYOUT[key][1]) > 0.01:
                raise RuntimeError("view %s ref point %.3f,%.3f did not take"
                                   % (key, ref.X, ref.Y))
        if len(placed) != 3:
            raise RuntimeError("expected to place 3 standard views, got %s"
                               % (placed,))
        print("PLACED=%s" % ",".join(placed))
    stage("place_views", s3)

    ufs.Part.Save()
    if FAILED_STAGES:
        print("TEST06_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    print("TEST06_DONE")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print(traceback.format_exc()[-600:])
        print("TEST06_FAIL uncaught")
