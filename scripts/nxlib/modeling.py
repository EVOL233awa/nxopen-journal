# -*- coding: utf-8 -*-
"""nxlib.modeling —— 建模配方标准层（权威来源：01/14/33 号已验收用例逐字平移）。

约定：
  - 第一个参数一律 wp（工作部件）；
  - 长度/距离以表达式字符串传入（RightHandSide 口径，已实测；float 未经批处理验证）；
  - 所有 builder 提交后立即 Destroy；
  - 失败就地抛异常，由 testing.stage 捕获。
"""
import math

import NXOpen
import NXOpen.Features
import NXOpen.UF

NULL = NXOpen.NXObject.Null
VIEW_REORIENT_FALSE = NXOpen.Sketch.ViewReorient.FalseValue


def ufs():
    return NXOpen.UF.UFSession.GetUFSession()


# ---------------------------------------------------------------- 表达式

def expressions(wp, pairs, unit_name="Length"):
    """pairs: [(名, 值)] → {名: Expression}（01 号口径）。

    unit_name: "Length"（默认）或 "Angle"。角度/弧度表达式必须传 "Angle"，
    否则量纲按长度建，写 RightHandSide 时数值被当成 mm 解释。
    """
    unit = wp.UnitCollection.GetBase(unit_name)
    out = {}
    for n, v in pairs:
        out[n] = wp.Expressions.CreateSystemExpressionWithUnits(n + " = " + str(v), unit)
    return out


# ---------------------------------------------------------------- 体素与查询

def block(wp, origin, lx, ly, lz):
    """SetOriginAndLengths 建块（14 号口径）；origin 必须是 NXOpen.Point3d
    （SetOriginAndLengths 不收 tuple），长度用表达式字符串（RightHandSide 口径）。"""
    bb = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    bb.SetOriginAndLengths(origin, lx, ly, lz)
    f = bb.CommitFeature()
    bb.Destroy()
    return f


def bodies(wp):
    """工作部件全部实体（14 号口径）。"""
    return [b for b in wp.Bodies]


def body_box(wp, body):
    """面遍历包盒 [xmin,ymin,zmin,xmax,ymax,zmax]（01 号口径）。

    这是 `AskFaceData` 的**控制点盒**：环面/B 曲面的控制点会伸到真实曲面
    之外，不能当精确包盒或 G4 包盒读数（那一档用 `audit.envelope` 的默认
    STL 三角顶点口径，底层是 `measure.mesh_bbox`）。
    """
    u = ufs()
    box = [1e18, 1e18, 1e18, -1e18, -1e18, -1e18]
    for f in body.GetFaces():
        fb = u.Modeling.AskFaceData(f.Tag)[3]
        for i in range(3):
            box[i] = min(box[i], fb[i])
            box[i + 3] = max(box[i + 3], fb[i + 3])
    return box


def planar_faces(wp, body, pred):
    """按法线向量过滤平面的全部面（15 号口径，ftype 22；pred 接收法线三元组）。"""
    u = ufs()
    out = []
    for f in body.GetFaces():
        d = u.Modeling.AskFaceData(f.Tag)
        if d[0] == 22 and pred(d[2]):
            out.append(f)
    return out


def face_collector(wp, faces):
    """SC 面收集器（CreateRuleFaceDumb，15 号口径）。调用方负责 Destroy。"""
    col = wp.ScCollectors.CreateCollector()
    col.ReplaceRules([wp.ScRuleFactory.CreateRuleFaceDumb(list(faces))], False)
    return col


def volume(wp, body):
    """质量属性体积 mm³（14/15 号口径）。"""
    uc = wp.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
    return wp.MeasureManager.NewMassProperties(units, [0.99], [body]).Volume


def centroid(wp, body):
    """质量属性质心 (X, Y, Z)（22 号口径）。"""
    uc = wp.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter", "Newton")]
    c = wp.MeasureManager.NewMassProperties(units, [0.99], [body]).Centroid
    return (c.X, c.Y, c.Z)


def find_face(wp, body, point, want_normal, axis=2):
    """找法线 axis 分量≈want_normal、离 point 最近的平面（ftype 22，01 号口径）。

    axis=0/1/2 对应法线的 X/Y/Z 分量（02 号沿 X 打孔时传 axis=0）。
    """
    u = ufs()
    best = None
    best_dist = 1e18
    for face in body.GetFaces():
        data = u.Modeling.AskFaceData(face.Tag)
        ftype, fp, fdir = data[0], data[1], data[2]
        if ftype != 22:
            continue
        if abs(fdir[axis] - want_normal) > 0.01:
            continue
        dist = abs((point.X - fp[0]) * fdir[0] + (point.Y - fp[1]) * fdir[1] + (point.Z - fp[2]) * fdir[2])
        if dist < best_dist:
            best_dist = dist
            best = face
    return best


# ---------------------------------------------------------------- 草图与拉伸

def make_sketch(wp, curves, reference_curves=None):
    """草图 + 自动约束 + 自动尺寸；reference_curves 转构造线并全固定（01 号口径）。

    ⚠ 这里的 AutoDimension 实际不产生任何尺寸：AutoConstrain 已经把简单轮廓
    标成完全约束且不产生表达式（实测圆 3→0 DOF、表达式表为空）。需要尺寸驱动
    的草图用 make_sketch_dims（不跑 AutoConstrain）。
    """
    sib = wp.Sketches.CreateNewSketchInPlaceBuilder(NXOpen.Sketch.Null)
    origin_point = wp.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0))
    sib.SketchOrigin = origin_point
    sib.Commit()
    sketch = sib.GetCommittedObjects()[0]
    sib.Destroy()
    sketch.Activate(VIEW_REORIENT_FALSE)
    sketch.AddGeometry(
        NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
        NXOpen.Sketch.AddEllipseOption.TreatAsEllipse,
        curves,
    )
    if reference_curves:
        for rc in reference_curves:
            sketch.AddGeometry(rc)
    ac = wp.Sketches.CreateAutoConstrainBuilder()
    ac.Commit()
    ac.Destroy()
    ad = wp.Sketches.CreateAutoDimensionBuilder()
    ad.SelectionObject.SetArray(curves)
    ad.SetRules([
        NXOpen.Sketch.AutoDimensioningRule.Length,
        NXOpen.Sketch.AutoDimensioningRule.Symmetric,
    ])
    ad.DimensionType = NXOpen.SketchAutoDimensionBuilder.DimType.Driving
    ad.Commit()
    ad.Destroy()
    # 孔中心十字线转参考（构造）线：可见但不参与轮廓（01 号口径）
    if reference_curves:
        cb = wp.Sketches.CreateConvertToFromReferenceBuilder()
        for rc in reference_curves:
            cb.InputObjects.Add(rc)
        cb.OutputState = NXOpen.ConvertToFromReferenceBuilder.OutputType.Reference
        cb.Commit()
        cb.Destroy()
        for rc in reference_curves:
            try:
                sketch.CreateFullyFixedConstraints(
                    NXOpen.Sketch.ConstraintGeometry(rc, NXOpen.Sketch.ConstraintPointType.NotSet, 0)
                )
            except Exception as exc:
                print("FIX_RC_FAIL " + str(exc))
    sketch.Deactivate(VIEW_REORIENT_FALSE, NXOpen.Sketch.UpdateLevel.Model)
    return sketch


def make_sketch_dims(wp, curves, links=(), rules=None):
    """草图 + AutoDimension 驱动尺寸，并把尺寸改指命名表达式。

    links: [(数值, "表达式右端"), ...]；对每个自动生成的尺寸，按
    float(RightHandSide) 与数值匹配（1e-6）后改指。返回 (sketch, 改指数)。

    唯一的实测前提：**不能先跑 AutoConstrain** —— 它会把简单轮廓标成完全
    约束且不产生表达式，AutoDimension 随后一个尺寸都不出（受控实验
    scripts/tests/37_sketch_autodim_param.py）。GetStatus 只用来读 dof，
    少调它不影响出尺寸。

    只用于简单轮廓（圆/矩形/扇形/台阶轮廓）；实测轮廓（短弧+倒角+偏移线）
    开了自动尺寸会被拉变形，仍走 make_sketch 的固定约束路线。
    """
    sib = wp.Sketches.CreateNewSketchInPlaceBuilder(NXOpen.Sketch.Null)
    sib.SketchOrigin = wp.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0))
    sib.Commit()
    sketch = sib.GetCommittedObjects()[0]
    sib.Destroy()
    sketch.Activate(VIEW_REORIENT_FALSE)
    sketch.AddGeometry(
        NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
        NXOpen.Sketch.AddEllipseOption.TreatAsEllipse,
        curves,
    )
    sketch.GetStatus()
    ad = wp.Sketches.CreateAutoDimensionBuilder()
    ad.SelectionObject.SetArray(curves)
    ad.SetRules(rules or [
        NXOpen.Sketch.AutoDimensioningRule.Length,
        NXOpen.Sketch.AutoDimensioningRule.Symmetric,
    ])
    ad.DimensionType = NXOpen.SketchAutoDimensionBuilder.DimType.Driving
    ad.Commit()
    ad.Destroy()
    sketch.GetStatus()
    linked = 0
    for e in sketch.GetAllExpressions():
        try:
            val = float(e.RightHandSide)
        except Exception:
            continue
        for target, rhs in links:
            if abs(val - float(target)) < 1e-6:
                e.RightHandSide = rhs
                linked += 1
                break
    sketch.LocalUpdate()
    sketch.Deactivate(VIEW_REORIENT_FALSE, NXOpen.Sketch.UpdateLevel.Model)
    return sketch, linked


def extrude(wp, curves, distance_expr):
    """dumb 曲线截面沿 +Z 拉伸 distance_expr（01 号口径）。"""
    section = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
    rule = wp.ScRuleFactory.CreateRuleCurveDumb(curves)
    section.AddToSection(
        [rule], NULL, NULL, NULL,
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Section.Mode.Create, False,
    )
    builder = wp.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    builder.Section = section
    direction = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 0.0, 1.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling,
    )
    builder.Direction = direction
    builder.Limits.StartExtend.Value.RightHandSide = "0"
    builder.Limits.EndExtend.Value.RightHandSide = distance_expr
    feat = builder.CommitFeature()
    builder.Destroy()
    return feat


# ---------------------------------------------------------------- 孔

def add_thru_hole_faces(wp, hole_pt, top_face, bottom_face, diam_expr):
    """以给定孔位与起止面打通孔（01 号 add_hole 的轴无关内核，02 号沿 X 复用）。"""
    builder = wp.Features.CreateHoleFeatureBuilder(NXOpen.Features.Feature.Null)
    builder.Subtype = NXOpen.Features.HoleFeatureBuilder.HoleSubtype.Simple
    builder.SetSimpleHole(hole_pt, False, top_face, diam_expr)
    builder.SetThruFace(bottom_face)
    builder.HoleLocation = hole_pt
    feat = builder.CommitFeature()
    builder.Destroy()
    return feat


def add_hole(wp, body, x, y, z_top, diam_expr):
    """简单通孔：top=离 (0,0,z_top) 最近的 z+ 平面，bottom=z- 平面（01 号口径，z_top 参数化）。"""
    top = find_face(wp, body, NXOpen.Point3d(0.0, 0.0, z_top), 1.0)
    bottom = find_face(wp, body, NXOpen.Point3d(0.0, 0.0, 0.0), -1.0)
    return add_thru_hole_faces(wp, NXOpen.Point3d(x, y, z_top), top, bottom, diam_expr)


def find_planar_face(body, point, want_normal_z):
    """找法线 z 分量≈want_normal_z、离 point 最近的平面（20/21/31 号口径；
    与 find_face 的区别：不吃 wp、只按 Z 过滤、face 锚点在孔位本身）。"""
    u = ufs()
    best = None
    best_dist = 1e18
    for face in body.GetFaces():
        data = u.Modeling.AskFaceData(face.Tag)
        ftype, fp, fdir = data[0], data[1], data[2]
        if ftype != 22:
            continue
        if abs(fdir[2] - want_normal_z) > 0.01:
            continue
        dist = abs((point.X - fp[0]) * fdir[0] + (point.Y - fp[1]) * fdir[1]
                   + (point.Z - fp[2]) * fdir[2])
        if dist < best_dist:
            best_dist = dist
            best = face
    return best


def add_thru_hole(wp, body, x, y, z_top, expr_name):
    """通孔，起止面按孔位 (x, y) 就近查找（20 号口径；add_hole 锚 (0,0)）。"""
    top = find_planar_face(body, NXOpen.Point3d(x, y, z_top), 1.0)
    bottom = find_planar_face(body, NXOpen.Point3d(x, y, 0.0), -1.0)
    return add_thru_hole_faces(wp, NXOpen.Point3d(x, y, z_top), top, bottom, expr_name)


ARC_TOL = 1e-3


def face_radius(face):
    """圆柱面半径（AskFaceData[4] 取绝对值；异常返回 -1.0，27 号口径）。"""
    try:
        return abs(ufs().Modeling.AskFaceData(face.Tag)[4])
    except Exception:
        return -1.0


def classify_edges(body):
    """按 (半径, 边, p1, p2, kind) 分类圆柱面边（27 号口径）。

    kind='arc' 部分圆 / 'circle' 全圆（p1==p2==圆心）/ 'line' 直边。
    只按半径找候选会漏：倒圆面同样带 R10 直边——这是 27 号钉死的坑。
    """
    out = []
    for face in body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            continue
        r = face_radius(face)
        for e in face.GetEdges():
            try:
                p1, p2 = e.GetVertices()
            except Exception:
                continue
            et = e.SolidEdgeType
            if et == NXOpen.Edge.EdgeType.Circular:
                same = (abs(p1.X - p2.X) < ARC_TOL and abs(p1.Y - p2.Y) < ARC_TOL
                        and abs(p1.Z - p2.Z) < ARC_TOL)
                kind = "circle" if same else "arc"
            elif et == NXOpen.Edge.EdgeType.Linear:
                kind = "line"
            else:
                continue
            out.append((r, e, p1, p2, kind))
    return out


# ---------------------------------------------------------------- 倒圆

def blend_on_faces(wp, faces, radius):
    """对圆柱面链倒圆（CreateRuleEdgeFace，01 号 s3 口径）。"""
    rule = wp.ScRuleFactory.CreateRuleEdgeFace(faces)
    collector = wp.ScCollectors.CreateCollector()
    collector.ReplaceRules([rule], False)
    builder = wp.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    builder.AddChainset(collector, str(radius))
    feat = builder.CommitFeature()
    builder.Destroy()
    collector.Destroy()
    return feat


def blend_on_edges(wp, edges, radius):
    """对边链倒圆（CreateRuleEdgeDumb，01 号 s5 口径）。"""
    rule = wp.ScRuleFactory.CreateRuleEdgeDumb(edges)
    collector = wp.ScCollectors.CreateCollector()
    collector.ReplaceRules([rule], False)
    builder = wp.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    builder.AddChainset(collector, str(radius))
    feat = builder.CommitFeature()
    builder.Destroy()
    collector.Destroy()
    return feat


def face_blend(wp, face_a, face_b, radius, reverse_a=False, reverse_b=False):
    """两支撑面 FaceBlend（BlendTwoFace）。

    支撑面可以是平面、圆柱、圆锥、环面或 B 曲面，但必须是完整解析面且
    非相切；相切缝，或**支撑面宽 < R** 的窄条，会报
    `Radius is too large/small`（实测支撑宽 1.6 / R=1.6 可倒、1.5 / R=1.6
    报错，没有 0.5 mm 余量；`structures.fillet_feasible` 同判据）。
    凸缘/凹口的两面法向组合不固定，未知时用 `face_blend_edge` 自动试。
    """
    builder = wp.Features.CreateFaceBlendBuilder(NXOpen.Features.Feature.Null)
    fbt = NXOpen.Features.FaceBlendBuilder
    builder.FaceBlendDefineType = fbt.DefiningType.BlendTwoFace
    builder.FirstFaceCollector = face_collector(wp, [face_a])
    builder.SecondFaceCollector = face_collector(wp, [face_b])
    builder.ReverseFirstFaceNormal = reverse_a
    builder.ReverseSecondFaceNormal = reverse_b
    builder.CrossSectionType = fbt.CrossSectionOption.Circular
    builder.CircularCrossSection.SetRadius(repr(radius))
    try:
        feat = builder.CommitFeature()
    finally:
        builder.Destroy()
    return feat


def face_blend_edge(wp, edge, radius,
                    orders=((True, True), (False, False),
                            (True, False), (False, True)), trace=None):
    """对一条边的两邻面做 FaceBlend，按 orders 试法向组合。

    失败组合回滚到自己的 undo mark；成功即返回 `(feature, (rev_a, rev_b))`。
    `trace` 是可选 list，逐次追加 `(comb, ok, error)`，用于记录哪组法向成功。
    边缘在成功提交后失效，调用方应按几何重新找下一条边，不要复用 wrapper。
    """
    faces = list(edge.GetFaces())
    if len(faces) != 2:
        raise ValueError("face_blend_edge needs a two-face edge, got %d" %
                         len(faces))
    session = NXOpen.Session.GetSession()
    last = None
    for rev_a, rev_b in orders:
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible,
                                   "face_blend_edge")
        try:
            feat = face_blend(wp, faces[0], faces[1], radius,
                              rev_a, rev_b)
            if trace is not None:
                trace.append(((rev_a, rev_b), True, None))
            session.DeleteUndoMark(mark, None)
            return feat, (rev_a, rev_b)
        except Exception as exc:
            last = exc
            if trace is not None:
                trace.append(((rev_a, rev_b), False, str(exc)[:300]))
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
    raise last if last is not None else RuntimeError("no blend attempt")


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit3(a):
    n = math.sqrt(_dot3(a, a))
    return None if n < 1e-9 else (a[0] / n, a[1] / n, a[2] / n)


def _extrude_along(wp, curves, direction, distance, start, help_pt):
    """沿任意方向拉伸（ExtrudeBuilder；direction 为三元组）。"""
    section = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
    rule = wp.ScRuleFactory.CreateRuleCurveDumb(curves)
    section.AddToSection([rule], NULL, NULL, NULL, help_pt,
                         NXOpen.Section.Mode.Create, False)
    builder = wp.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    builder.Section = section
    builder.Direction = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(float(direction[0]), float(direction[1]),
                        float(direction[2])),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    builder.Limits.StartExtend.Value.RightHandSide = start
    builder.Limits.EndExtend.Value.RightHandSide = distance
    feat = builder.CommitFeature()
    builder.Destroy()
    return feat


def edge_is_concave(edge, trace=None):
    """两邻面都是平面时，用“面在对面哪一侧”判凸凹。

    凸边：每个邻面的内侧都落在另一个面的材料侧（法向负侧）；凹边：都落在
    空侧（正侧）。两面不共点、法向不沿边、符号不一致时返回 None。只对平面
    邻边有效；曲面邻边直接返回 None。
    """
    u = ufs()
    vs = edge.GetVertices()
    fs = edge.GetFaces()
    if len(vs) != 2 or len(fs) != 2:
        return None
    p0 = (vs[0].X, vs[0].Y, vs[0].Z)
    fd = []
    for f in fs:
        try:
            d = u.Modeling.AskFaceData(f.Tag)
        except Exception:
            return None
        if int(d[0]) != 22:
            return None
        fd.append(d)
    n = [_unit3((d[2][0], d[2][1], d[2][2])) for d in fd]
    if n[0] is None or n[1] is None:
        return None
    side = []
    for i in (0, 1):
        b = fd[i][3]
        c = ((b[0] + b[3]) * 0.5, (b[1] + b[4]) * 0.5,
             (b[2] + b[5]) * 0.5)
        t = _dot3(_sub3(c, p0), n[i])
        c = (c[0] - t * n[i][0], c[1] - t * n[i][1], c[2] - t * n[i][2])
        side.append(_dot3(_sub3(c, p0), n[1 - i]))
    if side[0] < -1e-6 and side[1] < -1e-6:
        return False
    if side[0] > 1e-6 and side[1] > 1e-6:
        return True
    if trace is not None:
        trace.append("convexity ambiguous %.3f %.3f" % (side[0], side[1]))
    return None


def roll_edge(wp, edge, radius, min_len=None, ext=None, add=None, trace=None):
    """开放链圆角刀：截面 = 角区 − 切圆，沿边拉伸（凸边减、凹边加）。

    `EdgeBlend` 在开放链上不必然失败（实测 `Unable to terminate the blend
    faces` 由半径大于支撑面宽触发，与"边不闭合"无因果）；用刀的理由是**每
    段独立提交、失败即可回滚**，且能按几何重找下一条边：每条边生成一把截面
    垂直于边的刀，拉伸到终点外 `ee`（起点与边端点平齐，穿出起点会切掉顶点
    邻边该留的料）。`add=True` 生成凹边一侧的刀、`False` 凸边；缺省按
    `edge_is_concave` 自动判。两面不是平面、夹角不在 30°–150°、边长不足
    `4*radius`、切点退化时返回 None，原因写进 `trace`（若给）。返回
    `(feature, 预期体积 mm3)`，调用方对 `feature.GetBodies()[0]` 做一次布尔
    （凸 Subtract / 凹 Unite）。
    """
    u = ufs()
    vs = edge.GetVertices()
    if len(vs) != 2:
        if trace is not None:
            trace.append("vertices %d" % len(vs))
        return None
    p0 = (vs[0].X, vs[0].Y, vs[0].Z)
    p1 = (vs[1].X, vs[1].Y, vs[1].Z)
    dd = _sub3(p1, p0)
    ln = math.sqrt(_dot3(dd, dd))
    if ln < (4.0 * radius if min_len is None else min_len):
        if trace is not None:
            trace.append("short %.2f" % ln)
        return None
    dv = _unit3(dd)
    nrm = []
    for f in edge.GetFaces():
        try:
            fd = u.Modeling.AskFaceData(f.Tag)
        except Exception:
            if trace is not None:
                trace.append("no face data")
            return None
        if int(fd[0]) != 22:
            if trace is not None:
                trace.append("face type %d" % int(fd[0]))
            return None
        nv = _unit3((fd[2][0], fd[2][1], fd[2][2]))
        if nv is None or abs(_dot3(nv, dv)) > 0.5:
            if trace is not None:
                trace.append("normal along edge")
            return None
        nrm.append(nv)
    if len(nrm) != 2:
        if trace is not None:
            trace.append("faces %d" % len(nrm))
        return None
    ang = math.degrees(math.acos(max(-1.0, min(1.0, _dot3(nrm[0], nrm[1])))))
    if not (30.0 < ang < 150.0):
        if trace is not None:
            trace.append("angle %.1f" % ang)
        return None
    if add is None:
        add = edge_is_concave(edge, trace)
        if add is None:
            return None
    sgn = 1.0 if add else -1.0
    e1 = _unit3((sgn * nrm[0][0], sgn * nrm[0][1], sgn * nrm[0][2]))
    e2 = _unit3(_cross3(dv, e1))
    uu = []
    for nv in nrm:
        wi = (sgn * nv[0], sgn * nv[1], sgn * nv[2])
        uu.append((_dot3(wi, e1), _dot3(wi, e2)))
    det = uu[0][0] * uu[1][1] - uu[0][1] * uu[1][0]
    if abs(det) < 0.2:
        if trace is not None:
            trace.append("det %.2f" % det)
        return None
    ox = (radius * uu[1][1] - radius * uu[0][1]) / det
    oy = (uu[0][0] * radius - uu[1][0] * radius) / det
    tt = [(ox - radius * uu[0][0], oy - radius * uu[0][1]),
          (ox - radius * uu[1][0], oy - radius * uu[1][1])]
    near = min(math.hypot(*q) for q in tt)
    far = max(math.hypot(*q) for q in tt)
    if near < 0.3 * radius or far > 6.0 * radius:
        if trace is not None:
            trace.append("tangent near %.2f far %.2f" % (near, far))
        return None
    r0 = ((tt[0][0] - ox) / radius, (tt[0][1] - oy) / radius)
    r1 = ((tt[1][0] - ox) / radius, (tt[1][1] - oy) / radius)
    a0 = math.atan2(r0[1], r0[0])
    a1 = math.atan2(r1[1], r1[0])
    da = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
    bis = (-(uu[0][0] + uu[1][0]), -(uu[0][1] + uu[1][1]))
    mid = (ox + radius * math.cos(a0 + 0.5 * da),
           oy + radius * math.sin(a0 + 0.5 * da))
    if mid[0] * bis[0] + mid[1] * bis[1] <= ox * bis[0] + oy * bis[1]:
        da -= 2.0 * math.pi if da > 0 else -2.0 * math.pi
    bd = _unit3((-bis[0], -bis[1], 0.0))
    # 角区 − 切圆：两条直边贴两个面，滚圆段用精确圆弧。切点不回缩、
    # 只在角点外偏 0.1：切点附近回缩再用弦接圆弧会切进面内，留下
    # 0.2–0.5 mm 的窄平台（面表多出一族偏 0.01–0.2 的平面）。
    skirt = 0.1
    c_out = (-skirt * bd[0], -skirt * bd[1])
    if da < 0.0:
        arc_a0, arc_a1 = a1, a1 - da
    else:
        arc_a0, arc_a1 = a0, a0 + da
    arc_p0 = (ox + radius * math.cos(arc_a0),
              oy + radius * math.sin(arc_a0))
    arc_p1 = (ox + radius * math.cos(arc_a1),
              oy + radius * math.sin(arc_a1))
    pts2 = [c_out, arc_p0]
    for j in range(1, 16):
        a = arc_a0 + (arc_a1 - arc_a0) * j / 16.0
        pts2.append((ox + radius * math.cos(a),
                     oy + radius * math.sin(a)))
    pts2.append(arc_p1)
    area = 0.0
    for i in range(len(pts2)):
        x0, y0 = pts2[i]
        x1, y1 = pts2[(i + 1) % len(pts2)]
        area += x0 * y1 - x1 * y0
    area = abs(0.5 * area)
    ee = min(0.8, 0.25 * ln) if ext is None else ext
    base = (p0[0] - dv[0] * ee, p0[1] - dv[1] * ee, p0[2] - dv[2] * ee)

    def to3(xy):
        return NXOpen.Point3d(
            base[0] + xy[0] * e1[0] + xy[1] * e2[0],
            base[1] + xy[0] * e1[1] + xy[1] * e2[1],
            base[2] + xy[0] * e1[2] + xy[1] * e2[2])

    q0 = to3(c_out)
    curves = [wp.Curves.CreateLine(q0, to3(arc_p0)),
              wp.Curves.CreateArc(to3((ox, oy)),
                                  NXOpen.Vector3d(*e1),
                                  NXOpen.Vector3d(*e2),
                                  float(radius), arc_a0, arc_a1),
              wp.Curves.CreateLine(to3(arc_p1), q0)]
    hp = to3((sum(p[0] for p in pts2) / len(pts2),
              sum(p[1] for p in pts2) / len(pts2)))
    try:
        feat = _extrude_along(wp, curves, dv, repr(ln + 2.0 * ee), repr(ee),
                              hp)
    except Exception:
        if trace is not None:
            trace.append("cutter extrude failed")
        return None
    return feat, area * ln


def apply_roll(wp, body, edge, radius, min_len=None, want_add=None):
    """用 `roll_edge` 滚一条边；凸/凹先判定，失败回滚。返回 (ok, body)。

    凸凹由 `edge_is_concave` 按两邻面的相互侧判定，不按体积猜：凹边上先减
    也会“成功”切掉一刀，体积没法区分凸边倒圆和凹边开槽。体积只作提交后的
    一致性检查；减/加的方向反了就把这次提交回滚，再按另一侧重试一次。
    每次尝试独立 undo mark；失败清账后从 `wp.Bodies` 重新取实体。已提交的
    滚圆不回滚（回滚后实体 out-of-date，后续布尔会报
    `Tool body completely outside target body`）。
    """
    session = NXOpen.Session.GetSession()
    if want_add is None:
        want_add = edge_is_concave(edge)
        if want_add is None:
            return False, body
    for add in (want_add, not want_add):
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Invisible, "roll_edge")
        res = roll_edge(wp, edge, radius, min_len=min_len, add=add)
        if res is None:
            session.DeleteUndoMark(mark, None)
            return False, body
        feat, exp = res
        v0 = volume(wp, body)
        try:
            tools = feat.GetBodies()
            if len(tools) != 1:
                raise RuntimeError("roll tool made %d bodies" % len(tools))
            op = (NXOpen.Features.Feature.BooleanType.Unite if add
                  else NXOpen.Features.Feature.BooleanType.Subtract)
            boolean(wp, body, tools[0], op)
            allb = bodies(wp)
            if len(allb) != 1:
                raise RuntimeError("roll left %d bodies" % len(allb))
            body = allb[0]
            dv = (volume(wp, body) - v0) if add else (v0 - volume(wp, body))
        except Exception:
            session.UndoToMark(mark, None)
            session.DeleteUndoMark(mark, None)
            session.UpdateManager.ClearErrorList()
            allb = bodies(wp)
            body = allb[0] if allb else body
            continue
        if 0.65 * exp <= dv <= 1.35 * exp:
            session.DeleteUndoMark(mark, None)
            return True, body
        session.UndoToMark(mark, None)
        session.DeleteUndoMark(mark, None)
        session.UpdateManager.ClearErrorList()
        allb = bodies(wp)
        body = allb[0] if allb else body
    return False, body


def unique_by_tag(objects):
    """按 Tag 去重保序（01 号 s5 口径）。"""
    seen = set()
    out = []
    for o in objects:
        if o.Tag not in seen:
            seen.add(o.Tag)
            out.append(o)
    return out


# ---------------------------------------------------------------- 阵列与布尔

def pattern_linear_rect(wp, feats, x_pitch, y_pitch, x_copies, y_copies):
    """矩形线性阵列（XY 方向 Pitch×NCopies，01 号 s4 口径；copies 是份数）。"""
    pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    pb.FeatureList.SetArray(feats)
    pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
    pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
    pd = pb.PatternService
    pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Linear
    rect = pd.RectangularDefinition
    rect.XDirection = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling,
    )
    rect.UseYDirectionToggle = True
    rect.YDirection = wp.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 1.0, 0.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling,
    )
    rect.XSpacing.SpaceType = NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Pitch
    rect.XSpacing.PitchDistance.RightHandSide = str(x_pitch)
    rect.XSpacing.NCopies.RightHandSide = str(x_copies)
    rect.YSpacing.SpaceType = NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Pitch
    rect.YSpacing.PitchDistance.RightHandSide = str(y_pitch)
    rect.YSpacing.NCopies.RightHandSide = str(y_copies)
    feat = pb.CommitFeature()
    pb.Destroy()
    return feat


def pattern_circular(wp, feats, axis_point, axis_vec, pitch_deg, copies):
    """圆形阵列（绕给定轴 Pitch 角×NCopies，02 号 s2 口径；copies 是份数）。"""
    axis = wp.Axes.CreateAxis(
        axis_point, axis_vec, NXOpen.SmartObject.UpdateOption.WithinModeling,
    )
    pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    pb.FeatureList.SetArray(feats)
    pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
    pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
    pd = pb.PatternService
    pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Circular
    cd = pd.CircularDefinition
    cd.RotationAxis = axis
    cd.AngularSpacing.SpaceType = NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Pitch
    cd.AngularSpacing.PitchAngle.RightHandSide = str(pitch_deg)
    cd.AngularSpacing.NCopies.RightHandSide = str(copies)
    feat = pb.CommitFeature()
    pb.Destroy()
    return feat


def mirror_feature(wp, feats, plane):
    """跨给定平面镜像特征（03 号 s2 口径；MirrorFeatureBuilder 是 NX12 镜像唯一通路）。"""
    mb = wp.Features.CreateMirrorFeatureBuilder(NXOpen.Features.Feature.Null)
    mb.FeatureSet.SetArray(feats)
    mb.PlaneOption = NXOpen.Features.MirrorFeatureBuilder.PlaneOptions.New
    mb.PlaneConstructor = plane
    feat = mb.CommitFeature()
    mb.Destroy()
    return feat


def create_plane(wp, origin, normal_vec):
    """过原点法向平面（03 号 s2 口径）。"""
    return wp.Planes.CreatePlane(
        origin, normal_vec, NXOpen.SmartObject.UpdateOption.WithinModeling,
    )


def boolean(wp, target, tool, op_type):
    """通用布尔：`Target`/`Tool`/`Operation`（02/03 号口径）。

    `BooleanBuilder` **没有** `SetBooleanOperationAndTarget`（那是
    BlockFeatureBuilder 的方法，14 号验证），照写报 AttributeError；两条路
    分工见 modeling.md §2.5。`BlockFeatureBuilder.BooleanOption` 静默失效，
    方块布尔要走 `SetBooleanOperationAndTarget`。
    """
    bb = wp.Features.CreateBooleanBuilder(NXOpen.Features.BooleanFeature.Null)
    bb.Target = target
    bb.Tool = tool
    bb.Operation = op_type
    feat = bb.CommitFeature()
    bb.Destroy()
    return feat


def unite_all(wp):
    """合并工作部件的前两个实体（02/03 号口径）。"""
    bs = bodies(wp)
    return boolean(wp, bs[0], bs[1], NXOpen.Features.Feature.BooleanType.Unite)


def revolve_rect_uf(wp, x0, x1, r0, r1):
    """矩形截面绕 X 轴 360° 旋转（UF Modl.CreateRevolved，02 号口径）。
    360° 可用（含落在轴上的边）；自交或越过旋转轴的剖面才报
    `Cannot create Swept geometry`（见建模文档 §1.14/§3.3）。"""
    u = ufs()
    curves = [
        wp.Curves.CreateLine(NXOpen.Point3d(x0, r0, 0.0), NXOpen.Point3d(x0, r1, 0.0)),
        wp.Curves.CreateLine(NXOpen.Point3d(x0, r1, 0.0), NXOpen.Point3d(x1, r1, 0.0)),
        wp.Curves.CreateLine(NXOpen.Point3d(x1, r1, 0.0), NXOpen.Point3d(x1, r0, 0.0)),
        wp.Curves.CreateLine(NXOpen.Point3d(x1, r0, 0.0), NXOpen.Point3d(x0, r0, 0.0)),
    ]
    feats = u.Modl.CreateRevolved(
        [c.Tag for c in curves], ["0.0", "360.0"], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
        NXOpen.UF.ModlFeatureSigns.NULLSIGN,
    )
    return feats[0]


def extrude_subtract(wp, target_body, curves, distance_expr):
    """拉伸曲线为工具体并对 target 做求差（01 号 s6 口径）。返回工具体特征。"""
    tool_feat = extrude(wp, curves, distance_expr)
    tool_body = tool_feat.GetBodies()[0]
    boolean(wp, target_body, tool_body, NXOpen.Features.Feature.BooleanType.Subtract)
    return tool_feat


# ---------------------------------------------------------------- 渐开线齿轮
# 数值口径：z=20/m=2，体积与解析偏差 0.0013%。
# 齿廓 = 表达式驱动规律曲线（压力角参数化，NX12 表达式无反三角——见
# modeling.md §4.1 硬限制）；齿顶/齿根 = 三点弧；齿根连接 = 径向线；
# 全齿闭合轮廓一次 UF 拉伸成体；轴孔负向拉伸求差。

import math as _math  # noqa: E402  （函数内 import 亦可，这里模块级一次）

_D2R = _math.pi / 180.0
_A2R = 180.0 / _math.pi


def involute_gear(wp, m, z, alpha_deg, b_width, bore_d, hub_d=0.0,
                  hub_len=0.0, z_offset=0.0):
    """标准渐开线直齿圆柱齿轮（无变位、无根切保护，ha*=1 c*=0.25）。

    参数全部走数值（mm/deg）；内部建 Number 表达式链 p_gear_* → p_rp/ra/rf/rb
    与 2*z 条齿面规律曲线表达式（改表达式可联动齿面，弧/线为哑曲线）。
    hub_d/hub_len > 0 时在齿宽中央加轮毂（减速器常用口径）；
    z_offset 平移整个齿轮的 Z 起点（默认 0）。
    返回 dict: body / volume / tip_tags / root_tags（供用例断言）。
    口径：T8 逐字平移；体积对齿数敏感约 14%/齿（z=20→21 实测 +14.013%），
    验收是扣孔体积对解析值的 ±2% 带宽。
    """
    u = ufs()
    rp = m * z / 2.0
    rb = rp * _math.cos(alpha_deg * _D2R)
    ra = rp + m
    rf = rp - 1.25 * m
    psi_b = 180.0 / (2.0 * z) + (_math.tan(alpha_deg * _D2R) - alpha_deg * _D2R) * _A2R
    pitch = 360.0 / z
    umax = _math.sqrt((ra / rb) ** 2 - 1.0)
    smax = umax * _A2R
    # 两套参数域不可混用：flank_xy 走 u 参数域（s∈[0,smax]），
    # 规律曲线表达式 r=rb/cos(p_s) 走压力角域（p_s∈[0,alpha_a]），
    # p_smax 必须给 alpha_a；给成 smax 齿面越过齿顶圆、与齿顶弧端点错开，
    # UF 拉伸报 "Section curves are not connected each other"
    alpha_a = _math.degrees(_math.atan(umax))

    def flank_xy(s, center_deg, side):
        uu = s * _D2R
        r = rb * _math.sqrt(1.0 + uu * uu)
        off = s - _math.degrees(_math.atan(uu))
        phi = center_deg + side * (psi_b - off)
        return [r * _math.cos(phi * _D2R), r * _math.sin(phi * _D2R), 0.0]

    # 1) 参数表达式（Number 无量纲，公式链可改值联动）
    for nm, val in [("p_gear_m", m), ("p_gear_z", float(z)),
                    ("p_gear_alpha", alpha_deg), ("p_gear_b", b_width),
                    ("p_gear_d_bore", bore_d)]:
        wp.Expressions.CreateExpression("Number", "%s = %s" % (nm, repr(val)))
    wp.Expressions.CreateExpression("Number", "p_t = 1")
    wp.Expressions.CreateExpression("Number", "p_rp = p_gear_m*p_gear_z/2")
    wp.Expressions.CreateExpression("Number", "p_ra = p_rp+p_gear_m")
    wp.Expressions.CreateExpression("Number", "p_rf = p_rp-1.25*p_gear_m")
    wp.Expressions.CreateExpression("Number", "p_rb = p_rp*cos(p_gear_alpha)")
    # 齿顶压力角：表达式层无反三角（NX12 实测），宿主算好存字面量
    wp.Expressions.CreateExpression("Number", "p_smax = " + repr(alpha_a))
    wp.Expressions.CreateExpression("Number", "p_s = p_t*p_smax")

    # 2) 齿面函数表达式：r=p_rb/cos(p_s)，phi 按左右侧
    for i in range(z):
        th = i * pitch
        for side_name, center in (("R", th + psi_b), ("L", th - psi_b)):
            if side_name == "R":
                phi_expr = "%r - %r*tan(p_s) + p_s" % (center, _A2R)
            else:
                phi_expr = "%r + %r*tan(p_s) - p_s" % (center, _A2R)
            common = "p_rb/cos(p_s)"
            wp.Expressions.CreateExpression(
                "Number", "p_xt%s%d = %s*cos(%s)" % (side_name, i, common, phi_expr))
            wp.Expressions.CreateExpression(
                "Number", "p_yt%s%d = %s*sin(%s)" % (side_name, i, common, phi_expr))

    # 3) 规律曲线（⚠ ZLaw 默认缺常量表达式，必须显式 Constant + "0"）
    law_tags = []
    for i in range(z):
        for side_name in ("R", "L"):
            lb = wp.Features.CreateLawCurveBuilder(NXOpen.Features.LawCurve.Null)
            for axis, fn_prefix in ((lb.XLaw, "p_xt"), (lb.YLaw, "p_yt")):
                axis.LawType = NXOpen.GeometricUtilities.LawBuilder.Type.ByEquation
                axis.Parameter = "p_t"
                axis.Function = fn_prefix + side_name + str(i)
                axis.StartValue.RightHandSide = "0"
                axis.EndValue.RightHandSide = "1"
            lb.ZLaw.LawType = NXOpen.GeometricUtilities.LawBuilder.Type.Constant
            lb.ZLaw.Value.RightHandSide = "0"
            feat = lb.CommitFeature()
            lb.Destroy()
            law_tags.append(feat.GetEntities()[0].Tag)

    # 4) 径向连接线 + 齿顶/齿根三点弧（⚠ 必须按齿交错追加：线/线/顶弧/根弧×z，
    #    分组给（线全给完再弧）UF 链探测报 "Section curves are not connected
    #    each other"，探针二分实测，T8 原版即交错序）
    def _phi0(th, side):
        return th + side * psi_b

    aux_tags, tip_tags, root_tags = [], [], []
    for i in range(z):
        th = i * pitch
        for side in (+1, -1):
            p0 = _phi0(th, side)
            lo = [rf * _math.cos(p0 * _D2R), rf * _math.sin(p0 * _D2R), 0.0]
            hi = flank_xy(0.0, th, side)
            aux_tags.append(wp.Curves.CreateLine(
                NXOpen.Point3d(lo[0], lo[1], 0.0),
                NXOpen.Point3d(hi[0], hi[1], 0.0)).Tag)
        t_start = flank_xy(smax, th, -1)
        t_mid = [ra * _math.cos(th * _D2R), ra * _math.sin(th * _D2R), 0.0]
        t_end = flank_xy(smax, th, +1)
        tip = u.Curve.CreateArcThru3pts(1, t_start, t_mid, t_end)
        tip_tags.append(tip)
        aux_tags.append(tip)
        p_r0 = _phi0(th, +1)
        p_e = th + pitch - psi_b
        g_mid = th + pitch / 2.0
        root = u.Curve.CreateArcThru3pts(
            1,
            [rf * _math.cos(p_r0 * _D2R), rf * _math.sin(p_r0 * _D2R), 0.0],
            [rf * _math.cos(g_mid * _D2R), rf * _math.sin(g_mid * _D2R), 0.0],
            [rf * _math.cos(p_e * _D2R), rf * _math.sin(p_e * _D2R), 0.0])
        root_tags.append(root)
        aux_tags.append(root)

    # 5) 全齿闭合轮廓一次拉伸（region 点在材料内 r<rf）
    u.Modl.CreateExtruded(
        law_tags + aux_tags, "0.0", [repr(z_offset), repr(z_offset + b_width)],
        [min(16.0, rf * 0.5), 0.0, 0.0], [0.0, 0.0, 1.0],
        NXOpen.UF.ModlFeatureSigns.NULLSIGN)
    bs = bodies(wp)
    if len(bs) != 1:
        raise RuntimeError("involute_gear: extrude gave %d bodies" % len(bs))
    body = bs[0]

    # 6) 轴孔：整圆负向拉伸求差
    circ = wp.Curves.CreateArc(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0),
        bore_d / 2.0, 0.0, 2.0 * _math.pi)
    u.Modl.CreateExtruded(
        [circ.Tag], "0.0", [repr(z_offset - 1.0), repr(z_offset + b_width + 1.0)],
        [0.0, 0.0, 0.0], [0.0, 0.0, 1.0], NXOpen.UF.ModlFeatureSigns.NEGATIVE)
    bs = bodies(wp)
    if len(bs) != 1:
        raise RuntimeError("involute_gear: bore gave %d bodies" % len(bs))
    body = bs[0]

    # 7) 可选轮毂：齿宽中央的圆柱，先打轴孔再并入齿轮
    if hub_d > 0.0 and hub_len > 0.0:
        def _disc(z0, z1, radius):
            c = wp.Curves.CreateArc(
                NXOpen.Point3d(0.0, 0.0, 0.0),
                NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0),
                radius, 0.0, 2.0 * _math.pi)
            u.Modl.CreateExtruded(
                [c.Tag], "0.0", [repr(z0), repr(z1)],
                [0.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                NXOpen.UF.ModlFeatureSigns.NULLSIGN)

        z0 = z_offset + (b_width - hub_len) / 2.0
        _disc(z0, z0 + hub_len, hub_d / 2.0)
        hub_body = [b for b in bodies(wp) if b.Tag != body.Tag][0]
        if bore_d > 0.0:
            _disc(z0 - 1.0, z0 + hub_len + 1.0, bore_d / 2.0)
            hole_body = [b for b in bodies(wp)
                         if b.Tag not in (body.Tag, hub_body.Tag)][0]
            boolean(wp, hub_body, hole_body,
                    NXOpen.Features.Feature.BooleanType.Subtract)
        boolean(wp, body, hub_body, NXOpen.Features.Feature.BooleanType.Unite)
        bs = bodies(wp)
        if len(bs) != 1:
            raise RuntimeError("involute_gear: hub unite gave %d bodies" % len(bs))
        body = bs[0]

    return {
        "body": bs[0],
        "volume": volume(wp, bs[0]),
        "tip_tags": tip_tags,
        "root_tags": root_tags,
        "ra": ra, "rf": rf, "bore_r": bore_d / 2.0,
    }
