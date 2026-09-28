# -*- coding: utf-8 -*-
# Test J: assembly mating constraints (Touch), occurrence faces via
#         FindOccurrence, constraint network solve, DOF query, refset switch.
# Covers: ComponentAssembly.Positioner, BeginAssemblyConstraints,
#         CreateConstraint(True), ComponentConstraint.ConstraintType,
#         CreateConstraintReference(movable comp, occurrence face),
#         Network.Solve, Component.GetDegreesOfFreedom,
#         ComponentAssembly.ReplaceReferenceSet.
# Known limits (NX12 Python wrapper, tested): Constraint.Type property is
#         read-only (use ConstraintType); Distance offset setter is
#         "Not yet implemented" (position via AddComponent placement or
#         Touch pairs instead).
import os
import sys

import NXOpen
import NXOpen.Assemblies
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.assembly import add_component, find_proto_face, touch_pair
from nxlib.modeling import block
from nxlib.session import new_part, save, set_work
from nxlib.testing import stage


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    for stale in ("asmc_base.prt", "asmc_pin.prt", "asmc_assy.prt"):
        sp = os.path.abspath(stale)
        if os.path.exists(sp):
            os.remove(sp)

    state = {}

    def s1():
        base = new_part(name="asmc_base")
        set_work(base)
        blk_base = block(base, NXOpen.Point3d(0.0, 0.0, 0.0), "120", "80", "10")
        blk_base.SetName("BaseBlock")
        ufs.Part.Save()
        pin = new_part(name="asmc_pin")
        set_work(pin)
        blk_pin = block(pin, NXOpen.Point3d(0.0, 0.0, 0.0), "12", "12", "40")
        blk_pin.SetName("PinBlock")
        ufs.Part.Save()
        state["base"] = base
        state["pin"] = pin
        state["base_top"] = find_proto_face(base, "Z", 1)
        state["pin_bottom"] = find_proto_face(pin, "Z", -1)
        print("PROTO_FACES=" + str(state["base_top"] is not None) + "/" +
              str(state["pin_bottom"] is not None))
    stage("components", s1)

    def s2():
        assy = new_part(name="asmc_assy")
        set_work(assy)
        ufs.Part.SetDisplayPart(assy.Tag)
        c1, st1 = add_component(assy, state["base"].FullPath, NXOpen.Point3d(0.0, 0.0, 0.0))
        c2, st2 = add_component(assy, state["pin"].FullPath, NXOpen.Point3d(40.0, 30.0, 30.0))
        state["assy"] = assy
        state["c1"] = c1
        state["c2"] = c2
        print("COMPS=" + str(len(assy.ComponentAssembly.RootComponent.GetChildren())))
    stage("assembly", s2)

    def s3():
        err = touch_pair(session, state["assy"], state["c2"], state["pin_bottom"],
                         state["c1"], state["base_top"], "PinOnBase_Touch")
        print("SOLVE_ERR=" + str(err))
    stage("touch_constraint", s3)

    def s4():
        pos2 = state["c2"].GetPosition()
        dof = state["c2"].GetDegreesOfFreedom()
        n_dof = dof.NumTranslational + dof.NumRotational
        print("PIN_POS_Z=%.3f" % pos2[0].Z)
        print("PIN_DOF=" + str(n_dof))
        # pin placed at z=30 (bottom face), must be moved onto base top z=10
        if abs(pos2[0].Z - 10.0) < 1e-6:
            print("CONSTRAINT_PASS")
        else:
            print("CONSTRAINT_FAIL")
        ca = state["assy"].ComponentAssembly
        ca.ReplaceReferenceSet(state["c2"], "Entire Part")
        print("REFSET=" + state["c2"].ReferenceSet)
    stage("verify_and_refset", s4)

    ufs.Part.Save()
    print("ASM_CONSTR_DONE")


if __name__ == "__main__":
    main()
