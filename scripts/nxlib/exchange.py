# -*- coding: utf-8 -*-
"""STEP 交换配方：导出、导入、回读与 B-rep 事实表。

三条已验证约束都收在这里：

1. `StepCreator` 的 `ObjectTypes` 默认全 False；不设 `Solids=True` 会写出
   合法但零 B-rep 的空骨架，日志仍报成功。`export_step` 默认打开实体。
2. AP214 默认同样写空骨架；必须显式给 NX 自带的 `step214ug.def`。
3. 导入 `NewPart` 必须给 `SettingsFile`（242/214 各自导入向 def）与完整
   `.prt` OutputFile；def 缺失或路径不存在时静默写约 40 KB 空壳（0 bodies），
   `Commit` 不抛异常。判定必须另起进程重开文件，不能在同一次 Commit 后读
   `Parts.Work`（NewPart 成功后它仍为 None）。
"""
import os

import NXOpen
import NXOpen.UF

from . import measure


def nx_home():
    return os.environ.get("NX_HOME", r"D:\UG-NX12")


def settings_path(schema, direction="export"):
    """返回该 schema 的 NX 定义文件；找不到返回 None。

    定义文件分方向：`ugstep214.def` 是 UG→STEP（导出），`step214ug.def`
    是 STEP→UG（导入）。用反方向会静默空转或转去调安装目录的 .bat。
    """
    root = nx_home()
    if schema == "ap214":
        names = ("ugstep214.def", "step214ug.def") if direction == "export" \
            else ("step214ug.def", "ugstep214.def")
        for name in names:
            p = os.path.join(root, "STEP214UG", name)
            if os.path.exists(p):
                return p
    elif schema == "ap242":
        names = ("ugstep242.def", "step242ug.def") if direction == "export" \
            else ("step242ug.def", "ugstep242.def")
        for name in names:
            p = os.path.join(root, "TRANSLATORS", "step242", name)
            if os.path.exists(p):
                return p
    elif schema == "ap203":
        names = ("ugstep203.def", "step203ug.def") if direction == "export" \
            else ("step203ug.def", "ugstep203.def")
        for name in names:
            p = os.path.join(root, "STEP203UG", name)
            if os.path.exists(p):
                return p
    return None


def export_step(part, path, schema="ap242", bodies=None, pmi=False,
                annotations=False, surfaces=False, curves=False,
                settings=None, input_file=None, solids=True,
                strict_settings=True):
    """导出 STEP；返回 {path, size, schema, settings}。

    bodies 为 None 时导出 EntirePart；给列表时只导出选中体。
    AP214 找不到 SettingsFile 直接抛错——默认设置会静默写空骨架。
    """
    schema = schema.lower()
    path = os.path.abspath(path)
    if input_file is None:
        input_file = part.FullPath
    input_file = os.path.abspath(input_file)
    if not os.path.exists(input_file):
        raise ValueError("part file not saved: %s" % input_file)
    # 只有 AP214/AP203 必须给 def；AP242 给 step242ug.def 反而会把
    # ExportAs 覆盖成 AUTOMOTIVE_DESIGN 并丢掉 PMI 子类型。
    if settings is None and schema in ("ap214", "ap203"):
        settings = settings_path(schema, "export")
    if schema in ("ap214", "ap203") and strict_settings and not settings:
        raise ValueError("AP214 needs NX step214ug.def under %s" % nx_home())
    if not strict_settings:
        settings = None
    if os.path.exists(path):
        os.remove(path)

    sess = NXOpen.Session.GetSession()
    creator = sess.DexManager.CreateStepCreator()
    try:
        creator.OutputFile = path
        creator.ExportAs = {
            "ap203": NXOpen.StepCreator.ExportAsOption.Ap203,
            "ap214": NXOpen.StepCreator.ExportAsOption.Ap214,
            "ap242": NXOpen.StepCreator.ExportAsOption.Ap242,
        }[schema]
        creator.InputFile = input_file
        creator.FileSaveFlag = False
        creator.ExportFrom = NXOpen.StepCreator.ExportFromOption.DisplayPart
        creator.ProcessHoldFlag = True
        creator.ValidationProperties = False
        if settings:
            creator.SettingsFile = settings
        ot = creator.ObjectTypes
        ot.Solids = bool(solids)
        ot.Surfaces = bool(surfaces)
        ot.Curves = bool(curves)
        ot.PmiData = bool(pmi)
        ot.Annotations = bool(annotations)
        if bodies is None:
            creator.ExportSelectionBlock.SelectionScope = \
                NXOpen.ObjectSelector.Scope.EntirePart
        else:
            creator.ExportSelectionBlock.SelectionScope = \
                NXOpen.ObjectSelector.Scope.SelectedObjects
            for b in bodies:
                creator.ExportSelectionBlock.SelectionComp.Add(b)
        creator.Commit()
    finally:
        try:
            creator.Destroy()
        except Exception:
            pass

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("STEP export produced no file: %s" % path)
    return {"path": path, "size": os.path.getsize(path), "schema": schema,
            "settings": settings}


def import_step(path, schema="ap242", target="work", output_part=None,
                settings=None):
    """导入 STEP。target='work' 进当前工作件；'new' 落 OutputFile。

    两种 target 都必须给 OutputFile。'new' 的产物约 8 s 后才落盘，调用方
    必须另起进程重开验证；242/214 的纯实体均能重开，带 PMI 的 242 另按
    PMI 普查判定。
    """
    schema = schema.lower()
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise ValueError("no such STEP: %s" % path)
    sess = NXOpen.Session.GetSession()
    if schema == "ap242":
        imp = sess.DexManager.CreateStep242Importer()
        enum = NXOpen.Step242Importer.ImportToOption
    elif schema == "ap214":
        imp = sess.DexManager.CreateStep214Importer()
        enum = NXOpen.Step214Importer.ImportToOption
    else:
        raise ValueError("unsupported schema: %s" % schema)
    try:
        imp.InputFile = path
        imp.FileOpenFlag = False
        imp.ProcessHoldFlag = True
        imp.SewSurfaces = True
        imp.Optimize = True
        imp.ObjectTypes.Solids = True
        imp.ObjectTypes.Surfaces = True
        if target == "work":
            imp.ImportTo = enum.WorkPart
            # WorkPart 也必须给 OutputFile：不给时 Commit 不报错、work 件
            # 仍是 0 bodies（p8b_vp.stp 实测）。中间件放临时目录，不覆盖调用方。
            if not output_part:
                import tempfile
                output_part = os.path.join(
                    tempfile.gettempdir(),
                    "nxlib_import_work_%d.prt" % os.getpid())
            output_part = os.path.abspath(output_part)
            if os.path.exists(output_part):
                os.remove(output_part)
            imp.OutputFile = output_part
            work = sess.Parts.Work
            if work is not None:
                NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(
                    work.Tag)
        elif target == "new":
            if not output_part:
                raise ValueError("target='new' needs output_part")
            output_part = os.path.abspath(output_part)
            if os.path.exists(output_part):
                os.remove(output_part)
            imp.ImportTo = enum.NewPart
            imp.OutputFile = output_part
            if settings is None:
                settings = settings_path(schema, "import")
            if settings:
                imp.SettingsFile = settings
        else:
            raise ValueError("target must be 'work' or 'new'")
        imp.Commit()
    finally:
        try:
            imp.Destroy()
        except Exception:
            pass
    if target == "work":
        return sess.Parts.Work
    return None


def reopen_part(path):
    """另起一次 Parts.OpenBaseDisplay 打开部件并设为显示件。"""
    path = os.path.abspath(path)
    sess = NXOpen.Session.GetSession()
    opened = sess.Parts.OpenBaseDisplay(path)
    part = opened[0] if isinstance(opened, (tuple, list)) else opened
    try:
        NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(part.Tag)
    except Exception:
        pass
    return part


def _component_bodies(part):
    out = []
    try:
        root = part.ComponentAssembly.RootComponent
    except Exception:
        return out
    if root is None:
        return out
    stack = [root]
    while stack:
        comp = stack.pop()
        try:
            stack.extend(list(comp.GetChildren()))
        except Exception:
            pass
        try:
            proto = comp.Prototype
            out.extend(list(proto.Bodies))
        except Exception:
            pass
    return out


def part_facts(part):
    """B-rep 事实表：bodies/solid_bodies/faces/edges/volume。

    装配的 `part.Bodies` 可能为 0，此时按组件原型体累加。
    """
    bodies = list(part.Bodies)
    if not bodies:
        bodies = _component_bodies(part)
    solid = 0
    faces = 0
    edges = 0
    for b in bodies:
        try:
            if b.IsSolidBody:
                solid += 1
        except Exception:
            pass
        faces += len(list(b.GetFaces()))
        edges += len(list(b.GetEdges()))
    try:
        volume = measure.part_volume(part) if list(part.Bodies) else 0.0
    except Exception:
        volume = 0.0
    return {"part": part.Name, "bodies": len(bodies),
            "solid_bodies": solid, "faces": faces, "edges": edges,
            "volume": round(float(volume), 4)}
