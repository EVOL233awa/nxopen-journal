# -*- coding: utf-8 -*-
"""NXOpen journal 静态检查（无需 NX 环境）。

检查项:
  1. Python 语法 (ast.parse)
  2. TODO/FIXME/占位符
  3. main() 入口与 NXOpen import（提示性）
  4. 裸 except（提示性）
  5. 已固化坑位（NX 12 批处理验证）:
     - 创建 builder 传 None -> 必须用 NXOpen.Features.Feature.Null / BooleanFeature.Null
     - FileNew 未设 Units 或 NewFileName 不带 .prt -> Commit 必然报错
     - BasePart.SaveComponents/CloseAfterSave -> Python 关键字语法错误, 改用 ufs.Part.Save()
     - PartCollection.Open 参数个数 -> 只传 1 个参数, 返回 (part, loadStatus) 元组
     - BodyCollection.ToArray() -> 不存在, 直接迭代
     - ScCollector.ReplaceRules 第二参数 True -> 规则不立即求值, 选中 0 条边
     - Parts.Open 与 Parts.SetWork 同时出现 -> 批处理中会报 No Displayed Part
     - BlockFeatureBuilder.Length/Width/Height 只读 -> 用 SetLength/SetOriginAndLengths
       (AST 变量级判定: 只在该 builder 变量本身被赋值时报错,
        同文件里别的对象同名属性不再误报)
     - CreateRevolveBuilder 批处理 CommitFeature 内存违例 -> 用 UF Modl.CreateRevolved
     - NXOpen.UF.FeatureSigns 不存在 -> 用 NXOpen.UF.ModlFeatureSigns
     - ComponentAssembly.Components 不存在 -> 用 RootComponent.GetChildren()
     - DrawingSheets/DraftingViews 无 ToArray() -> 直接迭代
     - BlockFeatureBuilder.BooleanOption 被静默忽略 -> 用 SetBooleanOperationAndTarget
     - Point3d/Vector3d 传 int -> TypeError, 必须传 float
     - SetOriginAndLengths 长度传 float -> TypeError, 必须传 str
     - NX12 无 Features.Thread / CreateThreadBuilder -> 用 HolePackage 螺纹选项
     - StepCreator 未设 ProcessHoldFlag -> Commit 返回时文件尚未落盘
     - RemoveParametersBuilder -> 销毁特征树, 违背历史模式铁律
     - DraftBuilder.Method 只读 -> 用 DraftIsoclineOrTruedraft
     - DraftBuilder.AngleTolerance / ShellBuilder.Tolerance 默认 0.0 -> 必须显式设
     - NXOpen.UF.UFMotion / NXOpen.UF.UFDraw 不可导入 -> 会话对象 ufs.Motion / ufs.Draw
       (UF struct 按所属组查: NXOpen.UF.<组>.<名>, 如 Curve.SectionGeneralData;
        运动模块部分为顶层 NXOpen.UF.<名>_Struct, 如 MotionInterference_Struct)

用法:
  python check_journal.py path/to/journal.py
退出码: 0 = 通过(可含提示), 1 = 语法错误或占位符/已固化坑位
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# 保证输出不被控制台代码页吞掉/崩坏
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# builder 创建方法 -> 参数类型对应的空对象
BUILDER_NULL = {
    "CreateBlockFeatureBuilder": "NXOpen.Features.Feature.Null",
    "CreateCylinderBuilder": "NXOpen.Features.Feature.Null",
    "CreateConeBuilder": "NXOpen.Features.Cone.Null",
    "CreateBooleanBuilder": "NXOpen.Features.BooleanFeature.Null",
    "CreateChamferBuilder": "NXOpen.Features.Feature.Null",
    "CreateHoleFeatureBuilder": "NXOpen.Features.Feature.Null",
    "CreateEdgeBlendBuilder": "NXOpen.Features.Feature.Null",
    "CreateExtrudeBuilder": "NXOpen.Features.Feature.Null",
    "CreateRevolveBuilder": "NXOpen.Features.Feature.Null",
    "CreateMirrorFeatureBuilder": "NXOpen.Features.Feature.Null",
    "CreatePatternFeatureBuilder": "NXOpen.Features.Feature.Null",
}

# 尺寸属性只读的 builder: 只能 SetXxx / SetOriginAndLengths, 直接赋值会 AttributeError
READONLY_BUILDER_PROPS = {
    "CreateBlockFeatureBuilder": ("Length", "Width", "Height"),
    "CreateCylinderBuilder": ("Diameter", "Height"),
}


def _builder_vars(tree: ast.AST, create_method: str) -> set[str]:
    """收集由某 builder 创建方法赋值得到的变量名 (如 blk = ...CreateBlockFeatureBuilder(...)).

    规则 5.5/5.9/5.14 都只在该 builder 变量本身被误用时报警——按变量作用域判定,
    不做文件级文本匹配, 否则同文件里别的对象的同名属性会误报。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if isinstance(fn, ast.Attribute) and fn.attr == create_method:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def _root_name(node: ast.AST) -> str | None:
    """取属性链最左侧的名字 (blk.Length -> 'blk'), 非简单名字返回 None."""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _attr_chain(node: ast.AST) -> list[str]:
    """收集 Attribute 链上的属性名, 如 s.Parts.Open -> ['s','Parts','Open']."""
    names: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        names.append(cur.id)
    return names


def _is_none_literal(node: ast.AST) -> bool:
    """判断是否为 None 字面量 (Python 3.8+ 中 ast.Constant)."""
    return isinstance(node, ast.Constant) and node.value is None


def _is_int_literal(node: ast.AST) -> bool:
    """是否为 int 字面量 (排除 bool, Python 中 bool 是 int 子类)."""
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool))


def _is_float_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, float)


def _is_number_literal(node: ast.AST) -> bool:
    return _is_int_literal(node) or _is_float_literal(node)


def _waived(lines: list[str], lineno: int) -> bool:
    """该行行尾或上一行是否有 '# check_journal: expected-raise' 豁免标记."""
    marker = "check_journal: expected-raise"
    for idx in (lineno - 1, lineno - 2):
        if 0 <= idx < len(lines) and marker in lines[idx]:
            return True
    return False


def _is_point3d_construction(node: ast.AST) -> bool:
    """Point3d(...) 构造调用 (CreatePoint(Point3d(...)) 这种包了一层的不算)."""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("Point3d", "Point3d_Struct"))


# 需要 NXOpen.Point 对象、给 Point3d 会报 "Expecting NXOpen.Point type, found
# NXOpen.Point3d" 的属性白名单。只收已验证的属性名, 不做通用启发式 ——
# 反例: SectionLineOnlyPlacementOrigin 就明确收 Point3d。
POINT_OBJECT_PROPS = (
    "RotationPoint",      # Drawings.SectionLineSegmentsBuilder
    "BoundaryPoint1",     # Drawings.DetailViewBuilder
    "BoundaryPoint2",
    "MassCenter",         # Motion 质量属性 (类型不符在 try/except 内会静默失败)
    "FromLocationPoint",  # GeometricUtilities.GeneralPattern
)


def check(path: Path) -> int:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    issues: list[str] = []
    warnings: list[str] = []

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        hint = ""
        low = text.lower()
        if re.search(r"(savecomponents|closeaftersave)\.(true|false)\b(?!value)", low):
            hint = ("\n  -> 若是 BasePart.SaveComponents.True / CloseAfterSave.False: 其成员是 "
                    "TrueValue / FalseValue (裸 True/False 是 Python 关键字), "
                    "或改用 NXOpen.UF.UFSession.GetUFSession().Part.Save()")
        print(f"[错误] 语法错误: {exc}{hint}")
        return 1

    src_lower = text.lower()
    # 探针类文件（故意演示坑位）可在文件内声明豁免：
    #   # check_journal: allow-probes
    allow_probes = "check_journal: allow-probes" in src_lower
    for marker in ("todo", "fixme", "placeholder", "pass  #"):
        if marker in src_lower:
            issues.append(f"发现占位符/待办标记: {marker}")

    if "def main(" not in text:
        warnings.append("未找到 def main(): NXOpen journal 建议包含 main() 入口")
    if "import nxopen" not in src_lower:
        warnings.append("未找到 NXOpen import, journal 可能无法运行")

    for needle in ("session.getsession", "parts.work", "ui.getui"):
        if needle not in src_lower:
            warnings.append(f"未找到常见模板要素 '{needle}' (可能不需要)")

    # ---- 已固化坑位检查 ----

    # 5.1 builder 创建传 None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in BUILDER_NULL:
                if len(node.args) == 1 and _is_none_literal(node.args[0]):
                    issues.append(
                        f"第 {node.lineno} 行: {attr}(None) 不可用(NX12 Python 封装), "
                        f"改用 {BUILDER_NULL[attr]}"
                    )
            elif attr == "Open" and "Parts" in _attr_chain(node.func):
                if len(node.args) != 1:
                    issues.append(
                        f"第 {node.lineno} 行: Parts.Open 只传 1 个参数, "
                        f"返回 (part, loadStatus) 元组 (当前传 {len(node.args)} 个)"
                    )
            elif attr == "ToArray" and any(
                n in _attr_chain(node.func) for n in ("Bodies", "DrawingSheets", "DraftingViews")
            ):
                issues.append(
                    f"第 {node.lineno} 行: {'/'.join(('Bodies','DrawingSheets','DraftingViews'))} "
                    f"在 NX12 Python 封装没有 ToArray(), 直接迭代 for x in part.X"
                )
            elif attr == "ReplaceRules":
                if len(node.args) >= 2:
                    second = node.args[1]
                    if isinstance(second, ast.Constant) and second.value is True:
                        issues.append(
                            f"第 {node.lineno} 行: ReplaceRules 第二参数必须 False(立即求值), "
                            f"True 会选中 0 条边导致特征创建失败"
                        )
            elif attr in ("Point3d", "Vector3d"):
                # 坐标必须 float, 传 int 报 "Expecting double type, found int"
                if allow_probes:
                    continue
                for a in node.args:
                    if _is_int_literal(a):
                        issues.append(
                            f"第 {node.lineno} 行: {attr} 收到 int 字面量 -> NX12 报 "
                            f"'Expecting double type, found int', 改写为 float (0 -> 0.0)"
                        )
                        break
            elif attr == "SetOriginAndLengths" and len(node.args) >= 4:
                # 第 2-4 参数(三个长度)必须 str, 传 float 报 "Expecting str type"
                if allow_probes:
                    continue
                if any(_is_float_literal(a) for a in node.args[1:4]):
                    issues.append(
                        f"第 {node.lineno} 行: SetOriginAndLengths 长度参数必须 str (\"100\"), "
                        f"传 float (100.0) 报 'Expecting str type, found float'"
                    )
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            warnings.append(f"第 {node.lineno} 行: 裸 except, 建议限定异常类型并记录日志")

    # 5.20 两处"类型不符"坑位, 都只报错不静默:
    #   - Expression 属性 (.RightHandSide) 必须给字符串, 给数字报
    #     "Expecting Unicode str type, found int" (NumberOfSides);
    #   - 需要 Point 对象的属性给 Point3d 报 "Expecting NXOpen.Point type,
    #     found NXOpen.Point3d" (SectionLineSegments.RotationPoint)。
    # 负向对照(故意写错并断言必抛)可在该行行尾写豁免标记:
    #   # check_journal: expected-raise
    if not allow_probes:
        src_lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                if _waived(src_lines, node.lineno):
                    continue
                if tgt.attr == "RightHandSide" and _is_number_literal(node.value):
                    issues.append(
                        f"第 {node.lineno} 行: {tgt.attr} 是 Expression, 必须给字符串 "
                        f'(如 "{node.value.value}"), 给数字报 '
                        f"'Expecting Unicode str type, found int/float'"
                    )
                elif (tgt.attr in POINT_OBJECT_PROPS
                      and _is_point3d_construction(node.value)):
                    issues.append(
                        f"第 {node.lineno} 行: {tgt.attr} 需要 NXOpen.Point 对象, "
                        f"直接给 Point3d 报 'Expecting NXOpen.Point type, found "
                        f"NXOpen.Point3d'; 改写为 part.Points.CreatePoint(Point3d(...))"
                    )

    # 5.2 FileNew: 只在实际调用时检查 Units 与 .prt
    has_filenew_call = re.search(r"\.FileNew\s*\(", text) is not None
    if has_filenew_call:
        if not re.search(r"\.Units\s*=", text):
            issues.append("FileNew 未设置 .Units (如 NXOpen.Part.Units.Millimeters) -> Commit 报模板不存在")
        for m in re.finditer(r"\.NewFileName\s*=\s*[\"']([^\"']*)[\"']", text):
            name = m.group(1)
            # CAE 模板产物是 .fem/.sim (FemNxNastranMetric/SimNxNastranMetric)
            if not name.lower().endswith((".prt", ".fem", ".sim")):
                issues.append(
                    f"第 {text[:m.start()].count(chr(10)) + 1} 行: "
                    f"NewFileName 必须带 .prt/.fem/.sim 后缀 (当前: {name})"
                )

    # 5.3 BasePart.SaveComponents / CloseAfterSave: True/False 是 Python 关键字
    # 5.3 裸 .True / .False 本身是 Python 语法错误，会在 ast.parse 处被拦截并给出提示（见上）；
    #     .TrueValue / .FalseValue 才是正确写法（可用），此处不再重复检查。

    # 5.4 批处理: Open 后 SetWork 会报 No Displayed Part
    if ".parts.open(" in src_lower and ".parts.setwork(" in src_lower:
        warnings.append(
            "同时出现 Parts.Open 与 Parts.SetWork: 批处理中 Open 后无显示部件, SetWork 会报 "
            "No Displayed Part; 改用 NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(part.Tag)"
        )

    # 5.5 AST 变量级判定: Block/Cylinder 尺寸属性只读
    #     旧实现按文件级正则匹配 ".Length ="：只要文件里出现 CreateBlockFeatureBuilder,
    #     同文件里别的对象的同名属性也会被误报, 例如表达式 exp.Length = "5"、
    #     HolePackage 的 hp.Diameter = 10.0。现与 5.9/5.14 对齐, 只在 builder 变量本身
    #     被赋只读属性时报错。
    readonly_vars: dict[str, str] = {}
    for create_method in READONLY_BUILDER_PROPS:
        for var in _builder_vars(tree, create_method):
            readonly_vars[var] = create_method
    if not allow_probes:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                create_method = readonly_vars.get(_root_name(tgt) or "")
                if create_method and tgt.attr in READONLY_BUILDER_PROPS[create_method]:
                    if create_method == "CreateCylinderBuilder":
                        hint = ('改用 b.Diameter.RightHandSide = "..." / '
                                'b.Height.RightHandSide = "..." (Expression 通道), '
                                '并设 b.Type/b.Origin/b.Direction')
                    else:
                        hint = ("改用 Set%s(...) / SetOriginAndLengths(...)"
                                % tgt.attr)
                    issues.append(
                        f"第 {node.lineno} 行: {create_method} 的 {tgt.attr} 属性只读 "
                        f"(NX12 Python 实测 AttributeError), {hint}"
                    )

    # 5.6  RevolveBuilder 批处理不可用
    if "createrevolvebuilder" in src_lower:
        warnings.append(
            "检测到 CreateRevolveBuilder: 本机 NX12 批处理实测 CommitFeature 报 "
            "'Internal error: memory access violation'; 批处理改用 "
            "ufs.Modl.CreateRevolved(tags, ['0','360'], origin, dir, NXOpen.UF.ModlFeatureSigns.NULLSIGN)"
        )

    # 5.7 (扩充 UFDraw) UF 枚举名
    if re.search(r"\bFeatureSigns\b", text) and "ModlFeatureSigns" not in text:
        issues.append(
            "检测到 NXOpen.UF.FeatureSigns: NX12 Python 封装不存在该枚举, "
            "改用 NXOpen.UF.ModlFeatureSigns (成员如 POSITIVE / NULLSIGN)"
        )
    if re.search(r"\bNXOpen\.UF\.UFDraw\b", text):
        issues.append(
            "检测到 NXOpen.UF.UFDraw: NX12 Python 封装无可导入该名 "
            "(AttributeError: module 'NXOpen.UF' has no attribute "
            "'UFDraw'); UF 的枚举挂在会话对象上 —— 用 "
            "ufs = NXOpen.UF.UFSession.GetUFSession() 后取 ufs.Draw.ProjDir."
            "PROJECT_BELOW / PROJECT_RIGHT、ufs.Draw.SxsegType.SXSEG_CUT, "
            "且这些位置的参数不接受裸 int"
        )
    if re.search(r"\bNXOpen\.UF\.UFMotion\b", text) or re.search(
            r"from\s+NXOpen\.UF\s+import\s+UFMotion", text):
        issues.append(
            "检测到 NXOpen.UF.UFMotion: 不可导入 ("
            "AttributeError: module 'NXOpen.UF' has no attribute 'UFMotion'); "
            "枚举走 ufs = NXOpen.UF.UFSession.GetUFSession() 后的 ufs.Motion.*, "
            "struct 类型则是模块级 NXOpen.UF.<名>_Struct "
            "(如 NXOpen.UF.MotionInterference_Struct), 且 out 参数是返回值 "
            "(st = ufs.Motion.InitInterferenceStruct() 必须 0 参调用)"
        )

    # 5.8  装配枚举
    if "componentassembly.components" in src_lower:
        issues.append(
            "ComponentAssembly.Components 不存在 (NX12 Python 封装), "
            "改用 assy.ComponentAssembly.RootComponent.GetChildren()"
        )

    # 5.9  BlockFeatureBuilder 的 BooleanOption 被静默忽略（AST 精确判定：
    #     只在该 builder 的变量本身被赋 .BooleanOption 时报错，避免与 Boolean 特征误报）
    block_vars = _builder_vars(tree, "CreateBlockFeatureBuilder")
    for node in ast.walk(tree):
        if allow_probes:
            break
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute):
            tgt = node.targets[0]
            if tgt.attr in ("BooleanOption", "Type", "SetTargetBodies"):
                root_id = _root_name(tgt)
                if root_id and root_id in block_vars:
                    issues.append(
                        f"第 {node.lineno} 行: BlockFeatureBuilder({root_id}) 设置 "
                        f"BooleanOption 在 NX12 会被静默忽略 (求差不生效且无异常, 体数 +1); "
                        f"改用 SetBooleanOperationAndTarget(BooleanType.Subtract, target)"
                    )
                    break
    for node in ast.walk(tree):
        if allow_probes:
            break
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "SetTargetBodies":
                root_id = _root_name(node.func.value)
                if root_id and root_id in block_vars:
                    issues.append(
                        f"第 {node.lineno} 行: BlockFeatureBuilder({root_id}) 的 BooleanOption."
                        f"SetTargetBodies 在 NX12 不生效; 改用 SetBooleanOperationAndTarget"
                    )
                    break

    # 5.10  NX12 无螺纹特征 builder
    if not allow_probes and ("createthreadbuilder" in src_lower or "features.thread.null" in src_lower):
        issues.append(
            "NX12 不存在 Features.Thread / CreateThreadBuilder (NX 2506 专属); "
            "螺纹孔走 HolePackageBuilder 的 Thread* 选项, 或打底孔后交互加螺纹"
        )

    # 5.11  STEP 导出未设同步标志
    if not allow_probes and "createstepcreator" in src_lower and "processholdflag" not in src_lower:
        warnings.append(
            "使用 StepCreator 但未设 ProcessHoldFlag=True: 实测 Commit() 返回时 .stp 尚未落盘 "
            "(约 3 秒后才出现), 随即校验存在性会误判失败; 建议显式设 True"
        )

    # 5.12  去参销毁特征树, 违背历史模式铁律
    if not allow_probes and "createremoveparametersbuilder" in src_lower:
        warnings.append(
            "检测到 CreateRemoveParametersBuilder: 去参会销毁特征树, 违背'必须历史模式'铁律, "
            "仅用户明确要求哑实体时才可用"
        )

    # 5.13  长 journal 的 Save 缺落盘校验（仅对 >120 行的多阶段脚本提示，避免短脚本噪声）
    if not allow_probes and text.count("\n") > 120 and "save(" in src_lower and "getsize" not in src_lower:
        warnings.append(
            "长 journal 内有 Save 但无落盘校验: 阶段保存后应 "
            "assert os.path.exists(path) and os.path.getsize(path) > 0 (见 SKILL.md §3)"
        )

    # 5.14  DraftBuilder.Method 只读 + 容差默认 0 必须显式设
    draft_vars = _builder_vars(tree, "CreateDraftBuilder")
    if not allow_probes and draft_vars:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute):
                tgt = node.targets[0]
                if tgt.attr == "Method":
                    root_id = _root_name(tgt)
                    if root_id and root_id in draft_vars:
                        issues.append(
                            f"第 {node.lineno} 行: DraftBuilder({root_id}).Method 是只读属性 "
                            f"(AttributeError: object attribute 'Method' is read-only); "
                            f"改用 DraftIsoclineOrTruedraft = "
                            f"NXOpen.Features.DraftBuilder.Method.TrueDraft"
                        )
                        break
        if not re.search(r"\.AngleTolerance\s*=", text):
            warnings.append(
                "使用 CreateDraftBuilder 但未设 .AngleTolerance: 默认 0.0, Commit 报 "
                "'Angle tolerance is too small'; 建议显式设 0.5 (见 modeling.md §3.4)"
            )

    # 5.15  ShellBuilder.Tolerance 默认 0 必须显式设
    if not allow_probes and "createshellbuilder" in src_lower:
        if not re.search(r"\.Tolerance\s*=", text):
            warnings.append(
                "使用 CreateShellBuilder 但未设 .Tolerance: 默认 0.0, Commit 报 "
                "'Tolerance error'; 建议显式设 0.01 (见 modeling.md §3.4)"
            )

    # 5.16  journal 解释器 = NX12 内嵌 Python 3.6.1, 拦截 3.7+ 专属 API
    # 依据 (探针 journal): sys.version = 3.6.1 (v3.6.1:69c0db5, Mar 21 2017),
    # sys.hexversion = 0x030601. Host python (3.12) preview will pass,
    # 但 NX 回放报 AttributeError —— 不要在这条路线上尝试。
    # 用 AST 取真实调用/属性访问, 避免注释/字符串里提到名字就误报
    # (如本技能 tests/18 的注释 "不用 math.dist")。
    PY36_TRAPS = {
        ("math", "dist"): "3.8+; 用 math.hypot(dx, dy) 或 sqrt(dx**2 + dy**2)",
        ("math", "prod"): "3.8+; 用 functools.reduce(operator.mul, xs, 1)",
        ("math", "isqrt"): "3.8+; 用 int(math.sqrt(n))",
        ("math", "comb"): "3.8+; 用 math.factorial 自行组合",
        ("math", "perm"): "3.8+; 同上",
        ("math", "nextafter"): "3.9+",
        ("functools", "cache"): "3.9+; 用 functools.lru_cache(maxsize=None)",
        ("functools", "cached_property"): "3.8+",
        ("itertools", "pairwise"): "3.10+; 用 zip(xs, xs[1:])",
    }
    # 被 import 的名字 -> 其来源模块 (只认 from X import Y 与 import X)
    alias_mod = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                alias_mod[a.asname or a.name] = node.module.split(".")[0]
        elif isinstance(node, ast.Import):
            for a in node.names:
                alias_mod[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            v = node.value
            if isinstance(v, ast.Name):
                mod = alias_mod.get(v.id, v.id)
                hit = PY36_TRAPS.get((mod, node.attr))
                if hit:
                    issues.append(
                        f"第 {node.lineno} 行: journal 解释器是 NX12 内嵌 Python 3.6.1, "
                        f"{mod}.{node.attr} 不支持 ({hit})"
                    )
        # from math import dist 后直接 dist(a, b): AST 里是 Name 调用, 上面只看
        # Attribute 会漏。只在"作为调用被使用"时判, 避免
        # 把 import 行本身或同名局部变量误报。
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            mod = alias_mod.get(node.func.id)
            if mod:
                hit = PY36_TRAPS.get((mod, node.func.id))
                if hit:
                    issues.append(
                        f"第 {node.lineno} 行: journal 解释器是 NX12 内嵌 Python 3.6.1, "
                        f"from {mod} import {node.func.id} 后调用不支持 ({hit})"
                    )
    # str.removeprefix/removesuffix (3.9+) 与方法名撞车风险高, 只在确认为字符串变量时提示
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("removeprefix", "removesuffix"):
            warnings.append(
                f"第 {node.lineno} 行: str.{node.func.attr} 是 Python 3.9+, "
                f"journal 解释器为 3.6.1; 改用 re.sub 或切片"
            )

    # 5.17 (motion.md M.5a) 枚举访问器带 () 调用
    # NX12 Python 封装里这些枚举是"属性", 带 () 调用直接 TypeError/崩溃。
    # 只收已验证的名字, 不做通用启发式 (Types 太通用, 0 参调用才算命中)。
    ENUM_ACCESSOR_PROPS = ("Types", "HoleDepthOptions", "AttachmentType")
    for node in ast.walk(tree):
        if allow_probes:
            break
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ENUM_ACCESSOR_PROPS
                and not node.args and not node.keywords):
            issues.append(
                f"第 {node.lineno} 行: {node.func.attr}() 是枚举属性, 带 () 调用会崩; "
                f"直接读属性或赋成员 (如 .Types = NXOpen...Types.成员) "
                f"(见 motion.md M.5a / modeling.md §4.4)"
            )

    # 5.18  CylinderBuilder.Types 成员名
    # NX12 只有 ArcAndHeight / AxisDiameterAndHeight, 无 AxisAndHeight
    # (AxisAndHeight 是 .NET 文档名, Python 封装不存在)。
    if not allow_probes and re.search(
            r"CylinderBuilder\.Types\.AxisAndHeight\b", text):
        issues.append(
            "CylinderBuilder.Types.AxisAndHeight 不存在 (NX12 Python 封装只有 "
            "ArcAndHeight / AxisDiameterAndHeight); 改用 AxisDiameterAndHeight"
        )

    # 5.19 NXOpen.UF 没有 UFDrf 容器
    # 装配图气泡符号用例实际踩中: NXOpen.UF.UFDrf → AttributeError。
    # 正确入口是 ufs.Drf (UFSession.GetUFSession().Drf) / NXOpen.UF.Drf 属性。
    if not allow_probes and (
            re.search(r"\bNXOpen\.UF\.UFDrf\b", text)
            or re.search(r"from\s+NXOpen\.UF\s+import\s+[^\n]*\bUFDrf\b", text)):
        issues.append(
            "NXOpen.UF 没有 UFDrf 容器 (运行时报 AttributeError); "
            "改用 ufs.Drf (ufs = NXOpen.UF.UFSession.GetUFSession())"
        )

    for w in warnings:
        print(f"[提示] {w}")
    for i in issues:
        print(f"[错误] {i}")
    if issues:
        return 1
    print(f"[OK] {path} 通过静态检查 ({len(text.splitlines())} 行)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="NXOpen journal 静态检查")
    ap.add_argument("path", type=Path, help="journal .py 文件路径")
    args = ap.parse_args()
    if not args.path.exists():
        print(f"[错误] 文件不存在: {args.path}")
        sys.exit(1)
    sys.exit(check(args.path))


if __name__ == "__main__":
    main()