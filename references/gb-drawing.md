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
body = list(part.Bodies)[0]  # 多体件必须显式指定
gb.blank_datums(part)     # 不消隐→箭头杂线
gb.apply_gb_preferences(part)   # 3.5/2.5 实心箭头
gb.set_cjk_font(part)     # 注释/表格默认已出中文；尺寸·公差文字才必须（见下）
sheet = gb.new_sheet(part, "SHT1", "A4")
frame = gb.frame(sheet, "A4")   # 25/5
views = gb.standard_views(part, sheet, body=body, scale=1.0, size="A4")
tb = gb.title_block(sheet, frame, name=u"试验板", dwg_no="NXOJ-33", scale_txt=gb.scale_text(1.0))
gb.tech_note(sheet, tb)   # GB/T 1804-m + 1184-K
bbox = gb.model_bbox(body); ct = gb.content_bbox(views["TOP"], *bbox)
gb.dim_between(part, views["TOP"], (e1, "END_POINT", p1), (e2, "END_POINT", p2), lane_y=ct[1]-gb.LANE_FIRST)
gb.dim_diameter(part, views["TOP"], hole_edge, hole_center, (x, y))
gb.centermark(part, views["TOP"], hole_edge, hole_center)
gb.export_pdf(part, sheet, "drawing.pdf")
```

调用顺序：建模 → `blank_datums` → `apply_gb_preferences` → `set_cjk_font` → `new_sheet` → `frame` → `standard_views`（必须传 `size=`，与 `new_sheet` 一致；不传即抛 `RuntimeError: standard_views: pass size=`）→ `title_block`/`tech_note` → 尺寸/中心线 → `export_pdf`。道位用 `content_bbox`（`LANE_FIRST=10`、`LANE_STEP=7`），勿用 `view_bbox`；同向多道小内大外。

## 国标条款与本技能实现口径

| 条款 | 内容 | 本技能口径 |
| --- | --- | --- |
| GB/T 14689.1 | 幅面与边距 | A4/A3；a=25、c=5；单格表格 + 0.7 双线宽 |
| GB/T 14689.1 | 投影角 | 第一角（`ProjectionAngleType.FirstAngle`） |
| GB/T 10609.1 | 标题栏字段 | 设计/校核/日期/图号/比例/材料/图名；模块实现 105×21 简化版（3 行 7mm、六列），标准全格式 180×56 未实现 |
| GB/T 4458.4 | 尺寸注法 | 道位 10/7；小内大外；等径孔一条数量引线；UF 关联尺寸（细则见 `drafting-annotation.md` §3/§4b） |
| GB/T 14691 | 字体 | 3.5（尺寸/技术要求）、2.5（标题栏）；中文**默认就出得来**（模板 general/appended 字型本就是 `chinesef_fs`）；只有**尺寸/公差文字**默认 `blockfont`（无 CJK 字形），要出中文才必须 `set_cjk_font`（它把四类字型统一指向 `chinesef`） |
| GB/T 1804-m / GB/T 1184-K | 未注公差 | `tech_note` 默认，`lines=` 覆盖 |

## 模块路线约束

- `pin_view` 收敛（<0.05mm）；`AskViewBorders` 含标签余量仅粗估，道位用 `model_bbox`+`content_bbox`。
- `standard_views` 的摆位：NX 原生 `FrontTopRight` 布局（未钉位）把 `RIGHT` 放在 FRONT **左侧**（内容中心 x=67 vs 198）；`gb.standard_views` 却把 `RIGHT` 钉到 FRONT **右侧**（x=195 vs 93，TOP 在 FRONT 下方）——即同一张第一角图纸上，本模块的摆位与 NX 原生第一角布局左右相反，**布局方向与图幅角标不一致**。视图内容的投影手性（`RIGHT` 究竟是从右看还是其镜像）本文档未测，非对称件须按图核一遍。
- 图框/自定义表格线也可用 `part.Curves.CreateLine(...)`（`sheet.Open()` 后）；标准图框优先 `gb.frame`。
- `Cannot move view off of the drawing`：按视图参考点判定，且只在越界很远时才抛——参考点移到 (350,155) / (93,-40) / (-40,-30) 时内容已整块出纸仍**不报错**，只有移到 (-500,-500) 才抛该串，且那次调用自身不生效；抛错**不会**回滚之前已成功的移动（TOP 已被移到纸外，随后 FRONT 的越界调用抛错，TOP 参考点仍停在 (350,155)）。所以布局必须由代码自查：改完逐视图核 `content_bbox` 是否落在纸内。
- 枚举 `END_POINT`（`UF_DRF_end_point`）非 `ENDPOINT`；圆心 `ARC_CENTER`。
- Note 先设 `LetteringPreferences.AlignmentPosition=TopLeft`，再设 `AnnotationOrigin`。
- ASCII 字宽随字型变：模板默认 general 字型 `chinesef_fs`、2.5 字高时约 2.16 mm/字符（10 字符日期 ≈21.6mm，**21mm 列放不下**）；调过 `set_cjk_font`（`chinesef`）后约 1.88 mm/字符（≈18.8mm，21mm 列放得下）。溢出渲染为 `#`，个数 = floor(列宽/字宽)（14/18/21/25mm 列逐一吻合）；标题栏日期/数值列 25、标签列 10。
- 行高逐格 `NmFitMethods=0`；原点=左上角、向下生长。
- 表格行数 = `len(row_heights)`，不是 data 行数：heights 多一项就在表底多一行空框；反之 data 多出的行不显示。
- PDF 连字符成 U+00AD，中文抽取不出；文字审计对 `\xad` 归一化。

## 模块路线约束补充

- `model_bbox` 主路线 = `ufs.ModlGeneral.AskBoundingBox`（NX12 在 **ModlGeneral** 组，非 `ufs.Modeling`）；该调用失败时**打印 `WARN model_bbox: AskBoundingBox failed (...); using linear edges` 再回退直边**（非静默），纯回转体无直边时回退无料可用、直接抛错。

## 非轴对齐零件出图（自然坐标系）

零件存储系与出图系差一个绕 Z 的转角时，**可以旋转实体**：`ufs.Modl.TransformEntities` **有效**（矩阵是 4×4 = **16** 个浮点，只给 9 个报 `Expecting array dimension 16, found 9`），但**效果在下一次 update 之后才可见**——未 update 前用顶点/面表回读拿到的是旧值，很容易被误判成"静默不生效"（100×60 板绕 Z 转 45°，`DoUpdate` 后包盒才变成 113.14²）。保存成功，**不会**报 `Update undo happened`。Drafting 视图调用 `View.Rotate` 仍直接抛 `The view may not be rotated`。

另一条做法（不旋转实体）= 用自定义模型视图承载自然坐标系，再从该视图建基本视图：

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
- 基本视图默认 autoscale，Commit 后用 `ufs.Draw.SetViewScale(tag, scale)` + `UpdateOneView` 才生效；builder 的 `Scale.Numerator/Denominator` 在批处理下不可靠。
- `base_view` 返回的视图落在图纸坐标原点（左下角），大部分几何在纸外；必须再由 `SetDrawingReferencePoint` + 内容包盒迭代把视图摆到目标位置。
- `BaseViewBuilder.Placement.Placement` 是 `SelectObject`，`SetValue(None,None,Point3d)` 报参数不匹配 → 统一走 `SetDrawingReferencePoint` + 包盒迭代定位。
- 带转角的零件其轴对齐包围盒会明显大于真实自然系包盒，包盒取**全部边顶点在自然系下的并集**，不要旋转世界包盒角点。
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

- `DraftingView.AskVisibleObjects()` 返回的是**混合列表**（TOP = `Body`×1 + `DraftingCurve`×5），既不是纯 `DraftingCurve` 列表、也不是模型边；先按类型筛出 `DraftingCurve`（对 `Body` 调 `GetDraftingCurveInfo()` 报 `AttributeError: 'NXOpen.Body' object has no attribute 'GetDraftingCurveInfo'`），再 `curve.GetDraftingCurveInfo().GetParents()` 取回父模型边。`DraftingCurveInfo` 运行期没有 `FreeResource`，不要调用。
- 按父边几何筛出交线后，`view.DependentDisplay.Erase(curves)` 只在当前视图隐藏，模型与其它视图不受影响；随后 `view.UpdateDisplay()` 再导出 PDF。
- **按几何区域筛出交线再隐藏**（凸台内部、闭环或变 x 曲线；阈值按件确定）；按 `edge.SolidEdgeType == NXOpen.Edge.EdgeType.Intersection` 全删会切断外形轮廓。注意 `Edge.SolidEdgeType` **不是枚举、没有 `Intersection` 成员**（它只是 Edge 上的一个属性，值是小写 `.value`），比较必须用 `NXOpen.Edge.EdgeType.*`（`== Edge.EdgeType.Linear` 对直边全中）。
- 该操作会永久写入图纸 PRT；重跑生成脚本时先重新建视图，再执行筛除。

## 中文字体（注释/表格/标题栏）

模板四类字型的默认字体不同：`GeneralText`/`AppendedText` = id 2 `chinesef_fs`（有 CJK 字形），`DimensionText`/`ToleranceText` = id 1 `blockfont`（纯拉丁字形）。所以**注释/表格/技术要求里的中文默认就出得来**，不调 `set_cjk_font` 也正常；只有**尺寸/公差文字**要出中文（含 `2×` 这类前缀里的汉字）才必须调——`set_cjk_font` 把四类字型统一指向 `chinesef`。显式把 general 指成 `blockfont` 时中文才变成空框。做法：

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

- 字体在 `.NET Annotations.Lettering.Cfw.Font`（整数 ID），**没有** `Lettering.Font`；UF 侧是 `ufs.Drf.Lettering`（字段只有 `AspectRatio/Cfw/CharacterSpaceFactor/LineSpaceFactor/Size`，同样有 `Cfw` 无 `Font`）；`ufs.Drf.Lettering_Struct` 这个属性名不存在。
- `Arial Unicode MS` **不在** NX 字体表里（表内 8 项：`blockfont/chinesef_fs/blockfont_v2/chinesef_fs/chinesef/blockfont_v1/Arial/NX ANSI Symbols`；`fonts.AddFont("Arial Unicode MS", ...)` 报 `Font name was not found in the character font directory`），所以它渲不出中文是因为根本没加载；可用中文字体是 `chinesef` / `chinesef_fs`。
- 中文用 `chinesef` 后 ASCII 会变等宽，尺寸数字仍清晰；`<O>` 等控制序列不受影响。
- 表格单元字高走 `Tabnot.AskDefaultCellPrefs().TextHeight`；标题栏日期列宽 **25 mm**，出厂 2.5 字高下 10 字符日期 21.6 mm **放得下、不溢出**——只有把该 cell 字高调大（3.5 时 10 字符 ≈30 mm）或把列收窄，才会溢出画 `#`，那时才需要改小字高或改用年月文本。

## 文字控制字符（表格单元 / Note）

> 直径写 `<O>` 的规则见 `drafting-annotation.md` §1；本表只列其余控制字符。

| 字符 | 症状 | 做法 |
| --- | --- | --- |
| `×` (U+00D7) 及拉丁补充区字符（如 `é`） | **表格单元**：`Locale data detected when UTF8 data was expected.`，写入被拒、cell 留空（两种 cell 字高配置下都抛）；**Note 里创建不报错**，但 PDF 文本层里字符取不到（`café` → `caf`，`×` 处只剩空格） | 单元里写 ASCII `x`；Note 里也别用非 ASCII |
| `~` | 单元与 Note 一样：被当控制符，渲染成空格（单元 `1~2` → `1`／空格／`2`，Note 同）；存储值不变（回读仍是 `1~2`） | 写 `-` 或 `至` |
| `%` | 可用（单元 `50%` 写入、回读原样；Note 里 `50%` 出图正常。**出图文本层只在单元装不下时坏**：装不下就把文字逐字符替成 `#`，与 `%` 无关。判别读数：不显式设 cell 字高时文字实际约 7 mm 高（`AskDefaultCellPrefs` 报的 2.50 不是实际字高），30mm 列宽 + 7mm 行高读出 `###`、行高 20mm 读出 `50%`；显式把字高设 6.0 → 约 8.8 mm，7mm 行高读出 `###`；设 3.5 → 约 4.7 mm，7mm 行高与 12mm 列宽都读出 `50%`，行高换 3mm 读出 `###`；字高 2.5 + 行高 10mm 时 5mm 列宽读出 `##`、10/20mm 列宽读出 `50%`；ASCII 对照 `50x` 与 `50%` 每种配置同好同坏） | 建表前显式 `SetDefaultCellPrefs` 定字高并留余量（行高 > 实际字高、列宽 > 文字实宽），别按 `AskDefaultCellPrefs` 的读数估字高 |


## 标注配方（GB/T 4458.4-2003）

> 道位（10/7、小内大外）、数量引线与文字布点规则见 `drafting-annotation.md` §3/§4b；本模块只列 `gb_drawing` 的专用行为。

- **数量引线**：`dim_diameter` 默认不带数量前缀，成组等径孔走 `quantity_label(part, view, edge, centre, org, "2x<O>10")`（字高 3.5；均布加 EQS）；直径尺寸对象本身也能加前缀（`AppendedText.SetBeforeText`，见 `drafting-annotation.md` §4b）。
- **尺寸文字落在轮廓外**：`content_bbox(view, ...)` 取内容包盒，`dim_text_box(center_xy, text, size)` 估算文字框——该函数只有三行算术（`3.81×len(text)×size/3.5` 与 `7.0×size/3.5`），不查任何字体/文字度量 API，所以框是**保守上界**：33 号图上 Ø/线性尺寸文字（44/100/60/10）文本层字串宽 3.7–5.5mm（≈1.8–2.0 mm/字符），行距 5.25mm（1.5×字高）而框高取 7.0mm（2×字高），`box_overlap(box, content_bbox, gap=0)` 可能报出墨迹并未接触的重叠——判为重叠后须在图上确认。`dim_diameter` 的 `org_xy` 是文字中心，箭头仍在圆弧上，移动 `org_xy` 即可拉长引出线。
- **自定义尺寸文字走 `quantity_label`**；`dim_diameter` 的 `text` 形参不生效，文字始终按所选圆弧的实际值自动生成 `Ø<值>`。
- 无法用直径表达的小特征（凹槽圆角等）宁可不标，由技术要求兜底，不要硬造一个 `Ø` 引线压在轮廓上。
- **成图前清理未请求的中心标记**：遍历 `part.Annotations.Centerlines`，把不是本次 `gb.centermark` 返回对象的 `CenterMark` 全部 `Blank()`（保留返回对象 tag 的集合）。否则图上会留下孤立十字。

## API 速查

| 函数 |
| --- |
| `new_sheet(part,name,size)`、`frame(sheet,size)`、`standard_views(part,sheet,body,scale,size)`、`projected_views(part,sheet,parent,dx,dy)`、`pin_view(sheet,view,cx,cy,scale,bbox)` |
| `blank_datums(part)`、`apply_gb_preferences(part)`、`model_bbox(body)`、`assembly_bbox(bodies)`、`content_bbox(view,...)` |
| `title_block(sheet,frame_geo,...)`、`tech_note(sheet,tb_geo,lines,base_y=None)`、`part_note(sheet,lines,origin)`、`hole_circles(body,radius)`、`linear_edges(body)`、`extreme_edge(...)` |
| `save_model_view(part,name,rows)`、`base_view(part,sheet,name)`、`set_cjk_font(part)`（非轴对齐出图与中文出图） |
| `dim_between(...)`、`dim_diameter(...)`、`dim_text_box(...)`、`box_overlap(...)`、`quantity_label(part,view,edge,centre,org,text)`、`centermark`、`centerline_by_points`、`export_pdf(part,sheet,path)`、`scale_text(s)` |

## 未覆盖范围

A0/A1（c=10）、GB/T 10609.1 全格式标题栏未实现；剖视图部分已通（drafting.md B.4、31 号用例），"成套剖视 + 标注"未解；局部放大 `detail_rect` 的选框外扩系数 `DETAIL_CIRCLE_FACTOR=0.83` 是启发式、来源不可复现（`AskViewBorders` 对 detail 返回选框本身、量不到边界圆），边界圆是否覆盖目标区只能在出图上目视确认、选框须留余量（细则见 `drafting.md` B.4）。

## 装配图

- **包盒**：`standard_views`/`model_bbox` 只接受单 body；装配用 `gb.assembly_bbox([...])` 并集，须计入齿顶、端盖、轴伸（漏算裁顶部）。
- **尺寸值 PDF 文本层复核**：`extreme_edge` + `dim_between` 在装配实例边/剖视上即使两边不同、`AssocDwgPos` 显式给出也可能读错；pymupdf 逐值对账，对不上改写到技术要求。
- **明细栏**：位于标题栏上方时传 `base_y=明细栏顶边`，避免压字。
