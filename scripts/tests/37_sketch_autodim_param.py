# -*- coding: utf-8 -*-
"""Test 37: 草图自动尺寸 → 命名参数（唯一可行的参数化路线，NX12）。

五条断言，全部看几何，不看"提交成功"：

  1. `AddGeometry` 之后**不**调 `GetStatus` 直接建 AutoDimension，尺寸照出
     —— "少调 GetStatus 就没尺寸"是错归因，本用例把它钉死。
  2. 正路：AutoDimension 出尺寸、dof 归零（不跑 AutoConstrain）。
  3. 改指：把自动生成的 2r / r 尺寸改指 `2 * R_TEST` / `R_TEST` 后，拉伸体
     半径仍等于 R_TEST（体积 = π r² h，解析值比对）。
  4. 驱动：`R_TEST` ×1.5 → 更新后体积按 r² 变 2.25 倍；还原后体积回到原值。
  5. 反面对照：`AutoConstrain` 先跑会把圆标成完全约束且表达式表为空，随后
     AutoDimension 一个尺寸都不出 —— 这才是"0 尺寸"的真正原因，需要尺寸的
     草图不能先自动约束。
"""
import math
import os
import sys

import NXOpen
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, check_finish, say
from nxlib.session import new_part
from nxlib.modeling import expressions, extrude, make_sketch_dims, volume

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.join(HERE, "parts")
PART = os.path.join(PARTS, "t37_autodim_param.prt")

R0 = 10.0
H = 5.0
NULL = NXOpen.NXObject.Null
VRE = NXOpen.Sketch.ViewReorient.FalseValue


def circle(wp, r):
    return wp.Curves.CreateArc(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 1.0, 0.0),
        r, 0.0, 2.0 * math.pi)


def new_sketch(wp):
    sib = wp.Sketches.CreateNewSketchInPlaceBuilder(NXOpen.Sketch.Null)
    sib.SketchOrigin = wp.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0))
    sib.Commit()
    sk = sib.GetCommittedObjects()[0]
    sib.Destroy()
    sk.Activate(VRE)
    return sk


def autodim(wp, sk, curves):
    ad = wp.Sketches.CreateAutoDimensionBuilder()
    ad.SelectionObject.SetArray(curves)
    ad.SetRules([NXOpen.Sketch.AutoDimensioningRule.Length,
                 NXOpen.Sketch.AutoDimensioningRule.Symmetric])
    ad.DimensionType = NXOpen.SketchAutoDimensionBuilder.DimType.Driving
    ad.Commit()
    ad.Destroy()


def n_dims(sk):
    """数值型草图表达式数（AutoDimension 的驱动尺寸；已改指参数的 RHS 是名字，
    不算在内，所以正路用 linked 计数断言）。"""
    n = 0
    for e in sk.GetAllExpressions():
        try:
            float(e.RightHandSide)
        except Exception:
            continue
        n += 1
    return n


def update(s):
    mark = s.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "t37")
    errs = s.UpdateManager.DoUpdate(mark)
    s.DeleteUndoMark(mark, None)
    return errs


def main():
    s = NXOpen.Session.GetSession()
    wp = new_part(path=PART)
    expressions(wp, [("R_TEST", R0), ("H_TEST", H)])

    # 1. 对照：AddGeometry 之后不碰 GetStatus，直接建 AutoDimension —— 尺寸照出。
    #    （曾经把"0 尺寸"归因于少调 GetStatus，实际是 AutoConstrain 抢占，
    #     见本文件末尾的 AUTOCONSTRAIN_FIRST；这里把该结论钉死。）
    sk_bad = new_sketch(wp)
    c_bad = circle(wp, R0)
    sk_bad.AddGeometry(NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
                       NXOpen.Sketch.AddEllipseOption.TreatAsEllipse, [c_bad])
    autodim(wp, sk_bad, [c_bad])
    st_bad2, dof_bad2 = sk_bad.GetStatus()
    say("NEG status=%s dof=%d dims=%d" % (st_bad2, dof_bad2, n_dims(sk_bad)))
    check("T37_NO_GETSTATUS_STILL_DIMS", n_dims(sk_bad) > 0,
          "dims=%d dof=%d" % (n_dims(sk_bad), dof_bad2))
    sk_bad.Deactivate(VRE, NXOpen.Sketch.UpdateLevel.Model)

    # 2/3. 正路 + 改指
    c = circle(wp, R0)
    sk, linked = make_sketch_dims(
        wp, [c], links=[(2.0 * R0, "2 * R_TEST"), (R0, "R_TEST")])
    st, dof = sk.GetStatus()
    say("POS status=%s dof=%d dims=%d linked=%d" % (st, dof, n_dims(sk), linked))
    check("T37_DIMS_CREATED", n_dims(sk) > 0 and dof == 0,
          "dims=%d dof=%d" % (n_dims(sk), dof))
    check("T37_LINKED", linked >= 1, "linked=%d" % linked)

    extrude(wp, [c], "H_TEST")
    body = [b for b in wp.Bodies][0]
    v0 = volume(wp, body)
    a0 = math.pi * R0 * R0 * H
    say("V0=%.4f analytic=%.4f" % (v0, a0))
    check("T37_VOLUME_INITIAL", abs(v0 - a0) < 1e-3 * a0,
          "V=%.4f analytic=%.4f" % (v0, a0))

    # 4. 驱动
    e = None
    for ex in wp.Expressions:
        if ex.Name == "R_TEST":
            e = ex
    e.RightHandSide = "%.6f" % (R0 * 1.5)
    errs = update(s)
    v1 = volume(wp, body)
    a1 = math.pi * (R0 * 1.5) ** 2 * H
    say("V1=%.4f analytic=%.4f errs=%s" % (v1, a1, errs))
    check("T37_DRIVEN", errs == 0 and abs(v1 - a1) < 1e-3 * a1,
          "V=%.4f analytic=%.4f" % (v1, a1))

    e.RightHandSide = "%.6f" % R0
    errs = update(s)
    v2 = volume(wp, body)
    say("V2=%.4f errs=%s" % (v2, errs))
    check("T37_RESTORED", errs == 0 and abs(v2 - v0) < 1e-4 * v0,
          "V=%.4f V0=%.4f" % (v2, v0))

    # 记录（不断言）：AutoConstrain 先跑会吃掉尺寸
    sk_ac = new_sketch(wp)
    c_ac = circle(wp, R0)
    sk_ac.AddGeometry(NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
                      NXOpen.Sketch.AddEllipseOption.TreatAsEllipse, [c_ac])
    sk_ac.GetStatus()
    base_ac = n_dims(sk_ac)
    ac = wp.Sketches.CreateAutoConstrainBuilder()
    ac.Commit()
    ac.Destroy()
    st_ac, dof_ac = sk_ac.GetStatus()
    autodim(wp, sk_ac, [c_ac])
    st_ac2, dof_ac2 = sk_ac.GetStatus()
    say("AUTOCONSTRAIN_FIRST status=%s->%s dof=%d->%d dims=%d->%d" %
        (st_ac, st_ac2, dof_ac, dof_ac2, base_ac, n_dims(sk_ac)))
    check("T37_AUTOCONSTRAIN_PREEMPTS", n_dims(sk_ac) == base_ac,
          "dims=%d->%d" % (base_ac, n_dims(sk_ac)))
    sk_ac.Deactivate(VRE, NXOpen.Sketch.UpdateLevel.Model)

    ok = check_finish("TEST37_DONE", "TEST37")
    if not ok:
        raise RuntimeError("test 37 failed")


if __name__ == "__main__":
    main()
