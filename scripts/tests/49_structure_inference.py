# -*- coding: utf-8 -*-
# Test 49: structure inference -- measurement in, structure table out.
#
# Section 12.1/12.2: the delivery route compiles the measurement into a frozen
# structure table before a single feature is built.  This test feeds synthetic
# face tables (no NX needed) to the inference layer and checks:
#
#   - planar families and thickness bands come from normals/offsets, not from
#     face order or names;
#   - a plate + boss + stepped coaxial hole produce plate / hub / hole-chain
#     rows, every row carrying evidence faces, and the hole segments keep their
#     own dia/length (the R24 failure mode was one straight bore instead);
#   - structures that need face sampling (eye lobes, longitudinal profiles) are
#     reported as unresolved with a next probe instead of being guessed;
#   - a stack of parallel planes (the fingerprint of a per-slice feature tree)
#     is refused: no plate row, an unresolved row with evidence;
#   - two report writes are byte-identical (the table cannot wobble);
#   - validation stations are grouped per structure id, and a structure with no
#     station is reported missing.
import hashlib
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
import nxlib.structure_inference as si
import nxlib.transitions as tr

PLANE, CYL, CONE, TORUS = ms.PLANE, ms.CYLINDER, ms.CONE, ms.TORUS


def plane_face(tag, point, direction, area=100.0):
    return {"tag": tag, "type": PLANE, "point": point, "dir": direction,
            "area": area}


def cyl(tag, point, direction, radius, norm_dir=1, area=10.0):
    return {"tag": tag, "type": CYL, "point": point, "dir": direction,
            "radius": radius, "norm_dir": norm_dir, "area": area}


def cone_face(tag, point, direction, radius, half_rad, norm_dir=1,
              area=10.0):
    return {"tag": tag, "type": CONE, "point": point, "dir": direction,
            "radius": radius, "rad_data": half_rad, "norm_dir": norm_dir,
            "area": area}


def plate_boss_hole():
    """80x50x12 plate, boss on top, stepped coaxial bore through both."""
    # areas: the broad faces (top/bottom, 80x50) dominate the side faces, so
    # the thickness direction is z -- the x/y "bands" are outline extents.
    faces = [
        plane_face(1, [0.0, 0.0, 0.0], [0.0, 0.0, -1.0], area=4000.0),
        plane_face(2, [0.0, 0.0, 12.0], [0.0, 0.0, 1.0], area=4000.0),
        plane_face(3, [-40.0, 0.0, 6.0], [-1.0, 0.0, 0.0], area=600.0),
        plane_face(4, [40.0, 0.0, 6.0], [1.0, 0.0, 0.0], area=600.0),
        plane_face(5, [0.0, -25.0, 6.0], [0.0, -1.0, 0.0], area=960.0),
        plane_face(6, [0.0, 25.0, 6.0], [0.0, 1.0, 0.0], area=960.0),
        plane_face(7, [0.0, 0.0, 24.0], [0.0, 0.0, 1.0], area=452.0),
        cyl(10, [0.0, 0.0, 12.0], [0.0, 0.0, 1.0], 12.0),
        cyl(11, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 5.0, norm_dir=-1),
        cyl(12, [0.0, 0.0, 12.0], [0.0, 0.0, 1.0], 7.0, norm_dir=-1),
        cone_face(13, [0.0, 0.0, 24.0], [0.0, 0.0, 1.0], 5.0, 0.7854,
             norm_dir=-1),
    ]
    cylinders = [
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 12.0],
         "radius": 12.0, "faces": [10], "extent": [0.0, 12.0], "length": 12.0,
         "bbox": [-12.0, -12.0, 12.0, 12.0, 12.0, 24.0], "concave": False,
         "segments": [{"faces": [10], "extent": [0.0, 12.0], "length": 12.0}]},
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 0.0],
         "radius": 5.0, "faces": [11], "extent": [0.0, 12.0], "length": 12.0,
         "bbox": [-5.0, -5.0, 0.0, 5.0, 5.0, 12.0], "concave": True,
         "segments": [{"faces": [11], "extent": [0.0, 12.0],
                       "length": 12.0}]},
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 12.0],
         "radius": 7.0, "faces": [12], "extent": [0.0, 12.0], "length": 12.0,
         "bbox": [-7.0, -7.0, 12.0, 7.0, 7.0, 24.0], "concave": True,
         "segments": [{"faces": [12], "extent": [0.0, 12.0],
                       "length": 12.0}]},
    ]
    cones = [
        {"kind": CONE, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 24.0],
         "radius": 5.0, "half_angle_deg": 45.0, "faces": [13],
         "extent": [0.0, 5.0], "length": 5.0, "concave": True,
         "bbox": [-5.0, -5.0, 24.0, 5.0, 5.0, 29.0]},
    ]
    return {"faces": faces, "cylinders": cylinders, "cones": cones,
            "bodies": 1, "volume": 1.0}


def parallel_stack(n=9):
    """A per-slice feature tree: n parallel planes, no coaxial groups."""
    faces = []
    tag = 100
    for i in range(n):
        faces.append(plane_face(tag, [0.0, 0.0, float(i)], [0.0, 0.0, 1.0]))
        tag += 1
    return {"faces": faces, "cylinders": [], "cones": [], "bodies": 1}


def main():
    meas = plate_boss_hole()
    graph = si.face_graph(meas)
    say("graph faces=%d counts=%r"
        % (len(graph["faces"]), graph["counts"]))
    check("T49_GRAPH_ALL_FACES", len(graph["faces"]) == len(meas["faces"]),
          "every face must appear in the graph: %d/%d"
          % (len(graph["faces"]), len(meas["faces"])))
    check("T49_GRAPH_FILLET_ROLE",
          all(r["role"] == si.ROLE_FILLET for r in graph["faces"]
              if r["type"] == TORUS),
          "torus faces are fillets by type")

    families = si._planar_families(meas)
    z_fam = [f for f in families if abs(abs(f["normal"][2]) - 1.0) < 1e-6]
    say("families=%r" % ([(f["normal"], f["count"]) for f in families],))
    # 平面法向朝外：±Z 是同一族的两个方向（反向平行按同族处理），
    # 偏置一律按族法向取有符号距离，板厚才不丢。
    check("T49_FAMILY_BY_NORMAL",
          len(families) == 3 and len(z_fam) == 1 and z_fam[0]["count"] == 3 and
          sorted(f["count"] for f in families) == [1, 2, 2, 3][1:],
          "3 normal families (z: 3 offsets, x: 2, y: 2): %r"
          % ([(f["normal"], f["count"]) for f in families],))

    bands = si._bands(families)
    z_band = [b for b in bands if abs(abs(b["normal"][2]) - 1.0) < 1e-6]
    say("bands=%r" % ([(b["normal"], b["offsets"]) for b in bands],))
    check("T49_BAND_OFFSETS",
          len(z_band) == 1 and len(z_band[0]["offsets"]) == 3 and
          [p["thickness"] for p in z_band[0]["pairs"]] == [12.0, 12.0],
          "the z band must carry three offsets and two 12 mm pairs: %r"
          % (z_band,))

    result = si.infer_structures(meas)
    rows = result["structures"]
    templates = sorted(set(r["template"] for r in rows))
    say("structures=%r unresolved=%d templates=%r"
        % ([(r["id"], r["role"], r["template"], r["evidence_faces"])
            for r in rows], len(result["unresolved"]), templates))
    check("T49_ROWS_HAVE_EVIDENCE",
          rows and all(r["evidence_faces"] for r in rows),
          "every structure row needs evidence faces: %r" % (rows,))
    check("T49_IDS_UNIQUE",
          len(set(r["id"] for r in rows)) == len(rows),
          "ids=%r" % ([r["id"] for r in rows],))
    check("T49_BUILD_ORDER",
          [r["build_order"] for r in rows] == list(range(len(rows))),
          "build order must be 0..n-1 in table order: %r"
          % ([r["build_order"] for r in rows],))
    plates = [r for r in rows if r["role"] == "plate"]
    check("T49_PLATE_ROW",
          plates and all(r["template"] == "plate_2p5d" for r in plates) and
          min(r["thickness"] for r in plates) == 12.0,
          "the 12 mm thickness band must become a plate row: %r"
          % ([(r["id"], r["thickness"]) for r in plates],))
    check("T49_PLATE_THICKNESS_DIRECTION",
          any(abs(r["thickness"] - 12.0) < 1e-9 for r in plates) and
          not any(abs(r["thickness"] - 80.0) < 1e-9 or
                  abs(r["thickness"] - 50.0) < 1e-9 for r in plates),
          "the thickness direction is the broad-face pair; the x/y bands are "
          "outline extents and must not become plates: %r"
          % ([(r["id"], r["thickness"]) for r in plates],))
    check("T49_BOSS_ROW",
          any(r["role"] == "hub" and r["template"] == "cylinder"
              and r["evidence_faces"] == [10] for r in rows),
          "the boss cylinder must be a hub row: %r" % (rows,))
    holes = [r for r in rows if r["role"] == "hole_chain"]
    say("holes=%r" % ([(r["id"], r["template"],
                        [s for s in (r.get("segments") or [])])
                       for r in holes],))
    kinds = sorted(set(s["kind"] for s in holes[0]["segments"])) if holes         else []
    radii = sorted(s["radius"] for s in holes[0]["segments"]) if holes else []
    check("T49_HOLE_CHAIN_SEGMENTS",
          len(holes) == 1 and holes[0]["template"] == "hole_chain" and
          len(holes[0]["segments"]) == 3 and kinds == ["cone", "cylinder"],
          "the two coaxial bores plus the cone mouth are ONE chain (the chain "
          "is the coaxial-line group, not one chain per segment): %r"
          % ([(r["id"], r["n_segments"] if "n_segments" in r else
               len(r.get("segments") or [])) for r in holes],))
    check("T49_HOLE_CHAIN_KEEPS_RADII",
          len(holes) == 1 and 12.0 not in radii and len(set(radii)) == 2,
          "each bore keeps its own radius and the boss OD (12 mm, convex) must "
          "never join the chain: %r" % (radii,))
    check("T49_HOLE_CHAIN_LENGTHS",
          all(s.get("length") is not None for s in holes[0]["segments"]),
          "every segment keeps its own axial length (one straight bore was the "
          "R24 failure mode): %r" % (holes[0]["segments"],))
    check("T49_UNRESOLVED_NEEDS_PART",
          result["unresolved"] and
          all(u.get("next_probe") for u in result["unresolved"]),
          "sampling-dependent structures must be unresolved with a probe: %r"
          % (result["unresolved"],))
    check("T49_NO_GUESSED_EYE",
          not any(r["template"] in ("eye_2lobe", "clevis") for r in rows),
          "eye/clevis must not be guessed without boundary sampling: %r"
          % (templates,))

    # determinism: two writes must be byte-identical
    p1 = os.path.join(_here, "parts", "t49_report_a.json")
    p2 = os.path.join(_here, "parts", "t49_report_b.json")
    if not os.path.isdir(os.path.dirname(p1)):
        os.makedirs(os.path.dirname(p1))
    si.inference_report(si.infer_structures(meas), p1)
    si.inference_report(si.infer_structures(meas), p2)
    h1 = hashlib.sha256(open(p1, "rb").read()).hexdigest()
    h2 = hashlib.sha256(open(p2, "rb").read()).hexdigest()
    say("report sha=%s/%s" % (h1[:12], h2[:12]))
    check("T49_REPORT_DETERMINISTIC", h1 == h2,
          "the inferred table must be reproducible byte for byte")

    # negative: a parallel plane stack is not a plate
    stack = parallel_stack(9)
    bad = si.infer_structures(stack)
    say("stack structures=%r unresolved=%r"
        % ([(r["id"], r["template"]) for r in bad["structures"]],
           [u["reason"][:60] for u in bad["unresolved"]]))
    check("T49_STACK_REFUSED",
          not any(r["template"] == "plate_2p5d" for r in bad["structures"]) and
          any("stack" in u["reason"] for u in bad["unresolved"]) and
          any(u["evidence_faces"] for u in bad["unresolved"]),
          "a 9-offset parallel stack must be refused with evidence, not turned "
          "into plate rows: %r" % (bad["unresolved"],))

    # stations per structure: ordered table, missing reported
    plan = si.plan_validation_stations(meas, result)
    say("stations missing=%r complete=%s"
        % (plan["missing"], plan["complete"]))
    check("T49_STATIONS_GROUPED",
          all(r["validation_stations"] for r in rows),
          "every structure must own at least one station: %r"
          % ([(r["id"], r["validation_stations"]) for r in rows],))
    check("T49_STATIONS_PLAN_COMPLETE", plan["complete"] is True,
          "the full plan must cover every inferred structure: missing=%r"
          % (plan["missing"],))
    empty = si.plan_validation_stations(
        meas, {"structures": [{"id": "GHOST", "evidence_faces": [9999]}]})
    check("T49_STATIONS_MISSING_REPORTED",
          empty["missing"] == ["GHOST"] and empty["complete"] is False,
          "a structure with no station must be reported: %r" % (empty,))

    # stepped-shaft grouping: group_coaxial buckets by (axis, radius), so a
    # two-radius shaft arrives as two single-segment groups.  Merging by axis
    # is what makes a stepped shaft a revolved_profile row instead of two
    # cylinder rows -- and a z-band stack is exactly what several cylinder
    # rows on one axis looks like to the construction stage.
    shaft = plate_boss_hole()
    shaft["cylinders"] = [
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 0.0],
         "radius": 18.0, "faces": [20], "extent": [0.0, 12.0], "length": 12.0,
         "concave": False, "segments": [{"faces": [20]}]},
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 12.0],
         "radius": 11.0, "faces": [21], "extent": [12.0, 30.0], "length": 18.0,
         "concave": False, "segments": [{"faces": [21]}]},
        # a coaxial bore must NOT merge with the convex steps: on this axis the
        # convex/concave split is what keeps the bore out of the shaft row
        {"kind": CYL, "axis": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 0.0],
         "radius": 6.0, "faces": [22], "extent": [0.0, 30.0], "length": 30.0,
         "concave": True, "segments": [{"faces": [22]}]},
    ]
    shaft["cones"] = []
    got = si._revolved_structures(shaft)
    say("shaft rows=%r" % ([(r["role"], r["template"], r.get("radii"))
                            for r in got],))
    hubs = [r for r in got if r["role"] == "hub"]
    bores = [r for r in got if r["role"] == "bore"]
    check("T49_SHAFT_MERGED_BY_AXIS",
          len(hubs) == 1 and hubs[0]["template"] == "revolved_profile" and
          hubs[0]["radii"] == [11.0, 18.0],
          "two radii on one axis must be ONE revolved row carrying both: %r"
          % ([(r["template"], r.get("radii")) for r in hubs],))
    check("T49_SHAFT_CONCAVE_SPLIT",
          len(bores) == 1 and bores[0]["radii"] == [6.0],
          "a coaxial bore must not join the shaft's convex row: %r"
          % ([(r["role"], r.get("radii")) for r in got],))

    # draft vs loft: a drafted solid's two sections are the same outline
    # scaled, a variable-section arm's are not
    square = [(10.0, 10.0, 0.0), (-10.0, 10.0, 0.0), (-10.0, -10.0, 0.0),
              (10.0, -10.0, 0.0)]
    scaled = [(p[0] * 0.6, p[1] * 0.6, 0.0) for p in square]
    flat = [(16.0, 4.0, 0.0), (-16.0, 4.0, 0.0), (-16.0, -4.0, 0.0),
            (16.0, -4.0, 0.0)]
    sim_scaled = si._sections_similar(square, scaled, si.SHAPE_SIMILARITY)
    sim_flat = si._sections_similar(square, flat, si.SHAPE_SIMILARITY)
    say("similarity scaled=%r reshaped=%r" % (sim_scaled, sim_flat))
    check("T49_DRAFT_NOT_LOFT", sim_scaled is True,
          "a drafted solid's sections are one outline scaled -- that is not a "
          "loft")
    check("T49_LOFT_DETECTED", sim_flat is False,
          "a variable-section arm's sections differ in aspect ratio")

    # transitions: mechanism choice and unreachability evidence.  G7 may only
    # be BLOCKED when a per-runway topological reason exists, so the planner
    # must produce `evidence` for exactly those runways and nothing for the
    # rest.
    wide = plane_face(30, [0.0, 0.0, 10.0], [0.0, 0.0, 1.0], area=400.0)
    wide["box"] = [-20.0, -20.0, 10.0, 20.0, 20.0, 10.0]
    wide2 = plane_face(31, [0.0, 20.0, 5.0], [0.0, 1.0, 0.0], area=400.0)
    wide2["box"] = [-20.0, 20.0, 0.0, 20.0, 20.0, 10.0]
    narrow = plane_face(32, [0.0, 1.0, 0.0], [0.0, 1.0, 0.0], area=4.0)
    narrow["box"] = [-5.0, 0.0, 0.0, 5.0, 1.0, 10.0]
    fbt = {30: wide, 31: wide2, 32: narrow}

    ok_run = {"radius": 3.0, "nfaces": 2, "faces": [40, 41],
              "supports": [("22/R0.000/A0.000", 3)], "closed": False}
    # the runway's own faces must exist for support lookup; give them edges
    # to the two wide planes so the planner sees a 90 deg plane-plane pair
    fa = cyl(40, [0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 3.0)
    fa["edges"] = [{"tag": 900, "faces": [40, 30]}, {"tag": 901,
                                                    "faces": [40, 31]}]
    fb = cyl(41, [0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 3.0)
    fb["edges"] = [{"tag": 902, "faces": [41, 30]}, {"tag": 903,
                                                    "faces": [41, 31]}]
    fbt[40] = fa
    fbt[41] = fb
    plan_ok = tr.plan_runway(ok_run, fbt)
    say("transition wide=%r" % (plan_ok,))
    check("T49_TRANSITION_MECHANISM",
          plan_ok["mechanism"] == "roll_edge" and plan_ok["reachable"] is True,
          "two planar supports on an open runway route to roll_edge: %r"
          % (plan_ok["mechanism"],))
    check("T49_TRANSITION_NO_FALSE_EVIDENCE", plan_ok["evidence"] is None,
          "a reachable runway must not carry BLOCKED evidence: %r"
          % (plan_ok["evidence"],))

    # a support narrower than 2R+0.5 cannot hold the blend.  The two supports
    # must be a legitimate pair (parallel walls): with perpendicular supports
    # the dihedral check fires first and the width reason never appears --
    # which is the right behaviour, so the fixture has to isolate one cause.
    narrow2 = plane_face(33, [0.0, -1.0, 0.0], [0.0, -1.0, 0.0], area=4.0)
    narrow2["box"] = [-5.0, -1.0, 0.0, 5.0, 0.0, 10.0]
    tight = {"radius": 3.0, "nfaces": 2, "faces": [50, 51],
             "supports": [("22/R0.000/A0.000", 3)], "closed": False}
    ta = cyl(50, [0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 3.0)
    # slot walls 2 mm apart, normals antiparallel -> dihedral 180 deg would
    # fail the range check, so give them a slight included angle instead
    wall_a = plane_face(34, [0.0, 1.0, 5.0], [0.0, 0.866, -0.5], area=20.0)
    wall_a["box"] = [-5.0, 0.0, 0.0, 5.0, 2.0, 10.0]
    wall_b = plane_face(35, [0.0, -1.0, 5.0], [0.0, -0.866, -0.5], area=20.0)
    wall_b["box"] = [-5.0, -1.0, 0.0, 5.0, -1.0, 10.0]
    ta["edges"] = [{"tag": 910, "faces": [50, 34]}, {"tag": 911,
                                                    "faces": [50, 35]}]
    tb = cyl(51, [0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 3.0)
    tb["edges"] = [{"tag": 912, "faces": [51, 34]}, {"tag": 913,
                                                    "faces": [51, 35]}]
    fbt[50] = ta
    fbt[51] = tb
    fbt[34] = wall_a
    fbt[35] = wall_b
    fbt[33] = narrow2
    plan_tight = tr.plan_runway(tight, fbt)
    say("transition tight=%r" % (plan_tight,))
    obs = plan_tight.get("build_obstacle") or {}
    check("T49_TRANSITION_WIDTH_REASON",
          plan_tight["reachable"] is False and
          "support width" in obs.get("reason", ""),
          "a 1 mm support cannot hold R3 and must say why: %r" % (obs,))
    check("T49_TRANSITION_EVIDENCE_SHAPE",
          obs.get("runway_faces") == [50, 51] and "supports" in obs,
          "the obstacle record must name the runway and its supports: %r"
          % (obs,))
    # a support narrower than 2R is a BUILD obstacle, not topology: the
    # reference part already has that fillet, so width proves "hard to
    # reproduce", never "physically unreachable".  Mixing the two made the
    # reference solution itself un-passable.
    check("T49_TRANSITION_WIDTH_NOT_BLOCKED",
          plan_tight["evidence"] is None and
          (plan_tight.get("build_obstacle") or {}).get("reason"),
          "a width shortfall must be a build obstacle, never BLOCKED evidence: "
          "evidence=%r obstacle=%r"
          % (plan_tight["evidence"], plan_tight.get("build_obstacle")))

    # A stack fingerprint is "many offsets whose areas agree", not "many
    # offsets".  A real part with a flange, a boss and a lofted arm has plenty
    # of parallel planes, but each belongs to a different outline, so the
    # areas differ hugely.  Refusing it as a z-band stack reported a correct
    # multi-structure build as a per-slice tree (it silently dropped the arm
    # row and set unresolved).
    def band(areas):
        offs, pairs = 0.0, []
        prev = None
        for i, a in enumerate(areas):
            cur = {"offset": float(i), "faces": [100 + i], "area": a}
            if prev is not None:
                pairs.append({"lo": prev["offset"], "hi": cur["offset"],
                              "thickness": 1.0,
                              "faces": [prev["faces"][0], cur["faces"][0]],
                              "area": a + prev["area"]})
            prev = cur
        return {"normal": [0.0, 0.0, 1.0],
                "offsets": [float(i) for i in range(len(areas))],
                "n_offsets": len(areas), "pairs": pairs}

    stacked = band([5000.0] * 8)
    mixed = band([5000.0, 4800.0, 300.0, 280.0, 260.0, 240.0])
    say("stack vs mixed: stacked=%r mixed=%r"
        % (si._explained_offsets(stacked), si._explained_offsets(mixed)))
    check("T49_STACK_AREAS_DECIDE",
          si._explained_offsets(stacked) is False and
          si._explained_offsets(mixed) is True,
          "a stack is many offsets with agreeing areas; differing areas mean "
          "different structures: stacked=%r mixed=%r"
          % (si._explained_offsets(stacked), si._explained_offsets(mixed)))
    # a short stack is just a plate: two outer faces and nothing else
    check("T49_SHORT_BAND_EXPLAINED",
          si._explained_offsets(band([5000.0, 5000.0])) is True,
          "fewer than the stack threshold must never be refused")

    failed = [n for n, ok in RESULTS if not ok]
    say("TEST49_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST49_FAIL failed=%s" % failed)
        return
    say("TEST49_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST49_FATAL:\n" + traceback.format_exc()[-900:])
        say("TEST49_FAIL uncaught")
