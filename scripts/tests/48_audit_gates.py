# -*- coding: utf-8 -*-
# Test 48: audit gates must fail closed (nxlib.audit / measure / reverse /
# template, reverse-engineering section 4 / 10 / 12).
#
# Every gate here was, until now, able to report a pass on evidence that does
# not support one.  The cases below pin each hole shut, so a regression is a red
# test rather than a silently green delivery:
#
#   - an empty section used to report IoU 1.0 and pass G1 (both meshes empty);
#   - an empty primary denominator used to report G1full gate_pass=True;
#   - liveness ignored parameters that were declared but never built;
#   - G9 counted features without ever asking whether they carry a structure id;
#   - structure-table validation accepted faces that no structure explains;
#   - a schema could list one name as both an independent parameter and a
#     derived/data quantity.
#
# The meshes are synthetic solids; nothing here depends on a real part.
import math
import os
import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
import nxlib.measure as ms
import nxlib.audit as ad
import nxlib.reverse as rv
import nxlib.template as tpl


def cube_mesh(s=10.0):
    """Closed cube at 0..s: 12 triangles with outward normals.

    `section_outline` orients segments by the triangle normal, so a sheet with
    mixed winding would produce open chains instead of a loop.
    """
    p = [(0.0, 0.0, 0.0), (s, 0.0, 0.0), (s, s, 0.0), (0.0, s, 0.0),
         (0.0, 0.0, s), (s, 0.0, s), (s, s, s), (0.0, s, s)]

    def n(v0, v1, v2):
        ax = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
        bx = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
        c = (ax[1] * bx[2] - ax[2] * bx[1], ax[2] * bx[0] - ax[0] * bx[2],
             ax[0] * bx[1] - ax[1] * bx[0])
        ln = math.sqrt(sum(x * x for x in c)) or 1.0
        return [x / ln for x in c]

    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    tris = []
    for a, b, c, d in quads:
        for t in ((p[a], p[b], p[c]), (p[a], p[c], p[d])):
            tris.append((n(*t), list(t[0]), list(t[1]), list(t[2])))
    return tris


class FakeFeature(object):
    def __init__(self, tag, name, typ="EXTRUDE", parents=()):
        self.Tag = tag
        self.Name = name
        self.FeatureType = typ
        self._parents = list(parents)

    def GetParents(self):
        return [FakeFeature(t, "p%d" % t) for t in self._parents]


class FakePart(object):
    def __init__(self, features):
        self.Features = features
        self.Bodies = []


def station(z, sources=("plane#0",), kind="plane"):
    return {"origin": [0.0, 0.0, z], "normal": [0.0, 0.0, 1.0],
            "sources": list(sources), "kind": kind}


def case_empty_section():
    """Both-empty section is unmeasured, not a perfect match."""
    cube = cube_mesh()
    inside = ms.section_iou(cube, cube, [0.0, 0.0, 5.0], [0.0, 0.0, 1.0])
    outside = ms.section_iou(cube, cube, [0.0, 0.0, 100.0], [0.0, 0.0, 1.0])
    say("inside iou=%s both_empty=%s | outside iou=%s both_empty=%s"
        % (inside["iou"], inside["both_empty"], outside["iou"],
           outside["both_empty"]))
    check("T48_INSIDE_MEASURED", inside["iou"] is not None and
          not inside["both_empty"], "inside cut must be measured: %r" % inside)
    check("T48_OUTSIDE_EMPTY", outside["both_empty"] is True and
          outside["iou"] is None,
          "a cut missing both bodies must not report IoU: %r" % outside)

    # 空站必须分类：z=100 没有材料（站位落在材料空档 = 站表噪声），z=10 与
    # 立方体顶面共面（原件在那里有材料，只是 STL 求交看不到共面交线）。
    # 二者都不是 PASS，也不能改写有读数站的形状判定。
    rep = ms.station_report(cube, cube,
                            {"stations": [station(5.0), station(100.0),
                                          station(10.0, ("plane#1",))],
                             "dropped": 0})
    reasons = [r["na_reason"] for r in rep["stations"]]
    say("station_report na=%r na_reasons=%r noise=%r instrument=%r "
        "measured=%d complete=%s pass=%s"
        % (rep["na"], reasons, rep["plan_noise"], rep["instrument_errors"],
           rep["measured_count"], rep["plan_measured_complete"], rep["pass"]))
    check("T48_STATION_NA",
          rep["na"] == [1, 2] and
          reasons == [None, "no_material", "coplanar_section"] and
          rep["unmeasured"] == [1, 2] and
          rep["plan_noise"] == [1] and
          rep["instrument_errors"] == [2] and
          rep["measured_count"] == 1 and
          rep["plan_measured_complete"] is False and rep["pass"] is True,
          "an empty station is unmeasured, not a pass: %r" % (rep,))
    check("T48_STATION_NA_EMPTY_PLAN",
          ms.station_report(cube, cube,
                            {"stations": [], "dropped": 0})["pass"] is False,
          "an empty station plan must not pass")

    # 判定口径（hybrid）的两条分别处理：
    #  - 原件在站位处没有材料（`no_material`，这里的 z=100）→ 站表噪声，
    #    从"该量到的站"里剔除并单列；它不是任何自建件能通过的站；
    #  - 原件有材料却没量到（`coplanar_section`，z=10 与顶面共面）→ 仪器
    #    误差，门不通过。
    gate = ms.station_report_hybrid(
        cube, cube, None, None,
        {"stations": [station(5.0, ("axis#0",), "axis"),
                      station(100.0, ("axis#1",), "axis")],
         "dropped": 0})
    say("hybrid noise unmeasured=%r noise=%r pass=%s complete=%s reasons=%r"
        % (gate["unmeasured"], gate["plan_noise"], gate["pass"],
           gate["plan_measured_complete"], gate["reasons"]))
    check("T48_HYBRID_EXCLUDES_PLAN_NOISE",
          gate["unmeasured"] == [1] and gate["plan_noise"] == [1] and
          gate["pass"] is True and
          gate["plan_measured_complete"] is True,
          "a station with no reference material is plan noise, not a blocker: "
          "%r" % (gate,))
    gate2 = ms.station_report_hybrid(
        cube, cube, None, None,
        {"stations": [station(5.0, ("axis#0",), "axis"),
                      station(10.0, ("axis#1",), "axis")],
         "dropped": 0})
    say("hybrid instrument unmeasured=%r instrument=%r pass=%s reasons=%r"
        % (gate2["unmeasured"], gate2["instrument_errors"], gate2["pass"],
           gate2["reasons"]))
    check("T48_HYBRID_BLOCKS_INSTRUMENT",
          gate2["instrument_errors"] == [1] and gate2["pass"] is False and
          gate2["plan_measured_complete"] is False,
          "a station whose reference material could not be measured must not "
          "pass: %r" % (gate2,))


def case_g1full_empty_denominator():
    """No primary stations -> G1full must not pass."""
    cube = cube_mesh()
    # one axis station fed by one cylinder group; the group's faces are all
    # declared fillet, so the station classifies as fillet and primary is empty
    measure = {"faces": [], "cylinders": [{"faces": [1, 2], "axis": [0, 0, 1],
                                           "point": [0, 0, 0], "radius": 3.0,
                                           "extent": [0.0, 10.0],
                                           "kind": ms.CYLINDER,
                                           "length": 10.0}],
               "cones": []}
    plan = {"stations": [station(5.0, sources=("axis#0",), kind="axis")],
            "dropped": 0, "complete": True}
    g1 = ad.g1full(None, None, plan, measure, {1, 2},
                   meshes=(cube, cube))
    say("g1full primary=%s gate_pass=%s empty=%s"
        % (g1["primary"]["count"], g1["primary"]["gate_pass"],
           g1["primary"]["empty_denominator"]))
    check("T48_G1FULL_EMPTY_PRIMARY",
          g1["primary"]["count"] == 0 and
          g1["primary"]["gate_pass"] is False and
          g1["primary"]["empty_denominator"] is True,
          "an empty primary denominator must fail, got %r" % g1["primary"])
    check("T48_G1FULL_PLAN_COMPLETE_FALSE",
          g1["plan_complete"] is False,
          "empty primary must leave plan_complete false: %r"
          % g1["plan_complete"])


def case_g1full_plan_noise():
    """A station with no reference material is plan noise, not a blocker."""
    cube = cube_mesh()
    # two primary axis stations from one cylinder group: z=5 cuts material on
    # both sides, z=100 sits in air (a coaxial group's inter-face gap does this
    # in real plans).  Both are primary because no fillet faces are declared.
    measure = {"faces": [], "cylinders": [{"faces": [1, 2, 3],
                                           "axis": [0.0, 0.0, 1.0],
                                           "point": [0.0, 0.0, 0.0],
                                           "radius": 3.0,
                                           "extent": [0.0, 10.0],
                                           "kind": ms.CYLINDER,
                                           "length": 10.0}],
               "cones": []}
    plan = {"stations": [station(5.0, ("axis#0",), "axis"),
                         station(100.0, ("axis#1",), "axis")],
            "dropped": 0, "missing": []}
    g1 = ad.g1full(None, None, plan, measure, [],
                   meshes=(cube, cube), hybrid=True)
    prim = g1["primary"]
    say("g1full noise: %r" % prim)
    check("T48_G1FULL_PLAN_NOISE_EXCLUDED",
          prim["plan_noise"] == [1] and prim["failed"] == [] and
          prim["instrument_errors"] == [] and
          prim["denominator"] == 1 and prim["pass"] == 1 and
          abs(prim["ratio"] - 1.0) < 1e-9 and
          abs(prim["ratio_all_stations"] - 0.5) < 1e-9 and
          prim["gate_pass"] is True,
          "plan noise must be excluded from the denominator and reported: %r"
          % (prim,))


def case_cut_plan_coplanar():
    """STL 判定口径的平面站：偏移证据必须齐，偏移方向要有独立依据。"""
    cube = cube_mesh()
    plan = {"stations": [station(5.0, sources=("plane#0",))]}
    cuts = ms.cut_stations(cube, plan, 0.0137)
    c = cuts[0]
    say("cut coplanar=%s offset_mm=%s dir=%s basis=%s" %
        (c["coplanar"], c["offset_mm"], c["offset_dir"], c["offset_basis"]))
    check("T48_CUT_COPLANAR_FLAG",
          c["coplanar"] is True and c["offset_mm"] == 0.0137 and
          c["offset_dir"] in (1.0, -1.0) and
          c["offset_basis"] == "section_area",
          "plane station must carry coplanar/offset evidence: %r" % c)
    # 有面表时偏移方向取几何事实：共面平面面的外法向反向
    faces = [{"type": ms.PLANE, "point": [0.0, 0.0, 5.0],
              "dir": [0.0, 0.0, 1.0], "area": 100.0}]
    cf = ms.cut_stations(cube, plan, 0.0137, faces)[0]
    say("cut with faces dir=%s basis=%s origin_z=%.6f" %
        (cf["offset_dir"], cf["offset_basis"], cf["origin"][2]))
    check("T48_CUT_FACE_NORMAL_SIDE",
          cf["offset_basis"] == "face_normal" and cf["offset_dir"] == -1.0 and
          cf["origin"][2] < 5.0,
          "a coplanar face normal decides the material side: %r" % cf)
    # 源面方向冲突（薄壁两侧）时退回截面积判据，不猜
    two = faces + [{"type": ms.PLANE, "point": [0.0, 0.0, 5.0],
                    "dir": [0.0, 0.0, -1.0], "area": 100.0}]
    c2 = ms.cut_stations(cube, {"stations": [station(5.0, ("plane#0",
                                                           "plane#1"))]},
                         0.0137, two)[0]
    check("T48_CUT_CONFLICT_FALLS_BACK",
          c2["offset_basis"] == "section_area",
          "contradicting source normals must fall back to the area rule: %r"
          % c2)
    # 轴站也带 13.7 µm 偏移（沿站位法向），避免擦到端面共面三角
    ca = ms.cut_stations(cube, {"stations": [station(5.0, ("axis#0",),
                                                    "axis")]})[0]
    check("T48_CUT_AXIS_OFFSET_NOT_COPLANAR",
          ca["coplanar"] is False and ca["offset_dir"] == 1.0 and
          ca["offset_basis"] is None and
          abs(ca["origin"][2] - (5.0 + 0.0137)) < 1e-9,
          "axis stations keep the nominal cut depth without a coplanar flag: %r"
          % ca)
    kept = ms.cut_plan(cube, {"stations": plan["stations"], "dropped": 7})
    check("T48_CUT_PLAN_KEEPS_BUDGET",
          kept["dropped"] == 7 and len(kept["stations"]) == 1,
          "cut_plan must keep the budget fields of the source plan: %r"
          % (kept["dropped"],))


def case_structure_table_unassigned():
    """Faces no structure explains are an error, not a warning."""
    measure = {"faces": [{"tag": 1}, {"tag": 2}, {"tag": 3}]}
    res = rv.validate_structure_table(
        [{"id": "A", "faces": [1]}, {"id": "B", "faces": [2]}], measure)
    say("validate unassigned=%s complete=%s errors=%d"
        % (res["unassigned"], res["complete"], len(res["errors"])))
    check("T48_UNASSIGNED_IS_ERROR",
          res["unassigned"] == [3] and res["complete"] is False,
          "face 3 is unexplained and must be an error: %r" % res)
    ok = rv.validate_structure_table([{"id": "A", "faces": [1, 2, 3]}],
                                     measure)
    check("T48_ASSIGNED_COMPLETE", ok["complete"] is True,
          "a full assignment must validate: %r" % ok["errors"])
    exempt = rv.validate_structure_table(
        [{"id": "A", "faces": [1]}], measure, allow_unassigned=[2, 3])
    check("T48_EXEMPT_OK", exempt["complete"] is True,
          "explicit exemptions must validate: %r" % exempt["errors"])


def case_feature_mapping():
    part = FakePart([FakeFeature(1, "PLATE_MAIN"),
                     FakeFeature(2, "PLATE_RIB"),
                     FakeFeature(3, "")])
    res = rv.validate_feature_mapping(part, [{"id": "PLATE"},
                                             {"id": "ARM"}])
    say("feature mapping unmapped=%s unnamed=%s"
        % (res["unmapped"], res["unnamed"]))
    check("T48_UNNAMED_FEATURE_ERROR",
          res["unnamed"] == [3] and res["complete"] is False,
          "an empty feature name must be an error: %r" % res)
    check("T48_UNMAPPED_STRUCTURE_ERROR", res["unmapped"] == ["ARM"],
          "a structure with no named feature must be reported: %r"
          % res["unmapped"])
    clean = FakePart([FakeFeature(1, "PLATE_MAIN"),
                      FakeFeature(2, "ARM_SHAFT")])
    ok = rv.validate_feature_mapping(clean, [{"id": "PLATE"}, {"id": "ARM"}])
    check("T48_MAPPING_OK", ok["complete"] is True, "%r" % ok["errors"])


def case_g9_names():
    """G9 without name mapping used to pass on count alone."""
    part = FakePart([FakeFeature(i, "Extrude(%d)" % i)
                     for i in range(1, 13)])
    g9 = ms.g9_structure(part, [{"id": "PLATE"}, {"id": "ARM"}])
    say("g9 reasons=%s" % g9["reasons"])
    check("T48_G9_DEFAULT_NAMES_REJECTED",
          g9["pass"] is False and
          any("default names" in r for r in g9["reasons"]),
          "features with NX default names must fail G9: %r" % g9["reasons"])
    mapped = FakePart([FakeFeature(1, "PLATE_MAIN"),
                       FakeFeature(2, "ARM_SHAFT"),
                       FakeFeature(3, "PLATE_RIB"),
                       FakeFeature(4, "ARM_RIB")])
    ok = ms.g9_structure(mapped, [{"id": "PLATE"}, {"id": "ARM"}])
    check("T48_G9_MAPPED_PASS", ok["pass"] is True, "%r" % ok["reasons"])
    check("T48_G9_SOURCE", ok["structure_count_source"] == "structure_table",
          "structure count must come from a table: %r"
          % ok["structure_count_source"])


def case_station_plan_full_coverage():
    """Coverage is decided on face ownership, and missing blocks complete."""
    measure = {"faces": [{"tag": 10, "type": ms.PLANE,
                          "point": [0.0, 0.0, 0.0], "dir": [0.0, 0.0, 1.0]},
                         {"tag": 11, "type": ms.PLANE,
                          "point": [0.0, 0.0, 20.0], "dir": [0.0, 0.0, 1.0]}],
               "cylinders": [], "cones": []}
    plan = rv.station_plan_full(measure, [{"id": "P1", "faces": [10]},
                                          {"id": "P2", "faces": [11]},
                                          {"id": "P3", "faces": [99]}])
    say("plan_full stations=%d cover=%s missing=%s complete=%s families=%d"
        % (len(plan["stations"]), plan["structure_coverage"], plan["missing"],
           plan["complete"], len(plan["plane_families"])))
    check("T48_PLAN_FULL_MISSING_BLOCKS",
          plan["missing"] == ["P3"] and plan["complete"] is False,
          "a structure with no station must block complete: %r" % plan["missing"])
    check("T48_PLAN_FULL_FAMILIES",
          len(plan["plane_families"]) >= 1,
          "plane families must be reported: %r" % plan["plane_families"])
    check("T48_PLAN_FULL_FILLET_CLASS",
          all("primary_fillet_class" in s for s in plan["stations"]),
          "every station must carry primary_fillet_class")


def case_liveness_and_budget():
    """budget binds feature names to structure ids; the fake part has none."""
    part = FakePart([FakeFeature(1, "PLATE_MAIN"),
                     FakeFeature(2, "PLATE_RIB"),
                     FakeFeature(3, "ARM_RIB")])
    b = ad.budget(part, [{"id": "PLATE"}, {"id": "ARM"}])
    say("budget pass=%s source=%s unmapped=%s"
        % (b["pass"], b["structure_count_source"],
           b["unmapped_structures"]))
    check("T48_BUDGET_TABLE_BOUND",
          b["structure_count_source"] == "structure_table" and b["pass"] is True,
          "a fully mapped table must pass: %r" % b)
    b2 = ad.budget(part, [{"id": "PLATE"}, {"id": "MISSING"}])
    check("T48_BUDGET_UNMAPPED_REJECTED",
          b2["pass"] is False and b2["unmapped_structures"] == ["MISSING"],
          "an unmapped structure must fail the budget: %r" % b2)


def case_schema_validation():
    schema = {"build_order": ["A"],
              "structures": [{"id": "A", "template": "plate",
                              "parameters": [{"name": "T", "value": 10.0}],
                              "data": ["T"]}]}
    res = tpl.validate_schema(schema)
    say("schema errors=%s" % res["errors"])
    check("T48_SCHEMA_DESIGN_DATA_MIX",
          res["complete"] is False and
          any("both design and data" in e.get("reason", "")
              for e in res["errors"]),
          "one name cannot be both design and data: %r" % res["errors"])
    bad = {"structures": [{"id": "A", "template": "unassigned"},
                          {"id": "A", "template": "plate"}]}
    res2 = tpl.validate_schema(bad)
    reasons = [e.get("reason", "") for e in res2["errors"]]
    check("T48_SCHEMA_DUP_IDS_AND_TEMPLATE",
          any("duplicate" in r for r in reasons) and
          any("unassigned" in r for r in reasons) and
          any("build_order" in r for r in reasons),
          "duplicate id / unassigned template / missing order all error: %r"
          % reasons)
    good = {"build_order": ["A"],
            "structures": [{"id": "A", "template": "plate",
                            "parameters": [{"name": "T", "value": 10.0}],
                            "data": ["AXIS"]}]}
    ok = tpl.validate_schema(good)
    check("T48_SCHEMA_OK", ok["complete"] is True, "%r" % ok["errors"])


def case_param_table_layering():
    doc = {"structures": [{"id": "A", "parameters": [
        {"name": "R", "value": 5.0, "unit": "mm", "kind": "design"},
        {"name": "AX", "value": 1.0, "unit": "unit", "kind": "data"},
        {"name": "HA", "value": 4.0, "unit": "deg", "kind": "data",
         "derived_from": ["R", "L"]}]}]}
    values, units = tpl.param_table(doc)
    say("param_table names=%s" % sorted(values))
    check("T48_PARAM_TABLE_DESIGN_ONLY", sorted(values) == ["R"],
          "data/derived rows must not become independent parameters: %r"
          % sorted(values))
    allv, _ = tpl.param_table(doc, include_data=True)
    check("T48_PARAM_TABLE_INCLUDE_DATA", sorted(allv) == ["AX", "HA", "R"],
          "include_data must return every scalar: %r" % sorted(allv))
    names = tpl.structure_param_names(doc, "A")
    check("T48_STRUCTURE_PARAM_NAMES", names == ["R", "AX", "HA"],
          "structure_param_names must preserve order: %r" % names)


def main():
    case_empty_section()
    case_g1full_empty_denominator()
    case_g1full_plan_noise()
    case_cut_plan_coplanar()
    case_structure_table_unassigned()
    case_feature_mapping()
    case_g9_names()
    case_station_plan_full_coverage()
    case_liveness_and_budget()
    case_schema_validation()
    case_param_table_layering()
    failed = [n for n, good in RESULTS if not good]
    say("TEST48_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST48_FAIL failed=%s" % failed)
        return
    say("TEST48_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST48_FATAL:\n" + traceback.format_exc()[-1200:])
        say("TEST48_FAIL uncaught")
