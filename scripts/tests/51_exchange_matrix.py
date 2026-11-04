# -*- coding: utf-8 -*-
"""Test 51: STEP 导入矩阵——WorkPart 与 NewPart 都要另起进程回读。

固定三条 NX12 行为：

  - `ImportTo=WorkPart` 也必须设 `OutputFile`，否则 Commit 不报错、工作件
    仍是 0 bodies；
  - `ImportTo=NewPart` 的产物约 8 s 后才落盘；判定必须另起进程
    `Parts.OpenBaseDisplay` 重开读 `Bodies`，不能在同一次 Commit 后读
    `Parts.Work`；
  - 纯实体 AP242/AP214 的 242 与 214 NewPart 都能重开 1 solid/6 面/4000。

出口 TEST51_DONE。
"""
import os
import sys
import time

import NXOpen

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib import exchange, modeling
from nxlib import session as S
from nxlib.testing import check, check_finish, say

BASE = os.getcwd()


def build_source():
    path = os.path.join(BASE, "ex51_src.prt")
    part = S.new_part(path=path)
    modeling.block(part, NXOpen.Point3d(0.0, 0.0, 0.0), "20", "20", "10")
    S.save()
    return part


def near(a, b, rel=0.005):
    return abs(a - b) <= rel * max(abs(b), 1e-9)


def prt_names():
    return set(n for n in os.listdir(BASE) if n.lower().endswith(".prt"))


def inspect_new(before):
    rows = []
    for name in sorted(prt_names() - before):
        path = os.path.join(BASE, name)
        try:
            part = exchange.reopen_part(path)
            rows.append((name, exchange.part_facts(part)))
        except Exception as exc:
            rows.append((name, {"error": repr(exc)}))
    return rows


def main():
    src = build_source()
    src_facts = exchange.part_facts(src)
    say("SRC " + str(src_facts))
    check("T51_SRC", src_facts["bodies"] == 1 and src_facts["faces"] == 6
          and src_facts["edges"] == 12, str(src_facts))

    stp242 = os.path.join(BASE, "ex51_242.stp")
    stp214 = os.path.join(BASE, "ex51_214.stp")
    exchange.export_step(src, stp242, "ap242")
    exchange.export_step(src, stp214, "ap214")
    say("EXPORTS 242=%d 214=%d" % (os.path.getsize(stp242),
                                   os.path.getsize(stp214)))

    # 242 WorkPart 正控；显示件必须切到目标件，否则 importer 可能写进
    # 上一个显示件（本用例里是 ex51_src），目标件仍是 0 bodies。
    imp = S.new_part(path=os.path.join(BASE, "ex51_imp.prt"))
    NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(imp.Tag)
    got = exchange.import_step(stp242, "ap242", target="work")
    facts = exchange.part_facts(got)
    say("IMPORT242_WORK " + str(facts))
    check("T51_242_WORK",
          facts["bodies"] == 1 and facts["faces"] == 6
          and near(facts["volume"], 4000.0), str(facts))

    # 242 NewPart：简单实体 STEP 可用；importer 8 s 后才落盘，文件名由它
    # 自己定，不看我们给的 OutputFile。判"新出现的 .prt 里有没有可用实体"。
    out242 = os.path.join(BASE, "ex51_242_new.prt")
    before242 = prt_names()
    try:
        exchange.import_step(stp242, "ap242", target="new", output_part=out242)
    except Exception as exc:
        say("IMPORT242_NEW_EXC " + repr(exc))
    time.sleep(8.0)
    rows242 = inspect_new(before242)
    say("IMPORT242_NEW new=%r" % (rows242,))
    good242 = [r for r in rows242 if r[1].get("bodies", 0) > 0]
    ok242 = False
    if good242:
        f242 = good242[0][1]
        ok242 = (f242["bodies"] == 1 and f242["faces"] == 6
                 and near(f242["volume"], 4000.0))
    check("T51_242_NEW", ok242, str(rows242))

    # 214 NewPart 正控：同样等 8 s，再按目标路径或新文件找可开部件。
    out214 = os.path.join(BASE, "ex51_214_new.prt")
    before214 = prt_names()
    exchange.import_step(stp214, "ap214", target="new", output_part=out214)
    time.sleep(8.0)
    rows214 = inspect_new(before214)
    say("IMPORT214_NEW new=%r" % (rows214,))
    good = [r for r in rows214 if r[1].get("bodies", 0) > 0]
    ok214 = False
    if good:
        facts214 = good[0][1]
        ok214 = (facts214["bodies"] == 1 and facts214["faces"] == 6
                 and near(facts214["volume"], 4000.0))
    check("T51_214_NEW", ok214, str(rows214))

    return check_finish("TEST51_DONE", "TEST51")


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as exc:
        import traceback
        say("TEST51_EXC " + repr(exc))
        say(traceback.format_exc()[-600:])
        raise
    sys.exit(0 if ok else 1)
