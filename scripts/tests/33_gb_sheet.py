# -*- coding: utf-8 -*-
# Test 33: a complete GB-style drawing sheet produced ONLY through the
# shipped gb_drawing module.
#
# Why this case exists
#   Cases 06/19/20 prove individual NXOpen drafting APIs; none of them proves
#   that a fresh journal can import the module and get a deliverable
#   quality sheet on the first try (the "随手一用" acceptance).  This case is
#   that acceptance: plate 100x60x10 with two D10 holes, then frame / views /
#   title block / tech note / dimensions / centerlines / PDF - every step
#   through gb_drawing, with zero drafting code in the case itself beyond the
#   model-side attachments the caller must supply (which edges, which lane).
#
# Coverage
#   module import under the NX interpreter (defensive sys.path: __file__ may
#     be undefined; argv scan fallback; CWD fallback)
#   blank_datums / apply_gb_preferences / new_sheet(A4 first angle)
#   frame (GB/T 14689.1 margins, double-width border)
#   standard_views pinned FRONT/TOP/RIGHT at 1:1 with content assertions
#   title_block read-backs + tech_note
#   UF dimensions between edge/arc attachments on lanes derived from
#     view_bbox (LANE_FIRST/LANE_STEP); same-direction lanes ordered by
#     value ascending outward (small inner / large outer, GB/T 4458.4),
#     lane order asserted via AnnotationOrigin readback
#   quantity label 2x<O>10 on ONE hole (group elements get a single
#     callout, GB/T 4458.4) via gb.quantity_label
#   center marks + ByPoints centerline, PDF export + byte sanity
#
# The layout mirrors the module's reference sheet: pitch (44) on the inner
# lane and overall (100) on the outer lane below the top view, height on the
# right of the top view, thickness on the left of the front view, one
# quantity label leader landing in the band between front and top views.
import os
import sys

import NXOpen
import NXOpen.UF


def _module_dirs():
    """Directories to add to sys.path: the case's own dir (tests/) and its
    parent (scripts/, where gb_drawing.py ships)."""
    here = None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        for a in sys.argv:
            if str(a).lower().endswith("33_gb_sheet.py"):
                here = os.path.dirname(os.path.abspath(str(a)))
                break
    if here is None:
        here = os.path.abspath(os.getcwd())
    return here, os.path.dirname(here)


_here, _parent = _module_dirs()
for _p in (_here, _parent):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import gb_drawing as gb
    print("IMPORT_OK from %s" % os.path.abspath(
        getattr(gb, "__file__", "?")))
except Exception as exc:
    print("TEST33_FAIL import_gb_drawing :: %s" % exc)
    print("sys.path=%r" % (sys.path[:6],))
    sys.exit(0)

from nxlib.modeling import add_thru_hole, block
from nxlib.session import new_part
from nxlib.testing import FAILED_STAGES, stage

PDF = os.path.abspath("m33_gb.pdf")
PLATE_PATH = os.path.abspath("m33_plate.prt")

BLOCK = (-50.0, -30.0, 0.0)
BLOCK_L = (100.0, 60.0, 10.0)
HOLE_X = 22.0
HOLE_D = 10.0
SCALE = 1.0

VIEW_VISIBLE_MIN = 4
DIM_WANT = 4                 # 100 overall, 44 pitch, 60 height, 10 thickness
                             # (the 2x D10 callout is a label, not a dimension)
PDF_MIN_BYTES = 2000         # blank A4 sheet plots to 917 bytes (measured)


def endpoint_at(edge, pick_x=None, pick_y=None, pick_z=None):
    """Return the edge endpoint matching the given picks (nearest on each
    specified axis); picks left as None take p1's value."""
    p1, p2 = edge.GetVertices()
    best = p1
    for cand in (p1, p2):
        score_b = 0.0
        score_c = 0.0
        if pick_x is not None:
            score_b += abs(p1.X - pick_x)
            score_c += abs(cand.X - pick_x)
        if pick_y is not None:
            score_b += abs(p1.Y - pick_y)
            score_c += abs(cand.Y - pick_y)
        if pick_z is not None:
            score_b += abs(p1.Z - pick_z)
            score_c += abs(cand.Z - pick_z)
        if score_c < score_b:
            best = cand
    return best


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    state = {}

    def s_build():
        for p in (PLATE_PATH, PDF):
            if os.path.exists(p):
                os.remove(p)
        part = new_part(name="m33_plate")
        session.Parts.SetWork(part)
        ufs.Part.SetDisplayPart(part.Tag)
        body = block(part, NXOpen.Point3d(BLOCK[0], BLOCK[1], BLOCK[2]),
                     str(BLOCK_L[0]), str(BLOCK_L[1]), str(BLOCK_L[2]))
        unit = part.UnitCollection.GetBase("Length")
        part.Expressions.CreateSystemExpressionWithUnits(
            "HOLE_D = %.4f" % HOLE_D, unit)
        add_thru_hole(part, body, -HOLE_X, 0.0, BLOCK_L[2], "HOLE_D")
        add_thru_hole(part, body, HOLE_X, 0.0, BLOCK_L[2], "HOLE_D")
        bodies = list(part.Bodies)
        if len(bodies) != 1:
            raise RuntimeError("expected 1 body, got %d" % len(bodies))
        state["part"] = part
        state["body"] = bodies[0]
        print("BODIES=%d" % len(bodies))
    stage("build_part", s_build)

    def s_preflight():
        n = gb.blank_datums(state["part"])
        print("BLANKED_DATUMS=%d" % n)
        gb.apply_gb_preferences(state["part"])
        state["sheet"] = gb.new_sheet(state["part"], "SHT1", "A4")
        state["frame"] = gb.frame(state["sheet"], "A4")
        f = state["frame"]
        print("FRAME_OK left=%.1f right=%.1f top=%.1f bottom=%.1f"
              % (f["left"], f["right"], f["top"], f["bottom"]))
        if abs(f["left"] - gb.BINDING_A) > 1e-6 or abs(f["right"] - 292.0) \
                > 1e-6:
            raise RuntimeError("frame margins off GB/T 14689.1: %r" % (f,))
    stage("prefs_sheet_frame", s_preflight)

    def s_views():
        views = gb.standard_views(state["part"], state["sheet"],
                                  body=state["body"], scale=SCALE, size="A4")
        counts = []
        for k in ("FRONT", "TOP", "RIGHT"):
            v = views[k]
            vis = v.AskVisibleObjects() or []
            n = len(vis)
            counts.append("%s:%d" % (k, n))
            if n < VIEW_VISIBLE_MIN:
                raise RuntimeError("view %s has only %d visible objects"
                                   % (k, n))
            state[k] = v
        state["mbbox"] = gb.model_bbox(state["body"])
        for k in ("FRONT", "TOP", "RIGHT"):
            cb = gb.content_bbox(state[k], *state["mbbox"])
            print("VIEW %s content=(%.1f,%.1f)-(%.1f,%.1f)"
                  % (k, cb[0], cb[1], cb[2], cb[3]))
        print("VIEWS=3 VISIBLE=%s" % (",".join(counts),))
    stage("standard_views", s_views)

    def s_furniture():
        part = state["part"]
        tb = gb.title_block(
            state["sheet"], state["frame"],
            name=u"试验板", design=None, check=None, date=None,
            dwg_no="NXOJ-33", scale_txt=gb.scale_text(SCALE),
            material=None)
        print("TB_OK left=%.1f top=%.1f" % (tb["left"], tb["top"]))
        gb.tech_note(state["sheet"], tb)
        print("NOTE_OK")
        # the module already read back every filled cell; assert the table
        # really sits flush with the frame corner
        if abs(tb["right"] - state["frame"]["right"]) > 1e-6 \
                or abs(tb["bottom"] - state["frame"]["bottom"]) > 1e-6:
            raise RuntimeError("title block not flush with frame corner")
        _ = part
    stage("title_block_tech_note", s_furniture)

    def s_dims():
        part = state["part"]
        body = state["body"]
        top = state["TOP"]
        front = state["FRONT"]
        edges = gb.linear_edges(body)
        holes = gb.hole_circles(body, radius=HOLE_D / 2.0)
        if len(holes) != 2:
            raise RuntimeError("expected 2 hole circles, got %d (radii %r)"
                               % (len(holes),
                                  [round(h[2], 3) for h in
                                   gb.hole_circles(body)]))
        for h in holes:
            if abs(h[2] - HOLE_D / 2.0) > 0.01:
                raise RuntimeError("hole radius %.3f != %.3f"
                                   % (h[2], HOLE_D / 2.0))
        print("HOLES=2 RADII=%.2f/%.2f" % (holes[0][2], holes[1][2]))

        before = len(list(part.Dimensions))
        ct = gb.content_bbox(top, *state["mbbox"])
        tb_bottom, tb_right = ct[1], ct[2]
        cf = gb.content_bbox(front, *state["mbbox"])
        fr_left = cf[0]

        # 44 pitch between the hole centres: FIRST (inner) lane — GB/T 4458.4
        # orders same-direction lanes by value ascending outward, so the
        # smaller dimension never has its extension lines crossed by the
        # larger one's dimension line
        holes_sorted = sorted(holes, key=lambda h: h[1][0])
        pitch_tag = gb.dim_between(
            part, top,
            (holes_sorted[0][0], "ARC_CENTER", holes_sorted[0][1]),
            (holes_sorted[1][0], "ARC_CENTER", holes_sorted[1][1]),
            lane_y=tb_bottom - gb.LANE_FIRST)
        # 100 overall: second (outer) lane
        e_left = gb.extreme_edge(edges, along="y", key="x", side="min")
        e_right = gb.extreme_edge(edges, along="y", key="x", side="max")
        overall_tag = gb.dim_between(
            part, top,
            (e_left[0], "END_POINT", endpoint_at(e_left[0])),
            (e_right[0], "END_POINT", endpoint_at(e_right[0])),
            lane_y=tb_bottom - gb.LANE_FIRST - gb.LANE_STEP)
        # 60 height: right of the TOP view
        e_low = gb.extreme_edge(edges, along="x", key="y", side="min")
        e_high = gb.extreme_edge(edges, along="x", key="y", side="max")
        gb.dim_between(part, top,
                       (e_low[0], "END_POINT",
                        endpoint_at(e_low[0], pick_x=1e9)),
                       (e_high[0], "END_POINT",
                        endpoint_at(e_high[0], pick_x=1e9)),
                       lane_x=tb_right + gb.LANE_FIRST, horizontal=False)
        # 10 thickness: left of the FRONT view
        e_bot = gb.extreme_edge(edges, along="x", key="z", side="min")
        e_top = gb.extreme_edge(edges, along="x", key="z", side="max")
        gb.dim_between(part, front,
                       (e_bot[0], "END_POINT",
                        endpoint_at(e_bot[0], pick_x=-1e9)),
                       (e_top[0], "END_POINT",
                        endpoint_at(e_top[0], pick_x=-1e9)),
                       lane_x=fr_left - gb.LANE_FIRST, horizontal=False)
        # 2x D10: ONE quantity label on the first hole (GB/T 4458.4 group
        # elements carry size AND count in a single callout); the landing
        # point is a sheet position in the band between views
        hx = (ct[0] + ct[2]) / 2.0
        hy = ct[3] + 12.0
        label = gb.quantity_label(part, top, holes_sorted[0][0],
                                  holes_sorted[0][1], (hx - 35.0, hy),
                                  u"2x<O>10")
        if label is None:
            raise RuntimeError("quantity label not created")
        print("QTY_LABEL_OK tag=%s" % label.Tag)

        after = len(list(part.Dimensions))
        print("DIMS=%d" % (after - before))
        if after - before != DIM_WANT:
            raise RuntimeError("expected %d dimensions, got %d"
                               % (DIM_WANT, after - before))

        # lane order readback: below the view the inner lane has the larger
        # sheet y, and the smaller (pitch) dimension must sit there
        def _dim_origin_y(tag):
            for d in part.Dimensions:
                if int(d.Tag) == int(tag):
                    return d.AnnotationOrigin.Y
            raise RuntimeError("dimension tag %s not found for readback"
                               % (tag,))
        pitch_y = _dim_origin_y(pitch_tag)
        overall_y = _dim_origin_y(overall_tag)
        if not pitch_y > overall_y:
            raise RuntimeError("lane order wrong: pitch y %.2f must sit above "
                               "overall y %.2f (small inner / large outer)"
                               % (pitch_y, overall_y))
        print("LANE_ORDER_OK pitch_y=%.2f overall_y=%.2f"
              % (pitch_y, overall_y))
    stage("dimensions", s_dims)

    def s_centers():
        part = state["part"]
        top = state["TOP"]
        body = state["body"]
        holes = sorted(gb.hole_circles(body, radius=HOLE_D / 2.0),
                       key=lambda h: h[1][0])
        for h in holes:
            gb.centermark(part, top, h[0], h[1])
        gb.centerline_by_points(part, top, holes[0][0], holes[0][1],
                                holes[1][0], holes[1][1])
        print("CENTERS=2 CENTERLINE=1")
    stage("centerlines", s_centers)

    def s_export():
        gb.export_pdf(state["part"], state["sheet"], PDF)
        size = os.path.getsize(PDF)
        print("PDF=%d" % size)
        if size < PDF_MIN_BYTES:
            raise RuntimeError("PDF %d bytes < %d: sheet plots empty"
                               % (size, PDF_MIN_BYTES))
    stage("export_pdf", s_export)

    if FAILED_STAGES:
        print("TEST33_FAIL stages=%s" % (",".join(FAILED_STAGES),))
    else:
        print("TEST33_DONE")


main()
