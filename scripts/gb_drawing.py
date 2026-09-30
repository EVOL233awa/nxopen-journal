# -*- coding: utf-8 -*-
"""GB-style drawing furniture + annotation helpers for NX 12 journals.

随手出一张国标图纸的标准件：任何 NXOpen journal 把本目录加进 sys.path 后
`import gb_drawing`，按 "建件 -> blank_datums -> new_sheet -> frame ->
standard_views -> title_block/tech_note -> 标注 -> export_pdf" 的顺序调用即可
得到与回归用例 33 同版的图纸质量。所有数值口径都来自回归用例实测（引用见
各常量与 references/gb-drawing.md），不要凭感觉改。

标准依据（本技能可证实部分）：
  * GB/T 14689.1  幅面与边距：装订边 a=25，非装订边 c：A0/A1=10、A2-A4=5
  * GB/T 10609.1  标题栏字段（设计/校核/日期/图号/比例/材料/图名）；本模块
    默认版式 = 一张真实工程图纸实测（105x21，3 行 7mm，6 列），字段齐全
  * GB/T 4458.4   尺寸道位：第一道距轮廓约 10mm、相邻道约 7mm（通行做法）；
                同向多道按数值升序外推（小尺寸在内道、大尺寸在外道）。
                成组等径孔只标一条数量引线（2x<O>10，quantity_label），
                不逐孔 dim_diameter（UF 直径尺寸写不进数量前缀）
  * 投影角        第一角（GB）
  * 字高          3.5 / 2.5（GB/T 14691 常用两档）

NX 12 内嵌 Python 3.6 —— 不用 f-string，不做 3.7+ API 调用。
"""
import time

import NXOpen
import NXOpen.UF

# ------------------------------------------------------------ GB constants
SHEET = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}
BINDING_A = 25.0                          # 装订边 a（GB/T 14689.1）
NONBIND_C = {"A4": 5.0, "A3": 5.0}        # 非装订边 c；A0/A1 应为 10，未覆盖
TEXT_DIM = 3.5                            # 尺寸/常用字高
TEXT_SMALL = 2.5                          # 次要字高（标题栏字段）
ARROW_LEN = 4.0                           # 箭头长度（19 号用例实测可用）
LANE_FIRST = 10.0                         # 第一道尺寸线离轮廓
LANE_STEP = 7.0                           # 相邻尺寸线道距
VIEW_GAP = 22.0                           # 三视图间距（内容区留白）
VIEW_MARGIN = 18.0                        # 视图组离图框
# 标题栏：105x21，3 行 7mm，列宽 [label,value]x3（2026-09-24 从一张真实
# 工程图纸实测：总宽约 105mm、行高约 7mm、三行结构 = 图名/设计校核日期/
# 图号比例材料）。原图列宽 14/21 在 NX 表格字体下放不下 10 字符的日期
# （2.5 字高时 ASCII 字宽约 2.1mm，21mm 只容 10 字符，溢出画成 #），实测
# 后改为 10/25，总宽 105 不变。
TB_W, TB_H = 105.0, 21.0
TB_COLS = [10.0, 25.0, 10.0, 25.0, 10.0, 25.0]
TB_ROWS = [7.0, 7.0, 7.0]
# 局部放大边界圆半径约等于选框半对角的 0.83 倍（2026-09-23 两次实测缩进
# 5-6mm）：detail_rect() 据此自动放余量
DETAIL_CIRCLE_FACTOR = 0.83
DEFAULT_NOTE_LINES = [
    u"技术要求：",
    u"1. 未注线性尺寸公差按GB/T 1804-m。",
    u"2. 未注形位公差按GB/T 1184-K。",
    u"3. 锐边倒钝去毛刺。",
]


def _ufs():
    return NXOpen.UF.UFSession.GetUFSession()


def _norm(r):
    return r[0] if isinstance(r, tuple) else r


# ------------------------------------------------------------- sheet setup
def new_sheet(part, name="SHT1", size="A4"):
    """Insert an A4 (or A3) first-angle sheet and make it current."""
    if size not in SHEET:
        raise RuntimeError("gb_drawing: unsupported size %r" % (size,))
    sh = part.DrawingSheets.InsertSheet(
        name, NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4
        if size == "A4" else
        NXOpen.Drawings.DrawingSheet.StandardSheetSize.A3,
        1.0, 1.0,
        NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle)
    sh.Open()
    return sh


def blank_datums(part):
    """Blank every datum plane/axis before any view exists: the template's
    datum coordinate system projects into every drafting view as stray
    arrowheads (measured 2026-09-23). Blanked objects do not plot."""
    n = 0
    for o in part.Datums:
        if not o.IsBlanked:
            o.Blank()
            n += 1
    return n


def apply_gb_preferences(part, dim_text=TEXT_DIM, small_text=TEXT_SMALL):
    """Lettering 3.5/2.5 + filled arrows, per 19_drafting_annotation.py."""
    ap = part.Annotations.Preferences
    lp = ap.GetLetteringPreferences()
    for getter, setter, size in (
            (lp.GetDimensionText, lp.SetDimensionText, dim_text),
            (lp.GetGeneralText, lp.SetGeneralText, small_text),
            (lp.GetAppendedText, lp.SetAppendedText, small_text),
            (lp.GetToleranceText, lp.SetToleranceText, small_text)):
        lt = getter()
        lt.Size = float(size)
        setter(lt)
    ap.SetLetteringPreferences(lp)
    lap = ap.GetLineAndArrowPreferences()
    lap.ArrowheadLength = ARROW_LEN
    lap.ArrowheadIncludedAngle = 10.0
    lap.FirstArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
    lap.SecondArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
    ap.SetLineAndArrowPreferences(lap)


# ------------------------------------------------------- table primitives
def _cell(tn, row, col):
    ufs = _ufs()
    r = _norm(ufs.Tabnot.AskNthRow(tn, row))
    c = _norm(ufs.Tabnot.AskNthColumn(tn, col))
    return _norm(ufs.Tabnot.AskCellAtRowCol(r, c))


def _read_cell(tn, ri, ci):
    ufs = _ufs()
    v = _norm(ufs.Tabnot.AskCellText(_cell(tn, ri, ci)))
    if isinstance(v, tuple):
        v = v[0]
    return str(v)


def _drain(tn):
    """Default new tables are 5x5; remove all rows/cols before building."""
    ufs = _ufs()
    while True:
        n = _norm(ufs.Tabnot.AskNmRows(tn))
        n = int(n)
        if n <= 0:
            break
        ufs.Tabnot.RemoveRow(_norm(ufs.Tabnot.AskNthRow(tn, 0)))
    while True:
        n = int(_norm(ufs.Tabnot.AskNmColumns(tn)))
        if n <= 0:
            break
        ufs.Tabnot.RemoveColumn(_norm(ufs.Tabnot.AskNthColumn(tn, 0)))


def _new_table(origin, col_widths, row_heights, thick_border=False):
    """Table with origin = top-left corner, grows down (measured).  Row
    heights only take effect once every cell's auto-fit is off (uf_tabnot.h:
    "Fit methods auto size row and auto size text must be disabled")."""
    ufs = _ufs()
    sp = ufs.Tabnot.AskDefaultSectionPrefs()
    if thick_border:
        sp.UseDoubleWidthBorder = True
        sp.BorderWidth = 0.7
    sp.AttachPoint = NXOpen.UF.Tabnot.AttachPoint.ATTACH_POINT_TOP_LEFT
    tn = _norm(ufs.Tabnot.Create(sp, [float(origin[0]), float(origin[1]), 0.0]))
    _drain(tn)
    for w in col_widths:
        ufs.Tabnot.AddColumn(tn, _norm(ufs.Tabnot.CreateColumn(float(w))), -1)
    for h in row_heights:
        ufs.Tabnot.AddRow(tn, _norm(ufs.Tabnot.CreateRow(float(h))), -1)
    _pin_rows(tn, row_heights, len(col_widths))
    return tn


def _pin_rows(tn, row_heights, ncols):
    ufs = _ufs()
    for ri, h in enumerate(row_heights):
        row = _norm(ufs.Tabnot.AskNthRow(tn, ri))
        for ci in range(ncols):
            cell = _cell(tn, ri, ci)
            cp = ufs.Tabnot.AskCellPrefs(cell)
            cp.NmFitMethods = 0
            ufs.Tabnot.SetCellPrefs(cell, cp)
        ufs.Tabnot.SetRowHeight(row, float(h))


def _center_cell(tn, ri, ci):
    ufs = _ufs()
    cell = _cell(tn, ri, ci)
    cp = ufs.Tabnot.AskCellPrefs(cell)
    cp.HorizJust = NXOpen.UF.Tabnot.Just.JUST_CENTER
    cp.VertJust = NXOpen.UF.Tabnot.Just.JUST_MIDDLE
    ufs.Tabnot.SetCellPrefs(cell, cp)


# ------------------------------------------------------------- GB furniture
def frame(sheet, size="A4"):
    """GB/T 14689.1 图框：单格表格 + 双线宽边框，随图纸出图。

    Returns dict(tag=..., left, right, top, bottom) in sheet mm."""
    w, h = SHEET[size]
    c = NONBIND_C[size]
    left, bottom = BINDING_A, c
    right, top = w - c, h - c
    tn = _new_table((left, top), [right - left], [top - bottom],
                    thick_border=True)
    return {"tag": tn, "left": left, "right": right,
            "top": top, "bottom": bottom}


def title_block(sheet, frame_geo, name=None, design=None, check=None,
                date=None, dwg_no=None, scale_txt="1:1", material=None):
    """标题栏，贴图框右下角（GB/T 10609.1 字段、真实工程图纸实测版式）。

    签名/材料等没有依据的字段传 None 留空，不造数据；date=None 取当天
    （生成日期是真实事实）。Returns the same geometry dict as frame()."""
    ufs = _ufs()
    left = frame_geo["right"] - TB_W
    top = frame_geo["bottom"] + TB_H
    dp = ufs.Tabnot.AskDefaultCellPrefs()
    dp.TextHeight = TEXT_SMALL
    ufs.Tabnot.SetDefaultCellPrefs(dp)
    tn = _new_table((left, top), TB_COLS, TB_ROWS, thick_border=True)
    ufs.Tabnot.MergeCells(_cell(tn, 0, 0), _cell(tn, 0, 5))
    rows = [
        [name or "", "", "", "", "", ""],
        [u"设计", design or "", u"校核", check or "", u"日期",
         date if date is not None else time.strftime("%Y-%m-%d")],
        [u"图号", dwg_no or "", u"比例", scale_txt or "", u"材料",
         material or ""],
    ]
    for ri, vals in enumerate(rows):
        for ci, val in enumerate(vals):
            if val != "":
                ufs.Tabnot.SetCellText(_cell(tn, ri, ci), val)
    _pin_rows(tn, TB_ROWS, len(TB_COLS))
    _center_cell(tn, 0, 0)
    # read back everything the caller actually asked to write
    want = {(1, 0): u"设计", (2, 0): u"图号", (2, 2): u"比例"}
    if name:
        want[(0, 0)] = name
    if design:
        want[(1, 1)] = design
    if check:
        want[(1, 3)] = check
    if date is not None:
        want[(1, 5)] = date
    if dwg_no:
        want[(2, 1)] = dwg_no
    if scale_txt:
        want[(2, 3)] = scale_txt
    if material:
        want[(2, 5)] = material
    for (ri, ci), expect in sorted(want.items()):
        got = _read_cell(tn, ri, ci)
        if got != str(expect):
            raise RuntimeError("title_block r%d c%d read-back %r != %r"
                               % (ri, ci, got, expect))
    return {"tag": tn, "left": left, "right": frame_geo["right"],
            "top": top, "bottom": frame_geo["bottom"]}


def tech_note(sheet, tb_geo, lines=None, size=TEXT_DIM):
    """技术要求块：贴标题栏正上方、随行数上生长（GB 通行位置）。
    行距 6.5mm（约 1.9 倍字高），块底距标题栏顶约 6mm。"""
    if lines is None:
        lines = DEFAULT_NOTE_LINES
    x = tb_geo["left"]
    y = tb_geo["top"] + 6.5 * len(lines) + 6.0
    note = part_note(sheet, lines, (x, y), size)
    return note


def part_note(sheet, lines, origin_xy, size=TEXT_DIM):
    """Multi-line note anchored at its TOP-LEFT corner (default anchor is
    the block centre, which makes centred ragged lines - not GB style;
    measured 2026-09-24).  NX re-interprets the stored origin when the
    alignment changes, so the origin is pinned AFTER switching to TopLeft -
    then it is the block's top-left corner, deterministically."""
    part = sheet_part(sheet)
    note = part.Annotations.CreateNote(
        list(lines), NXOpen.Point3d(float(origin_xy[0]), float(origin_xy[1]),
                                    0.0),
        NXOpen.AxisOrientation.Horizontal, None, None)
    if note is None:
        raise RuntimeError("CreateNote returned None")
    lp = note.GetLetteringPreferences()
    g = lp.GetGeneralText()
    g.Size = float(size)
    lp.SetGeneralText(g)
    lp.AlignmentPosition = NXOpen.Annotations.AlignmentPosition.TopLeft
    note.SetLetteringPreferences(lp)
    note.AnnotationOrigin = NXOpen.Point3d(float(origin_xy[0]),
                                           float(origin_xy[1]), 0.0)
    got = note.GetLetteringPreferences().AlignmentPosition
    if got != NXOpen.Annotations.AlignmentPosition.TopLeft:
        raise RuntimeError("note alignment read-back %r != TopLeft" % (got,))
    o = note.AnnotationOrigin
    if abs(o.X - origin_xy[0]) > 1e-6 or abs(o.Y - origin_xy[1]) > 1e-6:
        raise RuntimeError("note origin read-back (%.2f,%.2f) != (%.2f,%.2f)"
                           % (o.X, o.Y, origin_xy[0], origin_xy[1]))
    return note


def sheet_part(sheet):
    return sheet.OwningPart


# ------------------------------------------------------------ view placement
def view_bbox(view):
    """Extent box centre + size from AskViewBorders.

    注意：边框含视图标签/边界余量，可以比内容大很多（实测 TOP 视图边框高
    141mm 而内容 60mm），只能用于"视图占多大地方"的粗估，禁止用于内容
    定位与尺寸道推导——用 content_bbox()。"""
    ufs = _ufs()
    b = ufs.Draw.AskViewBorders(view.Tag)
    if isinstance(b, tuple):
        b = b[-1]
    return (0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3]),
            b[2] - b[0], b[3] - b[1])


def model_bbox(body):
    """Model-space bounding box as ((xmin,ymin,zmin), (xmax,ymax,zmax)).

    NX12 UF 把 UF_MODL_ask_bounding_box 封装在 ufs.ModlGeneral（不是
    ufs.Modeling——属性名写错时本函数会静默落入直边回退，纯回转体无直边
    即抛错；2026-09-25 冷测 T10 实证后修正），返回扁平
    [xmin,ymin,zmin,xmax,ymax,zmax]。
    """
    ufs = _ufs()
    try:
        r = ufs.ModlGeneral.AskBoundingBox(body.Tag)
        return ((r[0], r[1], r[2]), (r[3], r[4], r[5]))
    except Exception:
        pass
    xs, ys, zs = [], [], []
    for _e, p1, p2 in linear_edges(body):
        xs += [p1.X, p2.X]
        ys += [p1.Y, p2.Y]
        zs += [p1.Z, p2.Z]
    if not xs:
        raise RuntimeError("model_bbox: body has no edges")
    return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def content_bbox(view, mmin, mmax):
    """Drawing-space extent of the view's CONTENT: the model bbox corners
    mapped model->drawing.  This is the truth for layout and dimension
    lanes; AskViewBorders is inflated by label margins (measured)."""
    pts = [map_point(view, (x, y, z))
           for x in (mmin[0], mmax[0])
           for y in (mmin[1], mmax[1])
           for z in (mmin[2], mmax[2])]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def pin_view(sheet, view, cx, cy, scale=1.0, tol=0.05, tries=3, bbox=None):
    """Pin a view so its CONTENT centre lands at (cx, cy) sheet mm.

    SetDrawingReferencePoint anchors the view's reference model point, which
    is not the content centre, so each Set is followed by a measured
    content-centre delta and one compensating Set (constant per view ->
    converges; measured <0.05mm).  bbox = model_bbox() result, needed for
    the content measurement.  Content moves are rolled back if a LATER call
    on the same sheet raises "Cannot move view off of the drawing" (measured
    2026-09-24), so the caller must keep every view in-sheet."""
    if bbox is None:
        raise RuntimeError("pin_view: bbox=model_bbox() is required")
    ufs = _ufs()
    ufs.Draw.SetViewScale(view.Tag, float(scale))
    tx, ty = float(cx), float(cy)
    last = None
    for _ in range(tries):
        view.SetDrawingReferencePoint(NXOpen.Point3d(tx, ty, 0.0))
        ufs.Draw.UpdateOneView(sheet.Tag, view.Tag)
        b = content_bbox(view, bbox[0], bbox[1])
        last = b
        dx = cx - (b[0] + b[2]) / 2.0
        dy = cy - (b[1] + b[3]) / 2.0
        if abs(dx) <= tol and abs(dy) <= tol:
            return b
        tx, ty = tx + dx, ty + dy
    raise RuntimeError("pin_view did not converge (delta %.3f, %.3f)"
                       % (tx - (last[0] + last[2]) / 2.0,
                          ty - (last[1] + last[3]) / 2.0))


def standard_views(part, sheet, body=None, scale=1.0, gap=VIEW_GAP,
                   margin=VIEW_MARGIN, size="A4"):
    """Create the first-angle trio (FRONT above, TOP below, RIGHT beside),
    pinned by CONTENT centre into the free area above the title block.
    Call blank_datums() BEFORE this.  body defaults to the part's single
    body.  Returns {"FRONT": view, "TOP": view, "RIGHT": view}."""
    ufs = _ufs()
    if body is None:
        bodies = list(part.Bodies)
        if len(bodies) != 1:
            raise RuntimeError("standard_views: pass body= for multi-body "
                               "parts (%d bodies)" % len(bodies))
        body = bodies[0]
    bbox = model_bbox(body)
    sheet.Open()
    svb = part.DraftingViews.CreateStandardViewsBuilder()
    svb.Part = part
    svb.ViewType = NXOpen.Drawings.StandardViewsBuilder.View.Base
    svb.LayoutType = NXOpen.Drawings.StandardViewsBuilder.Type.FrontTopRight
    svb.PlacementType = NXOpen.Drawings.StandardViewsBuilder.Placement.Center
    svb.Autoscale = True
    svb.Commit()
    svb.Destroy()
    sheet.Open()
    keep = ("FRONT", "TOP", "RIGHT")
    views = {}
    for v in sheet.GetDraftingViews():
        key = v.Name.split("@")[0].upper()
        if key in keep:
            views[key] = v
    missing = [k for k in keep if k not in views]
    if missing:
        raise RuntimeError("standard views missing: %s" % (missing,))
    # DraftingDrawingSheet exposes no Width/Height attribute in NX 12
    # (measured 2026-09-24); the size is known from new_sheet instead
    w, h = SHEET[size]
    # measure each view's content size at the target scale
    sizes = {}
    for k in keep:
        v = views[k]
        ufs.Draw.SetViewScale(v.Tag, float(scale))
        ufs.Draw.UpdateOneView(sheet.Tag, v.Tag)
        b = content_bbox(v, bbox[0], bbox[1])
        sizes[k] = (b[2] - b[0], b[3] - b[1])
    c = NONBIND_C[size]
    fx = BINDING_A + margin + sizes["FRONT"][0] / 2.0
    fy = h - c - margin - sizes["FRONT"][1] / 2.0
    pos = {
        "FRONT": (fx, fy),
        "TOP": (fx, fy - sizes["FRONT"][1] / 2.0 - gap
                - sizes["TOP"][1] / 2.0),
        "RIGHT": (fx + sizes["FRONT"][0] / 2.0 + gap
                  + sizes["RIGHT"][0] / 2.0, fy),
    }
    for k in keep:
        pin_view(sheet, views[k], pos[k][0], pos[k][1], scale, bbox=bbox)
    return views


def projected_views(part, sheet, parent, dx=0.0, dy=0.0):
    """Orthographic views projected from `parent`; call UpdateOneView (done
    here) before asking any view for visible objects, otherwise the count is
    0 even though the view plots (measured 2026-09-23)."""
    ufs = _ufs()
    sheet.Open()
    made = {}
    ref = parent_ref(parent)
    for name, d in (("BELOW", (0.0, -1.0)), ("RIGHT", (1.0, 0.0))):
        pos = [ref[0] + d[0] * float(dx), ref[1] + d[1] * float(dy)]
        r = ufs.Draw.AddOrthographicView(
            sheet.Tag, parent.Tag, getattr(ufs.Draw.ProjDir,
                                           "PROJECT_" + name),
            [float(pos[0]), float(pos[1])])
        tag = _norm(r)
        ufs.Draw.UpdateOneView(sheet.Tag, tag)
        made[name] = tag
    return made


def parent_ref(view):
    r = view.GetDrawingReferencePoint()
    return (r.X, r.Y)


def detail_rect(bx, by, half_w, half_h):
    """Selection rectangle for AddDetailView around (bx,by): NX draws the
    boundary circle at ~0.83x the rectangle's half-diagonal (measured), so
    the rectangle is inflated until the circle covers the requested box."""
    import math
    # inflate uniformly so the half-diagonal covers the boundary circle
    # (circle radius ~= 0.83 x selection-rect half-diagonal)
    k = 1.0 / DETAIL_CIRCLE_FACTOR
    return (bx - half_w * k, by - half_h * k,
            bx + half_w * k, by + half_h * k)


# ------------------------------------------------------- geometry discovery
def hole_circles(body, radius=None, tol=0.01):
    """Full-circle edges of cylindrical faces (hole openings), kept per (x,y)
    at the highest z (the opening a top view sees).  radius filters out
    blends; a radius-blind pick makes the dimension read the blend instead of
    the hole (silent wrong value, per 19_drafting_annotation.py).
    Returns [(edge, (x, y, z), radius)]."""
    out = {}
    for face in body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            continue
        try:
            r = abs(_ufs().Modeling.AskFaceData(face.Tag)[4])
        except Exception:
            continue
        if radius is not None and abs(r - float(radius)) > tol:
            continue
        for e in face.GetEdges():
            try:
                p1, p2 = e.GetVertices()
            except Exception:
                continue
            if (abs(p1.X - p2.X) > 0.05 or abs(p1.Y - p2.Y) > 0.05
                    or abs(p1.Z - p2.Z) > 0.05):
                continue
            key = (round(p1.X, 3), round(p1.Y, 3))
            if key not in out or p1.Z > out[key][1]:
                out[key] = (e, p1.Z, r)
    return [(v[0], (k[0], k[1], v[1]), v[2]) for k, v in sorted(out.items())]


def linear_edges(body):
    """All straight edges as [(edge, p1, p2)] with vertex coordinates."""
    out = []
    for face in body.GetFaces():
        for e in face.GetEdges():
            try:
                p1, p2 = e.GetVertices()
            except Exception:
                continue
            if (abs(p1.X - p2.X) < 0.05 and abs(p1.Y - p2.Y) < 0.05
                    and abs(p1.Z - p2.Z) < 0.05):
                continue
            out.append((e, p1, p2))
    return out


def extreme_edge(edges, along, key, side):
    """Pick the edge that runs along `along` ('x'/'y'/'z') and is extreme in
    `key` coordinate ('min'/'max').  Model-side pick: in the TOP view an edge
    along y at min x is the left outline, in FRONT an edge along x at max z
    is the top outline."""
    axis = {"x": 0, "y": 1, "z": 2}[along]
    k = {"x": 0, "y": 1, "z": 2}[key]
    best = None
    for e, p1, p2 in edges:
        d = [abs(p2.X - p1.X), abs(p2.Y - p1.Y), abs(p2.Z - p1.Z)]
        span = max(d)
        if span < 0.05 or d[axis] < 0.9 * span:
            continue
        val = (p1.X, p1.Y, p1.Z)[k]
        if best is None or (side == "min" and val < best[1]) \
                or (side == "max" and val > best[1]):
            best = (e, val, p1, p2)
    if best is None:
        raise RuntimeError("extreme_edge: no edge along %s for %s %s"
                           % (along, key, side))
    return best


def map_point(view, model_xyz):
    """UF_VIEW_map_model_to_drawing with the documented fallback formula.
    Accepts NXOpen.Point3d or any (x, y, z) sequence."""
    ufs = _ufs()
    if hasattr(model_xyz, "X"):
        xyz = (float(model_xyz.X), float(model_xyz.Y), float(model_xyz.Z))
    else:
        xyz = (float(model_xyz[0]), float(model_xyz[1]),
               float(model_xyz[2]))
    try:
        r = ufs.View.MapModelToDrawing(view.Tag, list(xyz))
        cand = r[1] if isinstance(r, tuple) else r
        if hasattr(cand, "__len__") and len(cand) >= 2:
            return (float(cand[0]), float(cand[1]))
    except Exception:
        pass
    ref = parent_ref(view)
    return (ref[0] + xyz[0], ref[1] + xyz[1])


# ----------------------------------------------------------------- dimensions
def _assoc_obj(edge, view, assoc, model_xyz):
    ufs = _ufs()
    xy = map_point(view, model_xyz)
    o = ufs.Drf.Object()
    ufs.Drf.InitObjectStructure(o)
    o.ObjectAssocType = getattr(NXOpen.UF.Drf.AssocType, assoc)
    o.ObjectTag = edge.Tag
    o.ObjectViewTag = view.Tag
    o.AssocDwgPos = [float(xy[0]), float(xy[1])]
    return o, xy


def dim_between(part, view, a, b, lane_y=None, lane_x=None, horizontal=True,
                text=None):
    """Linear dimension between two attachments.

    a/b = (edge, assoc_type, model_point).  The dimension line sits at
    lane_y (horizontal dim) or lane_x (vertical dim) in sheet mm — pass
    view_bbox() based values, e.g. bbox bottom - LANE_FIRST."""
    ufs = _ufs()
    oa, xy_a = _assoc_obj(a[0], view, a[1], a[2])
    ob, xy_b = _assoc_obj(b[0], view, b[1], b[2])
    txt = ufs.Drf.Text()
    if horizontal:
        org = [(xy_a[0] + xy_b[0]) / 2.0, float(lane_y), 0.0]
        r = ufs.Drf.CreateHorizontalDim(oa, ob, txt, org)
    else:
        org = [float(lane_x), (xy_a[1] + xy_b[1]) / 2.0, 0.0]
        r = ufs.Drf.CreateVerticalDim(oa, ob, txt, org)
    return _norm(r)


def dim_diameter(part, view, edge, center_model, org_xy, text=None):
    """Diameter callout with a leader landing at org_xy (sheet mm)."""
    ufs = _ufs()
    o, _xy = _assoc_obj(edge, view, "ARC_CENTER", center_model)
    txt = ufs.Drf.Text()
    r = ufs.Drf.CreateDiameterDim(o, txt, [float(org_xy[0]),
                                           float(org_xy[1]), 0.0])
    return _norm(r)


def quantity_label(part, view, edge, center_model, org_xy, text):
    """Quantity callout for a group of identical features (GB/T 4458.4-2003
    group elements): one leader label "2x<O>10" instead of one dim_diameter
    per hole — UF diameter dims cannot carry a count prefix
    (drafting-annotation.md §4b, measured dead end).

    edge = the real circle edge in `view`, center_model = its centre in
    model mm (the leader lands there, mapped to sheet mm), org_xy = text
    position in sheet mm.  Lettering forced to TEXT_DIM (UF CreateLabel is
    6.5 uncontrolled).  Returns the label object."""
    _o, xy = _assoc_obj(edge, view, "ARC_CENTER", center_model)
    bundle = part.Annotations.NewLeaderBundle()
    try:
        bundle.NumberOfLeaders = 1   # must precede SetLeaderData (§5 ⚠)
    except Exception:
        pass
    bundle.SetLeaderData(0, NXOpen.Annotations.LeaderAttachment.Screen,
                         edge, view, NXOpen.Point3d(float(xy[0]),
                                                    float(xy[1]), 0.0),
                         0.0, [])
    label = part.Annotations.CreateLabel(
        [text], NXOpen.Point3d(float(org_xy[0]), float(org_xy[1]), 0.0),
        None, None, None, bundle)
    if label is None:
        raise RuntimeError("gb_drawing: CreateLabel returned None")
    lp = label.GetLetteringPreferences()
    g = lp.GetGeneralText()
    g.Size = TEXT_DIM
    lp.SetGeneralText(g)
    label.SetLetteringPreferences(lp)
    return label


# ---------------------------------------------------------------- centerlines
def centermark(part, view, edge, center_model):
    cmb = part.Annotations.Centerlines.CreateCenterMarkBuilder(
        NXOpen.Annotations.CenterMark.Null)
    cmb.Locations.Add(edge, view, NXOpen.Point3d(
        float(center_model[0]), float(center_model[1]),
        float(center_model[2])))
    r = cmb.Commit()
    cmb.Destroy()
    return r


def centerline_by_points(part, view, edge_a, pt_a, edge_b, pt_b):
    c2 = part.Annotations.Centerlines.CreateCenterline2dBuilder(
        NXOpen.Annotations.Centerline2d.Null)
    c2.Type = c2.Types.ByPoints
    c2.Point1.SetValue(edge_a, view, NXOpen.Point3d(
        float(pt_a[0]), float(pt_a[1]), float(pt_a[2])))
    c2.Point2.SetValue(edge_b, view, NXOpen.Point3d(
        float(pt_b[0]), float(pt_b[1]), float(pt_b[2])))
    r = c2.Commit()
    c2.Destroy()
    return r


# -------------------------------------------------------------------- export
def export_pdf(part, sheet, path):
    """Plot one sheet to PDF (PrintPDFBuilder; measured 2026-09-17)."""
    import os
    if os.path.exists(path):
        os.remove(path)
    pdfb = part.PlotManager.CreatePrintPdfbuilder()
    pdfb.SourceBuilder.SetSheets([sheet])
    pdfb.Colors = NXOpen.PrintPDFBuilder.Color.BlackOnWhite
    pdfb.Size = NXOpen.PrintPDFBuilder.SizeOption.FullScale
    pdfb.Units = NXOpen.PrintPDFBuilder.UnitsOption.Metric
    pdfb.Scale = 1.0
    pdfb.Filename = path
    pdfb.Commit()
    pdfb.Destroy()
    if not os.path.exists(path):
        raise RuntimeError("export_pdf: %s was not written" % (path,))
    return path


def scale_text(s):
    """1.0 -> '1:1', 2.5 -> '2.5:1', 0.5 -> '1:2' (reference sheet uses '2.5:1')."""
    s = float(s)
    if abs(s - 1.0) < 1e-9:
        return "1:1"
    if s > 1.0:
        return ("%g:1" % s)
    return "1:%g" % (1.0 / s)
