# -*- coding: utf-8 -*-
"""nxlib.drafting —— 制图配方标准层（权威来源：20/21/31 号已验收用例逐字平移）。

覆盖：视图查询（可见对象计数/按名查找/类型统计）、UF 表格（建表/读格/
清空默认格/行高钉位）、PDF 导出、剖视线（sxline 腿数/类型名）、剖视图创建。

注意：建模侧查询（find_planar_face / add_thru_hole / classify_edges /
face_radius）归 nxlib.modeling，不在此模块。
"""
import os

import NXOpen
import NXOpen.UF


def ufs():
    return NXOpen.UF.UFSession.GetUFSession()


def norm_tag(r):
    """UF Create* 返回值有时包一层 1-tuple，此函数取平（19/20 号口径）。"""
    if isinstance(r, tuple):
        return r[0] if r else None
    return r


# ---------------------------------------------------------------- 视图查询

def visible_count(view):
    """视图可见对象计数；视图所在页非当前页会抛 'The view is not displayed'
    （20 号实测），此时返回 (-1, 异常文本)。"""
    try:
        vis = view.AskVisibleObjects()
    except Exception as exc:
        return -1, str(exc)
    return (0 if vis is None else len(vis)), ""


def view_names(sheet):
    """当前页全部制图视图名（排序）。"""
    return sorted("%s" % v.Name for v in sheet.GetDraftingViews())


def view_by_prefix(sheet, prefix):
    """按前缀（不区分大小写）找视图，找不到返回 None（20 号口径）。"""
    for v in sheet.GetDraftingViews():
        if v.Name.upper().startswith(prefix.upper()):
            return v
    return None


def view_kinds(sheet, view):
    """可见对象按类型名统计（31 号口径）。返回 (可见对象列表, {类型名: 数量})。"""
    sheet.Open()
    vis = list(view.AskVisibleObjects() or [])
    kinds = {}
    for o in vis:
        k = type(o).__name__
        kinds[k] = kinds.get(k, 0) + 1
    return vis, kinds


# ---------------------------------------------------------------- UF 表格

def cell_text(tn, row, col):
    """取 (row, col) 处 cell 的 tag（20 号口径）。"""
    u = ufs()
    r0 = u.Tabnot.AskNthRow(tn, row)
    c0 = u.Tabnot.AskNthColumn(tn, col)
    return norm_tag(u.Tabnot.AskCellAtRowCol(norm_tag(r0), norm_tag(c0)))


def read_cell(tn, ri, ci):
    """读单元格文本（20 号口径）。"""
    u = ufs()
    got = u.Tabnot.AskCellText(cell_text(tn, ri, ci))
    return got[1] if isinstance(got, tuple) else got


def drain_table(tn):
    """清掉新表的默认 5×5 格（20 号口径；Create 出来自带默认格必须先清）。"""
    u = ufs()
    for _ in range(50):
        try:
            u.Tabnot.RemoveColumn(norm_tag(u.Tabnot.AskNthColumn(tn, 0)))
        except Exception:
            break
    for _ in range(50):
        try:
            u.Tabnot.RemoveRow(norm_tag(u.Tabnot.AskNthRow(tn, 0)))
        except Exception:
            break


def new_table(origin, col_widths, row_heights, thick_border=False):
    """建 UF 表格：先清默认格再加列/行（20 号口径；origin 是 (x, y)）。"""
    u = ufs()
    sp = u.Tabnot.AskDefaultSectionPrefs()
    if thick_border:
        sp.UseDoubleWidthBorder = True
        sp.BorderWidth = 0.7
    sp.AttachPoint = NXOpen.UF.Tabnot.AttachPoint.ATTACH_POINT_TOP_LEFT
    res = u.Tabnot.Create(sp, [float(origin[0]), float(origin[1]), 0.0])
    tn = norm_tag(res)
    drain_table(tn)
    for w in col_widths:
        u.Tabnot.AddColumn(tn, norm_tag(u.Tabnot.CreateColumn(w)), -1)
    for h in row_heights:
        u.Tabnot.AddRow(tn, norm_tag(u.Tabnot.CreateRow(h)), -1)
    return tn


def pin_table_geometry(tn, row_heights, ncols=1, center_first_row=False):
    """行高只在逐格关掉自适应后生效（uf_tabnot.h：Fit methods auto size row
    and auto size text must be disabled；20 号口径）。"""
    u = ufs()
    for ri, h in enumerate(row_heights):
        row = norm_tag(u.Tabnot.AskNthRow(tn, ri))
        for ci in range(ncols):
            cell = cell_text(tn, ri, ci)
            cp = u.Tabnot.AskCellPrefs(cell)
            cp.NmFitMethods = 0
            u.Tabnot.SetCellPrefs(cell, cp)
        u.Tabnot.SetRowHeight(row, float(h))
    if center_first_row:
        cell = cell_text(tn, 0, 0)
        cp = u.Tabnot.AskCellPrefs(cell)
        cp.HorizJust = NXOpen.UF.Tabnot.Just.JUST_CENTER
        cp.VertJust = NXOpen.UF.Tabnot.Just.JUST_MIDDLE
        u.Tabnot.SetCellPrefs(cell, cp)


# ---------------------------------------------------------------- 导出

def export_pdf(part, sheet, path):
    """导出单页 PDF，返回文件字节数（不存在返回 -1；20/31 号口径）。"""
    if os.path.exists(path):
        os.remove(path)
    b = part.PlotManager.CreatePrintPdfbuilder()
    b.SourceBuilder.SetSheets([sheet])
    b.Colors = NXOpen.PrintPDFBuilder.Color.BlackOnWhite
    b.Size = NXOpen.PrintPDFBuilder.SizeOption.FullScale
    b.Units = NXOpen.PrintPDFBuilder.UnitsOption.Metric
    b.Scale = 1.0
    b.Filename = path
    b.Commit()
    b.Destroy()
    return os.path.getsize(path) if os.path.exists(path) else -1


# ---------------------------------------------------------------- 剖视

def sxline_type_name(u, value):
    """SxlineType 枚举值 → 成员名（31 号口径；未匹配返回 <unmatched:...>）。"""
    for n in dir(u.Draw.SxlineType):
        if n.startswith("_") or n == "ValueOf":
            continue
        try:
            if getattr(u.Draw.SxlineType, n) == value:
                return n
        except Exception:
            pass
    return "<unmatched:%r>" % (value,)


def sxline_legs(u, sxline):
    """剖视线腿段数，取自 AskSteppedSxline 第 6 字段（21 号口径）。

    AskSteppedSxline 对普通两点剖视线也作答（实测），区分阶梯/直线看它的
    返回值而不是 AskSxlineType；第 7 字段是 tag 列表，必须与腿数一致。
    """
    data = u.Draw.AskSteppedSxline(sxline)
    if not hasattr(data, "__len__") or len(data) < 7:
        raise RuntimeError("AskSteppedSxline returned %d field(s), expected "
                           "at least 7" % (len(data) if hasattr(data, "__len__")
                                           else -1))
    n_segs = data[5]
    seg_tags = data[6]
    if len(seg_tags) != n_segs:
        raise RuntimeError("AskSteppedSxline field 6 says %s leg segments but "
                           "field 7 lists %d tags" % (n_segs, len(seg_tags)))
    return n_segs


def add_cut_points(part, seglist, pts):
    """往剖视线段列表追加剖切点，返回追加后的长度（31 号口径）。"""
    for p in pts:
        seglist.AddCutSegment(part.Points.CreatePoint(NXOpen.Point3d(*p)))
    return seglist.Length


def new_section_view(part, parent, type_member, placement_origin):
    """建并提交一个剖视图 builder；builder 的收尾（Destroy）由调用方管
    （31 号口径——调用方常需要在 Commit 前补剖切点）。"""
    svb = part.DraftingViews.CreateSectionViewBuilder(
        NXOpen.Drawings.SectionView.Null)
    svb.ParentView.View.Value = parent
    svb.SectionViewType = type_member
    svb.SectionLineSegments.SectionLineOnlyPlacementOrigin = placement_origin
    svb.ViewPlacement.Placement.Value = part.Points.CreatePoint(placement_origin)
    return svb
