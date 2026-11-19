# -*- coding: utf-8 -*-
# Test 54: complete GB assembly-drawing furniture through gb_drawing only.
#
# Covers: full_title_block (180x56, all required fields), centering_marks,
#         balloon (UF ID symbol, circle + screen leader), set_view_line_width
#         (Width.Five = 0.5 mm), set_thin_line_widths, assembly_section
#         (TOP parent, orient_view=
#         FRONT, rotation equals FRONT and Hatch>=1)
#         and audit_gb_assembly (balloons/dimensions/section/title gate).
#
# The "assembly" is two disjoint bodies in one part: a plate and a pin.  The
# point is the drawing furniture and the gate, not component constraints
# (tests 04/10/35 cover those).
import os
import sys

import NXOpen
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_scripts = os.path.abspath(os.path.join(_here, ".."))
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import gb_drawing as gb
from nxlib.modeling import block
from nxlib.session import new_part
from nxlib.testing import stage, stage_finish

PDF = os.path.abspath("m54_gb_assembly.pdf")
PART = os.path.abspath("m54_gb_assembly.prt")


def main():
    ufs = NXOpen.UF.UFSession.GetUFSession()
    state = {}

    def s_build():
        for p in (PART, PDF):
            if os.path.exists(p):
                os.remove(p)
        part = new_part(name="m54_gb_assembly")
        ufs.Part.SetDisplayPart(part.Tag)
        block(part, NXOpen.Point3d(-50.0, -30.0, 0.0),
              "100", "60", "10")
        block(part, NXOpen.Point3d(40.0, -10.0, 10.0),
              "20", "20", "30")
        bodies = list(part.Bodies)
        if len(bodies) != 2:
            raise RuntimeError("expected 2 bodies, got %d" % len(bodies))
        state["part"] = part
        state["bodies"] = bodies
        state["bbox"] = gb.assembly_bbox(bodies)
        print("BODIES=2 BBOX=%r" % (state["bbox"],))
    stage("build_two_bodies", s_build)

    def s_sheet():
        part = state["part"]
        gb.blank_datums(part)
        gb.apply_gb_preferences(part)
        fid = gb.set_cjk_font(part)
        if fid <= 0:
            raise RuntimeError("set_cjk_font returned %r" % (fid,))
        sheet = gb.new_sheet(part, "SHT1", "A3")
        frame = gb.frame(sheet, "A3")
        state["sheet"] = sheet
        state["frame"] = frame
        print("FRAME=%.1f/%.1f/%.1f/%.1f"
              % (frame["left"], frame["right"], frame["top"],
                 frame["bottom"]))
    stage("sheet_frame", s_sheet)

    def s_views():
        part = state["part"]
        sheet = state["sheet"]
        views = gb.standard_views(part, sheet, bbox=state["bbox"],
                                  scale=1.0, size="A3")
        state["views"] = views
        gb.set_view_line_width(part, list(views.values()))
        for key in ("FRONT", "TOP", "RIGHT"):
            v = views[key]
            n = len(v.AskVisibleObjects() or [])
            if n < 2:
                raise RuntimeError("view %s has %d visible objects"
                                   % (key, n))
        print("VIEWS=3 LINE_WIDTH=0.5mm")
    stage("views_line_width", s_views)

    def s_furniture():
        sheet = state["sheet"]
        frame = state["frame"]
        tb = gb.full_title_block(
            sheet, frame, name=u"试验总成", dwg_no="NXOJ-54",
            material=u"见明细栏", scale_txt="1:1", weight="1.20 kg",
            design="ZCode", review="ZCode", process="ZCode",
            standardization="ZCode", approve="ZCode", date=None,
            unit_name=u"NXOpen Journal", total_sheets="1", sheet_no="1")
        state["tb"] = tb
        gb.centering_marks(sheet, "A3")
        print("TITLE_FIELDS=%d" % len(tb["fields"]))
    stage("full_title_marks", s_furniture)

    def s_balloons():
        part = state["part"]
        views = state["views"]
        a1 = gb.map_point(views["TOP"], (-50.0, -30.0, 10.0))
        a2 = gb.map_point(views["TOP"], (50.0, 10.0, 40.0))
        gb.balloon(part, "1", a1, (a1[0] - 18.0, a1[1] + 18.0))
        gb.balloon(part, "2", a2, (a2[0] + 18.0, a2[1] + 18.0))
        n = len(list(part.Annotations.IdSymbols))
        print("BALLOONS=%d" % n)
        if n < 2:
            raise RuntimeError("expected 2 ID symbols, got %d" % n)
    stage("balloons", s_balloons)

    def s_section():
        part = state["part"]
        views = state["views"]
        sec = gb.assembly_section(
            part, views["TOP"],
            [(-60.0, 0.0, 5.0), (60.0, 0.0, 5.0)],
            (150.0, 150.0), orient_view=views["FRONT"])
        if not ufs.Draw.IsSxview(sec.Tag):
            raise RuntimeError("section view not reported as Sxview")
        rot_sec = [round(float(x), 6) for x in ufs.View.AskRotation(sec.Tag)]
        rot_front = [round(float(x), 6)
                     for x in ufs.View.AskRotation(views["FRONT"].Tag)]
        if rot_sec != rot_front:
            raise RuntimeError("section orientation %r != FRONT %r"
                               % (rot_sec, rot_front))
        kinds = {}
        for o in (sec.AskVisibleObjects() or []):
            k = type(o).__name__
            kinds[k] = kinds.get(k, 0) + 1
        if kinds.get("Hatch", 0) < 1:
            raise RuntimeError("section has no hatch: %r" % kinds)
        print("SECTION=%s HATCH=%d ROT=FRONT" % (sec.Name, kinds["Hatch"]))
    stage("section", s_section)

    def s_thin_lines():
        part = state["part"]
        n = gb.set_thin_line_widths(part)
        if n < 2:
            raise RuntimeError("thin width touched %d objects" % n)
        want = NXOpen.DisplayableObject.ObjectWidth.Three
        bad = [o for o in list(part.Annotations.IdSymbols)
               if o.LineWidth != want]
        if bad:
            raise RuntimeError("ID symbol width readback %r" % bad[0].LineWidth)
        print("THIN_WIDTH=%d objects 0.25mm" % n)
    stage("thin_lines", s_thin_lines)

    def s_gate():
        part = state["part"]
        sheet = state["sheet"]
        rep = gb.audit_gb_assembly(
            part, sheet, state["tb"]["fields"], [1, 2],
            min_dims=0, require_section=True, strict=True)
        print("AUDIT=%r" % (rep,))
    stage("gb_gate", s_gate)

    def s_export():
        gb.export_pdf(state["part"], state["sheet"], PDF)
        size = os.path.getsize(PDF)
        print("PDF=%d" % size)
        if size < 20000:
            raise RuntimeError("PDF too small: %d" % size)
    stage("export_pdf", s_export)

    stage_finish("TEST54_DONE", "TEST54")


if __name__ == "__main__":
    main()
