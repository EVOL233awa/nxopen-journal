# -*- coding: utf-8 -*-
"""API 探针 3：STEP 导出同步性 + 质量属性校验原语（用于 junal 自校验）。"""
import os
import time
import traceback

import NXOpen
import NXOpen.Features

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.abspath(os.path.join(HERE, "parts", "probe3.prt"))


def show(name, ok, d=""):
    print("PROBE_%s=%s %s" % (name, "PASS" if ok else "FAIL", d))


def probe(name, fn):
    try:
        show(name, True, fn() or "")
    except Exception as exc:
        show(name, False, "%s: %s" % (type(exc).__name__, exc))


def bodies(wp):
    return [b for b in wp.Bodies]


def step_export(s, wp, out, hold, scope_selected, body=None):
    if os.path.exists(out):
        os.remove(out)
    sc = s.DexManager.CreateStepCreator()
    sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
    sc.ObjectTypes.Solids = True
    if scope_selected and body is not None:
        sc.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
        sc.ExportSelectionBlock.SelectionComp.Add(body)
    sc.InputFile = wp.FullPath
    sc.OutputFile = out
    if hold:
        sc.ProcessHoldFlag = True
    sc.Commit()
    sc.Destroy()
    immediate = os.path.exists(out)
    time.sleep(3.0)
    after = os.path.getsize(out) if os.path.exists(out) else -1
    return "hold=%s sel=%s | exists_at_commit=%s size_after_3s=%d" % (
        hold, scope_selected, immediate, after)


def main():
    s = NXOpen.Session.GetSession()
    print("=== API PROBE 3 START ===")

    if os.path.exists(P):
        os.remove(P)
    fn = s.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.UseBlankTemplate = False
    fn.NewFileName = P
    fn.Commit(); fn.Destroy()
    wp = s.Parts.Work

    blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
    blk.CommitFeature(); blk.Destroy()
    b = bodies(wp)[0]

    o = os.path.splitext(P)[0]
    probe("STEP_NO_HOLD_SEL", lambda: step_export(s, wp, o + "_nohold_sel.stp", False, True, b))
    probe("STEP_HOLD_SEL", lambda: step_export(s, wp, o + "_hold_sel.stp", True, True, b))

    # 质量属性校验原语：单体积 vs 解析值
    def p_measure():
        uc = wp.UnitCollection
        units = [uc.FindObject(n) for n in
                 ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
        mp = wp.MeasureManager.NewMassProperties(units, [0.99], [b])
        expect = 100.0 * 60.0 * 20.0
        return "V=%.3f expect=%.1f delta=%.6f A=%.3f centroid=(%.3f,%.3f,%.3f)" % (
            mp.Volume, expect, abs(mp.Volume - expect), mp.Area,
            mp.Centroid.X, mp.Centroid.Y, mp.Centroid.Z)
    probe("MEASURE_ASSERT", p_measure)

    # DoUpdate 错误数语义：制造一个失败特征后看返回
    def p_doupdate_err():
        mark = s.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "e")
        n = s.UpdateManager.DoUpdate(mark)
        return "clean update returns %r" % n
    probe("DOUPDATE_CLEAN", p_doupdate_err)

    # Point3d 精确复现我们文档里的写法
    def p_point3d_doc_pattern():
        try:
            NXOpen.Point3d(0, 0, 0)
            return "Point3d(0,0,0) accepted (unexpected)"
        except TypeError as exc:
            return "CONFIRMED TypeError: %s" % exc
    probe("POINT3D_DOC_PATTERN", p_point3d_doc_pattern)

    # SetOriginAndLengths 传数字 vs 字符串
    def p_lengths_type():
        blk2 = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            blk2.SetOriginAndLengths(NXOpen.Point3d(200.0, 0.0, 0.0), 10.0, 10.0, 10.0)
            blk2.CommitFeature()
            blk2.Destroy()
            return "SetOriginAndLengths(float,float,float,float) accepted; bodies=%d" % len(bodies(wp))
        except Exception as exc:
            blk2.Destroy()
            return "float lengths raised %s: %s" % (type(exc).__name__, exc)
    probe("SETORIGIN_LENGTHS_TYPE", p_lengths_type)

    print("=== API PROBE 3 DONE ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("PROBE_FATAL:\n" + traceback.format_exc())
        raise

# check_journal: allow-probes  （一次性 API 探针，故意演示坑位，静态检查豁免）
