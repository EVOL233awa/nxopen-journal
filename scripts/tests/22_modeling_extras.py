# -*- coding: utf-8 -*-
"""Test 22: 图层/类别 + 独立基准平面 + 沿路径阵列 回归（NX12 批处理）。

覆盖三组模块 API，每组都断言读回值：

A) 图层 API（modeling.md §1.7）
   - `body.Layer = 5` 可赋值可读回；`Feature.Layer` **不存在**（Feature 不是 DisplayableObject）
   - `LayerCategories.CreateCategory(name, desc, [1..5])` -> `GetMemberLayers() == [1,2,3,4,5]`
   - `cat.SetState(Hidden/Visible)` 与 `Layers.SetState(5, state, True)` 都能改 `GetState(5)`
   - `Layer.State` 成员全集 = Hidden/Selectable/Visible/WorkLayer（+ ValueOf）
   - ⚠ `Layers.SetState` 第 1 参必须是 **int**：传 list 会让 NX 以 0xC0000374 堆损坏退出
     （SKILL.md 铁律 6），故此处永远只传 int。

B) 独立基准平面特征（modeling.md §1.8）
   - `SetFaceAndOffset(Face, Double, String)` / `SetPointAndDirection(Point, Direction)` 两配方
     各使 `wp.Datums` +1，提交返回特征类型 `DATUM_PLANE`。
   - `DatumCsysBuilder` 在本机是死路：成员里只有 `Csys`，直接 CommitFeature 报
     "Reference coordinate system undefined"（只作 INFO 打印，不做检查——死路不需要守卫）。

C) 沿路径阵列 `AlongPath`（modeling.md §3.1a）
   受控 A/B：两条平行、Y 向错开 100mm 的引导线，分别只用一种写法，提交后量副本质心 Y：
   - 路线 1「赋值」`apd.XPath = sec`：不报错、且 `apd.XPath.Tag == sec.Tag`（真的换了对象），
     副本质心 (200, 0, 10) -> 落在 A 线
   - 路线 2「原地」`apd.XPath.AddToSection(...)`：副本质心 (200, 100, 10) -> 落在 B 线
   两条路线都必须生效，否则说明 AlongPath 配方又变了。
   ⚠ 默认间距/数量下只复制 1 个（落在引导线中点）。
"""
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
import NXOpen.Layer
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part
from nxlib.modeling import block, bodies, centroid

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts")
PART = os.path.join(OUT_DIR, "t22_modeling_extras.prt")


def layers_case(wp, body):
    body.Layer = 5
    check("REG_LAYER_ASSIGN", int(body.Layer) == 5, "body.Layer=%r" % body.Layer)

    feat = [f for f in wp.Features.GetFeatures()][0]
    try:
        feat.Layer = 21
        has_layer = True
    except AttributeError:
        has_layer = False
    check("REG_FEATURE_NO_LAYER", not has_layer,
          "Feature.Layer %s" % ("出现了（与记录不符）" if has_layer else "不存在，符合记录"))

    names = sorted(n for n in dir(NXOpen.Layer.State) if not n.startswith("_")
                   and n != "ValueOf")
    check("REG_LAYER_STATE_ENUM",
          names == ["Hidden", "Selectable", "Visible", "WorkLayer"], "enum=%s" % names)

    check("REG_WORK_LAYER", int(wp.Layers.WorkLayer) == 1,
          "WorkLayer=%r" % wp.Layers.WorkLayer)

    cat = wp.LayerCategories.CreateCategory("REG_SOLIDS", "regression solids", [1, 2, 3, 4, 5])
    check("REG_LAYER_CATEGORY", list(cat.GetMemberLayers()) == [1, 2, 3, 4, 5],
          "members=%r" % (cat.GetMemberLayers(),))

    cat.SetState(NXOpen.Layer.State.Hidden)
    hidden = wp.Layers.GetState(5)
    cat.SetState(NXOpen.Layer.State.Visible)
    visible = wp.Layers.GetState(5)
    check("REG_LAYER_CAT_STATE",
          hidden == NXOpen.Layer.State.Hidden and visible == NXOpen.Layer.State.Visible,
          "cat SetState -> %s / %s" % (hidden, visible))

    # ⚠ SetState 第 1 参是 int；传 list 会 0xC0000374 堆损坏（铁律 6），这里只传 int
    wp.Layers.SetState(5, NXOpen.Layer.State.Hidden, True)
    st_hidden = wp.Layers.GetState(5)
    wp.Layers.SetState(5, NXOpen.Layer.State.Visible, True)
    st_visible = wp.Layers.GetState(5)
    n0 = len(wp.Layers.GetAllObjectsOnLayer(5))
    wp.Layers.MoveDisplayableObjects(5, [body])
    n1 = len(wp.Layers.GetAllObjectsOnLayer(5))
    check("REG_LAYER_STATE_ROUNDTRIP",
          st_hidden == NXOpen.Layer.State.Hidden and st_visible == NXOpen.Layer.State.Visible
          and n1 >= n0 and int(body.Layer) == 5,
          "SetState 往返 %s/%s, layer5 objects %d->%d, body.Layer=%r"
          % (st_hidden, st_visible, n0, n1, body.Layer))


def datum_case(wp, ufs):
    body = bodies(wp)[0]
    top = None
    for f in body.GetFaces():
        d = ufs.Modeling.AskFaceData(f.Tag)
        if d[0] == 22 and abs(d[1][2] - 20.0) < 1e-6:
            top = f
    check("REG_DATUM_FACE_FOUND", top is not None, "top face=%r" % (top,))

    n0 = len([d for d in wp.Datums])
    b = wp.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)
    b.SetFaceAndOffset(top, 25.0, "")
    f1 = b.CommitFeature()
    b.Destroy()
    n1 = len([d for d in wp.Datums])
    check("REG_DATUM_FACE_OFFSET",
          n1 == n0 + 1 and f1 is not None and f1.FeatureType == "DATUM_PLANE",
          "datums %d->%d type=%r" % (n0, n1, f1.FeatureType if f1 else None))

    pt = wp.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 60.0))
    dr = wp.Directions.CreateDirection(NXOpen.Point3d(0.0, 0.0, 0.0),
                                       NXOpen.Vector3d(0.0, 0.0, 1.0),
                                       NXOpen.SmartObject.UpdateOption.WithinModeling)
    b = wp.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)
    b.SetPointAndDirection(pt, dr)
    f2 = b.CommitFeature()
    b.Destroy()
    n2 = len([d for d in wp.Datums])
    check("REG_DATUM_POINT_DIR",
          n2 == n1 + 1 and f2 is not None and f2.FeatureType == "DATUM_PLANE",
          "datums %d->%d type=%r" % (n1, n2, f2.FeatureType if f2 else None))

    # 死路记录，不作检查：本机 DatumCsysBuilder 只有 Csys 成员，提交报参考坐标系未定义
    b = wp.Features.CreateDatumCsysBuilder(NXOpen.Features.DatumCsys.Null)
    try:
        b.CommitFeature()
        say("REG_DATUM_CSYS=INFO committed（与记录不符，值得重查）")
    except Exception as exc:
        say("REG_DATUM_CSYS=INFO dead-end as recorded: %s: %s"
            % (type(exc).__name__, str(exc)[:60]))
    b.Destroy()


def along_path_case(wp):
    line_a = wp.Curves.CreateLine(NXOpen.Point3d(150.0, 0.0, 10.0),
                                  NXOpen.Point3d(250.0, 0.0, 10.0))
    line_b = wp.Curves.CreateLine(NXOpen.Point3d(150.0, 100.0, 10.0),
                                  NXOpen.Point3d(250.0, 100.0, 10.0))
    seed_a = block(wp, NXOpen.Point3d(145.0, -5.0, 0.0), "10", "10", "20")
    seed_b = block(wp, NXOpen.Point3d(145.0, 95.0, 0.0), "10", "10", "20")
    base = len(bodies(wp))
    check("REG_ALONGPATH_SEEDS", base == 3, "bodies=%d" % base)

    def make_pattern(seed):
        pb = wp.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
        pb.FeatureList.SetArray([seed])
        pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
        pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
        pd = pb.PatternService
        pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.AlongPath
        return pb, pd.AlongPathDefinition

    def fill(sec, line, hy):
        rule = wp.ScRuleFactory.CreateRuleCurveDumb([line])
        sec.AddToSection([rule], line, NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                         NXOpen.Point3d(150.0, hy, 10.0),
                         NXOpen.Section.Mode.Create, False)

    def new_centroid(tags_before):
        new = [b for b in bodies(wp) if int(b.Tag) not in tags_before]
        return (len(new), centroid(wp, new[0]) if len(new) == 1 else None)

    # ---- 路线 1：新建独立 Section 再赋值给 XPath ----
    tags = set(int(b.Tag) for b in bodies(wp))
    pb, apd = make_pattern(seed_a)
    sec = wp.Sections.CreateSection(0.0009, 0.001, 0.01)
    fill(sec, line_a, 0.0)
    try:
        apd.XPath = sec
        assigned = True
    except Exception:
        assigned = False
    same = False
    if assigned:
        try:
            same = int(apd.XPath.Tag) == int(sec.Tag)
        except Exception:
            same = False
    try:
        pb.CommitFeature()
        n, c = new_centroid(tags)
        ok = (assigned and same and n == 1 and c is not None
              and abs(c[0] - 200.0) < 1e-3 and abs(c[1] - 0.0) < 1e-3
              and abs(c[2] - 10.0) < 1e-3)
        check("REG_ALONGPATH_ASSIGN", ok,
              "assign=%s sameTag=%s new=%d C=%s" % (assigned, same, n, c))
    except Exception as exc:
        check("REG_ALONGPATH_ASSIGN", False, "%s: %s" % (type(exc).__name__, exc))
    pb.Destroy()

    # ---- 路线 2：不新建，直接往定义自带的 Section 里 AddToSection ----
    tags = set(int(b.Tag) for b in bodies(wp))
    pb, apd = make_pattern(seed_b)
    try:
        fill(apd.XPath, line_b, 100.0)
        pb.CommitFeature()
        n, c = new_centroid(tags)
        ok = (n == 1 and c is not None
              and abs(c[0] - 200.0) < 1e-3 and abs(c[1] - 100.0) < 1e-3
              and abs(c[2] - 10.0) < 1e-3)
        check("REG_ALONGPATH_INPLACE", ok, "new=%d C=%s" % (n, c))
    except Exception as exc:
        check("REG_ALONGPATH_INPLACE", False, "%s: %s" % (type(exc).__name__, exc))
    pb.Destroy()


def main():
    ufs = NXOpen.UF.UFSession.GetUFSession()
    wp = new_part(path=PART)
    block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "100", "60", "20")

    layers_case(wp, bodies(wp)[0])
    datum_case(wp, ufs)
    along_path_case(wp)

    ok = all(v for _, v in RESULTS)
    failed = [n for n, v in RESULTS if not v]
    say("TEST22_CASES=%d" % len(RESULTS))
    ufs.Part.Save()
    if not ok:
        say("TEST22_FAIL failed=%s" % failed)
        raise RuntimeError("test 22 failed: %s" % failed)
    say("TEST22_DONE")


if __name__ == "__main__":
    main()
