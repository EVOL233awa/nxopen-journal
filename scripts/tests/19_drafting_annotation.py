# -*- coding: utf-8 -*-
# Test 19: drafting annotation chain (requires bracket.prt WITH a sheet and
# three views, i.e. run 01_bracket.py then 06_drafting.py first).
#
# Covers, all in headless batch (run_journal.exe):
#   sheet.Open() precondition (references/assembly-drafting.md B.2)
#   global lettering / line+arrow preferences and their inheritance by new dims
#   UF DRF associative dimensions: hdim + vdim on hole-circle edges (ARC_CENTER)
#   .NET center mark + 2D centerline (ByPoints)
#   note (技术要求) and leader label
#   UFTabnot table: default row/column removal, cell text write + read-back
#   sheet furniture: inner frame + simplified title block, both built from
#     tabular notes so they plot with the sheet
#   PDF plot export
#
# Value gate: the two hole-pitch dimensions must render the real model values
# (70 / 40). ARC_CENTER on a circle resolves to the arc centre regardless of
# how the edge was picked, so a wrong association shows up as a bogus distance.
# The text-layer value check needs a PDF reader and lives in verify_anno_pdf.py
# (see tests/README.md), because NX's embedded Python 3.6 has no such module.
import os
import sys
import time

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

from nxlib.drafting import norm_tag
from nxlib.testing import FAILED_STAGES, stage

PART = os.path.abspath("bracket.prt")
PDF = os.path.abspath("anno19.pdf")

HOLE_R = 4.0
# Independent expectations, taken from 01_bracket.py (not from the geometry
# read back below): the 2x2 Ø8 hole pattern uses a 70 x 40 pitch, and these are
# the values the two hole-to-hole dimensions must render.
PITCH_X = 70.0
PITCH_Y = 40.0
DIM_TEXT_SIZE = 4.0     # dimension digits: deliberately NOT the template default
                        # (3.5), otherwise the inheritance audit below would pass
                        # even if the global preferences were never applied
TEXT_SIZE = 3.5         # note / label / table text (note default is ~6.5)
TOL_TEXT_SIZE = 2.5
ARROW_LEN = 4.0

# Sheet furniture and annotation placement, in sheet mm on the A4 landscape
# sheet (297 x 210) that 06 creates.  Views are pinned by 06 to front (95,150),
# top (95,90), right (230,150); the top view is a 100 x 60 plate at 1:1, so the
# dimension lanes hang off its reference point and stay outside the view
# outline.  Everything sheet-bound (frame, title block, note, BOM table) sits
# in the region right of x=152 that the views do not occupy.
#
# Tabular-note origins are the table's top-left corner, and note origins are
# the text block's top-left (both measured on the rendered sheet, see the
# figure these produce).  NX's own PDF text layer has no CJK mapping, which is
# why the title-block values that matter are ASCII.
FRAME_ORIGIN = (25.0, 205.0)     # one 267 x 200 cell, GB 25/5 margins
TITLE_ORIGIN = (152.0, 33.0)     # 140 x 28, flush with the frame corner
BOM_ORIGIN = (232.0, 49.0)       # directly above the title block, right-aligned
NOTE_ORIGIN = (180.0, 46.0)      # 技术要求, below the top view's right corner
DWG_NO = "NXOJ-19"
PART_NAME = u"基座"

NOTES = []


def main():
    s = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    part, load_status = s.Parts.Open(PART)
    ufs.Part.SetDisplayPart(part.Tag)
    print("OPEN_OK loadStatus=%s" % str(load_status))
    body = [b for b in part.Bodies][0]

    sheets = [sh for sh in part.DrawingSheets]
    if not sheets:
        print("TEST19_FAIL no_sheet: run 01 then 06 first")
        return
    sheet = sheets[0]
    print("SHEET=%s %.1fx%.1f" % (sheet.Name, sheet.Length, sheet.Height))

    # ---------------------------------------------------------------- context
    # Open() makes the sheet current and is harmless, but it is NOT a
    # precondition: measured 2026-09-20, every creator below also succeeds
    # without it, on both a sheet saved as current and a sheet inserted in this
    # session (references/assembly-drafting.md B.2). The old "1175307 because
    # the sheet was never opened" story was a mis-attribution; the real trigger
    # is a center-mark builder carrying 3 or more locations, see 07.
    stage("sheet_open", lambda: sheet.Open())

    views = {}
    for v in sheet.GetDraftingViews():
        views[v.Name.split("@")[0].upper()] = v
    print("VIEWS=" + ",".join(sorted(views)))
    if "TOP" not in views:
        print("TEST19_FAIL no_top_view")
        return
    vtop = views["TOP"]

    def set_scale_one():
        ufs.Draw.SetViewScale(vtop.Tag, 1.0)
        _, got = ufs.Draw.AskViewScale(vtop.Tag)
        print("TOP_SCALE=%.6f" % got)
    stage("view_scale_1_1", set_scale_one)

    # ------------------------------------------------------- edge resolution
    # A full-circle edge reports p1 == p2 == arc centre. The hole openings carry
    # an R2 blend, so the same centre also owns a R6 circle on the top face;
    # a radius-blind pick would make the diameter dimension read the blend
    # instead of the hole (silent wrong value), hence the radius filter.
    TOL = 0.05

    def near(pt, xyz):
        return (abs(pt.X - xyz[0]) < TOL and abs(pt.Y - xyz[1]) < TOL
                and abs(pt.Z - xyz[2]) < TOL)

    def face_radius(face):
        try:
            return abs(ufs.Modeling.AskFaceData(face.Tag)[4])
        except Exception:
            return -1.0

    circles = []      # (centre xy, z, radius, edge)
    n_edges = 0
    for face in body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            continue
        r = face_radius(face)
        for e in face.GetEdges():
            n_edges += 1
            try:
                p1, p2 = e.GetVertices()
            except Exception:
                continue
            if near(p1, (p2.X, p2.Y, p2.Z)):
                circles.append(((p1.X, p1.Y), p1.Z, r, e))
    print("CYL_FACE_EDGES=%d CIRCLES=%d" % (n_edges, len(circles)))

    resolved = {}

    def resolve_edges():
        """The 4 hole-wall circles: same (x, y), two z values (both ends of the
        wall). Keep the higher one, which is the opening seen in the Top view."""
        by_xy = {}
        for cxy, cz, r, e in circles:
            if abs(r - HOLE_R) > 0.01:
                continue
            key = (round(cxy[0], 3), round(cxy[1], 3))
            if key not in by_xy or cz > by_xy[key][0]:
                by_xy[key] = (cz, e)
        print("HOLE_CIRCLES=%d %s"
              % (len(by_xy), sorted("(%.1f,%.1f)" % k for k in by_xy)))
        if len(by_xy) != 4:
            raise RuntimeError("expected 4 hole circles, got %d" % len(by_xy))
        xs = sorted(set(k[0] for k in by_xy))
        ys = sorted(set(k[1] for k in by_xy))
        if len(xs) != 2 or len(ys) != 2:
            raise RuntimeError("hole grid is not 2x2: x=%s y=%s" % (xs, ys))
        # independent expectation: the pattern pitch declared in 01_bracket.py
        if abs((xs[1] - xs[0]) - PITCH_X) > 0.01:
            raise RuntimeError("x pitch %.3f != %.1f" % (xs[1] - xs[0], PITCH_X))
        if abs((ys[1] - ys[0]) - PITCH_Y) > 0.01:
            raise RuntimeError("y pitch %.3f != %.1f" % (ys[1] - ys[0], PITCH_Y))
        for name, xy in (("A", (xs[0], ys[0])), ("B", (xs[1], ys[0])),
                         ("C", (xs[0], ys[1]))):
            cz, edge = by_xy[xy]
            resolved[name] = (edge, (xy[0], xy[1], cz))
            print("CIRCLE_EDGE %s xy=(%.3f,%.3f) z=%.3f tag=%s"
                  % (name, xy[0], xy[1], cz, edge.Tag))
    stage("resolve_hole_circles", resolve_edges)

    # ------------------------------------------------------------ preferences
    def set_global_prefs():
        ap = part.Annotations.Preferences
        lp = ap.GetLetteringPreferences()
        for getter, setter, size in (
                (lp.GetDimensionText, lp.SetDimensionText, DIM_TEXT_SIZE),
                (lp.GetGeneralText, lp.SetGeneralText, TEXT_SIZE),
                (lp.GetAppendedText, lp.SetAppendedText, TEXT_SIZE),
                (lp.GetToleranceText, lp.SetToleranceText, TOL_TEXT_SIZE)):
            lt = getter()
            lt.Size = float(size)
            setter(lt)
        ap.SetLetteringPreferences(lp)

        lap = ap.GetLineAndArrowPreferences()
        lap.ArrowheadLength = ARROW_LEN
        lap.ArrowheadIncludedAngle = 10.0
        lap.FirstPosToExtLineDist = 0.0
        lap.LinePastArrowDistance = 0.0
        lap.FirstArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
        lap.SecondArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
        ap.SetLineAndArrowPreferences(lap)

        back = ap.GetLetteringPreferences().GetDimensionText().Size
        print("PREF_DIM_TEXT_SIZE=%.2f" % back)
        if abs(back - DIM_TEXT_SIZE) > 1e-6:
            raise RuntimeError("global dimension text size not applied")
    stage("global_prefs", set_global_prefs)

    # --------------------------------------------- model point -> sheet point
    def map_point(model_xyz):
        """UF_VIEW_map_model_to_drawing. Returns (x, y, source_of_truth)."""
        try:
            r = ufs.View.MapModelToDrawing(vtop.Tag, list(model_xyz))
            cand = r[1] if isinstance(r, tuple) else r
            if hasattr(cand, "__len__") and len(cand) >= 2:
                return float(cand[0]), float(cand[1]), "MapModelToDrawing"
        except Exception as exc:
            print("MAP_FAIL %s :: %s" % (str(model_xyz), str(exc)[:160]))
        # fallback: documented formula sheet = ref + proj(p) - proj(centre),
        # valid because the bracket is centred on the origin and the view is
        # pinned to scale 1:1 above; proj for the Top view is (x, y).
        ref = vtop.GetDrawingReferencePoint()
        return ref.X + float(model_xyz[0]), ref.Y + float(model_xyz[1]), "ref+proj"

    def probe_mapping():
        ref = vtop.GetDrawingReferencePoint()
        print("TOP_REF=(%.3f,%.3f)" % (ref.X, ref.Y))
        for label in ("A", "B"):
            p = resolved[label][1]
            x, y, src = map_point(p)
            print("MAP %s model=(%.3f,%.3f,%.3f) -> sheet=(%.3f,%.3f) via %s"
                  % (label, p[0], p[1], p[2], x, y, src))
            # cross-check against the documented formula
            fx, fy = ref.X + p[0], ref.Y + p[1]
            print("MAP %s formula=(%.3f,%.3f) delta=(%.3f,%.3f)"
                  % (label, fx, fy, x - fx, y - fy))
    stage("map_model_to_drawing", probe_mapping)

    # ---------------------------------------------------------------- table
    # helpers shared by the sheet furniture and the BOM table below
    def cell_text(tn, row, col):
        r0 = ufs.Tabnot.AskNthRow(tn, row)
        c0 = ufs.Tabnot.AskNthColumn(tn, col)
        cell = ufs.Tabnot.AskCellAtRowCol(norm_tag(r0), norm_tag(c0))
        return norm_tag(cell)

    def read_cell(tn, ri, ci):
        got = ufs.Tabnot.AskCellText(cell_text(tn, ri, ci))
        return got[1] if isinstance(got, tuple) else got

    def drain_table(tn):
        # the default table arrives as 5x5; drop every row/column it ships with.
        # Row count has no documented getter, so drain defensively instead of
        # guessing an API name.
        for _ in range(50):
            try:
                ufs.Tabnot.RemoveColumn(norm_tag(ufs.Tabnot.AskNthColumn(tn, 0)))
            except Exception:
                break
        for _ in range(50):
            try:
                ufs.Tabnot.RemoveRow(norm_tag(ufs.Tabnot.AskNthRow(tn, 0)))
            except Exception:
                break

    def new_table(origin, col_widths, row_heights, thick_border=False):
        sp = ufs.Tabnot.AskDefaultSectionPrefs()
        if thick_border:
            # the frame and the title block plot with a heavy border, like a
            # real sheet's 图框线; the BOM table keeps the default thin one
            sp.UseDoubleWidthBorder = True
            sp.BorderWidth = 0.7
        sp.AttachPoint = NXOpen.UF.Tabnot.AttachPoint.ATTACH_POINT_TOP_LEFT
        res = ufs.Tabnot.Create(sp,
                                [float(origin[0]), float(origin[1]), 0.0])
        tn = norm_tag(res)
        drain_table(tn)
        for w in col_widths:
            ufs.Tabnot.AddColumn(tn, norm_tag(ufs.Tabnot.CreateColumn(w)), -1)
        for h in row_heights:
            ufs.Tabnot.AddRow(tn, norm_tag(ufs.Tabnot.CreateRow(h)), -1)
        return tn

    def pin_table_geometry(tn, row_heights, ncols=1, center_first_row=False):
        # Row heights are only honoured once the per-cell auto-fit is off
        # (uf_tabnot.h on UF_TABNOT_set_row_height: "Fit methods auto size row
        # and auto size text must be disabled"); without this the frame row
        # collapsed to ~5 mm and the whole frame vanished.
        for ri, h in enumerate(row_heights):
            row = norm_tag(ufs.Tabnot.AskNthRow(tn, ri))
            for ci in range(ncols):
                cell = cell_text(tn, ri, ci)
                cp = ufs.Tabnot.AskCellPrefs(cell)
                cp.NmFitMethods = 0
                ufs.Tabnot.SetCellPrefs(cell, cp)
            ufs.Tabnot.SetRowHeight(row, float(h))
        if center_first_row:
            cell = cell_text(tn, 0, 0)
            cp = ufs.Tabnot.AskCellPrefs(cell)
            cp.HorizJust = NXOpen.UF.Tabnot.Just.JUST_CENTER
            cp.VertJust = NXOpen.UF.Tabnot.Just.JUST_MIDDLE
            ufs.Tabnot.SetCellPrefs(cell, cp)

    # ---------------------------------------------------- frame + title block
    # Both are ordinary tabular notes: a tabular note is sheet-bound and plots
    # with the sheet, which makes the frame a one-cell table and the title
    # block a 6-column table with its name row merged across all columns.
    def furniture():
        dp = ufs.Tabnot.AskDefaultCellPrefs()
        dp.TextHeight = TOL_TEXT_SIZE
        ufs.Tabnot.SetDefaultCellPrefs(dp)

        frame = new_table(FRAME_ORIGIN, [267.0], [200.0], thick_border=True)
        pin_table_geometry(frame, [200.0])
        ufs.Tabnot.Update(frame)
        print("FRAME_OK tag=%s" % frame)

        tn = new_table(TITLE_ORIGIN, [12.0, 32.0, 12.0, 38.0, 12.0, 34.0],
                       [12.0, 8.0, 8.0], thick_border=True)
        ufs.Tabnot.MergeCells(cell_text(tn, 0, 0), cell_text(tn, 0, 5))
        want = [
            [PART_NAME, "", "", "", "", ""],
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
        # read the identity cells back: SetCellText alone is not evidence that
        # the text landed (cf. SKILL.md section 3 "Commit success != written")
        for ri, ci, val in ((1, 1, "NX 12 journal"), (2, 1, DWG_NO),
                            (1, 3, "check_journal.py")):
            got = read_cell(tn, ri, ci)
            print("TITLE_CELL r%d c%d want=%s got=%s" % (ri, ci, val, got))
            if str(got) != val:
                raise RuntimeError("title block r%d c%d read-back %r != %r"
                                   % (ri, ci, got, val))
    stage("sheet_furniture", furniture)

    # -------------------------------------------------------- dimensions (UF)
    ATC = NXOpen.UF.Drf.AssocType

    def uf_obj(edge, view, assoc, dwg_xy):
        o = ufs.Drf.Object()
        ufs.Drf.InitObjectStructure(o)
        o.ObjectAssocType = getattr(ATC, assoc)
        o.ObjectTag = edge.Tag
        o.ObjectViewTag = view.Tag
        o.AssocDwgPos = [float(dwg_xy[0]), float(dwg_xy[1])]
        return o

    dims_before = len([d for d in part.Dimensions])
    made_dims = []

    def make_dims():
        # Dim lanes hang off the top view's reference point: the 70 pitch takes
        # the lane 10 mm below the view's bottom edge (half-height 30), the 40
        # pitch a vertical lane 12 mm left of the view's left edge (half-width
        # 50).  Both run outside the view; the absolute lanes this replaces
        # crossed the view and collided with the note.
        ref = vtop.GetDrawingReferencePoint()
        ea, ca = resolved["A"]
        eb, cb = resolved["B"]
        ec, cc = resolved["C"]
        da = map_point(ca)
        db = map_point(cb)
        dc = map_point(cc)

        oa = uf_obj(ea, vtop, "ARC_CENTER", (da[0], da[1]))
        ob = uf_obj(eb, vtop, "ARC_CENTER", (db[0], db[1]))
        oc = uf_obj(ec, vtop, "ARC_CENTER", (dc[0], dc[1]))

        txt = ufs.Drf.Text()
        r = ufs.Drf.CreateHorizontalDim(oa, ob, txt,
                                        [ref.X, ref.Y - 40.0, 0.0])
        made_dims.append(("hdim_pitch70", norm_tag(r)))
        r = ufs.Drf.CreateVerticalDim(oa, oc, txt, [ref.X - 62.0, ref.Y, 0.0])
        made_dims.append(("vdim_pitch40", norm_tag(r)))
        # the diameter callout goes to hole C so its leader stays short: the
        # text sits in the band between the top view and the front view
        r = ufs.Drf.CreateDiameterDim(oc, ufs.Drf.Text(),
                                      [ref.X - 53.0, ref.Y + 43.0, 0.0])
        made_dims.append(("ddim_hole8", norm_tag(r)))
        for nm, tag in made_dims:
            print("DIM_CREATED %s tag=%s" % (nm, tag))
        dims_after = len([d for d in part.Dimensions])
        print("DIM_COUNT %d -> %d" % (dims_before, dims_after))
        if dims_after - dims_before != 3:
            raise RuntimeError("expected 3 new dimensions, got %d"
                               % (dims_after - dims_before))
    stage("uf_dimensions", make_dims)

    # ----------------------------------------- global pref inheritance audit
    def check_dim_style():
        want = set(t for _, t in made_dims)
        seen = 0
        for d in part.Dimensions:
            if int(d.Tag) not in [int(t) for t in want]:
                continue
            seen += 1
            size = d.GetLetteringPreferences().GetDimensionText().Size
            print("DIM_STYLE tag=%s textSize=%.2f" % (d.Tag, size))
            if abs(size - DIM_TEXT_SIZE) > 1e-6:
                raise RuntimeError("dimension tag %s did not inherit %.1f"
                                   % (d.Tag, DIM_TEXT_SIZE))
        if seen != 3:
            raise RuntimeError("matched %d of 3 dimensions by tag" % seen)
    stage("dim_lettering_inheritance", check_dim_style)

    # ------------------------------------------------------ center lines (.NET)
    def make_centermark():
        edge, centre = resolved["A"]
        cmb = part.Annotations.Centerlines.CreateCenterMarkBuilder(
            NXOpen.Annotations.CenterMark.Null)
        cmb.Locations.Add(edge, vtop, NXOpen.Point3d(*centre))
        r = cmb.Commit()
        cmb.Destroy()
        print("CENTERMARK_OK %s" % str(r)[:80])
    stage("center_mark", make_centermark)

    def make_centerline():
        ea, ca = resolved["A"]
        eb, cb = resolved["B"]
        c2 = part.Annotations.Centerlines.CreateCenterline2dBuilder(
            NXOpen.Annotations.Centerline2d.Null)
        c2.Type = c2.Types.ByPoints
        c2.Point1.SetValue(ea, vtop, NXOpen.Point3d(*ca))
        c2.Point2.SetValue(eb, vtop, NXOpen.Point3d(*cb))
        r = c2.Commit()
        c2.Destroy()
        print("CENTERLINE_OK %s" % str(r)[:80])
    stage("centerline_2d", make_centerline)

    # ------------------------------------------------------ note + label (.NET)
    def set_size(obj, size):
        lp = obj.GetLetteringPreferences()
        g = lp.GetGeneralText()
        g.Size = float(size)
        lp.SetGeneralText(g)
        obj.SetLetteringPreferences(lp)

    def make_note():
        note = part.Annotations.CreateNote(
            [u"技术要求：", u"1. 未注圆角 R2。"],
            NXOpen.Point3d(*NOTE_ORIGIN, 0.0),
            NXOpen.AxisOrientation.Horizontal, None, None)
        if note is None:
            raise RuntimeError("CreateNote returned None")
        set_size(note, TEXT_SIZE)
        got = note.GetLetteringPreferences().GetGeneralText().Size
        print("NOTE_OK tag=%s size=%.2f" % (note.Tag, got))
    stage("note", make_note)

    def make_label():
        # attach to hole B and keep the text just right of the top view: the
        # old absolute position put the text in the far corner, so the leader
        # crossed the whole view.  The leader landing is a SHEET position
        # (passing the model coords reinterpreted them as sheet mm and yanked
        # the leader across the view), so it is mapped like the dims.
        edge, centre = resolved["B"]
        ref = vtop.GetDrawingReferencePoint()
        lx, ly, _src = map_point(centre)
        bundle = part.Annotations.NewLeaderBundle()
        try:
            bundle.NumberOfLeaders = 1
        except Exception:
            pass
        bundle.SetLeaderData(0, NXOpen.Annotations.LeaderAttachment.Screen,
                             edge, vtop, NXOpen.Point3d(lx, ly, 0.0), 0.0, [])
        label = part.Annotations.CreateLabel(
            [u"4x<O>8"],
            NXOpen.Point3d(ref.X + 57.0, ref.Y + 2.0, 0.0),
            None, None, None, bundle)
        if label is None:
            raise RuntimeError("CreateLabel returned None")
        set_size(label, TEXT_SIZE)
        print("LABEL_OK tag=%s" % label.Tag)
    stage("leader_label", make_label)

    # ---------------------------------------------------------------- table
    def make_table():
        # BOM-style demo table, parked directly above the title block where a
        # parts list lives on a real sheet
        dp = ufs.Tabnot.AskDefaultCellPrefs()
        dp.TextHeight = TEXT_SIZE
        ufs.Tabnot.SetDefaultCellPrefs(dp)
        tn = new_table(BOM_ORIGIN, [20.0, 40.0], [7.0, 7.0])
        want = [["序号", "1"], ["名称", "基座"]]
        for ri, vals in enumerate(want):
            for ci, val in enumerate(vals):
                ufs.Tabnot.SetCellText(cell_text(tn, ri, ci), val)
        ufs.Tabnot.Update(tn)
        print("TABLE_OK tag=%s" % tn)
        # read the cells back: SetCellText alone is not evidence that the text
        # landed (cf. SKILL.md section 3 "Commit success != written")
        for ri, vals in enumerate(want):
            for ci, val in enumerate(vals):
                got = read_cell(tn, ri, ci)
                print("TABLE_CELL r%d c%d want=%s got=%s" % (ri, ci, val, got))
                if str(got) != val:
                    raise RuntimeError("table cell r%d c%d read-back %r != %r"
                                       % (ri, ci, got, val))
    stage("table", make_table)

    # ------------------------------------------------------------------ plot
    def export_pdf():
        if os.path.exists(PDF):
            os.remove(PDF)
        pdfb = part.PlotManager.CreatePrintPdfbuilder()
        pdfb.SourceBuilder.SetSheets([sheet])
        pdfb.Colors = NXOpen.PrintPDFBuilder.Color.BlackOnWhite
        pdfb.Size = NXOpen.PrintPDFBuilder.SizeOption.FullScale
        pdfb.Units = NXOpen.PrintPDFBuilder.UnitsOption.Metric
        pdfb.Scale = 1.0
        pdfb.Filename = PDF
        pdfb.Commit()
        pdfb.Destroy()
        size = os.path.getsize(PDF) if os.path.exists(PDF) else -1
        print("PDF=%s size=%d" % (PDF, size))
        if size < 20000:
            raise RuntimeError("plot produced no usable pdf (size=%d)" % size)
    stage("export_pdf", export_pdf)

    if FAILED_STAGES:
        print("TEST19_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    print("TEST19_DONE dims=%d" % len([d for d in part.Dimensions]))


if __name__ == "__main__":
    main()
