# -*- coding: utf-8 -*-
# Test I: FEA linear static (NX Nastran SOL 101) full chain, self-verifying.
# Cantilever benchmark L=100 W=10 H=20 steel, fixed end, tip face force -500 N.
# Hand calc (E=206940): delta = F*L^3/(3*E*I) = 0.1208 mm
# Acceptance: FEA delta within [theory*0.9, theory*1.4] (shear + mesh effects)
# Covers: FileNew fem template, FemPart.FinalizeCreation, CAE body/face enum,
#         PSOLID + Steel library, solid mesh collector, CTETRA(10) mesh,
#         FileNew sim template, SimPart.FinalizeCreation, CreateSolution
#         SESTATIC 101, Structural Output Requests, UserDefinedDisplacement
#         constraint (all DOF=0), ComponentForceField (total, Newton),
#         SimSolveManager.SolveChainOfSolutions, ResultManager post (max disp
#         magnitude + von Mises), hand-calc verification culture.
import os
import NXOpen
import NXOpen.Features
import NXOpen.CAE
import NXOpen.Fields
import NXOpen.UF


import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import stage

L, W, H, F = 100.0, 10.0, 20.0, 500.0
E_STEEL = 206940.0
I = W * H ** 3 / 12.0
DELTA_THEORY = F * L ** 3 / (3.0 * E_STEEL * I)


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    for stale in ("bench_cad.prt", "bench.fem", "bench_i.prt", "bench_sim.sim",
                  "bench_sim-solution_1.dat", "bench_sim-solution_1.f06",
                  "bench_sim-solution_1.log", "bench_sim-solution_1.op2"):
        sp = os.path.abspath(stale)
        if os.path.exists(sp):
            os.remove(sp)

    state = {}

    def s1():
        fn = session.Parts.FileNew()
        fn.Units = NXOpen.Part.Units.Millimeters
        fn.TemplateFileName = "model-plain-1-mm-template.prt"
        fn.NewFileName = "bench_cad.prt"
        fn.UseBlankTemplate = False
        part = fn.Commit()
        fn.Destroy()
        session.Parts.SetWork(part)
        blk = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, -W / 2.0, -H / 2.0),
                                str(L), str(W), str(H))
        blk.CommitFeature()
        blk.Destroy()
        ufs.Part.Save()
        state["cad"] = part

        fn = session.Parts.FileNew()
        fn.Units = NXOpen.Part.Units.Millimeters
        fn.TemplateFileName = "FemNxNastranMetric.fem"
        fn.NewFileName = "bench.fem"
        fn.UseBlankTemplate = False
        fem = fn.Commit()
        fn.Destroy()
        fem.FinalizeCreation(part, "bench_i",
                             NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
                             fem.NewFemSynchronizeOptions(), "NXNASTRAN", "STRUCT",
                             NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
                             ["bench"], False)
        state["fem"] = fem
        state["fe"] = fem.BaseFEModel
        state["mm"] = state["fe"].MeshManager

        ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
            "PSOLID", "NX NASTRAN - Structural", "NX NASTRAN", "PSOLID1", 2)
        steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
        ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
        bld = state["mm"].CreateCollectorBuilder(NXOpen.CAE.MeshCollector.Null,
                                                 "Solid")
        bld.CollectorName = "SteelSolid"
        bld.PropertyTable.SetNamedPropertyTablePropertyValue("Solid Property", ppt)
        state["collector"] = bld.Commit()
        bld.Destroy()

        body = fem.FindObject("CAE_Body(1)")
        b = state["mm"].CreateMesh3dTetBuilder(NXOpen.CAE.Mesh3d.Null)
        b.SelectionList.Add(body)
        b.ElementType.ElementDimension = \
            NXOpen.CAE.ElementTypeBuilder.ElementType.FreeSolid
        b.ElementType.ElementTypeName = "CTETRA(10)"
        b.ElementType.DestinationCollector.ElementContainer = state["collector"]
        b.ElementType.DestinationCollector.AutomaticMode = False
        unit_mm = fem.UnitCollection.FindObject("MilliMeter")
        b.PropertyTable.SetBaseScalarWithDataPropertyValue(
            "quad mesh overall edge size", "4", unit_mm)
        b.CommitMesh()
        b.Destroy()
        ufs.Part.Save()
        print("NODES=" + str(state["fe"].MeshManager.GetNodeStatus()))
    stage("fem_build", s1)

    def s2():
        fem = state["fem"]
        idx_dir = {}
        for i in range(1, 60):
            try:
                f = fem.FindObject("CAE_Body(1)|CAE_Face(%d)" % i)
            except Exception:
                break
            ug = f.GetUgfaces()
            if len(ug) == 0:
                continue
            d = ufs.Modeling.AskFaceData(ug[0].Tag)
            idx_dir[i] = (d[0], d[2])
        state["idx_dir"] = idx_dir
        print("FACES=" + str(len(idx_dir)))
    stage("face_classify", s2)

    def s3():
        fn = session.Parts.FileNew()
        fn.Units = NXOpen.Part.Units.Millimeters
        fn.TemplateFileName = "SimNxNastranMetric.sim"
        fn.NewFileName = "bench_sim.sim"
        fn.UseBlankTemplate = False
        sim = fn.Commit()
        fn.Destroy()
        sim.FinalizeCreation(state["fem"], -1, ["bench sim"])
        state["sim"] = sim
        sol = sim.Simulation.CreateSolution(
            "NX NASTRAN", "Structural", "SESTATIC 101 - Single Constraint",
            "Solution 1", NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
        if sol.StepCount == 0:
            sol.CreateStep(0, True, "Subcase - Statics 1")
        mo = sim.ModelingObjectPropertyTables.CreateModelingObjectPropertyTable(
            "Structural Output Requests", "NX NASTRAN - Structural", "NX NASTRAN",
            "Structural Output Requests1", 2)
        sol.PropertyTable.SetNamedPropertyTablePropertyValue("Output Requests", mo)
        state["sol"] = sol
        comp = sim.ComponentAssembly.RootComponent.GetChildren()[0]
        occ = []
        for i in range(1, len(state["idx_dir"]) + 1):
            occ.append(comp.FindObject("CAE_Body(1)|CAE_Face(%d)" % i))
        state["occ"] = occ
        print("OCC=" + str(len(occ)))
    stage("sim_build", s3)

    def s4():
        sim_sim = state["sim"].Simulation
        sim = state["sim"]
        fixed_faces, tip_faces = [], []
        for i, f in enumerate(state["occ"], start=1):
            ftype, dirv = state["idx_dir"][i]
            if ftype == 22 and abs(dirv[0]) > 0.9:
                if dirv[0] < 0:
                    fixed_faces.append(f)
                else:
                    tip_faces.append(f)
        print("FIX=" + str(len(fixed_faces)) + " TIP=" + str(len(tip_faces)))

        def face_objs(faces):
            objs = []
            for f in faces:
                so = NXOpen.CAE.SetObject()
                so.Obj = f
                so.SubType = NXOpen.CAE.CaeSetObjectSubType.NotSet
                so.SubId = 0
                objs.append(so)
            return objs

        b = sim_sim.CreateBcBuilderForConstraintDescriptor(
            "UserDefinedDisplacementConstraint", "Fixed(1)", 1)
        b.TargetSetManager.SetTargetSetMembers(
            0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace,
            face_objs(fixed_faces))
        u_mm = sim.UnitCollection.FindObject("MilliMeter")
        u_deg = sim.UnitCollection.FindObject("Degrees")
        for dof, unit in (("DOF1", u_mm), ("DOF2", u_mm), ("DOF3", u_mm),
                          ("DOF4", u_deg), ("DOF5", u_deg), ("DOF6", u_deg)):
            fe_ = b.PropertyTable.GetScalarFieldPropertyValue(dof)
            fe_.EditFieldExpression("0", unit, [], False)
            b.PropertyTable.SetScalarFieldPropertyValue(dof, fe_)
        b.BcName = "FixedEnd"
        b.DestinationFolder = NXOpen.CAE.SimLbcFolder.Null
        b.CommitAddBc()
        b.Destroy()

        u_n = sim.UnitCollection.FindObject("Newton")
        lb = sim_sim.CreateBcBuilderForLoadDescriptor(
            "ComponentForceField", "Force(1)", 2)
        lb.TargetSetManager.SetTargetSetMembers(
            0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace,
            face_objs(tip_faces))
        exprs = [sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
                 sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
                 sim.Expressions.CreateSystemExpressionWithUnits(str(-F), u_n)]
        vw = sim.FindObject("FieldManager").CreateVectorFieldWrapperWithExpressions(
            exprs)
        lb.PropertyTable.SetVectorFieldWrapperPropertyValue("CartesianMagnitude", vw)
        lb.BcName = "TipLoad"
        lb.DestinationFolder = NXOpen.CAE.SimLbcFolder.Null
        lb.CommitAddBc()
        lb.Destroy()
    stage("boundary_conditions", s4)

    def s5():
        ufs.Part.Save()
        mgr = NXOpen.CAE.SimSolveManager.GetSimSolveManager(session)
        mgr.SolveChainOfSolutions(
            [state["sol"]],
            NXOpen.CAE.SimSolution.SolveOption.Solve,
            NXOpen.CAE.SimSolution.SetupCheckOption.DoNotCheck,
            NXOpen.CAE.SimSolution.SolveMode.Foreground)
    stage("solve", s5)

    def s6():
        sol = state["sol"]
        rd, rn = sol.GetResultFile()
        if not rd:
            sol.SetLocalResultFile(os.getcwd(), rn)
        rm = session.ResultManager
        sres = rm.CreateSolutionResult(sol)
        it = sres.GetLoadcases()[0].GetIterations()[0]
        rts = it.GetResultTypes()

        def ask(rt_name, comp):
            rt = [t for t in rts if t.Name.lower() == rt_name.lower()][0]
            rp = rm.CreateResultParameters()
            rp.SetGenericResultType(rt)
            rp.SetResultComponent(comp)
            rp.MakeElementResult(False)
            rp.SetUnit(rt.AskDefaultUnitForComponent(comp))
            ra = rm.CreateResultAccess(sres, rp)
            vmax = ra.AskMaximum()
            rm.DeleteResultAccess(ra)
            rm.DeleteResultParameters(rp)
            return vmax

        dmax = ask("Displacement - Nodal", NXOpen.CAE.Result.Component.Magnitude)
        smax = ask("Stress - Element-Nodal", NXOpen.CAE.Result.Component.VonMises)
        print("FEA_DELTA=%.6f" % dmax)
        print("FEA_VONMISES=%.6f" % smax)
        print("THEORY_DELTA=%.6f" % DELTA_THEORY)
        ratio = dmax / DELTA_THEORY
        print("RATIO=%.4f" % ratio)
        if 0.9 <= ratio <= 1.4:
            print("BENCH_PASS")
        else:
            print("BENCH_FAIL")
    stage("post_verify", s6)

    ufs.Part.Save()
    print("FEA_DONE")


if __name__ == "__main__":
    main()
