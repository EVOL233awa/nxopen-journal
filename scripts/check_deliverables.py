# -*- coding: utf-8 -*-
"""宿主侧交付件门：STEP / STL / DXF / PMI / 占用。

输入是 NX journal 落盘的 facts.json（B-rep 事实）与导出文件路径。
三态出口：PASS=0，FAIL=1，NO_SIGNAL=3（仪器看不见，例如缺 ezdxf）。
错误码统一 DELIV_E_*，与 deliverable.py 一致。

例：
    python scripts/check_deliverables.py --facts facts.json \\
        --step out.stp --stl out.stl --dxf out.dxf --schema AP242 \\
        --pmi FLATNESS_TOLERANCE=1
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import deliverable as d  # noqa: E402
import occupancy as o  # noqa: E402


def parse_pmi(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit("--pmi expects TYPE=COUNT: %s" % item)
        typ, count = item.split("=", 1)
        out[typ.strip()] = int(count)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts")
    ap.add_argument("--step")
    ap.add_argument("--stl")
    ap.add_argument("--dxf")
    ap.add_argument("--pdf")
    ap.add_argument("--pdf-expect", action="append")
    ap.add_argument("--pdf-min-words", type=int, default=20)
    ap.add_argument("--schema")
    ap.add_argument("--pmi", action="append")
    ap.add_argument("--dxf-units", type=int, default=4)
    ap.add_argument("--dxf-dims", type=int)
    ap.add_argument("--occupancy-ref")
    ap.add_argument("--occupancy-pitch", type=float, default=1.18)
    ap.add_argument("--min-feature", type=float)
    ap.add_argument("--volume-tol", type=float, default=0.001)
    ap.add_argument("--occupancy-volume-tol", type=float, default=0.002)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    facts = None
    if args.facts:
        with open(args.facts, encoding="utf-8") as fh:
            facts = json.load(fh)

    results = {}
    if facts is not None:
        results["part"] = d.part_gate(facts)
    if args.step:
        census = d.step_census(args.step)
        results["step"] = d.step_gate(
            census, facts, schema=args.schema, pmi=parse_pmi(args.pmi))
        if args.pmi:
            results["pmi"] = d.pmi_gate(census, parse_pmi(args.pmi))
    if args.stl:
        results["stl"] = d.stl_gate(
            d.stl_census(args.stl), facts, volume_tol=args.volume_tol)
    if args.dxf:
        results["dxf"] = d.dxf_gate(
            d.dxf_census(args.dxf), args.dxf_units, args.dxf_dims)
    if args.occupancy_ref:
        if not args.stl:
            raise SystemExit("--occupancy-ref needs --stl as the built mesh")
        results["occupancy"] = o.occupancy_gate(
            args.occupancy_ref, args.stl, pitch=args.occupancy_pitch,
            min_feature=args.min_feature,
            volume_tol=args.occupancy_volume_tol)
    if args.pdf:
        try:
            from render import pdf_audit
        except ImportError:
            results["pdf"] = d._no_signal(
                ["DELIV_E_PDF_UNAVAILABLE"], ["render.pdf_audit missing"])
        else:
            results["pdf"] = pdf_audit.pdf_gate(
                args.pdf, expect=args.pdf_expect,
                min_words=args.pdf_min_words)

    if not results:
        raise SystemExit("nothing to check")
    summary = d.gate_summary(results)
    for name in sorted(results):
        print(d.format_result(name, results[name]))
    print("DELIV_RESULT=%s codes=%s"
          % (summary["verdict"], ",".join(summary["codes"]) or "-"))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"results": results, "summary": summary}, fh, indent=2)
    return {"PASS": 0, "FAIL": 1, "NO_SIGNAL": 3}[summary["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
