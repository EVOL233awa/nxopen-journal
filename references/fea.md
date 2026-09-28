# 有限元域：CAD → FEM → SIM → 求解 → 后处理（NX 12 批处理全链路实测）

> 先读 SKILL.md（铁律/骨架/通用部件操作）。2026-08-23 全链路批处理实测通过（CAD→FEM→CTETRA(10)→PSOLID+Steel→SIM→BC→SOL101→op2 后处理），悬臂梁基准 FEA 挠度/手算 = 1.033。完整可跑示例 = `scripts/tests/09_fea_static.py`（自带手算校验，BENCH_PASS 标志）。模式来源：theScriptingEngineer/NXOpen-CAE-python 录制 journal + 本机 NX12 批处理适配。

## 0. 文件体系与前置

- 文件链：主几何 .prt →（理想化 `_i.prt` 自动创建）→ .fem（网格/材料）→ .sim（BC/解算方案）。模板在 `%NX_HOME%\SIMULATION\templates\`：`FemNxNastranMetric.fem` / `SimNxNastranMetric.sim`（公制 NX Nastran）。
- 许可：本机已确认有 `nx_masterfem`、`nx_design_sim`、NX Nastran 求解许可（`%NX_HOME%\NXNASTRAN\bin\nastran.exe`）。
- 求解器/分析类型字符串：`"NXNASTRAN"`/`"STRUCT"`（FinalizeCreation 入参）；读回显示名为 `('NX NASTRAN', 'Structural')`。
- **单位制 mm-N-s-MPa**：应力即 MPa、力即 N；库 Steel E=206940 MPa、密度 7.83e-9 tonne/mm³（重力载荷时注意）。
- 载荷/边界条件数据来自上游校核类技能或手工计算的结果（接触压紧力、摩擦扭矩、转速这类工程载荷）时，注意单位换算。

## 1. CAD → FEM

```python
fn = session.Parts.FileNew()
fn.Units = NXOpen.Part.Units.Millimeters
fn.TemplateFileName = "FemNxNastranMetric.fem"      # 扩展名必须 .fem
fn.NewFileName = "model.fem"
fn.UseBlankTemplate = False
fem = fn.Commit(); fn.Destroy()                     # 直接返回 FemPart（无需 Cast，NX12 无 FemPart.Cast）
fem.FinalizeCreation(
    cad_part, "model_i",                            # 理想化部件名（自动创建同名 .prt）
    NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
    fem.NewFemSynchronizeOptions(),
    "NXNASTRAN", "STRUCT",
    NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet,
    ["desc"], False)
fem.GetSolverAndAnalysisType()                      # 读回 ('NX NASTRAN', 'Structural')
# ⚠ 幂等清理须连理想化件一起删：model.fem、model_i.prt（及关联 .prt）
```

## 2. 材料 + PSOLID + 实体网格收集器

```python
ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
    "PSOLID", "NX NASTRAN - Structural", "NX NASTRAN", "PSOLID1", 2)   # 2=label
steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")  # 库 E=206940 MPa
ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
col_b = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(
    NXOpen.CAE.MeshCollector.Null, "Solid")          # None 不行，必须 .Null
col_b.CollectorName = "SteelSolid"
col_b.PropertyTable.SetNamedPropertyTablePropertyValue("Solid Property", ppt)
collector = col_b.Commit(); col_b.Destroy()
# 2D 壳对应：("ThinShell", "PSHELL", "PSHELL2", "element thickness" mm, "Shell Property")
```

⚠ **材料属性表两条（2026-09-25 冷测 T4 实测）**：setter 对无单位量（ν）不接受 Python `None`（报 `No overload matches (str,str,NoneType)`），须传 `NXOpen.Unit.Null`；属性名精确匹配 `YoungsModulus` / `PoissonsRatio` / `MassDensity`——子串匹配会抓到 `YoungsModulusControl` 控制属性报错。

## 3. CAE 几何枚举（体/面）

```python
body = fem.FindObject("CAE_Body(1)")                # CAEBody 无 GetFaces（NX12 实测）
faces = []
for i in range(1, 60):
    try: faces.append(fem.FindObject("CAE_Body(1)|CAE_Face(%d)" % i))
    except Exception: break                          # 越界即停，编号连续
# 面法向识别（仅原型面！实例面 GetUgfaces 会内存违例）：
ug = face.GetUgfaces()                               # CAEFace -> NXOpen.Face 桥
d = ufs.Modeling.AskFaceData(ug[0].Tag)              # 返回 (type, point, dir_list, box, radius, ...)
plane = (d[0] == 22); nz = d[2][2]                   # dir 是 list 不是 Vector3d
```

## 3a. 2D 壳网格 + PSHELL（2026-09-22 实测通过；求解级标定见 §3a-2，回归 `scripts/tests/24_shell_mesh.py` + `25_shell_solve.py`）

```python
# 物理属性表 + 壳收集器（PSHELL 走 PhysicalPropertyTables，材质走 MaterialManager）
ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
    "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", "PSHELL1", 2)
steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
cb = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(NXOpen.CAE.MeshCollector.Null, "ThinShell")
cb.CollectorName = "PTShell"
cb.PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)
col = cb.Commit(); cb.Destroy()

# 2D 面网格
face = fem.FindObject("CAE_Body(1)|CAE_Face(6)")
mb = fem.BaseFEModel.MeshManager.CreateMesh2dBuilder(NXOpen.CAE.Mesh2d.Null)
mb.SelectionList.Add(face)
mb.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.Shell   # 见下表
mb.ElementType.ElementTypeName = "CQUAD4"
mb.CommitMesh(); mb.Destroy()
```

- ⚠ **`ElementTypeBuilder.ElementType` 成员名不能猜**：`ThinShell` **不存在**（报 `type object '...ElementType' has no attribute 'ThinShell'`）。实测全表 = `AnySolid / Beam / Connection / Contact / FreeSolid / Point / Pyramid / QuadShell / Shell / Spider / SweepSolid / SweepSolidWedge / TriaShell / Weld`。2D 壳用 `Shell`（配 `ElementTypeName="CQUAD4"` 或 `"CTRIA3"`）；3D 用 `FreeSolid`（配 `"CTETRA(10)"`，§4）。
- ⚠ `.fem/.sim` 部件**不能用 `Parts.Work` 收尾**：`FileNew` 一个 `.fem` 模板后 `session.Parts.Work` 会抛 `NXException: The part file is not a .prt part`。必须用 `fn.Commit()` 的返回值（本节与 §5 都是这么拿的）。
- ⚠ **壳厚必须在 PSHELL 表上显式写 `element thickness`**，它不是从几何取的（不写就只剩默认厚度，挠度差几个量级）。属性名不要猜，先枚举：`[ppt.PropertyTable.GetPropertyNameByIndex(i) for i in range(ppt.PropertyTable.GetPropertyCount())]` → 实测 13 项 `Plane Strain / material / bending material uses material / bending material / transverse shear material uses material / transverse shear material / membrane-bending coupling material / element thickness / bending coefficient / shear ratio / nonstructural mass / fiber distance 1 / fiber distance 2`。
  写法：`ppt.PropertyTable.SetBaseScalarWithDataPropertyValue("element thickness", "5.0", unit_mm)`，单位对象取 `fem.UnitCollection.FindObject("MilliMeter")`；读回用 `GetScalarWithDataPropertyValue("element thickness")` → `(5.0, <Unit>)`。

### 3a-2. 2D 壳的**求解级数值标定**（2026-09-22 实测，回归 `scripts/tests/25_shell_solve.py`）

整链：**薄板体 → PSHELL 壳网格 → 端边固支 + 端边集中力 → SOL101 → 与梁理论对照**，检查期望值全部来自独立解析解。

| 量 | 解析（梁理论） | NX SOL101 | 比值 |
| --- | --- | --- | --- |
| 端部挠度 δ = FL³/(3EI) | 3.0927 mm | 3.090916 mm | **0.9994** |
| 根部 von Mises σ = FL(t/2)/I | 480.0 MPa | 473.83 MPa | **0.9871** |

算例：100 × 5 mm 薄板体、PSHELL 厚 t = 5 mm、Steel（E = 206940 MPa）、一端短边 6 DOF 全固支、另一端短边 −Z 总力 100 N、
`I = b·t³/12 = 52.0833 mm⁴`；20 mm 四边形壳元，204 节点。b/L = 0.05，横向剪切只占 0.2%，故梁理论可用。

三条落地要点（都曾让人白跑）：

1. **被测几何要造成薄板体（sheet body）**：`cad.Features.CreateBoundedPlaneBuilder(NXOpen.Features.BoundedPlane.Null)`，
   而 `BoundingCurves` 是**只读容器**（直接赋值报 … is not writable，提交报 `No profile selected`）→
   必须 `bp.BoundingCurves.AddToSection([rule], lines[0], NXObject.Null, NXObject.Null, helpPoint, Section.Mode.Create, False)`（SKILL.md 铁律 4）。
   只有 4 条边的板体才能用**边长**认出两端边；换成"实体块顶面"网格化后块有 12 条边，分不清哪 4 条属于被网格化的面。
2. **端边 BC/载荷挂 `CAE_Edge`**，过滤器用 `CaeSetGroupFilterType.GeomEdge`，目标对象经 `NXOpen.CAE.SetObject()`（`Obj` + `SubType` + `SubId`）包一层；
   `CAEEdge` 只暴露 `GetLength()`（没有取底层 UG 边的入口），所以端边靠 `abs(len - B) < 0.5` 挑出来（实测 4 条边长度 = 5/100/100/5）。
   ⚠ sim 侧要取**FEM 组件的实例边**：`sim.ComponentAssembly.RootComponent.GetChildren()[0].FindObject("CAE_Body(1)|CAE_Edge(n)")`（§6 同规矩）。
3. **解算方案要挂输出请求**（§5 的同一坑）：不挂 `Structural Output Requests` 则后处理报 `No results found`；实测结果类型 =
   `Displacement - Nodal / Rotation - Nodal / Stress - Elemental / Stress - Element-Nodal / Reaction Force - Nodal / Reaction Moment - Nodal`。

**检查必须有判别力（反向验证已做）**：把壳体 `element thickness` 改成 2.5 mm 而理论值仍按 5 mm 算（模拟"属性静默没生效"），
实测挠度比 **7.9803**（理论预测 (5/2.5)³ = 8）、应力比 3.8682，`BENCH_SHELL_DEFLECTION` / `BENCH_SHELL_STRESS` 双双 FAIL、退出码 1。
——注意**不能**让理论值跟着错误厚度重算，那样是自洽检查，恒真无鉴别力。

## 4. CTETRA(10) 四面体网格

```python
b = fem.BaseFEModel.MeshManager.CreateMesh3dTetBuilder(NXOpen.CAE.Mesh3d.Null)
b.SelectionList.Add(body)
b.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.FreeSolid
b.ElementType.ElementTypeName = "CTETRA(10)"
b.ElementType.DestinationCollector.ElementContainer = collector
b.ElementType.DestinationCollector.AutomaticMode = False
unit_mm = fem.UnitCollection.FindObject("MilliMeter")
# ⚠ 属性名跨版本有漂移：先 GetPropertyCount()/GetPropertyNameByIndex(i) 枚举再设值
b.PropertyTable.SetBaseScalarWithDataPropertyValue(
    "quad mesh overall edge size", "4", unit_mm)     # NX12 有此名；无 "automatic size option bool"
b.CommitMesh(); b.Destroy()
fem.BaseFEModel.MeshManager.GetNodeStatus()          # [TotalNum=..., LowLabel, HighLabel]
```

## 5. SIM 文件 + SOL101 解算方案

```python
fn = session.Parts.FileNew()
fn.Units = NXOpen.Part.Units.Millimeters
fn.TemplateFileName = "SimNxNastranMetric.sim"
fn.NewFileName = "model_sim.sim"; fn.UseBlankTemplate = False
sim = fn.Commit(); fn.Destroy()                      # 直接返回 SimPart
sim.FinalizeCreation(fem, -1, ["desc"])              # -1 = USE_ORIGINAL 层
sol = sim.Simulation.CreateSolution(
    "NX NASTRAN", "Structural", "SESTATIC 101 - Single Constraint",
    "Solution 1", NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
if sol.StepCount == 0:
    sol.CreateStep(0, True, "Subcase - Statics 1")   # ⚠ NX12 是 3 参重载（5 参版本报错）
# ⚠ 关键：不挂输出请求则 dat 无 DISPLACEMENT/STRESS 卡片、op2 空、后处理报 No results found
mo = sim.ModelingObjectPropertyTables.CreateModelingObjectPropertyTable(
    "Structural Output Requests", "NX NASTRAN - Structural", "NX NASTRAN",
    "Structural Output Requests1", 2)
sol.PropertyTable.SetNamedPropertyTablePropertyValue("Output Requests", mo)
# ⚠ BC 目标必须用 sim 树下 FEM 组件的实例面，传 .fem 原型面报
#   "Selected objects are not in the same file as the Targetset"：
comp = sim.ComponentAssembly.RootComponent.GetChildren()[0]
occ_face = comp.FindObject("CAE_Body(1)|CAE_Face(%d)" % i)   # 无需 PROTO# 前缀
```

## 6. 边界条件（描述符 + SetObject + TargetSetManager）

```python
def face_objs(faces):
    objs = []
    for f in faces:
        so = NXOpen.CAE.SetObject(); so.Obj = f
        so.SubType = NXOpen.CAE.CaeSetObjectSubType.NotSet; so.SubId = 0
        objs.append(so)
    return objs

# 固定约束：⚠ NX12 无 "FixedConstraint" 描述符（Invalid LBC neutral name），
# 用 "UserDefinedDisplacementConstraint" + DOF1..6 全 0（"-777777"=自由）
b = sim.Simulation.CreateBcBuilderForConstraintDescriptor(
    "UserDefinedDisplacementConstraint", "Fixed(1)", 1)b.TargetSetManager.SetTargetSetMembers(
    0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace, face_objs(fixed_faces))
u_mm = sim.UnitCollection.FindObject("MilliMeter"); u_deg = sim.UnitCollection.FindObject("Degrees")
for dof, unit in (("DOF1", u_mm), ("DOF2", u_mm), ("DOF3", u_mm),
                  ("DOF4", u_deg), ("DOF5", u_deg), ("DOF6", u_deg)):
    fe = b.PropertyTable.GetScalarFieldPropertyValue(dof)
    fe.EditFieldExpression("0", unit, [], False)
    b.PropertyTable.SetScalarFieldPropertyValue(dof, fe)
b.BcName = "FixedEnd"; b.DestinationFolder = NXOpen.CAE.SimLbcFolder.Null
b.CommitAddBc(); b.Destroy()

# 面力（默认 Total 分布，单位牛顿，已由悬臂梁基准标定验证）：
lb = sim.Simulation.CreateBcBuilderForLoadDescriptor(
    "ComponentForceField", "Force(1)", 2)            # "magnitudeDirectionForce" 是另一种交互
lb.TargetSetManager.SetTargetSetMembers(
    0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace, face_objs(tip_faces))
u_n = sim.UnitCollection.FindObject("Newton")
exprs = [sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
         sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
         sim.Expressions.CreateSystemExpressionWithUnits("-500", u_n)]
vw = sim.FindObject("FieldManager").CreateVectorFieldWrapperWithExpressions(exprs)
lb.PropertyTable.SetVectorFieldWrapperPropertyValue("CartesianMagnitude", vw)
lb.CommitAddBc(); lb.Destroy()
# ⚠ distributionType 属性不是 string 类型（SetStringPropertyValue 报 "does not support this
#   interface"），默认即 Total，勿画蛇添足。
# 过滤器类型：GeomFace/GeomBody/GeomVertex/GeomEdge/Node（CaeSetGroupFilterType）
```

## 6a. 解算方案家族全表 + 模态 SOL103（2026-09-22 实测；描述符结论与"激活方案绑定"已纳入检查，回归 `scripts/tests/30_fea_descriptors.py`）

**描述符真名只能从 NX 自己的模板里读，不能猜**。规矩：`%NX_HOME%\SIMULATION\templates\SimNxNastran*.sim` 里存着该求解器可用的描述符全集，用正则 `[A-Z]{2,10} 1\d\d - ...` 直接抽：

```bash
python -c "
import os, re
p = os.path.join(os.environ.get('NX_HOME', r'D:\UG-NX12'),
                 'SIMULATION', 'templates', 'SimNxNastranEnglish.sim')
b = open(p, 'rb').read()
print(sorted({m.group().decode('latin-1') for m in re.finditer(rb'[A-Z]{2,10} 1[0-9]{2} - [ -~]{5,45}', b)}))"
```

实测全集（NX Nastran 模板）：`SESTATIC 101 - {Single,Multi} Constraint / Adaptive / Superelement`、`NLSTATIC 106 - {Single,Multi} Constraint`、`SEMODES 103 - {Flexible Body,Response Simulation,Superelement}`、`SEDFREQ 108 - Direct FRF`、`SEMFREQ 111 - Modal FRF`。

```python
# 模态（SOL 103 Real Eigenvalues）：⚠ 描述符就是裸的 "SEMODES 103"，没有 " - Normal Modes" 后缀
sol = sim.Simulation.CreateSolution(
    "NX NASTRAN", "Structural", "SEMODES 103", "SolModal",
    NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
if sol.StepCount == 0: sol.CreateStep(0, True, "Subcase")
sol.GetDisplayNameOfSolutionType()   # → 'SOL 103 Real Eigenvalues'
sol.GetDisplayNameOfSolverType()     # → 'NX Nastran'
sol.SolverType                       # → 'NX NASTRAN'
```

⚠ 网上常见的 `SEMODAL 103 - Normal Modes` 在本机**不存在**。判据别用错误消息
（`NXException: Error number: 1775003` 对垃圾名和错名返回**同一个号**，分辨不出是"名字不存在"还是"创建失败"），
改用正对照：换成 `SESTATIC 101 - Single Constraint` 立刻成功，真名从模板正则抽。

⚠ **BC 描述符的有效性跟当前激活解算方案绑定，而新建方案会立刻变成激活方案**（2026-09-22 受控 A/B，用例 30 断言复现）：
建完模态方案后紧接着建载荷 BC 会报 `Invalid LBC neutral name`，先 `sim.Simulation.ActiveSolution = <静态方案>`，
**同一个名字立刻可用**。描述符错误抛在 builder 创建那一刻（`CreateBcBuilderFor{Load,Constraint}Descriptor`），不是 `CommitAddBc`；
该函数的第 3 参是**载荷标签（int）**，不是方案选择器。

- 实测有效的中性名只有两个：载荷 **`ComponentForceField`**、约束 **`UserDefinedDisplacementConstraint`**（两者都有正向对照，见 `scripts/tests/30_fea_descriptors.py`）。试过但**无效**（全部 `Invalid LBC neutral name`）：`PressureField` / `Pressure` / `NormalPressureField` / `HydrostaticPressureField` / `MagnitudeDirectionForceField` / `GravityField` / `AccelerationField` / `InertiaLoad` / `CentrifugalField` / `FixedConstraint` / `EnforcedDisplacementConstraint` / `PinnedConstraint` / `SimplySupportedConstraint`（用例 30 对 `FixedConstraint`/`PinnedConstraint`/`PressureField` 三个做了常驻负向断言）。
- `sim.Simulation` 上可用的 BC 入口：`CreateBcBuilderForBc` / `…ForConstraintDescriptor` / `…ForLoadDescriptor` / `…ForSimulationObjectDescriptor` / `CreateAutoBcBuilder` / `CreateLoadSetBuilder` / `CreateConstraintSetBuilder`。

## 7. 求解 + 后处理

```python
ufs.Part.Save()                                      # 求解前保存
mgr = NXOpen.CAE.SimSolveManager.GetSimSolveManager(session)
mgr.SolveChainOfSolutions([sol],
    NXOpen.CAE.SimSolution.SolveOption.Solve,
    NXOpen.CAE.SimSolution.SetupCheckOption.DoNotCheck,
    NXOpen.CAE.SimSolution.SolveMode.Foreground)     # NX12 批处理同步求解 OK
# 产物：<sim名>-solution_<n>.{dat,f06,log,op2}；EXIT(0) 看 .log 尾部

rd, rn = sol.GetResultFile()                         # rd 可能为空串！
if not rd: sol.SetLocalResultFile(os.getcwd(), rn)   # 必须显式挂目录
sres = session.ResultManager.CreateSolutionResult(sol)   # 比 Find("Structural")+CreateReferenceResult 稳
it = sres.GetLoadcases()[0].GetIterations()[0]
rts = it.GetResultTypes()   # Displacement - Nodal / Stress - Element-Nodal / Reaction Force - Nodal ...

def ask_max(rt_name, comp):                          # comp: Component.Magnitude / VonMises
    rt = [t for t in rts if t.Name.lower() == rt_name.lower()][0]
    rp = session.ResultManager.CreateResultParameters()
    rp.SetGenericResultType(rt); rp.SetResultComponent(comp)
    rp.MakeElementResult(False); rp.SetUnit(rt.AskDefaultUnitForComponent(comp))
    ra = session.ResultManager.CreateResultAccess(sres, rp)
    v = ra.AskMaximum()                              # 直接取极值，勿逐节点循环
    session.ResultManager.DeleteResultAccess(ra); session.ResultManager.DeleteResultParameters(rp)
    return v
```

⚠ NXOpen.CAE 无 SetShellSection（NX12 实体结果不需要）；von Mises 用 `Component.VonMises`；应力类型名是 **"Stress - Element-Nodal"**（不是 Elemental-Nodal）；解引用用 `ResultManager.DeleteResultAccess/DeleteResultParameters`（对象上无 Delete 方法）。

⚠ **批处理求解与后处理四条（2026-09-25 冷测 T4/T9 实测）**：
1. 输出请求带 PLOT 选项时数值**只落 op2 不打印 f06**——f06 仅含求解摘要，值级复核走 ResultAccess 读结果文件或解析 op2。
2. 中文工作目录下批处理 .NET 侧 `SetLocalResultFile` / ResultManager 不可用（Python 层文件操作不受影响）——后处理走 f06 文本提取（求解器原生产物）。
3. 直调 nastran.exe 返回码 1 但结果可能完整——以 f06 内容判定，不看返回码（与技能"按 token 判定"口径一致）。
4. SOL103 deck 提交前必查 `EIGRL` 体卡与 `METHOD` case-control 命令都在：NX12 批处理下挂接 Lanczos 提取对象成功且无报错，两卡仍可能都不导出，缺卡即 Nastran FATAL 9056、0 阶；文本补卡 + 直调求解配方见冷测样本（工作目录 t09/patch_solve.py），NX 自导出路线待实测（路标）。

## 8. FEA 工程师方法论（2026-08-23 网络调研 + 本机基准实测归纳）

来源：Simcenter/FEA 通用最佳实践（网格收敛、圣维南原理、NAFEMS 基准文化）、theScriptingEngineer 工作流、本机悬臂梁基准。

1. **先手算后软件**：任何 FEA 前先做量级手算（梁弯曲 δ=FL³/3EI、σ=Mc/I、压缩 δ=FL/AE）；偏差 >20% 先查模型，<10% 再谈精度。本机基准：δ=+3.3%（剪切效应）、σ 峰值 +16%（固定端应力集中，正常圣维南现象，报告中注明位置）。
2. **单位制**：mm-N-s-MPa；面力默认 Total（整面合力，已标定验证）。
3. **网格**：CTETRA(10) 为默认（CTETRA4 过刚）；全局尺寸取关键特征/壁厚的 1/2~1/4 起步；正式结果做 h 加密收敛研究（尺寸减半、关注量变化 <5% 视为收敛）。
4. **边界条件远离关注区**（圣维南）：约束/集中载荷附近 1~2 倍特征长度内应力不可信；固定面全约束在角点产生应力集中，报告 max 应力时注明位置；必要时取远离约束的中段应力对比梁理论。
5. **奇异性识别**：点载荷、锐角、约束角点的应力随网格细化不收敛，不作为判定依据；改用分布载荷/圆角/远端取值。
6. **判定准则**：延性钢 von Mises vs 屈服（235/345 MPa），安全系数 = 屈服/vM_max；位移做 sanity check（量级、方向、变形形状合理）。
7. **验证闭环（journal 内自动化）**：09 测试模式——求解后自动读 Max 位移/vM，与手算解析解比对，容差内打印 BENCH_PASS/BENCH_FAIL。
8. **网格前先验 CAD**：FEA 前先用 modeling.md §3.5 测 CAD 实体的体积/质心，确认几何是想要的（体积对不上说明布尔没融合或尺寸写错）——几何错了网格再细也白搭。

## 9. FEA 交付自检清单

- [ ] 手算解析解已列（公式+数值），FEA/手算比值在 0.9~1.4（含剪切/圣维南余量）
- [ ] 材料来源明确（库 Steel 或自定义参数已核对 E/ν/ρ）
- [ ] 网格：CTETRA(10)、尺寸依据（壁厚比例）、节点/单元数已打印
- [ ] BC 用意图命名（FixedEnd/TipLoad 等），载荷大小/方向/单位（N）明确
- [ ] 求解 log EXIT(0)、无 FATAL；f06 无奇异警告
- [ ] 输出请求已挂（否则 op2 空）；读回 Max 位移与 vM 并与手算对照
- [ ] 报告注明应力峰值是否位于约束边角（圣维南区）
- [ ] .fem/.sim/.op2 全部落盘在工程目录
