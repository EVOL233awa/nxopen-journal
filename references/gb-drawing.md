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

调用顺序：建模 → `blank_datums` → `new_sheet` → `frame` → `standard_views` → `title_block`/`tech_note` → 尺寸/中心线 → `export_pdf`。道位用 `content_bbox`（`LANE_FIRST=10`、`LANE_STEP=7`），勿用 `view_bbox`；同向多道小内大外。

## 国标条款与本技能实现口径

| 条款 | 内容 | 本技能口径 |
| --- | --- | --- |
| GB/T 14689.1 | 幅面与边距 | A4/A3；a=25、c=5；单格表格 + 0.7 双线宽 |
| GB/T 14689.1 | 投影角 | 第一角（`ProjectionAngleType.FirstAngle`） |
| GB/T 10609.1 | 标题栏字段 | 设计/校核/日期/图号/比例/材料/图名；105×21、3 行 7mm、六列 |
| GB/T 4458.4 | 尺寸注法 | 道位 10/7；小内大外；等径孔一条数量引线；UF 关联尺寸 |
| GB/T 14691 | 字体 | 3.5（尺寸/技术要求）、2.5（标题栏）；NX 默认中文字体 |
| GB/T 1804-m / GB/T 1184-K | 未注公差 | `tech_note` 默认，`lines=` 覆盖 |

## 模块内建的事实（勿绕过）

- `pin_view` 收敛（<0.05mm）；`AskViewBorders` 含标签余量仅粗估，道位用 `model_bbox`+`content_bbox`。
- `Cannot move view off of the drawing` 回滚已成功的视图移动；不得出图幅。
- 枚举 `END_POINT`（`UF_DRF_end_point`）非 `ENDPOINT`；圆心 `ARC_CENTER`。
- Note 先设 `LetteringPreferences.AlignmentPosition=TopLeft`，再设 `AnnotationOrigin`。
- 2.5 字高 ASCII 字宽约 2.1mm：21mm 列放不下 10 字符日期（画 `#`）；数值列 25、标签 10。
- 行高逐格 `NmFitMethods=0`；原点=左上角、向下生长。
- PDF 连字符成 U+00AD，中文抽取不出；文字审计对 `\xad` 归一化。

## 模块内建的事实补充

- `model_bbox` 主路线 = `ufs.ModlGeneral.AskBoundingBox`（NX12 在 **ModlGeneral** 组，非 `ufs.Modeling`）；名字错误静默回退直边。

## 标注配方（GB/T 4458.4-2003）

- **同向多道按数值升序外推**：小内大外，否则小尺寸界线穿过大尺寸线。
- **成组等径孔只标一条数量引线**：`2x<O>10`（GB/T 4458.4-2003；均布加 EQS）。`dim_diameter` 无数量前缀，走 `quantity_label`（字高 3.5）。

## API 速查

| 函数 |
| --- |
| `new_sheet(part,name,size)`、`frame(sheet,size)`、`standard_views(part,sheet,body,scale)`、`projected_views(part,sheet,parent,dx,dy)`、`pin_view(sheet,view,cx,cy,scale,bbox)` |
| `blank_datums(part)`、`apply_gb_preferences(part)`、`model_bbox(body)`、`assembly_bbox(bodies)`、`content_bbox(view,...)` |
| `title_block(sheet,frame_geo,...)`、`tech_note(sheet,tb_geo,lines,base_y=None)`、`part_note(sheet,lines,origin)`、`hole_circles(body,radius)`、`linear_edges(body)`、`extreme_edge(...)` |
| `dim_between(...)`、`dim_diameter(...)`、`quantity_label(part,view,edge,centre,org,text)`、`centermark`、`centerline_by_points`、`export_pdf(part,sheet,path)`、`scale_text(s)` |

## 扩展方向

A0/A1（c=10）、GB/T 10609.1 全格式标题栏、明细栏、隐藏线未实现；剖视图部分已通（assembly-drafting.md B.4、31 号用例），"成套剖视 + 标注"未解；局部放大 `detail_rect`（半径 ≈ 半对角 × 0.83）。

## 装配图

- **包盒**：`standard_views`/`model_bbox` 只接受单 body；装配用 `gb.assembly_bbox([...])` 并集，须计入齿顶、端盖、轴伸（漏算裁顶部）。
- **尺寸值 PDF 文本层复核**：`extreme_edge` + `dim_between` 在装配实例边/剖视上即使两边不同、`AssocDwgPos` 显式给出也可能读错；pymupdf 逐值对账，对不上改写到技术要求。
- **明细栏**：位于标题栏上方时传 `base_y=明细栏顶边`，避免压字。
