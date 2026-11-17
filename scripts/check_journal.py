# -*- coding: utf-8 -*-
"""NXOpen journal 静态检查（无需 NX 环境）。

检查项:
  1. Python 语法 (ast.parse)
  2. TODO/FIXME/占位符
  3. main() 入口与 NXOpen import（提示性）
  4. 裸 except（提示性）
  5. 已固化坑位（NX 12 批处理验证）:
     5.1a 创建 builder 传 None -> 必须用 NXOpen.Features.Feature.Null / BooleanFeature.Null
          (只覆盖 BUILDER_NULL 白名单, 未登记的 Create*Builder 不判)
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
          functools.cache/cached_property、itertools.pairwise、str.removeprefix/removesuffix、
          f-string 自记录表达式 f"{x=}"
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
    "CreateDraftBuilder": "NXOpen.Features.Feature.Null",
    "CreateShellBuilder": "NXOpen.Features.Feature.Null",
    "CreateHolePackageBuilder": "NXOpen.Features.HolePackage.Null",
}

# 尺寸属性只读的 builder: 只能 SetXxx / SetOriginAndLengths, 直接赋值会 AttributeError
READONLY_BUILDER_PROPS = {
    "CreateBlockFeatureBuilder": ("Length", "Width", "Height"),
    "CreateCylinderBuilder": ("Diameter", "Height"),
}


def _target_names(target: ast.AST) -> list[str]:
    """展开赋值目标里的名字 (含元组/列表解包与对象属性).

    `(blk,) = ...` -> ['blk']; `self.fn = ...` -> ['fn'] —— 属性名并入 builder
    候选, 赋值处按接收者链匹配 (`self.fn.Units` 的接收者是 self.fn)。
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
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
    只认同一文件内的朴素名字绑定 (含元组解包/with-as/for 目标) 与对象属性绑定
    (`self.x`/`h.x` 取属性名): helper 返回的 builder 无法静态确认, 相关规则按
    未检出处理。
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


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """局部名 -> 导入的完整点名。

    `import NXOpen.UF as uf` -> {'uf': 'NXOpen.UF'};
    `from NXOpen.UF import UFDraw as D` -> {'D': 'NXOpen.UF.UFDraw'};
    `import math` -> {'math': 'math'}。
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = node.module + "." + a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                local = a.asname or a.name.split(".")[0]
                aliases[local] = a.name if a.asname else a.name.split(".")[0]
    return aliases


def _full_name(node: ast.AST, aliases: dict[str, str]) -> str:
    """按别名表把点号表达式展开成完整点名 (uf.FeatureSigns -> NXOpen.UF.FeatureSigns)."""
    chain = _attr_chain(node)
    if not chain:
        return ""
    parts = list(reversed(chain))
    return ".".join([aliases.get(parts[0], parts[0])] + parts[1:])


def _dotted_aliases(tree: ast.AST, aliases: dict[str, str]) -> dict[str, str]:
    """补一层 `uf = NXOpen.UF` / `P = NXOpen.Point3d` 形式的局部别名。"""
    out = dict(aliases)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        else:
            continue
        if value is None or not isinstance(value, (ast.Name, ast.Attribute)):
            continue
        full = _full_name(value, out)
        if not full:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                out[tgt.id] = full
    return out


def _scope_names(body: list[ast.AST]) -> set[str]:
    """一个作用域内被重新绑定的名字 (不进嵌套函数/类体; import 不算遮蔽)."""
    names: set[str] = set()
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp,
                               ast.DictComp, ast.GeneratorExp)):
            continue
        else:
            stack.extend(ast.iter_child_nodes(node))
    return names


def _local_bindings(tree: ast.Module) -> tuple[set[str], list[tuple[int, int, set[str]]]]:
    """模块级绑定 + 各函数/推导式的局部绑定 (按行区间归属)。

    函数里的局部名/形参只遮蔽该函数范围内的同名 import, 不会把模块级调用静音;
    推导式目标只遮蔽推导式自己的范围。
    """
    module_names = _scope_names(tree.body)
    ranges: list[tuple[int, int, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            bound = {a.arg for a in args.args}
            bound.update(a.arg for a in getattr(args, "posonlyargs", []))
            bound.update(a.arg for a in args.kwonlyargs)
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
            body = node.body if isinstance(node.body, list) else [node.body]
            bound |= _scope_names(body)
            ranges.append((node.lineno, node.end_lineno or node.lineno, bound))
        elif isinstance(node, (ast.ListComp, ast.SetComp,
                               ast.DictComp, ast.GeneratorExp)):
            bound = set()
            for gen in node.generators:
                bound.update(_target_names(gen.target))
            ranges.append((node.lineno, node.end_lineno or node.lineno, bound))
    return module_names, ranges


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


def _is_zero_literal(node: ast.AST) -> bool:
    """数值字面量 0 / 0.0 (含 -0.0); bool 不算。"""
    node = _unwrap_sign(node)
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and node.value == 0)


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


def _receiver_names(tgt: ast.Attribute) -> set[str]:
    """赋值目标接收者链上的名字: self.fn.Units -> {'fn', 'self'}."""
    return set(_attr_chain(tgt)[1:])


def _var_attr_assignments(tree: ast.AST, var_names: set[str],
                          attr: str) -> list[tuple[int, ast.AST]]:
    """变量集合里所有 `var.<attr> = ...` 赋值: (行号, 右值)。

    带注解赋值 (`var.<attr>: t = ...`) 与普通赋值同属一个坑位; 变量可以绑在
    朴素名字上 (`fn = ...`), 也可以绑在对象属性上 (`self.fn = ...`)。
    """
    out: list[tuple[int, ast.AST]] = []
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
            if (isinstance(tgt, ast.Attribute) and tgt.attr == attr
                    and _receiver_names(tgt) & var_names):
                out.append((node.lineno, value))
    return out


def _var_attr_assigned(tree: ast.AST, var_names: set[str], attr: str) -> bool:
    """变量集合里是否有人被赋过 `var.<attr> = ...` (5.2 的作用域判据)。"""
    return bool(_var_attr_assignments(tree, var_names, attr))


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


def _var_attr_assigned_true(tree: ast.AST, var_names: set[str], attr: str) -> bool:
    """变量集合里是否存在 `var.<attr> = True` 赋值 (赋别的值不算)。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value, targets = node.value, node.targets
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        else:
            continue
        if value is None or not (isinstance(value, ast.Constant) and value.value is True):
            continue
        if any(isinstance(t, ast.Attribute) and t.attr == attr
               and _receiver_names(t) & var_names for t in targets):
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


def _point3d_names(aliases: dict[str, str]) -> set[str]:
    """Point3d 构造器的局部名: 导入别名与一层 `P = NXOpen.Point3d`。"""
    names = {"Point3d", "Point3d_Struct"}
    for local, full in aliases.items():
        if full.rsplit(".", 1)[-1] in ("Point3d", "Point3d_Struct"):
            names.add(local)
    return names


def _is_point3d_construction(node: ast.AST, point3d_names: set[str]) -> bool:
    """Point3d(...) 构造调用 (CreatePoint(Point3d(...)) 这种包了一层的不算).

    三种写法同源: `NXOpen.Point3d(...)`、`from NXOpen import Point3d` 之后的
    `Point3d(...)`、以及 `P = NXOpen.Point3d` 之后的 `P(...)`。
    """
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr in ("Point3d", "Point3d_Struct")
    return isinstance(fn, ast.Name) and fn.id in point3d_names


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
    aliases = _dotted_aliases(tree, _import_aliases(tree))
    # 豁免标记只认注释 token：字符串里出现同样文字不是豁免声明。
    comments: dict[int, str] = {}
    # f-string 自记录表达式 f"{x=}" 是 3.8+ 语法, ast.parse(feature_version=(3, 6))
    # 拦不住; 且 AST 里它与 f"x={x!r}" 同形, 只能按 token 流判:
    # f-string 内的 OP '=' 紧跟 '}' / '!' / ':' 即 debug 说明符。
    debug_fstrings: list[int] = []
    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)
    # 占位符只看注释 token 与真正的 raise NotImplementedError；字符串常量里
    # 出现 TODO 是测试反例/文档，不是待办。也不再把合法的 `pass  # ...` 当占位。
    try:
        depth = 0
        eq_line: int | None = None
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if fstring_start is not None:
                if tok.type == fstring_start:
                    depth += 1
                    eq_line = None
                    continue
                if tok.type == fstring_end:
                    depth = max(0, depth - 1)
                    eq_line = None
                    continue
                if depth:
                    if tok.type == tokenize.OP and tok.string == "=":
                        eq_line = tok.start[0]
                        continue
                    if eq_line is not None:
                        if tok.type == tokenize.OP and tok.string in ("}", "!", ":"):
                            debug_fstrings.append(eq_line)
                        eq_line = None
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
        point3d_names = _point3d_names(aliases)
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
                if not isinstance(tgt, ast.Attribute):
                    continue
                if _waived(comments, node.lineno):
                    continue
                if tgt.attr == "RightHandSide" and _is_number_literal(value):
                    issues.append(
                        f"第 {node.lineno} 行: {tgt.attr} 是 Expression, 必须给字符串 "
                        f'(如 "{_number_text(value)}"), 给数字报 '
                        f"'Expecting Unicode str type, found int/float'"
                    )
                elif (tgt.attr in POINT_OBJECT_PROPS
                      and _is_point3d_construction(value, point3d_names)):
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
    #     AST + 导入别名判：文本匹配会被注释/字符串里的名字误报，
    #     `uf.FeatureSigns` / `from NXOpen.UF import UFDraw` 这类别名写法也会漏。
    bad_signs = False
    bad_ufdraw = False
    bad_ufmotion = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            full = _full_name(node, aliases)
            if full == "NXOpen.UF.FeatureSigns":
                bad_signs = True
            elif full == "NXOpen.UF.UFDraw":
                bad_ufdraw = True
            elif full == "NXOpen.UF.UFMotion":
                bad_ufmotion = True
        elif isinstance(node, ast.ImportFrom) and node.module == "NXOpen.UF":
            imported = {a.name for a in node.names}
            if "FeatureSigns" in imported:
                bad_signs = True
            if "UFDraw" in imported:
                bad_ufdraw = True
            if "UFMotion" in imported:
                bad_ufmotion = True
    if bad_signs:
        issues.append(
            "检测到 NXOpen.UF.FeatureSigns: NX12 Python 封装不存在该枚举, "
            "改用 NXOpen.UF.ModlFeatureSigns (成员如 POSITIVE / NULLSIGN)"
        )
    if bad_ufdraw:
        issues.append(
            "检测到 NXOpen.UF.UFDraw: NX12 Python 封装无可导入该名 "
            "(AttributeError: module 'NXOpen.UF' has no attribute "
            "'UFDraw'); UF 的枚举挂在会话对象上 —— 用 "
            "ufs = NXOpen.UF.UFSession.GetUFSession() 后取 ufs.Draw.ProjDir."
            "PROJECT_BELOW / PROJECT_RIGHT、ufs.Draw.SxsegType.SXSEG_CUT, "
            "且这些位置的参数不接受裸 int"
        )
    if bad_ufmotion:
        issues.append(
            "检测到 NXOpen.UF.UFMotion: 不可导入 ("
            "AttributeError: module 'NXOpen.UF' has no attribute 'UFMotion'); "
            "枚举走 ufs = NXOpen.UF.UFSession.GetUFSession() 后的 ufs.Motion.*, "
            "struct 类型则是模块级 NXOpen.UF.<名>_Struct "
            "(如 NXOpen.UF.MotionInterference_Struct), 且 out 参数是返回值 "
            "(st = ufs.Motion.InitInterferenceStruct() 必须 0 参调用)"
        )

    # 5.8  装配枚举 (AST 判定: 注释/字符串里出现该名不算)
    bad_components = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "Components":
            if _attr_chain(node)[:2] == ["Components", "ComponentAssembly"]:
                bad_components = True
                break
    if bad_components:
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

    # 5.10  NX12 无螺纹特征 builder (AST 判定: 注释/字符串里出现该名不算)
    if not allow_probes:
        bad_thread = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "CreateThreadBuilder"):
                bad_thread = True
                break
            if (isinstance(node, ast.Attribute)
                    and _full_name(node, aliases) == "NXOpen.Features.Thread"):
                bad_thread = True
                break
            if (isinstance(node, ast.ImportFrom) and node.module == "NXOpen.Features"
                    and any(a.name in ("Thread", "CreateThreadBuilder")
                            for a in node.names)):
                bad_thread = True
                break
        if bad_thread:
            issues.append(
                "NX12 不存在 Features.Thread / CreateThreadBuilder (NX 2506 专属); "
                "螺纹孔走 HolePackageBuilder 的 Thread* 选项, 或打底孔后交互加螺纹"
            )

    # 5.11  STEP 导出未设同步标志
    #      判据走 AST：文案要求"显式设 True"，写 False、只在注释/字符串里提该名都不算;
    #      只认 CreateStepCreator() 绑定的那个变量 (含 self.x/对象属性), 别的对象
    #      赋 ProcessHoldFlag 顶不掉。
    step_vars = _builder_vars(tree, "CreateStepCreator")
    if not allow_probes and "createstepcreator" in src_lower \
            and not _var_attr_assigned_true(tree, step_vars, "ProcessHoldFlag"):
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
    #     判据走 AST：注释或字符串里写个 "getsize(" 顶不掉它；每一次 SaveAs
    #     都要有自己的校验（多路径保存只校最后一个会漏掉前面的文件），最后
    #     一次 Save/SaveAs 也要有校验；SaveAs 写死路径时校验必须是同一路径。
    if not allow_probes:
        save_checked_names = {"save_checked"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    if a.name == "save_checked":
                        save_checked_names.add(a.asname or a.name)
        saves: list[tuple[int, int, str | None, str]] = []
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
                saves.append((node.lineno, node.col_offset, call_path, fn.attr))
            elif isinstance(fn, ast.Attribute) and fn.attr in ("getsize", "exists") \
                    and "path" in _attr_chain(fn):
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        call_path = arg.value
                checks.append((node.lineno, node.col_offset, call_path))
            elif ((isinstance(fn, ast.Attribute) and fn.attr == "save_checked")
                  or (isinstance(fn, ast.Name) and fn.id in save_checked_names)):
                # 该调用自身即"保存 + 校验"，同一位置同时记两条;
                # 任意接收者的 .save_checked(...) 与 import 别名都算,
                # 第 1 个 str 字面量参数参与 SaveAs 路径对账。
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        call_path = arg.value
                saves.append((node.lineno, node.col_offset, call_path,
                              "save_checked"))
                checks.append((node.lineno, node.col_offset, call_path))
        if saves:
            saves.sort(key=lambda s: (s[0], s[1]))
            missing = []
            for idx, save in enumerate(saves):
                is_last = idx == len(saves) - 1
                if not is_last and save[3] != "SaveAs":
                    continue
                verified = False
                for line, col, check_path in checks:
                    if (line, col) < (save[0], save[1]):
                        continue
                    # SaveAs 路径是字面量时，校验路径必须是同一字面量；校验
                    # 路径不是字面量（变量）时无法静态确认，按可能命中处理。
                    if save[2] is not None and check_path is not None \
                            and check_path != save[2]:
                        continue
                    verified = True
                    break
                if not verified:
                    missing.append(save)
            if missing:
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
        angle_assigns = _var_attr_assignments(tree, draft_vars, "AngleTolerance")
        if not angle_assigns:
            issues.append(
                "使用 CreateDraftBuilder 但未设 .AngleTolerance: 默认 0.0, Commit 报 "
                "'Angle tolerance is too small'; 必须显式设 0.5 (见 modeling.md §3.4)"
            )
        else:
            zero_lines = [lineno for lineno, value in angle_assigns
                          if _is_zero_literal(value)]
            if zero_lines:
                issues.append(
                    f"第 {zero_lines[0]} 行: DraftBuilder.AngleTolerance 显式设 0.0 -> "
                    f"Commit 报 'Angle tolerance is too small'; 必须显式设非 0 值 "
                    f"(如 0.5, 见 modeling.md §3.4)"
                )

    # 5.15  ShellBuilder.Tolerance 默认 0 必须显式设
    shell_vars = _builder_vars(tree, "CreateShellBuilder")
    if not allow_probes and shell_vars:
        tol_assigns = _var_attr_assignments(tree, shell_vars, "Tolerance")
        if not tol_assigns:
            issues.append(
                "使用 CreateShellBuilder 但未设 .Tolerance: 默认 0.0, Commit 报 "
                "'Tolerance error'; 必须显式设 0.01 (见 modeling.md §3.4)"
            )
        else:
            zero_lines = [lineno for lineno, value in tol_assigns
                          if _is_zero_literal(value)]
            if zero_lines:
                issues.append(
                    f"第 {zero_lines[0]} 行: ShellBuilder.Tolerance 显式设 0.0 -> "
                    f"Commit 报 'Tolerance error'; 必须显式设非 0 值 "
                    f"(如 0.01, 见 modeling.md §3.4)"
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
    # 局部名 -> (来源模块, 原名): from math import dist as d -> ('math', 'dist');
    # import math as m -> ('math', None)。别名表来自 _import_aliases/_dotted_aliases,
    # 一层 `d = math.dist` 也算。
    alias_mod: dict[str, tuple[str, str | None]] = {}
    for local, full in aliases.items():
        parts = full.split(".")
        alias_mod[local] = (parts[0], parts[-1] if len(parts) > 1 else None)
    # 同一名字只在它被重新绑定的作用域里遮蔽 import: 函数内的局部变量/形参不会
    # 把模块级调用静音, 模块级也只认模块级绑定。
    module_shadowed, scope_bindings = _local_bindings(tree)

    def is_shadowed(name: str, lineno: int) -> bool:
        if name in module_shadowed:
            return True
        return any(start <= lineno <= end and name in bound
                   for start, end, bound in scope_bindings)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            v = node.value
            if isinstance(v, ast.Name) and not is_shadowed(v.id, node.lineno):
                src = alias_mod.get(v.id)
                if src is not None and src[1] is not None:
                    # from math import dist 之后写 dist.attr 不是 math.attr
                    continue
                mod = src[0] if src else v.id
                hit = PY36_TRAPS.get((mod, node.attr))
                if hit:
                    issues.append(
                        f"第 {node.lineno} 行: journal 解释器是 NX12 内嵌 Python 3.6.1, "
                        f"{mod}.{node.attr} 不支持 ({hit})"
                    )
        # from math import dist / as d 后直接 dist(a, b) / d(a, b): AST 里是 Name
        # 调用, 上面只看 Attribute 会漏。只在"作为调用被使用"时判, 避免
        # 把 import 行本身或同名局部变量误报。
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            src = alias_mod.get(node.func.id)
            if src and not is_shadowed(node.func.id, node.lineno):
                mod, orig = src
                name = orig or node.func.id
                hit = PY36_TRAPS.get((mod, name))
                if hit:
                    issues.append(
                        f"第 {node.lineno} 行: journal 解释器是 NX12 内嵌 Python 3.6.1, "
                        f"from {mod} import {name} 后调用不支持 ({hit})"
                    )
    for lineno in sorted(set(debug_fstrings)):
        issues.append(
            f"第 {lineno} 行: f-string 自记录表达式 f\"{{x=}}\" 是 Python 3.8+, "
            f"journal 解释器为 3.6.1; 改写为 f\"x={{x}}\" 或先赋值给变量"
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
                if _full_name(node, aliases) == "NXOpen.UF.UFDrf":
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
