# -*- coding: utf-8 -*-
"""Test 52: 占用门用三轴+体积抓住 1 mm 薄腔。

旧口径只切 Z、站距 1.18 mm，1 mm 薄腔可能 0 命中，于是"面积无差异"被当
PASS。本用例建两个真实 NX 件（平板 / 同尺寸挖 20×20×1 浅腔），导出 STL 后
要求：

  - 薄腔对 FAIL，且 Z 轴至少 1 个站命中（三轴/体积至少一条给出证据）；
  - 同件自比 PASS；
  - 无差异且站距粗于 min_feature/2 时 NO_SIGNAL，不是 PASS。

出口 TEST52_DONE。
"""
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

import occupancy as occ
from nxlib import measure, modeling
from nxlib import session as S
from nxlib.testing import check, check_finish, say

BASE = os.getcwd()


def build_plain(name):
    path = os.path.join(BASE, name + ".prt")
    part = S.new_part(path=path)
    modeling.block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "10")
    S.save()
    return part


def build_pocket(name):
    path = os.path.join(BASE, name + ".prt")
    part = S.new_part(path=path)
    modeling.block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "10")
    rect = [
        part.Curves.CreateLine(NXOpen.Point3d(0.0, 0.0, 0.0),
                               NXOpen.Point3d(20.0, 0.0, 0.0)),
        part.Curves.CreateLine(NXOpen.Point3d(20.0, 0.0, 0.0),
                               NXOpen.Point3d(20.0, 20.0, 0.0)),
        part.Curves.CreateLine(NXOpen.Point3d(20.0, 20.0, 0.0),
                               NXOpen.Point3d(0.0, 20.0, 0.0)),
        part.Curves.CreateLine(NXOpen.Point3d(0.0, 20.0, 0.0),
                               NXOpen.Point3d(0.0, 0.0, 0.0)),
    ]
    modeling.make_sketch(part, rect)
    modeling.extrude_subtract(part, modeling.bodies(part)[0], rect, "1")
    S.save()
    return part


def export(part, name):
    path = os.path.join(BASE, name + ".stl")
    measure.export_mesh(part, path, chordal_tol=0.01)
    return path


def main():
    plain = build_plain("occ52_plain")
    pocket = build_pocket("occ52_pocket")
    say("BODIES plain=%d pocket=%d" % (
        len(list(plain.Bodies)), len(list(pocket.Bodies))))
    ref = export(plain, "occ52_plain")
    cut = export(pocket, "occ52_pocket")

    res = occ.occupancy_gate(ref, cut, pitch=1.18, min_feature=1.0)
    axes = res.get("report", {}).get("axes", {})
    z_hits = len(axes.get("z", {}).get("hits", []))
    say("CAVITY %s z_hits=%d rel=%.5f"
        % (res["verdict"], z_hits, res["report"].get("rel_volume", -1.0)))
    check("T52_THIN_CAVITY",
          res["verdict"] == "FAIL"
          and "DELIV_E_OCCUPANCY" in res["codes"]
          and z_hits >= 1
          and res["report"]["rel_volume"] > 0.001,
          "codes=%s z_hits=%d rel=%.5f"
          % (res["codes"], z_hits, res["report"]["rel_volume"]))

    same = occ.occupancy_gate(ref, ref, pitch=1.18)
    say("SELF %s" % same["verdict"])
    check("T52_SELF_PASS", same["verdict"] == "PASS",
          "codes=%s" % same["codes"])

    coarse = occ.occupancy_gate(ref, ref, pitch=1.18, min_feature=1.0)
    say("COARSE %s %s" % (coarse["verdict"], coarse["codes"]))
    check("T52_COARSE_NO_SIGNAL",
          coarse["verdict"] == "NO_SIGNAL"
          and "DELIV_E_OCC_NO_SIGNAL" in coarse["codes"],
          "codes=%s" % coarse["codes"])

    return check_finish("TEST52_DONE", "TEST52")


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as exc:
        import traceback
        say("TEST52_EXC " + repr(exc))
        say(traceback.format_exc()[-600:])
        raise
    sys.exit(0 if ok else 1)
