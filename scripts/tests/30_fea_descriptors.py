# -*- coding: utf-8 -*-
"""Test 30: FEA 解算方案家族与 BC 描述符绑定（NX12 批处理，2026-09-22；fea.md §6a）。

fea.md §6a 此前自己标注"本节的描述符结论**未纳入检查**，只有实测记录"——本用例把它
升格成会失败的检查。守的是四条结论，其中第一条在本轮取证时**被修正**：

A) 解算方案描述符真名只能从模板抽，实测全集 11 个（6 个 Nastran 变体模板各含同一套；
   `SimNxNastranDesign*.sim` 是 0，属另一种模板，不算"全集"）。
   ⚠ 期望清单的**项数**另用独立字面量钉住（REG_DESCRIPTOR_LIST_INTACT）：清单被削掉一项时
   REG_TEMPLATE_DESCRIPTORS 只会少检一项、静默保持通过 —— 覆盖清单型断言看不见自己的覆盖缩水。
   这是本轮反向验证时实测到的误判通过，不是推测（删 `SEMFREQ 111 - Modal FRF` 后判定结果仍是 PASS）。

B) 显示名与描述符名**不是一回事**：
   `SESTATIC 101 - Single Constraint` → 'SOL 101 Linear Statics - Global Constraints'
   `SEMODES 103`                     → 'SOL 103 Real Eigenvalues'
   垃圾名（`SEMODAL 103 - Normal Modes`）报 `Error number: 1775003`，**错误文本里没有任何
   可分辨的信息**，所以判据只能是"正对照能建 + 真名来自模板"，不能靠错误消息。

C) **BC 描述符的有效性跟"当前激活的解算方案"绑定，且"当前激活方案"会被新建方案带走**
   （本轮实测修正）：建完第二个（模态）方案后，`sim.Simulation.ActiveSolution` **指向的
   就是那个模态方案**，此时 `ComponentForceField` 报 `Invalid LBC neutral name`；
   显式 `sim.Simulation.ActiveSolution = <静态方案>` 后同一个名字即可用。
   旧文档只写了"切到模态方案后报错"，没说"新建方案本身就会把激活方案切过去"，
   读者按字面理解会以为默认激活一直是静态方案 —— 检查自己走一遍
   「模态激活 → 报错 → 回切静态 → 可用」的受控 A/B 把这条钉住。

D) 无效中性名清单抽样（全部 `Invalid LBC neutral name`，在静态方案激活下测）：
   `FixedConstraint` / `PinnedConstraint` / `PressureField`；
   有效对照：`UserDefinedDisplacementConstraint`（约束）、`ComponentForceField`（载荷）。
   负向断言必须与正向对照同轮出现，否则"名字无效"与"整个功能不可用"分辨不开。

异常抛点已实测：描述符错误抛在 **builder 创建那一刻**
（`CreateBcBuilderFor{Load,Constraint}Descriptor`），不是 Commit。
"""
import glob
import os
import re
import sys

import NXOpen
import NXOpen.CAE
import NXOpen.Features
import NXOpen.UF


import sys

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
CAD = os.path.join(PARTS, "t30_cad.prt")
FEM = os.path.join(PARTS, "t30.fem")
SIM = os.path.join(PARTS, "t30_sim.sim")
IDEA = os.path.join(PARTS, "t30_i.prt")
NX_HOME = os.environ.get("NX_HOME", r"D:\UG-NX12")

L, B, T = 100.0, 5.0, 5.0
DESCR_SNIPPET = rb"[A-Z]{2,10} 1[0-9]{2} - [ -~]{5,45}"
EXPECT_DESCRIPTORS = [
    "SESTATIC 101 - Single Constraint",
    "SESTATIC 101 - Multi Constraint",
    "SESTATIC 101 - Adaptive",
    "SESTATIC 101 - Superelement",
    "NLSTATIC 106 - Single Constraint",
    "NLSTATIC 106 - Multi Constraint",
    "SEMODES 103 - Flexible Body",
    "SEMODES 103 - Response Simulation",
    "SEMODES 103 - Superelement",
    "SEDFREQ 108 - Direct FRF",
    "SEMFREQ 111 - Modal FRF",
]
EXPECT_DESCRIPTOR_COUNT = 11   # 独立字面量：与下列清单分开数，清单被削项时才能变成 FAIL
STATIC_NAME = "SESTATIC 101 - Single Constraint"
MODAL_NAME = "SEMODES 103"
BOGUS_NAME = "SEMODAL 103 - Normal Modes"
EXPECT_STATIC_DISPLAY = "SOL 101 Linear Statics - Global Constraints"
EXPECT_MODAL_DISPLAY = "SOL 103 Real Eigenvalues"

def extract_descriptors():
    files = sorted(glob.glob(os.path.join(NX_HOME, "SIMULATION", "templates",
                                         "SimNxNastran*.sim")))
    per_file = {}
    for p in files:
        raw = open(p, "rb").read()
        got = set(m.group().decode("latin-1")
                  for m in re.finditer(DESCR_SNIPPET, raw))
        per_file[os.path.basename(p)] = got
    return per_file


def build_fem(session, ufs):
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
    cad.Save(NXOpen.BasePart.SaveComponents.TrueValue,
             NXOpen.BasePart.CloseAfterSave.FalseValue)

    fem = new_part(path=FEM, template="FemNxNastranMetric.fem")
    fem.FinalizeCreation(cad, "t30_i",
                         NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
                         fem.NewFemSynchronizeOptions(), "NXNASTRAN", "STRUCT",
                         NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
                         ["t30"], False)
    ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
        "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", "PSHELL1", 2)
    steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
    ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
    unit_mm = fem.UnitCollection.FindObject("MilliMeter")
    ppt.PropertyTable.SetBaseScalarWithDataPropertyValue("element thickness",
                                                         str(T), unit_mm)
    col_b = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(
        NXOpen.CAE.MeshCollector.Null, "ThinShell")
    col_b.CollectorName = "T30Shell"
    col_b.PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)
    col = col_b.Commit()
    col_b.Destroy()
    face = fem.FindObject("CAE_Body(1)|CAE_Face(1)")
    mb = fem.BaseFEModel.MeshManager.CreateMesh2dBuilder(NXOpen.CAE.Mesh2d.Null)
    mb.SelectionList.Add(face)
    mb.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.Shell
    mb.ElementType.ElementTypeName = "CQUAD4"
    mb.ElementType.DestinationCollector.ElementContainer = col
    mb.ElementType.DestinationCollector.AutomaticMode = False
    mb.PropertyTable.SetBaseScalarWithDataPropertyValue(
        "quad mesh overall edge size", "5.0", unit_mm)
    mb.CommitMesh()
    mb.Destroy()
    nodes = int(fem.BaseFEModel.MeshManager.GetNodeStatus().TotalNum)
    say("NODES=%d" % nodes)
    ufs.Part.Save()
    return fem


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    for p in (CAD, FEM, SIM, IDEA):
        if os.path.exists(p):
            os.remove(p)

    # ---- A) 模板里的描述符全集（结论取自 NX 自己的模板，不是猜） ----
    per_file = extract_descriptors()
    nastran = {k: v for k, v in per_file.items() if "Design" not in k}
    union = set()
    for v in per_file.values():
        union |= v
    check("REG_TEMPLATE_FILES", len(per_file) >= 6 and len(nastran) >= 6,
          "SimNxNastran*.sim 共 %d 个，其中非 Design %d 个" % (len(per_file), len(nastran)))
    check("REG_DESCRIPTOR_LIST_INTACT",
          len(EXPECT_DESCRIPTORS) == EXPECT_DESCRIPTOR_COUNT,
          "期望清单 %d 项（钉住 %d 项；不相等说明断言覆盖被削，后续两条会静默变宽）"
          % (len(EXPECT_DESCRIPTORS), EXPECT_DESCRIPTOR_COUNT))
    missing_union = [n for n in EXPECT_DESCRIPTORS if n not in union]
    check("REG_TEMPLATE_DESCRIPTORS", not missing_union,
          "并集缺失=%s；每个非 Design 模板都含同一套 11 个=%s"
          % (missing_union,
             all(set(EXPECT_DESCRIPTORS) <= v for v in nastran.values())))
    eng = per_file.get("SimNxNastranEnglish.sim", set())
    missing_eng = [n for n in EXPECT_DESCRIPTORS if n not in eng]
    check("REG_TEMPLATE_ENGLISH_FILE", not missing_eng,
          "SimNxNastranEnglish.sim 缺失=%s（文档点名的就是这一个）" % missing_eng)

    fem = build_fem(session, ufs)

    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "SimNxNastranMetric.sim"
    fn.NewFileName = SIM
    fn.UseBlankTemplate = False
    sim = fn.Commit()
    fn.Destroy()
    sim.FinalizeCreation(fem, -1, ["t30 sim"])
    simsim = sim.Simulation

    # ---- B) 解算方案：真名 / 显示名 / 垃圾名 ----
    def mk_solution(name, label):
        s = simsim.CreateSolution(
            "NX NASTRAN", "Structural", name, label,
            NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
        if s.StepCount == 0:
            s.CreateStep(0, True, "Subcase")
        return s

    stat = mk_solution(STATIC_NAME, "SolStatic")
    check("REG_SOL_STATIC_DISPLAY",
          stat.SolverType == "NX NASTRAN"
          and stat.GetDisplayNameOfSolutionType() == EXPECT_STATIC_DISPLAY,
          "SolverType=%r display=%r" % (stat.SolverType,
                                        stat.GetDisplayNameOfSolutionType()))
    mod = mk_solution(MODAL_NAME, "SolModal")
    check("REG_SOL_MODAL_DISPLAY",
          mod.GetDisplayNameOfSolutionType() == EXPECT_MODAL_DISPLAY,
          "display=%r（裸 'SEMODES 103' 就是真名，没有 ' - Normal Modes' 后缀）"
          % (mod.GetDisplayNameOfSolutionType(),))
    bogus_msg = ""
    try:
        mk_solution(BOGUS_NAME, "SolBogus")
        check("REG_SOL_BOGUS_REJECTED", False, "垃圾名竟然建成功了")
    except Exception as exc:
        bogus_msg = str(exc)
        check("REG_SOL_BOGUS_REJECTED", "1775003" in bogus_msg,
              "异常原文=%r（无任何可分辨信息，故判据只能靠正对照+模板抽名）" % bogus_msg)

    # ---- C) 受控 A/B：激活方案决定 BC 描述符是否有效 ----
    def set_active(sol):
        simsim.ActiveSolution = sol
        return simsim.ActiveSolution.Tag == sol.Tag

    def new_load_builder(name, label):
        return simsim.CreateBcBuilderForLoadDescriptor(name, label, 2)

    def new_con_builder(name, label):
        return simsim.CreateBcBuilderForConstraintDescriptor(name, label, 1)

    # C1) 新建方案会把"当前激活方案"带走 —— 旧文档没写这条，是读者踩坑的真因
    check("REG_ACTIVE_FOLLOWS_NEW_SOLUTION",
          simsim.ActiveSolution.Tag == mod.Tag,
          "建完模态方案后激活方案指向它=%s（modal tag=%s / static tag=%s）"
          % (simsim.ActiveSolution.Tag == mod.Tag, mod.Tag, stat.Tag))

    # C2) 因此此刻建载荷 BC 必报 Invalid LBC neutral name
    try:
        b1 = new_load_builder("ComponentForceField", "ForceBlocked")
        b1.Destroy()
        check("REG_BC_LOAD_UNDER_MODAL_ACTIVE", False,
              "模态方案激活下仍可建载荷 BC（旧结论不成立）")
    except Exception as exc:
        check("REG_BC_LOAD_UNDER_MODAL_ACTIVE",
              "Invalid LBC neutral name" in str(exc),
              "异常原文=%r（抛在 builder 创建那一刻，不是 Commit）" % str(exc))

    # C3) 显式切回静态方案 -> 同一个名字恢复可用
    check("REG_SET_ACTIVE_STATIC", set_active(stat),
          "ActiveSolution 可写且赋值粘住（tag=%s）" % stat.Tag)
    try:
        b2 = new_load_builder("ComponentForceField", "ForceBack")
        b2.Destroy()
        check("REG_BC_LOAD_ACTIVE_RESTORE", True,
              "回切静态后同一个名字可用（受控 A/B 成立）")
    except Exception as exc:
        check("REG_BC_LOAD_ACTIVE_RESTORE", False, "异常原文=%r" % str(exc))

    # ---- D) 无效中性名抽样 + 正向对照（同轮出现，才有鉴别力） ----
    try:
        b3 = new_con_builder("UserDefinedDisplacementConstraint", "FixOK")
        b3.Destroy()
        check("REG_BC_CONS_UDD_OK", True,
              "UserDefinedDisplacementConstraint（正向对照）可建")
    except Exception as exc:
        check("REG_BC_CONS_UDD_OK", False, "异常原文=%r" % str(exc))

    cons_bad = {}
    for nm in ("FixedConstraint", "PinnedConstraint"):
        try:
            bb = new_con_builder(nm, "C_" + nm)
            bb.Destroy()
            cons_bad[nm] = "BUILT(意外)"
        except Exception as exc:
            cons_bad[nm] = str(exc)
    check("REG_BC_CONS_BLACKLIST",
          all(cons_bad[n] == "Invalid LBC neutral name" for n in cons_bad),
          "失败清单=%s" % cons_bad)

    try:
        b4 = new_load_builder("PressureField", "Press")
        b4.Destroy()
        check("REG_BC_LOAD_PRESSURE_BLACKLIST", False, "PressureField 竟然可建")
    except Exception as exc:
        check("REG_BC_LOAD_PRESSURE_BLACKLIST",
              "Invalid LBC neutral name" in str(exc), "异常原文=%r" % str(exc))

    ufs.Part.Save()
    landed = [os.path.basename(p) for p in (CAD, FEM, SIM)
              if os.path.exists(p) and os.path.getsize(p) > 0]
    check("REG_ARTIFACTS_LANDED", len(landed) == 3, "落盘非空=%s" % landed)

    failed = [n for n, v in RESULTS if not v]
    say("TEST30_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST30_FAIL failed=%s" % failed)
        raise RuntimeError("test 30 failed: %s" % failed)
    say("TEST30_DONE")


if __name__ == "__main__":
    main()
