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
