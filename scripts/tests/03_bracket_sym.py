# -*- coding: utf-8 -*-
# Test C: symmetric bracket (mirror feature + boolean unite + holes)
# Covers: sketch+extrude half profile, datum plane via part.Planes.CreatePlane,
#         MirrorFeatureBuilder, boolean unite, hole
# 配方走 nxlib 标准层（原实现平移自本文件的已验收版本）。
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
    add_hole, create_plane, extrude, make_sketch, mirror_feature, unite_all,
)

PART_NAME = "bracket_sym"
HALF_Y = 15.0
HALF_X = 40.0
T = 8.0
HOLE_D = 8.0


def main():
    session = NXOpen.Session.GetSession()
    part = new_part(name=PART_NAME)
    wp = session.Parts.Work

    # 1) half profile sketch + extrude (y in [0, HALF_Y])
    def s1():
        nonlocal half_feat
        rect = [
            wp.Curves.CreateLine(NXOpen.Point3d(-HALF_X, 0.0, 0.0), NXOpen.Point3d(HALF_X, 0.0, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(HALF_X, 0.0, 0.0), NXOpen.Point3d(HALF_X, HALF_Y, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(HALF_X, HALF_Y, 0.0), NXOpen.Point3d(-HALF_X, HALF_Y, 0.0)),
            wp.Curves.CreateLine(NXOpen.Point3d(-HALF_X, HALF_Y, 0.0), NXOpen.Point3d(-HALF_X, 0.0, 0.0)),
        ]
        make_sketch(wp, rect)
        half_feat = extrude(wp, rect, str(T))
    half_feat = None
    stage("half_sketch_extrude", s1)

    # 2) mirror across XZ plane (normal +Y through origin)
    def s2():
        mirror_plane = create_plane(wp, NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0))
        mirror_feature(wp, [half_feat], mirror_plane)
    stage("mirror_feature", s2)

    # 3) unite the two bodies
    def s3():
        unite_all(wp)
    stage("unite", s3)

    # 4) four holes on the united body
    def s4():
        body = [b for b in wp.Bodies][0]
        for x, y in [(-25.0, 10.0), (25.0, 10.0), (25.0, -10.0), (-25.0, -10.0)]:
            add_hole(wp, body, x, y, T, str(HOLE_D))
    stage("holes", s4)

    save()
    stage_finish("TEST03_DONE bodies=" + str(len([b for b in wp.Bodies])), "TEST03")


if __name__ == "__main__":
    main()
