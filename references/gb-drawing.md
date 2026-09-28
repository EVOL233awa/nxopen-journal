# 国标工程图标准件 gb_drawing.py

`scripts/gb_drawing.py` 是随技能分发的 NX 12 Python 3.6 模块：任何 journal
把它所在目录加进 `sys.path` 后 `import gb_drawing`，按固定顺序调用即可得到
可直接交付的国标图纸——不需要逐张手调常数。回归用例
`scripts/tests/33_gb_sheet.py` 就是它的验收（板 100×60×10 双孔，一张图从
建模到 PDF 全走模块），改模块后跑 33 号即可回归。

## 最小调用骨架

```python
import os
import sys

import NXOpen
import NXOpen.UF

# __file__ 在 NX journal 里可能未定义，先兜住再入 sys.path
try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    here = os.path.abspath(os.getcwd())
sys.path.insert(0, os.path.dirname(here))   # gb_drawing.py 所在的 scripts/

import gb_drawing as gb

session = NXOpen.Session.GetSession()
part = ...                                   # 建模：体必须先于出图存在
gb.blank_datums(part)                        # 基准体不消隐会投影成箭头杂线
gb.apply_gb_preferences(part)                # 字高 3.5/2.5 + 实心箭头
sheet = gb.new_sheet(part, "SHT1", "A4")     # A4 第一角（GB）
frame = gb.frame(sheet, "A4")                # 25/5 图框，双线宽
views = gb.standard_views(part, sheet, body=body, scale=1.0)
tb = gb.title_block(sheet, frame, name=u"试验板", dwg_no="NXOJ-33",
                    scale_txt=gb.scale_text(1.0))
gb.tech_note(sheet, tb)                      # 默认 GB/T 1804-m + 1184-K
bbox = gb.model_bbox(body)
ct = gb.content_bbox(views["TOP"], *bbox)
gb.dim_between(part, views["TOP"], (e1, "END_POINT", p1),
               (e2, "END_POINT", p2), lane_y=ct[1] - gb.LANE_FIRST)
gb.dim_diameter(part, views["TOP"], hole_edge, hole_center, (x, y))
gb.centermark(part, views["TOP"], hole_edge, hole_center)
gb.export_pdf(part, sheet, "drawing.pdf")
```

调用顺序固定为：建模 → `blank_datums` → `new_sheet` → `frame` →
`standard_views` → `title_block`/`tech_note` → 尺寸/中心线 → `export_pdf`。
尺寸道位一律从 `content_bbox` 推导（`LANE_FIRST=10`、`LANE_STEP=7`），
不要从 `view_bbox` 推导（它被标签余量撑大，实测 TOP 视图边框 141mm 而
内容 60mm）。

## 国标条款与本技能实现口径

| 条款 | 内容 | 本技能口径 |
| --- | --- | --- |
| GB/T 14689.1 | 幅面与边距 | A4/A3；装订边 a=25，非装订边 c=5（A0/A1 应为 10，未覆盖）；图框单格表格 + 0.7 双线宽边框 |
| GB/T 14689.1 | 投影角 | 第一角（`ProjectionAngleType.FirstAngle`） |
| GB/T 10609.1 | 标题栏字段 | 设计/校核/日期/图号/比例/材料/图名齐全；**版式取自真实工程图纸实测**（105×21，3 行 7mm，六列），标准全文的 180×56 大格式未实现 |
| GB/T 4458.4 | 尺寸注法 | 道位 LANE_FIRST=10、LANE_STEP=7（通行做法）；直径/线性尺寸走 UF 关联对象，随几何更新 |
| GB/T 14691 | 字体 | 字高 3.5（尺寸/技术要求）与 2.5（标题栏字段）两档；中文由 NX 默认字体渲染 |
| GB/T 1804-m / GB/T 1184-K | 未注公差 | `tech_note` 默认条款，可传 `lines=` 覆盖 |

诚实声明：上表是"技能可证实的实现口径"，不是标准原文翻译；标题栏版式与
字段实测自一张真实工程图纸，未逐条比对 GB/T 10609.1 原文。
签名（设计/校核）没有依据就不填（传 `None` 留空），日期默认当天（生成日期
是真实事实）。明细栏（GB/T 10609.2）未实现，需要时参照 19 号用例的表格
配方自建。

## 模块内建的事实（33 号用例实测，勿绕过）

- `SetDrawingReferencePoint` 移动的是 plot 出来的内容（逐份 PDF 数值
  验证）；`pin_view` 用"Set → 测内容中心 → 补偿"闭环收敛（<0.05mm）。
- **同一图纸上后续调用抛 `Cannot move view off of the drawing` 会回滚之前
  已成功的视图移动**——布局必须保证任何视图不出图幅（33 号第一、二跑的
  内容残留原位就是这个坑）。
- `AskViewBorders` 含视图标签余量，只配"这视图占多大地方"的粗估；布局与
  尺寸道位用 `model_bbox` + `content_bbox`（模型包盒角点逐视图映射）。
- `DraftingDrawingSheet` 没有 `Width`/`Height` 属性；幅面尺寸从
  `new_sheet` 的 `size` 参数带常量表来。
- 关联类型枚举名是 `END_POINT`（`UF_DRF_end_point`），不是 `ENDPOINT`；
  圆心是 `ARC_CENTER`。
- Note 默认按块中心锚定（各行居中、左右参差）：先设
  `LetteringPreferences.AlignmentPosition = TopLeft`，**再**设
  `note.AnnotationOrigin`，原点才是块的左上角、可确定钉位。
- NX 表格 2.5 字高时 ASCII 字宽约 2.1mm：21mm 列放不下 10 字符日期
  （溢出画 `#`），标题栏数值列宽 25、标签列宽 10（总宽 105 不变）。
- 表格行高只在逐格 `NmFitMethods=0` 后生效；表格原点=左上角、向下生长；
  行高/列宽的 PascalCase 成员与枚举对象见 drafting-annotation.md §6。
- 基准体（模板自带 CSYS）不消隐会投影进每个视图成箭头杂线；
  `blank_datums` 必须在建视图之前调用。
- PDF 里 NX 的连字符会被抽取成软连字符（U+00AD），中文抽取不出——数值
  审计按位置与线段核，文字审计对 `\xad` 归一化。

## 模块内建的事实补充（2026-09-25 冷测 T10 后修正）

- `model_bbox` 主路线 = `ufs.ModlGeneral.AskBoundingBox`（NX12 UF 把 UF_MODL 包盒函数封装在 **ModlGeneral** 组，不是 `ufs.Modeling`——旧写法属性名错误，静默落入直边回退，纯回转体无直边即抛 "body has no edges"；已修正，34 号用例以纯回转齿轮覆盖）。

## API 速查

| 函数 | 作用 |
| --- | --- |
| `new_sheet(part, name, size)` | A4/A3 第一角图幅并置为当前 |
| `blank_datums(part)` | 消隐全部基准面/轴 |
| `apply_gb_preferences(part)` | 字高 3.5/2.5、实心箭头 |
| `frame(sheet, size)` | GB 25/5 图框，返回几何 dict |
| `standard_views(part, sheet, body, scale)` | 第一角三视图按内容钉位 |
| `projected_views(part, sheet, parent, dx, dy)` | 从父视图再投影（已 Update） |
| `pin_view(sheet, view, cx, cy, scale, bbox)` | 内容中心闭环钉位 |
| `model_bbox(body)` / `content_bbox(view, ...)` | 布局与道位的真值来源 |
| `title_block(sheet, frame_geo, ...)` | 标题栏（逐格回读，None 留空） |
| `tech_note(sheet, tb_geo, lines)` | 技术要求块（默认 GB/T 1804-m） |
| `part_note(sheet, lines, origin)` | 左上角锚定的多行注释 |
| `hole_circles(body, radius)` | 孔口整圆边（逐 (x,y) 取最高 z） |
| `linear_edges(body)` / `extreme_edge(...)` | 直边与包络边挑选 |
| `dim_between(...)` / `dim_diameter(...)` | UF 关联尺寸（道位自定） |
| `centermark` / `centerline_by_points` | 中心标记 / 两点中心线 |
| `export_pdf(part, sheet, path)` | 单图幅 PDF（BlackOnWhite 1:1） |
| `scale_text(s)` | 1.0→"1:1"、2.5→"2.5:1"、0.5→"1:2" |

## 扩展方向

A0/A1 幅面（c=10）、GB/T 10609.1 全格式标题栏、明细栏、隐藏线开关、
剖视图（UF 路线已通的部分见 assembly-drafting.md B.4 与 31 号用例，
"成套剖视 + 标注"仍是未解项）。局部放大见 `detail_rect`（边界圆半径
≈ 选框半对角 × 0.83，函数已自动放余量）。
