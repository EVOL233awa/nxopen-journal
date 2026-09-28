# -*- coding: utf-8 -*-
# Test B: flange (revolve: two convex sections + boolean unite, circular pattern, edge blend)
# Covers: UF Modl.CreateRevolved (convex sections only; concave profile fails in NX12 batch),
#         boolean unite, hole, circular pattern, edge blend
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
    add_thru_hole_faces, blend_on_faces, find_face, pattern_circular,
    revolve_rect_uf, unite_all, ufs,
)

PART_NAME = "flange"
HUB_LEN = 20.0
HUB_R = 15.0
BORE_R = 10.0
PLATE_R = 40.0
PLATE_T = 10.0
HOLE_D = 8.0
PCD_R = 30.0
BLEND_R = 2.0


def main():
    session = NXOpen.Session.GetSession()
    part = new_part(name=PART_NAME)
    wp = session.Parts.Work

    # 1) hub tube + plate tube, unite -> flange with bore
    def s1():
        nonlocal body
        revolve_rect_uf(wp, 0.0, HUB_LEN, BORE_R, HUB_R)
        revolve_rect_uf(wp, HUB_LEN - PLATE_T, HUB_LEN, BORE_R, PLATE_R)
        unite_all(wp)
        body = [b for b in wp.Bodies][0]
    body = None
    stage("revolve_unite", s1)

    # 2) one hole -> circular pattern (6 copies, 60 deg pitch)
    def s2():
        top = find_face(wp, body, NXOpen.Point3d(PLATE_R, 0.0, 0.0), 1.0, axis=0)
        bottom = find_face(wp, body, NXOpen.Point3d(PLATE_R - PLATE_T, 0.0, 0.0), -1.0, axis=0)
        seed_hole = add_thru_hole_faces(wp, NXOpen.Point3d(PLATE_R, PCD_R, 0.0), top, bottom, "8")
        pattern_circular(
            wp, [seed_hole],
            NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(1.0, 0.0, 0.0),
            "60", "6",
        )
    stage("circular_pattern", s2)

    # 3) edge blend on hub outer cylinder edges (r=15)
    def s3():
        u = ufs()
        hub_faces = []
        for face in body.GetFaces():
            if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
                continue
            r = abs(u.Modeling.AskFaceData(face.Tag)[4])
            if abs(r - HUB_R) < 0.01:
                hub_faces.append(face)
        blend_on_faces(wp, hub_faces, BLEND_R)
    stage("edge_blend", s3)

    save()
    stage_finish("TEST02_DONE bodies=" + str(len([b for b in wp.Bodies])), "TEST02")


if __name__ == "__main__":
    main()
