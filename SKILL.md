---
name: nxopen-journal
description: 生成、检查并批处理回放 Siemens NX 12 的 NXOpen Python journal 脚本（NX 安装根用环境变量 NX_HOME 指定），覆盖三维建模、装配、Drafting 工程图、Advanced Simulation 有限元与 NX Motion 运动仿真自动化。用于“用 UG 建模/出三视图/做有限元分析/做运动仿真”或“写 NXOpen 脚本”类请求；触发词包括 NXOpen、journal、UG 脚本、NX 二次开发、自动建模、Drafting、NX Nastran、运动仿真、NX Motion、run_journal；英文触发词（English triggers）：Siemens NX automation, NXOpen Python journal, NX journal scripting, NX 12 automation, UG NX API, NX modeling, NX drafting, NX Nastran FEA, NX Motion simulation, run_journal.exe.
---

# NXOpen Journal 生成（NX 12）

NX 自动化唯一入口是 NXOpen API。本技能生成可在 NX 12 回放的 Python journal，覆盖建模/装配/工程图/有限元/运动仿真。
分层架构：本文件 = 会话与部件层（所有任务必读）；六个域文件（`references/` 下 modeling / assembly-drafting / drafting-annotation / fea / motion / gb-drawing）按任务类型选读其一（见 §5 路由表）。

⚠ **journal 解释器 = NX 12 内嵌 Python 3.6.1**（2026-09-16 实测：探针 journal 打印 `sys.version` = `3.6.1 (v3.6.1:69c0db5, Mar 21 2017) [MSC v.1900 64 bit]`，`sys.hexversion` = `0x030601 0x30`）。含义：**无 `math.dist`**（3.8+）、无 f-string `=` 调试语法、无 `math.prod`/`math.isqrt`(3.8+)、无 `dict` 合并运算符（3.9+）、无 `functools.cache`（3.9+）。`subprocess.run` 可用（3.5+）。写完 journal 先按 3.6 语法自查（`check_journal.py` 规则 5.16 已用 AST 拦截这批 API）；纯算法段可用宿主解释器（3.8 以上任意版本）预演逻辑，但那**只是预演、不能替代 NX 回放**——3.12 通过而 3.6 报 `AttributeError` 正是本坑的典型表现（曾白跑两次 NX 批处理才暴露完）。

## 1. 铁律

1. **API 零幻觉**：写任何 NXOpen 类/成员前先经 `nxopen` MCP 核实（`search_api` 支持中英文 / `get_class` / `get_member`）；API 幻觉是本类脚本失败的首要原因。
2. **MCP 核实"存在" ≠ Python 封装"可调用"**：新 API 必须先最小批处理实测，通过后才能写入本技能"已实测"条目（附日期）。
3. **MCP 查不到 ≠ 不存在**（2026-09-22 实测补）：nxopen MCP 索引对 NX12 收录不全 —— `ufs.Draw` 上实际存在 `CreateSteppedSxview`/`CreateHalfSxview`/`CreateRevolvedSxview`/`CreateUnfoldedSxview`/`CreateSxviewFromDmv` 五个索引里没有的方法，`NXOpen.UF.UFDraw` 也索引不到。查到方法名后仍要按顺序确认真实存在性：**先 `dir()` 运行期对象 → 再查 `%NX_HOME%\UGOPEN\*.h` 头文件与同目录 `*.c` 样例**（样例还能反推参数语义）。
4. **属性只读 ≠ 设不进去**（2026-09-22 实测补，与铁律 3 配套）：builder 的输入属性报 `is not writable` 时，先看它返回的是什么 —— 若返回 `SelectObject` / `ScCollector` 这类**容器**，容器自身的 `.Value` 往往可写。剖视图就是靠 `svb.ParentView.View.Value = <父视图>` 从"砍掉的功能"变成可用的（`View` 属性只读，但返回的 `SelectObject.Value` 可写）；反过来 `DetailViewBuilder.Origin`/`Scale` 确实无通道，那才退回 UF。判据：**先穷尽 builder 的容器通道，再改走 UF**——`*SegmentsBuilder` 看似"无 Add 方法"，实际入口是 `SegmentLocation.AddCutSegment()`。
5. **批处理 stdout 是全缓冲的：崩一次就丢光全部输出**（2026-09-22 实测，代价两轮）：`run_journal.exe` 的输出被重定向到文件时按块缓冲，进程一旦硬崩（见铁律 6），**已经 print 过但没落盘的内容全部消失**，日志只剩半截甚至为空，看上去像"根本没跑"。所以探针/长脚本的每一行都必须**同时**写日志文件并 `sys.stdout.flush()`：

```python
def say(msg):
    line = str(msg)
    with open(LOG, "a", encoding="utf-8") as f:   # 逐行落盘
        f.write(line + "\n")
    sys.stdout.write(line + "\n")
    sys.stdout.flush()                            # 否则崩溃时这行也没了
```

6. **传错参数类型会损坏原生堆，进程直接死且没有任何 traceback**（2026-09-22 实测）：把 Python **list** 传给期望 **int** 的 .NET 参数（实测 `wp.Layers.SetState([5], 1, 1)`）会让 NX 以 `-1073740940` = `0xC0000374`（STATUS_HEAP_CORRUPTION）退出，**既不抛 Python 异常也不给行号**。推论：**禁止写"猜签名、逐个候选调用"的自适应循环**——猜错一次就赔掉整个进程；签名必须来自 nxopen MCP 或 `dir()` 内省，然后**只调一次正确的那次**。
7. 未知 API/参数 → 标注"未验证"，交付时提醒用户回放确认。
8. 不修改 NX 安装目录（默认 `D:\UG-NX12`，可用环境变量 `NX_HOME` 覆盖，见 §2）；脚本与模型保存到用户工作区。
9. 回放前要求用户备份当前 Part；先用最小用例（新建 Part + 方块 + 保存）验证环境，再跑正式脚本。

## 2. 本机环境事实（已实测）

- **NX 安装根目录 = 环境变量 `NX_HOME`，默认 `D:\UG-NX12`**。本技能的全部实测都在该默认路径下完成；下文与 references 里一律写 `%NX_HOME%`，它就是该变量（未设时即 `D:\UG-NX12`）。**换安装位置时只需 `set NX_HOME=<NX 安装根>`**：`run_journal_batch.bat` 据此解析 `ugiicmd.bat` 与 `run_journal.exe`，解析不到就打印 `ERROR: run_journal.exe not found under NX_HOME=...` 并以 2 退出，不会静默跑错路径。
- NX 12.0.0.27；NXOpen .NET 程序集与 XML 文档在 `%NX_HOME%\NXBIN\managed\`（NXOpen.dll、NXOpen.xml、NXOpen.UF.* 等）。
- 批处理执行：`scripts\run_journal_batch.bat <journal.py> [workdir]`（自动 `call %NX_HOME%\UGII\ugiicmd.bat` 加载命令环境后调 `%NX_HOME%\NXBIN\run_journal.exe`）；`print()` 直达控制台、退出码 0=成功、无 GUI 弹窗。**每次冷启动新进程，不能注入已打开的 UG 会话**。workdir 不存在时批处理会先 `mkdir` 再进入，并**无条件打印 `=== RUN_JOURNAL workdir=<解析后绝对路径> ===`** —— 2026-09-22 实测：`pushd` 到不存在的目录会静默失败，journal 于是带着**调用方**的 CWD 运行，`os.path.abspath()` 指向别处、产物落到调用目录。判断"到底跑在哪个目录"就看这一行。
- 批处理会话没有已打开部件：`theSession.Parts.Work` 为 `None`；`UI.GetUI()` 与 `Parts.Display` 无实际意义（仅交互回放有意义）。
- mm 模板 `model-plain-1-mm-template.prt` 在 `%NX_HOME%\UGII\templates`。
- nxopen MCP 语义检索嵌入端点 = 本机 llama-server `http://127.0.0.1:11436`（bge-m3，`NXOPEN_MCP_EMBEDDER=llama`）；精确查询 `get_class`/`get_member` 不依赖嵌入服务。**嵌入服务没起时 `search_api`/`find_builder` 直接报错**，不会退化成关键词检索（`LlamaEmbedder` 只把 HTTPError 转成 RuntimeError，连不上的 URLError 原样抛出）；遇到这种报错就改走 `get_class`/`get_member` 精确查询，再按铁律 3 的顺序核实。README「前置条件」一节写了服务启动方式与三个环境变量。
- 交互回放：中文界面 工具→操作记录→运行；英文 Tools→Journal→Run。
- 批处理 `.bat` 必须纯 ASCII（cmd 按 GBK 解析，UTF-8 中文注释会损坏脚本）。

## 3. Journal 骨架与通用部件操作

```python
import NXOpen
import NXOpen.UF

def main():
    theSession = NXOpen.Session.GetSession()
    workPart = theSession.Parts.Work          # 批处理中为 None，须先新建/打开
    # ---- 功能代码：所有类/方法名先经 nxopen-mcp 核实 ----
    # 每个功能段 try/except 打印 NXOpen.NXException 的 Message（报错定位难）
    # 默认绝对坐标系建模；需要局部坐标系时显式创建
    # 结束必须显式保存（NX 异常退出未保存即丢失）

if __name__ == '__main__':
    main()
```

### 新建部件（已实测，直接套用）

```python
fileNew = theSession.Parts.FileNew()
fileNew.Units = NXOpen.Part.Units.Millimeters      # 必设
fileNew.TemplateFileName = "model-plain-1-mm-template.prt"
fileNew.NewFileName = "part_name.prt"              # 必带 .prt
fileNew.UseBlankTemplate = False
part = fileNew.Commit(); fileNew.Destroy()
```

新建回退链（批处理无工作部件时）：FileNew → NewDisplay → 当前工作部件（判空）→ 显式报错。

### 打开 / 保存 / 修改已有部件（已实测，直接套用）

```python
# 打开：Open 只传 1 个参数，返回 (part, loadStatus) 元组
part, loadStatus = theSession.Parts.Open(r"C:\path\part.prt")
# 修改已有部件必须先设显示部件，否则建特征 builder 报内存访问违例、SetWork 报无显示部件
NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(part.Tag)
# ... 对 part 建 builder/特征 ...
# 保存：无参 UF API（不要用 BasePart.SaveComponents.True，True/False 是 Python 关键字）
NXOpen.UF.UFSession.GetUFSession().Part.Save()
```

保存的另一条可用路线（带阶段校验，见本节「日志与阶段保存」）：

```python
import os
wp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue)
assert os.path.exists(path) and os.path.getsize(path) > 0   # 落盘才算数
```

⚠ 成员名是 `TrueValue` / `FalseValue`（枚举成员 `True` / `False` 在 Python 里是关键字，不能写）。

### 通用坑位（会话/部件层，check_journal.py 已静态拦截大部分）

1. **builder 创建不能传 `None`**：必须传封装层空对象 `NXOpen.Features.Feature.Null`（Block/Cylinder/Chamfer/Hole/EdgeBlend/Extrude/Revolve/Mirror/Pattern 等）、`NXOpen.Features.BooleanFeature.Null`（Boolean）。`.Null` 是 Python 封装层属性，.NET 反射中不存在，不要用 MCP 查。
2. **FileNew 不覆盖**：重复运行报 `File already exists` → 生成类 journal 启动时清理本工程旧 .prt 保证幂等；幂等清理须连 `_i.prt` 理想化件一起删（FEA 场景，见 fea.md §1）。**同一进程内也不要对同一路径 FileNew 两次**（2026-09-15 实测：第二个部件必须换文件名）→ 多部件脚本给每个部件独立路径。
3. **`Part.FullPath` 批处理中可能只显示文件名**（FileNew 刚创建时）；以磁盘实际落盘位置为准。
4. **集合无 `ToArray()`**：`part.Bodies`、`DrawingSheets`、`DraftingViews` 等直接 `for x in ...` 迭代。
5. **`ScCollector.ReplaceRules(rules, False)` 第二参数必须 `False`** 立即求值；`True` 规则不求值 → 选中 0 条边 → 倒角/特征创建失败。
6. **STL 批导出可用，位图出不了（要位图就走 PDF 与 STL 两条路）**（2026-09-16 修正，推翻 2026-08-22 与 2026-09-15 的"无产物"结论）：STL 导出**不需要** `ProcessHoldFlag`，关键是选择器用 `SetArray` 而非 `SelectionComp`：

```python
sc = s.DexManager.CreateStlCreator()
sc.OutputFile = stl_path
sc.ExportSelectionBlock.SetArray(bodies)   # ✅ 实体列表直接 SetArray → 落盘成功
sc.ChordalTol = 0.05                       # 可选；容差成员名见下
sc.Commit(); sc.Destroy()
```

   `STLCreator` 的容差成员实测只有 `ChordalTol` / `AngularTol` / `AdjacencyTol` 三个，**没有
   `TriangleTolerance`**；输出类型成员是 `OutputType` 配 `OutputTypeEnum`，**没有
   `OutputTypeOption`**。写错成员名会在提交时抛 `AttributeError` 并让整个导出中断——2026-09-23
   实测：5 个单实体件与 2 个装配件跑完一件 STL 都没落盘。装配件（几何在组件里）用 `part.Bodies`
   得到 0 个实体，且 `ExportSelectionBlock` 是 `SelectObjectList`、**没有 `SelectionScope`**
   （`ObjectSelector.Scope.EntirePart` 属于另一套 builder，对这里无效，实测 `AttributeError`）。
   可行路线是按组件逐个导出：`Component.GetPosition()` 给原点与 3×3 方向，`Component.DisplayName`
   给原型件名，两者都在装配件上就能读到，之后在 NX 之外按位置拼装。
   实测 4 件 CATPart 导入后批量导 STL 全部成功（276 KB～1.3 MB）；从导出的 STL 独立解析复算包围盒，与 NX `AskBoundingBox` 偏差 <3 mm，可交叉校验。`Body` **无** `GetVolume()` 方法（v12 实测 AttributeError），要体积得走 `ufs.Modl` 或 STL 复算。

   同一族的另一条边界（2026-09-23 实测）：**批处理会话出不了位图**。
   `Gateway.ImageCaptureManager.CreateImageCaptureBuilder()` 提交后不抛异常也**不写文件**；
   `ufs.Disp.CreateImage(path, ufs.Disp.ImageFormat.PNG, ufs.Disp.BackgroundColor.WHITE)` 直接抛
   `NXException: Internal error: memory access violation`（UF 枚举全大写，写 `Png` 会是
   `AttributeError`）。同一批实测里 `WorkView.Orient("Isometric", View.ScaleAdjustment.Fit)` 与
   `WorkView.RenderingStyle` 是能改的，模型视图也确实跟着变了，但落盘这一步没有可用入口。
   要位图就两条路：工程图用 Drafting 出 PDF（§4 域文件），三维几何按本条导 STL 后在 NX 之外渲染。
7. **`Point3d` / `Vector3d` 必须传 float**（2026-09-15 实测）：`NXOpen.Point3d(0, 0, 0)` 报 `TypeError: First parameter is invalid. Expecting double type, found int.`，`Vector3d` 同。写 `0.0` 而非 `0`（从 `Edge.GetVertices()` 等返回值构造的点本身已是 float，不受影响）。
8. **尺寸字符串不接受 float**（2026-09-15 实测）：`BlockFeatureBuilder.SetOriginAndLengths(origin, "100", "60", "20")` 的长度参数必须是 **str**，传 `100.0` 报 `Expecting str type, found float`；字符串里可写表达式名（`"T"`）。同理 `AddChainset(col, "2.0")`、`FirstOffset = "1.0"`。
9. **UF 的 struct 类型在 Python 里叫 `NXOpen.UF.<名>_Struct`**（2026-09-22 实测）：不是 `NXOpen.UF.UFMotion.InterferenceStruct`，也不是 `type(ufs.Motion).InterferenceStruct`——这两种写法分别报 `module 'NXOpen.UF' has no attribute 'UFMotion'` 与 `AttributeError`。`dir(NXOpen.UF)` 里能一次看到全部：`MotionInterference_Struct`、`MotionTrace_Struct`、`MotionSpringDamper_Struct`…（Motion 一族就有 25 个）。**UF 参数表里的 `Xxx@`（out 参数）在 Python 绑定里是返回值，不要当实参传**：MCP 写 `InitInterferenceStruct(Struct@)`，实际要写 `st = ufs.Motion.InitInterferenceStruct()`（0 参调用），传进去报 `Function takes 0 arguments, 1 passed`；同理 `AskGrueblerCount()` / `Interference(tag, 0)` 都是"传 in、收 out"。
10. **`builders` 的 `Name` 有的是通道、有的是普通 str**（2026-09-22 实测）：`SpringBuilder.Name` 是普通可写 str（直接 `b.Name = "x"` 即可）；而 `BushingDefine.Name` 在嵌套对象上（要写 `b.BushingDefine.Name`）。提交报 `A name has not been specified` 就是名字没落到真正承载它的那个对象上。

### 长 journal 的日志与阶段保存（2026-09-15 吸收）

批处理 journal 中断时 NX 可能不给收尾机会，**日志与已建几何必须能独立存活**。多阶段 journal（阵列 30+ 孔、复杂布尔、长循环）按以下写法：

1. **日志写文件并逐行 rewrite**，不要只 `print()`（agent 读不到 NX 列表窗口，截图低效）：每次 append 后整文件重写，硬崩也留下到故障点为止的轨迹。`print()` 仍保留，给控制台快速看。
2. **每步包 try/except 记完整 traceback 后继续**：一次运行暴露多个问题，而不是修一个跑一次；只有致命错误才让 journal 退出。
3. **阶段边界保存 + 校验落盘**：把 journal 分成"基础几何 → 主体 → 孔/布尔 → 阵列 → 倒圆/收尾"等阶段，每个阶段末保存并 `assert os.path.exists(path) and os.path.getsize(path) > 0`。**Commit 成功 ≠ 落盘**——这是唯一的落盘证据。
4. **昂贵/易崩步骤前存 checkpoint 副本**（`<部件名>__03-holes-complete.prt`）：大循环、复杂布尔、倒圆之前先存一次，崩了从最新 checkpoint 续做，不覆盖已确认的好文件。
5. **每次布尔后断言体数**：NX 布尔会静默不生效，体数是唯一证据（见 modeling.md §2.5）。

### Undo mark 与失败回滚（2026-09-19 补；惯例来源 nxjournaling.com，tests/11 实测回滚生效）

```python
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "stage-1")
try:
    ...  # 本段作业（建特征/约束/更新）
    session.DeleteUndoMark(mark, "stage-1")     # 成功即清理，不留脏 mark
except Exception:
    session.UndoToMark(mark, "stage-1")         # 回滚到 mark，部件回到作业前状态
    session.DeleteUndoMark(mark, "stage-1")
    raise
```

- **UndoToMark 是批处理下唯一的"事务边界"**：NX 没有事务，一段写了一半的几何特征只能靠 mark 回退（tests/11 实测：建方块后 UndoToMark，体数回到作业前）。
- 回滚是兜底不是掩错：先验证输入、每段 try/except 打 traceback（见上节）；UndoToMark 只用于"已确认失败、需要保持部件干净"的分支，不让它吞掉报错。
- 中间小段（DoUpdate 前置 mark 等）用 `Invisible`，需要整体可回滚的作业段用 `Visible`（不打扰/打扰交互回放的 Ctrl+Z 列表，两档本机均有使用实例）。
- `DeleteUndoMark` 必与 `SetUndoMark` 配对，长会话不清理会累积 mark。

### 外部格式导入（NX12 实测，2026-09-16）

判"NX 能不能读某异构格式"，**别猜，枚举 + 看对 DLL**：

```python
s = NXOpen.Session.GetSession()
for n in dir(s.DexManager):            # 只有这些就是全部能力
    if n.startswith('Create'): print(n)
# NX12 实测全集：Acis/Catiav4/Catiav5/Proe/Step(203/214/242)/Iges/Dxfdwg/Asc/Virtuallab/Stl/Nxto2d
```

- **没有 3dxml、没有 cgr 入口**。查扩展名要读主译者 `%NX_HOME%\CATIAV5\libtrancatv5.dll`（只含 `.catproduct`/`.CATPart`），**不要读 `libpscatiav5.dll`**——它是通用 CATIA 引擎，含 `.3dxml`/`.cgr`/`.model` 字样但导入器并不暴露，据此会误判支持（踩过）。
- ⚠ **假成功**：把不被支持的几何复制成 `.CATPart` 再 `Commit()` 会**不报错**并产出 ~38 KB `.prt`，实际 `part.Bodies` 数为 **0**。所以**导入后必须开文件读 `Bodies` 数**，"Commit 无异常"绝不等于成功。
- CATIA 的 `V5_CFV3` / `.3DRep` 是专有压缩容器（熵 7.5 bit/byte），**无公开解码器**（GitHub 亦无），要读只能用 CATIA 本体。
- **CATProduct 导入是扁平化的**：只解析当前文件直接层级的组件，子层常 `bodies=0`；`SearchDirectoryList` 是普通 str 属性（不是 `SetArray`）。组件本体坐标通常已是整车坐标——可用左右镜像对件的 Y 符号自行标定约定（本机实测件号段 411=左→Y 负、412=右→Y 正）。

### 导出（NX12 批处理实测，2026-09-15）

STEP 可用，但必须设同步标志：

```python
sc = session.DexManager.CreateStepCreator()
sc.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214      # Ap203 / Ap214 / Ap242
sc.ObjectTypes.Solids = True
sc.ExportSelectionBlock.SelectionScope = NXOpen.ObjectSelector.Scope.SelectedObjects
sc.ExportSelectionBlock.SelectionComp.Add(body)            # 只导实体，别整部件
sc.InputFile  = wp.FullPath
sc.OutputFile = r"C:\path\out.stp"
sc.ProcessHoldFlag = True                                  # ⚠ 必设：否则 Commit 返回时文件还没落盘
sc.Commit(); sc.Destroy()
```

⚠ 实测（2026-09-15）：不设 `ProcessHoldFlag=True` 时 `Commit()` 立即返回而 `.stp` 尚未生成（约 3 秒后才出现），紧接着校验存在性会误判失败；设 `True` 则 Commit 返回即已落盘，可立即校验。`DexManager` 在 NX12 **没有** Parasolid 导出方法。STL 导出可用，写法见 §3 坑位 6。

## 4. 工作流（固定 6 步）

1. 明确任务：零件/装配/图纸/仿真 + 关键尺寸 + 单位（默认 mm）。
2. 按 §5 路由表读对应域文件；建模任务先过 modeling.md §1 方法论（设计意图四问 + 特征树规划）再动手。
3. 用 nxopen MCP 核实每个将用到的类/方法/枚举。**新 API 先最小探针验证**：正式建模型前，先写一个只做"新建部件 + 每类操作各试一次"的探针 journal，逐项打 `成功/traceback`；探针通过再写正式脚本（`scripts/tests/11_api_probe.py`、`12_api_probe2.py`、`13_api_probe3.py` 是可抄的探针模板）。
4. 按域文件配方生成 journal（含 `main()` 入口、Session 获取、部件新建/打开、保存；长脚本按 §3「日志与阶段保存」加文件日志与阶段断言）。
5. `python scripts/check_journal.py <journal.py>` 静态检查（语法 + 占位符 + 已实测坑位模式拦截）。规则与实测依据逐条写在 `check_journal.py` 的注释里；两处豁免标记：整个文件是故意演示坑位的探针时在文件里写 `# check_journal: allow-probes`，单行负向对照（故意写错并断言必抛）在该行写 `# check_journal: expected-raise`。
6. `scripts\run_journal_batch.bat <journal.py> <workdir>` 本机批处理试跑（**journal 路径传绝对路径；workdir 非空时批处理会先切目录，相对路径会失效**；workdir 不存在会被自动创建，且日志首行无条件打印解析后的 workdir）→ 成功后交付用户交互回放；报错收集（截图或粘贴文本）→ MCP 核实修正 → 迭代。

## 5. 模块路由

| 任务 | 必读 |
|---|---|
| 零件建模（草图/特征/孔/阵列/镜像/旋转/表达式/可编辑性） | `references/modeling.md` |
| 图层与图层类别、独立基准平面 | `references/modeling.md` §1.7-§1.9 |
| 阵列（线性/圆周/沿路径/螺旋/正多边形/目标点/引用已有阵列）与特征镜像 | `references/modeling.md` §3.1-§3.1f + §3.2 |
| 抽壳/拔模/质量属性校验/去参/导出 | `references/modeling.md` §3.4-§3.6 + 本文件 §3 导出 |
| 装配（加组件/配对约束/组件阵列/引用集/装配质量属性） | `references/assembly-drafting.md` |
| 工程图（图纸/三视图/投影视图/局部放大/剖视图/PDF 导出/球标） | `references/assembly-drafting.md` §B |
| 工程图标注（尺寸道位布局/字高箭头风格/注释文字/表格/中心线） | `references/drafting-annotation.md` |
| **国标成套出图**（GB 图框/标题栏/技术要求/尺寸道位一张图直接到位） | `scripts/gb_drawing.py` + `references/gb-drawing.md`（验收=33 号用例） |
| 有限元（CAD→FEM→SIM→求解→后处理；实体 CTETRA 与 2D 壳/PSHELL、模态 SOL103） | `references/fea.md` |
| 运动仿真（NX Motion：Link/运动副/驱动/连接件/求解/结果提取/静不定反力陷阱） | `references/motion.md` |
| 可编辑性验证 | `references/modeling.md` §6 + `scripts/tests/08_editability_probe.py` |

- 纯修改已有部件（不建草图/阵列）通常只读本文件即可。
- 跨域复合任务（建模+装配+出图）按依赖顺序读多个域文件；域文件之间不互相依赖，个别两三行的通用事实在域内直接重复，避免连环读取。
- 与上游流程联动：载荷/边界数据可来自上游校核类技能或手工计算的结果；模型文件落在项目工作区约定的固定目录。

## 6. 脚本与回归

```bash
# 静态检查（无需 NX；拦截 §3 坑位 1/2/4/5/7/8 + 尺寸只读属性 + UF 枚举名 + Py3.6 专属 API 等）
python scripts/check_journal.py path/to/journal.py

# 批处理试跑（journal 用绝对路径；workdir 可选）
scripts\run_journal_batch.bat C:\abs\path\journal.py [workdir]

# 全量回归（35 例 = 32 个批处理令牌校验 + 11-13 三个一次性探针）。
# 逐例覆盖内容与令牌名**只维护在 tests/README.md**（"用例、文件与判决 token"一节），
# 此处不再复制一份 —— 两份清单必有一份先腐烂。
# 09 含 Nastran 求解较慢
# 跑完自动清理 parts\ 下的产物（含 Nastran 的 .f06/.op2 中间件；每次运行完整重建）；
# 产物个数与体积只在 tests/README.md 记一处，此处不再抄一份
# set KEEP_PARTS=1 可保留
# 最后一步自动做 19 的数值口径复核（宿主 python + pymupdf 读 PDF 文本层，见 tests/README.md）；
# 该步无条件打印 "pdf value check interpreter:" 与 "rc=" 两行自证，输出 PASS/SKIP/FAIL 三态关键字
#   python scripts\tests\verify_anno_pdf.py scripts\tests\parts\anno19.pdf
scripts\tests\RUN_TESTS.bat
# 环境变量（都可省，省了用默认值）：
#   NX_HOME   NX 安装根，默认 D:\UG-NX12；换安装位置必须设它
#   PYTHON    跑 19 的 PDF 值级复核用的解释器，需带 pymupdf；默认取 PATH 上第一个 python
#   KEEP_PARTS=1  跑完保留 parts\ 产物，便于排查
```

改动本技能（references 配方、check_journal.py、run_journal_batch.bat）后，先跑 `RUN_TESTS.bat` 全部通过再交付。

**写新用例/新脚本：先 `import nxlib`，不复制配方**（2026-09-23 起）。`scripts/nxlib/` 是五域标准层：`testing`（stage/check/RESULTS 与 `_FAIL` 约定）、`session`（new_part 的 name/path 两态与 FEM/SIM 模板坑位）、`modeling`/`assembly`/`drafting`（各域已固化配方）；文件头 8 行引导样板见 `nxlib/__init__.py` 的 docstring。探针/死路用例保持自包含是设计决策，豁免名单在 `check_repo.py` 的 `SELF_CONTAINED`，新增同类必须显式登记；用例顶层函数与 nxlib 公开 API 同名会被 check_repo 第 5 组拦截（防配方复制回流）。

⚠ **检查一律看输出 token，不看退出码**（2026-09-20 实测修正）：`run_journal.exe` 对**未捕获**异常确实返回非零（顶层 `raise` 实测 `RUN_JOURNAL_EXIT=1`），但本技能 §3 强制"每步 try/except 打 traceback 后继续"，失败被脚本自己吞掉时退出码仍是 0 —— 所以退出码只在"脚本没吞异常"时才可信。29 个批处理用例全部由 `RUN_TESTS.bat` 的 `:gate` 子过程把关：**必须出现期望 token，且输出中不得出现任何 `_FAIL`**。用例侧约定（新用例照此写）：成功只在全部通过时打印 `TESTxx_DONE`（09/16/18 打 `BENCH_PASS`、10 打 `CONSTRAINT_PASS`），失败路径必须打印带 `_FAIL` 的判定结果（`TESTxx_FAIL`/`BENCH_FAIL`/`STAGE_FAIL`）；`test14/15` 的 `TESTxx_DONE` 必须放在 ok 判定**之后**，否则失败运行也会打出成功 token。逐项 `check()` 型用例（22/23/24/25/26/27/28/29/30）单条失败打 `REG_xxx=FAIL <实测值>`（刻意不含 `_FAIL` 子串，避免与整体判定结果混淆），末尾再打 `TESTxx_FAIL failed=[...]`。
⚠ **退出码还有第三种污染源**（2026-09-22 实测）：`test26` 故意复现 `ThreadedHole` 的原生崩溃（内存访问违例），此后进程退出码恒为 1 —— 即使日志开头写着 "Execution was successful."、全部检查 PASS。**这类"已知崩溃探针"必须末位执行、并靠令牌判定**；崩后残留的残废特征用 `session.SetUndoMark/UndoToMark` 撤掉。

⚠ **检查要有判别力（不是恒真断言）**：写运动学/数值检查时，期望值必须来自**独立信息源**（解析闭式解、指令参数），不能取自被测数据本身——后者是自洽检查，数据整体平移/缩放都会通过。且必须做过**反向验证**：故意改坏一处（如把驱动速率写成 rad/s 值、改一个杆长），确认对应检查确实 FAIL。`tests/18_motion_sim.py` 的记录在 `tests/README.md`「18 的反向验证记录」。

## 7. 维护约定

- 新实测坑位/配方按操作归位并入对应域文件小节（标注实测日期），不按日期另开新节。
- 各域文件内的**坑位对照表**（"遇到 → 怎么做"）保持显式列出，防止重复踩坑；每格只写"遇到什么"与"该怎么做"，不复述失败经过与已作废的旧结论。
- 入库门槛 = 铁律 2：MCP 核实 + 批处理实测双通过。
- **结论要能追溯到实测轮次**（2026-09-22 补）：探针是"跑完即弃"的一次性脚本，但**日志是唯一证据** —— 删除探针前把日志归档到项目侧的取证目录（本机约定 `work\`）下，勿留在技能目录里。
  ⚠ 读日志时**区分"尝试失败行"与"实测结论行"**：前者的 `X -> AttributeError: …` 常被误读成结论（本轮 `SpringBuilder.AttachmentType` 就是这么写错了配方）。
  所以只有**升格成回归用例并跑通**的结论才算固化；用例就是结论的常驻复核。
- **新增小节后核对交叉引用**（2026-09-22 补）：插入/重排小节会让 `§x.y` 引用与铁律/坑位编号错位（本轮铁律 5/6 插入后旧 5/6/7 顺延为 7/8/9），
  改完 `grep -rn "§[0-9]" SKILL.md references/` 与 `grep -rn "铁律 [0-9]\|坑位 [0-9]"` 逐个核一遍。
- **吸收外部技能/项目时**：其结论先按铁律 2 在本机复验，与竞品冲突处以本机实测为准并注明（如 cookbook 的 25.4× 换算、多体质量属性、螺纹配方均为 NX 2506 专属，NX12 不适用）；确认可用的按域归位，不可用的进坑位表。

## 8. 文件清单

```
nxopen-journal/
├── SKILL.md                        ← 本文件（入口层：铁律/环境/骨架/通用部件操作/日志导出/工作流/路由）
├── LICENSE                         ← MIT 许可证
├── README.md                       ← 对外说明（中文，主文档）：定位 / 前置条件（NX 版本、NX_HOME、agent、Nastran、nxopen MCP 与嵌入服务）/ 安装与使用 / 实跑产物 / 覆盖范围 / 回归用例 / 为什么选择这个 skill / 已知限制 / 目录结构
├── README.en.md                    ← 同一份说明的英文落地页，与 README.md 顶部互链
├── images/                         ← README 的实跑产物图（三维与装配由 STL 离线渲染，其余来自回放产物）
├── references/*.md                 ← 六个域文件；各自的域与覆盖范围见 §5 路由表（勿在此重复维护一份）
├── scripts/gb_drawing.py           ← 国标出图标准件（图框/三视图钉位/标题栏/技术要求/尺寸道位/PDF；验收=33 号用例，用法=references/gb-drawing.md）
├── scripts/nxlib/                  ← 用例标准层（testing/session/modeling/assembly/drafting 五模块；新用例 import 它、不复制配方，函数 docstring 标注来源用例即口径；文件头引导样板见 __init__.py）
├── scripts/render/                 ← 离线出图链（NX 批处理截不了图：STL→着色渲染、PDF→PNG；用法=scripts/render/README.md）
├── scripts/check_journal.py        ← 静态检查（语法/占位符/已实测坑位，含 NX12 专属名与 Py3.6 API）
├── scripts/check_repo.py           ← 仓库自检（Py3.6 语法 / 用例清单一致 / 文档结构 / 文件清单 / 标准层独占；CI 与本机共用）
├── scripts/run_journal_batch.bat   ← 批处理试跑（ugiicmd + run_journal.exe；NX 安装根走 NX_HOME）
├── scripts/tests/                  ← 回归套件；README.md 有运行方式、用例与判决 token 表、各轮反向验证记录、已知限制
│   ├── 01…35_*.py                  ← 32 个并入令牌校验的用例（RUN_TESTS.bat 全量跑）
│   ├── 11…13_api_probe*.py         ← 一次性 API 探针，不纳入检查
│   ├── verify_anno_pdf.py          ← 19 号用例的 PDF 文本层数值复核（宿主解释器 + pymupdf）
│   └── RUN_TESTS.bat               ← 全量回归 + 19 号用例的 PDF 值级复核
└── agents/openai.yaml              ← Codex/OpenAI 端界面配置（跨端迁移用）
```
