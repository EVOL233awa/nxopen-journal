# 工程图标注域（NX 12 批处理实测 2026-09-19）

> 前置：SKILL.md（铁律/骨架）+ assembly-drafting.md §B.1-B.3（图纸/三视图/PDF 导出）。
> 本文件解决"标注质量"：怎么标出人类建模师水准的尺寸/文字/表格。
> 全部结论出自 4 轮批处理实测（探针：`work/nx-anno-train/01_anno_probe.py`，
> 建模→三视图→偏好→道位尺寸→中心线→注释→表格→PDF 全链路 23/23 PASS，
> 每轮 PDF 渲染目检迭代）。可读性基准图：`work/nx-anno-train/page4.png`。

## 1. 决定性结论（先读这个）

1. **全局偏好是字高/箭头的唯一正道**：`wp.Annotations.Preferences`
   （NXOpen.Preferences.AnnotationPreferences）设好后，**UF DRF 创建的尺寸自动继承**
   （实测：全局字高 3.5 → 新建尺寸读回 `GetDimensionText().Size == 3.50`）。
   不要逐尺寸改样式。
2. **线性尺寸 = `CreateHorizontalDim`/`CreateVerticalDim` + `AssocDwgPos` 显式图纸点**。
   `CreateParallelDim` 在线性边上会因 END_POINT 端点歧义测出任意两点距（100.7/31 之类），禁用；
   它只用于关联点唯一的场景（圆心-圆心）。hdim/vdim 不给 dwg 点则界线会画到共享投影的错误视图上（残影）。
3. **表格 = UF TABNOT 全家**（`ufs.Tabnot.*`），`Create` 默认给 **5×5**，必须先删默认行列再加自己的。
4. **直径符号永远写 `<O>` 控制序列**，不要传字面 `Ø`(U+00D8)——UF 字符串接口报
   `Locale data detected when UTF8 data was expected`（中文反而没事）。

## 2. 标注前必设的全局偏好（配方，2026-09-19 实测）

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

- 字高 3.5 = GB/T 14691 字高系列（1.8/2.5/3.5/5/7/10/14/20）中 A3 图常用值；
  汉字不得小于 3.5；表题/标题栏图名可用 5。
- 继承审计：建完尺寸后取任一尺寸 `d.GetLetteringPreferences().GetDimensionText().Size`
  打进日志，必须等于设定值。
- ⚠ **`SetLetteringPreferences` 不能省**（2026-09-20 实测）：`GetLetteringPreferences()`
  拿到的是副本，改完字段不 `Set` 回去等于没改（把 Set 行去掉后读回仍是模板默认值）。
- ⚠ **审计期望值必须取非默认值**：mm A4 模板的尺寸字高默认 **3.5**、注释默认 **6.5**
  （实测）。若把期望设成 3.5 这种恰好等于默认值的数，则"偏好设了"与"没设"读回相同，
  审计退化成恒真断言。正确写法是把尺寸字高设成 5.0 再断言读回 5.0
  （`scripts/tests/19` 即此口径，已做反向验证）。
- 兜底（全局路线万一失效）：遍历 `wp.Dimensions` 逐个
  `d.GetLetteringPreferences()`→改→`d.SetLetteringPreferences()`（note 同款配方，实测可用）。

## 3. 尺寸布局规范（GB/T 4458.4-2003 + 专业实践）

道位算法（这是"整洁"的核心，全部为图纸坐标）：

1. **第一道距视图轮廓 10mm，道距 7mm**（GB：平行尺寸线间距 5~10 且 ≥7）。
2. **大尺寸在外道、小尺寸在内道**——否则小尺寸的界线必然穿过大尺寸的线。
   例：俯视图下方"孔距 80 内道、总长 100 外道"。
3. **高度链同道相接**：板厚 12 与凸台高 8 共用内道上下相接（链式），总体尺寸 20 独占外道。
4. **每个尺寸只标一次**；某个视图标了总长，其它视图不重复。
5. **直径标在圆的非圆投影上**（回转体在主视/左视为矩形时 Ø 标其上）或俯视图圆上直接引出。
6. **不封闭尺寸链**：链式尺寸 + 总体尺寸并存时，其中一个链环不标（或括号作参考）。
7. 相关尺寸集中标在形状特征最清晰的视图；孔位尺寸从孔心（ARC_CENTER）引出。
8. 界线超出尺寸线约 2mm、箭头长≈6×宽、中心线超出轮廓 2~5mm（NX 自动处理超出量，
   全局偏好里 pos-gap/past-arrow 设 0 即可）。

视图映射（org 与 dwg 点都要用；sheet = ref + proj(p) − proj(中心)）：

| 视图 | 投影 | 图纸坐标（ref 为视图中心） |
| --- | --- | --- |
| Front | (x, z) | (fx + x−cx, fy + z−cz) |
| Top   | (x, y) | (tx + x−cx, ty + y−cy) |
| Right | (y, z) | (rx + y−cy, ry + z−cz) |

org 语义（实测）：`Create*Dim` 的 org 是尺寸线名义位置，渲染会吸附偏移 2~3mm；
表格 `Tabnot.Create` 的 origin 是**左上角**（向下生长），同样有 ~2mm 吸附。定位按此心算补偿。

**视图重新摆位（2026-09-19 七图重排实测；2026-09-24 用例 33 两处证伪并修正）**：

- `SetDrawingReferencePoint` 的实际落点与传入值有**视图相关常数偏差**
  （实测 Top −25 / Front −12.5 / Right +12.5mm，与视图"显示内容"构成有关），
  直接设 ref 会导致几何中心偏离设计值、道位相对轮廓失准。
  2026-09-24 补充：Set 移动的确实是 **plot 出来的内容**（逐份 PDF 数值验证），
  但**同一图纸上后续调用抛 `Cannot move view off of the drawing` 会回滚之前
  已成功的移动**——布局必须保证任何视图不出图幅，否则"每针都成功"内容
  却停在原位（用例 33 第二跑事故）。
- **落位闭环的测量对象**：~~AskViewBorders~~ **已降级**——它含视图标签余量，
  可比内容大很多（2026-09-24 实测 TOP 视图边框高 141mm 而内容 60mm），
  只配"这视图占多大地方"的粗估。真值用**内容包盒**：`model_bbox` 取模型
  包盒角点，逐视图 `ufs.View.MapModelToDrawing` 映射后取 min/max
  （已实现为 `scripts/gb_drawing.py` 的 `content_bbox` + `pin_view`，
  验收=用例 33）；闭环收敛判据同样是内容中心与目标的偏差 <0.05mm。
- **剖视图沿父视图对齐轴定位**（同 x 或同 y 中心，2026-09-28 冷启动 + 探针实测）：此时内容
  方向正确、`MapModelToDrawing` 包盒精确（120×16 剖面实测分毫不差）；定位只用 builder 的
  placement origin（`SectionLineOnlyPlacementOrigin` 与 `ViewPlacement.Placement.Value`
  给同一点，冷启动配方）。剖视图的放置方位决定内容旋转——离对齐轴斜放会整体旋转且包盒
  映射失真（120×16 实测 76.64×119.87），内容包盒闭环 pin 只用于普通视图。
- **剖视图 placement 放在图幅内，建完即断言可见对象数与 hatch ≥ 1**（`view_kinds`，
  31 号配方；2026-09-28 探针实测）：placement 落在 A4 图幅外时 Commit 照常成功、scale
  仍读 1.0，视图零内容（可见对象 0、无剖面线、包盒映射乱值）——自检在建完当轮就能抓住。
- 改 `view_layout` 后**全部标注坐标必须按新布局重算**（cfg 生成器里布局参数驱动
  sh() 映射，勿手写绝对坐标）；漏传 view_layout 时视图停在旧位而尺寸按新坐标
  放置，全体错位（七图重排首轮事故）。尺寸道位从内容包盒推导
  （`LANE_FIRST`/`LANE_STEP`），勿从边框推导。

## 4. 尺寸配方（UF DRF，关联点显式化）

```python
ATC = NXOpen.UF.Drf.AssocType

def uf_obj(ufs, edge, view, assoc, dwg_xy):
    o = ufs.Drf.Object(); ufs.Drf.InitObjectStructure(o)
    o.ObjectAssocType = getattr(ATC, assoc)   # 线性边 END_POINT / 圆边 ARC_CENTER
    o.ObjectTag = edge.Tag
    o.ObjectViewTag = view.Tag
    o.AssocDwgPos = [float(dwg_xy[0]), float(dwg_xy[1])]   # ⚠ 显式图纸点（见下）
    return o

# 竖直尺寸 12：底边/顶边 + 各自引出端模型点（映射成图纸点）
o1 = uf_obj(ufs, bottom_edge, vfront, "END_POINT", dwg_of((0, 0, 0)))
o2 = uf_obj(ufs, top_edge,    vfront, "END_POINT", dwg_of((0, 0, 12)))
ufs.Drf.CreateVerticalDim(o1, o2, ufs.Drf.Text(), [155.0, 191.0, 0.0])
# 水平/直径/半径：CreateHorizontalDim(o1,o2,txt,org) /
# CreateDiameterDim(o1,txt,org) / CreateRadiusDim(o1,txt,org)
# 半径：o1 必须建在**圆/圆弧边**上（判据 Edge.SolidEdgeType == EdgeType.Circular，
#   对应 AssocType=ARC_CENTER）；返回 tag，ComputedSize 自动取真实半径（R10 实测 10.0000）
```

- **`AssocDwgPos` 必须显式给**（界线引出端的图纸坐标）。留 `[0,0]` 时长直边
  （跨视图共享投影的轮廓边）的界线会被画到错误视图上——实测出现"幽灵矩形+孤立箭头"残影。
- **副作用**：显式 dwg 点处会渲染一个 ~1.5mm 的"关联点符号"（圆+十字），无法关闭。
  8 尺寸试件出现 3 个，视觉影响小，**接受**（劣化远小于残影）。
- 圆边（ARC_CENTER）不受残影影响，dwg 点给孔心即可。
- **线性尺寸的两个关联对象挂两条不同的边**（2026-09-28 冷启动+探针实测：9 尺寸两两异边
  全部测出真值）：END_POINT 关联不选"哪一端"，`AssocDwgPos` 只定图纸引出位置。同一条边
  挂两个 END_POINT 时 `ComputedSize` 测 0.0（两条平行边对照 120.0），换异边即恢复真值。
- **竖直尺寸字向必须显式设 `TextOrientation.Aligned`**（2026-09-30 装配图冷启动实测）：
  UF `CreateVerticalDim` 的字向默认**不可控**——同一会话、同一调用路径，70 渲染成整体
  旋转、30/66 渲染成直立逐字堆叠且界线穿字（触发条件未定位，所以配方 = 线性尺寸一律
  显式设置）。Get→改→Set（与 AppendedText 同型）：
  `prefs = dim.GetDimensionPreferences(); prefs.TextOrientation = NXOpen.Annotations.TextOrientation.Aligned; dim.SetDimensionPreferences(prefs)`。
  Aligned = 文字与尺寸线平行（竖直尺寸即旋转 90°、字头朝左，GB 合规）；UF tag → .NET
  对象用 `for d in part.Dimensions: if int(d.Tag) == int(tag)` 遍历包装。**角度尺寸例外**：
  GB 要求角度数字水平，勿设 Aligned（150° 默认渲染正常）。
- `ufs.Drf.Text()` 无参 = 自动关联值文本；**公差代号后缀不走 UF 追加字段**，
  走 part.Dimensions + Get/改/Set AppendedText（实测配方见 §5"公差带代号"）。
- **UF DRF Create\* 全集**（`dir(ufs.Drf)`，NX12 实测存在）：
  Linear/H/V/Parallel/Perpendicular/Angular/Diameter/Radius/Foldedradius/Cylindrical/
  Arclength/ChamferDim/HoleDim/ConcirDim + Horizontal/VerticalChainDimension +
  Horizontal/VerticalBaselineDimension + OrdinateDim/OrdinateOrigin/OrdinateMargin +
  SymCline/LinearCline/BlockCline/3ptCline\*/CptCline\*/OffcylCline\*/Offctrpt\* +
  IdSymbol/Note/Label/GdtSymbol(WithMultipleLeaders)/WeldSymbol/Crosshatch/Xhatch/
  Areafill/NonAssocHatch/Image/ImageFromFile/CustomSymbolInstance/SymbolFont/SbfFile。
  其中 Radius/Chamfer/Cylindrical/Hole/Chain/Baseline/Ordinate/Gdt/Weld **2026-09-22 第一轮逐项探针实测结果**：

| 方法 | 实测结论（NX12 批处理，2026-09-22） |
|---|---|
| `CreateDiameterDim` | ✅ 可用，返回 tag；`part.Dimensions` 里出现 `DiameterDimension` |
| `CreateHoleDim` | ✅ 可用（3 参）；`part.Dimensions` 里出现 `HoleDimension` |
| `CreateRadiusDim` | ✅ 可用（2026-09-23 实测）：圆角圆弧边与孔口整圆边**都能**标注，`ComputedSize` 自动取真实半径（R10 → 10.0000，文本 "10"），`part.Dimensions` 出现 `RadiusDimension`；**直线边被拒**（`NXException: The input object is invalid.`）。取候选按 `edge.SolidEdgeType == NXOpen.Edge.EdgeType.Circular` 筛（枚举全集：Circular/ConstantParameter/Convergent/Elliptical/Foreign/Intersection/Linear/Rubber/SpCurve/Spline/TrimmedCurve/Undefined）；**不要按面半径筛**，同一圆柱面的 2 条直边会被一起选中 |
| `CreateVertical/HorizontalChainDimension` | 签名 = **3 参**（`List[NXOpen.UF.Drf.Object]`, `int`, `NXOpen.UF.DrfText_Struct`）；传 4 参会报 `Function takes 3 arguments, 4 passed`，把 `DrfObject_Struct` 当第 1 参、`DrfText_Struct` 当第 2 参都报 `Expecting List of .../Expecting int type` |
| `CreateHorizontal/VerticalBaselineDimension` | 同上 3 参签名 |
| `CreateOrdinateDim` | **12 参**；`CreateOrdinateOrigin` **7 参**（探针只试了 1/2/3 参，均报缺参） |
| `CreateCylindricalDim` | **4 参** |
| Gdt / Weld | 本轮未跑（`CreateGdtSymbol`/`CreateWeldSymbol` 存在但没进探针调用表） |

  ⚠ 教训（探针写法）：报 `Function takes N arguments` 与 `Expecting <类型>` 的**错误消息本身就是签名文档**——第一轮就该把"每个候选都打出完整消息"，只打异常类名等于白跑一轮（本文件 §4 的这条就是踩过之后的写法）。

## 4b. 引线与数量前缀（2026-09-25 冷测 T1/T5/T7 观察沉淀）

- 直径引线就近引出、不穿越轮廓或视图边界；落点离特征过远即观感失分。
- `dim_diameter` 不支持附加文本（"4×Ø7" 这类数量前缀写不进去）——EQS/数量形态走 §5 的 label 注记配方，只把直径文字写进技术要求不算标注到位。

## 5. 注释文字（技术要求/标题栏/图名）

```python
wp.Annotations.CreateNote([u"技术要求："],
    NXOpen.Point3d(x, y, 0.0), NXOpen.AxisOrientation.Horizontal, None, None)
```

- ⚠ **origin 是文本块中心**：多行/左对齐要按估宽右移半宽
  （CJK 字宽≈字高 h、ASCII≈0.55h：`sum(h if ord(ch)>0x2E80 else h*0.55 for ch in s)`）。
- ⚠ note 默认字高 ~6.5mm，压字高：
  `lp = note.GetLetteringPreferences(); g = lp.GetGeneralText(); g.Size = 3.5;
  lp.SetGeneralText(g); note.SetLetteringPreferences(lp)`。
- **带引线标签（.NET 路线，2026-09-19 沉淀自 67_annotate 实测）**：
  ```python
  bundle = wp.Annotations.NewLeaderBundle()
  try:
      bundle.NumberOfLeaders = 1   # 必须前置，缺这步 SetLeaderData 必拒（见下条 ⚠）
  except Exception:
      pass
  bundle.SetLeaderData(0, NXOpen.Annotations.LeaderAttachment.Screen,
                       edge, view, NXOpen.Point3d(lx, ly, 0.0), 0.0, [])
  label = wp.Annotations.CreateLabel([u"文本"], NXOpen.Point3d(x, y, 0.0),
                                     None, None, None, bundle)
  # 挂真实边（如倒角斜边）用 LeaderAttachment.OnObject（无 "Object" 成员），
  # 其余参数同上；自由点引线用 Screen。
  # 字高后置（UF CreateLabel 恒 6.5 不可控，故弃用走 .NET）：GetLetteringPreferences
  # → GetGeneralText → Size=3.5 → SetGeneralText → SetLetteringPreferences（同上 note 配方）
  ```
  assoc 必须真实边（传 part → `Cannot extract the curve from edge`；传 None → `Expecting NXObject`）；view 必须 drafting view（传 sheet → `Expecting NXOpen.View`）。
- ⚠ **`NumberOfLeaders = 1` 必须在 SetLeaderData 前置**：缺它四种参数形态全报 "Second parameter is invalid"，加它后同参即过（2026-09-25 冷测 T7-R2 照旧片段实测踩中，主线探针 A/B 复测定位）；用例 19 一直带这步，此前本片段漏抄。
- ⚠ **退化侧立圆（圆平面⊥纸面）作引线 assoc → 锚点飞出图框**（实测 (286.65,232)→(420,238.9)）；真圆（圆柱面⊥视线）与直线边正常，圆柱面轮廓素线不是真实边、挂不上。**侧立圆直径正解**：换到与圆平面平行的视图，ddim 挂真圆，即使该圆是隐藏边也能挂（数值/布局全对），但须先让圆显示出来。
- **公差带代号（H8/f7 等）＝尺寸后缀，实测配方（探针 73 打通，批处理 NX12）**：
  UF DRF 创建后无法带后缀 → 创建后按 tag 找 .NET 尺寸对象，**Get→改→Set**：
  ```python
  for d in part.Dimensions:
      if int(d.Tag) == int(tag):            # tag 来自 Create*Dim 后的对象
          at = d.GetAppendedText()          # 不能凭空构造 AppendedText()
          at.SetAfterText([u"H8"])          # 后缀在尺寸数字之后
          d.SetAppendedText(at)             # 否则 Invalid self parameter
          break
  ```
  ⚠ `d.Tag` 与 UF Create\* 返回 tag 的对应：用创建返回值直接匹配 part.Dimensions
  遍历（不要走 NXObjectManager.Get，见 §9）。
- **倒角标注：CreateChamferDim 在 NX12 批处理不可用 → label 引线注记等效**
  （02/03/05/06 端部 C2 实测）：`CreateChamferDim` 传 END_POINT 对象报
  "The first input object is invalid"（两轮复现，定性死路，见 §9）。
  等效做法 = label（§5 上条配方）文本 "C2"，引线挂 45° 倒角斜边（边几何里
  找 0.3<dx<4 且 |dx−dy|<0.05 的边），文本放斜边中点上方（my≥0, +8mm）/
  下方（my<0, −8mm），字高压 3.5。
- 常用控制序列：`<O>` 直径 Ø、`<#C>` 沉孔、`<$s>` 度 °、`<&10>` 位置度（Lettering 文档）。

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
    r = ufs.Tabnot.CreateRow(7.0)            # 行高 7mm（GB/T 10609.2 明细栏行高）
    ufs.Tabnot.AddRow(tn, tag_of(r), -1)
    for ci in range(ncols):
        c0 = ufs.Tabnot.AskNthColumn(tn, ci)
        cell = ufs.Tabnot.AskCellAtRowCol(tag_of(r), tag_of(c0))  # (row, col)
        ufs.Tabnot.SetCellText(tag_of(cell), vals[ci])            # 直径写 "<O>8"
ufs.Tabnot.Update(tn)
```

- **origin = 表格左上角**，向下生长；渲染吸附 ~2mm。
- 备用定位：`ufs.Drf.SetOrigin(tag, [x, y, 0.0])` **签字不符、本机未打通**（2026-09-22 实测：按此调用报 `NXException: The first parameter passed in was invalid.`，即第 1 参不接受 tabular note 的 tag，与 §6 表本体路线不同源）。定位继续用 §6 的 UFTabnot 路线（`AddColumn`/`AddRow` + `SetColumnWidth`/`SetRowHeight`，均已实测可用）。
- 其它成员 2026-09-22 实测结果（探针逐项打全消息）：
  - ✅ 可用：`AddColumn` / `AddRow` / `SetColumnWidth` / `SetRowHeight`（表格本体增删与列宽行高，实测通过）。
  - `AddHeaderRow` 报 `Function takes 3 arguments, 2 passed`（**3 参**）。
  - `EnableAutomaticUpdate` 报 `Function takes 1 arguments, 2 passed` —— 即它是 **0 参取用**（Python 绑定把 out 参数当返回值，见 SKILL.md §3 坑位 9），不要当 setter 用。
  - `SetCellPrefs` 报 `Tag passed to function is not of a tabular note cell (...cell_subtype) entity`：第 1 参必须是**真正的 cell tag**（`AskCellPrefs` 取回来的那个），传表格 tag 无效。
  - `MergeCells` 报 `Function takes 2 arguments, 5 passed`（**2 参**）。
  - `Sort` 在 `ufs.Tabnot` 上**不存在**。
- **结构体成员是 PascalCase、枚举要传枚举对象**（2026-09-23 实测，小写/裸 int 全被拒）：
  `SectionPrefs.UseDoubleWidthBorder = True` + `SectionPrefs.BorderWidth = 0.7` 打粗边框
  （图框用），`SectionPrefs.AttachPoint = NXOpen.UF.Tabnot.AttachPoint.ATTACH_POINT_TOP_LEFT`；
  `CellPrefs.HorizJust = NXOpen.UF.Tabnot.Just.JUST_CENTER`、`VertJust = Just.JUST_MIDDLE`。
- **行高只在对每个单元格关掉自适应后生效**（2026-09-23 实测；uf_tabnot.h 对 set_row_height
  的原话是 "Fit methods auto size row and auto size text must be disabled"）：先对每个 cell
  `AskCellPrefs` → `cp.NmFitMethods = 0` → `SetCellPrefs`，再 `SetRowHeight`。否则空行塌缩成
  ~5mm、超宽文字出图成 `############`（不是报错，是画面问题，渲染后才能看见）。
- **图框可以就用单格表格**（2026-09-23，用例 19/20 实测）：`Create` 一个 267×200 的单格表
  （GB A4 25/5 边距）+ 双线宽边框，标题栏/明细栏各自再用多列表格贴图框右下角——表格随图纸
  一起出图，无需画线拼框。表格 origin 都是左上角、向下生长，锚定后先 `AskNthRow/Col` 回读
  单元格文本做校验。
- **明细栏规范**（GB/T 10609.2）：行高 7mm、置于标题栏上方、**自下而上**填写
  （UF 表 row0 在底部，正好按"序号大的先加"）；列序 = 序号/代号/名称/数量/材料/备注。
- **BOM 单元格文字垂直居中公式**（2026-09-19 补）：`cy = ROW0 + RH*ri + RH/2.0`（ROW0 = 末行底边、ri 自 0 计）。错写成 `RH*(ri+1)+RH/2.0` 会全表上浮一行（表头悬空、末行空白）。
- **一项经用户定稿的版式口径**（2026-09-18；出同类正式图纸时优先于上方 GB 通用值）：
  1. 技术要求写在图样右下方空白区、**紧贴标题栏正上方**（总成图放明细表正上方），全套图纸**统一同一相对位置**，不得与图形、尺寸重叠（GB/T 14689 系列约定 + 机械制图通行做法）；
  2. 明细表收紧到 **150mm 宽、6.5mm 行高**、9 行（表头 + 8 项）；
  3. 标题栏与明细表**等宽对齐**（150×36 简化标题栏，图名/设计/校核/日期/图号/比例/材料重排）；
  4. **装配图三视图版式**（2026-09-30 用户按参考样图成图定稿）：主视图大面居图框**左下**（平面机构取运动平面视图为主视）、长条辅助视图居上方偏左、右视图居上方偏右，三视图铺满图框不挤半边；技术要求落明细栏正上方空档（与本条 1 同源）；球标随主视图布置。ZA 总成图 za30 按此重排后目检通过。
- **标题栏规范**（GB/T 10609.1）：180×56mm 右下角，图名/图号/材料/比例/设计/校核/日期。
  简化标题栏用画线+note 方案完全可控（7 张图纸实测，见 assembly-drafting.md §B.2）；
  UFTabnot 方案胜在自动边框/合并，定位靠 origin。
- **件号防自动编号**（2026-09-19 补）：总成图件号用 `CreateIdSymbol` 手动编号 + 手工明细表，不开自动件号（零件内草图曲线会被卷入自动编号）。
- .NET `PartsListBuilder` 在 NX12 **无创建入口**（仅模具模块 BomListBuilder）→
  装配明细栏批处理走"UFTabnot 手工明细栏 + `CreateIdSymbol` 球标"组合。

## 7. 中心线与中心标记

- 圆心十字：`Centerlines.CreateCenterMarkBuilder(CenterMark.Null)`，
  `Locations.Add(圆边, view, Point3d(圆心))`。
  ⚠ **一个 builder 只放一个 location**（2026-09-20 逐档实测：n=1 通过、n=2 通过、
  n=3 与 n=4 报 1175305、n=8 报 1175307；同一条边重复放两次也通过，说明与孔位、
  视图、图纸是否激活都无关，只与单次提交的 location 数有关）。批量中心标记就循环建
  builder；回归见 `scripts/tests/07_center_marks.py`（每次运行复测 n=3 被拒）。
- 通孔圆柱面有**两个等半径圆**（近端可见、远端在视图里是隐藏边），`ARC_CENTER` 挂哪个
  都成功（实测）；取其圆心时按 `p1 == p2`（整圆的两个顶点重合于圆心）识别整圆、
  按半径筛出孔壁面、取 z 较大者（近端）更贴合标注习惯。
- 轴线（过两孔/回转轴）：`CreateCenterline2dBuilder(Centerline2d.Null)`，
  `Type = Types.ByPoints`，`Point1/Point2.SetValue(关联边, view, 模型点)`。
  两点取对称要素的两心（孔对/边中点），线自动贯通超出轮廓。
- 回转体三视图都要画对称轴线（Front/Right 竖直轴 + Top 十字轴），这是"专业感"的硬指标。
- ⚠ 上述 .NET 标注路线**不需要 `sheet.Open()`**（2026-09-20 复测，见 assembly-drafting.md B.2）。

## 8. 反模式清单（AI 标注的"一眼假"来源，逐条对照）

1. 所有尺寸挤在离轮廓 2~3mm 处，或全部甩到 30mm 外 —— 无道位概念。
2. 平行尺寸大内小外 —— 界线交叉成网格。
3. 同一尺寸在两个视图重复标注。
4. 尺寸标注在虚线/不可见轮廓上。
5. 字号忽大忽小（note 6.5 vs 尺寸 3.5 混排）。
6. 箭头大小不一 / 开口箭头（未设 FilledArrow 或全局未继承）。
7. 无中心线、无中心标记 —— 回转体没有轴线。
8. 直径符号用字面 `Ø` 编码报错后整格空白。
9. 表格落在页面外/压标题栏（未删默认 5×5、origin 语义理解错）。
10. 封闭尺寸链（链式 + 总体全标）。

## 9. 坑位对照（遇到 → 怎么做）

| 遇到 | 怎么做 |
| --- | --- |
| `CenterMarkBuilder` 一次提交 ≥3 个 location，报 1175305 / 1175307（2026-09-20 实测，n=1/2 正常） | 一个标记一个 builder（§7）；与"批处理不能标注"无关，也不是 `sheet.Open()` 的事 |
| `CreateParallelDim` 配线性边，量出的距离是任意两点距（31 / 72.8 / 100.7 / 116.6 全错） | 端点歧义所致；pdim 只用于圆心对等这类唯一点，线性边改 hdim/vdim |
| hdim/vdim 的 `AssocDwgPos=[0,0]` 把共享边界线画到另一个视图（幽灵矩形 + 孤立箭头） | `AssocDwgPos` 给显式点；代价是引出点会渲染 ~1.5mm 圆 + 十字关联符号，关不掉，接受即可 |
| 字面 `Ø`(U+00D8) 进 UF 字符串，报 `Locale data detected when UTF8 data was expected` | 直径符号用 `<O>` 控制序列 |
| `Tabnot.Create` 后表格错位、多出空白列 | 先删默认 5×5 行列，再建自建行列 |
| `ufs.Modl.CreateCyl1` 报 AttributeError（MCP 索引里有，NX12 Python 封装没有） | 圆柱走圆弧截面拉伸 + BooleanBuilder 减（modeling.md §2.2/§2.5）；构造弧在建视图前 Blank |
| 想用 `NXOpen.UF.FeatureSigns` | 不存在（静态检查会拦）；UF 的 sign 枚举是 `NXOpen.UF.ModlFeatureSigns` |
| 想用 `part.Dimensions.Create*Dimension` 或 .NET dimension builder 出尺寸 | 无头批处理一律内存访问违例；尺寸全部走 UF DRF（assembly-drafting.md §B.2） |
| 想用 FCF / 表面粗糙度 / 孔表的 .NET builder | 空对象类在 NX12 不存在（`DraftingFeatureControlFrame` / `DraftingSurfaceFinishSymbol` 取不到 `.Null`），但 `CreateDraftingFeatureControlFrameBuilder` / `DraftingSurfaceFinishSymbols.CreateDraftingSurfaceFinishBuilder` / `HoleTables.CreateHoleTableBuilder` 都在，孔表 builder 实测可构造（成员 `Baseline/OrdinateOrigin/Origin/SelectedObjects/Style/Inherit/ResetLabelPosition`）。三者都还没跑出标注对象，**配方未打通**，用前先探针找空对象来源（`.Null` 不一定挂在同名类上） |
| 想标直径 / 孔径 / 半径 | `CreateDiameterDim` / `CreateHoleDim` / `CreateRadiusDim` 三者可用（2026-09-23 实测：圆角圆弧边与孔口整圆边上 `ComputedSize=10.0000`，直线边报 `The input object is invalid.`）；取候选按 `edge.SolidEdgeType == EdgeType.Circular` 筛，**不要按面半径筛**（同一圆柱面的两条直边会被一起选中） |
| `CreateChamferDim` 用 END_POINT，报 `The input object is invalid` | `AssocType` 无 CURVE 成员；倒角尺寸改走 label 引线注记（§5） |
| `NXOpen.Annotations.AppendedText()` 凭空构造，报 Invalid self parameter | 用 `d.GetAppendedText()` → 改 → `d.SetAppendedText()` |
| `import NXOpen.Utilities` 报 ImportError | NX12 的 sitecustomize 白名单拦截；改用 tag 匹配 `part.Dimensions` |
| label 引线想挂 `LeaderAttachment.Object` | 没有这个成员；挂真实边用 `OnObject`（§5） |
| 隐藏线开关按名字反推，画出来的正好相反 | `HIDDEN_LINE_REMOVAL_ON` = 移除不画、`OFF` = 画出；配方 `ufs.Draw.AskViewDisplay(tag)` → 改 `st.HiddenLine`/`st.HiddenLineFont` → `SetViewDisplay(tag, st)` → `UpdateOneView(sheet.Tag, view.Tag)`（**两参**） |
| 指望导出的 PDF 里有虚线 | 导出层不渲染虚线（`HiddenLineFont` 1~7 全实线），GB 的虚线要求批处理下满足不了 |
| 想逐尺寸设 EdlineAndArrow | 冗余，全局偏好已经继承 |
| hdim/vdim 两个 Drf 对象挂在同一条边上，尺寸渲染 "0" | END_POINT 关联对象不选端点，`AssocDwgPos` 给不同点也救不了（实测 `ComputedSize=0.0`，两条平行边对照 120.0）；每个尺寸挂两条不同的平行边（§4） |
| 剖视图内容方向不对 / `MapModelToDrawing` 包盒乱值 | 放置方位决定内容旋转：斜放即旋转且映射失真、无报错（实测包盒 76.64×119.87 对 120×16 剖面）；剖视沿父视图对齐轴放置（同 x/y 中心，实测包盒分毫不差），定位只走 placement origin，不用内容包盒 pin（§3） |
| 剖视图 Commit 成功但视图是空的 | placement 超出图幅不报错（实测可见对象 0、无 hatch、scale 仍 1.0）；建完断言可见对象数与 hatch ≥ 1（§3，`view_kinds`） |

## 10. 验证方法（标注类交付的反向验证底线）

1. **PDF 文本层逐值核对**：`pymupdf get_text('words')` 提取全部数字+坐标，
   与设计值/道位坐标比对（尺寸值错是 pdim 端点歧义这类"静默错误"的唯一线索）。
   ⚠ expect 容差 ±0.1：NX 关联值来自**模型真实几何**，而边几何 dump 的显示值
   本身有舍入（实例：dump 显示 553.45、模型真实 553.4499 → NX 渲染 "553.4"，
   按显示值算的 expect "553.5" 误报）。
2. **PDF 矢量线坐标测量**（`get_drawings()`；mm = pt/72×25.4、y 翻转 297−y_mm）：
   视图轮廓/尺寸线/道距的精确判据——渲染图像素目测不可靠，道位偏差曾靠它定位。
3. **150dpi 全页渲染目检布局** + 300~400dpi 局部裁剪核箭头/符号/字高细节。
4. 布局缺陷在渲染图上肉眼可辨：界线交叉、文字压线、道距不均、表格压框。
5. **幂等重跑**：对已保存标注的 PRT 重跑会**双重标注**——批处理 runner 必须
   先强制重置底稿副本再跑（副本被上轮 save 写回是隐形陷阱）。⚠ 若 runner 的
   prepare 是**全量**重置（删全部副本+全部产物），单张重跑须绕过它手动重置
   该张 PRT、单独调 run_one，否则连带删掉其他张的产物。
6. 拷贝产物核对**内容而非文件大小**（v1/v2 尺寸集不同 → 文本层判据如
   "v1 没有的尺寸值 + 标题栏版本号"），cp 的 glob 未匹配会静默跳过。
7. **中文文本层零判别力**：NX 导出 PDF 的中文无 ToUnicode 映射，pymupdf
   提不出中文字符——技术要求/标题栏/明细表的**中文内容**不能靠文本层核对
   （含"禁止出现 XX 字样"的反向断言同样无效），只能矢量词 bbox 定位 +
   get_pixmap clip 3~4x 高清渲染目检。数字/字母（H8、C2、45、v1.1）文本层
   仍可用，但注意分词粘连（"φ10H8," 整体成词，用 substring 而非 word 精确匹配）。
   ⚠ 2026-09-20 补：**直径符号 Ø 同样无 ToUnicode 映射**（`<O>8` 渲染正确但文本层
   只剩裸 "8"），故直径尺寸/引线标签里的 Ø 值只能用渲染图目检，不能进文本层判据。
8. **可复跑的值级校验**（2026-09-20 落地）：`scripts/tests/19_drafting_annotation.py`
   在 NX 侧断言"尺寸对象真的建出来了 + 全局偏好真的被继承 + 表格单元格回读一致 +
   PDF 落盘"；数值口径由 host 端 `scripts/tests/verify_anno_pdf.py` 用 PDF 文本层核对
   （实测 token：`70`/`40` 两孔距 + `R2.`/`4x` 证明注释与引线标签确实渲染进图）。
   NX 内嵌 Python 3.6 没有 PDF 库，所以值级判据只能放 host 端。
