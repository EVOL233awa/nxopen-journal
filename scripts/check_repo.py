# -*- coding: utf-8 -*-
"""本仓库自检：不依赖 NX 与第三方包，云端 CI 与本机都能跑。

四组检查，判据全部从目录树自身推出，没有一个写死的期望值，所以新增用例或文档
不会让检查静默放过：

  1) PY36       scripts/tests/*.py 必须能以 Python 3.6 语法解析。NX 12 内嵌解释器
                实测是 Python 3.6.1，3.7+ 的新语法在宿主 Python 上通过、在 NX 里直接
                报语法错，这一组就是拦这件事。
  2) COVERAGE   RUN_TESTS.bat 里 :gate 的每个用例号都要有对应文件，且每个用例文件
                都要在 RUN_TESTS.bat 里被点到名（在跑或在不跑的注释里说明）。
  3) DOCS       .md 的围栏配平、表格块必须有表头与分隔行、列数一致；README 与
                README.en.md 里提到的本仓库文件必须存在；两个 README 要互相链接。
  4) TREE       SKILL.md 的文件清单要覆盖磁盘上的每个顶层条目（隐藏项除外），
                避免新增目录后清单过期。
  5) NOLIB      标准层独占：非探针用例的顶层函数不得与 nxlib 公开 API 同名
                （同名=配方被复制进用例，正是"越滚越大的史山"的形态；应 import）。
                探针/死路用例的自包含是设计决策，名单在 SELF_CONTAINED，新增同类
                必须显式登记。nxlib/*.py 与 scripts/gb_drawing.py 同样过 PY36 语法。

用法：python scripts/check_repo.py [仓库根]
退出码 0 = 全部通过，1 = 有问题（逐条打印在 stdout）。
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                       os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TESTS = os.path.join(ROOT, "scripts", "tests")
BATCH = os.path.join(TESTS, "RUN_TESTS.bat")
NXLIB = os.path.join(ROOT, "scripts", "nxlib")
KEEP_DIRS = ("parts", "__pycache__", ".git")
# 探针/死路类用例：自包含（不复用标准层）是设计决策——它们的价值在原样记录
# 当时的调用方式，改写成库调用反而失真。新增同类用例必须显式登记进来。
SELF_CONTAINED = {
    "08_editability_probe.py", "11_api_probe.py", "12_api_probe2.py",
    "13_api_probe3.py", "17_motion_deadends.py", "28_pattern_helix.py",
    "32_pattern_enums.py",
}
CASE_RE = re.compile(r"^\d\d_[a-z_0-9]+\.py$")
# 文档里提到的文件名：带扩展名的反引号串；NX 安装目录自带的文件不算本仓库文件
PATH_RE = re.compile(r"`([A-Za-z0-9_./\\-]+\.(?:md|py|bat|yaml|png|prt|sim|fem))`")
# 图的两条引用途径：README 里既用 Markdown 图片也用 <img src=...>（表格里靠 width 控宽）
IMG_RE = re.compile(r"(?:<img[^>]*\bsrc=\"([^\"]+)\")|(?:\]\(([^)\s]+\.png)\))")
EXTERNAL = ("ugiicmd.bat", "ufvars.bat", "run_journal.exe")
DELIM = re.compile(r"^\|[\s:|\-]+\|$")

problems = []

# Output is Chinese: without this a locale-less runner (C/POSIX) picks an ASCII
# encoder and print() dies with UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def md_files():
    out = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in KEEP_DIRS]
        for n in names:
            if n.lower().endswith(".md"):
                out.append(os.path.join(base, n))
    return sorted(out)


def check_py36():
    print("== 1. Python 3.6 语法（NX 12 内嵌解释器）==")
    py_files = []
    for name in sorted(os.listdir(TESTS)):
        if CASE_RE.match(name):
            py_files.append(os.path.join(TESTS, name))
    # NX 解释器下运行的模块代码与用例同权：一处语法错 = 批处理全链路挂
    shipped = os.path.join(ROOT, "scripts", "gb_drawing.py")
    if os.path.exists(shipped):
        py_files.append(shipped)
    if os.path.isdir(NXLIB):
        py_files += [os.path.join(NXLIB, f)
                     for f in sorted(os.listdir(NXLIB))
                     if f.endswith(".py")]
    n = 0
    for path in py_files:
        name = os.path.relpath(path, ROOT)
        n += 1
        src = read(path)
        try:
            ast.parse(src, filename=name, feature_version=(3, 6))
        except SyntaxError as exc:
            problems.append("PY36 %s:%s %s" % (name, exc.lineno, exc.msg))
            print("  FAIL %s:%s %s" % (name, exc.lineno, exc.msg))
    print("  解析 %d 个 py 文件（用例+随包模块），问题 %d 处" % (n, len(problems)))


def check_coverage():
    print("== 2. 用例清单与文件一致 ==")
    if not os.path.exists(BATCH):
        problems.append("COVERAGE RUN_TESTS.bat 不存在")
        print("  FAIL RUN_TESTS.bat 不存在")
        return
    batch = read(BATCH)
    files = set(n for n in os.listdir(TESTS) if CASE_RE.match(n))
    gated = set(re.findall(r"call\s*:\s*gate\s+(\d\d)_[a-z_0-9]+\.py", batch))
    mentioned = set(re.findall(r"(\d\d_[a-z_0-9]+\.py)", batch))
    for n in sorted(files):
        if n not in mentioned:
            problems.append("COVERAGE %s 未被 RUN_TESTS.bat 提及" % n)
            print("  FAIL %s 未被 RUN_TESTS.bat 提及" % n)
    by_num = dict((n[:2], n) for n in files)
    for g in sorted(gated):
        if g not in by_num:
            problems.append("COVERAGE :gate %s 没有对应文件" % g)
            print("  FAIL :gate %s 没有对应文件" % g)
    print("  用例文件 %d 个（其中并入校验 %d 个），批次文件提到 %d 个"
          % (len(files), len(gated), len(mentioned)))


def check_docs():
    print("== 3. 文档结构 / 路径 / 双语互链 ==")
    docs = md_files()
    fence_bad, tbl_bad = [], []
    for path in docs:
        r = rel(path)
        lines = read(path).splitlines()
        fences = [i for i, l in enumerate(lines, 1) if l.strip().startswith("```")]
        if len(fences) % 2:
            fence_bad.append("%s 围栏不配平（第 %d 行起未闭合）" % (r, fences[-1]))
        in_fence, i = False, 0
        while i < len(lines):
            if lines[i].strip().startswith("```"):
                in_fence = not in_fence
                i += 1
                continue
            if not in_fence and lines[i].lstrip().startswith("|"):
                j = i
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    j += 1
                block = lines[i:j]
                counts = set(l.count("|") for l in block)
                if len(counts) > 1:
                    tbl_bad.append("%s:%d 列数不一致 %s" % (r, i + 1, sorted(counts)))
                if len(block) < 2 or not DELIM.match(block[1].strip()):
                    tbl_bad.append("%s:%d 表格块第 2 行不是分隔行" % (r, i + 1))
                i = j
            else:
                i += 1
    for x in fence_bad + tbl_bad:
        problems.append("DOCS " + x)
        print("  FAIL %s" % x)

    missing = []
    for name in ("README.md", "README.en.md"):
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            continue
        text = read(p)
        refs = [(m.group(1), None) for m in PATH_RE.finditer(text)]
        refs += [(m.group(1) or m.group(2), "img") for m in IMG_RE.finditer(text)]
        for raw, kind in refs:
            base = raw.replace("\\", "/").split("/")[-1]
            if raw.replace("\\", "/").startswith(("C:", "/")) or "://" in raw:
                continue
            if base in EXTERNAL:
                continue
            cands = [raw.replace("\\", "/"), base, "scripts/" + base,
                     "scripts/tests/" + base, "references/" + base,
                     "images/" + base]
            if not any(os.path.exists(os.path.join(ROOT, c)) for c in cands):
                missing.append("%s -> %s%s" % (name, raw, " (图片)" if kind else ""))
    for x in sorted(set(missing)):
        problems.append("DOCS 路径不存在 " + x)
        print("  FAIL 路径不存在 %s" % x)

    zh, en = os.path.join(ROOT, "README.md"), os.path.join(ROOT, "README.en.md")
    if os.path.exists(en) and os.path.exists(zh):
        # A bare substring would pass on any passing mention of the file name, so
        # require the markdown link target itself.
        if "](README.en.md)" not in read(zh):
            problems.append("DOCS README.md 未链接 README.en.md")
            print("  FAIL README.md 未链接 README.en.md")
        if "](README.md)" not in read(en):
            problems.append("DOCS README.en.md 未链接回 README.md")
            print("  FAIL README.en.md 未链接回 README.md")
    print("  扫描 %d 个 .md：围栏/表格问题 %d 处，缺失路径 %d 个"
          % (len(docs), len(fence_bad) + len(tbl_bad), len(set(missing))))


def check_tree():
    print("== 4. SKILL.md 文件清单 vs 磁盘 ==")
    skill = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(skill):
        problems.append("TREE 缺 SKILL.md")
        print("  FAIL 缺 SKILL.md")
        return
    text = read(skill)
    blk = re.search(r"##\s*8\.[^\n]*\n+```(.*?)```", text, re.S)
    tree = blk.group(1) if blk else ""
    if not tree:
        problems.append("TREE SKILL.md §8 未找到文件清单代码块")
        print("  FAIL 未找到 §8 文件清单代码块")
        return
    for must in ("README.md", "SKILL.md"):
        if must not in tree:
            problems.append("TREE 清单缺 %s" % must)
            print("  FAIL 清单缺 %s" % must)
    tops = sorted(n for n in os.listdir(ROOT) if not n.startswith("."))
    for n in tops:
        if n not in tree:
            problems.append("TREE 清单未覆盖顶层条目 %s" % n)
            print("  FAIL 清单未覆盖顶层条目 %s" % n)
    print("  顶层条目 %d 个：%s" % (len(tops), " ".join(tops)))


def nxlib_apis():
    """nxlib 各模块的顶层公开函数名集合。"""
    names = set()
    for n in sorted(os.listdir(NXLIB)):
        if not n.endswith(".py"):
            continue
        tree = ast.parse(read(os.path.join(NXLIB, n)))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                names.add(node.name)
    return names


def check_nolib():
    print("== 5. 标准层独占（nxlib 配方不得被用例复制）==")
    if not os.path.isdir(NXLIB):
        problems.append("NOLIB scripts/nxlib 不存在")
        print("  FAIL scripts/nxlib 不存在")
        return
    apis = nxlib_apis()
    dup = 0
    for name in sorted(os.listdir(TESTS)):
        if not CASE_RE.match(name) or name in SELF_CONTAINED:
            continue
        tree = ast.parse(read(os.path.join(TESTS, name)))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in apis:
                dup += 1
                problems.append("NOLIB %s 重新定义 nxlib.%s（应 import，不是复制）"
                                % (name, node.name))
                print("  FAIL %s 重新定义 nxlib.%s" % (name, node.name))
    for n in sorted(os.listdir(NXLIB)):
        if not n.endswith(".py"):
            continue
        try:
            ast.parse(read(os.path.join(NXLIB, n)), feature_version=(3, 6))
        except SyntaxError as exc:
            problems.append("NOLIB nxlib/%s:%s %s" % (n, exc.lineno, exc.msg))
            print("  FAIL nxlib/%s:%s %s" % (n, exc.lineno, exc.msg))
    print("  nxlib 公开 API %d 个；豁免自包含用例 %d 个；非探针用例撞名 %d 处"
          % (len(apis), len(SELF_CONTAINED), dup))


def main():
    print("check_repo.py  root=%s" % ROOT)
    check_py36()
    check_coverage()
    check_docs()
    check_tree()
    check_nolib()
    print("")
    if problems:
        print("CHECK_REPO_FAILED %d 项" % len(problems))
        return 1
    print("CHECK_REPO_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
