# -*- coding: utf-8 -*-
"""API 探针：复验竞品技能（cookbook / Kenneth2Y / nx-codex）中的候选条目在 NX 12 的真实行为。

每项独立 try/except，单项失败不影响其余；输出 PROBE_<NAME>=PASS/FAIL/INFO 供 grep。
不是交付 journal，不做可编辑性检查，跑完即弃。
"""
# check_journal: allow-probes  （一次性 API 探针，故意演示坑位，静态检查豁免）

import os
import sys
import traceback

import NXOpen
import NXOpen.Features
import NXOpen.UF
import NXOpen.GeometricUtilities

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "parts", "probe_api.prt"))


def show(name, ok, detail=""):
    print("PROBE_%s=%s %s" % (name, "PASS" if ok else "FAIL", detail))


def probe(name, fn):
    try:
        detail = fn()
        show(name, True, detail if detail is not None else "")
    except Exception as exc:
        show(name, False, "%s: %s" % (type(exc).__name__, exc))


def new_part(s):
    if os.path.exists(OUT):
        os.remove(OUT)
    fn = s.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.UseBlankTemplate = False
    fn.NewFileName = OUT
    fn.Commit()
    fn.Destroy()
    return s.Parts.Work


def bodies(wp):
    return [b for b in wp.Bodies]


def main():
    s = NXOpen.Session.GetSession()
    print("=== API PROBE START ===")

    # ---------- 0. 子模块 import 是否必须（模块顶层 import NXOpen.Features 已在上方） ----------
    def p_submodule():
        return "top-level 'import NXOpen.Features' enables NXOpen.Features.* = %s" % (
            hasattr(NXOpen, "Features"))
    probe("SUBMODULE_TOP_IMPORT", p_submodule)

    wp = new_part(s)
    print("work part: %s" % wp.FullPath)
    print("bodies=%d" % len(bodies(wp)))

    # ---------- 1. 表达式 .Value vs RightHandSide（25.4x 单位换算） ----------
    def p_expr_units():
        e = wp.Expressions.CreateExpression("Number", "p_L=100")
        # 枚举 Expression 可写属性，判断是否存在 .Value
        attrs = [a for a in dir(e) if not a.startswith("_")]
        has_value = "Value" in attrs
        info = "has .Value attr=%s; attrs=%s" % (
            has_value, [a for a in attrs if a in
                        ("Value", "RightHandSide", "Name", "Units", "Formula",
                         "Type", "Comment", "EditComment")])
        if has_value:
            try:
                before = e.RightHandSide
                e.Value = 200.0
                after = e.RightHandSide
                info += " | after .Value=200.0 -> RHS=%r" % after
                # 检查是否被 25.4 放大
                e.Value = 1.0
                info += " | .Value=1.0 -> RHS=%r" % e.RightHandSide
                e.RightHandSide = before
            except Exception as exc:
                info += " | .Value write raised %s: %s" % (type(exc).__name__, exc)
        return info
    probe("EXPR_VALUE_VS_RHS", p_expr_units)

    # ---------- 2. Point3d 传 int ----------
    def p_int_point():
        NXOpen.Point3d(0, 0, 0)
        return "Point3d(int,int,int) accepted"
    probe("POINT3D_INT", p_int_point)

    # ---------- 3. FileNew 模板 / 单位枚举 ----------
    def p_units_enum():
        return "Part.Units.Millimeters exists = %s; BasePart.Units exists = %s" % (
            hasattr(NXOpen.Part, "Units"), hasattr(NXOpen.BasePart, "Units"))
    probe("UNITS_ENUM", p_units_enum)

    # ---------- 4. 方块 + BlockFeatureBuilder 布尔：BooleanOption vs SetBooleanOperationAndTarget ----------
    def p_block_bool():
        blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")
        blk.CommitFeature()
        blk.Destroy()
        n1 = len(bodies(wp))
        target = bodies(wp)[0]

        cut = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        cut.SetOriginAndLengths(NXOpen.Point3d(30.0, 20.0, -5.0), "20", "20", "30")
        cut.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
        cut.BooleanOption.SetTargetBodies([target])
        cut.CommitFeature()
        cut.Destroy()
        n2 = len(bodies(wp))

        # 第二种：SetBooleanOperationAndTarget
        cut2 = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        cut2.SetOriginAndLengths(NXOpen.Point3d(60.0, 20.0, -5.0), "15", "15", "30")
        cut2.SetBooleanOperationAndTarget(
            NXOpen.Features.Feature.BooleanType.Subtract, bodies(wp)[0])
        cut2.CommitFeature()
        cut2.Destroy()
        n3 = len(bodies(wp))
        return "bodies: start=%d afterBooleanOption=%d afterSetBoolOpAndTarget=%d" % (n1, n2, n3)
    probe("BLOCK_BOOLEAN_SILENT", p_block_bool)

    # ---------- 5. 质量属性 NewMassProperties 签名 ----------
    def p_mass():
        b = bodies(wp)[0]
        uc = wp.UnitCollection
        units = [uc.FindObject(n) for n in
                 ("SquareMilliMeter", "CubicMilliMeter", "Kilogram",
                  "MilliMeter", "Newton")]
        notes = "units(%d)=%s " % (len(units), [u is not None for u in units])
        # 5a: 数组形式 tolerances
        try:
            mp = wp.MeasureManager.NewMassProperties(units, [0.99], [b])
            notes += "| array-tol OK V=%.3f A=%.3f M=%.6f" % (mp.Volume, mp.Area, mp.Mass)
        except Exception as exc:
            notes += "| array-tol raised %s: %s" % (type(exc).__name__, exc)
        # 5b: 标量形式（cookbook 写法）
        try:
            mp2 = wp.MeasureManager.NewMassProperties(units, 0.99, [b])
            notes += "| scalar-tol OK V=%.3f" % mp2.Volume
        except Exception as exc:
            notes += "| scalar-tol raised %s: %s" % (type(exc).__name__, exc)
        return notes
    probe("MASS_PROPS_SIG", p_mass)

    # ---------- 6. 质量属性：多体返回 0？ ----------
    def p_mass_multi():
        b2 = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        b2.SetOriginAndLengths(NXOpen.Point3d(200.0, 0.0, 0.0), "10", "10", "10")
        b2.CommitFeature()
        b2.Destroy()
        uc = wp.UnitCollection
        units = [uc.FindObject(n) for n in
                 ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
        allb = bodies(wp)
        mp = wp.MeasureManager.NewMassProperties(units, [0.99], allb)
        return "bodies=%d multi-body V=%.3f (cookbook claims 0)" % (len(allb), mp.Volume)
    probe("MASS_PROPS_MULTI", p_mass_multi)

    # ---------- 7. DoUpdate 返回值语义 ----------
    def p_doupdate():
        mark = s.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "probe")
        errs = s.UpdateManager.DoUpdate(mark)
        return "DoUpdate returned %r (type %s)" % (errs, type(errs).__name__)
    probe("DOUPDATE_RETURN", p_doupdate)

    # ---------- 8. ShellBuilder 默认 Tolerance / DraftBuilder 默认 AngleTolerance ----------
    def p_shell_defaults():
        sb = wp.Features.CreateShellBuilder(NXOpen.Features.Feature.Null)
        t = sb.Tolerance
        db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)
        at = db.AngleTolerance
        sb.Destroy()
        db.Destroy()
        return "Shell.Tolerance default=%r  Draft.AngleTolerance default=%r" % (t, at)
    probe("SHELL_DRAFT_TOL_DEFAULTS", p_shell_defaults)

    # ---------- 9. CreateRuleBaseCurveDumb 是否存在（cookbook 称已废弃） ----------
    def p_rule_names():
        rf = wp.ScRuleFactory
        names = [n for n in dir(rf) if "Rule" in n and "Curve" in n]
        return "curve rules=%s" % names
    probe("RULE_FACTORY_CURVE_NAMES", p_rule_names)

    # ---------- 10. 螺纹：NX12 是否有 Thread 特征 builder ----------
    def p_thread():
        has_cls = hasattr(NXOpen.Features, "Thread")
        has_meth = hasattr(wp.Features, "CreateThreadBuilder")
        cls_names = [n for n in dir(NXOpen.Features) if "Thread" in n]
        return "Features.Thread=%s CreateThreadBuilder=%s threadClasses=%s" % (
            has_cls, has_meth, cls_names)
    probe("THREAD_AVAILABILITY", p_thread)

    # ---------- 11. 保存重载：SaveComponents.TrueValue / CloseAfterSave.FalseValue ----------
    def p_save_overload():
        info = "SaveComponents=%s CloseAfterSave=%s" % (
            [n for n in dir(NXOpen.BasePart.SaveComponents) if not n.startswith("_")],
            [n for n in dir(NXOpen.BasePart.CloseAfterSave) if not n.startswith("_")])
        wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
                NXOpen.BasePart.CloseAfterSave.FalseValue)
        info += " | Save(TrueValue,FalseValue) OK exists=%s size=%d" % (
            os.path.exists(OUT), os.path.getsize(OUT) if os.path.exists(OUT) else -1)
        return info
    probe("SAVE_TWO_ARG_OVERLOAD", p_save_overload)

    # ---------- 12. STEP 导出（DexManager.CreateStepCreator） ----------
    def p_step():
        sc = s.DexManager.CreateStepCreator()
        sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
        sc.ObjectTypes.Solids = True
        sc.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
        sc.InputFile = wp.FullPath
        step_out = os.path.splitext(OUT)[0] + ".stp"
        if os.path.exists(step_out):
            os.remove(step_out)
        sc.OutputFile = step_out
        try:
            sc.ExportSelectionBlock.SelectionComp.Add(bodies(wp)[0])
            comp = "SelectionComp.Add(single body) OK"
        except Exception as exc:
            comp = "SelectionComp.Add raised %s: %s" % (type(exc).__name__, exc)
        sc.Commit()
        sc.Destroy()
        ok = os.path.exists(step_out) and os.path.getsize(step_out) > 0
        return "%s | file exists=%s size=%d" % (
            comp, ok, os.path.getsize(step_out) if os.path.exists(step_out) else -1)
    probe("STEP_EXPORT", p_step)

    # ---------- 13. STL 导出（修正：可用，选择器必须用 SetArray） ----------
    def p_stl():
        stl_out = os.path.splitext(OUT)[0] + ".stl"
        if os.path.exists(stl_out):
            os.remove(stl_out)
        sc = s.DexManager.CreateStlCreator()
        sc.OutputFile = stl_out
        try:
            sc.ExportSelectionBlock.SetArray(bodies(wp))
        except Exception as exc:
            print("  STL SetArray raised %s: %s" % (type(exc).__name__, exc))
        sc.Commit()
        sc.Destroy()
        ok = os.path.exists(stl_out)
        return "STL file exists=%s size=%d" % (
            ok, os.path.getsize(stl_out) if ok else -1)
    probe("STL_EXPORT", p_stl)

    # ---------- 14. RemoveParametersBuilder（去参） ----------
    def p_remove_params():
        rpb = wp.Features.CreateRemoveParametersBuilder()
        rpb.Objects.Add(bodies(wp))
        rpb.Commit()
        rpb.Destroy()
        return "RemoveParameters committed OK"
    probe("REMOVE_PARAMETERS", p_remove_params)

    # ---------- 15. UndoToMark 回滚 ----------
    def p_undo():
        # 去参后特征数已变；此处只验证 API 可调用
        mark = s.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "undo-probe")
        blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
        blk.SetOriginAndLengths(NXOpen.Point3d(400.0, 0.0, 0.0), "5", "5", "5")
        blk.CommitFeature()
        blk.Destroy()
        n_after = len(bodies(wp))
        s.UndoToMark(mark, "undo-probe")
        n_undo = len(bodies(wp))
        return "bodies after commit=%d after UndoToMark=%d" % (n_after, n_undo)
    probe("UNDO_TO_MARK", p_undo)

    # ---------- 16. Parasolid 导出器可用性 ----------
    def p_parasolid():
        names = [n for n in dir(s.DexManager) if "Parasolid" in n or "Ps" in n]
        return "DexManager parasolid methods=%s" % names
    probe("PARASOLID_EXPORT_API", p_parasolid)

    print("=== API PROBE DONE ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("PROBE_FATAL:\n" + traceback.format_exc())
        raise
