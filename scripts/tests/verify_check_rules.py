# -*- coding: utf-8 -*-
"""check_journal.py 规则自检（host 端运行，不进 NX）。

每条新增规则配一个会命中的反例（任务书 §7 步骤 2 的要求：规则必须配会命中的
样本，防规则本身是死的），外加一个干净样本做阴性对照。
RUN_TESTS.bat 末尾以 host 解释器调用（同 verify_anno_pdf 模式）。
判定出口：`PASS check_journal rule selftest` / `FAIL check_journal rule selftest ...`
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_journal  # noqa: E402

# (名, 期望规则痕迹, 反例源码) —— 每例必须命中 [错误] 且退出码 1
COUNTER_EXAMPLES = [
    ("5.17 枚举访问器 0 参调用",
     "枚举属性",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    wp = NXOpen.Session.GetSession().Parts.Work\n"
     "    spring = wp.Axies.CreateSpringBuilder(NXOpen.Features.Feature.Null)\n"
     "    t = spring.AttachmentType()\n"
     "    print(t)\n"),
    ("5.18 CylinderBuilder 枚举成员名",
     "AxisDiameterAndHeight",
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    part = NXOpen.Session.GetSession().Parts.Work\n"
     "    cb = part.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)\n"
     "    cb.Type = NXOpen.Features.CylinderBuilder.Types.AxisAndHeight\n"
     "    cb.Commit()\n"),
    ("5.19 UFDrf 伪容器",
     "UFDrf",
     "import NXOpen\n"
     "import NXOpen.UF\n"
     "\n"
     "\n"
     "def main():\n"
     "    bad = NXOpen.UF.UFDrf\n"
     "    print(bad)\n"),
    ("5.16 from math import dist",
     "3.6.1",
     "from math import dist\n"
     "import NXOpen\n"
     "\n"
     "\n"
     "def main():\n"
     "    print(dist((0.0, 0.0), (3.0, 4.0)))\n"),
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


def run_check(src: str):
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8",
            dir=str(Path(tempfile.gettempdir()))) as f:
        f.write(src)
        path = Path(f.name)
    try:
        rc = check_journal.check(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return rc


def main() -> int:
    failures = []
    for name, marker, src in COUNTER_EXAMPLES:
        rc = run_check(src)
        if rc != 1:
            failures.append("%s: 反例未命中 (rc=%d, 规则失效?)" % (name, rc))
    rc_clean = run_check(CLEAN_SAMPLE)
    if rc_clean != 0:
        failures.append("阴性对照被误报 (rc=%d, 规则过严?)" % rc_clean)
    if failures:
        for f in failures:
            print("FAIL check_journal rule selftest - %s" % f)
        return 1
    print("PASS check_journal rule selftest - %d 反例命中 + 1 阴性通过"
          % len(COUNTER_EXAMPLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
