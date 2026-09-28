# -*- coding: utf-8 -*-
# Test A: parametric bracket (base part)
# Covers: FileNew, expressions, sketch+autodim, extrude, hole, chamfer,
#         edge blend, linear pattern, boolean subtract, expression edit+update
# 2026-09-24 起配方走 nxlib 标准层（原实现平移自本文件的已验收版本）。
import os
import sys

import NXOpen

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import stage, stage_finish
from nxlib.session import new_part, save
from nxlib.modeling import (
    add_hole, bodies, body_box, blend_on_edges, blend_on_faces, extrude,
    expressions, extrude_subtract, make_sketch, pattern_linear_rect,
    unique_by_tag, ufs,
)

PART_NAME = "bracket"
L = 100.0
W = 60.0
T = 10.0
HD = 8.0
SLOT_L = 30.0
SLOT_W = 8.0
FILLET_R = 1.0
BLEND_R = 2.0


def main():
    session = NXOpen.Session.GetSession()
    part = new_part(name=PART_NAME)
    wp = session.Parts.Work
    exprs = expressions(wp, [("L", L), ("W", W), ("T", T), ("HD", HD)])

    # 1) outer rectangle sketch + hole-center cross reference lines -> extrude T
    def s1():
        nonlocal body, cross_lines
        rect = [
            wp.Curves.CreateLine(NXOpen.Point3d(-L / 2.0, -W / 2.0, 0.0), NXOpen.Point3d(L / 2.0, -W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(L / 2.0, -W / 2.0, 0.0), NXOpen.Point3d(L / 2.0, W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(L / 2.0, W / 2.0, 0.0), NXOpen.Point3d(-L / 2.0, W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(-L / 2.0, W / 2.0, 0.0), NXOpen.Point3d(-L / 2.0, -W / 2.0, 0.0)),
        ]
        cross_lines = []
        for cx, cy in [(-35.0, -20.0), (35.0, -20.0), (35.0, 20.0), (-35.0, 20.0)]:
            h = 6.0
            cross_lines.append(wp.Curves.CreateLine(NXOpen.Point3d(cx - h, cy, 0.0), NXOpen.Point3d(cx + h, cy, 0.0)))
            cross_lines.append(wp.Curves.CreateLine(NXOpen.Point3d(cx, cy - h, 0.0), NXOpen.Point3d(cx, cy + h, 0.0)))
        make_sketch(wp, rect, cross_lines)
        extrude(wp, rect, "T")
        body = [b for b in wp.Bodies][0]
    body = None
    cross_lines = None
    stage("sketch+extrude", s1)

    # 2) seed hole only (center read from first horizontal cross reference line)
    def s2():
        nonlocal seed_hole, seed_hole_pt
        hline = cross_lines[0]
        s = hline.StartPoint
        e = hline.EndPoint
        cx = (s.X + e.X) / 2.0
        cy = (s.Y + e.Y) / 2.0
        seed_hole_pt = (cx, cy)
        print("SEED_HOLE_AT ({:.3f},{:.3f})".format(cx, cy))
        seed_hole = add_hole(wp, body, cx, cy, T, "HD")
    seed_hole = None
    seed_hole_pt = None
    stage("seed_hole", s2)

    # 3) fillet (round) on seed hole opening edges
    def s3():
        nonlocal blend_feature
        u = ufs()
        seed_wall_faces = []
        for face in seed_hole.GetFaces():
            if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
                continue
            r = abs(u.Modeling.AskFaceData(face.Tag)[4])
            if abs(r - HD / 2.0) < 0.01:
                seed_wall_faces.append(face)
        blend_feature = blend_on_faces(wp, seed_wall_faces, FILLET_R)
        print("SEED_FILLET_OK")
    blend_feature = None
    stage("seed_fillet", s3)

    # 4) 2D linear pattern of [seed hole + fillet] -> 4 corner holes, fillet on every instance
    def s4():
        pattern_linear_rect(wp, [seed_hole, blend_feature], "70", "40", "2", "2")
        u = ufs()
        wall_count = 0
        fillet_count = 0
        for face in body.GetFaces():
            data = u.Modeling.AskFaceData(face.Tag)
            r = abs(data[4])
            # hole wall: cylindrical face r = HD/2
            if abs(r - HD / 2.0) < 0.01:
                wall_count += 1
            # hole opening fillet: torus face (type 19), UF radius = major radius = HD/2 + R
            if abs(r - (HD / 2.0 + FILLET_R)) < 0.01:
                fillet_count += 1
        print("PATTERN_VERIFY walls={} fillets={}".format(wall_count, fillet_count))
    stage("pattern_hole_fillet", s4)

    # 5) edge blend on 4 vertical outer corners (independent of holes)
    def s5():
        u = ufs()
        vert_edges = []
        for face in body.GetFaces():
            data = u.Modeling.AskFaceData(face.Tag)
            if data[0] != 22 or abs(data[2][2]) > 0.01:
                continue
            for edge in face.GetEdges():
                e0 = edge.GetVertices()[0]
                e1 = edge.GetVertices()[1]
                if abs(e0.X - e1.X) < 1e-6 and abs(e0.Y - e1.Y) < 1e-6 and abs(e0.Z - e1.Z) > 1.0:
                    vert_edges.append(edge)
        uniq = unique_by_tag(vert_edges)
        blend_on_edges(wp, uniq, BLEND_R)
    stage("outer_edge_blend", s5)

    # 6) slot sketch -> extrude -> boolean subtract
    def s6():
        slot = [
            wp.Curves.CreateLine(NXOpen.Point3d(-SLOT_L / 2.0, -SLOT_W / 2.0, 0.0), NXOpen.Point3d(SLOT_L / 2.0, -SLOT_W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(SLOT_L / 2.0, -SLOT_W / 2.0, 0.0), NXOpen.Point3d(SLOT_L / 2.0, SLOT_W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(SLOT_L / 2.0, SLOT_W / 2.0, 0.0), NXOpen.Point3d(-SLOT_L / 2.0, SLOT_W / 2.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(-SLOT_L / 2.0, SLOT_W / 2.0, 0.0), NXOpen.Point3d(-SLOT_L / 2.0, -SLOT_W / 2.0, 0.0)),
        ]
        make_sketch(wp, slot)
        extrude_subtract(wp, body, slot, "T")
    stage("boolean_subtract", s6)

    # 7) expression edit T 10->12, update, verify, revert
    def s7():
        exprs["T"].RightHandSide = "12"
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "edit_T")
        errs = session.UpdateManager.DoUpdate(mark)
        box = body_box(wp, body)
        print("AFTER_EDIT z=({:.3f},{:.3f}) h={:.3f} errs={}".format(box[2], box[5], box[5] - box[2], errs))
        exprs["T"].RightHandSide = str(T)
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "revert_T")
        errs = session.UpdateManager.DoUpdate(mark)
        box = body_box(wp, body)
        print("AFTER_REVERT z=({:.3f},{:.3f}) h={:.3f} errs={}".format(box[2], box[5], box[5] - box[2], errs))
    stage("expression_edit", s7)

    save()
    stage_finish("TEST01_DONE bodies=" + str(len(bodies(wp))), "TEST01")


if __name__ == "__main__":
    main()
