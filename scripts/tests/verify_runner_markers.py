# -*- coding: utf-8 -*-
"""Host-side selftest of the output-marker verdict in run_journal_checked.py.

The batch runner's exit code is not a verdict; the wrapper must fail on
_FATAL-ish markers and on a missing success token. Counter-examples below
must be rejected, the clean sample must pass.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from run_journal_checked import run_batch, verdict  # noqa: E402

CASES = [
    ("clean", "RUN_JOURNAL_EXIT=0\nTEST01_DONE\n", "TEST01_DONE", False,
     False, True),
    ("fatal", "FATAL traceback\nTEST01_DONE\n", "TEST01_DONE", False, False,
     False),
    # "STAGE_FAIL" is not a distinct marker: it hits through the "_FAIL"
    # substring, so this case pins substring matching, not STAGE_FAIL itself.
    ("fail_substring", "STAGE_FAIL s1\nTEST01_DONE\n", "TEST01_DONE", False,
     False, False),
    ("fail_flag", "REG_x=FAIL\n_TEST_FAIL\n", None, False, True, False),
    ("traceback", "Traceback (most recent call last)\n", None, False, True,
     False),
    ("clean_exit", 'Line 9: Traceback (most recent call last):\n'
     '  File "x.py", line 12, in <module>\n    sys.exit(0)\n'
     "SystemExit: 0\nTEST01_DONE\n", "TEST01_DONE", False, False, True),
    ("real_error_then_exit0", "Traceback (most recent call last):\n"
     '  File "x.py", line 3\nValueError: boom\nSystemExit: 0\n'
     "TEST01_DONE\n", "TEST01_DONE", False, False, False),
    ("exit1", 'Line 9: Traceback (most recent call last):\n'
     '  File "x.py", line 12, in <module>\n    sys.exit(1)\n'
     "SystemExit: 1\nTEST01_DONE\n", "TEST01_DONE", False, False, False),
    ("crash", "Internal error: memory access violation\nTEST26_DONE\n",
     "TEST26_DONE", False, False, False),
    ("crash_allowed", "Internal error: memory access violation\nTEST26_DONE\n",
     "TEST26_DONE", True, False, True),
    ("missing_token", "RUN_JOURNAL_EXIT=0\n", "TEST01_DONE", False, False,
     False),
    # Real passing log of test 50.
    ("real_50_pass", "RUN_JOURNAL_EXIT=0\nTEST50_DONE\n", "TEST50_DONE",
     False, False, True),
    # Real passing log of test 28: the crash-probe check prints the message it
    # matched, so a pass still carries "memory access violation".
    ("real_28_crash_text",
     "REG_AXIS_FACTORY_ARGS=PASS ... memory access violation\nTEST28_DONE\n",
     "TEST28_DONE", True, False, True),
    # Real failing log of test 51: the per-check line reads "=FAIL" (no
    # "_FAIL"); only TEST51_FAIL carries the marker.
    ("real_51_failed_checks",
     "T51_242_NEW=FAIL []\nTEST51_FAIL checks=T51_242_NEW,T51_214_NEW\n"
     "Traceback (most recent call last):\nSystemExit: 1\n", "TEST51_DONE",
     False, False, False),
]


def check_stdin_isolation():
    """生产路径必须在含 pause 的批处理上立即返回。

    DEX 的 step214ug.cmd 在转换器失败时执行 pause；继承控制台 stdin 会与
    communicate() 互等。正例走 run_batch（与 run_journal_checked 同一条路）；
    反例保留同一脚本但不隔离 stdin，必须停住——否则正例没有判别力。
    """
    bad = 0
    fd, path = tempfile.mkstemp(suffix=".bat")
    os.close(fd)
    try:
        with open(path, "w", newline="") as fh:
            fh.write("@echo off\r\npause\r\necho PAUSE_BATCH_DONE\r\n")
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", path]
        started = time.time()
        _rc, raw = run_batch(cmd)
        elapsed = time.time() - started
        ok = b"PAUSE_BATCH_DONE" in raw and elapsed < 10.0
        print("stdin_devnull=%s %.1fs" % ("PASS" if ok else "FAIL", elapsed))
        if not ok:
            bad += 1

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        time.sleep(2.0)
        blocked = proc.poll() is None
        proc.kill()
        proc.communicate()
        print("stdin_inherited_blocks=%s" % ("PASS" if blocked else "FAIL"))
        if not blocked:
            bad += 1
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return bad


def check_batch_redirect():
    """run_journal_batch.bat 直跑 run_journal 时也必须隔离 stdin。"""
    path = os.path.join(SCRIPTS, "run_journal_batch.bat")
    with open(path, "r", encoding="ascii") as fh:
        text = fh.read()
    ok = 'run_journal.exe" "%~1" < NUL' in text
    print("batch_nul_redirect=%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    bad = 0
    for name, text, token, allow, allow_missing, want in CASES:
        got = verdict(text, token, allow, allow_missing)[0]
        ok = got == want
        print("%s=%s want=%s got=%s" % (name, "PASS" if ok else "FAIL",
                                        want, got))
        if not ok:
            bad += 1
    try:
        verdict("clean\n")
    except ValueError:
        print("missing_token_requires_optin=PASS")
    else:
        print("missing_token_requires_optin=FAIL")
        bad += 1
    bad += check_stdin_isolation()
    bad += check_batch_redirect()
    if bad:
        print("RUNNER_MARKERS_FAILED %d" % bad)
        return 1
    print("RUNNER_MARKERS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
