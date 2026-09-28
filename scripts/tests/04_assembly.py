# -*- coding: utf-8 -*-
# Test D: assembly (create two parts, build assembly, add components)
# Covers: multiple FileNew in one session, ComponentAssembly.AddComponent,
#         component placement via origin + matrix, save assembly
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

from nxlib.assembly import add_component
from nxlib.modeling import block, bodies
from nxlib.session import new_part, save, set_work
from nxlib.testing import stage, stage_finish


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    # 1) component parts: plate + pin
    def s1():
        nonlocal plate_path, pin_path
        plate = new_part(name="asm_plate")
        wp = set_work(plate)
        block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "60.0", "40.0", "6.0")
        ufs.Part.Save()
        plate_path = plate.FullPath
        print("PLATE_PATH=" + str(plate_path))
        pin = new_part(name="asm_pin")
        wp = set_work(pin)
        block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "12.0", "12.0", "30.0")
        ufs.Part.Save()
        pin_path = pin.FullPath
        print("PIN_PATH=" + str(pin_path))
    plate_path = None
    pin_path = None
    stage("create_components", s1)

    # 2) assembly part + add components
    def s2():
        nonlocal assy
        assy = new_part(name="asm_demo")
        set_work(assy)
        comp, status1 = add_component(assy, plate_path, NXOpen.Point3d(0.0, 0.0, 0.0))
        print("ADD_PLATE_OK comp=" + str(comp))
        comp2, status2 = add_component(assy, pin_path, NXOpen.Point3d(24.0, 0.0, 6.0))
        print("ADD_PIN_OK comp2=" + str(comp2))
        root = assy.ComponentAssembly.RootComponent
        comps = root.GetChildren()
        print("COMPONENTS=" + str(len(comps)))
    assy = None
    stage("add_components", s2)

    save()
    stage_finish("TEST04_DONE", "TEST04")


if __name__ == "__main__":
    main()
