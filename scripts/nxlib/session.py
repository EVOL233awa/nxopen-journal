# -*- coding: utf-8 -*-
"""nxlib.session —— 部件生命周期统一配方（收编 21 份 new_part 变体）。

21 个用例里的 new_part 实为两种本质语义，此处收成单签名：
  new_part(name="bracket")    → 内存件，NewFileName=name+".prt"（01 号口径）
  new_part(path="D:/x.prt")   → 落盘件：先建目录、删旧文件（14/15/22 号口径）
模板统一 model-plain-1-mm-template.prt、毫米；返回前 SetWork。
"""
import math
import os

import NXOpen
import NXOpen.UF

TEMPLATE = "model-plain-1-mm-template.prt"


def _ufs():
    return NXOpen.UF.UFSession.GetUFSession()


def _unit(v, zero="zero", eps=1e-12):
    """单位向量；zero="raise" 抛零向量，zero="none" 返回 None，否则返回 [0,0,0]。"""
    n = math.sqrt(sum(x * x for x in v))
    if zero == "raise" and n <= eps:
        raise ValueError("zero-length vector")
    if zero == "none" and n < eps:
        return None
    if n == 0:
        return [0.0, 0.0, 0.0]
    return [x / n for x in v]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _perp_dist(p1, p2, d):
    v = _sub(p2, p1)
    return math.sqrt(max(0.0, _dot(v, v) - _dot(v, d) ** 2))


def new_part(name=None, path=None, template=TEMPLATE):
    """新建部件并设为工作部件。name 与 path 二选一，path 优先。

    template 换模板（24/25/30 号的 FEA 链用 FemNxNastranMetric.fem /
    SimNxNastranMetric.sim）。⚠ .fem/.sim 模板下不能用 session.Parts.Work 收尾
    （抛 "The part file is not a .prt part"，25 号实测），此时返回
    FileNew().Commit() 的返回值且不做 SetWork。
    ⚠ name 分支并非"纯内存"：Commit() 会按 NewFileName 相对 CWD 直接落盘
    （实测 112KB 模板件），同名文件已存在时 Commit 抛
    "File already exists" —— 用例开工先 os.remove 同名残留（29 号实测）。
    """
    if not name and not path:
        raise ValueError("new_part 需要 name 或 path 之一")
    s = NXOpen.Session.GetSession()
    if path:
        d = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(d):
            os.makedirs(d)
        if os.path.exists(path):
            os.remove(path)
    fn = s.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = template
    fn.UseBlankTemplate = False
    if path:
        fn.NewFileName = path
    elif name:
        fn.NewFileName = name + ".prt"
    part = fn.Commit()
    fn.Destroy()
    if not (template.endswith(".fem") or template.endswith(".sim")):
        part = s.Parts.Work
        s.Parts.SetWork(part)
    return part


def set_work(part):
    """设工作部件并返回 wp。"""
    s = NXOpen.Session.GetSession()
    s.Parts.SetWork(part)
    return s.Parts.Work


def work():
    """当前工作部件。"""
    return NXOpen.Session.GetSession().Parts.Work


def save():
    """保存工作部件（UFSession.Part.Save，01 号口径）。"""
    _ufs().Part.Save()


def save_checked(path):
    """保存并断言确实落盘（15 号 save_part 口径）。"""
    save()
    assert os.path.exists(path) and os.path.getsize(path) > 0, "save did not land: %s" % path
