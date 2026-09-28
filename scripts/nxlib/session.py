# -*- coding: utf-8 -*-
"""nxlib.session —— 部件生命周期统一配方（收编 21 份 new_part 变体）。

21 个用例里的 new_part 实为两种本质语义，此处收成单签名：
  new_part(name="bracket")    → 内存件，NewFileName=name+".prt"（01 号口径）
  new_part(path="D:/x.prt")   → 落盘件：先建目录、删旧文件（14/15/22 号口径）
模板统一 model-plain-1-mm-template.prt、毫米；返回前 SetWork。
"""
import os

import NXOpen
import NXOpen.UF

TEMPLATE = "model-plain-1-mm-template.prt"


def new_part(name=None, path=None, template=TEMPLATE):
    """新建部件并设为工作部件。name 与 path 二选一，path 优先。

    template 换模板（24/25/30 号的 FEA 链用 FemNxNastranMetric.fem /
    SimNxNastranMetric.sim）。⚠ .fem/.sim 模板下不能用 session.Parts.Work 收尾
    （抛 "The part file is not a .prt part"，25 号实测），此时返回
    FileNew().Commit() 的返回值且不做 SetWork。
    ⚠ name 分支并非"纯内存"：Commit() 会按 NewFileName 相对 CWD 直接落盘
    （实测 112KB 模板件，2026-09-23），同名文件已存在时 Commit 抛
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
    NXOpen.UF.UFSession.GetUFSession().Part.Save()


def save_checked(path):
    """保存并断言确实落盘（15 号 save_part 口径）。"""
    save()
    assert os.path.exists(path) and os.path.getsize(path) > 0, "save did not land: %s" % path
