# -*- coding: utf-8 -*-
"""API 探针 2：钉死第一轮暴露的歧义点。

1. 长度量纲表达式的 .Value vs RightHandSide（25.4x 单位换算是否真实存在）
2. BlockFeatureBuilder 布尔隔离复测（BooleanOption 静默失败 vs SetBooleanOperationAndTarget）
3. STEP 导出为何无产物（ProcessHoldFlag / FileSaveFlag / 整部件导出）
4. 函数内 import 子模块的作用域陷阱
5. 螺纹：NX12 是否有替代 API
"""
# check_journal: allow-probes  （一次性 API 探针，故意演示坑位，静态检查豁免）

import os
import traceback

import NXOpen
import NXOpen.Features
import NXOpen.UF
import NXOpen.GeometricUtilities

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "parts", "probe2_api.prt"))
STEP1 = os.path.abspath(os.path.join(HERE, "parts", "probe2_sel.stp"))
STEP2 = os.path.abspath(os.path.join(HERE, "parts", "probe2_all.stp"))


def show(name, ok, detail=""):
    print("PROBE_%s=%s %s" % (name, "PASS" if ok else "FAIL", detail))


def probe(name, fn):
    try:
        d = fn()
        show(name, True, d if d is not None else "")
    except Exception as exc:
        show(name, False, "%s: %s" % (type(exc).__name__, exc))


def bodies(wp):
    return [b for b in wp.Bodies]


def new_part(s, path):
    if os.path.exists(path):
        os.remove(path)
    fn = s.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.UseBlankTemplate = False
    fn.NewFileName = path
    fn.Commit()
    fn.Destroy()
    return s.Parts.Work


def main():
    s = NXOpen.Session.GetSession()
    print("=== API PROBE 2 START ===")

    wp = new_part(s, OUT)
    print("work part: %s" % wp.FullPath)

    # ---------- 1. 长度表达式 .Value 是否 25.4x ----------
    def p_length_value():
        unit = wp.UnitCollection.GetBase("Length")
        e = wp.Expressions.CreateSystemExpressionWithUnits("L_Test = 100.0", unit)
        info = "RHS=%r .Value=%r" % (e.RightHandSide, e.Value)
        # 设置 .Value = 200，看 RHS 变成什么
        e.Value = 200.0
        info += " | set .Value=200.0 -> RHS=%r .Value=%r" % (e.RightHandSide, e.Value)
        # 设置 RHS = 300，看 .Value
        e.RightHandSide = "300.0"
        info += " | set RHS='300.0' -> .Value=%r" % e.Value
        info += " | Units=%s" % (e.Units is not None)
        return info
    probe("LENGTH_EXPR_VALUE", p_length_value)

    # ---------- 2. 布尔隔离复测 ----------
    def p_bool_option_isolated():
        blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
        blk.CommitFeature(); blk.Destroy()
        n1 = len(bodies(wp))
        tgt = bodies(wp)[-1]

        cut = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        cut.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
        cut.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
        cut.BooleanOption.SetTargetBodies([tgt])
        cut.CommitFeature(); cut.Destroy()
        n2 = len(bodies(wp))
        return "A) BooleanOption: bodies %d -> %d (expect 1 if subtracted, 2 if silently ignored)" % (n1, n2)
    probe("BOOLOPT_ISOLATED", p_bool_option_isolated)

    def p_setbool_isolated():
        # 新建干净 part 复测 SetBooleanOperationAndTarget
        wp2 = new_part(s, os.path.abspath(os.path.join(HERE, "parts", "probe2_b.prt")))
        blk = wp2.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
        blk.CommitFeature(); blk.Destroy()
        n1 = len(bodies(wp2))
        tgt = bodies(wp2)[0]
        cut = wp2.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        cut.SetOriginAndLengths(NXOpen.Point3d(10.0, 10.0, -5.0), "20", "20", "30")
        cut.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Subtract, tgt)
        cut.CommitFeature(); cut.Destroy()
        n2 = len(bodies(wp2))
        return "B) SetBooleanOperationAndTarget: bodies %d -> %d (expect 1)" % (n1, n2)
    probe("SETBOOL_ISOLATED", p_setbool_isolated)

    # ---------- 3. STEP 导出无产物排查 ----------
    def p_step_variants():
        notes = []
        # 3a 选中实体 + ProcessHoldFlag
        try:
            sc = s.DexManager.CreateStepCreator()
            sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
            sc.ObjectTypes.Solids = True
            sc.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
            sc.ExportSelectionBlock.SelectionComp.Add(bodies(wp)[0])
            sc.InputFile = wp.FullPath
            sc.OutputFile = STEP1
            try:
                sc.ProcessHoldFlag = True
            except Exception as exc:
                notes.append("ProcessHoldFlag raise %s" % exc)
            sc.Commit(); sc.Destroy()
            notes.append("3a selected+hold: exists=%s size=%d" % (
                os.path.exists(STEP1), os.path.getsize(STEP1) if os.path.exists(STEP1) else -1))
        except Exception as exc:
            notes.append("3a raised %s: %s" % (type(exc).__name__, exc))
        # 3b 整部件（不设选择集）
        try:
            sc = s.DexManager.CreateStepCreator()
            sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
            sc.ObjectTypes.Solids = True
            sc.InputFile = wp.FullPath
            sc.OutputFile = STEP2
            sc.Commit(); sc.Destroy()
            notes.append("3b whole-part: exists=%s size=%d" % (
                os.path.exists(STEP2), os.path.getsize(STEP2) if os.path.exists(STEP2) else -1))
        except Exception as exc:
            notes.append("3b raised %s: %s" % (type(exc).__name__, exc))
        # 3c 检查 OutputFile 属性是否回读
        sc = s.DexManager.CreateStepCreator()
        notes.append("3c default ExportFrom=%s FileSaveFlag=%s" % (
            sc.ExportFrom, sc.FileSaveFlag))
        sc.Destroy()
        return " | ".join(notes)
    probe("STEP_VARIANTS", p_step_variants)

    # ---------- 4. 函数内 import 子模块的作用域陷阱 ----------
    def p_local_import():
        # 复现 cookbook 陷阱：函数内 import 子模块后，NXOpen 变成局部名
        def bad():
            import NXOpen.GeometricUtilities  # noqa: F401
            return NXOpen.Features.Feature.Null  # 若 NXOpen 被判为局部名则 UnboundLocalError
        try:
            bad()
            return "function-local submodule import did NOT break NXOpen reference"
        except UnboundLocalError as exc:
            return "CONFIRMED UnboundLocalError: %s" % exc
    probe("LOCAL_SUBMODULE_IMPORT", p_local_import)

    # ---------- 5. 螺纹替代 API ----------
    def p_thread_alt():
        hits = []
        for n in ("ThreadBuilder", "Thread", "ThreadFeatureBuilder"):
            hits.append("%s=%s" % (n, hasattr(NXOpen.Features, n)))
        # HolePackage 的螺纹选项
        hp = wp.Features.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null)
        hp_attrs = [a for a in dir(hp) if "Thread" in a]
        hp.Destroy()
        return "Features: %s | HolePackage thread attrs=%s" % (hits, hp_attrs)
    probe("THREAD_ALT", p_thread_alt)

    print("=== API PROBE 2 DONE ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("PROBE_FATAL:\n" + traceback.format_exc())
        raise
