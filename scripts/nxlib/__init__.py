# -*- coding: utf-8 -*-
"""nxlib —— NX12 journal 标准层（Python 3.6.1 兼容，全部配方来自已验收用例的逐字平移）。

用例引导（写在 import 之前，8 行，适配 run_journal 下 __file__ 缺失的情形；
注入的是 nxlib 的**父目录**，即 scripts/）：

    import os, sys
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        _here = os.path.dirname(os.path.abspath(sys.argv[0]))
    _p = os.path.abspath(os.path.join(_here, ".."))
    if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
        sys.path.insert(0, _p)
    from nxlib.testing import stage, stage_finish
    from nxlib.session import new_part, save
    from nxlib.modeling import block, bodies

模块分工：
  testing  —— stage/say/check 框架（失败输出含 _FAIL，逐行 flush）
  session  —— 部件生命周期（new_part 统一签名 / set_work / save）
  modeling —— 块/表达式/草图/拉伸/孔/倒圆/阵列/布尔/面查找/包盒
  assembly —— 组件添加/单位阵/原型面查找/Touch 约束网络
  drafting —— 视图查询/UF 表格/PDF 导出/剖视配方
  measure  —— 只读面表/同轴分组/孔锥参数/STL 截面面积与 IoU/件间比对
"""
from . import testing
from . import session
from . import modeling
from . import assembly
from . import drafting
from . import measure

NXLIB_VERSION = "0.1.0"
