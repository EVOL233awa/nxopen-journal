# -*- coding: utf-8 -*-
"""NXOpen journal 静态检查（无需 NX 环境）。

检查项:
  1. Python 语法 (ast.parse)
  2. TODO/FIXME/占位符
  3. main() 入口与 NXOpen import（提示性）
  4. 裸 except（提示性）
  5. 已固化坑位（NX 12 批处理验证）:
     5.1a 创建 builder 传 None -> 必须用 NXOpen.Features.Feature.Null / BooleanFeature.Null
     5.1b PartCollection.Open 参数个数 -> 只传 1 个参数, 返回 (part, loadStatus) 元组
     5.1c BodyCollection/DrawingSheets/DraftingViews 无 ToArray(), len(集合) 也不存在
          -> 直接迭代
     5.1d ScCollector.ReplaceRules -> 2 参重载第二参是 createRulesWoUpdate, 与选择集无关;
          排除实体走 3 参 negatedEntities([DisplayableObject]);
          1 参报 TypeError: No overload matches these arguments
     5.1e Point3d/Vector3d 传 int -> TypeError, 必须传 float (含 from NXOpen import Point3d 的短形式)
     5.1f SetOriginAndLengths 长度传数字 -> TypeError, 必须传 str
     5.2  FileNew 未设 Units 或 NewFileName 不带 .prt -> Commit 必然报错
          (Units 按 FileNew builder 变量作用域判, 同文件里别的对象的 .Units 不算;
           NewFileName 非字面量时只提示, 不拦)
     5.3  BasePart.SaveComponents/CloseAfterSave -> 成员是 TrueValue/FalseValue,
          裸 True/False 是 Python 关键字 -> 在语法层拦并给定点提示
     5.4  Parts.Open 与 Parts.SetWork 同时出现 -> 批处理中会报 No Displayed Part
     5.5  BlockFeatureBuilder.Length/Width/Height 只读 -> 用 SetLength/SetOriginAndLengths
          (AST 变量级判定: 只在该 builder 变量本身被赋值时报错,
           同文件里别的对象同名属性不再误报)
     5.6  CreateRevolveBuilder 批处理 CommitFeature 内存违例 -> 用 UF Modl.CreateRevolved
     5.7  NXOpen.UF.FeatureSigns 不存在 -> 用 NXOpen.UF.ModlFeatureSigns
          (AST 判定: 注释/字符串里出现该名不算, 也不会被别处的 ModlFeatureSigns 静音);
          NXOpen.UF.UFMotion / NXOpen.UF.UFDraw 不可导入 -> 会话对象 ufs.Motion / ufs.Draw
          (UF struct 按所属组查: NXOpen.UF.<组>.<名>, 如 Curve.SectionGeneralData;
           运动模块部分为顶层 NXOpen.UF.<名>_Struct, 如 MotionInterference_Struct)
     5.8  ComponentAssembly.Components 不存在 -> 用 RootComponent.GetChildren()
     5.9  BlockFeatureBuilder.BooleanOption 被静默忽略 -> 用 SetBooleanOperationAndTarget
     5.10 NX12 无 Features.Thread / CreateThreadBuilder -> 用 HolePackage 螺纹选项
     5.11 StepCreator 未设 ProcessHoldFlag -> Commit 返回时文件尚未落盘(约 5 秒后才有)
     5.12 RemoveParametersBuilder -> 销毁特征树, 违背历史模式铁律
     5.13 有 Save/SaveAs 但保存后无落盘校验 -> 用 nxlib.session.save_checked(path),
          或 assert os.path.exists(path) and os.path.getsize(path) > 0
     5.14a DraftBuilder.Method 只读 -> 用 DraftIsoclineOrTruedraft
     5.14b DraftBuilder.AngleTolerance 默认 0.0 -> 必须显式设
     5.15 ShellBuilder.Tolerance 默认 0.0 -> 必须显式设
          (5.14b/5.15 同样按 builder 变量作用域判, 别的对象的 .Tolerance = 顶不掉)
     5.16 journal 解释器是 Python 3.6.1 -> 不用 math.dist/prod/isqrt/comb/perm/nextafter、
          functools.cache/cached_property、itertools.pairwise、str.removeprefix/removesuffix
     5.17 Types / HoleDepthOptions / AttachmentType 是枚举属性, 带 () 调用会崩 -> 直接读属性
     5.18 CylinderBuilder.Types 无 AxisAndHeight (.NET 文档名) -> 用 AxisDiameterAndHeight
     5.19 NXOpen.UF 没有 UFDrf 容器 -> 用 ufs.Drf (UFSession.GetUFSession().Drf)
     5.20 Expression 属性 (.RightHandSide) 必须给字符串; 需要 Point 的属性给 Point3d 报类型不符

豁免标记:
  `# check_journal: allow-probes` 跳过 5.1e/5.1f、5.5、5.9、5.10、5.11、5.12、5.13、
  5.14a/5.14b、5.15、5.17、5.18、5.19、5.20；
  `# check_journal: expected-raise` 覆盖 5.1a-5.1f、5.5、5.9、5.14a、5.17、5.20；
  两种标记都不放行：5.2、5.3（语法层）、5.7、5.8、5.16（5.1a-5.1d 只认 expected-raise）。

用法:
  python check_journal.py path/to/journal.py
退出码: 0 = 通过(可含提示), 1 = 语法错误或占位符/已固化坑位
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
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


def _target_names(target: ast.AST) -> list[str]:
    """展开赋值目标里的名字 (含元组/列表解包): (blk,) = ... -> ['blk']."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _is_create_call(node: ast.AST, create_method: str) -> bool:
    """`X.<create_method>(...)` 形式的 builder 创建调用."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == create_method)


def _iter_payloads(node: ast.AST) -> list[ast.AST]:
    """for/推导式 iterable 里可能绑定到目标的取值表达式 (展开元组/列表/集合字面量)."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out: list[ast.AST] = []
        for elt in node.elts:
            out.extend(_iter_payloads(elt))
        return out
    return [node]


def _bound_names(value: ast.AST, target: ast.AST, create_method: str) -> list[str]:
    """值 -> 目标的一对绑定: 值是创建调用时返回目标里的名字.

    解包按位置配对: `blk, rest = CreateBlockFeatureBuilder(...), other()` 只收 blk;
    `(blk,) = CreateBlockFeatureBuilder(...),` 是同一个坑位的另一种写法。
    """
    if _is_create_call(value, create_method):
        return _target_names(target)
    if not isinstance(value, (ast.Tuple, ast.List)):
        return []
    if isinstance(target, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
        names: list[str] = []
        for tgt, val in zip(target.elts, value.elts):
            names.extend(_bound_names(val, tgt, create_method))
        return names
    return []


def _builder_vars(tree: ast.AST, create_method: str) -> set[str]:
    """收集由某 builder 创建方法绑定得到的变量名 (如 blk = ...CreateBlockFeatureBuilder(...)).

    规则 5.5/5.9/5.14 都只在该 builder 变量本身被误用时报警——按变量作用域判定,
    不做文件级文本匹配, 否则同文件里别的对象的同名属性会误报。
    绑定形式不限 `名 = 调用(...)`: 带注解的赋值、with-as、for/推导式目标、元组解包
    是同一个坑位, 少收一种写法就整条规则静默漏判。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                names.update(_bound_names(node.value, t, create_method))
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                names.update(_bound_names(node.context_expr, node.optional_vars,
                                          create_method))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            if any(_is_create_call(v, create_method)
                   for v in _iter_payloads(node.iter)):
                names.update(_target_names(node.target))
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


def _unwrap_sign(node: ast.AST) -> ast.AST:
    """剥掉一元 +/-: AST 里 -1 是 UnaryOp(USub, Constant(1)), 不是 Constant."""
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        node = node.operand
    return node


def _is_int_literal(node: ast.AST) -> bool:
    """是否为 int 字面量 (排除 bool, Python 中 bool 是 int 子类)."""
    node = _unwrap_sign(node)
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool))


def _is_float_literal(node: ast.AST) -> bool:
    node = _unwrap_sign(node)
    return isinstance(node, ast.Constant) and isinstance(node.value, float)


def _is_number_literal(node: ast.AST) -> bool:
    return _is_int_literal(node) or _is_float_literal(node)


def _number_text(node: ast.AST) -> str:
    """数字字面量的写法, 用于提示 (-20 在 AST 里是 UnaryOp, 没有 .value 可读)."""
    negatives = 0
    while isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        if isinstance(node.op, ast.USub):
            negatives += 1
        node = node.operand
    return ("-" if negatives % 2 else "") + str(getattr(node, "value", node))


# 规则 5.3: `.True` / `.False` 不是合法 Python 属性名, 带它的文件解析不过 ——
# 提示挂在语法层 (ast.parse 的 except 分支), 没有可再判的 AST, 故不重复报。
SAVE_KEYWORD_RE = re.compile(
    r"(savecomponents|closeaftersave)\s*\.\s*(true|false)\b(?!value)", re.I)


def _savecomponents_hint(text: str) -> str:
    """规则 5.3 的定点提示: 成员名是 TrueValue/FalseValue, 不是裸 True/False。"""
    if not SAVE_KEYWORD_RE.search(text):
        return ""
    return ("\n  -> 若是 BasePart.SaveComponents.True / CloseAfterSave.False: 其成员是 "
            "TrueValue / FalseValue (裸 True/False 是 Python 关键字), "
            "或改用 NXOpen.UF.UFSession.GetUFSession().Part.Save()")


def _var_attr_assigned(tree: ast.AST, var_names: set[str], attr: str) -> bool:
    """变量集合里是否有人被赋过 `var.<attr> = ...` (5.14b/5.15 的作用域判据)。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Attribute) and tgt.attr == attr
                    and _root_name(tgt) in var_names):
                return True
    return False


def _attr_assign_targets(tree: ast.AST) -> list[tuple[int, ast.Attribute]]:
    """收集 `X.attr = ...` / `X.attr: t = ...` 的目标, 产出 (行号, 属性节点)。

    链式赋值 (a = b.c = ...) 的每个目标都收: 只看 targets[0] 会漏掉后一个。
    """
    out: list[tuple[int, ast.Attribute]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Attribute):
                out.append((node.lineno, tgt))
    return out


def _attr_assigned_true(tree: ast.AST, attr: str) -> bool:
    """是否存在 `X.<attr> = True` 赋值 (5.11 要求显式设 True, 赋别的值不算)。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        else:
            continue
        if not (isinstance(value, ast.Constant) and value.value is True):
            continue
        if any(isinstance(t, ast.Attribute) and t.attr == attr for t in targets):
            return True
    return False


COLLECTION_PROPS = ("Bodies", "Features", "DrawingSheets", "DraftingViews",
                    "Components", "Expressions")


def _is_collection_len(node: ast.AST) -> bool:
    """`len(<obj>.Bodies/.Features/...)` —— 集合没有 __len__, 直接迭代。"""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "len"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Attribute)
            and node.args[0].attr in COLLECTION_PROPS)


def _waived(comments: dict[int, str], lineno: int) -> bool:
    """该行行尾或上一行是否有 '# check_journal: expected-raise' 豁免标记.

    只认注释 token: 字符串/docstring 里出现同样文字不算豁免。
    """
    marker = "check_journal: expected-raise"
    for line in (lineno, lineno - 1):
        if marker in comments.get(line, ""):
            return True
    return False


def _is_point3d_construction(node: ast.AST) -> bool:
    """Point3d(...) 构造调用 (CreatePoint(Point3d(...)) 这种包了一层的不算).

    两种写法同源: `NXOpen.Point3d(...)` 与 `from NXOpen import Point3d` 之后的
    `Point3d(...)` —— 后者 AST 里是 Name 调用, 只看 Attribute 会漏。
    """
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr in ("Point3d", "Point3d_Struct")
    return isinstance(fn, ast.Name) and fn.id in ("Point3d", "Point3d_Struct")


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
        # NX12 内嵌解释器是 Python 3.6.1；宿主机 3.12 的默认语法会放过
        # walrus / positional-only / match 等 3.7+ 语法，必须按 3.6 解析。
        tree = ast.parse(text, filename=str(path), feature_version=(3, 6))
    except SyntaxError as exc:
        print(f"[错误] 语法错误: {exc}{_savecomponents_hint(text)}")
        return 1

    src_lower = text.lower()
    # 豁免标记只认注释 token：字符串里出现同样文字不是豁免声明。
    comments: dict[int, str] = {}
    # 占位符只看注释 token 与真正的 raise NotImplementedError；字符串常量里
    # 出现 TODO 是测试反例/文档，不是待办。也不再把合法的 `pass  # ...` 当占位。
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            low = tok.string.lower()
            comments[tok.start[0]] = comments.get(tok.start[0], "") + low
            for marker in ("todo", "fixme", "placeholder"):
                if marker in low:
                    issues.append(
                        f"第 {tok.start[0]} 行: 发现占位符/待办标记: {marker}")
    except (tokenize.TokenError, IndentationError):
        pass
    # 探针类文件（故意演示坑位）可在注释中声明豁免：
    #   # check_journal: allow-probes
    allow_probes = any("check_journal: allow-probes" in c for c in comments.values())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        name = None
        if isinstance(exc, ast.Name):
            name = exc.id
        elif isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
            name = exc.func.id
        if name == "NotImplementedError":
            issues.append(f"第 {node.lineno} 行: raise NotImplementedError 是占位实现")

    if "def main(" not in text:
        warnings.append("未找到 def main(): NXOpen journal 建议包含 main() 入口")
    if "import nxopen" not in src_lower:
        warnings.append("未找到 NXOpen import, journal 可能无法运行")

    for needle in ("session.getsession", "parts.work"):
        if needle not in src_lower:
            warnings.append(f"未找到常见模板要素 '{needle}' (可能不需要)")

    # ---- 已固化坑位检查 ----

    # 5.1 builder 创建传 None 等按行定位的 AST 规则。
    # 行尾 `# check_journal: expected-raise` 对这一组同样生效（负向对照用例常写在
    # 5.1 系列的反例行上，见 SKILL.md §4）。
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is not None and _waived(comments, lineno):
            continue
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
                # 2 参重载 (rules, createRulesWoUpdate) 的 bool 与选择集无关, 两侧都合法;
                # 1 参缺 createRulesWoUpdate, 报 No overload matches these arguments;
                # 3 参重载第 2 位是 negatedEntities, 要对象列表, 传 bool 报 TypeError。
                if len(node.args) + len(node.keywords) < 2:
                    issues.append(
                        f"第 {node.lineno} 行: ReplaceRules 至少需要 2 个参数 "
                        f"(rules, createRulesWoUpdate); 1 参报 TypeError: "
                        f"No overload matches these arguments"
                    )
                if len(node.args) >= 3 and isinstance(node.args[1], ast.Constant) \
                        and isinstance(node.args[1].value, bool):
                    issues.append(
                        f"第 {node.lineno} 行: ReplaceRules 3 参重载第 2 位是 negatedEntities "
                        f"(要 DisplayableObject 列表), 传 bool 报 TypeError; "
                        f"排除实体用 ReplaceRules(rules, [实体], False)"
                    )
                for kw in node.keywords:
                    if kw.arg not in (None, "negatedEntities", "createRulesWoUpdate"):
                        issues.append(
                            f"第 {node.lineno} 行: ReplaceRules 没有参数名 {kw.arg!r}, "
                            f"签名是 (rules, negatedEntities, createRulesWoUpdate)"
                        )
                        break
            elif attr in ("Point3d", "Vector3d", "Point3d_Struct", "Vector3d_Struct"):
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
                # 第 2-4 参数(三个长度)必须 str, 传数字报 "Expecting str type"
                if allow_probes:
                    continue
                if any(_is_number_literal(a) for a in node.args[1:4]):
                    issues.append(
                        f"第 {node.lineno} 行: SetOriginAndLengths 长度参数必须 str (\"100\"), "
                        f"传数字 (100 / 100.0) 报 'Expecting str type, found int/float'"
                    )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("Point3d", "Vector3d"):
            # from NXOpen import Point3d 之后直接 Point3d(...) 是同一坑位, 短形式不能漏
            if not allow_probes:
                for a in node.args:
                    if _is_int_literal(a):
                        issues.append(
                            f"第 {node.lineno} 行: {node.func.id} 收到 int 字面量 -> NX12 报 "
                            f"'Expecting double type, found int', 改写为 float (0 -> 0.0)"
                        )
                        break
        elif _is_collection_len(node):
            issues.append(
                f"第 {node.lineno} 行: len({node.args[0].attr}) 报 "
                f"'object of type ... has no len()'; 集合直接迭代 for x in part.X"
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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                if _waived(comments, node.lineno):
                    continue
                if tgt.attr == "RightHandSide" and _is_number_literal(node.value):
                    issues.append(
                        f"第 {node.lineno} 行: {tgt.attr} 是 Expression, 必须给字符串 "
                        f'(如 "{_number_text(node.value)}"), 给数字报 '
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
    filenew_vars = _builder_vars(tree, "FileNew")
    if filenew_vars:
        # 判据挂在 FileNew 得到的 builder 变量上：同文件里别的对象的 .Units = 顶不掉它
        if not _var_attr_assigned(tree, filenew_vars, "Units"):
            issues.append("FileNew 未设置 .Units (如 NXOpen.Part.Units.Millimeters) -> Commit 报模板不存在")
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.AnnAssign):
                value, targets = node.value, [node.target]
            else:
                continue
            if value is None:
                continue
            for tgt in targets:
                if not (isinstance(tgt, ast.Attribute) and tgt.attr == "NewFileName"):
                    continue
                # CAE 模板产物是 .fem/.sim (FemNxNastranMetric/SimNxNastranMetric)
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    name = value.value
                    if not name.lower().endswith((".prt", ".fem", ".sim")):
                        issues.append(
                            f"第 {node.lineno} 行: NewFileName 必须带 .prt/.fem/.sim 后缀 "
                            f"(当前: {name})"
                        )
                else:
                    warnings.append(
                        f"第 {node.lineno} 行: NewFileName 不是字面量后缀，无法静态确认；"
                        f"运行时必须以 .prt/.fem/.sim 结尾"
                    )

    # 5.3 BasePart.SaveComponents / CloseAfterSave: 成员名是 TrueValue / FalseValue。
    #     裸 `.True` / `.False` 是 Python 关键字，文件根本解析不过 —— 这条在语法层
    #     实现（_savecomponents_hint()，见上面的 SyntaxError 分支），此处不重复判。

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
            if not isinstance(node, ast.Assign) or _waived(comments, node.lineno):
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
    #     FeatureSigns 用 AST 判：文本匹配既会被注释里出现的名字误报，
    #     也会被注释/字符串里随便写一个 ModlFeatureSigns 静音。
    bad_signs = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "FeatureSigns":
            # _attr_chain 由外向内: NXOpen.UF.FeatureSigns -> ['FeatureSigns','UF','NXOpen']
            if _attr_chain(node)[:2] == ["FeatureSigns", "UF"]:
                bad_signs = True
                break
        elif (isinstance(node, ast.ImportFrom) and node.module == "NXOpen.UF"
              and any(a.name == "FeatureSigns" for a in node.names)):
            bad_signs = True
            break
    if bad_signs:
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
    if not allow_probes:
        for lineno, tgt in _attr_assign_targets(tree):
            if _waived(comments, lineno):
                continue
            if tgt.attr in ("BooleanOption", "Type", "SetTargetBodies"):
                root_id = _root_name(tgt)
                if root_id and root_id in block_vars:
                    issues.append(
                        f"第 {lineno} 行: BlockFeatureBuilder({root_id}) 设置 "
                        f"{tgt.attr} 在 NX12 会被静默忽略 (求差不生效且无异常, 体数 +1); "
                        f"改用 SetBooleanOperationAndTarget(BooleanType.Subtract, target)"
                    )
                    break
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "SetTargetBodies" and not _waived(comments, node.lineno):
                    root_id = _root_name(node.func.value)
                    if root_id and root_id in block_vars:
                        issues.append(
                            f"第 {node.lineno} 行: BlockFeatureBuilder({root_id})."
                            f"SetTargetBodies 在 NX12 不生效 (求差不生效且无异常, 体数 +1); "
                            f"改用 SetBooleanOperationAndTarget(BooleanType.Subtract, target)"
                        )
                        break

    # 5.10  NX12 无螺纹特征 builder
    if not allow_probes and ("createthreadbuilder" in src_lower or "features.thread.null" in src_lower):
        issues.append(
            "NX12 不存在 Features.Thread / CreateThreadBuilder (NX 2506 专属); "
            "螺纹孔走 HolePackageBuilder 的 Thread* 选项, 或打底孔后交互加螺纹"
        )

    # 5.11  STEP 导出未设同步标志
    #      判据走 AST：文案要求"显式设 True"，写 False、只在注释/字符串里提该名都不算。
    if not allow_probes and "createstepcreator" in src_lower \
            and not _attr_assigned_true(tree, "ProcessHoldFlag"):
        issues.append(
            "使用 StepCreator 但未设 ProcessHoldFlag=True: Commit() 返回时 .stp 尚未落盘 "
            "(逐秒轮询: T+0.1s~T+4s 都不存在, T+5s 才出现), 随即校验存在性会误判失败; "
            "必须显式设 True"
        )

    # 5.12  去参销毁特征树, 违背历史模式铁律
    if not allow_probes and "createremoveparametersbuilder" in src_lower:
        warnings.append(
            "检测到 CreateRemoveParametersBuilder: 去参会销毁特征树, 违背'必须历史模式'铁律, "
            "仅用户明确要求哑实体时才可用"
        )

    # 5.13  Save/SaveAs 之后必须有落盘校验（save_checked 已内含存在性+大小断言）。
    #     判据走 AST：注释或字符串里写个 "getsize(" 顶不掉它；校验必须晚于最后一次
    #     保存，SaveAs 写死路径时校验的也必须是同一路径（校别的是"保存到哪个文件"）。
    if not allow_probes:
        saves: list[tuple[int, int, str | None]] = []
        checks: list[tuple[int, int, str | None]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            call_path = None
            if isinstance(fn, ast.Attribute) and fn.attr in ("Save", "SaveAs"):
                if fn.attr == "SaveAs" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        call_path = arg.value
                saves.append((node.lineno, node.col_offset, call_path))
            elif isinstance(fn, ast.Attribute) and fn.attr in ("getsize", "exists") \
                    and "path" in _attr_chain(fn):
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        call_path = arg.value
                checks.append((node.lineno, node.col_offset, call_path))
            elif isinstance(fn, ast.Name) and fn.id == "save_checked":
                # 该调用自身即"保存 + 校验"，同一位置同时记两条。
                saves.append((node.lineno, node.col_offset, call_path))
                checks.append((node.lineno, node.col_offset, call_path))
        if saves:
            last = max(saves, key=lambda s: (s[0], s[1]))
            verified = False
            for line, col, check_path in checks:
                if (line, col) < (last[0], last[1]):
                    continue
                # SaveAs 路径是字面量时，校验路径必须是同一字面量；校验路径
                # 不是字面量（变量）时无法静态确认，按可能命中处理。
                if last[2] is not None and check_path is not None \
                        and check_path != last[2]:
                    continue
                verified = True
                break
            if not verified:
                issues.append(
                    "有 Save/SaveAs 但保存后无落盘校验: 改用 nxlib.session.save_checked(path)，"
                    "或保存后 assert os.path.exists(path) and os.path.getsize(path) > 0 "
                    "(见 SKILL.md §3)"
                )

    # 5.14  DraftBuilder.Method 只读 + 容差默认 0 必须显式设
    draft_vars = _builder_vars(tree, "CreateDraftBuilder")
    if not allow_probes and draft_vars:
        for lineno, tgt in _attr_assign_targets(tree):
            if _waived(comments, lineno):
                continue
            if tgt.attr == "Method":
                root_id = _root_name(tgt)
                if root_id and root_id in draft_vars:
                    issues.append(
                        f"第 {lineno} 行: DraftBuilder({root_id}).Method 是只读属性 "
                        f"(AttributeError: object attribute 'Method' is read-only); "
                        f"改用 DraftIsoclineOrTruedraft = "
                        f"NXOpen.Features.DraftBuilder.Method.TrueDraft"
                    )
                    break
        if not _var_attr_assigned(tree, draft_vars, "AngleTolerance"):
            issues.append(
                "使用 CreateDraftBuilder 但未设 .AngleTolerance: 默认 0.0, Commit 报 "
                "'Angle tolerance is too small'; 必须显式设 0.5 (见 modeling.md §3.4)"
            )

    # 5.15  ShellBuilder.Tolerance 默认 0 必须显式设
    shell_vars = _builder_vars(tree, "CreateShellBuilder")
    if not allow_probes and shell_vars:
        if not _var_attr_assigned(tree, shell_vars, "Tolerance"):
            issues.append(
                "使用 CreateShellBuilder 但未设 .Tolerance: 默认 0.0, Commit 报 "
                "'Tolerance error'; 必须显式设 0.01 (见 modeling.md §3.4)"
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
    # 同一文件里被重新绑定过的名字（赋值 / def / class / 形参）不是模块对象：
    # `class M: dist = ...` + `math = M()` 之后 `math.dist(...)` 是本地对象的方法，
    # 按 math.dist 报 3.8+ 属于误报（规则头部注释承诺的正是"注释里提到名字不误报"）。
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            shadowed.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
        elif isinstance(node, ast.arg):
            shadowed.add(node.arg)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            v = node.value
            if isinstance(v, ast.Name) and v.id not in shadowed:
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
            if mod and node.func.id not in shadowed:
                hit = PY36_TRAPS.get((mod, node.func.id))
                if hit:
                    issues.append(
                        f"第 {node.lineno} 行: journal 解释器是 NX12 内嵌 Python 3.6.1, "
                        f"from {mod} import {node.func.id} 后调用不支持 ({hit})"
                    )
    # str.removeprefix/removesuffix (3.9+) 与方法名撞车风险高, 按方法名提示, 不解析接收者类型
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("removeprefix", "removesuffix"):
            issues.append(
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
        lineno = getattr(node, "lineno", None)
        if lineno is not None and _waived(comments, lineno):
            continue
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
    # (AxisAndHeight 是 .NET 文档名, Python 封装不存在)。判的是成员名本身:
    # `T = ...CylinderBuilder.Types` 再写 `T.AxisAndHeight` 是同一坑位, 别名挡不住。
    if not allow_probes:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "AxisAndHeight":
                issues.append(
                    "CylinderBuilder.Types.AxisAndHeight 不存在 (NX12 Python "
                    "封装只有 ArcAndHeight / AxisDiameterAndHeight); "
                    "改用 AxisDiameterAndHeight"
                )
                break

    # 5.19 NXOpen.UF 没有 UFDrf 容器
    # 装配图气泡符号用例实际踩中: NXOpen.UF.UFDrf → AttributeError。
    # 正确入口是 ufs.Drf (UFSession.GetUFSession().Drf) / NXOpen.UF.Drf 属性。
    if not allow_probes:
        bad_drf = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain = _attr_chain(node)
                if (len(chain) >= 3 and chain[-3:] == ["UFDrf", "UF", "NXOpen"]):
                    bad_drf = True
                    break
            elif isinstance(node, ast.ImportFrom):
                if (node.module == "NXOpen.UF" and
                        any(a.name == "UFDrf" for a in node.names)):
                    bad_drf = True
                    break
        if bad_drf:
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
