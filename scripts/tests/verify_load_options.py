# -*- coding: utf-8 -*-
"""跨会话加载选项 gate（宿主侧，两次独立 NX 进程）。

NX 只在进程启动时读 `UGII_LOAD_OPTIONS` 指向的 def，所以单进程 journal
无法验证“下次打开装配时组件是否按 def 载入”。本脚本：

1. 阶段 A（NX 进程 1）：建 `parts/loadopt/sub/lo_comp.prt` 与引用它的
   `parts/loadopt/lo_top.prt`，然后保存两份 def：`lo_as_saved.def` 与
   `lo_from_dir.def`。组件在子目录里，因此 FromDirectory（只在父装配目录找）
   找不到、AsSaved（按保存目录找）找得到。
2. 阶段 B（NX 进程 2/3）：分别用两份 def 启动全新 NX，打开顶层装配，报告
   `LoadStatus.NumberUnloadedParts` 与组件原型体数。

判定：AsSaved 必须全部载入（unloaded=0、体数>0）；FromDirectory 必须缺件
（unloaded>0 或体数=0）。两个方向都成立才 PASS，单向通过可能是默认搜索路径
碰巧命中，不构成证据。

用法（RUN_TESTS.bat 调用）：verify_load_options.py <parts_dir>
退出码 0=PASS，1=FAIL，2=环境缺失（无 NX_HOME/run_journal）。
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)
BAT = os.path.join(SCRIPTS, "run_journal_batch.bat")
CREATE_NO_WINDOW = 0x08000000

PHASE_A = r'''# -*- coding: utf-8 -*-
import os
import sys

import NXOpen
import NXOpen.UF

_p = os.environ["LOADOPT_SKILL"]
if _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.modeling import block
from nxlib.session import new_part, set_work, save_checked
from nxlib.assembly import add_component

ROOT = os.environ["LOADOPT_ROOT"]
SUB = os.path.join(ROOT, "sub")
if not os.path.isdir(SUB):
    os.makedirs(SUB)
COMP = os.path.join(SUB, "lo_comp.prt")
TOP = os.path.join(ROOT, "lo_top.prt")
for fp in (COMP, TOP):
    if os.path.exists(fp):
        os.remove(fp)

session = NXOpen.Session.GetSession()
ufs = NXOpen.UF.UFSession.GetUFSession()

cp = set_work(new_part(path=COMP))
block(cp, NXOpen.Point3d(0.0, 0.0, 0.0), "10", "10", "10")
save_checked(COMP)

tp = set_work(new_part(path=TOP))
add_component(tp, COMP, NXOpen.Point3d(30.0, 0.0, 0.0))
tp.Save(NXOpen.BasePart.SaveComponents.TrueValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue)
save_checked(TOP)

lo = session.Parts.LoadOptions
lo.ComponentsToLoad = NXOpen.LoadOptions.LoadComponents.All
lo.PartLoadOption = NXOpen.LoadOptions.LoadOption.FullyLoad
lo.AbortOnFailure = False
lo.ComponentLoadMethod = NXOpen.LoadOptions.LoadMethod.AsSaved
lo.Save(os.path.join(ROOT, "lo_as_saved.def"))
lo.ComponentLoadMethod = NXOpen.LoadOptions.LoadMethod.FromDirectory
lo.Save(os.path.join(ROOT, "lo_from_dir.def"))
print("LOADOPT_A_DEFS as_saved=%s from_dir=%s"
      % (os.path.getsize(os.path.join(ROOT, "lo_as_saved.def")),
         os.path.getsize(os.path.join(ROOT, "lo_from_dir.def"))))
print("LOADOPT_A_DONE")
'''

PHASE_B = r'''# -*- coding: utf-8 -*-
import os

import NXOpen

TOP = os.environ["LOADOPT_TOP"]
EXPECT = os.environ["LOADOPT_EXPECT"]
session = NXOpen.Session.GetSession()
opened = session.Parts.Open(TOP)
top = opened[0] if isinstance(opened, tuple) else opened
status = opened[1] if isinstance(opened, tuple) else None
unloaded = getattr(status, "NumberUnloadedParts", -1)
kids = list(top.ComponentAssembly.RootComponent.GetChildren())
comp = None
for c in kids:
    fp = str(getattr(c.Prototype, "FullPath", ""))
    if fp.lower().endswith("lo_comp.prt"):
        comp = c
        break
bodies = len(list(comp.Prototype.Bodies)) if comp is not None else -1
print("LOADOPT_B_STATE unloaded=%r comp_bodies=%r" % (unloaded, bodies))
loaded = (unloaded == 0 and bodies > 0)
missing = (unloaded > 0 or bodies == 0)
if EXPECT == "loaded" and loaded:
    print("LOADOPT_B_PASS")
elif EXPECT == "missing" and missing:
    print("LOADOPT_B_PASS")
else:
    print("LOADOPT_B_FAIL expect=%s unloaded=%r bodies=%r"
          % (EXPECT, unloaded, bodies))
print("LOADOPT_B_DONE")
'''


def _run_nx(journal, workdir, extra_env, timeout=420):
    env = os.environ.copy()
    env.update(extra_env)
    cmd = ["cmd.exe", "/c", BAT, journal, workdir]
    proc = subprocess.run(cmd, cwd=SKILL, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=CREATE_NO_WINDOW)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _tail(text, n=25):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def main(parts_dir):
    root = os.path.join(parts_dir, "loadopt")
    if not os.path.isdir(root):
        os.makedirs(root)
    ja = os.path.join(root, "phase_a.py")
    jb = os.path.join(root, "phase_b.py")
    _write(ja, PHASE_A)
    _write(jb, PHASE_B)

    rc, out = _run_nx(ja, root, {
        "LOADOPT_ROOT": root,
        "LOADOPT_SKILL": SCRIPTS,
    })
    if "LOADOPT_A_DONE" not in out:
        print("FAIL load-options phase A (rc=%s)" % rc)
        print(_tail(out))
        return 1

    for name, expect in (("lo_as_saved.def", "loaded"),
                         ("lo_from_dir.def", "missing")):
        def_path = os.path.join(root, name)
        if not os.path.exists(def_path):
            print("FAIL load-options def missing: %s" % def_path)
            return 1
        rc, out = _run_nx(jb, root, {
            "LOADOPT_TOP": os.path.join(root, "lo_top.prt"),
            "LOADOPT_EXPECT": expect,
            "UGII_LOAD_OPTIONS": def_path,
            "LOADOPT_SKILL": SCRIPTS,
        })
        if "LOADOPT_B_PASS" not in out or "LOADOPT_B_FAIL" in out:
            print("FAIL load-options cross-session %s (rc=%s)" % (name, rc))
            print(_tail(out))
            return 1
        line = [ln for ln in out.splitlines() if ln.startswith("LOADOPT_B_STATE")]
        print("PASS load-options cross-session %s %s"
              % (name, line[-1] if line else ""))
    print("LOAD_OPTIONS_CROSS_SESSION_OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: verify_load_options.py <parts_dir>")
        sys.exit(2)
    sys.exit(main(os.path.abspath(sys.argv[1])))
