# -*- coding: utf-8 -*-
# Test 47: structure-level builders (nxlib.structures, section 12.4).
#
# Section 12.4 requires "one function per structure".  Until now the library
# only had primitives (prism/cylinder/cone + booleans), so a cast body whose
# thickness changes along z could only be built as N stacked z-band prisms.
# That is exactly what the failing delivery did: 9 bands -> 74 features and
# 10 773 faces against 998 in the original, and the band steps are still flat
# slices of a curved surface.  These builders replace the stack with one
# analytic feature per structure, and the test pins the two claims that make
# that a real capability rather than a rename:
#
#   - every builder reproduces the analytic volume (frustum / Steiner / prism
#     formulas), so "it built" is not mistaken for "it is right";
#   - the same stepped shaft costs an order of magnitude fewer faces when it
#     comes from a revolved profile than from stacked polygon bands, at equal
#     volume -- the face-count blowup is a construction choice, not a
#     tessellation accident;
#   - a drafted extrusion is checked against the frustum, so a silently
#     ignored DraftOption (volume identical to the straight prism) fails here;
#   - fillet_run returns one ledger row per edge including the verbatim
#     failure text, because a runway ledger without the reason cannot answer
#     "why is this runway unreachable".
import math
import os
import sys

import NXOpen

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.dirname(os.path.abspath(sys.argv[0]))
_p = os.path.abspath(os.path.join(_here, ".."))
if os.path.isdir(os.path.join(_p, "nxlib")) and _p not in sys.path:
    sys.path.insert(0, _p)

from nxlib.testing import check, say, RESULTS
from nxlib.session import new_part, save_checked
import nxlib.modeling as mdl
import nxlib.skeleton as sk
import nxlib.structures as st
import nxlib.template as tpl

SQUARE = [(-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0)]
SIDE, DRAFT_H, DRAFT_DEG = 40.0, 20.0, 5.0
# (t, r) stepped shaft: r 20 for t 0..10, r 12 for t 10..30, flat end at 30
SHAFT = [(0.0, 20.0), (10.0, 20.0), (10.0, 12.0), (30.0, 12.0), (30.0, 0.0)]
NGON = 64


def nfaces(body):
    return len(list(body.GetFaces()))


def ngon(r, n=NGON):
    return [(r * math.cos(2.0 * math.pi * k / n),
             r * math.sin(2.0 * math.pi * k / n)) for k in range(n)]


def frustum(h, r0, r1):
    return math.pi * h / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)


def shaft_volume():
    v = 0.0
    for i in range(len(SHAFT) - 1):
        t0, r0 = SHAFT[i]
        t1, r1 = SHAFT[i + 1]
        if t1 > t0:
            v += frustum(t1 - t0, r0, r1)
    return v


def case_plate(wp):
    """2.5D plate: straight prism and drafted prism."""
    frame = sk.Frame()
    tpl.create_expressions(wp, {"PLATE_T": 20.0, "DRAFT_A": DRAFT_DEG},
                           {"PLATE_T": "mm", "DRAFT_A": "deg"})
    body = st.plate_2p5d(wp, frame, SQUARE, "0.0", "PLATE_T",
                         name="PLATE")["bodies"][0]
    v = mdl.volume(wp, body)
    v_straight = SIDE * SIDE * DRAFT_H
    say("plate straight volume=%.4f expect=%.4f faces=%d"
        % (v, v_straight, nfaces(body)))
    check("T47_PLATE_VOLUME", abs(v - v_straight) < 1e-3,
          "straight plate %.4f vs analytic %.4f" % (v, v_straight))
    # a band stack of the same plate shows up as extra side faces; one
    # extrusion of a closed plan has exactly 6
    check("T47_PLATE_SIX_FACES", nfaces(body) == 6,
          "one extruded plan must give 6 faces, got %d" % nfaces(body))

    drafted = st.plate_2p5d(wp, frame, SQUARE, "0.0", "PLATE_T",
                            name="PLATE_DRAFT", draft_expr="DRAFT_A")
    bd = drafted["bodies"][0]
    vd = mdl.volume(wp, bd)
    top = SIDE - 2.0 * DRAFT_H * math.tan(math.radians(DRAFT_DEG))
    v_frustum = DRAFT_H / 3.0 * (SIDE * SIDE + top * top + SIDE * top)
    say("plate drafted volume=%.4f frustum=%.4f straight=%.4f top=%.4f"
        % (vd, v_frustum, v_straight, top))
    check("T47_DRAFT_FRUSTUM", abs(vd - v_frustum) < 1e-2,
          "drafted plate %.4f vs frustum %.4f" % (vd, v_frustum))
    # a DraftOption that was set but never took effect commits fine, raises no
    # alert and matches the straight prism bit for bit; only the volume shows it
    check("T47_DRAFT_TAKES_EFFECT", vd < v_straight - 1.0,
          "draft must remove material (drafted %.4f, straight %.4f): a "
          "DraftOption without a type is silently ignored"
          % (vd, v_straight))
    return bd


def case_shaft(wp):
    """Revolved profile: one feature per convex segment, analytic volume."""
    res = st.revolved_profile(wp, SHAFT, name="SHAFT")
    body = res["bodies"][0]
    v = mdl.volume(wp, body)
    v_nom = shaft_volume()
    say("shaft volume=%.4f expect=%.4f segments=%d bodies=%d faces=%d"
        % (v, v_nom, len(res["segments"]), len(list(wp.Bodies)), nfaces(body)))
    check("T47_SHAFT_VOLUME", abs(v - v_nom) < 1e-3 * max(v_nom, 1.0),
          "revolved profile %.4f vs analytic %.4f" % (v, v_nom))
    check("T47_SHAFT_SEGMENTS", len(res["segments"]) == 2,
          "the flat end segment has no extent and must be skipped, got %r"
          % (res["segments"],))
    check("T47_SHAFT_SINGLE_BODY", len(list(wp.Bodies)) == 1,
          "the segments must unite into one body, got %d"
          % len(list(wp.Bodies)))
    return body


def case_stack_contrast(wp):
    """Same shaft from stacked polygon bands: faces explode, volume does not."""
    frame = sk.Frame()
    bands = [(0.0, 10.0, 20.0), (10.0, 30.0, 12.0)]
    target = None
    for i, (z0, z1, r) in enumerate(bands):
        d = st.prism(wp, sk.loop_uv(wp, frame, ngon(r)), (0.0, 0.0, 1.0),
                     str(z0), str(z1))
        if target is None:
            target = d["bodies"][0]
        else:
            st.unite(wp, target, d["features"][0])
    v_stack = mdl.volume(wp, target)
    f_stack = nfaces(target)

    rev = st.revolved_profile(wp, SHAFT, name="SHAFT_CMP")
    body = rev["bodies"][0]
    v_rev = mdl.volume(wp, body)
    f_rev = nfaces(body)
    a_ngon = NGON / 2.0 * math.sin(2.0 * math.pi / NGON)
    v_ngon = a_ngon * (20.0 ** 2 * 10.0 + 12.0 ** 2 * 20.0)
    say("contrast: stack vol=%.4f faces=%d | revolve vol=%.4f faces=%d | "
        "ngon analytic=%.4f | ratio=%.1fx"
        % (v_stack, f_stack, v_rev, f_rev, v_ngon, f_stack / float(f_rev)))
    check("T47_STACK_VOLUME", abs(v_stack - v_ngon) < 0.01 * v_ngon,
          "stacked bands %.4f vs polygon analytic %.4f" % (v_stack, v_ngon))
    check("T47_FACE_RATIO", f_stack >= 8 * f_rev,
          "the same shape must cost many fewer faces when revolved "
          "(stack %d, revolve %d)" % (f_stack, f_rev))
    check("T47_SAME_VOLUME", abs(v_stack - v_rev) < 0.01 * v_ngon,
          "face count must not be bought with volume: stack %.4f revolve %.4f"
          % (v_stack, v_rev))
    return body


def case_bore_and_holes(wp):
    """Drafted bore (cone cut) and a hole set, both analytic."""
    blk = mdl.block(wp, NXOpen.Point3d(-30.0, -30.0, 0.0), "60", "60", "40")
    body = list(blk.GetBodies())[0]
    v0 = mdl.volume(wp, body)
    tpl.create_expressions(wp, {"BORE_D0": 20.0, "BORE_D1": 8.0,
                                "BORE_L": 50.0},
                           {"BORE_D0": "mm", "BORE_D1": "mm", "BORE_L": "mm"})
    res = st.drafted_bore(wp, body, (-5.0, 0.0, 20.0), (1.0, 0.0, 0.0),
                          "BORE_D0", "BORE_D1", "BORE_L", name="BORE")
    v1 = mdl.volume(wp, body)
    # the cone starts at x=-5 (outside the block) on x=-30..30, so the block
    # only keeps t = 0..35 of the 50 long cone
    r0, r1, lt = 10.0, 4.0, 50.0
    r_at = lambda t: r0 + (r1 - r0) * t / lt
    v_in = frustum(35.0, r_at(0.0), r_at(35.0))
    say("drafted bore removed=%.4f expect=%.4f"
        % (v0 - v1, v_in))
    check("T47_BORE_VOLUME", abs((v0 - v1) - v_in) < 1e-2 * v_in,
          "removed %.4f vs frustum-in-block %.4f" % (v0 - v1, v_in))
    check("T47_BORE_NAMED", res["features"][0].Name == "BORE",
          "the bore must carry its structure id, got %r"
          % (res["features"][0].Name,))

    tpl.create_expressions(wp, {"HOLE_D": 10.0, "HOLE_L": 30.0},
                           {"HOLE_D": "mm", "HOLE_L": "mm"})
    before = mdl.volume(wp, body)
    hs = st.hole_set(wp, body, [(-1.0, 20.0, 20.0), (-1.0, -20.0, 20.0)],
                     (1.0, 0.0, 0.0), "HOLE_D", "HOLE_L", name="HSET")
    after = mdl.volume(wp, body)
    v_hole = math.pi / 4.0 * 10.0 ** 2 * 30.0 * 2.0
    say("hole_set count=%d removed=%.4f expect=%.4f"
        % (hs["count"], before - after, v_hole))
    check("T47_HOLESET_COUNT", hs["count"] == 2,
          "two positions must give two hole features, got %d" % hs["count"])
    check("T47_HOLESET_VOLUME", abs((before - after) - v_hole) < 1e-2 * v_hole,
          "removed %.4f vs two cylinders %.4f" % (before - after, v_hole))
    check("T47_HOLESET_NAMED",
          all(f.Name.startswith("HSET_") for f in hs["features"]),
          "each hole must carry its structure id: %r"
          % ([f.Name for f in hs["features"]],))
    return body


def case_pocket(wp):
    """Stepped pocket: section profile intersected with plan profile."""
    frame = sk.Frame()
    blk = mdl.block(wp, NXOpen.Point3d(-40.0, -40.0, 0.0), "80", "80", "30")
    body = list(blk.GetBodies())[0]
    v0 = mdl.volume(wp, body)
    # section (u,z): a slot from the top face down to z=10, 20 wide in u;
    # plan (u,v): 20 x 40.  Their intersection is a 20 x 40 x 20 block.
    section = [(-10.0, 30.0), (10.0, 30.0), (10.0, 10.0), (-10.0, 10.0)]
    plan = [(-10.0, -20.0), (10.0, -20.0), (10.0, 20.0), (-10.0, 20.0)]
    st.pocket_intersect(wp, body, frame, section, plan, 30.0, ("-2.0", "35.0"),
                        name="PKT")
    v1 = mdl.volume(wp, body)
    v_pkt = 20.0 * 40.0 * 20.0
    say("pocket removed=%.4f expect=%.4f" % (v0 - v1, v_pkt))
    check("T47_POCKET_VOLUME", abs((v0 - v1) - v_pkt) < 1e-2 * v_pkt,
          "removed %.4f vs 20x40x20 %.4f" % (v0 - v1, v_pkt))
    return body


def case_fillet_ledger(wp):
    """Per-edge ledger: success rows carry radius, failure rows carry the text."""
    frame = sk.Frame()
    blk = mdl.block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "30", "20")
    body = list(blk.GetBodies())[0]
    top = st.edges_by(body, frame, lambda pts: all(
        abs(p[2] - 20.0) < 0.2 and abs(p[1] - 30.0) < 0.2 for p in pts))
    # a second, untouched edge: blending an edge consumes it, so the oversized
    # attempt must NOT reuse the edge the successful run just consumed --
    # "Referenced edge does not exist" would hide whether the radius is the
    # reason
    bottom = st.edges_by(body, frame, lambda pts: all(
        abs(p[2]) < 0.2 and abs(p[1] - 30.0) < 0.2 for p in pts))
    say("fillet candidates top=%d bottom=%d" % (len(top), len(bottom)))
    ok = st.fillet_run(wp, top, "3.0", name="FR", edges_id=[11])
    say("fillet ledger=%r pass=%r" % (ok["ledger"], ok["pass"]))
    check("T47_FILLET_LEDGER_ROWS", len(ok["ledger"]) == len(top),
          "one ledger row per edge: %d edges, %d rows"
          % (len(top), len(ok["ledger"])))
    check("T47_FILLET_LEDGER_OK", ok["pass"] is True,
          "R3 on a 40x30x20 box top edge must succeed: %r" % (ok["ledger"],))

    big = st.fillet_run(wp, bottom, "60.0", name="FRBIG", edges_id=["r1"])
    say("fillet oversized ledger=%r" % (big["ledger"],))
    check("T47_FILLET_TEXT_KEPT", big["pass"] is False
          and big["ledger"][0]["msg"],
          "an unreachable radius must leave the verbatim failure: %r"
          % (big["ledger"],))
    check("T47_FILLET_ROLLBACK", len(list(wp.Bodies)) == 1,
          "the failed blend must roll back, bodies=%d" % len(list(wp.Bodies)))
    return body


def case_hole_chain(wp):
    """Stepped coaxial bore: per-segment cut, built-vs-declared reconciliation."""
    blk = mdl.block(wp, NXOpen.Point3d(-30.0, -30.0, 0.0), "60", "60", "40")
    body = list(blk.GetBodies())[0]
    tpl.create_expressions(wp, {"D_BORE_A": 10.0, "D_BORE_B": 14.0},
                           {"D_BORE_A": "mm", "D_BORE_B": "mm"})
    v0 = mdl.volume(wp, body)
    res = st.hole_chain(wp, body, [
        {"kind": "cylinder", "p0": (-30.0, 0.0, 20.0), "p1": (0.0, 0.0, 20.0),
         "dia": "D_BORE_A", "dia_mm": 10.0},
        {"kind": "cylinder", "p0": (0.0, 0.0, 20.0), "p1": (30.0, 0.0, 20.0),
         "dia": "D_BORE_B", "dia_mm": 14.0},
    ], name="BORE", back=1.5)
    v1 = mdl.volume(wp, body)
    # union of the two extended tools inside the block: D10 over 28.5 mm,
    # D14 over the 3 mm the small tool overran, D14 over 28.5 mm
    v_expect = math.pi * (28.5 * 25.0 + 3.0 * 49.0 + 28.5 * 49.0)
    say("hole_chain removed=%.4f expect=%.4f checks=%r"
        % (v0 - v1, v_expect, res["checks"]))
    check("T47_CHAIN_VOLUME", abs((v0 - v1) - v_expect) < 1e-2 * v_expect,
          "removed %.4f vs two-segment union %.4f" % (v0 - v1, v_expect))
    check("T47_CHAIN_PASS", res["pass"] is True and res["count"] == 2,
          "each segment must come back with its own evidence: %r"
          % (res["checks"],))
    check("T47_CHAIN_TWO_RADII",
          all(any(a["type"] == 16 for a in c["added"]) for c in res["checks"]) and
          all("radius" in c["reason"] for c in res["checks"]),
          "both segments must add a cylindrical face whose radius was "
          "compared with its declared value: %r" % (res["checks"],))
    one = math.pi / 4.0 * 10.0 ** 2 * 30.0
    say("chain vs single straight bore: chain=%.4f single=%.4f"
        % (v0 - v1, one))
    check("T47_CHAIN_NOT_ONE_BORE", abs((v0 - v1) - one) > 0.2 * one,
          "a stepped bore must not measure like one straight bore (chain "
          "%.4f, single %.4f)" % (v0 - v1, one))
    return body


def case_cone_mouth(wp):
    """Cone mouth segment: half angle is read back from the built face."""
    blk = mdl.block(wp, NXOpen.Point3d(-30.0, -30.0, 0.0), "60", "60", "40")
    body = list(blk.GetBodies())[0]
    tpl.create_expressions(wp, {"D_HOLE": 14.0, "D_MOUTH": 20.0},
                           {"D_HOLE": "mm", "D_MOUTH": "mm"})
    v0 = mdl.volume(wp, body)
    res = st.hole_chain(wp, body, [
        {"kind": "cylinder", "p0": (-30.0, 0.0, 20.0), "p1": (30.0, 0.0, 20.0),
         "dia": "D_HOLE", "dia_mm": 14.0},
        {"kind": "cone", "p0": (-30.0, 0.0, 20.0), "p1": (-26.0, 0.0, 20.0),
         "dia_a": "D_MOUTH", "dia_a_mm": 20.0,
         "dia_b": "D_HOLE", "dia_b_mm": 14.0},
    ], name="MOUTH", back=1.5)
    v1 = mdl.volume(wp, body)
    hole = math.pi * 49.0 * 60.0
    # annular extra of the mouth over x -30..-26: r linear 10 -> 7
    ring = math.pi * (4.0 * (100.0 + 70.0 + 49.0) / 3.0 - 49.0 * 4.0)
    say("cone mouth removed=%.4f expect=%.4f checks=%r"
        % (v0 - v1, hole + ring, res["checks"]))
    check("T47_MOUTH_VOLUME", abs((v0 - v1) - (hole + ring)) < 1e-2 * hole,
          "removed %.4f vs hole+ring %.4f" % (v0 - v1, hole + ring))
    cone_row = res["checks"][1]
    check("T47_MOUTH_HALF_ANGLE",
          cone_row["ok"] is True and
          any(a["type"] == 17 for a in cone_row["added"]) and
          "half angle" in cone_row["reason"],
          "the cone segment must add a conical face and match the declared "
          "half angle: %r" % (cone_row,))
    return body


def case_chain_declared_mismatch(wp):
    """The per-segment check must compare the built face with the declared value."""
    blk = mdl.block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "40", "20")
    body = list(blk.GetBodies())[0]
    tpl.create_expressions(wp, {"D_LIE": 10.0}, {"D_LIE": "mm"})
    res = st.hole_chain(wp, body, [
        {"kind": "cylinder", "p0": (0.0, 20.0, 10.0), "p1": (40.0, 20.0, 10.0),
         "dia": "D_LIE", "dia_mm": 12.0},
    ], name="LIAR")
    say("declared-mismatch checks=%r pass=%r" % (res["checks"], res["pass"]))
    check("T47_CHAIN_DECLARED_MISMATCH",
          res["pass"] is False and res["checks"][0]["ok"] is False and
          "declared 6.0000" in res["checks"][0]["reason"],
          "a segment whose built radius does not match its declared value "
          "must fail its own check: %r" % (res["checks"],))
    return body


def case_eye_and_clevis(wp):
    """Two-lobe eye (tangent lobes) and a clevis slot, both analytic."""
    frame = sk.Frame()
    tpl.create_expressions(wp, {"EYE_T": 10.0, "EYE_R": 3.0},
                           {"EYE_T": "mm", "EYE_R": "mm"})
    plan = [(-20.0, -9.0), (0.0, -9.0), (0.0, 9.0), (-20.0, 9.0)]
    res = st.eye_2lobe(wp, frame, [(0.0, 6.0), (0.0, -6.0)], "EYE_R", 3.0,
                       plan, "EYE_T", name="EYE")
    body = res["bodies"][0]
    v = mdl.volume(wp, body)
    v_expect = (20.0 * 18.0 + 2.0 * math.pi * 9.0 / 2.0) * 10.0
    say("eye volume=%.4f expect=%.4f checks=%r"
        % (v, v_expect, res["checks"]))
    check("T47_EYE_VOLUME", abs(v - v_expect) < 1e-3 * v_expect,
          "platform + two half lobes %.4f vs %.4f" % (v, v_expect))
    check("T47_EYE_TANGENT", res["tangent_ok"] is True and
          res["checks"]["single_body_build"] is True and
          len(res["checks"]["lobe_faces"]) == 2,
          "W_HALF must equal h + R and both lobes must exist: %r"
          % (res["checks"],))

    cl = st.clevis(wp, frame, [(-30.0, -15.0), (0.0, -15.0), (0.0, 15.0),
                               (-30.0, 15.0)], "EYE_T", 10.0,
                   {"u0": -12.0, "u1": 5.0, "w_mm": 8.0}, name="CLV")
    cbody = cl["bodies"][0]
    vc = mdl.volume(wp, cbody)
    # the tool reaches 5 mm past the end face, but only the 12 mm inside the
    # plate remove material
    vc_expect = 30.0 * 30.0 * 10.0 - 12.0 * 8.0 * 10.0
    say("clevis volume=%.4f expect=%.4f checks=%r"
        % (vc, vc_expect, cl["checks"]))
    check("T47_CLEVIS_VOLUME", abs(vc - vc_expect) < 1e-3 * vc_expect,
          "plate minus 17x8 slot %.4f vs %.4f" % (vc, vc_expect))
    check("T47_CLEVIS_SLOT", cl["checks"]["wall_spacing_ok"] is True and
          cl["checks"]["single_body_build"] is True and
          cl["checks"]["bottom_u"] == [-12.0, 0.0],
          "the slot walls must sit at the declared width and the floor at u0 "
          "(u=0 is the split end face): %r" % (cl["checks"],))
    return body


def case_eye_tangency_gap(wp):
    """A non-tangent lobe must be reported, not silently built as a step."""
    frame = sk.Frame()
    tpl.create_expressions(wp, {"EYE_T": 10.0, "EYE_R4": 4.0},
                           {"EYE_T": "mm", "EYE_R4": "mm"})
    plan = [(-20.0, -9.0), (0.0, -9.0), (0.0, 9.0), (-20.0, 9.0)]
    res = st.eye_2lobe(wp, frame, [(0.0, 6.0), (0.0, -6.0)], "EYE_R4", 4.0,
                       plan, "EYE_T", name="EYE_GAP")
    say("eye gap checks=%r" % (res["checks"],))
    check("T47_EYE_GAP_REPORTED",
          res["tangent_ok"] is False and
          abs(res["checks"]["tangency_gap_mm"] - 1.0) < 1e-9,
          "W_HALF - (h + R) must be reported instead of hidden: %r"
          % (res["checks"],))
    return res["bodies"][0]


def case_trim_planes(wp):
    """Trimming by measured planes: volume, single body, direction sanity."""
    blk = mdl.block(wp, NXOpen.Point3d(-20.0, -20.0, -20.0), "40", "40", "40")
    body = list(blk.GetBodies())[0]
    res = st.trim_planes(wp, body, [
        {"point": (0.0, 0.0, 0.0), "normal": (1.0, 0.0, 0.0), "keep": "below"},
        {"point": (0.0, 0.0, 10.0), "normal": (0.0, 0.0, 1.0), "keep": "below"},
    ], name="TR")
    v = mdl.volume(wp, body)
    # block -20..20 on every axis; keep x<0 then z<10 -> 20 x 40 x 30
    say("trim volume=%.4f expect=%.4f checks=%r" % (v, 24000.0, res["checks"]))
    check("T47_TRIM_VOLUME", abs(v - 24000.0) < 1e-3 * 24000.0,
          "two half-space cuts must leave 20x40x30: %.4f" % v)
    check("T47_TRIM_CHECKS", res["pass"] is True and
          all(c["bodies"] == 1 for c in res["checks"]),
          "every trim must keep one body and remove material: %r"
          % (res["checks"],))
    # a trim plane beyond the body with the wrong side keeps nothing: the
    # volume check is what catches a reversed direction
    blk2 = mdl.block(wp, NXOpen.Point3d(60.0, 0.0, 0.0), "20", "20", "20")
    b2 = list(blk2.GetBodies())[0]
    bad = st.trim_planes(wp, b2, [
        {"point": (0.0, 0.0, 0.0), "normal": (1.0, 0.0, 0.0), "keep": "below"},
    ], name="TRBAD")
    say("trim beyond body checks=%r" % (bad["checks"],))
    check("T47_TRIM_SIDE_REVERSED",
          bad["pass"] is False and bad["checks"][0]["ok"] is False and
          "completely inside" in bad["checks"][0]["reason"],
          "a keep side that puts the whole body inside the tool must be "
          "flagged with NX's own reason: %r" % (bad["checks"],))
    return body


def case_fillet_precheck(wp):
    """fillet_feasible separates 'radius too large' from NX's own text."""
    frame = sk.Frame()
    blk = mdl.block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "40", "30", "20")
    body = list(blk.GetBodies())[0]
    edges = st.edges_by(body, frame, lambda pts: all(
        abs(p[2] - 20.0) < 0.2 and abs(p[1] - 30.0) < 0.2 for p in pts))
    pre_big = st.fillet_feasible(edges[0], 60.0)
    pre_ok = st.fillet_feasible(edges[0], 3.0)
    say("fillet precheck big=%r ok=%r" % (pre_big, pre_ok))
    check("T47_FILLET_PRECHECK_BIG",
          pre_big["ok"] is False and "support width" in pre_big["reason"],
          "a radius that cannot fit its supports must be attributed before "
          "the attempt: %r" % (pre_big,))
    check("T47_FILLET_PRECHECK_OK", pre_ok["ok"] is True and
          abs(pre_ok["dihedral_deg"] - 90.0) < 1.0,
          "a 90 deg box edge must pass the precheck with its dihedral: %r"
          % (pre_ok,))
    res = st.fillet_run(wp, edges, "60.0", name="FRP", radius_mm=60.0,
                        edges_id=["r1"])
    say("fillet ledger with precheck=%r" % (res["ledger"],))
    check("T47_FILLET_REASON_ATTRIBUTED",
          res["pass"] is False and
          res["ledger"][0]["reason"].startswith("R") and
          "(precheck:" in res["ledger"][0]["reason"],
          "the ledger must name the radius/support cause, not only NX text: %r"
          % (res["ledger"],))
    return body


def case_section_loft(wp):
    """Variable-section arm: two rings loft to the frustum, not to a band stack."""
    frame = sk.Frame()
    n = 48
    # a round-to-round frustum: r 15 at t=0, r 8 at t=40 -> analytic frustum
    a = [(15.0 * math.cos(2.0 * math.pi * k / n),
          15.0 * math.sin(2.0 * math.pi * k / n)) for k in range(n)]
    b = [(8.0 * math.cos(2.0 * math.pi * k / n),
          8.0 * math.sin(2.0 * math.pi * k / n)) for k in range(n)]
    secs = [{"plane": ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), "uv": a},
            {"plane": ((0.0, 0.0, 40.0), (0.0, 0.0, 1.0)), "uv": b}]
    res = st.section_loft(wp, secs, name="ARM")
    v = mdl.volume(wp, res["bodies"][0])
    v_expect = math.pi * 40.0 / 3.0 * (15.0 ** 2 + 15.0 * 8.0 + 8.0 ** 2)
    say("loft volume=%.4f expect=%.4f checks=%r" % (v, v_expect,
                                                    res["checks"]))
    check("T47_LOFT_VOLUME", abs(v - v_expect) < 0.02 * v_expect,
          "two-ring loft %.4f vs frustum %.4f" % (v, v_expect))
    check("T47_LOFT_SOLID", res["pass"] is True and
          res["checks"]["is_solid"] is True and
          res["checks"]["bodies"] == 1,
          "a loft must come back as one solid body, not a sheet: %r"
          % (res["checks"],))
    check("T47_LOFT_ONE_FEATURE_ID", [f.Name for f in res["features"]] ==
          ["ARM"],
          "one structure = one feature, named by the structure id: %r"
          % ([f.Name for f in res["features"]],))
    # the z-band alternative costs one prism per slice AND leaves flat steps;
    # the loft's side wall must be a single ruled face per angular sector
    check("T47_LOFT_FEW_FACES", res["checks"]["faces"] <= n + 2,
          "a two-ring loft must not slice into bands: %d faces for a %d-gon"
          % (res["checks"]["faces"], n))
    bad = None
    try:
        st.section_loft(wp, [secs[0], {"plane": secs[1]["plane"],
                                       "uv": b[:24]}], name="ARMBAD")
    except ValueError as exc:
        bad = str(exc)
    say("loft mismatched ring counts rejected=%r" % (bad,))
    check("T47_LOFT_COUNT_MISMATCH_REJECTED",
          bad is not None and "resampled count" in bad,
          "sections with different point counts must be refused before "
          "commit, not lofted into a twist: %r" % (bad,))
    return res["bodies"][0]


def case_resample_ring(wp):
    """Equal-angle resampling keeps a square square and is index-stable."""
    square = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
    ring = st._resample_ring(square, 40)
    ring2 = st._resample_ring(square, 40)
    r_min = min(math.hypot(p[0], p[1]) for p in ring)
    r_max = max(math.hypot(p[0], p[1]) for p in ring)
    say("resample n=%d r=%.4f..%.4f identical=%s"
        % (len(ring), r_min, r_max, ring == ring2))
    check("T47_RESAMPLE_COUNT", len(ring) == 40,
          "resampling must return exactly the asked count: %d" % len(ring))
    # a square inradius 10, circumradius 14.14: the ring must stay between
    check("T47_RESAMPLE_ON_SQUARE",
          abs(r_min - 10.0) < 0.2 and abs(r_max - 14.142) < 0.35,
          "equal-angle rays on a square must hit the boundary between the "
          "inradius and the corner radius: %.4f..%.4f" % (r_min, r_max))
    check("T47_RESAMPLE_DETERMINISTIC", ring == ring2,
          "the same ring resampled twice must be identical")
    # a C: outer 0..10, mouth notch x 0..5 / y 3..7 cut in from the left. Its
    # vertex average (3.75, 5.0) lies in the notch, i.e. outside the material.
    cring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0),
             (0.0, 7.0), (5.0, 7.0), (5.0, 3.0), (0.0, 3.0)]
    bad_center = ""
    try:
        st._resample_ring(cring, 48)
        bad_center = "accepted with the vertex average"
    except ValueError as exc:
        bad_center = str(exc)
    say("resample C vertex-average detail=%r" % (bad_center,))
    check("T47_RESAMPLE_CENTER_CHECK",
          "outside the ring" in bad_center,
          "a reference point that falls outside the material must be named "
          "as the cause: %r" % (bad_center,))
    # with a point that IS inside the material the C is still not star-shaped
    # about it: a ray into the mouth leaves at the notch wall and re-enters at
    # the far arm, so the fill would close the mouth
    rejected = False
    detail = ""
    try:
        got = st._resample_ring(cring, 48, center=(7.0, 5.0))
        detail = "accepted %d points" % len(got)
    except ValueError as exc:
        rejected = True
        detail = str(exc)
    say("resample C inside-ref rejected=%s detail=%r" % (rejected, detail))
    check("T47_RESAMPLE_REJECTS_NONSTAR",
          rejected and "non-star" in detail,
          "a non-star ring must raise instead of silently filling its notch: "
          "%r" % (detail,))
    # ... while a convex ring is accepted at any interior point: the refusal is
    # about the section's visibility, not about resampling being unavailable
    ok_conv = st._resample_ring(
        [(0.0, 0.0), (10.0, 0.0), (12.0, 5.0), (10.0, 10.0), (0.0, 10.0)], 48)
    say("resample convex points=%d" % len(ok_conv))
    check("T47_RESAMPLE_CONVEX_ACCEPTED", len(ok_conv) == 48,
          "a convex ring must resample to the asked count: %d" % len(ok_conv))
    return None


def case_window_cut(wp):
    """Drafted window: straight and drafted removal, per-cut face evidence."""
    frame = sk.Frame()
    blk = mdl.block(wp, NXOpen.Point3d(-30.0, -30.0, 0.0), "60", "60", "20")
    body = list(blk.GetBodies())[0]
    tpl.create_expressions(wp, {"WIN_D": 0.0, "WIN_DRAFT": 4.0},
                           {"WIN_D": "mm", "WIN_DRAFT": "deg"})
    v0 = mdl.volume(wp, body)
    win = [(-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)]
    res = st.window_cut(wp, body, frame, win, -2.0, 22.0, name="WIN")
    v1 = mdl.volume(wp, body)
    say("window straight removed=%.4f expect=%.4f checks=%r"
        % (v1 and v0 - v1, 20.0 * 10.0 * 20.0, res["checks"]))
    v_win = 20.0 * 10.0 * 20.0
    check("T47_WINDOW_VOLUME", abs((v0 - v1) - v_win) < 1e-2 * v_win,
          "straight window removed %.4f vs 20x10x20 %.4f" % (v0 - v1, v_win))
    check("T47_WINDOW_SINGLE_BODY", res["checks"]["single_body_build"] is True
          and res["checks"]["bodies"] == 1,
          "cutting a window must not split the body: %r" % (res["checks"],))
    check("T47_WINDOW_ONLY_PLANES",
          all(t == 22 for t in res["checks"]["added_types"]),
          "a straight window adds only planar walls: %r"
          % (res["checks"]["added_types"],))

    # the drafted window sits on its own block, with the ring fully inside it:
    # a ring straddling a block face would draft against that face too, and
    # the wall count would be 3 drafted + 1 coincident instead of 4 drafted
    frame2 = sk.Frame(origin=(90.0, 0.0, 0.0))
    blk2 = mdl.block(wp, NXOpen.Point3d(60.0, -30.0, 0.0), "60", "60", "20")
    b2 = list(blk2.GetBodies())[0]
    v2 = mdl.volume(wp, b2)
    dres = st.window_cut(wp, b2, frame2, win, -2.0, 22.0, name="WINDRAFT",
                         draft_expr="WIN_DRAFT")
    v3 = mdl.volume(wp, b2)
    # the draft starts on the z0 section and shrinks toward z1, so the mouth
    # (z0 side) is the wide end; a mouth-up window just flips the frame
    say("window drafted removed=%.4f types=%r"
        % (v2 - v3, dres["checks"]["added_types"]))
    check("T47_WINDOW_DRAFT_EFFECTIVE",
          (v2 - v3) < v_win * 0.90,
          "a drafted window must remove clearly less than the straight one "
          "at the far end (otherwise the DraftOption was ignored): drafted "
          "%.4f vs straight %.4f" % (v2 - v3, v_win))
    # A drafted extrusion of a straight-edged plan gives RULED PLANES tilted by
    # the draft angle, not cones -- cones only appear where the plan has arcs.
    # So the wall evidence is the normal tilt, not the face type: a straight
    # wall has its normal in the frame's uv plane, a drafted one is tilted by
    # the draft angle away from z.
    tilts = []
    uf = NXOpen.UF.UFSession.GetUFSession()
    for a in dres["checks"]["added"]:
        d = uf.Modeling.AskFaceData(a["tag"])
        nz = abs(float(d[2][2]))
        # walls have a normal in the uv plane at 0 deg draft; a drafted wall's
        # normal leaves that plane by the draft angle. Faces whose normal is
        # near +z are the tool's cap faces, not walls.
        from_z = math.degrees(math.acos(min(1.0, nz)))
        if from_z > 45.0:
            tilts.append(round(90.0 - from_z, 3))
    say("window drafted wall dev from uv plane (deg)=%r" % (tilts,))
    check("T47_WINDOW_DRAFT_TILT",
          len(tilts) == 4 and abs(min(tilts) - 4.0) < 0.5,
          "the four drafted walls must leave the uv plane by the declared "
          "draft angle: devs=%r" % (tilts,))
    check("T47_WINDOW_DRAFT_CONES",
          all(t == 22 for t in dres["checks"]["added_types"]),
          "a straight-edged plan drafts to ruled planes (cones only come from "
          "arc segments), so the added types must be planar: %r"
          % (dres["checks"]["added_types"],))
    return body


def case_sweep_trim(wp):
    """Skew end wall: trim_planes can only cut one plane, a swept profile can
    cut an oblique line, and the removed volume matches the analytic wedge."""
    frame = sk.Frame()
    blk = mdl.block(wp, NXOpen.Point3d(-30.0, -20.0, 0.0), "60", "40", "20")
    body = list(blk.GetBodies())[0]
    v0 = mdl.volume(wp, body)
    # keep the region below the line from (0, 20) to (30, 0) AND the whole
    # left part of the block: the profile must bound the entire keep region,
    # not just the triangle -- a profile that covers only part of the material
    # there leaves the rest as a second body
    # counter-clockwise in the (u, z) view (signed area +): along the bottom,
    # up the 45 deg line, then back across the top to the left edge
    prof = [(-40.0, 0.0), (30.0, 0.0), (0.0, 20.0), (-40.0, 20.0)]
    res = st.sweep_trim(wp, body, frame, prof, [-20.0, 20.0], name="SKEW")
    v1 = mdl.volume(wp, body)
    # The block spans u -30..30, z 0..20, v -20..20 (volume 48000).  The trim
    # keeps the part of the block on the material side of the 45 deg line from
    # (0,20) to (30,0).  Which side is kept depends on the profile winding,
    # which NX normalises, so the assertion is that exactly ONE of the two
    # complementary wedges is kept and the other removed -- at a 45 deg line
    # the two are 24000 (u<-0 full height) and 24000 (the wedge under the
    # line), i.e. the kept volume must be one of them, not something else.
    v_block = 60.0 * 40.0 * 20.0
    half = 0.5 * 30.0 * 20.0 * 40.0      # wedge on one side of the 45 deg line
    v_left = 30.0 * 20.0 * 40.0          # the u<0 half at full height
    say("sweep trim kept=%.4f block=%.4f checks=%r"
        % (v1, v_block, res["checks"]))
    check("T47_SWEEPTRIM_VOLUME",
          abs(v1 - half) < 1e-2 * half or abs(v1 - v_left) < 1e-2 * v_left,
          "the trim must leave one complete side of the 45 deg line "
          "(%.4f or %.4f), got %.4f (block %.4f)"
          % (half, v_left, v1, v_block))
    check("T47_SWEEPTRIM_SINGLE_BODY", res["checks"]["single_body_build"] is True,
          "a skew trim must not split the body: %r" % (res["checks"],))
    check("T47_SWEEPTRIM_PLANE_ONLY",
          all(t == 22 for t in res["checks"]["added_types"]),
          "a straight skew end wall adds only planar faces: %r"
          % (res["checks"]["added_types"],))
    check("T47_SWEEPTRIM_REMOVED", abs(res["checks"]["removed"] - (v0 - v1)) < 1e-6,
          "the ledger must report the volume it removed: %r" % (res["checks"],))

    # a curved end wall: an arc profile leaves a cylindrical face, which a
    # single-plane trim cannot produce at all
    blk2 = mdl.block(wp, NXOpen.Point3d(60.0, -20.0, 0.0), "60", "40", "20")
    b2 = list(blk2.GetBodies())[0]
    v2 = mdl.volume(wp, b2)
    say("arc block bodies=%d (must be 2: the skew block + this one)"
        % len(list(wp.Bodies)))
    # keep everything left of the arc: the arc bulges to +u, so the keep
    # region is the block minus the sliver outside it
    # The block is u 60..120 in world terms, i.e. u -40..20 in this frame's
    # shifted coordinates (the frame origin sits at the block's u=60 face).
    # The keep region must be a STRICT SUBSET of the block or the trim removes
    # nothing: an arc that spans the whole u range leaves the tool outside the
    # body ("completely outside target body").  So the arc cuts a corner off:
    # from (10,0) bulging to +u, back to (10,20).
    # A sampled arc gives 24 planar facets, not a cylinder: the profile has to
    # carry a real arc curve or the end wall is a fan of planes.  This list is
    # only used for the frame/shape check below; the built profile is passed
    # with `sweep_trim_arc` so NX sees one circular edge.
    arc_prof = [(10.0 + 8.0 * math.cos(-math.pi / 2.0 + math.pi * k / 24.0),
                 10.0 + 10.0 * math.sin(-math.pi / 2.0 + math.pi * k / 24.0))
                for k in range(25)]
    prof2 = [(-40.0, 0.0)] + arc_prof + [(-40.0, 20.0)]
    # the block sits at world x 60..120, so the profile frame must sit there
    # too -- the same profile read in the world frame lands outside the body
    # and the boolean is refused ("completely outside target body")
    frame2 = sk.Frame(origin=(60.0, 0.0, 0.0))
    # one real arc so the end wall is a cylinder, not a fan of 24 planes
    segs2 = [
        {"line": [(-40.0, 0.0), (10.0, 0.0)]},
        {"arc": [(10.0, 10.0), 10.0, -90.0, 90.0]},
        {"line": [(10.0, 20.0), (-40.0, 20.0)]},
        {"line": [(-40.0, 20.0), (-40.0, 0.0)]},
    ]
    r2 = st.sweep_trim(wp, b2, frame2, prof2, [-20.0, 20.0], name="ARCTRIM",
                       profile_segs=segs2)
    v3 = mdl.volume(wp, b2)
    say("sweep arc trim volume=%.4f checks=%r types=%r"
        % (v3, r2["checks"], r2["checks"]["added_types"]))
    check("T47_SWEEPTRIM_ARC_FACE",
          16 in r2["checks"]["added_types"],
          "a curved end wall must leave a cylindrical face (a plane trim "
          "cannot): %r" % (r2["checks"]["added_types"],))
    check("T47_SWEEPTRIM_ARC_REMOVED", v2 - v3 > 1.0,
          "the curved trim must remove the material outside the arc: %.4f"
          % (v2 - v3,))
    # the arc profile builds an extra body (the keep-side prism) before the
    # cut; the ledger's `bodies` counts what is left, so it is 2 here while
    # `single_body_build` compares against the pre-build count correctly
    say("arc trim bodies before=%d after=%d"
        % (r2["checks"]["bodies_before"], r2["checks"]["bodies"]))
    return body


def case_window_no_material(wp):
    """A window that lands outside the body must report 'removed nothing'."""
    frame = sk.Frame()
    n0 = len(list(wp.Bodies))
    blk = mdl.block(wp, NXOpen.Point3d(0.0, 0.0, 0.0), "20", "20", "10")
    body = list(blk.GetBodies())[0]
    win = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
    before = len(list(wp.Bodies))
    res = st.window_cut(wp, body, frame, win, 100.0, 120.0, name="WINOUT")
    after = len(list(wp.Bodies))
    say("window out of body checks=%r bodies %d->%d"
        % (res["checks"], before, after))
    check("T47_WINDOW_EMPTY_REPORTED",
          res["pass"] is False and res["checks"]["removed"] == 0.0 and
          "completely outside" in res["checks"]["reason"],
          "a window that removes nothing must say so instead of passing: %r"
          % (res["checks"],))
    check("T47_WINDOW_ROLLBACK", after == before,
          "a rejected boolean must roll the tool body back, not leave it "
          "behind: bodies %d -> %d" % (before, after))
    return body


def main():
    out = os.getcwd()

    path = os.path.join(out, "t47_plate.prt")
    wp = new_part("t47a", path)
    case_plate(wp)
    save_checked(path)

    path = os.path.join(out, "t47_shaft.prt")
    wp = new_part("t47b", path)
    case_shaft(wp)
    save_checked(path)

    path = os.path.join(out, "t47_contrast.prt")
    wp = new_part("t47c", path)
    case_stack_contrast(wp)
    save_checked(path)

    path = os.path.join(out, "t47_bore.prt")
    wp = new_part("t47d", path)
    case_bore_and_holes(wp)
    save_checked(path)

    path = os.path.join(out, "t47_pocket.prt")
    wp = new_part("t47e", path)
    case_pocket(wp)
    save_checked(path)

    path = os.path.join(out, "t47_fillet.prt")
    wp = new_part("t47f", path)
    case_fillet_ledger(wp)
    save_checked(path)

    path = os.path.join(out, "t47_chain.prt")
    wp = new_part("t47g", path)
    case_hole_chain(wp)
    case_cone_mouth(wp)
    case_chain_declared_mismatch(wp)
    save_checked(path)

    path = os.path.join(out, "t47_eye.prt")
    wp = new_part("t47h", path)
    case_eye_and_clevis(wp)
    save_checked(path)

    path = os.path.join(out, "t47_eye_gap.prt")
    wp = new_part("t47i", path)
    case_eye_tangency_gap(wp)
    save_checked(path)

    path = os.path.join(out, "t47_trim.prt")
    wp = new_part("t47j", path)
    case_trim_planes(wp)
    save_checked(path)

    path = os.path.join(out, "t47_precheck.prt")
    wp = new_part("t47k", path)
    case_fillet_precheck(wp)
    save_checked(path)

    path = os.path.join(out, "t47_loft.prt")
    wp = new_part("t47l", path)
    case_section_loft(wp)
    case_resample_ring(wp)
    save_checked(path)

    path = os.path.join(out, "t47_window.prt")
    wp = new_part("t47m", path)
    case_window_cut(wp)
    case_window_no_material(wp)
    save_checked(path)

    path = os.path.join(out, "t47_sweep.prt")
    wp = new_part("t47n", path)
    case_sweep_trim(wp)
    save_checked(path)

    failed = [n for n, good in RESULTS if not good]
    say("TEST47_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST47_FAIL failed=%s" % failed)
        return
    say("TEST47_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST47_FATAL:\n" + traceback.format_exc()[-1200:])
        say("TEST47_FAIL uncaught")
