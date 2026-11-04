# 交付件验证（STEP / STL / DXF / PMI / 占用）

本域只回答一个问题：导出的文件是否真的承载了几何与语义。所有门共用三态：
`PASS` / `FAIL` / `NO_SIGNAL`。仪器看不见时给 `NO_SIGNAL`，不得写成 `PASS`。

## 1. STEP 导出

固定配方（`nxlib.exchange.export_step`）：

1. 先保存部件；`InputFile` 指向已落盘的 `.prt`。
2. `ObjectTypes.Solids = True`。默认全 False 时 `Commit()` 不抛异常、日志写
   “All components translated successfully”、退出码 0，但文件只有 17–23 个实体、
   零 `MANIFOLD_SOLID_BREP`。
3. `ProcessHoldFlag = True`；`FileSaveFlag = False`。
4. AP214 必须设 `SettingsFile = <NX_HOME>\STEP214UG\ugstep214.def`。默认设置同样
   写空骨架（18 实体、solid=0）。
5. AP242 不要设 `step242ug.def`：它会把 `ExportAs` 覆盖成 `AUTOMOTIVE_DESIGN`
   并丢掉 `FLATNESS_TOLERANCE`。只设 `ExportAs = Ap242`。
6. PMI 要同时开 `ObjectTypes.PmiData` 与 `ObjectTypes.Annotations`；只开一个
   不会产生公差子类型。

## 2. STEP 普查门

导出后立即数实体，判据用相等而不是“≥”：

| 实体 | 应等于 |
|---|---|
| `MANIFOLD_SOLID_BREP` | 实体数 `len(part.Bodies)` |
| `ADVANCED_FACE` | `Σ body.GetFaces()` |
| `EDGE_CURVE` | `Σ body.GetEdges()` |
| `NEXT_ASSEMBLY_USAGE_OCCURRENCE` | 组件实例数 |
| `PRODUCT` | 零件数 + 1（装配根） |

单件 1/7/14、双体 2/12/24、两件装配 2 solids/2 NAUO/3 PRODUCT 均严格相等。
`ValidationProperties` 在 NX12 不写体积/质心，开关两份文件除产品名外逐字节相同；
不要把它当体积校验。

引用完整性另查：`#id` 定义集合减去引用集合，悬空即 `DELIV_E_STEP_DANGLING`。

## 3. STEP 导入与回读

- `ImportTo=WorkPart` 必须同时设 `OutputFile`（任意可写 `.prt` 路径）；漏设时
  `Commit()` 不报错、工作件仍是 0 bodies，必须靠回读判失败。
- `ImportTo=NewPart` 必须给 `SettingsFile` 与完整 `.prt` `OutputFile`。def 缺失
  或路径不存在时静默写约 40 KB 空壳（0 bodies），`Commit()` 不抛异常；
  `FileOpenFlag` 只设 False；`OutputFile` 的目录必须先建好，否则同样静默无产物。
- `ImportTo=NewPart` 的产物要等约 8 s 才落盘；成功后 `Parts.Work` 仍为 None、
  `Parts` 集合看不到新件、`GetCommittedObjects()` 为空，只能另起进程
  `Parts.OpenBaseDisplay` 重开读 `Bodies`。
- 242 与 214 的 NewPart 对“纯实体 AP242/AP214”都能重开 1 solid；带 PMI 的
  242 文件按 §6 的 PMI 普查另行判定。AP214 导出丢 PMI（装配件 1→0），
  期望 PMI 时不要选 214。
- 导入设置文件分方向：`ugstep214.def` 是 UG→STEP（导出），`step214ug.def`
  是 STEP→UG（导入）；214 用反方向打印 “No parts in current input file”，
  静默不产文件。242 的导入向在 `TRANSLATORS\step242\step242ug.def`，导出向
  `ugstep242.def`；`STEP242UG` 目录不存在，按 `TRANSLATORS\step242` 找。

## 4. STL 拓扑门

- 二进制尺寸公式 `84 + 50n` 必须成立。
- 水密：每条无向边恰好出现 2 次。
- 绕向：每条无向边一正一反；整体翻面仍满足局部绕向，必须另查有符号体积
  为正（NX 约定外法向）。
- 欧拉数按 `χ = 2C − 2g` 解释，不固定要求 2。带通孔件 g=1、单壳 χ=0。
- 体积与 B-rep 差按 0.1% 预算；ChordalTol=0.01 时圆孔多边形化约 +0.017%。
- 分量数 < 实体数判 `DELIV_E_STL_COMPONENTS`（少体）。分量数 > 实体数可能是
  内腔壳，不单独判失败；按 `χ=2C−2g` 逐壳解释。

## 5. DXF 门

实体分在 `Model` 与 `SHT1` 两个布局：几何线在 `Model`，`DIMENSION`/`VIEWPORT`/
`INSERT`/`MTEXT` 在 `SHT1`。只数 `modelspace()` 会把尺寸数成 0；必须遍历
`doc.layouts`。判据：`readfile` 成功、audit 0/0、`$INSUNITS=4`、`$MEASUREMENT=1`、
`DIMENSION` 数达到源图要求。

## 6. PMI 门

NX 写具体子类型：平面度是 `FLATNESS_TOLERANCE`，不是 `GEOMETRIC_TOLERANCE`。
按泛型计数恒为 0。判据按子类型族：`FLATNESS_TOLERANCE >= 1`、
`GEOMETRIC_ITEM_SPECIFIC_USAGE >= 2`，并检查 `LENGTH_MEASURE(0.05)` 是否落盘。
`PmiData`/`Annotations` 关掉时这三个读数一起归零。

- 只按公差子类型判：`DRAUGHTING_MODEL` 在无 PMI 的 AP242 里也有 25 个。
- 装配件：AP242 保留组件 PMI（1 FLATNESS / 2 GISU），AP214 静默丢成 0/0；
  结构实体两边一致（2 solid / 12 面 / 2 NAUO / 3 PRODUCT）。
- 尺寸类 PMI 在 NX12 批处理里不可用：`CreatePmiHorizontalDimension` 与
  Horizontal/Vertical/Ordinate/Diameter/Hole 及普通 `CreateHorizontalDimension`
  全部 `memory access violation`，空 `DimensionData + PmiData` 也崩；builder
  要求已存在 Dimension，无法自举。可交付的 PMI 只有 FCF（形状/方向类）。
  UndoMark 能隔离崩溃、部件仍可继续建 FCF；按 STEP 里
  `DIMENSIONAL_SIZE`/`LOCATION`/`SHAPE_DIMENSION_REPRESENTATION` 按 0 值判失败。

## 7. 占用门（空腔/多料）

- Z 单轴定站距会漏 1 mm 薄腔；站距必须 ≤ 最小特征厚度的一半，或改用三轴。
- 三轴切片按等分格中心取站，最后一格不足站距也要取中心，否则顶/底薄层无站。
- 体积差是独立证据：三角网格有符号体积差超过 `max(1 mm³, 0.2%·V_ref)` 即判
  FAIL，即使所有切片都 0 命中。面积站差阈值为 `max(0.5 mm², 0.1%·A_ref)`。
- 无差异且站距粗于 `min_feature/2` 时输出 `NO_SIGNAL`，不是 `PASS`。
- 连通分量变化也算差异（多体、内腔）。通孔负控：Ø10 通孔 ΔV 785.08 mm³
  （1.3258%），缺料跨满 Z 0–10。

## 8. 图纸 PDF

NX12 的 PDF 正文多为矢量轮廓：A3 页只有 8/12/16 个可提取词（归一化后
8/11/13），CJK 字符 0 个；`0 重叠`是“无信号”，不能证明版面正确。PDF 门只负责
页数、页面尺寸、可提取 token 与词级重叠；词数低于阈值时给 `NO_SIGNAL`。标题栏
与中文技术要求是矢量路径（右下区域 3 条路径，0 个 CJK 字符），由 NX 模型侧回读
（`gb_drawing.title_block` 的读回断言），不靠 PDF 文本层。软连字符 U+00AD
与零宽字符先归一化再比较；块级检测会被 PyMuPDF 合并词块，只作辅助。

## 9. 离线索引

- 运行期反射是“存在性”的唯一真源；pyi 快照用于参数表，hxx 只作名称辅助。
- hxx 的类声明要收 `class NX_DEPRECATED("...") EXPORT Name`；消息里可能含
  `()`，正则按引号串匹配，不按 `[^)]*`。当前头文件声明 72 个 deprecated 类。
- pyi 对比：24,157 类 / 运行期 16,797 类 / common 16,147 / runtime_only 650；
  公开成员缺失 0，缺失的 6,121 全是下划线枚举产物。
- 逐参数签名：`inspect.signature()` 对 NXOpen 运行期对象 0/1,900 可用，
  `__text_signature__` 全空；唯一来源是 `__doc__` 里的 `Signature Foo(a, b)` 块。
  50 类样本按 MRO 对比 pyi：1,826/1,828 参数名+顺序精确一致，2 个零参工厂
  （`Session.GetSession`、`UI.GetUI`）无 `__doc__`，0 个只能拿 arity、0 个名字/顺序
  不同。参数名是文档名不是关键字名：`CreateLine(startPoint=...)` 报
  `takes no keyword arguments`，所以可校验的是位置参数个数/顺序/文档一致性。
  用法：`python scripts/api_index.py --pyi <dir> --runtime <json> --doc-jsonl <jsonl>`。

## 10. 门的使用顺序

1. 导出前：保存部件并断言落盘。
2. 导出后：先跑 STEP/STL 普查，再跑 PMI/占用；任何 `FAIL` 立即回退。
3. 回读：另起进程打开产物，重算体积/面数。
4. 交付前：`check_deliverables.py` 汇总；`NO_SIGNAL` 要附原因（缺 ezdxf、
   缺 pymupdf、站距不足、PDF 无文本层）。
