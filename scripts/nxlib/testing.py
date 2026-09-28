# -*- coding: utf-8 -*-
"""nxlib.testing —— 用例框架统一实现（收编 14 份重复定义）。

口径权威：01 号的 stage、26 号的 check、22 号的 say（docstring 保留原语义）。

两条铁律：
  1. 失败输出必须含 "_FAIL"——RUN_TESTS.bat 的逐用例校验用它定位失败；
  2. say 逐行 flush——批处理 stdout 全缓冲，崩溃时也能看到断到哪一行。
"""
import sys
import traceback

RESULTS = []
FAILED_STAGES = []


def say(msg):
    """批处理 stdout 全缓冲：逐行 flush，崩溃时也能看到断到哪一行（铁律 5）。"""
    line = str(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def stage(name, fn):
    """包一个阶段：成功打 STAGE_OK（返回 fn 的返回值），失败记入
    FAILED_STAGES、打 STAGE_FAIL 与 400 字符栈尾（20 号口径）并返回 None。"""
    try:
        r = fn()
        say("STAGE_OK " + name)
        return r
    except Exception as exc:
        FAILED_STAGES.append(name)
        say("STAGE_FAIL " + name + " :: " + str(exc))
        say(traceback.format_exc()[-400:])
        return None


def check(name, ok, detail=""):
    """记录一条断言：进 RESULTS，输出 name=PASS/FAIL detail。"""
    RESULTS.append((name, bool(ok)))
    say("%s=%s %s" % (name, "PASS" if ok else "FAIL", detail))


def stage_finish(done_line, fail_prefix):
    """stage 型用例收尾：有失败打 <fail_prefix>_FAIL stages=...，全过打 done_line。"""
    if FAILED_STAGES:
        say(fail_prefix + "_FAIL stages=" + ",".join(FAILED_STAGES))
        return False
    say(done_line)
    return True


def check_finish(done_line, fail_prefix):
    """check 型用例收尾：RESULTS 有 False 打 <fail_prefix>_FAIL checks=...，全过打 done_line。"""
    bad = [n for (n, ok) in RESULTS if not ok]
    if bad:
        say(fail_prefix + "_FAIL checks=" + ",".join(bad))
        return False
    say(done_line)
    return True


def reset():
    """清空本轮状态（一个进程串多个用例时用）。"""
    del RESULTS[:]
    del FAILED_STAGES[:]
