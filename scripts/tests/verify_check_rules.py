# -*- coding: utf-8 -*-
"""check_journal.py 规则自检（host 端运行，不进 NX）。

每条规则配一个会命中的反例（规则必须配会命中的样本，防规则本身是死的），
外加阴性对照（干净样本，以及"看起来该报、实际合法/已豁免"的写法）。
报错级规则必须 rc=1 且输出带对应判据；提示级规则（5.4/5.6/5.12、5.2 非字面量、
通用 3/4）只断言提示出现、退出码仍为 0 —— 它们本来就不拦。
RUN_TESTS.bat 末尾以 host 解释器调用（同 verify_anno_pdf 模式）。
判定出口：`PASS check_journal rule selftest` / `FAIL check_journal rule selftest ...`
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_journal  # noqa: E402

_WP = ("import NXOpen\n"
       "import NXOpen.UF\n"
       "\n"
       "\n"
       "def main():\n"
       "    wp = NXOpen.Session.GetSession().Parts.Work\n")

# (名, 期望输出痕迹, 反例源码, 期望退出码) —— 每例必须命中该痕迹
COUNTER_EXAMPLES = [
    ("5.1a builder 传 None", "Feature.Null",
     _WP + "    blk = wp.Features.CreateBlockFeatureBuilder(None)\n", 1),
    ("5.1b Parts.Open 参数个数", "Parts.Open 只传 1 个参数",
     _WP + "    part, st = NXOpen.Session.GetSession().Parts.Open('a.prt', True)\n", 1),
    ("5.1c Bodies.ToArray()", "没有 ToArray()",
     _WP + "    xs = wp.Bodies.ToArray()\n", 1),
    ("5.1c len(Bodies)", "no len()",
     _WP + "    n = len(wp.Bodies)\n    print(n)\n", 1),
    ("5.1d ReplaceRules 3 参第 2 位传 bool", "negatedEntities",
     _WP + "    sc = wp.ScCollectors.CreateCollector()\n"
           "    sc.ReplaceRules([], True, False)\n", 1),
    ("5.1d ReplaceRules 非法参数名", "没有参数名",
     _WP + "    sc = wp.ScCollectors.CreateCollector()\n"
           "    sc.ReplaceRules([], bogusFlag=False)\n", 1),
    ("5.1d ReplaceRules 只传 1 参", "至少需要 2 个参数",
     _WP + "    sc = wp.ScCollectors.CreateCollector()\n"
           "    sc.ReplaceRules([])\n", 1),
    ("5.1e Point3d 传 int", "Expecting double type",
     _WP + "    p = NXOpen.Point3d(0, 0, 0)\n", 1),
    ("字符串里的 allow-probes 不豁免", "Expecting double type",
     "def main():\n"
     "    marker = \"check_journal: allow-probes\"\n"
     "    p = NXOpen.Point3d(0, 0, 0)\n", 1),
    ("字符串里的 expected-raise 不豁免", "Expecting double type",
     "def main():\n"
     "    p = NXOpen.Point3d(0, 0, 0); s = \"check_journal: expected-raise\"\n", 1),
    ("5.1f SetOriginAndLengths 传数字", "必须 str",
     _WP + "    blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)\n"
           "    blk.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), '100', '60', 20)\n", 1),
    ("5.2 FileNew 未设 Units", "FileNew 未设置 .Units",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    s = NXOpen.Session.GetSession()\n"
     "    fn = s.Parts.FileNew()\n"
     "    fn.NewFileName = 'a.prt'\n"
     "    fn.Commit()\n", 1),
    ("5.2 NewFileName 非字面量（提示级）", "无法静态确认",
     _WP + "    fn = NXOpen.Session.GetSession().Parts.FileNew()\n"
           "    fn.Units = NXOpen.Part.Units.Millimeters\n"
           "    fn.NewFileName = name\n"
           "    fn.Commit()\n", 0),
    ("5.3 SaveComponents.True（语法层提示）", "TrueValue",
     _WP + "    wp.Save(NXOpen.BasePart.SaveComponents.True, "
           "NXOpen.BasePart.CloseAfterSave.FalseValue)\n", 1),
    ("5.4 Parts.Open + Parts.SetWork（提示级）", "No Displayed Part",
     _WP + "    part, st = NXOpen.Session.GetSession().Parts.Open('a.prt')\n"
           "    NXOpen.Session.GetSession().Parts.SetWork(part)\n", 0),
    ("5.5 Block 尺寸属性只读", "属性只读",
     _WP + "    blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)\n"
           "    blk.Length = 10.0\n", 1),
    ("5.5 Cylinder 尺寸属性只读", "属性只读",
     _WP + "    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
           "    cb.Diameter = 10.0\n", 1),
    ("5.6 CreateRevolveBuilder（提示级）", "CreateRevolveBuilder",
     _WP + "    rv = wp.Features.CreateRevolveBuilder(NXOpen.Features.Feature.Null)\n", 0),
    ("5.7 NXOpen.UF.FeatureSigns", "ModlFeatureSigns",
     "import NXOpen\n"
     "import NXOpen.UF\n"
     "\n"
     "\n"
     "def main():\n"
     "    x = NXOpen.UF.FeatureSigns.POSITIVE\n"
     "    print(x)\n", 1),
    ("5.7 NXOpen.UF.UFDraw", "UFDraw",
     _WP + "    bad = NXOpen.UF.UFDraw\n", 1),
    ("5.7 NXOpen.UF.UFMotion", "UFMotion",
     _WP + "    bad = NXOpen.UF.UFMotion\n", 1),
    ("5.8 ComponentAssembly.Components", "ComponentAssembly.Components 不存在",
     _WP + "    xs = wp.ComponentAssembly.Components\n", 1),
    ("5.9 Block builder 的 BooleanOption", "BooleanOption",
     _WP + "    blk = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)\n"
           "    blk.BooleanOption = 1\n", 1),
    ("5.10 NX12 无螺纹特征 builder", "CreateThreadBuilder",
     _WP + "    th = wp.Features.CreateThreadBuilder(NXOpen.Features.Feature.Null)\n", 1),
    ("5.11 StepCreator 未设 ProcessHoldFlag", "ProcessHoldFlag",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    s = NXOpen.Session.GetSession()\n"
     "    sc = s.DexManager.CreateStepCreator()\n"
     "    sc.Commit()\n", 1),
    ("5.12 去参（提示级）", "去参",
     _WP + "    rp = wp.Features.CreateRemoveParametersBuilder()\n", 0),
    ("5.13 Save 无落盘校验", "落盘校验",
     _WP + "    wp.Save()\n", 1),
    ("5.13 SaveAs 无落盘校验", "落盘校验",
     _WP + "    wp.SaveAs('x.prt')\n", 1),
    ("5.13 校验早于 Save", "落盘校验",
     _WP + "    assert os.path.exists('a.prt') and os.path.getsize('a.prt') > 0\n"
           "    wp.Save()\n", 1),
    ("5.13 SaveAs 后校验别的路径", "落盘校验",
     _WP + "    wp.SaveAs('a.prt')\n"
           "    assert os.path.exists('b.prt') and os.path.getsize('b.prt') > 0\n", 1),
    ("5.13 多路径 SaveAs 只校最后一个", "落盘校验",
     _WP + "    wp.SaveAs('a.prt')\n"
           "    wp.SaveAs('b.prt')\n"
           "    assert os.path.exists('b.prt') and os.path.getsize('b.prt') > 0\n", 1),
    ("5.14a DraftBuilder.Method 只读", "只读属性",
     _WP + "    db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)\n"
           "    db.Method = 1\n"
           "    db.AngleTolerance = 0.5\n", 1),
    ("5.14b DraftBuilder 未设 AngleTolerance", "AngleTolerance",
     _WP + "    db = wp.Features.CreateDraftBuilder(NXOpen.Features.Feature.Null)\n"
           "    db.Commit()\n", 1),
    ("5.15 ShellBuilder 未设 Tolerance", "Tolerance",
     _WP + "    sb = wp.Features.CreateShellBuilder(NXOpen.Features.Feature.Null)\n"
           "    sb.Commit()\n", 1),
    ("5.16 from math import dist", "3.6.1",
     "from math import dist\n"
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    print(dist((0.0, 0.0), (3.0, 4.0)))\n", 1),
    ("5.16 math.dist 属性访问", "3.6.1",
     _WP + "    import math\n"
           "    print(math.dist((0.0, 0.0), (3.0, 4.0)))\n", 1),
    ("5.16 math.prod", "3.6.1",
     _WP + "    import math\n"
           "    print(math.prod([1, 2, 3]))\n", 1),
    ("5.16 math.isqrt", "3.6.1",
     _WP + "    import math\n"
           "    print(math.isqrt(9))\n", 1),
    ("5.16 math.comb", "3.6.1",
     _WP + "    import math\n"
           "    print(math.comb(5, 2))\n", 1),
    ("5.16 math.perm", "3.6.1",
     _WP + "    import math\n"
           "    print(math.perm(5, 2))\n", 1),
    ("5.16 math.nextafter", "3.6.1",
     _WP + "    import math\n"
           "    print(math.nextafter(1.0, 2.0))\n", 1),
    ("5.16 functools.cache", "3.6.1",
     _WP + "    import functools\n"
           "    print(functools.cache)\n", 1),
    ("5.16 functools.cached_property", "3.6.1",
     _WP + "    import functools\n"
           "    print(functools.cached_property)\n", 1),
    ("5.16 itertools.pairwise", "3.6.1",
     _WP + "    import itertools\n"
           "    print(itertools.pairwise([1, 2, 3]))\n", 1),
    ("5.16 str.removeprefix", "removeprefix",
     _WP + "    s = 'abc'\n"
           "    print(s.removeprefix('a'))\n", 1),
    ("5.16 str.removesuffix", "removesuffix",
     _WP + "    s = 'abc'\n"
           "    print(s.removesuffix('c'))\n", 1),
    ("5.17 枚举访问器 0 参调用", "枚举属性",
     _WP + "    spring = wp.Axies.CreateSpringBuilder(NXOpen.Features.Feature.Null)\n"
           "    t = spring.AttachmentType()\n"
           "    print(t)\n", 1),
    ("5.17 Types() 枚举访问器", "枚举属性",
     _WP + "    t = wp.Types()\n", 1),
    ("5.17 HoleDepthOptions() 枚举访问器", "枚举属性",
     _WP + "    t = wp.HoleDepthOptions()\n", 1),
    ("5.18 CylinderBuilder 枚举成员名", "AxisDiameterAndHeight",
     _WP + "    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
           "    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisAndHeight\n"
           "    cb.Commit()\n", 1),
    ("5.18 别名一层后仍命中", "AxisDiameterAndHeight",
     _WP + "    T = NXOpen.Features.CylinderBuilder.Types\n"
           "    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
           "    cb.Type = T.AxisAndHeight\n", 1),
    ("5.19 UFDrf 伪容器", "UFDrf",
     "import NXOpen\n"
     "import NXOpen.UF\n"
     "\n"
     "\n"
     "def main():\n"
     "    bad = NXOpen.UF.UFDrf\n"
     "    print(bad)\n", 1),
    ("5.20 RightHandSide 给数字", "必须给字符串",
     _WP + "    cb = wp.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
           "    cb.Height.RightHandSide = 20\n", 1),
    ("5.20 需要 Point 的属性给 Point3d", "需要 NXOpen.Point 对象",
     _WP + "    seg = wp.Drawings.CreateSectionLineSegmentsBuilder(NXOpen.Drawings.SectionLineSegmentsBuilder.Null)\n"
           "    seg.RotationPoint = NXOpen.Point3d(0.0, 0.0, 0.0)\n", 1),
    ("Python 3.6 语法：walrus", "语法错误",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    if (n := 1):\n"
     "        print(n)\n", 1),
    ("通用 2 TODO 注释", "占位符",
     _WP + "    # TODO: fill this in\n", 1),
    ("通用 3 缺 main（提示级）", "未找到 def main",
     "import NXOpen\n"
     "\n"
     "\n"
     "def f():\n"
     "    pass\n", 0),
    ("通用 4 裸 except（提示级）", "裸 except",
     _WP + "    try:\n"
           "        pass\n"
           "    except:\n"
           "        pass\n", 0),
]

CLEAN_SAMPLE = (
    "import NXOpen\n"
    "\n"
    "\n"
    "def main():\n"
    "    part = NXOpen.Session.GetSession().Parts.Work\n"
    "    cb = part.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
    "    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight\n"
    "    cb.Height.RightHandSide = \"20\"\n"
    "    cb.Commit()\n"
)

EXTRA_CLEAN = [
    ("合法 pass 注释",
     "import NXOpen\n"
     "\n"
     "\n"
     "def f():\n"
     "    pass  # legitimate no-op\n"
     "\n"
     "\n"
     "def main():\n"
     "    f()\n"),
    ("字符串里的 UFDrf/AxisAndHeight 不算代码",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    print(\"NXOpen.UF.UFDrf is gone\")\n"
     "    print(\"CylinderBuilder.Types.AxisAndHeight is gone\")\n"),
    ("save_checked 通过落盘校验",
     "import NXOpen\n"
     "from nxlib.session import save_checked\n"
     "\n"
     "\n"
     "def main():\n"
     "    save_checked(\"x.prt\")\n"),
    ("2 参 ReplaceRules 传 True 合法（第二参是 createRulesWoUpdate）",
     _WP + "    sc = wp.ScCollectors.CreateCollector()\n"
           "    sc.ReplaceRules([], True)\n"),
    ("同名局部变量遮蔽 math 不误报",
     "import NXOpen\n"
     "\n"
     "\n"
     "class M:\n"
     "    dist = staticmethod(lambda a, b: 0.0)\n"
     "\n"
     "\n"
     "def main():\n"
     "    math = M()\n"
     "    print(math.dist((0.0, 0.0), (1.0, 1.0)))\n"),
    ("行尾 expected-raise 对 5.1 系列同样生效",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    p = NXOpen.Point3d(0, 0, 0)  # check_journal: expected-raise\n"
     "    print(p)\n"),
    ("真正调 os.path.getsize 算落盘校验",
     "import os\n"
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    wp = NXOpen.Session.GetSession().Parts.Work\n"
     "    wp.Save()\n"
     "    assert os.path.exists('a.prt') and os.path.getsize('a.prt') > 0\n"),
    ("注释里的 allow-probes 生效",
     "def main():\n"
     "    # check_journal: allow-probes\n"
     "    p = NXOpen.Point3d(0, 0, 0)\n"),
    ("字符串里的 TODO 不是占位符",
     _WP + "    print(\"TODO in text\")\n"),
    ("SaveAs 后校验同一路径",
     _WP + "    wp.SaveAs('a.prt')\n"
           "    assert os.path.exists('a.prt') and os.path.getsize('a.prt') > 0\n"),
    ("两次 SaveAs 各自校验",
     _WP + "    wp.SaveAs('a.prt')\n"
           "    assert os.path.exists('a.prt') and os.path.getsize('a.prt') > 0\n"
           "    wp.SaveAs('b.prt')\n"
           "    assert os.path.exists('b.prt') and os.path.getsize('b.prt') > 0\n"),
]


def run_check(src: str):
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8",
            dir=str(Path(tempfile.gettempdir()))) as f:
        f.write(src)
        path = Path(f.name)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = check_journal.check(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return rc, buf.getvalue()


def main() -> int:
    failures = []
    for name, marker, src, want_rc in COUNTER_EXAMPLES:
        rc, out = run_check(src)
        if rc != want_rc:
            failures.append("%s: 未命中 (rc=%d, 期望 %d)" % (name, rc, want_rc))
        elif marker not in out:
            failures.append("%s: 退出码正确但输出无规则痕迹 %r "
                            "(可能被另一条规则拦截)" % (name, marker))
    clean_samples = [("基础阴性样本", CLEAN_SAMPLE)] + EXTRA_CLEAN
    for name, src in clean_samples:
        rc_clean, out_clean = run_check(src)
        if rc_clean != 0:
            failures.append("%s 被误报 (rc=%d, %s)" %
                            (name, rc_clean, out_clean.strip()[:120]))
    if failures:
        for f in failures:
            print("FAIL check_journal rule selftest - %s" % f)
        return 1
    errors = sum(1 for c in COUNTER_EXAMPLES if c[3] == 1)
    print("PASS check_journal rule selftest - %d 反例命中对应规则（%d 报错级 + %d 提示级）"
          " + %d 阴性通过"
          % (len(COUNTER_EXAMPLES), errors, len(COUNTER_EXAMPLES) - errors,
             len(clean_samples)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
