# -*- coding: utf-8 -*-
"""Test 26: 孔包（HolePackage）四条孔型的批处理落地边界（NX12）。

三条正路 + 一条明确边界（每条都断言几何，不看"提交成功"就算数）：

正路（本用例逐条断言几何，不看"提交成功"就算数）：
  1. `DrillSizeHole` 钻孔：**必须** `DrillSize`（规格标签）+ `DrillSizeHoleDiameter`
     / `DrillSizeHoleDepth`（Expression）**同时**给。只给标签 → 孔会变成默认的
     Ø11 贯通；只给 Expression → `Standard data not found`。
     两者都给 → Ø10、深 15 精确成立（r=5.0000，圆柱面 z=[5.0,19.4]）。
  2. `GeneralHole` 通用孔（默认简单形式）：直径/深度全走 Expression，Ø10 × 15 成立。
  3. `ScrewClearanceHole` 螺钉过孔：吃标准数据，`ScrewSize="M10"` +
     `ScrewFitOption="Normal (H13)"` → 过孔 Ø11（ISO 273 正常配合），深度同样成立。
边界（同样断言，防止"静默做错"）：
  4. `ThreadedHole` 螺纹孔：Validate 通过但 **Commit 必崩**
     `NXException: Internal error: memory access violation`（t1–t5 五种深度组合
     全部复现，树里只留下一个没有几何的 HOLE PACKAGE 特征）。
     本用例把它写成**条件检查**：崩了算"已知边界"通过；一旦哪天不崩了，
     就必须几何正确（底孔 Ø8.5）才算通过 —— 既不掩盖既有限制，也不锁死未来修复。

三条曾被写错的 API 事实（都实测钉死）：
  a. `Tolerance`（距离公差，double）**必填**。不写 → Validate 直接报
     "The Tolerance Specification requires three numbers"；写了 0.0254 就通。
     `HolePackageBuilder` **没有** `PropertyTable`（那是 CAE/FEM 的特征属性表），
     所以别再往属性表上找这个公差。
  b. 标准名必须与 `UGII\\modeling_standards\\*.xml` 里的 `Standard=` 一致：
     螺纹孔是 **`Metric Coarse`**（不是 `Metric`），尺寸串是 **`M10 x 1.5`**（带空格）；
     钻孔是 **`ISO`**。写错 → "Thread standard data not found" / "Standard data not found"。
  c. `ScrewStandard/ScrewType/ScrewSize/ScrewFitOption` 只对**螺钉过孔**适用
     （API 文档明示 + 实测评测），螺纹孔写这些字段是无效动作；成员名是
     `ScrewFitOption`，没有 `ScrewFit`。

几何读数约定（踩过坑）：`ufs.Modeling.AskFaceData` 返回的 box 是
`(xmin, ymin, zmin, xmax, ymax, zmax)`，配对必须是 (0,3)/(1,4)/(2,5)；
曾把 (0,1) 当 x 范围算出"孔跑到 x=20"，浪费一轮。

⚠ **本用例预期 `run_journal` 退出码 = 1**：第 5 个 case 故意触发 `ThreadedHole` 的原生崩溃，
此后进程退出码恒为 1，**而日志仍写 `Execution was successful.`**。判定一律看令牌
（`TEST26_DONE` + 无 `_FAIL` 行），见 SKILL.md §6 与 RUN_TESTS.bat 头注释。
"""
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
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
from nxlib.modeling import block

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.join(HERE, "parts")

SAVED_PARTS = [os.path.join(PARTS, "t26_%s.prt" % n)
               for n in ("drill", "general", "screwclear")]

HX, HY, TOP_Z = 30.0, 20.0, 20.0
BLOCK_L, BLOCK_B, BLOCK_H = 60.0, 40.0, 20.0
DIA, DEPTH = 10.0, 15.0
SCREW_CLEAR_DIA = 11.0
TAP_DRILL_DIA = 8.5
TOL = 0.0254


def new_block(path):
    wp = new_part(path=path)
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0),
          str(BLOCK_L), str(BLOCK_B), str(BLOCK_H))
    return wp


def make_builder(wp, with_tolerance=True):
    """点 Section → 目标体 → 投影方向 → 深度按值 → 距离公差。"""
    body = [x for x in wp.Bodies][0]
    pt = wp.Points.CreatePoint(NXOpen.Point3d(HX, HY, TOP_Z))
    b = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
    rule = wp.ScRuleFactory.CreateRuleCurveDumbFromPoints([pt])
    b.HolePosition.AddToSection([rule], pt, NXOpen.NXObject.Null,
                                NXOpen.NXObject.Null,
                                NXOpen.Point3d(HX, HY, TOP_Z),
                                NXOpen.Section.Mode.Create, False)
    BT = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
    b.BooleanOperation.SetBooleanOperationAndBody(BT.Subtract, body)
    b.ProjectionDirection.ProjectVector = wp.Directions.CreateDirection(
        pt, NXOpen.Vector3d(0.0, 0.0, -1.0))
    b.HoleDepthLimitOption = NXOpen.Features.HolePackageBuilder\
        .HoleDepthLimitOptions.Value
    if with_tolerance:
        b.Tolerance = TOL
    return b


def bore(session, wp):
    """孔位处的圆柱面：(半径, zmin, zmax)。box 配对 (0,3)/(1,4)/(2,5)。"""
    ufs = NXOpen.UF.UFSession.GetUFSession()
    out = []
    for body in wp.Bodies:
        for f in body.GetFaces():
            if f.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
                continue
            d = ufs.Modeling.AskFaceData(f.Tag)
            box = d[3]
            if abs(0.5 * (box[0] + box[3]) - HX) > 1e-3:
                continue
            if abs(0.5 * (box[1] + box[4]) - HY) > 1e-3:
                continue
            out.append((d[4], box[2], box[5]))
    return out


def commit(b):
    for label, fn_ in (("Validate", lambda: b.Validate()),
                       ("CommitFeature", lambda: b.CommitFeature())):
        try:
            fn_()
        except Exception as exc:
            return label, exc
    try:
        b.Destroy()
    except Exception:
        pass
    return None, None


def case_drill(session, ufs):
    wp = new_block(os.path.join(PARTS, "t26_drill.prt"))
    b = make_builder(wp)
    b.Type = b.Types.DrillSizeHole
    b.DrillSizeStandard = "ISO"
    b.DrillSizeFitOption = "Exact"
    b.DrillSize = "10"
    b.DrillSizeHoleDiameter.RightHandSide = str(DIA)
    b.DrillSizeHoleDepth.RightHandSide = str(DEPTH)
    b.DrillSizeTipAngle.RightHandSide = "118"
    step, exc = commit(b)
    check("REG_HOLE_DRILL_COMMIT", step is None,
          "钻孔提交=%s %s" % ("OK" if step is None else step,
                              "" if exc is None else str(exc)[:80]))
    bores = bore(session, wp)
    check("BENCH_HOLE_DRILL_DIA",
          len(bores) == 1 and abs(bores[0][0] - DIA / 2.0) < 1e-3,
          "圆柱面=(r, zmin, zmax) %s（期望 r=%.3f）"
          % ([tuple(round(x, 3) for x in t) for t in bores], DIA / 2.0))
    check("BENCH_HOLE_DRILL_DEPTH",
          len(bores) == 1 and abs(bores[0][1] - (TOP_Z - DEPTH)) < 0.05,
          "孔底 z=%.3f（期望 %.1f = 顶面 %.0f − 深 %.0f）"
          % (bores[0][1] if bores else -1.0, TOP_Z - DEPTH, TOP_Z, DEPTH))
    ufs.Part.Save()


def case_general(session, ufs):
    wp = new_block(os.path.join(PARTS, "t26_general.prt"))
    b = make_builder(wp)
    b.Type = b.Types.GeneralHole
    b.GeneralSimpleHoleDiameter.RightHandSide = str(DIA)
    b.GeneralSimpleHoleDepth.RightHandSide = str(DEPTH)
    b.GeneralTipAngle.RightHandSide = "118"
    step, exc = commit(b)
    check("REG_HOLE_GENERAL_COMMIT", step is None,
          "通用孔提交=%s %s" % ("OK" if step is None else step,
                                "" if exc is None else str(exc)[:80]))
    bores = bore(session, wp)
    check("BENCH_HOLE_GENERAL_DIA",
          len(bores) == 1 and abs(bores[0][0] - DIA / 2.0) < 1e-3,
          "圆柱面=(r, zmin, zmax) %s" % ([tuple(round(x, 3) for x in t)
                                          for t in bores],))
    check("BENCH_HOLE_GENERAL_DEPTH",
          len(bores) == 1 and abs(bores[0][1] - (TOP_Z - DEPTH)) < 0.05,
          "孔底 z=%.3f（期望 %.1f）"
          % (bores[0][1] if bores else -1.0, TOP_Z - DEPTH))
    ufs.Part.Save()


def case_screw_clearance(session, ufs):
    wp = new_block(os.path.join(PARTS, "t26_screwclear.prt"))
    b = make_builder(wp)
    b.Type = b.Types.ScrewClearanceHole
    b.ScrewStandard = "ISO"
    b.ScrewType = "General Screw Clearance"
    b.ScrewSize = "M10"
    b.ScrewFitOption = "Normal (H13)"
    b.ScrewClearanceHoleDepth.RightHandSide = str(DEPTH)
    step, exc = commit(b)
    check("REG_HOLE_SCREW_CLEAR_COMMIT", step is None,
          "螺钉过孔提交=%s %s" % ("OK" if step is None else step,
                                  "" if exc is None else str(exc)[:80]))
    bores = bore(session, wp)
    check("BENCH_HOLE_SCREW_CLEAR_DIA",
          len(bores) == 1 and abs(bores[0][0] - SCREW_CLEAR_DIA / 2.0) < 1e-3,
          "圆柱面=(r, zmin, zmax) %s（期望 r=%.3f，ISO 273 正常配合）"
          % ([tuple(round(x, 3) for x in t) for t in bores],
             SCREW_CLEAR_DIA / 2.0))
    ufs.Part.Save()


def case_tolerance_required(session, ufs):
    """负对照：不给 Tolerance，Validate 必须报错（否则这条检查没有鉴别力）。"""
    wp = new_block(os.path.join(PARTS, "t26_notol.prt"))
    b = make_builder(wp, with_tolerance=False)
    b.Type = b.Types.GeneralHole
    b.GeneralSimpleHoleDiameter.RightHandSide = str(DIA)
    b.GeneralSimpleHoleDepth.RightHandSide = str(DEPTH)
    step, exc = commit(b)
    check("REG_HOLE_TOLERANCE_REQUIRED",
          step == "Validate" and exc is not None
          and "three numbers" in str(exc),
          "不给 Tolerance 时 %s: %s" % (step, "" if exc is None
                                        else str(exc)[:90]))


def case_threaded(session, ufs):
    """螺纹孔：崩 = 已知边界（通过）；不崩则几何必须对（底孔 Ø8.5）。

    崩之前先立一个撤销标记，崩之后撤销回去：崩溃会在树里留下一个**没有几何**的
    HOLE PACKAGE 特征，不清掉会污染会话（实测还让 run_journal 的退出码变成 1，
    虽然日志明确写着 Execution was successful）。
    """
    wp = new_block(os.path.join(PARTS, "t26_threaded.prt"))
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible,
                               "t26_threaded")
    b = make_builder(wp)
    b.Type = b.Types.ThreadedHole
    b.ThreadStandard = "Metric Coarse"
    b.ThreadSize = "M10 x 1.5"
    b.ThreadLengthOption = NXOpen.Features.HolePackageBuilder\
        .ThreadLengthOptions.Standard
    b.ThreadedHoleDepth.RightHandSide = str(DEPTH)
    b.ThreadDepth.RightHandSide = "12"
    b.TapDrillDiameter.RightHandSide = str(TAP_DRILL_DIA)
    step, exc = commit(b)
    if step is not None:
        check("REG_HOLE_THREADED_BOUNDARY",
              "memory access violation" in str(exc),
              "螺纹孔在批处理下不可用（已知边界）：%s: %s"
              % (step, str(exc)[:90]))
        rolled = False
        try:
            session.UndoToMark(mark, "t26_threaded")
            rolled = True
        except Exception as exc2:
            say("THREADED_ROLLBACK_RAISE=%s: %s"
                % (type(exc2).__name__, str(exc2)[:90]))
        left = [f.FeatureType for f in wp.Features.GetFeatures()
                if f.FeatureType == "HOLE PACKAGE"]
        check("REG_HOLE_THREADED_ROLLBACK", rolled and not left,
              "撤销后残留孔特征=%s" % left)
        return
    bores = bore(session, wp)
    check("REG_HOLE_THREADED_GEOMETRY",
          len(bores) == 1 and abs(bores[0][0] - TAP_DRILL_DIA / 2.0) < 1e-3,
          "螺纹孔这次没崩，几何必须正确：%s"
          % ([tuple(round(x, 3) for x in t) for t in bores],))
    ufs.Part.Save()


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    case_drill(session, ufs)
    case_general(session, ufs)
    case_screw_clearance(session, ufs)
    case_tolerance_required(session, ufs)
    case_threaded(session, ufs)
    landed = [os.path.basename(p) for p in SAVED_PARTS
              if os.path.exists(p) and os.path.getsize(p) > 0]
    check("REG_ARTIFACTS_LANDED", len(landed) == 3, "落盘非空=%s" % landed)
    failed = [n for n, v in RESULTS if not v]
    say("TEST26_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST26_FAIL failed=%s" % failed)
        raise RuntimeError("test 26 failed: %s" % failed)
    say("TEST26_DONE")


if __name__ == "__main__":
    main()
