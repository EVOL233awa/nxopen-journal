# 工程图标注域（NX 12 批处理）

> 前置：SKILL.md + assembly-drafting.md §B.1-B.3（图纸/三视图/PDF 导出）。
> 本文件：标注配方（尺寸/文字/表格）。

## 1. 决定性结论（先读这个）

1. **全局偏好是字高/箭头的唯一正道**：`wp.Annotations.Preferences` 设好后 **UF DRF 尺寸自动继承**（字高 3.5 → `GetDimensionText().Size == 3.50`），不逐尺寸改。
2. **线性尺寸 = `CreateHorizontalDim`/`CreateVerticalDim` + `AssocDwgPos` 显式图纸点**。`CreateParallelDim` 线性边端点歧义、测任意两点距，禁用（仅圆心-圆心）；缺 dwg 点界线会画到共享投影的错误视图（残影）。
3. **表格 = `ufs.Tabnot.*`**；`Create` 默认 **5×5**，先删。
4. **直径写 `<O>`**，不传字面 `Ø`(U+00D8)：UF 报 `Locale data detected when UTF8 data was expected`（中文没事）。

## 2. 标注前必设的全局偏好

```python
def set_global_prefs(wp):
    ap = wp.Annotations.Preferences
    lp = ap.GetLetteringPreferences()          # Get→改→Set（TransientObject 模式）
    for getter, setter, size in [
            (lp.GetDimensionText, lp.SetDimensionText, 3.5),   # 尺寸数字
            (lp.GetGeneralText,   lp.SetGeneralText,   3.5),   # 注释/表文
            (lp.GetAppendedText,  lp.SetAppendedText,  3.5),   # 附加文本
            (lp.GetToleranceText, lp.SetToleranceText, 2.5)]:  # 公差
        lt = getter(); lt.Size = float(size); setter(lt)
    ap.SetLetteringPreferences(lp)

    lap = ap.GetLineAndArrowPreferences()
    lap.ArrowheadLength = 4.0                  # GB 箭头：长 ≈ 6×宽
    lap.ArrowheadIncludedAngle = 10.0          # 10° → 宽 0.7，比例 ~5.7:1
    lap.FirstPosToExtLineDist = 0.0            # 尺寸界线紧贴引出点
    lap.LinePastArrowDistance = 0.0
    lap.FirstArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
    lap.SecondArrowType = NXOpen.Annotations.ArrowheadType.FilledArrow
    ap.SetLineAndArrowPreferences(lap)
```

- 字高 3.5 = GB/T 14691 A3 常用值；汉字 ≥3.5；表题/图名可用 5。
- 继承审计：建完取 `d.GetLetteringPreferences().GetDimensionText().Size` = 设定值。
- ⚠ **`SetLetteringPreferences` 不能省**：Get 返回副本，不 Set 等于没改。
- ⚠ **期望非默认**：mm A4 默认尺寸 **3.5**、注释 **6.5**；改设 5.0 再断言（`scripts/tests/19`）。
- 兜底：遍历 `wp.Dimensions` 逐个 Get→改→Set。

## 3. 尺寸布局规范（GB/T 4458.4-2003 + 专业实践）

道位算法（图纸坐标）：① 第一道距轮廓 10mm、道距 7mm（GB 间距 5~10 且 ≥7）；② 大在外、小在内（否则界线交叉；孔距 80 内道、总长 100 外道）；③ 高度链同道相接（板厚 12 + 凸台 8 内道，总体 20 外道）；④ 每尺寸只标一次；⑤ 直径标非圆投影或圆上直接引出；⑥ 不封闭链（一环不标或括号）；⑦ 集中标在特征最清晰视图，孔位从 ARC_CENTER 引出；⑧ 界线超出 ~2mm、箭头长≈6×宽、中心线超出 2~5mm（NX 自动，pos-gap/past-arrow 设 0）。

视图映射（org 与 dwg 点都要用；sheet = ref + proj(p) − proj(中心)）：

| 视图 | 投影 | 图纸坐标（ref 为视图中心） |
| --- | --- | --- |
| Front | (x, z) | (fx + x−cx, fy + z−cz) |
| Top   | (x, y) | (tx + x−cx, ty + y−cy) |
| Right | (y, z) | (rx + y−cy, ry + z−cz) |

org：`Create*Dim` = 尺寸线名义位置（吸附 2~3mm）；`Tabnot.Create` origin = **左上角**、向下生长（吸附 ~2mm）。

**摆位**：

- `SetDrawingReferencePoint` 落点有**视图相关常数偏差**（Top −25 / Front −12.5 / Right +12.5mm），直接设 ref 会失准。
- 后续抛 `Cannot move view off of the drawing` 会**回滚已成功的移动**；保证视图不出图幅。
- `AskViewBorders` 含标签余量，只配粗估；真值用内容包盒 `model_bbox` + `ufs.View.MapModelToDrawing` 取 min/max（`content_bbox`/`pin_view`），收敛判据内容中心偏差 <0.05mm。
- 剖视沿父视图对齐轴（同 x/y 中心）时方向正确、包盒精确；定位只用 placement origin（`SectionLineOnlyPlacementOrigin` = `ViewPlacement.Placement.Value`）。斜放会旋转且包盒失真；包盒 pin 仅普通视图。
- ⚠ **placement origin ≠ 内容中心**；沿对齐轴用包盒量偏移修正。
- 剖视 placement 须在图幅内；建完断言可见对象数与 hatch ≥ 1（`view_kinds`）——出图幅时 Commit 成功、scale 1.0、零内容。
- 改 `view_layout` 后标注坐标全部重算；道位从内容包盒推导（`LANE_FIRST`/`LANE_STEP`）。

## 4. 尺寸配方（UF DRF，关联点显式化）

```python
ATC = NXOpen.UF.Drf.AssocType

def uf_obj(ufs, edge, view, assoc, dwg_xy):
    o = ufs.Drf.Object(); ufs.Drf.InitObjectStructure(o)
    o.ObjectAssocType = getattr(ATC, assoc)   # 线性边 END_POINT / 圆边 ARC_CENTER
    o.ObjectTag = edge.Tag
    o.ObjectViewTag = view.Tag
    o.AssocDwgPos = [float(dwg_xy[0]), float(dwg_xy[1])]   # ⚠ 显式图纸点
    return o

# 竖直尺寸 12：底边/顶边 + 各自引出端模型点（映射成图纸点）
o1 = uf_obj(ufs, bottom_edge, vfront, "END_POINT", dwg_of((0, 0, 0)))
o2 = uf_obj(ufs, top_edge,    vfront, "END_POINT", dwg_of((0, 0, 12)))
ufs.Drf.CreateVerticalDim(o1, o2, ufs.Drf.Text(), [155.0, 191.0, 0.0])
# 水平/直径/半径：CreateHorizontalDim(o1,o2,txt,org) /
# CreateDiameterDim(o1,txt,org) / CreateRadiusDim(o1,txt,org)
# 半径：o1 建在圆/圆弧边（Edge.SolidEdgeType == EdgeType.Circular，
#   AssocType=ARC_CENTER）；ComputedSize 取真实半径（R10 → 10.0000）
```

- **`AssocDwgPos` 必须显式给**；留 `[0,0]` 时长直边界线画到错误视图。显式点渲染 ~1.5mm 关联符号，关不掉，接受。
- **线性尺寸两关联对象挂两条不同的边**；同边两个 END_POINT → `ComputedSize=0.0`。
- ⚠ **装配实例边 + 剖视图，异边也不保证真值**（200/140 → 200.2/136.3）：PDF 文本层逐值对账，不符则删尺寸、外形写进技术要求。
- **竖直尺寸显式 `TextOrientation.Aligned`**：`prefs = dim.GetDimensionPreferences(); prefs.TextOrientation = NXOpen.Annotations.TextOrientation.Aligned; dim.SetDimensionPreferences(prefs)`；UF tag → .NET 用 `for d in part.Dimensions: if int(d.Tag) == int(tag)`。角度尺寸例外（数字须水平）。
- `ufs.Drf.Text()` 无参 = 自动关联值；**公差后缀**走 part.Dimensions + Get/改/Set AppendedText（§5）。

| 方法 | 结论 |
|---|---|
| `CreateDiameterDim` | 可用，返回 tag；出现 `DiameterDimension` |
| `CreateHoleDim` | 可用（3 参）；出现 `HoleDimension` |
| `CreateRadiusDim` | 可用：圆弧/整圆边，`ComputedSize` 取真实半径（R10 → 10.0000）；直线边报 `NXException: The input object is invalid.`；按 `Edge.SolidEdgeType == EdgeType.Circular` 筛，不按面半径 |
| `CreateVertical/HorizontalChainDimension` | **3 参**（`List[NXOpen.UF.Drf.Object]`, `int`, `NXOpen.UF.DrfText_Struct`） |
| `CreateHorizontal/VerticalBaselineDimension` | 同上 3 参 |
| `CreateOrdinateDim` | **12 参**；`CreateOrdinateOrigin` **7 参** |
| `CreateCylindricalDim` | **4 参** |

## 4b. 引线与数量前缀

- 直径引线就近引出、不穿越轮廓或视图边界。
- `dim_diameter` 不支持附加文本（"4×Ø7"）：EQS/数量形态走 §5 的 label 注记。

## 5. 注释文字（技术要求/标题栏/图名）

```python
wp.Annotations.CreateNote([u"技术要求："],
    NXOpen.Point3d(x, y, 0.0), NXOpen.AxisOrientation.Horizontal, None, None)
```

- ⚠ **origin 是文本块中心**：多行/左对齐按估宽右移半宽（CJK≈h、ASCII≈0.55h：`sum(h if ord(ch)>0x2E80 else h*0.55 for ch in s)`）。
- ⚠ note 默认 6.5mm：`lp = note.GetLetteringPreferences(); g = lp.GetGeneralText(); g.Size = 3.5; lp.SetGeneralText(g); note.SetLetteringPreferences(lp)`。
- **带引线标签（.NET）**：
  ```python
  bundle = wp.Annotations.NewLeaderBundle()
  try:
      bundle.NumberOfLeaders = 1   # 必须前置，缺这步 SetLeaderData 必拒
  except Exception:
      pass
  bundle.SetLeaderData(0, NXOpen.Annotations.LeaderAttachment.Screen,
                       edge, view, NXOpen.Point3d(lx, ly, 0.0), 0.0, [])
  label = wp.Annotations.CreateLabel([u"文本"], NXOpen.Point3d(x, y, 0.0),
                                     None, None, None, bundle)
  # 真实边用 OnObject（无 Object 成员），自由点用 Screen；字高后置：
  # GetLetteringPreferences→GetGeneralText→Size=3.5→SetGeneralText→Set
  ```
  assoc 须真实边（part → `Cannot extract the curve from edge`；None → `Expecting NXObject`）；view 须 drafting view（sheet → `Expecting NXOpen.View`）。
- ⚠ **`NumberOfLeaders = 1` 必须前置**，否则 "Second parameter is invalid"。
- ⚠ **侧立圆（圆平面⊥纸面）作 assoc → 锚点飞出图框**；真圆/直线边正常，素线挂不上。**侧立圆直径**：换平行视图挂真圆（隐藏边也可）。
- **公差带代号（H8/f7）**：按 tag 找 .NET 尺寸对象，Get→改→Set：
  ```python
  for d in part.Dimensions:
      if int(d.Tag) == int(tag):            # tag 来自 Create*Dim 后的对象
          at = d.GetAppendedText()          # 不能凭空构造 AppendedText()
          at.SetAfterText([u"H8"])          # 后缀在尺寸数字之后
          d.SetAppendedText(at)             # 否则 Invalid self parameter
          break
  ```
  ⚠ tag 用创建返回值匹配（§9）。
- **倒角：CreateChamferDim 不可用**（END_POINT → "The first input object is invalid"）→ label "C2" 挂 45° 斜边（0.3<dx<4、|dx−dy|<0.05），文本在斜边中点 ±8mm，字高 3.5。
- 控制序列：`<O>` Ø、`<#C>` 沉孔、`<$s>` °、`<&10>` 位置度。

## 6. 表格（孔参数表/明细栏/标题栏）

```python
dp = ufs.Tabnot.AskDefaultCellPrefs()
dp.TextHeight = 3.5                          # CellPrefs 字高字段 = TextHeight
ufs.Tabnot.SetDefaultCellPrefs(dp)
res = ufs.Tabnot.Create(ufs.Tabnot.AskDefaultSectionPrefs(), [x, y, 0.0])
tn = res[0] if isinstance(res, tuple) else res           # 返回 tag（int）
# ⚠ 默认 5×5，全删：
for _ in range(int(ufs.Tabnot.AskNmColumns(tn)[0] if isinstance(ufs.Tabnot.AskNmColumns(tn), tuple) else ufs.Tabnot.AskNmColumns(tn))):
    c0 = ufs.Tabnot.AskNthColumn(tn, 0); ufs.Tabnot.RemoveColumn(c0[0] if isinstance(c0, tuple) else c0)
# 行同理 RemoveRow
for w in (15.0, 25.0, 20.0, 30.0):           # 列宽 mm
    c = ufs.Tabnot.CreateColumn(w); ufs.Tabnot.AddColumn(tn, tag_of(c), -1)
for ri, vals in enumerate(rows):
    r = ufs.Tabnot.CreateRow(7.0)            # 行高 7mm（GB/T 10609.2）
    ufs.Tabnot.AddRow(tn, tag_of(r), -1)
    for ci in range(ncols):
        c0 = ufs.Tabnot.AskNthColumn(tn, ci)
        cell = ufs.Tabnot.AskCellAtRowCol(tag_of(r), tag_of(c0))  # (row, col)
        ufs.Tabnot.SetCellText(tag_of(cell), vals[ci])            # 直径写 "<O>8"
ufs.Tabnot.Update(tn)
```

- **origin = 左上角**，向下生长，吸附 ~2mm。
- `ufs.Drf.SetOrigin` **未打通**（第 1 参不收 tabular note tag）→ 定位走 UFTabnot。
- 成员：`AddColumn`/`AddRow`/`SetColumnWidth`/`SetRowHeight` 可用；`AddHeaderRow` **3 参**；`EnableAutomaticUpdate` **0 参取用**（SKILL.md §3 坑位 9）；`SetCellPrefs` 需真 cell tag；`MergeCells` **2 参**；无 `Sort`。
- **PascalCase + 枚举对象**：`SectionPrefs.UseDoubleWidthBorder=True` + `BorderWidth=0.7`；`AttachPoint=NXOpen.UF.Tabnot.AttachPoint.ATTACH_POINT_TOP_LEFT`；`CellPrefs.HorizJust=Just.JUST_CENTER`、`VertJust=Just.JUST_MIDDLE`。
- **行高先关自适应**（uf_tabnot.h）：每 cell `AskCellPrefs` → `cp.NmFitMethods = 0` → `SetCellPrefs`，再 `SetRowHeight`；否则空行 ~5mm、超宽文字 `############`。
- **图框用单格表**：267×200（A4 25/5 边距）+ 双线宽边框，标题栏/明细栏贴右下角；`AskNthRow/Col` 回读校验。
- **明细栏**（GB/T 10609.2）：行高 7mm、标题栏上方、**自下而上**（row0 在底部）；列序 序号/代号/名称/数量/材料/备注。
- **BOM 垂直居中**：`cy = ROW0 + RH*ri + RH/2.0`；错写 `RH*(ri+1)+RH/2.0` 全表上浮一行。
- **定稿版式**（优先于 GB 通用值）：① 技术要求在图样右下、紧贴标题栏上方（总成图放明细表上方），全套统一；② 明细表 150mm 宽、6.5mm 行高、9 行；③ 标题栏 180×56 与明细表等宽（简化版画线+note，assembly-drafting.md §B.2）；④ 装配图三视图：主视图大面左下、长条视图上方偏左、右视图上方偏右，铺满图框；球标随主视图。
- **件号**：`CreateIdSymbol` 手动 + 手工明细表，不开自动件号。
- `PartsListBuilder` NX12 **无创建入口** → UFTabnot 明细栏 + `CreateIdSymbol` 球标。

## 7. 中心线与中心标记

- 圆心十字：`Centerlines.CreateCenterMarkBuilder(CenterMark.Null)`，`Locations.Add(圆边, view, Point3d(圆心))`。⚠ **一个 builder 一个 location**（n=3/4 报 1175305、n=8 报 1175307），批量循环建 builder（`scripts/tests/07_center_marks.py`）。
- 通孔圆柱面两个等半径圆（近端可见、远端隐藏），`ARC_CENTER` 挂哪个都成功；按 `p1 == p2` 识别整圆、按半径筛孔壁、取 z 大者。
- 轴线：`CreateCenterline2dBuilder(Centerline2d.Null)`，`Type = Types.ByPoints`，`Point1/Point2.SetValue(关联边, view, 模型点)`；两点取对称要素两心。
- 回转体三视图都画对称轴（Front/Right 竖直 + Top 十字）。
- ⚠ .NET 标注路线**不需要 `sheet.Open()`**（assembly-drafting.md B.2）。

## 8. 反模式清单（AI 标注的"一眼假"来源，逐条对照）

1. 无道位：尺寸挤轮廓或甩到 30mm 外。
2. 平行尺寸大内小外（界线交叉）。
3. 同尺寸跨视图重复。
4. 标在虚线上。
5. 字号混排（6.5/3.5）。
6. 箭头开口或大小不一。
7. 回转体无中心线/标记。
8. 字面 `Ø` 报错后空白。
9. 表格出页/压标题栏。
10. 封闭尺寸链。

## 9. 坑位对照（遇到 → 怎么做）

| 遇到 | 怎么做 |
| --- | --- |
| `CenterMarkBuilder` ≥3 location → 1175305 / 1175307 | 一个标记一个 builder（§7） |
| `CreateParallelDim` 线性边测出任意两点距 | 端点歧义；线性边用 hdim/vdim |
| `AssocDwgPos=[0,0]` → 界线画到别的视图 | 给显式点；~1.5mm 关联符号关不掉，接受 |
| 字面 `Ø` → `Locale data detected when UTF8 data was expected` | 用 `<O>` |
| `Tabnot.Create` 后错位/多空白列 | 先删默认 5×5 |
| `part.Dimensions.Create*Dimension` / .NET builder | 无头批处理内存访问违例；走 UF DRF |
| FCF / 粗糙度 / 孔表 .NET builder | 空对象类无 `.Null`；`CreateDraftingFeatureControlFrameBuilder`/`DraftingSurfaceFinishSymbols.CreateDraftingSurfaceFinishBuilder`/`HoleTables.CreateHoleTableBuilder` 存在，孔表 builder 可构造；配方未打通 |
| 标直径/孔径/半径 | 三个 Create* 可用（`ComputedSize=10.0000`；直线边报 `The input object is invalid.`）；按 `EdgeType.Circular` 筛 |
| `CreateChamferDim` + END_POINT 报 invalid | `AssocType` 无 CURVE；走 label（§5） |
| `AppendedText()` 凭空构造 → Invalid self parameter | `GetAppendedText()`→改→`SetAppendedText()` |
| `import NXOpen.Utilities` → ImportError | sitecustomize 白名单；改 tag 匹配 `part.Dimensions` |
| `LeaderAttachment.Object` | 无；用 `OnObject`（§5） |
| 隐藏线开关反推相反 | `HIDDEN_LINE_REMOVAL_ON`=移除不画、`OFF`=画出；`AskViewDisplay`→改 `HiddenLine`/`HiddenLineFont`→`SetViewDisplay`→`UpdateOneView(sheet.Tag, view.Tag)`（两参） |
| 指望 PDF 有虚线 | 导出层不渲染（`HiddenLineFont` 1~7 全实线） |
| 逐尺寸设 EdlineAndArrow | 冗余，全局已继承 |
| 同边两个 Drf 对象 → "0" | 每尺寸挂两条不同平行边（§4） |
| 剖视方向不对 / 包盒乱值 | 斜放即旋转且映射失真；沿对齐轴放置，用 placement origin 定位（§3） |
| 剖视 placement origin 放置偏左下 | origin ≠ 内容中心；用包盒量偏移修正（§3） |
| 剖视 Commit 成功但空 | placement 超图幅不报错；断言可见对象数与 hatch ≥1（§3） |

## 10. 验证方法（标注类交付的反向验证底线）

1. **PDF 文本层逐值核对**：`pymupdf get_text('words')` 提数字+坐标与设计值/道位比对。容差 ±0.1：NX 值来自真实几何，dump 显示值有舍入（553.45 vs 553.4499 → 渲染 553.4，expect 553.5 误报）。
2. **PDF 矢量线测量**（`get_drawings()`；mm = pt/72×25.4、y 翻转 297−y_mm）：轮廓/尺寸线/道距判据。
3. **150dpi 全页目检** + 300~400dpi 局部核箭头/符号/字高。
4. 布局缺陷肉眼可辨：界线交叉、压线、道距不均、表格压框。
5. **幂等重跑**：已标注 PRT 重跑会**双重标注**；runner 先重置底稿副本（上轮 save 写回是陷阱）。全量 prepare 时单张重跑须绕过它、单独 `run_one`。
6. 产物核对**内容而非大小**（v1 没有的尺寸值 + 标题栏版本号）；cp glob 未匹配静默跳过。
7. **中文文本层零判别力**：无 ToUnicode 映射，提不出中文；技术要求/标题栏/明细表不能靠文本层（反向断言同样无效），只能矢量词 bbox + `get_pixmap` clip 3~4x 目检。数字/字母（H8、C2、45、v1.1）可用，注意分词粘连（用 substring）；⚠ Ø 同样无映射（`<O>8` 只剩 "8"）。
8. **值级校验**：`scripts/tests/19_drafting_annotation.py` NX 侧断言尺寸对象/偏好继承/单元格回读/PDF 落盘；host 端 `scripts/tests/verify_anno_pdf.py` 用文本层核对（token `70`/`40` + `R2.`/`4x`）。NX Python 3.6 无 PDF 库，判据放 host。
