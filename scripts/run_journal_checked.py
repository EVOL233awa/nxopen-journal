# -*- coding: utf-8 -*-
"""带输出标记判定的批处理包装器。

`run_journal.exe` 只在未捕获异常时返回非零；脚本吞掉失败时退出 0，原生
FATAL 也可能退出 0。这个包装器把"退出码"降级为参考，真正的判决是输出里
的标记：

  - 必须出现 `--token` 指定的成功 token；不给 `--token` 视为配置错误，进程在
    启动 journal 之前以退出码 2 结束；只查标记时显式传 `--allow-missing-token`；
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

# 输出重定向到文件时，locale 决定的编码可能装不下日志里的中文，write 会直接抛。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(HERE, "run_journal_batch.bat")

# run_journal 把正常收尾的 sys.exit(0) 也打成 "Line N: Traceback ... SystemExit: 0"，
# 整段吞掉；只有块内除 traceback 头外全是缩进行时才吞，顶格的其它行（异常行、
# 链式 traceback 头，含 StopIteration 这类名字不含 "Error" / "Exception" 的）
# 一律留作失败。
# 吞与判必须用同一套标记：FATAL / _FAIL 都不含 "Error" / "Exception"，只看异常名
# 会把夹在块里的原生 FATAL 一并吞掉。
_CLEAN_EXIT = re.compile(r"Traceback \(most recent call last\):")
_MARKERS = ("_FAIL", "STAGE_FAIL", "FATAL", "Traceback")


def run_batch(cmd):
    """启动批处理并收集输出，返回 (returncode, raw)。

    stdin 必须隔离：NX 的 DEX 脚本 `step214ug.cmd` 在转换器非零返回时执行
    `pause`（`step242ug.cmd` 没有）。继承控制台 stdin 时 `pause` 等按键，
    而这里等 `communicate()` 返回，两边互等就是永久挂死；`DEVNULL` 让
    `pause` 立即读到 EOF，失败路径退回"非零退出 + 日志"。
    """
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    raw = proc.communicate()[0] or b""
    return proc.returncode, raw


def strip_clean_exit(text):
    out = []
    pos = 0
    for m in _CLEAN_EXIT.finditer(text):
        seg = text[m.start():]
        end = seg.find("SystemExit: 0")
        if end < 0:
            continue
        body = seg[:end]
        inner = body.split("\n", 1)[-1] if "\n" in body else ""
        # 帧与源码行都缩进；顶格行是异常行或链式 traceback 头，出现即非
        # clean-exit 块。
        if any(line and not line[0].isspace() for line in inner.split("\n")):
            continue
        if any(marker in inner for marker in _MARKERS):
            continue
        out.append(text[pos:m.start()])
        pos = m.start() + end + len("SystemExit: 0")
    out.append(text[pos:])
    return "".join(out)


def scan(text):
    hits = []
    text = strip_clean_exit(text)
    for marker in _MARKERS:
        if marker in text:
            hits.append(marker)
    return hits


def verdict(text, token=None, allow_crash=False, allow_missing_token=False):
    """返回 (ok, hits, token_missing)；供包装器与宿主自检共用。

    没有 token 的判决等于免检，按配置错误抛错；只查标记时显式传
    allow_missing_token=True。
    """
    if not token and not allow_missing_token:
        raise ValueError("verdict() 需要 token；"
                         "只查标记时显式传 allow_missing_token=True")
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
    ap.add_argument("--allow-missing-token", action="store_true")
    args = ap.parse_args(argv)
    if not args.token and not args.allow_missing_token:
        ap.error("--token is required unless --allow-missing-token is given")

    cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", BATCH, args.journal]
    if args.workdir:
        cmd.append(args.workdir)
    returncode, raw = run_batch(cmd)
    text = raw.decode("utf-8", "replace")
    sys.stdout.write(text)
    sys.stdout.flush()
    if args.log:
        with open(args.log, "wb") as fh:
            fh.write(raw)

    ok, hits, missing = verdict(text, args.token, args.allow_crash,
                                args.allow_missing_token)
    print("RUN_CHECK exit=%d markers=%s token=%s"
          % (returncode, ",".join(hits) or "-",
             "missing" if missing else "ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
