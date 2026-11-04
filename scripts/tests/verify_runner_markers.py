# -*- coding: utf-8 -*-
"""Host-side selftest of the output-marker verdict in run_journal_checked.py.

The batch runner's exit code is not a verdict; the wrapper must fail on
_FATAL-ish markers and on a missing success token. Counter-examples below
must be rejected, the clean sample must pass.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from run_journal_checked import verdict  # noqa: E402

CASES = [
    ("clean", "RUN_JOURNAL_EXIT=0\nTEST01_DONE\n", "TEST01_DONE", False,
     True),
    ("fatal", "FATAL traceback\nTEST01_DONE\n", "TEST01_DONE", False, False),
    ("stage_fail", "STAGE_FAIL s1\nTEST01_DONE\n", "TEST01_DONE", False,
     False),
    ("fail_flag", "REG_x=FAIL\n_TEST_FAIL\n", None, False, False),
    ("traceback", "Traceback (most recent call last)\n", None, False, False),
    ("clean_exit", 'Line 9: Traceback (most recent call last):\n'
     '  File "x.py", line 12, in <module>\n    sys.exit(0)\n'
     "SystemExit: 0\nTEST01_DONE\n", "TEST01_DONE", False, True),
    ("real_error_then_exit0", "Traceback (most recent call last):\n"
     '  File "x.py", line 3\nValueError: boom\nSystemExit: 0\n'
     "TEST01_DONE\n", "TEST01_DONE", False, False),
    ("exit1", 'Line 9: Traceback (most recent call last):\n'
     '  File "x.py", line 12, in <module>\n    sys.exit(1)\n'
     "SystemExit: 1\nTEST01_DONE\n", "TEST01_DONE", False, False),
    ("crash", "Internal error: memory access violation\nTEST26_DONE\n",
     "TEST26_DONE", False, False),
    ("crash_allowed", "Internal error: memory access violation\nTEST26_DONE\n",
     "TEST26_DONE", True, True),
    ("missing_token", "RUN_JOURNAL_EXIT=0\n", "TEST01_DONE", False, False),
]


def main():
    bad = 0
    for name, text, token, allow, want in CASES:
        got = verdict(text, token, allow)[0]
        ok = got == want
        print("%s=%s want=%s got=%s" % (name, "PASS" if ok else "FAIL",
                                        want, got))
        if not ok:
            bad += 1
    if bad:
        print("RUNNER_MARKERS_FAILED %d" % bad)
        return 1
    print("RUNNER_MARKERS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
