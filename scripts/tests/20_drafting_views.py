# -*- coding: utf-8 -*-
# Test 20: drafting view creation - standard / projected / detail views, and
# a content gate that a view-count assertion alone cannot provide.
#
# Why this case exists
#   Test 06 asserted only "VIEWS=3", which is satisfied by three EMPTY views.
#   Measured 2026-09-20 on this build: StandardViewsBuilder.View.Drawing
#   produces views whose AskVisibleObjects() is empty and whose sheet plots to
#   a blank page, while View.Base produces views with real content. Test 06
#   used View.Drawing, so the suite was green while the views were empty.
#   This case gates the two apart and covers the view types 06 cannot reach.
#
# Coverage
#   standard views with View.Base   - content asserted, not just the count
#   standard views with View.Drawing- the empty control, asserted to be empty
#   projected views (orthographic)  - ufs.Draw.AddOrthographicView
#   detail view (rectangular)       - ufs.Draw.AddDetailView
#   detail view placement rejected  - negative control: placement off the sheet
#   sheet furniture                 - inner frame + simplified title block as
#                                     tabular notes, on the base sheet only
#   PDF export compared against the empty sheet's PDF
#
# Layout: the sheet is arranged like a drawing, not like builder defaults.
# The standard set is created only to gate View.Base content; TOP and RIGHT are
# then deleted (UF_OBJ_delete_object) because the projected pair re-covers the
# same directions in first-angle positions - front above, top view below it,
# the left-looking projection right of front, the detail view in the free
# lower-right region.  The empty control sheet stays bare so the PDF byte
# comparison keeps comparing content against a true blank page.
#
# Route notes (measured, not documented anywhere in the shipped NX help)
#   * part.DraftingViews.CreateSectionViewBuilder(NXOpen.Drawings.SectionView
#     .Null) works, but ParentViewBuilder.View and ViewPlacementBuilder
#     .Placement are read-only, so the parent view and the placement cannot be
#     set from Python, and Commit fails with "Null tag not allowed".
#     CreateDetailViewBuilder has the same read-only Parent/Origin/Scale.
#   * The UF route takes parent view and drawing coordinates as plain
#     arguments, which is why it is used here:
#       %NX_HOME%\UGOPEN\uf_draw.h           exact prototypes
#       %NX_HOME%\UGOPEN\ufd_draw_circ_det_vw.c circular detail view recipe
#   * ufs.Draw exposes CreateSteppedSxview / CreateHalfSxview /
#     CreateRevolvedSxview / CreateUnfoldedSxview / CreateSxviewFromDmv. The
#     nxopen MCP index does not list them for NX12, so query the session object
#     (dir(ufs.Draw)) rather than trusting the index.
#   * The section view route is still NOT solved - see
#     references/assembly-drafting.md B.4 for the attempts and exact errors.
#
# NXOpen enums in this build:
#   ufs.Draw.ProjDir   PROJECT_INFER / PROJECT_ABOVE / PROJECT_RIGHT /
#                      PROJECT_BELOW / PROJECT_LEFT   (no short names)
#   ufs.Draw.SxsegType SXSEG_CUT / SXSEG_BEND / SXSEG_ARROW
#   NXOpen.Tag.Null is not reachable as a module attribute; use 0.
import os
import sys
import time

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
from nxlib.session import new_part
from nxlib.modeling import add_thru_hole, block
from nxlib.drafting import (
    cell_text, drain_table, export_pdf, new_table, norm_tag,
    pin_table_geometry, read_cell, view_by_prefix, view_names, visible_count,
)

PLATE = os.path.abspath("m20_plate.prt")
PDF_FULL = os.path.abspath("m20_full.pdf")
PDF_EMPTY = os.path.abspath("m20_empty.pdf")

BLOCK = (-60.0, -40.0, 0.0)
BLOCK_L = (120.0, 80.0, 12.0)
HOLE_BIG_D = 20.0
HOLE_SMALL_D = 8.0

BASE_VISIBLE_MIN = 4      # measured 5 on the side view once the datum
                          # planes/axes are blanked (13 pre-blank included 8
                          # datum-derived objects)
PROJ_VISIBLE_MIN = 4      # measured 7 on both projected views
DETAIL_VISIBLE_MIN = 3    # measured 3 on the two-hole detail (both hole
                          # circles + the third edge the window catches); the
                          # old front-view detail measured 11 but its content
                          # was nothing but two parallel plate edges
DETAIL_SCALE = 2.0
EMPTY_PDF_MAX = 1200      # an empty A4 sheet plots to 917 bytes here
FULL_PDF_MIN = 2000       # the same sheet with content plots to 2179+ bytes
DRAWING_VIEW_STATE = 2    # UF_DRAW_set_display_state: 2 = drawing view
NULL_TAG = 0

# sheet furniture (see 19_drafting_annotation.py for the same recipe): A4
# landscape, frame as a one-cell tabular note on the 25/5 margins, title block
# pinned to its bottom-right corner.  Tabular-note origins are the table's
# top-left corner (measured on the rendered sheet).
FRAME_ORIGIN = (25.0, 205.0)
TITLE_ORIGIN = (152.0, 33.0)
DWG_NO = "NXOJ-20"
PART_TITLE = u"试验板"

NOTES = []


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    for p in (PLATE, PDF_FULL, PDF_EMPTY):
        if os.path.exists(p):
            os.remove(p)

    part = new_part(name="m20_plate")
    session.Parts.SetWork(part)
    ufs.Part.SetDisplayPart(part.Tag)
    body = block(part, NXOpen.Point3d(*BLOCK), str(BLOCK_L[0]), str(BLOCK_L[1]), str(BLOCK_L[2]))
    unit = part.UnitCollection.GetBase("Length")
    part.Expressions.CreateSystemExpressionWithUnits(
        "BIG_D = %.4f" % HOLE_BIG_D, unit)
    part.Expressions.CreateSystemExpressionWithUnits(
        "SMALL_D = %.4f" % HOLE_SMALL_D, unit)
    add_thru_hole(part, body, 0.0, 0.0, BLOCK_L[2], "BIG_D")
    add_thru_hole(part, body, 30.0, 0.0, BLOCK_L[2], "SMALL_D")
    print("BODIES=%d" % len([b for b in part.Bodies]))

    def s_blank():
        # Blank the datum planes/axes before any view exists: they project
        # into every drafting view as stray arrowheads (measured 2026-09-23).
        n = 0
        for o in part.Datums:
            if not o.IsBlanked:
                o.Blank()
                n += 1
        print("BLANKED_DATUMS=%d" % n)
        return n
    stage("blank_datums", s_blank)

    sheet = None
    empty_sheet = None
    proj_names = {}

    # ------------------------------------------------ 1. View.Base content
    def s_base_views():
        sh = part.DrawingSheets.InsertSheet(
            "SHT_BASE", NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
            1.0, 1.0, NXOpen.Drawings.DrawingSheet.ProjectionAngleType
            .FirstAngle)
        sh.Open()
        svb = part.DraftingViews.CreateStandardViewsBuilder()
        svb.Part = part
        svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
        svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
        svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
        svb.Autoscale = True
        svb.Commit()
        svb.Destroy()
        sh.Open()
        views = list(sh.GetDraftingViews())
        counts = []
        for v in views:
            n, err = visible_count(v)
            counts.append((v.Name, n))
            if n < 0:
                raise RuntimeError("view %s not readable: %s" % (v.Name, err))
            if n < BASE_VISIBLE_MIN:
                raise RuntimeError("View.Base view %s has only %d visible "
                                   "objects (< %d); the views are empty"
                                   % (v.Name, n, BASE_VISIBLE_MIN))
            if v.IsOutOfDate:
                raise RuntimeError("view %s is out of date" % v.Name)
        if len(views) != 3:
            raise RuntimeError("expected 3 standard views, got %d" % len(views))
        print("BASE_COUNTS=%s" % ",".join("%s:%d" % c for c in counts))
        return sh
    sheet = stage("standard_views_base_content", s_base_views)
    if sheet is None:
        print("TEST20_FAIL stages=" + ",".join(FAILED_STAGES))
        return

    # ------------------------------------ 1b. prune the set, pin front at 1:1
    # TOP and RIGHT are deleted after the content gate: the projected pair
    # below re-covers those directions in first-angle positions, and two views
    # of the same direction on one sheet read as a mistake.  FRONT is pinned to
    # 1:1 at (90,158) so the projections hang off known coordinates (the
    # plate is 120 x 80 x 12; at 1:1 the front view is 120 x 12).
    FRONT_POS = (90.0, 158.0)

    def s_prune():
        sheet.Open()
        front = view_by_prefix(sheet, "FRONT")
        if front is None:
            raise RuntimeError("no FRONT view after the base gate")
        pruned = []
        for v in list(sheet.GetDraftingViews()):
            key = v.Name.split("@")[0].upper()
            if key in ("TOP", "RIGHT"):
                ufs.Obj.DeleteObject(v.Tag)
                pruned.append(key)
        if sorted(pruned) != ["RIGHT", "TOP"]:
            raise RuntimeError("expected to delete TOP and RIGHT, got %s"
                               % (pruned,))
        sheet.Open()
        left = [v.Name for v in sheet.GetDraftingViews()]
        if len(left) != 1 or not left[0].upper().startswith("FRONT"):
            raise RuntimeError("expected FRONT to survive the prune, got %s"
                               % (left,))
        cnt, err = visible_count(view_by_prefix(sheet, "FRONT"))
        if cnt < BASE_VISIBLE_MIN:
            raise RuntimeError("FRONT lost content after prune: %d (%s)"
                               % (cnt, err))
        ufs.Draw.SetViewScale(front.Tag, 1.0)
        front.SetDrawingReferencePoint(NXOpen.Point3d(*FRONT_POS, 0.0))
        ref = front.GetDrawingReferencePoint()
        _, sc = ufs.Draw.AskViewScale(front.Tag)
        print("PRUNED=%s FRONT@(%.1f,%.1f)x%.2f visible=%d"
              % (",".join(pruned), ref.X, ref.Y, sc, cnt))
        if abs(ref.X - FRONT_POS[0]) > 0.01 or abs(ref.Y - FRONT_POS[1]) > 0.01:
            raise RuntimeError("FRONT ref point %.3f,%.3f did not take"
                               % (ref.X, ref.Y))
    stage("prune_standard_views_pin_front", s_prune)

    # --------------------------------------- 2. View.Drawing is the control
    def s_drawing_views_empty():
        sh = part.DrawingSheets.InsertSheet(
            "SHT_EMPTY", NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
            1.0, 1.0, NXOpen.Drawings.DrawingSheet.ProjectionAngleType
            .FirstAngle)
        sh.Open()
        svb = part.DraftingViews.CreateStandardViewsBuilder()
        svb.Part = part
        svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Drawing
        svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
        svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
        svb.Autoscale = True
        svb.Commit()
        svb.Destroy()
        sh.Open()
        views = list(sh.GetDraftingViews())
        counts = []
        for v in views:
            n, err = visible_count(v)
            counts.append((v.Name, n))
            if n != 0:
                raise RuntimeError(
                    "View.Drawing view %s now carries %d visible objects; the "
                    "documented distinction from View.Base no longer holds, "
                    "see references/assembly-drafting.md B.1" % (v.Name, n))
        if len(views) != 3:
            raise RuntimeError("expected 3 views, got %d" % len(views))
        print("DRAWING_COUNTS=%s" % ",".join("%s:%d" % c for c in counts))
        return sh
    empty_sheet = stage("standard_views_drawing_is_empty", s_drawing_views_empty)

    # ------------------------------------------------- 3. projected views
    def s_projected():
        # Open() first: it is what makes this sheet the current drawing, and
        # UF_DRAW_ask_current_drawing / the UF creators both work against the
        # current drawing. Opening it after the check reported the empty
        # control sheet and this stage failed (measured).
        sheet.Open()
        ufs.Draw.SetDisplayState(DRAWING_VIEW_STATE)
        cur = ufs.Draw.AskCurrentDrawing()
        cur = cur[-1] if isinstance(cur, tuple) else cur
        if int(cur) != int(sheet.Tag):
            raise RuntimeError("current drawing %s is not the base sheet %s"
                               % (cur, sheet.Tag))
        front = view_by_prefix(sheet, "FRONT")
        if front is None:
            raise RuntimeError("no FRONT view to project from")
        ref = front.GetDrawingReferencePoint()
        before = view_names(sheet)
        made = []
        # first-angle placement: the top-direction view goes below the front
        # view, the left-looking one to its right; the offsets leave the top
        # view (120 x 80) clear of the front view (120 x 12) and put the side
        # view in the free upper-right region
        for dname, pos in (("PROJECT_BELOW", (ref.X, ref.Y - 63.0)),
                           ("PROJECT_RIGHT", (ref.X + 110.0, ref.Y))):
            r = ufs.Draw.AddOrthographicView(
                sheet.Tag, front.Tag,
                getattr(ufs.Draw.ProjDir, dname),
                [float(pos[0]), float(pos[1])])
            tag = r[-1] if isinstance(r, tuple) else r
            made.append((dname, tag))
        sheet.Open()
        # AskVisibleObjects on a freshly added projected view returns [] until
        # the view is regenerated (measured 2026-09-23: the view plots fine
        # while its visible list is still empty) - update each view first
        for _, vtag in made:
            ufs.Draw.UpdateOneView(sheet.Tag, vtag)
        sheet.Open()
        after = view_names(sheet)
        new = [n for n in after if n not in before]
        print("PROJECTED made=%s new=%s" % (made, new))
        if len(new) != 2:
            raise RuntimeError("expected 2 new projected views, got %s" % (new,))
        # creation order pairs new[0] with the first AddOrthographicView call;
        # verify the pairing by position before anyone relies on it
        proj_names["BELOW"] = new[0]
        proj_names["RIGHT"] = new[1]
        below_v = [v for v in sheet.GetDraftingViews()
                   if v.Name == proj_names["BELOW"]][0]
        right_v = [v for v in sheet.GetDraftingViews()
                   if v.Name == proj_names["RIGHT"]][0]
        rb = below_v.GetDrawingReferencePoint()
        rr = right_v.GetDrawingReferencePoint()
        if not (rb.Y < ref.Y - 40.0 and rr.X > ref.X + 40.0):
            raise RuntimeError(
                "projected name pairing wrong: below@(%.1f,%.1f) "
                "right@(%.1f,%.1f) front@(%.1f,%.1f)"
                % (rb.X, rb.Y, rr.X, rr.Y, ref.X, ref.Y))
        for n in new:
            v = view_by_prefix(sheet, n.split("@")[0])
            cnt, err = visible_count(v)
            if cnt < PROJ_VISIBLE_MIN:
                raise RuntimeError("projected view %s has %d visible objects "
                                   "(< %d) %s" % (n, cnt, PROJ_VISIBLE_MIN, err))
        print("PROJECTED_COUNTS=%s"
              % ",".join("%s:%d" % (n, visible_count(
                  view_by_prefix(sheet, n.split("@")[0]))[0]) for n in new))
    stage("projected_views", s_projected)

    # ---------------------------------------------------- 4. detail view
    def s_detail():
        sheet.Open()
        # anchor on the projected face view: it carries the two holes, so the
        # detail shows the hole pattern (the front view is a 12 mm edge whose
        # magnification is just two parallel lines)
        below = [v for v in sheet.GetDraftingViews()
                 if v.Name == proj_names["BELOW"]][0]
        front = view_by_prefix(sheet, "FRONT")
        fref = front.GetDrawingReferencePoint()
        bref = below.GetDrawingReferencePoint()
        before = view_names(sheet)
        # the face view's anchor is the model origin = the BIG hole; wrap both
        # holes (SMALL at +30 in x, measured on the plotted sheet).  NX draws
        # the boundary circle at ~0.83x the selection rectangle's
        # half-diagonal (measured 2026-09-23 on two rects: 5-6 mm inside), so
        # the rectangle needs the extra margin or the circle clips the BIG
        # hole's rim.
        r = ufs.Draw.AddDetailView(
            sheet.Tag, below.Tag,
            [bref.X - 15.0, bref.Y - 14.0], [bref.X + 45.0, bref.Y + 14.0],
            DETAIL_SCALE, [fref.X + 125.0, fref.Y - 68.0])
        tag = r[-1] if isinstance(r, tuple) else r
        sheet.Open()
        ufs.Draw.UpdateOneView(sheet.Tag, tag)
        sheet.Open()
        new = [n for n in view_names(sheet) if n not in before]
        if len(new) != 1:
            raise RuntimeError("expected 1 detail view, got %s" % (new,))
        v = view_by_prefix(sheet, "DETAIL")
        cnt, err = visible_count(v)
        _, psc = ufs.Draw.AskViewScale(below.Tag)
        _, dsc = ufs.Draw.AskViewScale(v.Tag)
        print("DETAIL tag=%s name=%s scale_prop=%.4f scale_uf=%.4f "
              "parent_uf=%.4f visible=%d"
              % (tag, v.Name, v.Scale, dsc, psc, cnt))
        if cnt < DETAIL_VISIBLE_MIN:
            raise RuntimeError("detail view has %d visible objects (< %d) %s"
                               % (cnt, DETAIL_VISIBLE_MIN, err))
        # the detail scale multiplies the parent scale (UF values, which are
        # what actually plots; the .NET Scale property tracks the creation
        # autoscale chain and reported 2.36 = 2.0 x 1.18 in earlier runs)
        if abs(dsc - DETAIL_SCALE * psc) > 0.01:
            raise RuntimeError("detail view scale %.4f != %.4f x parent %.4f"
                               % (dsc, DETAIL_SCALE, psc))
        if not v.IsOutOfDate:
            print("DETAIL_FRESH ok")
        return v
    stage("detail_view", s_detail)

    # ----------------------------- 5. negative control: placement off sheet
    def s_detail_off_sheet():
        sheet.Open()
        below = [v for v in sheet.GetDraftingViews()
                 if v.Name == proj_names["BELOW"]][0]
        front = view_by_prefix(sheet, "FRONT")
        fref = front.GetDrawingReferencePoint()
        bref = below.GetDrawingReferencePoint()
        before = view_names(sheet)
        off_y = sheet.Height + 40.0          # A4 is 297 x 210; 250 is off sheet
        try:
            ufs.Draw.AddDetailView(
                sheet.Tag, below.Tag,
                [bref.X - 15.0, bref.Y - 14.0], [bref.X + 45.0, bref.Y + 14.0],
                DETAIL_SCALE, [fref.X, off_y])
        except Exception as exc:
            print("DETAIL_OFF_SHEET_REJECTED y=%.1f :: %s"
                  % (off_y, str(exc)[:90]))
            sheet.Open()
            if view_names(sheet) != before:
                raise RuntimeError("a view appeared even though the placement "
                                   "was rejected")
            return True
        raise RuntimeError("AddDetailView accepted placement y=%.1f, which is "
                           "outside the %.1f tall sheet" % (off_y, sheet.Height))
    stage("detail_placement_off_sheet_rejected", s_detail_off_sheet)

    # ------------------------------------------------ 5b. sheet furniture
    # Frame + title block on the base sheet only; the empty control sheet must
    # stay bare for the PDF byte comparison below.
    def s_furniture():
        sheet.Open()
        dp = ufs.Tabnot.AskDefaultCellPrefs()
        dp.TextHeight = 2.5
        ufs.Tabnot.SetDefaultCellPrefs(dp)

        frame = new_table(FRAME_ORIGIN, [267.0], [200.0], thick_border=True)
        pin_table_geometry(frame, [200.0])
        ufs.Tabnot.Update(frame)
        print("FRAME_OK tag=%s" % frame)

        tn = new_table(TITLE_ORIGIN, [12.0, 32.0, 12.0, 38.0, 12.0, 34.0],
                       [12.0, 8.0, 8.0], thick_border=True)
        ufs.Tabnot.MergeCells(cell_text(tn, 0, 0), cell_text(tn, 0, 5))
        want = [
            [PART_TITLE, "", "", "", "", ""],
            [u"设计", "NX 12 journal", u"校核", "check_journal.py", u"日期",
             time.strftime("%Y-%m-%d")],
            [u"图号", DWG_NO, u"比例", "1:1", u"数量", "1"],
        ]
        for ri, vals in enumerate(want):
            for ci, val in enumerate(vals):
                if val:
                    ufs.Tabnot.SetCellText(cell_text(tn, ri, ci), val)
        pin_table_geometry(tn, [12.0, 8.0, 8.0], ncols=6, center_first_row=True)
        ufs.Tabnot.Update(tn)
        print("TITLE_OK tag=%s dwg=%s" % (tn, DWG_NO))
        for ri, ci, val in ((1, 1, "NX 12 journal"), (2, 1, DWG_NO),
                            (1, 3, "check_journal.py")):
            got = read_cell(tn, ri, ci)
            print("TITLE_CELL r%d c%d want=%s got=%s" % (ri, ci, val, got))
            if str(got) != val:
                raise RuntimeError("title block r%d c%d read-back %r != %r"
                                   % (ri, ci, got, val))
    stage("sheet_furniture", s_furniture)

    # ------------------------------------------ 6. PDF content comparison
    def s_pdf():
        if empty_sheet is None:
            raise RuntimeError("the empty control sheet was not created")
        empty_sheet.Open()
        esize = export_pdf(part, empty_sheet, PDF_EMPTY)
        sheet.Open()
        fsize = export_pdf(part, sheet, PDF_FULL)
        print("PDF_EMPTY=%d PDF_FULL=%d" % (esize, fsize))
        if esize < 0 or fsize < 0:
            raise RuntimeError("plot failed (empty=%d full=%d)" % (esize, fsize))
        # the empty sheet is the calibration: an A4 sheet with three empty
        # views plots to ~917 bytes here, so a byte count at or below that is
        # a blank page, whatever the view count says
        if esize > EMPTY_PDF_MAX:
            raise RuntimeError("the empty control sheet plotted to %d bytes, "
                               "expected a blank page below %d"
                               % (esize, EMPTY_PDF_MAX))
        if fsize < FULL_PDF_MIN or fsize <= esize:
            raise RuntimeError("the content sheet plotted to %d bytes, not "
                               "above the blank page's %d" % (fsize, esize))
    stage("pdf_content_vs_blank_sheet", s_pdf)

    # ------------------------------------------------------------ 7. save
    def s_save():
        ufs.Part.Save()
        if not os.path.exists(PLATE) or os.path.getsize(PLATE) < 10000:
            raise RuntimeError("plate part was not written to disk")
        print("PART=%s size=%d" % (PLATE, os.path.getsize(PLATE)))
    stage("save_part", s_save)

    if FAILED_STAGES:
        print("TEST20_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    print("VIEWS=%d" % len([v for v in sheet.GetDraftingViews()]))
    print("TEST20_DONE base_min=%d drawing_empty=1 projected=2 detail=%d scale=%.2f"
          % (BASE_VISIBLE_MIN, 1, DETAIL_SCALE))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print(traceback.format_exc()[-600:])
        print("TEST20_FAIL uncaught")
