# -*- coding: utf-8 -*-
"""Test 24: 2D 壳网格 + PSHELL 回归（NX12 批处理实测，2026-09-22；fea.md §3a）。

此前 fea.md 只写了实体 CTETRA(10) 一条路线，壳路线属于"从未用过"。本用例把它固化成检查：

A) 壳物理属性：`PhysicalPropertyTables.CreatePhysicalPropertyTable(
       "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", name, 2)` 可建；
   材质从 `MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")` 取；
   壳收集器 = `MeshManager.CreateCollectorBuilder(MeshCollector.Null, "ThinShell")`
   + `PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)`。

B) 2D 面网格：`MeshManager.CreateMesh2dBuilder(Mesh2d.Null)`，
   `SelectionList.Add(CAE_Face)` —— ⚠ 要的是 **CAE 面**（`fem.FindObject("CAE_Body(1)|CAE_Face(n)")`），
   不是 CAD Face；单元维度枚举真名是 `ElementTypeBuilder.ElementType.Shell`
   （**没有** `ThinShell`——上一轮就是猜这个名字报的 AttributeError）；
   单元类型名 `"CQUAD4"`；`CommitMesh()` 后 `GetNodeStatus()` 报节点数。

C) 结构体返回：`GetNodeStatus()` 返回 `IMeshManagerStatusInfo_Struct`，字段含 `TotalNum`。

⚠ 本用例只做网格，不做求解（2D 壳的求解级数值口径仍未标定，fea.md §3a 已如实标注）。
"""
import os
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

PARTS = os.path.join(os.path.dirname(__file__), "parts")
CAD = os.path.join(PARTS, "t24_shell_cad.prt")
FEM = os.path.join(PARTS, "t24_shell.fem")
IDEA = os.path.join(PARTS, "t24_shell_i.prt")

def build_cad(session, ufs):
    cad = new_part(path=CAD)
    ufs.Part.SetDisplayPart(cad.Tag)
    blk = cad.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "20", "5")
    blk.CommitFeature()
    blk.Destroy()
    cad.Save(NXOpen.BasePart.SaveComponents.TrueValue,
             NXOpen.BasePart.CloseAfterSave.FalseValue)
    check("REG_SHELL_CAD", os.path.exists(CAD) and os.path.getsize(CAD) > 0,
          "saved %s" % os.path.basename(CAD))
    return cad


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    for p in (CAD, FEM, IDEA):
        if os.path.exists(p):
            os.remove(p)

    cad = build_cad(session, ufs)
    fem = new_part(path=FEM, template="FemNxNastranMetric.fem")
    fem.FinalizeCreation(
        cad, "t24_shell_i",
        NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
        fem.NewFemSynchronizeOptions(), "NXNASTRAN", "STRUCT",
        NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet, ["desc"], False)
    say("fem=%s solver=%s" % (fem.Leaf, fem.GetSolverAndAnalysisType()))

    # ---------- A. PSHELL + 材质 + 壳收集器 ----------
    ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
        "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", "PSHELL1", 2)
    check("REG_PSHELL_TABLE", ppt is not None, "PSHELL table=%r" % (ppt is not None))

    steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
    check("REG_PSHELL_MATERIAL", steel is not None, "Steel=%r" % (steel is not None))
    ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)

    col_b = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(
        NXOpen.CAE.MeshCollector.Null, "ThinShell")
    col_b.CollectorName = "REGShell"
    col_b.PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)
    col = col_b.Commit()
    col_b.Destroy()
    check("REG_SHELL_COLLECTOR", col is not None, "collector=%r" % (col is not None))

    # ---------- B. 2D 面网格 ----------
    enum_cls = NXOpen.CAE.ElementTypeBuilder.ElementType
    names = sorted(n for n in dir(enum_cls) if not n.startswith("_") and n != "ValueOf")
    check("REG_SHELL_ENUM_NAME",
          "Shell" in names and "ThinShell" not in names,
          "ElementType=%s" % names)

    face = fem.FindObject("CAE_Body(1)|CAE_Face(6)")     # 顶面（100x20）
    check("REG_CAE_FACE_FOUND", face is not None, "CAE_Face(6)=%r" % (face is not None))

    mb = fem.BaseFEModel.MeshManager.CreateMesh2dBuilder(NXOpen.CAE.Mesh2d.Null)
    mb.SelectionList.Add(face)
    mb.ElementType.ElementDimension = enum_cls.Shell
    mb.ElementType.ElementTypeName = "CQUAD4"
    mb.ElementType.DestinationCollector.ElementContainer = col
    mb.ElementType.DestinationCollector.AutomaticMode = False
    mb.CommitMesh()
    mb.Destroy()

    st = fem.BaseFEModel.MeshManager.GetNodeStatus()
    total = getattr(st, "TotalNum", None)
    check("REG_SHELL_MESH_NODES",
          total is not None and int(total) >= 4,
          "GetNodeStatus().TotalNum=%r (%s)" % (total, type(st).__name__))

    try:
        est = fem.BaseFEModel.MeshManager.GetElementStatus()
        say("REG_SHELL_MESH_ELEMENTS=INFO %r" % (est,))
    except Exception as exc:
        say("REG_SHELL_MESH_ELEMENTS=INFO 无 GetElementStatus: %s" % type(exc).__name__)

    ufs.Part.Save()
    ok = all(v for _, v in RESULTS)
    failed = [n for n, v in RESULTS if not v]
    say("TEST24_CASES=%d" % len(RESULTS))
    if not ok:
        say("TEST24_FAIL failed=%s" % failed)
        raise RuntimeError("test 24 failed: %s" % failed)
    say("TEST24_DONE")


if __name__ == "__main__":
    main()
