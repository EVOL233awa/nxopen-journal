# -*- coding: utf-8 -*-
"""带输出标记判定的批处理包装器。

`run_journal.exe` 只在未捕获异常时返回非零；脚本吞掉失败时退出 0，原生
FATAL 也可能退出 0。这个包装器把"退出码"降级为参考，真正的判决是输出里
的标记：

  - 必须出现 `--token` 指定的成功 token；
  - 不得出现 `_FAIL` / `STAGE_FAIL` / `FATAL` / `Traceback`；
  - 原生崩溃串 `memory access violation` 默认也算失败（`--allow-crash` 放行，
    用于 26 号这类已知崩溃探针）。

例：
    python scripts/run_journal_checked.py journal.py workdir \\
        --token TEST01_DONE --log run.log
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(HERE, "run_journal_batch.bat")

# run_journal 把正常收尾的 sys.exit(0) 也打成 "Line N: Traceback ... SystemExit: 0"，
# 整段吞掉；只有块内没有别的异常行时才吞，真异常后面跟 SystemExit: 0 仍算失败。
_CLEAN_EXIT = re.compile(r"Traceback \(most recent call last\):")


def strip_clean_exit(text):
    out = []
    pos = 0
    for m in _CLEAN_EXIT.finditer(text):
        seg = text[m.start():]
        end = seg.find("SystemExit: 0")
        if end < 0:
            continue
        body = seg[:end]
        if "Error" in body or "Exception" in body:
            continue
        out.append(text[pos:m.start()])
        pos = m.start() + end + len("SystemExit: 0")
    out.append(text[pos:])
    return "".join(out)


def scan(text):
    hits = []
    text = strip_clean_exit(text)
    for marker in ("_FAIL", "STAGE_FAIL", "FATAL", "Traceback"):
        if marker in text:
            hits.append(marker)
    return hits


def verdict(text, token=None, allow_crash=False):
    """返回 (ok, hits, token_missing)；供包装器与宿主自检共用。"""
    hits = scan(text)
    if "memory access violation" in text and not allow_crash:
        hits.append("memory access violation")
    missing = bool(token) and token not in text
    return (not hits and not missing, hits, missing)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    ap.add_argument("workdir", nargs="?")
    ap.add_argument("--token")
    ap.add_argument("--log")
    ap.add_argument("--allow-crash", action="store_true")
    args = ap.parse_args(argv)

    cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", BATCH, args.journal]
    if args.workdir:
        cmd.append(args.workdir)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    raw = proc.communicate()[0] or b""
    text = raw.decode("utf-8", "replace")
    sys.stdout.write(text)
    sys.stdout.flush()
    if args.log:
        with open(args.log, "wb") as fh:
            fh.write(raw)

    ok, hits, missing = verdict(text, args.token, args.allow_crash)
    print("RUN_CHECK exit=%d markers=%s token=%s"
          % (proc.returncode, ",".join(hits) or "-",
             "missing" if missing else "ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
