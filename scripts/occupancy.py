# -*- coding: utf-8 -*-
"""截面占用门：三轴切片 + 体积差 + 连通分量。

旧口径只做 Z 向定站距切片，1 mm 薄腔遇到 1.18 mm 站距会 0 命中，于是
"没有差异"被当成 PASS。这里把三件事分开：

  - 切片：Z/X/Y 三轴，站距由调用方给定；
  - 体积：闭合三角网格的有符号体积差，与切片互为独立证据；
  - 分量：多体/内腔导致的连通分量变化。

判定三态：PASS / FAIL / NO_SIGNAL。站距粗于可检厚度且体积也无差异时给
NO_SIGNAL，绝不把"仪器没看见"写成 PASS。

纯标准库 + `deliverable`/`stl_math`，Python 3.6 兼容；不依赖 numpy/trimesh。
"""
import math

from deliverable import FAIL, NO_SIGNAL, PASS
from stl_math import (components, mesh_bbox, mesh_volume, read_stl_triangles,
                      section_area)


def _stations(lo, hi, pitch):
    """站点取 lo+(k+0.5)*pitch；末格宽 ≤ pitch/2 时该站落到 hi 及以上，
    钳到 hi-1e-4，保证顶面薄层也有站。"""
    if pitch <= 0.0 or hi <= lo:
        return []
    n = int(math.ceil((hi - lo) / pitch))
    if n <= 0:
        return []
    out = []
    for k in range(n):
        s = lo + (k + 0.5) * pitch
        if s >= hi:
            s = hi - 1e-4
        out.append(s)
    return out


def axis_report(ref_mesh, test_mesh, axis, pitch, area_tol=0.5,
                rel_area_tol=0.001):
    box_r = mesh_bbox(ref_mesh)
    box_t = mesh_bbox(test_mesh)
    lo = min(box_r[axis], box_t[axis])
    hi = max(box_r[axis + 3], box_t[axis + 3])
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    rows = []
    for s in _stations(lo, hi, pitch):
        origin = [0.0, 0.0, 0.0]
        origin[axis] = s
        a = section_area(ref_mesh, origin, normal)
        b = section_area(test_mesh, origin, normal)
        delta = abs(a["area"] - b["area"])
        tol = max(area_tol, rel_area_tol * max(abs(a["area"]),
                                               abs(b["area"])))
        loop_delta = a["loops"] != b["loops"]
        # 两侧都无材料：空站，不算命中也不算通过。
        empty = abs(a["area"]) < tol and abs(b["area"]) < tol
        hit = (not empty) and (delta > tol or loop_delta)
        rows.append({"station": s, "ref": a["area"], "test": b["area"],
                     "delta": delta, "ref_loops": a["loops"],
                     "test_loops": b["loops"], "empty": empty,
                     "hit": hit})
    return {
        "axis": "xyz"[axis],
        "pitch": pitch,
        "stations": rows,
        "hits": [r["station"] for r in rows if r["hit"]],
        "measured": [r["station"] for r in rows if not r["empty"]],
        "empty": [r["station"] for r in rows if r["empty"]],
    }


def _uniq(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def occupancy_gate(ref_path, test_path, pitch=1.18, axes=(0, 1, 2),
                   min_feature=None, volume_tol=0.002, area_tol=0.5,
                   bbox_tol=0.05):
    ref_mesh = read_stl_triangles(ref_path)
    test_mesh = read_stl_triangles(test_path)
    codes, notes = [], []
    if not ref_mesh or not test_mesh:
        return {"verdict": NO_SIGNAL, "codes": ["DELIV_E_OCC_MESH"],
                "notes": ["empty mesh"], "report": {}}

    ref_vol = mesh_volume(ref_mesh)
    test_vol = mesh_volume(test_mesh)
    vol_delta = abs(abs(ref_vol) - abs(test_vol))
    rel = vol_delta / max(abs(ref_vol), 1e-12)
    comp_ref = components(ref_mesh)
    comp_test = components(test_mesh)
    box_ref = mesh_bbox(ref_mesh)
    box_test = mesh_bbox(test_mesh)
    box_delta = max(abs(a - b) for a, b in zip(box_ref, box_test))

    reports = {}
    total_hits = 0
    for axis in axes:
        rep = axis_report(ref_mesh, test_mesh, axis, pitch, area_tol)
        reports["xyz"[axis]] = rep
        total_hits += len(rep["hits"])

    # 绝对下限 1 mm³ 挡住切面噪声；相对阈值按参考体积。
    if vol_delta > max(1.0, volume_tol * abs(ref_vol)):
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("volume delta %.4f%% (%.3f -> %.3f)"
                     % (rel * 100.0, abs(ref_vol), abs(test_vol)))
    if total_hits:
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("%d slice stations differ" % total_hits)
    if comp_ref != comp_test:
        codes.append("DELIV_E_OCCUPANCY")
        notes.append("components %d -> %d" % (comp_ref, comp_test))
    if box_delta > bbox_tol:
        codes.append("DELIV_E_OCCUPANCY_BBOX")
        notes.append("bbox delta %.4f" % box_delta)

    if codes:
        codes = _uniq(codes)
        return {"verdict": FAIL, "codes": codes, "notes": notes,
                "report": {"axes": reports, "rel_volume": rel,
                           "components": [comp_ref, comp_test],
                           "bbox_delta": box_delta}}

    # 无差异但站距粗于可检厚度：仪器看不见，给 NO_SIGNAL。
    if min_feature is not None and pitch > min_feature * 0.5:
        return {"verdict": NO_SIGNAL,
                "codes": ["DELIV_E_OCC_NO_SIGNAL"],
                "notes": ["pitch %.3f > min_feature/2 %.3f"
                          % (pitch, min_feature * 0.5)],
                "report": {"axes": reports, "rel_volume": rel,
                           "components": [comp_ref, comp_test],
                           "bbox_delta": box_delta}}
    return {"verdict": PASS, "codes": [], "notes": [],
            "report": {"axes": reports, "rel_volume": rel,
                       "components": [comp_ref, comp_test],
                       "bbox_delta": box_delta}}


if __name__ == "__main__":
    print("use scripts/tests/52_occupancy_gate.py for the shipped selftest")
