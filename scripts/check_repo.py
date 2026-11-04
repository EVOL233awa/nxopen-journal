# -*- coding: utf-8 -*-
"""本仓库自检：不依赖 NX 与第三方包，云端 CI 与本机都能跑。

八组检查，判据尽量从目录树自身推出；只有设计决策（探针名单、外部依赖、
精简词表）显式登记在常量里，所以新增用例或文档不会让检查静默放过：

  1) PY36       scripts/tests/*.py 必须能以 Python 3.6 语法解析。NX 12 内嵌解释器
                是 Python 3.6.1，3.7+ 的新语法在宿主 Python 上通过、在 NX 里直接
                报语法错，这一组就是拦这件事。
  2) COVERAGE   RUN_TESTS.bat 里 :gate 的每个用例号都要有对应文件，且每个用例文件
                都要在 RUN_TESTS.bat 里被点到名（在跑或在不跑的注释里说明）。
  3) DOCS       .md 的围栏配平、表格块必须有表头与分隔行、列数一致；README 与
                README.en.md 里提到的本仓库文件必须存在；两个 README 要互相链接。
  4) TREE       SKILL.md 的文件清单要覆盖磁盘上的每个顶层条目（隐藏项除外），
                清单里写出的 scripts/references/docs 路径必须在磁盘上存在，
                避免新增目录或删文件后清单过期。
  5) NOLIB      标准层独占：非探针用例的函数（含嵌套）不得与 nxlib 公开 API 同名
                （同名=配方被复制进用例，正是"越滚越大的史山"的形态；应 import）。
                探针/死路用例的自包含是设计决策，名单在 SELF_CONTAINED，新增同类
                必须显式登记。nxlib/*.py 与 scripts/gb_drawing.py 同样过 PY36 语法。
  6) CONCISE    agent 文档（SKILL.md、references/*.md、tests/README.md）不得出现
                日期与过程叙述词；新知识必须是结论/做法，不能把验证故事写回来。
  7) ROUTE      路线优先：域文件不新开坑位清单/坑位表；负面断言必须带做法。
                跨域通用且高发（静默失败/崩溃）的陷阱才留在 SKILL.md 铁律。
  8) WIKI       维护者导览 docs/wiki 必须跟代码同改：名册表（roster 标记后的
                表格首列）要列出每个 nxlib 模块、域文件、工具脚本；用例/gate
                计数要与本文件常量一致；页面必须被索引页链接；禁用"文件:行号"
                锚点（行号随维护漂移，改用符号名或 §章节）；被引用的符号与
                §章节必须仍然存在。

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
WIKI = os.path.join(ROOT, "docs", "wiki")
KEEP_DIRS = ("parts", "__pycache__", ".git")
# 探针/死路类用例：自包含（不复用标准层）是设计决策——它们的价值在原样记录
# 原样调用方式，改写成库调用反而失真。新增同类用例必须显式登记进来。
SELF_CONTAINED = {
    "05_modify_existing.py", "08_editability_probe.py", "11_api_probe.py",
    "12_api_probe2.py", "13_api_probe3.py", "17_motion_deadends.py",
    "28_pattern_helix.py", "32_pattern_enums.py",
}
# 一次性探针：保留证据，但明确不纳入 :gate 令牌校验。
PROBES = {"11_api_probe.py", "12_api_probe2.py", "13_api_probe3.py"}
# 期望计数：文档/批次头写错数字时在这里拦，而不是靠人眼比对。
EXPECTED_CASES = 53
EXPECTED_GATES = 50
EXPECTED_PROBES = 3
# 标准层规模：模块数与公开 API 数在 wiki 里有散文计数，一并钉住（同名函数跨模块
# 只算一次，与 check_nolib 的 nxlib_apis() 同口径）。
EXPECTED_API_COUNT = 231
# 用例文件名的实名规则：PY36/COVERAGE/NOLIB/_FAIL 四组共用同一份。编号不限位数、
# 大小写不敏感，否则 `54_Bad_Case.py` 这类名字对整道门隐形（连用例计数都不动）。
CASE_NAME = r"\d\d+_[A-Za-z0-9_]+\.py"
CASE_RE = re.compile(r"^" + CASE_NAME + r"$")
# 文档里提到的文件名：带扩展名的反引号串；NX 安装目录自带的文件不算本仓库文件
PATH_RE = re.compile(r"`([A-Za-z0-9_./\\-]+\.(?:md|py|bat|yaml|png|prt|sim|fem))`")
# 图的两条引用途径：README 里既用 Markdown 图片也用 <img src=...>（表格里靠 width 控宽）
IMG_RE = re.compile(r"(?:<img[^>]*\bsrc=\"([^\"]+)\")|(?:\]\(([^)\s]+\.png)\))")
EXTERNAL = ("ugiicmd.bat", "ufvars.bat", "run_journal.exe")
DELIM = re.compile(r"^\|[\s:|\-]+\|$")
# CONCISE：只扫 agent 文档。README/CHANGELOG 是人类文档，允许日期与"实测"表述。
# 词表只收过程叙述标记；"验证/复测"这类动作词是配方的一部分，不拦。
CONCISE_PATTERNS = (
    (r"(19|20)\d\d[-年/.]\d{1,2}[-月/.]\d{1,2}", "日期"),
    (r"实测", "实测"),
    (r"冷启动", "冷启动"),
    (r"复验", "复验"),
    (r"此前", "此前"),
    (r"推翻", "推翻"),
    (r"旧结论", "旧结论"),
    (r"作废", "作废"),
    (r"踩过", "踩过"),
    (r"白跑", "白跑"),
    (r"本轮", "本轮"),
    (r"代价", "代价"),
    (r"冷测", "冷测"),
    (r"沉淀", "沉淀"),
    (r"复证", "复证"),
    (r"审计实证", "审计实证"),
    (r"踩到", "踩坑"),
    (r"上轮|旧版|曾经|当时|最初|后来", "历史指代"),
)
# ROUTE：负面断言必须同时给出做法；坑位式标题/表格一律不再新增。
ROUTE_VERBS = ("用", "改", "走", "传", "设", "先", "必须", "直接", "按", "只",
               "不要", "禁止", "改用", "退回", "换", "取", "写", "赋", "加",
               "保留", "删", "断言", "校验", "枚举", "调", "提交", "选", "匹配",
               "→", "打")
NEG_RE = re.compile(r"(不可用|不存在|只读|死路|不生效|必报|必抛|报错|失败|不能)")
PITFALL_HEAD_RE = re.compile(r"^#+.*(坑位|反模式|不可用项|死路|陷阱)")
ALLOWED_TRAP_HEAD_RE = re.compile(r"^#+.*高发")
# 高发清单只按显式标记认定：标题是否含「高发」由作者措辞决定，改个标题就能让
# ≤8 约束失效，反向也会误伤同名的普通清单。
TRAP_MARK_RE = re.compile(r"<!--\s*trap-list\s*-->")
TRAP_MAX = 8
PITFALL_TABLE_RE = re.compile(r"^\|\s*(遇到|症状|问题|现象|坑位|反模式|不可用项|死路|陷阱)\s*\|")

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
        # 隐藏目录（.git/.zcode 会话草稿）不在版本控制里，扫进来会让门的结论依赖
        # 别人本机的工作副本；KEEP_DIRS 按前缀匹配，覆盖 parts38/parts46 这类产物目录。
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and not any(d == p or d.startswith(p) for p in KEEP_DIRS)]
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
    # NX 解释器下运行的模块代码与用例同权：一处语法错 = 批处理全链路挂。
    # occupancy/deliverable 被 50/52/53 号 gated 用例 import，同样跑在 3.6.1 里。
    shipped = ("scripts/gb_drawing.py", "scripts/occupancy.py",
               "scripts/deliverable.py", "scripts/render/export_stl.py",
               "scripts/stl_math.py")
    for r in shipped:
        p = os.path.join(ROOT, r)
        if not os.path.exists(p):
            problems.append("PY36 随包文件不存在 %s" % r)
            print("  FAIL 随包文件不存在 %s" % r)
            continue
        py_files.append(p)
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
    # :gate 必须是行首的 call（允许前导空白）。正则不锚行首时，
    # "if errorlevel 1 exit /b 1call :gate 34_..." 这种拼接行会被算作
    # "已覆盖"，套件实际跳过 34 号却报全绿。
    gated = set(re.findall(r"(?m)^[ \t]*call[ \t]+:gate[ \t]+(" + CASE_NAME + r")", batch))
    mentioned = set(re.findall(r"(" + CASE_NAME + r")", batch))
    expected = files - PROBES
    for n in sorted(files):
        if n not in mentioned:
            problems.append("COVERAGE %s 未被 RUN_TESTS.bat 提及" % n)
            print("  FAIL %s 未被 RUN_TESTS.bat 提及" % n)
    for n in sorted(expected - gated):
        problems.append("COVERAGE %s 有文件但没有行首 call :gate（不会被实际执行）" % n)
        print("  FAIL %s 有文件但没有行首 call :gate（不会被实际执行）" % n)
    for g in sorted(gated - expected):
        problems.append("COVERAGE :gate %s 是探针或没有对应文件" % g)
        print("  FAIL :gate %s 是探针或没有对应文件" % g)
    if len(files) != EXPECTED_CASES:
        problems.append("COVERAGE 用例文件 %d 个，期望 %d 个；同步 README/批次头"
                        % (len(files), EXPECTED_CASES))
    if len(expected) != EXPECTED_GATES:
        problems.append("COVERAGE 应并入校验 %d 个，期望 %d 个"
                        % (len(expected), EXPECTED_GATES))
    if len(gated) != EXPECTED_GATES:
        problems.append("COVERAGE 实际 gate %d 个，期望 %d 个"
                        % (len(gated), EXPECTED_GATES))
    if len(PROBES) != EXPECTED_PROBES:
        problems.append("COVERAGE 探针 %d 个，期望 %d 个"
                        % (len(PROBES), EXPECTED_PROBES))
    # :gate 的返回值必须紧跟 `if errorlevel 1 exit /b 1`：漏了它，该用例的
    # FAIL 只被打出来、套件照样打印 ALL TESTS PASSED 并返回 0（09 之前的
    # 两条就是这么被吞掉的）。
    blines = batch.splitlines()
    unchecked = []
    for i, line in enumerate(blines):
        m = re.match(r"^[ \t]*call[ \t]+:gate[ \t]+(" + CASE_NAME + r")", line)
        if not m:
            continue
        nxt = blines[i + 1] if i + 1 < len(blines) else ""
        if re.match(r"^[ \t]*if[ \t]+errorlevel[ \t]+1[ \t]+exit[ \t]+/[bB][ \t]+1",
                    nxt) is None:
            unchecked.append(m.group(1))
    for n in unchecked:
        problems.append("COVERAGE %s 的 :gate 返回值未被检查（漏 if errorlevel）" % n)
        print("  FAIL %s 的 :gate 返回值未被检查（漏 if errorlevel）" % n)
    print("  用例文件 %d 个（应并入校验 %d 个，实际 gate %d 个），批次文件提到 %d 个"
          % (len(files), len(expected), len(gated), len(mentioned)))


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
            problems.append("DOCS %s 不存在" % name)
            print("  FAIL %s 不存在" % name)
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
            # 写出了目录的引用必须按写出的路径存在：折成 basename 到候选目录里找
            # 同名文件，会让 `docs/nope/modeling.md` 命中 `references/modeling.md`。
            cands = ([raw.replace("\\", "/")] if "/" in raw.replace("\\", "/") else
                     [raw.replace("\\", "/"), base, "scripts/" + base,
                      "scripts/tests/" + base, "references/" + base,
                      "images/" + base])
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
    # 面类型号必须与 nxlib.measure 的常量一致；只扫 references/，CHANGELOG 是历史记录不改写。
    msrc = read(os.path.join(NXLIB, "measure.py"))
    ftypes = {}
    for name in ("SPHERE", "BLEND", "B_SURFACE", "TORUS"):
        m = re.search(r"^%s\s*=\s*(\d+)" % name, msrc, re.M)
        if m:
            ftypes[name] = int(m.group(1))
    pairs = (("球面", ftypes.get("SPHERE")),
             ("blend 面", ftypes.get("BLEND")),
             ("B 曲面", ftypes.get("B_SURFACE")),
             ("环面圆角", ftypes.get("TORUS")))
    refdir = os.path.join(ROOT, "references")
    bad_types = []
    for n in (sorted(os.listdir(refdir)) if os.path.isdir(refdir) else []):
        if not n.endswith(".md"):
            continue
        for i, line in enumerate(read(os.path.join(refdir, n)).splitlines(), 1):
            for name, num in pairs:
                if num is None:
                    continue
                for m in re.finditer(re.escape(name) + r"\s*[（(]?\s*(\d{2})\b", line):
                    if int(m.group(1)) != num:
                        bad_types.append("%s:%d %s(%s) 应为 %d"
                                         % (n, i, name, m.group(1), num))
            for m in re.finditer(r"圆角\s*[（(]\s*(23|43)\b", line):
                bad_types.append("%s:%d 圆角(%s) 未区分环面圆角(19) 与 blend 面(23)/B 曲面(43)"
                                 % (n, i, m.group(1)))
    for x in bad_types:
        problems.append("DOCS 面类型号 " + x)
        print("  FAIL 面类型号 %s" % x)
    print("  面类型号对账：%d 处" % len(bad_types))
    print("  扫描 %d 个 .md：围栏/表格问题 %d 处，缺失路径 %d 个"
          % (len(docs), len(fence_bad) + len(tbl_bad), len(set(missing))))


def _tree_paths(tree):
    """从 SKILL.md §8 的树形清单提取 scripts/、references/、docs/ 下的文件路径。"""
    stack = []
    out = []
    for line in tree.splitlines():
        m = re.search(r"(?:├──|└──)\s*(.*)$", line)
        if not m:
            continue
        depth = len(line[:m.start()]) // 4
        del stack[depth:]
        entry = m.group(1).split("←", 1)[0].strip()
        if not entry or "*" in entry or "…" in entry:
            continue
        if entry.endswith("/"):
            stack.append(entry.rstrip("/"))
            continue
        path = "/".join(stack + [entry])
        if path.startswith(("scripts/", "references/", "docs/")):
            out.append(path)
    return out


def _tree_missing(tree):
    return [p for p in _tree_paths(tree)
            if not os.path.exists(os.path.join(ROOT, p))]


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
    # 清单条目的首段路径要与顶层条目全名相等：整块子串判据会把新增的 render/
    # 判成已登记（清单里现成写着 `scripts/render/`）。
    listing = set()
    for line in tree.splitlines():
        m = re.match(r"^[│├└─\s]*([^\s/]+)", line)
        if m:
            listing.add(m.group(1))
    for n in tops:
        if n not in listing:
            problems.append("TREE 清单未覆盖顶层条目 %s" % n)
            print("  FAIL 清单未覆盖顶层条目 %s" % n)
    for p in _tree_missing(tree):
        problems.append("TREE 清单路径不存在 %s" % p)
        print("  FAIL 清单路径不存在 %s" % p)
    probe = "├── scripts/\n│   └── __tree_selftest_missing__.py\n"
    if _tree_missing(probe) != ["scripts/__tree_selftest_missing__.py"]:
        problems.append("TREE 自检失败：清单里的不存在路径未被识别")
        print("  FAIL 清单路径自检失败")
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
    if len(apis) != EXPECTED_API_COUNT:
        problems.append("NOLIB nxlib 公开 API %d 个，期望 %d 个；同步 EXPECTED_API_COUNT 与 wiki"
                        % (len(apis), EXPECTED_API_COUNT))
        print("  FAIL nxlib 公开 API %d 个，期望 %d 个"
              % (len(apis), EXPECTED_API_COUNT))
    dup = 0
    for name in sorted(os.listdir(TESTS)):
        if not CASE_RE.match(name) or name in SELF_CONTAINED:
            continue
        tree = ast.parse(read(os.path.join(TESTS, name)))
        for node in ast.walk(tree):
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
    # A check id containing "_FAIL" fails the gate on a green run: the gate is
    # `findstr /C:"_FAIL"` over the whole log, so a line like
    # `T47_X_FAILURE_TEXT=PASS ...` matches and the case is reported failed no
    # matter what it measured.  Only the deliberate verdict lines
    # (`TESTxx_FAIL ...`, `REG_x=FAIL`) may carry the token; those go through
    # say()/print(), never through check().
    bad_ids = 0
    for name in sorted(os.listdir(TESTS)):
        if not CASE_RE.match(name):
            continue
        for node in ast.walk(ast.parse(read(os.path.join(TESTS, name)))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            fname = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fname != "check":
                continue
            a0 = node.args[0]
            # id 可能是拼出来的（`"47_A" + "_FAIL"` / `"47_B{0}".format("_FAIL")`）：
            # 折不动就查首参整棵子树里的字符串常量，按约定 id 里不允许出现该 token。
            bad = [p.value for p in ast.walk(a0)
                   if isinstance(p, ast.Constant) and isinstance(p.value, str)
                   and "_FAIL" in p.value]
            if bad:
                bad_ids += 1
                problems.append("NOLIB %s:%d check id %r 含 _FAIL（通过时会误触 gate）"
                                % (name, node.lineno, bad[0]))
                print("  FAIL %s:%d check id 含 _FAIL：%r"
                      % (name, node.lineno, bad[0]))
    print("  nxlib 公开 API %d 个；豁免自包含用例 %d 个；非探针用例撞名 %d 处；"
          "check id 含 _FAIL %d 处"
          % (len(apis), len(SELF_CONTAINED), dup, bad_ids))


def agent_docs():
    paths = [os.path.join(ROOT, "SKILL.md")]
    refdir = os.path.join(ROOT, "references")
    if os.path.isdir(refdir):
        paths += [os.path.join(refdir, n) for n in sorted(os.listdir(refdir))
                  if n.endswith(".md")]
    tests_readme = os.path.join(TESTS, "README.md")
    if os.path.exists(tests_readme):
        paths.append(tests_readme)
    return paths


def check_concise():
    print("== 6. agent 文档精简（禁日期 / 过程叙述）==")
    paths = agent_docs()
    hits = 0
    for path in paths:
        r = rel(path)
        text = read(path)
        for pat, label in CONCISE_PATTERNS:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                hits += 1
                problems.append("CONCISE %s:%d 出现过程词 %s（改写成结论/做法）"
                                % (r, line, label))
                print("  FAIL %s:%d 过程词 %s" % (r, line, label))
    print("  扫描 %d 个 agent 文档：过程词 %d 处" % (len(paths), hits))


def _trap_lists(lines):
    """带 `<!-- trap-list -->` 标记的清单：返回 [(标题行号, 条目数)]。"""
    out = []
    cur = None
    count = 0
    in_fence = False
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith("#"):
            if cur is not None:
                out.append((cur, count))
            cur = i if TRAP_MARK_RE.search(s) else None
            count = 0
            continue
        if cur is not None and (re.match(r"[-*+]\s|\d+[.)]", s) or s.startswith("|")):
            count += 1
    if cur is not None:
        out.append((cur, count))
    return out


def _trap_selftest():
    """自检：无标记的 9 条清单返回 []，带标记的 9 条清单返回 [(1, 9)]。"""
    bare = ["## 高发清单"] + ["- 条目%d" % i for i in range(1, 10)]
    marked = ["## 高发清单 <!-- trap-list -->"] + ["- 条目%d" % i for i in range(1, 10)]
    return _trap_lists(bare), _trap_lists(marked)


def check_routes():
    print("== 7. 路线优先（负面事实内联，不新开坑位清单）==")
    if _trap_selftest() != ([], [(1, 9)]):
        problems.append("ROUTE 自检失败：无标记的 9 条清单应不报、带标记的 9 条清单应报")
        print("  FAIL 高发清单标记自检失败")
    paths = agent_docs()
    bad_head = bad_tbl = bad_line = bad_long = 0
    for path in paths:
        r = rel(path)
        lines = read(path).splitlines()
        in_fence = False
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if (s.startswith("#") and PITFALL_HEAD_RE.match(s)
                    and not ALLOWED_TRAP_HEAD_RE.match(s)):
                bad_head += 1
                problems.append("ROUTE %s:%d 坑位式标题，改为成功路线" % (r, i))
                print("  FAIL %s:%d 坑位式标题" % (r, i))
            if PITFALL_TABLE_RE.match(s):
                bad_tbl += 1
                problems.append("ROUTE %s:%d 坑位表，并入对应路线" % (r, i))
                print("  FAIL %s:%d 坑位表" % (r, i))
            if (not s.startswith("#") and NEG_RE.search(s)
                    and not any(v in s for v in ROUTE_VERBS)):
                bad_line += 1
                problems.append("ROUTE %s:%d 只有负面断言，没有做法" % (r, i))
                print("  FAIL %s:%d 只有负面断言" % (r, i))
        for h, n in _trap_lists(lines):
            if n > TRAP_MAX:
                bad_long += 1
                problems.append("ROUTE %s:%d 高发清单 %d 条，超过 8 条" % (r, h, n))
                print("  FAIL %s:%d 高发清单超过 8 条" % (r, h))
    print("  扫描 %d 个 agent 文档：坑位标题 %d、坑位表 %d、无做法负面行 %d、超长高发清单 %d"
          % (len(paths), bad_head, bad_tbl, bad_line, bad_long))


def wiki_text():
    """docs/wiki 下除索引外的全部页面，拼成一份文本（覆盖检查用）。"""
    if not os.path.isdir(WIKI):
        return ""
    parts = []
    for n in sorted(os.listdir(WIKI)):
        if n.endswith(".md"):
            parts.append(read(os.path.join(WIKI, n)))
    return "\n".join(parts)


def resolve_ref(ref):
    """把文档里写的文件引用解析到磁盘路径：先按写出的相对路径，再按 basename 在
    候选目录里找（文档常省掉目录前缀，如 `check_repo.py`）；找不到返回 None。"""
    raw = ref.replace("\\", "/")
    base = os.path.basename(raw)
    cands = [raw, "scripts/" + raw, "scripts/tests/" + raw, "references/" + raw,
             "docs/wiki/" + raw, base, "scripts/" + base, "scripts/tests/" + base,
             "references/" + base, "docs/wiki/" + base]
    for c in cands:
        p = os.path.join(ROOT, c)
        if os.path.isfile(p):
            return p
    return None


def wiki_heading_has(text, token):
    """token 是章节号（4.1 / B.4 / 0a）或章节名（运行方式）时，都要求存在对应标题。

    章节号后面通常是 `.`/`、` 或空格，所以只排除"更长数字"与"字母"：
    §1 不能命中 `## 11.`，但能命中 `## 1. 铁律`。章节名按标题开头匹配——标题被
    改名而正文还留着同一个词，正是最难发现的过期形态。
    """
    if re.match(r"^[0-9]+(?:\.[0-9]+)*[a-z]?$", token) or re.match(r"^[A-Z]\.[0-9]+$", token):
        pat = r"(?m)^#{2,6}\s*" + re.escape(token) + r"(?![0-9A-Za-z])(?!\.\d)"
        return re.search(pat, text) is not None
    return re.search(r"(?m)^#{2,6}\s*" + re.escape(token), text) is not None


def wiki_anchor_token(anchor):
    """从锚点文字里取最有辨识度的标识符：优先最长 ASCII 标识符。"""
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", anchor)
    if not toks:
        return None
    return max(toks, key=len)


def check_wiki():
    print("== 8. 维护者 wiki 与代码同步（docs/wiki）==")
    if not os.path.isdir(WIKI):
        problems.append("WIKI docs/wiki 不存在")
        print("  FAIL docs/wiki 不存在")
        return
    index = os.path.join(WIKI, "README.md")
    if not os.path.exists(index):
        problems.append("WIKI docs/wiki/README.md（索引页）不存在")
        print("  FAIL 缺索引页 README.md")
        return
    pages = [n for n in sorted(os.listdir(WIKI)) if n.endswith(".md") and n != "README.md"]
    idx = read(index)
    # 判据取 markdown 链接目标本身：子串包含会让 `[模块](03-modules.md.bak)` 这种
    # 坏链照样过（`.md.bak` 仍含 `03-modules.md`），只有删整行才报。
    idx_links = {os.path.basename(m.group(1))
                 for m in re.finditer(r"\]\(\s*([^)\s]+)\s*\)", idx)}
    for n in pages:
        if n not in idx_links:
            problems.append("WIKI %s 未在索引页里链接" % n)
            print("  FAIL 索引页未链接 %s" % n)
    blob = wiki_text()

    # 1) 覆盖：新增模块/域文件/工具脚本后，wiki 不改就过不去。
    #    只在"整个 wiki 任意处出现"不够：删掉专责页面里的那一行，别页的
    #    交叉引用还在，门照样绿。所以三个名册表用 `<!-- roster: X -->` 标记，
    #    门只从标记后的紧邻表格取首列；表被删/改名，对应 roster 就缺项。
    must = {}
    if os.path.isdir(NXLIB):
        must["nxlib"] = [n[:-3] for n in sorted(os.listdir(NXLIB))
                         if n.endswith(".py") and n != "__init__.py"]
    refdir = os.path.join(ROOT, "references")
    if os.path.isdir(refdir):
        must["references"] = [n for n in sorted(os.listdir(refdir)) if n.endswith(".md")]
    must["scripts"] = [n for n in sorted(os.listdir(os.path.join(ROOT, "scripts")))
                       if n.endswith((".py", ".bat"))]
    rosters = {}
    for n in pages:
        lines = read(os.path.join(WIKI, n)).splitlines()
        cur = None
        for line in lines:
            s = line.strip()
            m = re.match(r"<!--\s*roster:\s*([A-Za-z0-9_]+)\s*-->", s)
            if m:
                cur = m.group(1)
                rosters.setdefault(cur, set())
                continue
            if cur is None:
                continue
            if not s.startswith("|"):
                if s:
                    cur = None
                continue
            cells = s.strip("|").split("|")
            if cells:
                for mm in re.finditer(r"`([A-Za-z0-9_./\-]+)`", cells[0]):
                    rosters[cur].add(os.path.basename(mm.group(1)))
    missing = []
    for group, names in must.items():
        got = rosters.get(group, set())
        for m in names:
            base = os.path.basename(m)
            stem = base.replace(".py", "").replace(".bat", "")
            if not ({base, stem} & got):
                missing.append("%s/%s" % (group, m))
    for m in missing:
        problems.append("WIKI 名册缺 %s（新增/改名后需同步 docs/wiki 的 roster 表）" % m)
        print("  FAIL 名册缺 %s" % m)

    # 1b) nxlib 名册的行数列必须等于文件实际行数：行数随维护漂移，写死了就
    #     会静默说谎（旧条目只靠人工回顾，漂了几个月没人发现）。
    for n in pages:
        cur = None
        for line in read(os.path.join(WIKI, n)).splitlines():
            s = line.strip()
            m = re.match(r"<!--\s*roster:\s*([A-Za-z0-9_]+)\s*-->", s)
            if m:
                cur = m.group(1)
                continue
            if cur is None:
                continue
            if not s.startswith("|"):
                # 空行不清标记：与 1) 同一口径，标记后隔一个空行的表照样要核对。
                if s:
                    cur = None
                continue
            if cur != "nxlib":
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            mm = re.match(r"`([A-Za-z0-9_]+)`", cells[0]) if cells else None
            num = re.match(r"^(\d+)\s*行?$", cells[-1]) if cells else None
            if not mm or not num:
                continue
            path = os.path.join(NXLIB, mm.group(1) + ".py")
            if not os.path.isfile(path):
                continue
            real = len(read(path).splitlines())
            if int(num.group(1)) != real:
                problems.append("WIKI 行数过期 %s：wiki %s / 实际 %d"
                                % (mm.group(1), num.group(1), real))
                print("  FAIL 行数过期 %s：wiki %s / 实际 %d"
                      % (mm.group(1), num.group(1), real))

    # 1c) 散文里的"`xxx.py` 是最大的模块（NNNN 行）"这类行数也会漂：名册表
    #     由 1b 拦，正文里写的行数没人管，实测漂了 16 行仍全绿。凡正文里
    #     提到 nxlib 模块名后 40 字内出现"N 行"且 N>=50，都按实际行数核对。
    prose_line_refs = 0
    for n in pages:
        s = read(os.path.join(WIKI, n))
        for m in re.finditer(r"`([A-Za-z0-9_]+)(?:\.py)?`([^|]{0,40}?)(\d+)\s*行",
                             s, re.S):
            mod, claimed = m.group(1), int(m.group(3))
            path = os.path.join(NXLIB, mod + ".py")
            if claimed < 50 or not os.path.isfile(path):
                continue
            real = len(read(path).splitlines())
            prose_line_refs += 1
            if claimed != real:
                problems.append("WIKI 正文行数过期 %s：wiki %d / 实际 %d"
                                % (mod, claimed, real))
                print("  FAIL 正文行数过期 %s：wiki %d / 实际 %d"
                      % (mod, claimed, real))

    # 2) 计数：用例数/gate 数在 wiki 里必须唯一自洽——既要有当前值，
    #    也不得残留其它可能过期的数字（改一处漏一处就是旧的会留下来）。
    #    wiki 里还有子集计数（自包含用例、一次性探针），它们远小于总数，
    #    所以过期判定只看总数区间（>=20）内的数字，子集另按常量核对。
    for value, label, pat in ((EXPECTED_CASES, "用例", r"(\d+)\s*(?:个)?\s*用例"),
                              (EXPECTED_GATES, "gate", r"(\d+)\s*(?:个)?\s*(?:gate|门)")):
        found = [int(x) for x in re.findall(pat, blob)]
        if value not in found:
            problems.append("WIKI 未出现当前%s数 %d（数字变了要同步 wiki）" % (label, value))
            print("  FAIL 缺当前%s数 %d" % (label, value))
        stale = sorted(set(v for v in found if v != value and v >= 20))
        if stale:
            problems.append("WIKI 出现过期%s数 %s（当前 %d）" % (label, stale, value))
            print("  FAIL 过期%s数 %s" % (label, stale))
    for value, label, pat in ((len(SELF_CONTAINED), "自包含用例", r"%d\s*(?:个)?\s*用例不用 nxlib"),
                              (len(PROBES), "一次性探针", r"%d\s*(?:个)?\s*一次性探针")):
        if not re.search(pat % value, blob):
            problems.append("WIKI 的%s数应为 %d（与 check_repo.py 常量同步）" % (label, value))
            print("  FAIL %s数应为 %d" % (label, value))

    # 2b) 标准层规模：wiki 散文里的"15 模块 / 231 个公开 API"没有名册背书（名册只保证
    #     每个模块有一行，改错数字照样绿），按常量核对。
    modules_now = len([n for n in os.listdir(NXLIB)
                       if n.endswith(".py") and n != "__init__.py"]) if os.path.isdir(NXLIB) else 0
    for value, label, pat in ((modules_now, "模块", r"(\d+)\s*(?:个)?\s*模块"),
                              (EXPECTED_API_COUNT, "公开 API", r"(\d+)\s*个公开 API")):
        found = [int(x) for x in re.findall(pat, blob)]
        if value not in found:
            problems.append("WIKI 未出现当前%s数 %d（数字变了要同步 wiki）" % (label, value))
            print("  FAIL 缺当前%s数 %d" % (label, value))
        stale = sorted(set(v for v in found if v != value and v >= 5))
        if stale:
            problems.append("WIKI 出现过期%s数 %s（当前 %d）" % (label, stale, value))
            print("  FAIL 过期%s数 %s" % (label, stale))

    # 3) 行号锚点禁用：行号随维护漂移，wiki 会静默说谎
    line_refs = 0
    for n in pages + ["README.md"]:
        s = read(os.path.join(WIKI, n))
        for m in re.finditer(r"`[A-Za-z0-9_./\\-]+\.(?:py|bat|md|yml|json):\d+(?:-\d+)?`", s):
            line_refs += 1
            problems.append("WIKI %s 用了行号锚点 %s（改用符号名或 §章节）" % (n, m.group(0)))
            print("  FAIL %s 行号锚点 %s" % (n, m.group(0)))

    # 4) 锚点存在性：被引用的符号/章节必须还在
    checked = bad_anchor = 0
    for n in pages + ["README.md"]:
        s = read(os.path.join(WIKI, n))
        for m in re.finditer(r"`([A-Za-z0-9_./\-]+\.(?:py|bat|md))`\s*的\s*`([^`]+)`", s):
            target, anchor = m.group(1), m.group(2)
            path = resolve_ref(target)
            if path is None:
                bad_anchor += 1
                problems.append("WIKI %s 引用 %s 但文件不存在" % (n, target))
                print("  FAIL %s 引用不存在的文件 %s" % (n, target))
                continue
            tok = wiki_anchor_token(anchor)
            checked += 1
            if tok is None:
                bad_anchor += 1
                problems.append("WIKI %s 引用 %s 的 %s，但锚点里没有可校验的标识符"
                                % (n, target, anchor))
                print("  FAIL %s 锚点无法校验 %s -> %s" % (n, target, anchor))
            elif tok not in read(path):
                bad_anchor += 1
                problems.append("WIKI %s 引用 %s 的 %s，但目标文件里已无 %s"
                                % (n, target, anchor, tok))
                print("  FAIL %s 锚点失效 %s -> %s" % (n, target, tok))
        for m in re.finditer(
                r"`([A-Za-z0-9_./\-]+\.md)`\s*§\s*([^\s，。；：、（）]+)"
                r"|(?<![\w`/\\.-])([A-Za-z0-9_./\-]+\.md)\s*§\s*([^\s，。；：、（）]+)", s):
            target = m.group(1) or m.group(3)
            token = m.group(2) or m.group(4)
            path = resolve_ref(target)
            if path is None:
                bad_anchor += 1
                problems.append("WIKI %s 引用 %s 但文件不存在" % (n, target))
                print("  FAIL %s 引用不存在的文件 %s" % (n, target))
                continue
            checked += 1
            if not wiki_heading_has(read(path), token):
                bad_anchor += 1
                problems.append("WIKI %s 引用 %s §%s，但该章节不存在" % (n, target, token))
                print("  FAIL %s 章节失效 %s §%s" % (n, target, token))

    print("  页面 %d 个；名册 %d 组（缺 %d）；行号锚点 %d；锚点 %d 处（失效 %d）；正文行数 %d 处"
          % (len(pages), len(must), len(missing), line_refs, checked,
             bad_anchor, prose_line_refs))


def main():
    print("check_repo.py  root=%s" % ROOT)
    check_py36()
    check_coverage()
    check_docs()
    check_tree()
    check_nolib()
    check_concise()
    check_routes()
    check_wiki()
    print("")
    if problems:
        print("CHECK_REPO_FAILED %d 项" % len(problems))
        return 1
    print("CHECK_REPO_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
