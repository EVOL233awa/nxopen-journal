# 逆向重建域（无特征实体 → 可分析/可出图模型）

> 适用：只给一个无特征历史的实体（单特征或导入体），需要重建参数化/可编辑模型并量化精度。
> 前置：`modeling.md`（拉伸/放样/布尔/孔）与 `fea.md`（验证网格）。

## 1. 流程（判据先行）

1. **先定坐标系再测量**：用零件的主承载方向、回转/对称轴和安装面法向建立自然系。所有截面、孔位、出图共用同一变换；存储系与自然系不一致时，只在读/写边界处变换一次。
2. **先转图纸形态，再按正向路线重建**：垂直主轴切截面，间隔按最小结构特征尺寸定并保证每个结构分界都有一刀；另沿其余两轴切过凸台、支臂、凹槽等局部结构。在截面上量取闭合轮廓、孔位与深度，不要靠三角网格“看形猜结构”。截面曲线直接用 §2.1 的 UF 批量接口从 B-rep 取，不要手工在视图上描。
3. **每层一个闭合草图 → 拉伸**：一个闭合环写成一条闭合样条（光滑轮廓）或精确直线/圆弧（机加工平面、棱边、圆角凸台），沿轴拉伸到下一结构分界并布尔合并。顺序按承力路径：主承载基体 → 次级承力结构（筋、凸台、支臂、回转体）→ 局部细节。
4. **孔系与凹陷作为切除特征后置**：通孔、锥孔、沉孔、减重凹槽、通槽在实体合并后逐个切除，按截面量取的圆心、半径、深度和起止面建工具体，两端各穿出 1–2 mm。
5. **校核顺序**：体积 → 包围盒 → 双向偏差 → 分区域偏差。任一步不达标先回退结构判断，不要靠倒角/拟合修补；按区域逐轮修，每轮只改一个热点并复测，整模重拟合会把已达标区域带偏。

## 2. 草图—拉伸做法

- 截面曲线直接建在对应高度的基准平面上（`offset` 到 z），沿 +Z 拉伸；批处理下不建 Sketch 对象也能得到与“草图—拉伸”相同的直纹面。
- 闭合样条用 `ufs.Curve.CreateSplineThruPts`（degree 3、`periodicity=0` 开曲线），点序周向一致，首点重复闭合；接缝放在曲率最大处，避免样条在长直段中点起笔。截面折线先做 5 点加权平滑（1-2-3-2-1）再隔点抽稀，抑制采样锯齿；平滑后仍有尖角的位置是真棱线，改用精确直线/圆弧。
- **闭合样条只用开曲线**（`periodicity=0`）；`periodicity=1` 在 NX12 批处理无返回并挂起。
- 矩形/圆角凸台用精确曲线（4 条直线、4 条直线 + 2 个 90° 圆弧），不要让样条穿过 4 个角点（会变成圆角鼓包）。
- 变截面凸台（根部与端部轮廓不同）用两张正交视图的轮廓各拉伸一次，先 `Intersect` 再并入主体；单轮廓拉伸只能得到等截面，逐层截面拉伸会把凸台切成台阶。
- 拔模：`ExtrudeBuilder.Draft` 是 `MultiDraft`；`DraftOption = SimpleDraftSimpleDraftType.SimpleFromStart`，`DraftAngle.RightHandSide = "<deg>"`；正值向拉伸端收缩。锥孔切除用带拔模的拉伸，不用圆锥体拼；锥度从多个截面的圆心与半径对轴向坐标线性拟合，再沿拟合轴起刀，不要拿单个截面的圆直接拉直孔。
- 合并相邻实体时给 0.5–1 mm 重叠；合并后断言体数 = 1 且体积单调增加。

### 2.1 从 B-rep 批量取截面曲线（UF，NX12 已验证）

```python
ufs = NXOpen.UF.UFSession.GetUFSession()
# wp = 工作部件；body = 待切实体（NXOpen.Body）

# 截面网格的基准面（位置 + 法向）；平行截面按它的法向等距展开
plane = wp.Planes.CreatePlane(NXOpen.Point3d(0.0, 0.0, 0.0),
                              NXOpen.Vector3d(0.0, 0.0, 1.0),
                              NXOpen.SmartObject.UpdateOption.WithinModeling)

fd = NXOpen.UF.ModlCurveFitData_Struct()
fd.CurveFitMethod = 0          # 0=cubic 1=quintic 2=advanced
fd.MaximumDegree = 3
fd.MaximumSegments = 1

gd = NXOpen.UF.Curve.SectionGeneralData()
gd.Objects = [body.Tag]        # 体/面/曲线 tag 列表（int，不是 NXObject）
gd.NumObjects = 1
gd.Associate = 1               # 1=关联特征；0=非关联曲线组
gd.Grouping = 0
gd.JoinType = 0                # 0=不连接；1/2/3=三次/一般/五次样条连接
gd.Tolerance = 0.01            # 部件单位
gd.CurveFitData = fd

pd = NXOpen.UF.Curve.SectionParallelData()
pd.BasePlane = plane.Tag
pd.StepDistance = 5.0
pd.StartDistance = 2.5
pd.EndDistance = 17.5

feat_tag = ufs.Curve.SectionFromParallelPlanes(gd, pd)
n, curves = ufs.Curve.AskFeatureCurves(feat_tag)   # n=15，curves=tag 列表

# 采样：t 归一化 0..1，返回元组第 0 项是点
for ct in curves:
    for i in range(33):
        p = ufs.ModlGeneral.AskCurveProps(ct, i / 32.0)[0]
```

- 结构体是 `NXOpen.UF.Curve.SectionGeneralData()` / `SectionPlanesData()` / `SectionParallelData()`，字段 **PascalCase**（`Objects`/`NumObjects`/`Associate`/`JoinType`/`Tolerance`/`BasePlane`/`StepDistance`/`StartDistance`/`EndDistance`）；曲线拟合参数用 `NXOpen.UF.ModlCurveFitData_Struct()`，不是 `Curve.CurveFitData`。
- 单平面：`pd = NXOpen.UF.Curve.SectionPlanesData()`、`pd.Planes=[plane.Tag]`、`pd.NumPlanes=1` → `ufs.Curve.SectionFromPlanes(gd, pd)`。`Planes` 是数组，可一次传多个任意方向的基准面（本机只验证单面）。
- **平行面位置语义**：截面在基准面法向上按 `k*StepDistance` 等距生成，再用 `[StartDistance, EndDistance]` 和实体范围裁剪；`StartDistance` **不是**第一张面的偏移。请求 2.5–17.5、步长 5 得到 **5 / 10 / 15** 三张，不是 2.5/7.5/12.5/17.5。
- 返回值：`Associate=1` 返回特征 tag，`FeatureType == "SECTION_CURVES"`；`AskFeatureCurves` 返回 `(n, [curve tags])`。`Associate=0` 按头文件返回曲线组 tag（未验证返回形态）。
- 截面曲线在**绝对坐标系**；直线段是 line（对象类型 3），圆柱孔截面是 **spline（类型 5）不是 circle**——闭合性用首尾采样点距离判，不要按对象类型认圆。
- 采样函数在 `ufs.ModlGeneral.AskCurveProps`（不在 `ufs.Modl`）；返回 `(point, tangent, p_norm, b_norm, torsion, radius_of_curvature)`。孔截面采样点到孔心距离应为常数（r=5.0000、首尾闭合）。
- 取完截面按 §2 平滑重建：直线/圆弧段保留精确曲线，样条段做 1-2-3-2-1 平滑后隔点抽稀；每层截面用同一条闭合样条，接缝放在曲率最大处。

## 3. 分层重建的布尔路线

按“切除 → 合并 → 圆角”的顺序走：

1. **切除在子体上做完再合并**：邻体边界贴近切除面时，合并会被判成相切求交而拒绝。
2. **合并前裁掉与邻体重叠的冗余块**：残留薄片（<1 mm）会让合并结果非流形；重叠区给 0.5–1 mm。
3. **圆角放到全部分层合并之后**：在孤立子体上倒圆会改变后续合并的终止边，导致 intersection gap。
4. **每刀后断言体积下降、合并后断言体数 = 1**；体数仍为 1 但特征没切掉时，检查目标体/工具体顺序与工具体是否穿过。

约束：
- 合并报 intersection gaps：截面折线过多时改一条光滑闭合样条，或把折线减到只保留棱线点。
- 合并报 zero wall thickness：两实体共面，重叠 0.5–1 mm，或把人工封口面错开 0.1 mm。
- 人工封口面擦到相邻薄壁：用覆盖式矩形从主体减去封口区域，再把臂/凸台并进来。
- 倒圆报 `Unable to terminate the blend`：轮廓含凹角或薄壁（≤1.5 mm），跳过该圆角并在交付说明列为简化。
- 轴承孔/通孔内留“塞子”：圆柱切除参数把半径当直径，用 `2*R`，切完用体积差验证。
- 凹槽“有形状没凹下去”：切除工具体起点在实体外侧，检查起止高度是否跨过目标面。
- 视图出现密集纵向面边界：多段线/放样残留，改用单条样条闭合草图拉伸。

## 4. 精度验证（双向，必须两个方向都算）

- 引擎：二进制 STL 读三角面片 → KD-tree 候选 → 点到三角形精确投影（不要用顶点最近点，误差随网格密度漂移）。
- 采样：每个三角面按面积采样（重心坐标），重建网格用顶点 + 面心加密。
- 输出：`mean / RMS / P50 / P95 / max`，两个方向分别统计；再按结构区域（主承载区、连接区、回转区、局部凸台）拆分定位系统误差。
- 合格判据（铸/锻件逆向）：RMS ≤ 1% 最大外形；P95 ≤ 2%；体积差 ≤ 5%；最大偏差只出现在未倒圆过渡或拟合曲面边缘。
- 偏差热点集中在同一区域 → 结构判断错误；分散且小 → 曲面近似误差，可接受。

## 5. 重建件与原始件的分工

- **FEA**：两件用同一网格尺寸、同一材料、同一载荷，结果差异即几何误差带来的误差带。
- **出图**：原始件用于外形/孔系图（轮廓准确）；重建件出“逆向成果图”，技术要求注明简化项与偏差统计。
- **出图前隐藏全部独立构造曲线/点**：拉伸与切除用的样条、圆弧、点不属于实体，Drafting 视图会把它们当可见几何投影成游离短线/悬空椭圆。重建收尾遍历 `part.Curves`/`part.Points` 逐个 `Blank()`；只隐藏、不删除，避免破坏特征引用。

## 6. 与出图的坐标衔接

- 存储系与自然系相差 45° 时，**不要旋转实体**（批处理下 `UF_MODL_transform_entities` 静默不生效，Drafting 视图拒绝 `View.Rotate`）；改用自定义模型视图，见 `gb-drawing.md` §非轴对齐零件出图。

## 7. 重建件的后续修改

- 按序号定位拉伸：遍历 `part.Features`，按 `FeatureType == "EXTRUDE"` 过滤后计数，与界面特征树的拉伸序号一致（重排过的树用 `Timestamp` 复核）；用体积/包围盒变化确认目标。
- NX12 的 `UF.Modl` 无 delete/suppress，`FeatureCollection` 只有 `SuppressFeatures`/`UnsuppressFeatures`；不要写 `ufs.Modl.DeleteFeature`。删除特征走 NX 界面，脚本只做枚举、`GetAllPartFeaturesWithAlerts()` 校核与复测。
