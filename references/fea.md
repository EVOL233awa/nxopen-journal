# 有限元域：CAD → FEM → SIM → 求解 → 后处理（NX 12 批处理）

> 先读 SKILL.md。完整示例 `scripts/tests/09_fea_static.py`（手算校验，BENCH_PASS）。悬臂梁基准 FEA 挠度/手算 = 1.033。

## 0. 文件体系与前置

- 链：.prt →（`_i.prt` 自动创建）→ .fem（网格/材料）→ .sim（BC/解算方案）；模板 `%NX_HOME%\SIMULATION\templates\`：`FemNxNastranMetric.fem` / `SimNxNastranMetric.sim`（公制 NX Nastran）。
- 许可：`nx_masterfem`、`nx_design_sim`、NX Nastran（`%NX_HOME%\NXNASTRAN\bin\nastran.exe`）。
- 求解器/分析类型：`"NXNASTRAN"`/`"STRUCT"`（FinalizeCreation 入参）；读回 `('NX NASTRAN', 'Structural')`。
- 单位制 mm-N-s-MPa（应力 MPa、力 N）；Steel E=206940 MPa、密度 7.83e-9 tonne/mm³（重力载荷注意）；上游/手算载荷（压紧力、摩擦扭矩、转速）需换算单位。

## 1. CAD → FEM

```python
fn = session.Parts.FileNew()
fn.Units = NXOpen.Part.Units.Millimeters
fn.TemplateFileName = "FemNxNastranMetric.fem"   # 扩展名必须 .fem
fn.NewFileName = "model.fem"; fn.UseBlankTemplate = False
fem = fn.Commit(); fn.Destroy()                  # 直接返回 FemPart；NX12 无 FemPart.Cast
fem.FinalizeCreation(
    cad_part, "model_i", NXOpen.CAE.FemPart.UseBodiesOption.AllBodies, [],
    fem.NewFemSynchronizeOptions(), "NXNASTRAN", "STRUCT",
    NXOpen.CAE.BaseFemPart.AxisymAbstractionType.NotSet, ["desc"], False)
fem.GetSolverAndAnalysisType()
# ⚠ 幂等清理连理想化件一起删：model.fem、model_i.prt（及关联 .prt）
```

基名全目录唯一（跨扩展名亦然）：`cantilever_cad.prt` / `cantilever.fem` / `cantilever_i.prt` / `cantilever_sim.sim`；否则 `A part file with the same base name already exists.`

## 2. 材料 + PSOLID + 实体网格收集器

```python
ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
    "PSOLID", "NX NASTRAN - Structural", "NX NASTRAN", "PSOLID1", 2)   # 2=label
steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
col_b = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(
    NXOpen.CAE.MeshCollector.Null, "Solid")      # None 不行，必须 .Null
col_b.CollectorName = "SteelSolid"
col_b.PropertyTable.SetNamedPropertyTablePropertyValue("Solid Property", ppt)
collector = col_b.Commit(); col_b.Destroy()
```

⚠ 无单位量（ν）传 `NXOpen.Unit.Null`（`None` 报 `No overload matches (str,str,NoneType)`）；属性名精确 `YoungsModulus`/`PoissonsRatio`/`MassDensity`（子串命中 `YoungsModulusControl`）。

## 3. CAE 几何枚举（体/面）

```python
body = fem.FindObject("CAE_Body(1)")             # CAEBody 无 GetFaces
faces = []
for i in range(1, 60):
    try: faces.append(fem.FindObject("CAE_Body(1)|CAE_Face(%d)" % i))
    except Exception: break                      # 越界即停，编号连续
# 面法向仅原型面可用（实例面 GetUgfaces 内存违例）：
ug = face.GetUgfaces()                           # CAEFace -> NXOpen.Face 桥
d = ufs.Modeling.AskFaceData(ug[0].Tag)          # (type, point, dir_list, box, radius, ...)
plane = (d[0] == 22); nz = d[2][2]               # dir 是 list 不是 Vector3d
```

## 3a. 2D 壳网格 + PSHELL（求解级标定见 §3a-2）

```python
ppt = fem.PhysicalPropertyTables.CreatePhysicalPropertyTable(
    "PSHELL", "NX NASTRAN - Structural", "NX NASTRAN", "PSHELL1", 2)
steel = fem.MaterialManager.PhysicalMaterials.LoadFromNxlibrary("Steel")
ppt.PropertyTable.SetMaterialPropertyValue("material", False, steel)
cb = fem.BaseFEModel.MeshManager.CreateCollectorBuilder(NXOpen.CAE.MeshCollector.Null, "ThinShell")
cb.CollectorName = "PTShell"
cb.PropertyTable.SetNamedPropertyTablePropertyValue("Shell Property", ppt)
col = cb.Commit(); cb.Destroy()

face = fem.FindObject("CAE_Body(1)|CAE_Face(6)")
mb = fem.BaseFEModel.MeshManager.CreateMesh2dBuilder(NXOpen.CAE.Mesh2d.Null)
mb.SelectionList.Add(face)
mb.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.Shell
mb.ElementType.ElementTypeName = "CQUAD4"
mb.CommitMesh(); mb.Destroy()
```

- ⚠ `ElementType` 无 `ThinShell`（`has no attribute 'ThinShell'`）。全表：`AnySolid/Beam/Connection/Contact/FreeSolid/Point/Pyramid/QuadShell/Shell/Spider/SweepSolid/SweepSolidWedge/TriaShell/Weld`。2D 用 `Shell`+`CQUAD4`/`CTRIA3`；3D 用 `FreeSolid`+`CTETRA(10)`。
- ⚠ `.fem/.sim` 不能用 `Parts.Work`（`The part file is not a .prt part`），用 `fn.Commit()` 返回值。
- ⚠ 壳厚必须在 PSHELL 表显式写 `element thickness`（不写只剩默认厚度，挠度差几个量级）。属性名先枚举 `GetPropertyNameByIndex(i)` + `GetPropertyCount()` → 13 项 `Plane Strain / material / bending material uses material / bending material / transverse shear material uses material / transverse shear material / membrane-bending coupling material / element thickness / bending coefficient / shear ratio / nonstructural mass / fiber distance 1 / fiber distance 2`。
  写法：`SetBaseScalarWithDataPropertyValue("element thickness", "5.0", unit_mm)`，单位取 `fem.UnitCollection.FindObject("MilliMeter")`；读回 `GetScalarWithDataPropertyValue` → `(5.0, <Unit>)`。

### 3a-2. 2D 壳的**求解级数值标定**

整链：薄板体 → PSHELL 壳网格 → 端边固支 + 端边集中力 → SOL101 → 对照梁理论。

| 量 | 解析（梁理论） | NX SOL101 | 比值 |
| --- | --- | --- | --- |
| 端部挠度 δ = FL³/(3EI) | 3.0927 mm | 3.090916 mm | **0.9994** |
| 根部 von Mises σ = FL(t/2)/I | 480.0 MPa | 473.83 MPa | **0.9871** |

算例：100×5 mm 板、t=5 mm、E=206940 MPa、短边 6 DOF 固支、对边 −Z 100 N；`I=b·t³/12=52.0833 mm⁴`；20 mm CQUAD4、204 节点；b/L=0.05。

1. **薄板体**：`cad.Features.CreateBoundedPlaneBuilder(NXOpen.Features.BoundedPlane.Null)`；`BoundingCurves` 只读（not writable / `No profile selected`）→ `bp.BoundingCurves.AddToSection([rule], lines[0], NXObject.Null, NXObject.Null, helpPoint, Section.Mode.Create, False)`。仅 4 边板体可按边长认端边。
2. **端边 BC/载荷挂 `CAE_Edge`**，过滤器 `GeomEdge`，目标经 `NXOpen.CAE.SetObject()`（`Obj`/`SubType`/`SubId`）；`CAEEdge` 只有 `GetLength()`，按 `abs(len-B)<0.5` 挑。sim 用实例边：`sim.ComponentAssembly.RootComponent.GetChildren()[0].FindObject("CAE_Body(1)|CAE_Edge(n)")`。
3. **挂 `Structural Output Requests`**，否则 `No results found`。结果类型：`Displacement - Nodal/Rotation - Nodal/Stress - Elemental/Stress - Element-Nodal/Reaction Force - Nodal/Reaction Moment - Nodal`。

判别力：理论值不得随错误厚度重算。t = 2.5 对 5 mm：挠度比 ≈ 8（7.9803）、应力比 3.8682，`BENCH_SHELL_*` 应 FAIL。

## 4. CTETRA(10) 四面体网格

```python
b = fem.BaseFEModel.MeshManager.CreateMesh3dTetBuilder(NXOpen.CAE.Mesh3d.Null)
b.SelectionList.Add(body)
b.ElementType.ElementDimension = NXOpen.CAE.ElementTypeBuilder.ElementType.FreeSolid
b.ElementType.ElementTypeName = "CTETRA(10)"
b.ElementType.DestinationCollector.ElementContainer = collector
b.ElementType.DestinationCollector.AutomaticMode = False
unit_mm = fem.UnitCollection.FindObject("MilliMeter")
# ⚠ 属性名跨版本漂移：先 GetPropertyCount()/GetPropertyNameByIndex(i) 枚举再设值
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
sim = fn.Commit(); fn.Destroy()
sim.FinalizeCreation(fem, -1, ["desc"])              # -1 = USE_ORIGINAL 层
sol = sim.Simulation.CreateSolution(
    "NX NASTRAN", "Structural", "SESTATIC 101 - Single Constraint",
    "Solution 1", NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
if sol.StepCount == 0: sol.CreateStep(0, True, "Subcase - Statics 1")  # NX12 3 参重载
# ⚠ 不挂输出请求：dat 无 DISPLACEMENT/STRESS、op2 空、后处理 No results found
mo = sim.ModelingObjectPropertyTables.CreateModelingObjectPropertyTable(
    "Structural Output Requests", "NX NASTRAN - Structural", "NX NASTRAN",
    "Structural Output Requests1", 2)
sol.PropertyTable.SetNamedPropertyTablePropertyValue("Output Requests", mo)
# ⚠ BC 目标用 sim 树 FEM 组件实例面；原型面报
#   "Selected objects are not in the same file as the Targetset"
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

# 固定约束：NX12 无 "FixedConstraint"（Invalid LBC neutral name），
# 用 "UserDefinedDisplacementConstraint" + DOF1..6 全 0（"-777777"=自由）
b = sim.Simulation.CreateBcBuilderForConstraintDescriptor(
    "UserDefinedDisplacementConstraint", "Fixed(1)", 1)
b.TargetSetManager.SetTargetSetMembers(
    0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace, face_objs(fixed_faces))
u_mm = sim.UnitCollection.FindObject("MilliMeter"); u_deg = sim.UnitCollection.FindObject("Degrees")
for dof, unit in (("DOF1", u_mm), ("DOF2", u_mm), ("DOF3", u_mm),
                  ("DOF4", u_deg), ("DOF5", u_deg), ("DOF6", u_deg)):
    fe = b.PropertyTable.GetScalarFieldPropertyValue(dof)
    fe.EditFieldExpression("0", unit, [], False)
    b.PropertyTable.SetScalarFieldPropertyValue(dof, fe)
b.BcName = "FixedEnd"; b.DestinationFolder = NXOpen.CAE.SimLbcFolder.Null
b.CommitAddBc(); b.Destroy()

# 面力（默认 Total 分布，单位 N）：
lb = sim.Simulation.CreateBcBuilderForLoadDescriptor(
    "ComponentForceField", "Force(1)", 2)
lb.TargetSetManager.SetTargetSetMembers(
    0, NXOpen.CAE.CaeSetGroupFilterType.GeomFace, face_objs(tip_faces))
u_n = sim.UnitCollection.FindObject("Newton")
exprs = [sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
         sim.Expressions.CreateSystemExpressionWithUnits("0", u_n),
         sim.Expressions.CreateSystemExpressionWithUnits("-500", u_n)]
vw = sim.FindObject("FieldManager").CreateVectorFieldWrapperWithExpressions(exprs)
lb.PropertyTable.SetVectorFieldWrapperPropertyValue("CartesianMagnitude", vw)
lb.CommitAddBc(); lb.Destroy()
# ⚠ distributionType 非 string（SetStringPropertyValue 报 "does not support this
#   interface"），默认即 Total。
# 过滤器：GeomFace/GeomBody/GeomVertex/GeomEdge/Node（CaeSetGroupFilterType）
```

## 6a. 解算方案家族全表 + 模态 SOL103

**描述符真名只能从 NX 模板读，不能猜**：`%NX_HOME%\SIMULATION\templates\SimNxNastran*.sim`，正则 `[A-Z]{2,10} 1\d\d - ...` 抽取：

```bash
python -c "
import os, re
p = os.path.join(os.environ.get('NX_HOME', r'D:\UG-NX12'),
                 'SIMULATION', 'templates', 'SimNxNastranEnglish.sim')
b = open(p, 'rb').read()
print(sorted({m.group().decode('latin-1') for m in re.finditer(rb'[A-Z]{2,10} 1[0-9]{2} - [ -~]{5,45}', b)}))"
```

全集：`SESTATIC 101 - {Single,Multi} Constraint / Adaptive / Superelement`、`NLSTATIC 106 - {Single,Multi} Constraint`、`SEMODES 103 - {Flexible Body,Response Simulation,Superelement}`、`SEDFREQ 108 - Direct FRF`、`SEMFREQ 111 - Modal FRF`。

```python
# 模态 SOL 103：描述符就是裸的 "SEMODES 103"，无 " - Normal Modes" 后缀
sol = sim.Simulation.CreateSolution(
    "NX NASTRAN", "Structural", "SEMODES 103", "SolModal",
    NXOpen.CAE.SimSimulation.AxisymAbstractionType.NotSet)
if sol.StepCount == 0: sol.CreateStep(0, True, "Subcase")
sol.GetDisplayNameOfSolutionType()   # → 'SOL 103 Real Eigenvalues'
sol.GetDisplayNameOfSolverType()     # → 'NX Nastran'
sol.SolverType                       # → 'NX NASTRAN'
```

⚠ `SEMODAL 103 - Normal Modes` 不存在；`NXException: Error number: 1775003` 对垃圾名/错名同号，不能判别；用正对照 `SESTATIC 101 - Single Constraint`。

⚠ **BC 描述符有效性绑定当前激活方案，新建方案立即激活**：模态方案后建载荷 BC 报 `Invalid LBC neutral name`，先 `sim.Simulation.ActiveSolution = <静态方案>`。错误抛在 `CreateBcBuilderFor{Load,Constraint}Descriptor`（非 `CommitAddBc`）；第 3 参是载荷标签（int），非方案选择器。

- 有效：`ComponentForceField`（载荷）、`UserDefinedDisplacementConstraint`（约束）。无效（均 `Invalid LBC neutral name`）：`PressureField`/`Pressure`/`NormalPressureField`/`HydrostaticPressureField`/`MagnitudeDirectionForceField`/`GravityField`/`AccelerationField`/`InertiaLoad`/`CentrifugalField`/`FixedConstraint`/`EnforcedDisplacementConstraint`/`PinnedConstraint`/`SimplySupportedConstraint`。
- BC 入口：`CreateBcBuilderForBc` / `…ForConstraintDescriptor` / `…ForLoadDescriptor` / `…ForSimulationObjectDescriptor` / `CreateAutoBcBuilder` / `CreateLoadSetBuilder` / `CreateConstraintSetBuilder`。

## 7. 求解 + 后处理

```python
ufs.Part.Save()                                      # 求解前保存
mgr = NXOpen.CAE.SimSolveManager.GetSimSolveManager(session)
mgr.SolveChainOfSolutions([sol],
    NXOpen.CAE.SimSolution.SolveOption.Solve,
    NXOpen.CAE.SimSolution.SetupCheckOption.DoNotCheck,
    NXOpen.CAE.SimSolution.SolveMode.Foreground)     # NX12 批处理同步求解
# 产物：<sim名>-solution_<n>.{dat,f06,log,op2}；EXIT(0) 看 .log 尾部

rd, rn = sol.GetResultFile()                         # rd 可能为空串
if not rd: sol.SetLocalResultFile(os.getcwd(), rn)   # 必须显式挂目录
sres = session.ResultManager.CreateSolutionResult(sol)
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

⚠ 无 `SetShellSection`（NX12 实体结果不需要）；von Mises 用 `Component.VonMises`；应力类型名 **"Stress - Element-Nodal"**（非 Elemental-Nodal）；解引用 `DeleteResultAccess`/`DeleteResultParameters`（对象无 Delete）。

⚠ **批处理求解与后处理**：
1. PLOT 输出时数值只落 op2 不打印 f06（f06 仅求解摘要）；值级复核用 ResultAccess 或解析 op2。
2. 中文工作目录下 .NET 侧 `SetLocalResultFile`/ResultManager 不可用（Python 文件操作正常）→ 后处理走 f06 文本提取。
3. 直调 nastran.exe 返回码 1 可能结果完整 → 以 f06 内容判定。
4. SOL103 deck 提交前查 `EIGRL` 体卡与 `METHOD`：Lanczos 提取对象成功且无报错时两卡仍可能不导出，缺卡即 FATAL 9056、0 阶；文本补卡 + 直调求解，NX 自导出未验证。

## 8. FEA 工程师方法论

1. **先手算后软件**：δ=FL³/3EI、σ=Mc/I、δ=FL/AE；偏差 >20% 查模型，<10% 谈精度。基准：δ +3.3%（剪切）、σ 峰值 +16%（固定端集中，注明位置）。
2. **单位制**：mm-N-s-MPa；面力默认 Total（整面合力）。
3. **网格**：CTETRA(10) 默认（CTETRA4 过刚）；尺寸取关键特征/壁厚 1/2~1/4；h 加密（尺寸减半）变化 <5% 为收敛。
4. **BC 远离关注区**（圣维南）：约束/集中载荷 1~2 倍特征长度内应力不可信；角点应力集中注明位置；取远端中段对比梁理论。
5. **奇异性**：点载荷、锐角、约束角点随网格细化不收敛，不作判据；改用分布载荷/圆角/远端取值。
6. **判定**：延性钢 von Mises vs 屈服（235/345 MPa），SF = 屈服/vM_max；位移查量级、方向、变形形状。
7. **验证闭环**：求解后自动读 Max 位移/vM 对比手算，容差内打印 BENCH_PASS/BENCH_FAIL。
8. **网格前验 CAD**：modeling.md §3.5 测体积/质心（不符 = 布尔未融合或尺寸错）。

## 9. FEA 交付自检清单

- [ ] 手算解析解（公式+数值），FEA/手算比值 0.9~1.4（含剪切/圣维南余量）
- [ ] 材料 E/ν/ρ 已核对（库 Steel 或自定义）
- [ ] 网格 CTETRA(10)、尺寸依据（壁厚比例）、节点/单元数已打印
- [ ] BC 意图命名（FixedEnd/TipLoad 等），载荷大小/方向/单位（N）明确
- [ ] 求解 log EXIT(0)、无 FATAL；f06 无奇异警告
- [ ] 输出请求已挂（否则 op2 空）；读回 Max 位移/vM 与手算对照
- [ ] 报告注明应力峰值是否位于约束边角（圣维南区）
- [ ] .fem/.sim/.op2 全部落盘工程目录
