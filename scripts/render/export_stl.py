# -*- coding: utf-8 -*-
"""Export the solids of a part to a binary STL, for offline figure rendering.

Env:
  IMG_PART  absolute path of the .prt to open (required)
  IMG_OUT   absolute path of the .stl to write (required)

Selection block takes a plain body list (SetArray); ProcessHoldFlag is not
needed for STL.  Measured corrections:
  * NX 12 STLCreator has no TriangleTolerance -> use ChordalTol.
  * It also has no OutputTypeOption; the member is OutputType (OutputTypeEnum),
    so this probe leaves the default instead of guessing.
Assembly parts keep their geometry in component occurrences, so when the part
has no own bodies the probe falls back to ObjectSelector.Scope.EntirePart and
logs whatever the assembly-level attempt produced.

Pass IMG_PART/IMG_OUT through the wrapper bat (run_export.bat): Git Bash
`\\$var` inside double quotes eats the backslash and the journal sees a
literal `$n` (measured).  The log lands next to the STL so a
swallowed NX console still leaves evidence.
"""
import os
import sys
import traceback

import NXOpen
import NXOpen.UF

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


def export(session, bodies, out, say):
    sc = session.DexManager.CreateStlCreator()
    say("  STLCreator tol/output members: %s"
        % [n for n in dir(sc) if "Tol" in n or "Output" in n])
    sc.OutputFile = out
    # 0.05 left visible facets on the flange's cylindrical faces at README
    # render size; 0.01 costs a few x triangles and reads smooth
    sc.ChordalTol = 0.01
    if bodies is None:
        sc.ExportSelectionBlock.SelectionScope = \
            NXOpen.ObjectSelector.Scope.EntirePart
        say("  scope=EntirePart")
    else:
        say("  scope=SelectedObjects n=%d" % len(bodies))
        sc.ExportSelectionBlock.SetArray(bodies)
    sc.Commit()
    sc.Destroy()
    ok = os.path.exists(out)
    say("  stl written=%s size=%s" % (ok, os.path.getsize(out) if ok else 0))
    return ok


def collect_bodies(part, say):
    bodies = list(part.Bodies)
    if bodies:
        say("  own bodies=%d via part.Bodies" % len(bodies))
        return bodies
    root = part.ComponentAssembly.RootComponent
    kids = list(root.GetChildren()) if root is not None else []
    say("  no own bodies; children=%d" % len(kids))
    say("  ufs.Assem members with Part/Comp: %s"
        % [n for n in dir(NXOpen.UF.UFSession.GetUFSession().Assem)
           if "Part" in n or "Comp" in n][:14])
    for c in kids:
        try:
            proto = c.Prototype
            say("  child %r proto=%s" % (c.Name, type(proto).__name__))
        except Exception as exc:
            say("  child %r Prototype raised %s" % (c.Name, exc))
    return None


def main():
    say("=" * 60)
    say("EXPORT STL  PART=%r OUT=%r" % (PART, OUT))
    if not PART or not OUT:
        say("ABORT missing env")
        return
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    try:
        part, status = session.Parts.Open(PART)
        ufs.Part.SetDisplayPart(part.Tag)
        say("opened %s" % part.FullPath)
        bodies = collect_bodies(part, say)
        export(session, bodies, OUT, say)
    except Exception as exc:
        say("FAIL %s: %s" % (type(exc).__name__, exc))
        say(traceback.format_exc())
    say("DONE_EXPORT_STL")


if __name__ == "__main__":
    main()
