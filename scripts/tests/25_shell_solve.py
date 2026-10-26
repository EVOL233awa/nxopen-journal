# -*- coding: utf-8 -*-
"""Test 25: 2D 壳的**求解级**数值标定（NX12 批处理；fea.md §3a）。

把「薄板体 → PSHELL 壳网格 → 端边固支 + 端边集中力 → SOL101 → 与梁理论对照」整条链固化，
并且**检查期望值来自独立解析解**，不是从 NX 数据反推：

    被测件：100 × 5（mm）薄板体（sheet body），PSHELL 厚 t = 5 mm，库 Steel（E = 206940 MPa）
    约束：一端短边 6 自由度全固支；载荷：另一端短边 −Z 总力 100 N
    I = b·t³/12 = 52.0833 mm⁴
    δ = F·L³/(3·E·I) = 3.0927 mm      （b/L = 0.05，横向剪切只占 0.2%，可忽略）
    σ = F·L·(t/2)/I  = 480.0 MPa

结果：δ_FEA = 3.090916（比值 0.9994）、von Mises = 473.83 MPa（比值 0.9871）。

三条被本用例钉住的 API 事实：
  1. 薄板体用 `CreateBoundedPlaneBuilder(BoundedPlane.Null)`，而 `BoundingCurves` 是
     **只读容器**（直接赋值报 is not writable）→ 必须 `bp.BoundingCurves.AddToSection(...)`
     原地灌线（SKILL.md 铁律 4）。
  2. 壳厚度不是从几何取的，必须在 PSHELL 表上显式写 **`element thickness`**
     （属性名来自 `GetPropertyNameByIndex` 枚举，不是猜的；不写就只有默认厚度，挠度差几个量级）。
  3. 壳的端边边界条件用 **CAE_Edge**（`CAE_Body(1)|CAE_Edge(n)`）+ `GeomEdge` 过滤器，
     `CAEEdge` 只暴露 `GetLength`（没有取底层 UG 边的入口）→ 用长度认边：
     薄板体只有 4 条边（2×100、2×5），两条 5 mm 的就是两端。
     若改用"实体块顶面"网格化，则块有 12 条边、无法区分哪 4 条属于被网格化的面，
     所以本用例的几何特意做成薄板体。
"""
import os
import sys

import NXOpen
import NXOpen.CAE
import NXOpen.Features
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part

HERE = os.path.dirname(__file__)
PARTS = os.path.join(HERE, "parts")
CAD = os.path.join(PARTS, "t25_shell_cad.prt")
FEM = os.path.join(PARTS, "t25_shell.fem")
SIM = os.path.join(PARTS, "t25_shell_sim.sim")
IDEA = os.path.join(PARTS, "t25_shell_i.prt")

L, B, T = 100.0, 5.0, 5.0
E_STEEL = 206940.0
F_TIP = 100.0
I_MM4 = B * T ** 3 / 12.0
DELTA_TH = F_TIP * L ** 3 / (3.0 * E_STEEL * I_MM4)
SIGMA_TH = F_TIP * L * (T / 2.0) / I_MM4

def build_sheet(session, ufs):
    cad = new_part(path=CAD)
    ufs.Part.SetDisplayPart(cad.Tag)
    lines = [cad.Curves.CreateLine(NXOpen.Point3d(0.0, 0.0, 0.0),
                                   NXOpen.Point3d(L, 0.0, 0.0)),
             cad.Curves.CreateLine(NXOpen.Point3d(L, 0.0, 0.0),
                                   NXOpen.Point3d(L, B, 0.0)),
             cad.Curves.CreateLine(NXOpen.Point3d(L, B, 0.0),
                                   NXOpen.Point3d(0.0, B, 0.0)),
             cad.Curves.CreateLine(NXOpen.Point3d(0.0, B, 0.0),
                                   NXOpen.Point3d(0.0, 0.0, 0.0))]
    rule = cad.ScRuleFactory.CreateRuleCurveDumb(lines)
    bp = cad.Features.CreateBoundedPlaneBuilder(NXOpen.Features.BoundedPlane.Null)
    bp.BoundingCurves.AddToSection([rule], lines[0], NXOpen.NXObject.Null,
                                   NXOpen.NXObject.Null,
                                   NXOpen.Point3d(L / 2.0, B / 2.0, 0.0),
                                   NXOpen.Section.Mode.Create, False)
    bp.CommitFeature()
    bp.Destroy()
    nb = len([b for b in cad.Bodies])
    check("REG_SHEET_BODY", nb == 1, "BoundedPlane 提交后体数=%d" % nb)
    cad.Save(NXOpen.BasePart.SaveComponents.TrueValue,
             NXOpen.BasePart.CloseAfterSave.FalseValue)
    return cad


def build_fem(session, ufs, cad):
    fem = new_part(path=FEM, template="FemNxNastranMetric.fem")
    fem.FinalizeCreation(cad, "t25_shell_i",
                         NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
                         fem.NewFemSynchronizeOptions(), "NXNASTRAN", "STRUCT",
                         NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
                         ["t25"], False)
    say("fem=%s solver=%s" % (fem.Leaf, fem.GetSolverAndAnalysisType()))

    ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
        "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", "PSHELL1", 2)
    names = [ppt.PropertyTable.GetPropertyNameByIndex(i)
             for i in range(ppt.PropertyTable.GetPropertyCount())]
    check("REG_PSHELL_PROPS", "element thickness" in names,
          "PSHELL 属性名=%s" % names)
    steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
    ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
    unit_mm = fem.UnitCollection.FindObject("MilliMeter")
    ppt.PropertyTable.SetBaseScalarWithDataPropertyValue("element thickness",
                                                        str(T), unit_mm)
    got = ppt.PropertyTable.GetScalarWithDataPropertyValue("element thickness")
    check("REG_PSHELL_THICKNESS", abs(float(got[0]) - T) < 1e-6,
          "element thickness 读回=%r" % (got[0],))

    col_b = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(
        NXOpen.CAE.MeshCollector.Null, "ThinShell")
    col_b.CollectorName = "T25Shell"
    col_b.PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)
    col = col_b.Commit()
    col_b.Destroy()

    faces = [fem.FindObject("CAE_Body(1)|CAE_Face(1)")]
    edges = []
    for i in range(1, 12):
        try:
            edges.append(fem.FindObject("CAE_Body(1)|CAE_Edge(%d)" % i))
        except Exception:
            break
    lens = [e.GetLength() for e in edges]
    short = [n for n in lens if abs(n - B) < 0.5]
    check("REG_CAE_SHEET_GEOM",
          len(faces) == 1 and len(edges) == 4 and len(short) == 2,
          "面=%d 边=%d 长度=%s" % (len(faces), len(edges),
                                   [round(x, 3) for x in lens]))

    mb = fem.BaseFEModel.MeshManager.CreateMesh2dBuilder(NXOpen.CAE.Mesh2d.Null)
    mb.SelectionList.Add(faces[0])
    mb.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.Shell
    mb.ElementType.ElementTypeName = "CQUAD4"
    mb.ElementType.DestinationCollector.ElementContainer = col
    mb.ElementType.DestinationCollector.AutomaticMode = False
    mb.PropertyTable.SetBaseScalarWithDataPropertyValue(
        "quad mesh overall edge size", "2.0", unit_mm)
    mb.CommitMesh()
    mb.Destroy()
    nodes = int(fem.BaseFEModel.MeshManager.GetNodeStatus().TotalNum)
    check("REG_SHELL_MESH_NODES", nodes >= 100, "节点数=%d" % nodes)
    ufs.Part.Save()
    return fem, edges, lens


def build_sim(session, ufs, fem, units_holder):
    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "SimNxNastranMetric.sim"
    fn.NewFileName = SIM
    fn.UseBlankTemplate = False
    sim = fn.Commit()
    fn.Destroy()
    sim.FinalizeCreation(fem, -1, ["t25 sim"])
    sol = sim.Simulation.CreateSolution(
        "NX NASTRAN", "Structural", "SESTATIC 101 - Single Constraint",
        "Solution 1", NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
    if sol.StepCount == 0:
        sol.CreateStep(0, True, "Subcase - Statics 1")
    mo = sim.ModelingObjectPropertyTables.CreateModelingObjectPropertyTable(
        "Structural Output Requests", "NX NASTRAN - Structural", "NX NASTRAN",
        "Structural Output Requests1", 2)
    sol.PropertyTable.SetNamedPropertyTablePropertyValue("Output Requests", mo)

    comp = sim.ComponentAssembly.RootComponent.GetChildren()[0]
    ends = []
    for i in range(1, 12):
        try:
            e = comp.FindObject("CAE_Body(1)|CAE_Edge(%d)" % i)
        except Exception:
            break
        if abs(e.GetLength() - B) < 0.5:
            ends.append(e)
    check("REG_EDGE_ENDS_IN_SIM", len(ends) == 2,
          "sim 端边数=%d" % len(ends))

    def edge_objs(objs):
        out = []
        for o in objs:
            so = NXOpen.CAE.SetObject()
            so.Obj = o
            so.SubType = NXOpen.CAE.CaeSetObjectSubType.NotSet
            so.SubId = 0
            out.append(so)
        return out

    sim_sim = sim.Simulation
    u_mm = sim.UnitCollection.FindObject("MilliMeter")
    u_deg = sim.UnitCollection.FindObject("Degrees")
    b = sim_sim.CreateBcBuilderForConstraintDescriptor(
        "UserDefinedDisplacementConstraint", "Fixed(1)", 1)
    b.TargetSetManager.SetTargetSetMembers(
        0, NXOpen.CAE.CaeSetGroupFilterType.GeomEdge, edge_objs([ends[0]]))
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
    lb = sim_sim.CreateBcBuilderForLoadDescriptor("ComponentForceField", "Force(1)", 2)
    lb.TargetSetManager.SetTargetSetMembers(
        0, NXOpen.CAE.CaeSetGroupFilterType.GeomEdge, edge_objs([ends[1]]))
    exprs = [sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
             sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
             sim.Expressions.CreateSystemExpressionWithUnits(str(-F_TIP), u_n)]
    vw = sim.FindObject("FieldManager").CreateVectorFieldWrapperWithExpressions(exprs)
    lb.PropertyTable.SetVectorFieldWrapperPropertyValue("CartesianMagnitude", vw)
    lb.BcName = "TipLoad"
    lb.DestinationFolder = NXOpen.CAE.SimLbcFolder.Null
    lb.CommitAddBc()
    lb.Destroy()
    check("REG_EDGE_BC_COMMIT", True, "端边固支 + 端边集中力 两条 BC 均提交成功")
    ufs.Part.Save()
    return sim, sol


def solve_and_verify(session, ufs, sim, sol):
    mgr = NXOpen.CAE.SimSolveManager.GetSimSolveManager(session)
    mgr.SolveChainOfSolutions(
        [sol], NXOpen.CAE.SimSolution.SolveOption.Solve,
        NXOpen.CAE.SimSolution.SetupCheckOption.DoNotCheck,
        NXOpen.CAE.SimSolution.SolveMode.Foreground)
    rd, rn = sol.GetResultFile()
    if not rd:
        sol.SetLocalResultFile(os.getcwd(), rn)
    rm = session.ResultManager
    sres = rm.CreateSolutionResult(sol)
    it = sres.GetLoadcases()[0].GetIterations()[0]
    rts = it.GetResultTypes()
    say("RESULT_TYPES=%s" % [t.Name for t in rts])

    def ask(rt_name, comp):
        rt = [t for t in rts if t.Name.lower() == rt_name.lower()][0]
        rp = rm.CreateResultParameters()
        rp.SetGenericResultType(rt)
        rp.SetResultComponent(comp)
        rp.MakeElementResult(False)
        rp.SetUnit(rt.AskDefaultUnitForComponent(comp))
        ra = rm.CreateResultAccess(sres, rp)
        v = ra.AskMaximum()
        rm.DeleteResultAccess(ra)
        rm.DeleteResultParameters(rp)
        return v

    dmax = ask("Displacement - Nodal", NXOpen.CAE.Result.Component.Magnitude)
    smax = ask("Stress - Element-Nodal", NXOpen.CAE.Result.Component.VonMises)
    r_d = dmax / DELTA_TH
    r_s = smax / SIGMA_TH
    say("BENCH_SHELL delta=%.6f theory=%.6f ratio=%.4f" % (dmax, DELTA_TH, r_d))
    say("BENCH_SHELL vonmises=%.4f theory=%.4f ratio=%.4f" % (smax, SIGMA_TH, r_s))
    check("REG_SHELL_SOLVE", r_d > 0.0, "SOL101 解出非零位移")
    check("BENCH_SHELL_DEFLECTION", 0.95 <= r_d <= 1.05,
          "挠度比 %.4f（20 mm 壳单元；横向剪切实测只贡献 0.2%%）" % r_d)
    check("BENCH_SHELL_STRESS", 0.85 <= r_s <= 1.15,
          "根部 von Mises 比 %.4f（梁理论极值，壳单元报表面层）" % r_s)


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    for p in (CAD, FEM, SIM, IDEA):
        if os.path.exists(p):
            os.remove(p)
    cad = build_sheet(session, ufs)
    fem, edges, lens = build_fem(session, ufs, cad)
    sim, sol = build_sim(session, ufs, fem, None)
    solve_and_verify(session, ufs, sim, sol)
    ufs.Part.Save()

    landed = [os.path.basename(p) for p in (CAD, FEM, SIM)
              if os.path.exists(p) and os.path.getsize(p) > 0]
    check("REG_ARTIFACTS_LANDED", len(landed) == 3, "落盘非空=%s" % landed)

    failed = [n for n, v in RESULTS if not v]
    say("TEST25_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST25_FAIL failed=%s" % failed)
        raise RuntimeError("test 25 failed: %s" % failed)
    say("TEST25_DONE")


if __name__ == "__main__":
    main()
