# 国标工程图标准件 gb_drawing.py

`scripts/gb_drawing.py`：NX 12 Python 3.6 模块，目录入 `sys.path` 后 `import gb_drawing`，按序调用即出图。

## 最小调用骨架

```python
import os, sys

# cwd 不在 sys.path；用绝对路径插入。
SKILL = r"C:\path\to\nxopen-journal"; WORK = r"C:\path\to\work"
for p in (os.path.join(SKILL, "scripts"), WORK):
    if p not in sys.path: sys.path.insert(0, p)
import gb_drawing as gb

part = ...                # 体先于出图
gb.blank_datums(part)     # 不消隐→箭头杂线
gb.apply_gb_preferences(part)   # 3.5/2.5 实心箭头
gb.set_cjk_font(part)     # 中文必须；默认 blockfont 把汉字画成空框
sheet = gb.new_sheet(part, "SHT1", "A4")
frame = gb.frame(sheet, "A4")   # 25/5
views = gb.standard_views(part, sheet, body=body, scale=1.0)
tb = gb.title_block(sheet, frame, name=u"试验板", dwg_no="NXOJ-33", scale_txt=gb.scale_text(1.0))
gb.tech_note(sheet, tb)   # GB/T 1804-m + 1184-K
bbox = gb.model_bbox(body); ct = gb.content_bbox(views["TOP"], *bbox)
gb.dim_between(part, views["TOP"], (e1, "END_POINT", p1), (e2, "END_POINT", p2), lane_y=ct[1]-gb.LANE_FIRST)
gb.dim_diameter(part, views["TOP"], hole_edge, hole_center, (x, y))
gb.centermark(part, views["TOP"], hole_edge, hole_center)
gb.export_pdf(part, sheet, "drawing.pdf")
```

调用顺序：建模 → `blank_datums` → `apply_gb_preferences` → `set_cjk_font` → `new_sheet` → `frame` → `standard_views` → `title_block`/`tech_note` → 尺寸/中心线 → `export_pdf`。道位用 `content_bbox`（`LANE_FIRST=10`、`LANE_STEP=7`），勿用 `view_bbox`；同向多道小内大外。

## 国标条款与本技能实现口径

| 条款 | 内容 | 本技能口径 |
| --- | --- | --- |
| GB/T 14689.1 | 幅面与边距 | A4/A3；a=25、c=5；单格表格 + 0.7 双线宽 |
| GB/T 14689.1 | 投影角 | 第一角（`ProjectionAngleType.FirstAngle`） |
| GB/T 10609.1 | 标题栏字段 | 设计/校核/日期/图号/比例/材料/图名；模块实现 105×21 简化版（3 行 7mm、六列），标准全格式 180×56 未实现 |
| GB/T 4458.4 | 尺寸注法 | 道位 10/7；小内大外；等径孔一条数量引线；UF 关联尺寸（细则见 `drafting-annotation.md` §3/§4b） |
| GB/T 14691 | 字体 | 3.5（尺寸/技术要求）、2.5（标题栏）；中文用 `chinesef`（`set_cjk_font`），默认 blockfont 出空框 |
| GB/T 1804-m / GB/T 1184-K | 未注公差 | `tech_note` 默认，`lines=` 覆盖 |

## 模块路线约束

- `pin_view` 收敛（<0.05mm）；`AskViewBorders` 含标签余量仅粗估，道位用 `model_bbox`+`content_bbox`。
- 图框/自定义表格线也可用 `part.Curves.CreateLine(...)`（`sheet.Open()` 后）；标准图框优先 `gb.frame`。
- `Cannot move view off of the drawing` 回滚已成功的视图移动；不得出图幅。
- 枚举 `END_POINT`（`UF_DRF_end_point`）非 `ENDPOINT`；圆心 `ARC_CENTER`。
- Note 先设 `LetteringPreferences.AlignmentPosition=TopLeft`，再设 `AnnotationOrigin`。
- 2.5 字高 ASCII 字宽约 2.1mm：10 字符日期恰好占满 21mm、无余量会溢出画 `#`；日期/数值列 25、标签列 10。
- 行高逐格 `NmFitMethods=0`；原点=左上角、向下生长。
- 表格行数 = `len(row_heights)`，不是 data 行数：heights 多一项就在表底多一行空框；反之 data 多出的行不显示。
- PDF 连字符成 U+00AD，中文抽取不出；文字审计对 `\xad` 归一化。

## 模块路线约束补充

- `model_bbox` 主路线 = `ufs.ModlGeneral.AskBoundingBox`（NX12 在 **ModlGeneral** 组，非 `ufs.Modeling`）；名字错误静默回退直边。

## 非轴对齐零件出图（自然坐标系）

零件存储系与出图系差一个绕 Z 的转角时，**不要旋转实体**：批处理下 `ufs.Modl.TransformEntities` 对实体静默不生效，保存后才报 `Update undo happened`；Drafting 视图调用 `View.Rotate` 直接抛 `The view may not be rotated`。

正确做法 = 用自定义模型视图承载自然坐标系，再从该视图建基本视图：

```python
gb.save_model_view(part, "VFRONT", ((C, C, 0.0), (0.0, 0.0, 1.0), (C, -C, 0.0)))
gb.save_model_view(part, "VTOP",    ((C, C, 0.0), (-C, C, 0.0), (0.0, 0.0, 1.0)))
gb.save_model_view(part, "VLEFT",   ((C, -C, 0.0), (0.0, 0.0, 1.0), (-C, -C, 0.0)))
base = gb.base_view(part, sheet, "VFRONT")
```

- **顺序硬约束**：`save_model_view` 必须在 `new_sheet` 之前。图纸一打开 `Views.WorkView` 就是 drafting view，再调 `SetRotationTranslationScale` 报 `The view may not be rotated`。

```python
# 等价底层写法（行 = 屏幕 X / 屏幕 Y / 视线 Z，绝对坐标）
m = NXOpen.Matrix3x3()
m.Xx, m.Xy, m.Xz = C, C, 0.0               # 自然 X
m.Yx, m.Yy, m.Yz = 0.0, 0.0, 1.0           # 自然 Z 向上
m.Zx, m.Zy, m.Zz = C, -C, 0.0              # 视线方向
part.Views.WorkView.SetRotationTranslationScale(m, NXOpen.Point3d(0,0,0), 1.0)
part.Views.SaveAs(part.Views.WorkView, "VFRONT", True, True)     # 存为命名模型视图
...
bv = part.DraftingViews.CreateBaseViewBuilder(NXOpen.Drawings.BaseView.Null)
bv.SelectModelView.SelectedView = part.Views.FindObject("VFRONT")  # 直接赋 Model view 对象
bv.Commit(); bv.Destroy()
```

- 三个视图各存一个模型视图（前/俯/左）。第一角左视图：`X=-natY`、`Y=natZ`、`Z=-natX`；俯视图：`X=natX`、`Y=natY`、`Z=natZ`。
- 基本视图默认 autoscale（如 0.354），Commit 后用 `ufs.Draw.SetViewScale(tag, scale)` + `UpdateOneView` 才生效；builder 的 `Scale.Numerator/Denominator` 在批处理下不可靠。
- `base_view` 返回的视图落在图纸坐标原点（左下角），大部分几何在纸外；必须再由 `SetDrawingReferencePoint` + 内容包盒迭代把视图摆到目标位置。
- `BaseViewBuilder.Placement.Placement` 是 `SelectObject`，`SetValue(None,None,Point3d)` 报参数不匹配 → 统一走 `SetDrawingReferencePoint` + 包盒迭代定位。
- 带转角的零件其轴对齐包围盒会明显大于真实自然系包盒（菱形板件差 ~24 mm/边），包盒取**全部边顶点在自然系下的并集**，不要旋转世界包盒角点。
- `MapModelToDrawing` 只接受 Drafting 视图；模型视图上调用报 `View tag is invalid for this operation`。

## 视图样式（隐藏线 / 虚拟交线 / 平滑边）

```python
b = part.SettingsManager.CreateDrawingEditViewSettingsBuilder([view])
b.ViewStyle.ViewStyleHiddenLines.HiddenLine = True          # 默认开
b.ViewStyle.ViewStyleVirtualIntersections.VirtualIntersections = False
b.ViewStyle.ViewStyleSmoothEdges.SmoothEdge = False         # 基本视图默认已关
b.Commit(); b.Destroy()
```

- `part.SettingsManager` 的实际类型是 `NXOpen.Drafting.SettingsManager`，不是 `Part.SettingsManager`。
- 隐藏线默认**开**；对多段线放样体关掉隐藏线会触发可见边重算，产生大量重叠短线，打印反而更黑 → 保持开。
- 虚拟交线默认**开**；关掉可减少一部分曲线，但消不掉放样体的面边界。
- 平滑边默认**关**；放样体视图里的密集纵向线是真实面边界，切换该开关无效。要减少只能重建更少/更光滑的面，或接受并在技术要求注明“图示真实边界”。

## 视图级简化（隐去布尔交线）

- `DraftingView.AskVisibleObjects()` 返回 `DraftingCurve` 列表（不是模型边）；`curve.GetDraftingCurveInfo().GetParents()` 取回父模型边。`DraftingCurveInfo` 运行期没有 `FreeResource`，不要调用。
- 按父边几何筛出交线后，`view.DependentDisplay.Erase(curves)` 只在当前视图隐藏，模型与其它视图不受影响；随后 `view.UpdateDisplay()` 再导出 PDF。
- **按几何区域筛出交线再隐藏**（凸台内部、闭环或变 x 曲线；阈值按件确定）；按 `SolidEdgeType == Intersection` 全删会切断外形轮廓。
- 该操作会永久写入图纸 PRT；重跑生成脚本时先重新建视图，再执行筛除。

## 中文字体（注释/表格/标题栏）

NX 默认 `blockfont` 只有拉丁字形，中文在 PDF 里是一排空框。做法：

```python
fonts = part.Fonts
fid = None
for i in range(1, fonts.GetLength() + 1):          # 字体 ID 从 1 开始
    if fonts.GetFontName(i) == "chinesef":
        fid = i; break
if fid is None:
    r = fonts.AddFont("chinesef", NXOpen.FontCollection.Type.Nx)
    fid = r[0] if isinstance(r, tuple) else r
lp = part.Annotations.Preferences.GetLetteringPreferences()
for getter, setter in ((lp.GetGeneralText, lp.SetGeneralText),
                       (lp.GetDimensionText, lp.SetDimensionText),
                       (lp.GetAppendedText, lp.SetAppendedText),
                       (lp.GetToleranceText, lp.SetToleranceText)):
    lt = getter(); cfw = lt.Cfw; cfw.Font = int(fid); lt.Cfw = cfw; setter(lt)
part.Annotations.Preferences.SetLetteringPreferences(lp)
```

等价调用：`gb.set_cjk_font(part)`（返回字体 id）。

- 字体在 `.NET Annotations.Lettering.Cfw.Font`（整数 ID），**没有** `Lettering.Font`；UF 的 `Drf.Lettering_Struct` 也没有 Font，只有 Cfw。
- `Arial Unicode MS` 已加载（ID=2）但 NX 描边绘图不渲染其中文字形；`chinesef` 正常。
- 中文用 `chinesef` 后 ASCII 会变等宽，尺寸数字仍清晰；`<O>` 等控制序列不受影响。
- 表格单元字高走 `Tabnot.AskDefaultCellPrefs().TextHeight`；标题栏 10 字符日期在 25 mm 列仍溢出时，把该 cell 的 `TextHeight` 调到 2.2 或改用年月（`2026-10`）。

## 文字控制字符（SetCellText / Note）

> 直径写 `<O>` 的规则见 `drafting-annotation.md` §1；本表只列其余控制字符。

| 字符 | 症状 | 做法 |
| --- | --- | --- |
| `×` (U+00D7) | `Locale data detected when UTF8 data was expected`（拉丁补充区字符同罪） | 写 ASCII `x` |
| `~` | 被当成 NX 文本控制符，渲染成空格或丢字 | 写 `-` 或 `至` |
| `%` | 可用 | — |


## 标注配方（GB/T 4458.4-2003）

> 道位（10/7、小内大外）、数量引线与文字布点规则见 `drafting-annotation.md` §3/§4b；本模块只列 `gb_drawing` 的专用行为。

- **数量引线**：`dim_diameter` 无数量前缀，成组等径孔走 `quantity_label(part, view, edge, centre, org, "2x<O>10")`（字高 3.5；均布加 EQS）。
- **尺寸文字落在轮廓外**：`content_bbox(view, ...)` 取内容包盒，`dim_text_box(center_xy, text, size)` 估算文字框（chinesef 3.5 约 3.81 mm/字符、框高 7.0 mm），`box_overlap(box, content_bbox, gap=0)` 逐条判重叠；`dim_diameter` 的 `org_xy` 是文字中心，箭头仍在圆弧上，移动 `org_xy` 即可拉长引出线。
- **自定义尺寸文字走 `quantity_label`**；`dim_diameter` 的 `text` 形参不生效，文字始终按所选圆弧的实际值自动生成 `Ø<值>`。
- 无法用直径表达的小特征（凹槽圆角等）宁可不标，由技术要求兜底，不要硬造一个 `Ø` 引线压在轮廓上。
- **成图前清理未请求的中心标记**：遍历 `part.Annotations.Centerlines`，把不是本次 `gb.centermark` 返回对象的 `CenterMark` 全部 `Blank()`（保留返回对象 tag 的集合）。否则图上会留下孤立十字，`dim_diameter` 前导的 mark 也可能残留在别的视图。

## API 速查

| 函数 |
| --- |
| `new_sheet(part,name,size)`、`frame(sheet,size)`、`standard_views(part,sheet,body,scale,size)`、`projected_views(part,sheet,parent,dx,dy)`、`pin_view(sheet,view,cx,cy,scale,bbox)` |
| `blank_datums(part)`、`apply_gb_preferences(part)`、`model_bbox(body)`、`assembly_bbox(bodies)`、`content_bbox(view,...)` |
| `title_block(sheet,frame_geo,...)`、`tech_note(sheet,tb_geo,lines,base_y=None)`、`part_note(sheet,lines,origin)`、`hole_circles(body,radius)`、`linear_edges(body)`、`extreme_edge(...)` |
| `save_model_view(part,name,rows)`、`base_view(part,sheet,name)`、`set_cjk_font(part)`（非轴对齐出图与中文出图） |
| `dim_between(...)`、`dim_diameter(...)`、`dim_text_box(...)`、`box_overlap(...)`、`quantity_label(part,view,edge,centre,org,text)`、`centermark`、`centerline_by_points`、`export_pdf(part,sheet,path)`、`scale_text(s)` |

## 未覆盖范围

A0/A1（c=10）、GB/T 10609.1 全格式标题栏未实现；剖视图部分已通（drafting.md B.4、31 号用例），"成套剖视 + 标注"未解；局部放大 `detail_rect`（半径 ≈ 半对角 × 0.83）。

## 装配图

- **包盒**：`standard_views`/`model_bbox` 只接受单 body；装配用 `gb.assembly_bbox([...])` 并集，须计入齿顶、端盖、轴伸（漏算裁顶部）。
- **尺寸值 PDF 文本层复核**：`extreme_edge` + `dim_between` 在装配实例边/剖视上即使两边不同、`AssocDwgPos` 显式给出也可能读错；pymupdf 逐值对账，对不上改写到技术要求。
- **明细栏**：位于标题栏上方时传 `base_y=明细栏顶边`，避免压字。
