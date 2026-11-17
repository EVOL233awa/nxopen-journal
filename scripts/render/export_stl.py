# -*- coding: utf-8 -*-
"""Export the solids of a part to a binary STL, for offline figure rendering.

Env:
  IMG_PART  absolute path of the .prt to open (required)
  IMG_OUT   absolute path of the .stl to write (required)

All STL creation lives in nxlib.measure.export_mesh(scope="auto"): own bodies
go through SetArray, assembly parts without own bodies fall back to
ObjectSelector.Scope.EntirePart, and a <=84-byte file (0 triangles) is
rejected.  This journal only opens the part, runs the exporter, and logs.

Pass IMG_PART/IMG_OUT through the wrapper bat (run_export.bat): Git Bash
`\\$var` inside double quotes eats the backslash and the journal sees a
literal `$n` (measured).  The log lands next to the STL so a swallowed NX
console still leaves evidence.
"""
import os
import sys
import traceback

import NXOpen
import NXOpen.UF

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.assembly import preload_tree
from nxlib.measure import export_mesh

PART = os.environ.get("IMG_PART", "").strip()
OUT = os.environ.get("IMG_OUT", "").strip()
if OUT:
    LOG = os.path.join(os.path.dirname(OUT), "export_stl.log")
else:
    LOG = os.path.join(os.environ.get("TEMP", os.getcwd()),
                       "nx_export_stl.log")


def say(msg):
    line = str(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main():
    say("=" * 60)
    say("EXPORT STL  PART=%r OUT=%r" % (PART, OUT))
    if not PART or not OUT:
        say("ABORT missing env")
        return
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    ok = False
    try:
        part, status = session.Parts.Open(PART)
        ufs.Part.SetDisplayPart(part.Tag)
        say("opened %s" % part.FullPath)
        own = len(list(part.Bodies))
        say("own bodies=%d" % own)
        if own == 0:
            say("preload_tree opened=%d"
                % len(preload_tree(session, part)))
        export_mesh(part, OUT, scope="auto")
        say("size=%d" % os.path.getsize(OUT))
        ok = True
    except Exception as exc:
        say("FAIL %s: %s" % (type(exc).__name__, exc))
        say(traceback.format_exc())
    if ok:
        say("DONE_EXPORT_STL")


if __name__ == "__main__":
    main()
