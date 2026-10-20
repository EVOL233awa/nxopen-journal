# -*- coding: utf-8 -*-
# Test 28: helical patterns in NX12 batch, two routes, both checked against the
# analytic helix r == R, z == p*theta/(2*pi).
#
# Route A -- the native Helix pattern type -- WORKS, and the earlier record that
# called it a dead end was a defect in the probe, not in NX: the probe asked for an
# axis with part.Axes.CreateAxis(NXOpen.Axis.Null, NXOpen.Xform.Null, ...), which
# dies with "NXException: Internal error: memory access violation", and concluded
# that NX12 has no axis factory. The measured signature takes a POINT and a
# DIRECTION, and it is what 02_flange.py's circular pattern has always used:
#   axis = part.Axes.CreateAxis(NXOpen.Point3d(0,0,0),
#                               NXOpen.Vector3d(0,0,1),
#                               NXOpen.SmartObject.UpdateOption.WithinModeling)
#   pd.PatternType = PatternDefinition.PatternEnum.Helix
#   hd = pd.HelixDefinition                    # NXOpen.GeometricUtilities.HelixPattern
#   hd.SizeOption = HelixPattern.SizeOptions.CountHelixPitchAndTurns
#   hd.CountOfInstances.RightHandSide = "4"    # Expressions, no SetRightHandSide
#   hd.NumberOfTurns.RightHandSide    = "1"
#   hd.HelixPitch.RightHandSide       = "20"
#   hd.RotationAxis = axis                     # NXOpen.Axis; a Point is a TypeError
# Measured () on a 5 mm seed cube centred at r = 20: 3 new bodies at
# theta = 120/240/360 deg with z = 6.6667/13.3333/20.0000 and r = 20.0000, i.e.
# z = HelixPitch*theta/(2*pi) to 0.0000 mm. CountOfInstances counts the seed
# (the angular step is 360/(CountOfInstances-1) = 120 deg) and the rise is
# HelixPitch per full turn. HelixPattern members: AnglePitch / CountOfInstances /
# DirectionType / DirectionTypes / DistancePitch / HelixPitch / HelixSpan /
# NumberOfTurns / RotationAxis / SizeOption / SizeOptions; SizeOptions is
# AngleHelixPitchAndSpan, AngleHelixPitchAndTurns, CountAngleDistance,
# CountHelixPitchAndSpan, CountHelixPitchAndTurns.
# Passing Axis.Null is accepted and means "no axis"; committing then produces no
# new body at all, so the failure mode to watch for is a silent empty pattern.
#
# Route B -- a Helix CURVE plus an AlongPath pattern -- arrays a solid along an
# arbitrary curve, which the Helix pattern type cannot do:
#   hb = part.Features.CreateHelixBuilder(NXOpen.Features.Helix.Null)
#        ^^ the Null class is Features.Helix, not Features.Feature
#   hb.Type = HelixBuilder.Types.AlongVector
#   hb.CoordinateSystem = csys          <- direct assignment; the getter is None
#   hb.SizeOption = HelixBuilder.SizeOptions.Radius
#   hb.LengthMethod = HelixBuilder.LengthMethods.Turns
#   hb.Turns.RightHandSide = "2"        <- Expression
#   hb.SizeLaw.Value.RightHandSide  = "20"   <- Value is an Expression, not a
#   hb.PitchLaw.Value.RightHandSide = "20"      float; the law property itself
#                                              is read-only
# The pattern needs three settings, and the measured semantics are:
#   apd.XPath.AddToSection(...)                     the curve the pattern follows
#   sp = apd.XOnPathSpacing                         OnPathDistancePatternSpacing
#   sp.SpaceType = PatternSpacingSpacingType.Pitch  the enum is NOT reachable as
#     PatternSpacing.SpaceType (that name is the property descriptor); members are
#     Offset=0 Span=1 PitchAndSpan=2 Pitch=3 List=4 PolygonCountPerSide=5
#     PolygonPitchAlongSide=6. Offset is the default.
#   sp.OnPathPitchDistance.IsPercentUsed = False    <- default True, so a bare
#     number is read as PERCENT of the path: "63.62252" meant 63.62 % = 161.9 mm
#   sp.OnPathPitchDistance.Expression.RightHandSide = "<mm>"   <- the distance
#     slot is an OnPathDimensionBuilder, so it has no RightHandSide itself; the
#     writable Expression hangs off it
#   sp.NCopies.RightHandSide = "<n>"                Expression
# Measured behaviour:
#   * Pitch mode, pitch = arc/4 = 63.62252 mm, NCopies=5 -> exactly 4 instances at
#     arc lengths 63.62/127.25/190.87/254.49, i.e. z = 10/20/30/40 at r = 20, every
#     centroid matching the closed form to 0.000 mm
#   * the same with NCopies=6 -> still 4: copies that would land past the end of
#     the path are NOT created, they are not extrapolated
#   * Span mode with the span set to the whole path and NCopies=4 -> 3 instances,
#     evenly divided, so NCopies counts the seed as well (span/(NCopies-1))
#   * the default Offset mode ignores both distances and spaced the instances one
#     whole turn apart (z = 20 and 40 on a 2-turn helix)
#   * NCopies on its own therefore does not size the pattern at all: in Offset
#     mode NCopies=3, 4, 6 and 8 all produced the same 2 instances
import math
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
import NXOpen.UF

OUT_DIR = os.path.join(os.path.dirname(__file__), "parts")
PART = os.path.join(OUT_DIR, "t28_pattern_helix.prt")

RADIUS = 20.0
PITCH = 20.0
TURNS = 2.0
NCOPIES = 5
COPIES_NATIVE = 4
NATIVE_TURNS = 1.0
SEED = 5.0
LEN_TOL = 0.01          # spline approximation of the exact helix length
POS_TOL = 0.05          # mm, on-helix membership
TWO_PI = 2.0 * math.pi
# the closed form the positions are checked against: one radian of a helix of
# radius R and pitch p is sqrt(R^2 + (p/2pi)^2) long
ARC_PER_RAD = math.sqrt(RADIUS ** 2 + (PITCH / TWO_PI) ** 2)
ARC_ANALYTIC = TURNS * TWO_PI * ARC_PER_RAD
TURN_ARC = ARC_ANALYTIC / TURNS

RESULTS = []


def say(msg):
    sys.stdout.write(str(msg) + "\n")
    sys.stdout.flush()


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    say("%s=%s %s" % (name, "PASS" if ok else "FAIL", detail))


def new_part(session, path):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    if os.path.exists(path):
        os.remove(path)
    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.UseBlankTemplate = False
    fn.NewFileName = path
    fn.Commit()
    fn.Destroy()
    part = session.Parts.Work
    NXOpen.UF.UFSession.GetUFSession().Part.SetDisplayPart(part.Tag)
    return part


def block(wp, origin, lx, ly, lz):
    b = wp.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    b.SetOriginAndLengths(NXOpen.Point3d(*origin), lx, ly, lz)
    f = b.CommitFeature()
    b.Destroy()
    return f


def centroids(part, bodies):
    uc = part.UnitCollection
    units = [uc.FindObject(n) for n in
             ("SquareMilliMeter", "CubicMilliMeter", "Kilogram", "MilliMeter",
              "Newton")]
    out = []
    for b in bodies:
        c = part.MeasureManager.NewMassProperties(units, [0.99], [b]).Centroid
        out.append((c.X, c.Y, c.Z))
    return out


def set_expr(owner, attr, value):
    """Pattern/law parameters are Expressions: RightHandSide is the setter."""
    got = getattr(owner, attr)
    if hasattr(got, "RightHandSide"):
        got.RightHandSide = value
        return "%s.RightHandSide=%s (now %r)" % (attr, value, got.RightHandSide)
    setattr(owner, attr, value)
    return "%s <- %s (direct)" % (attr, value)


def make_csys(part):
    pt = part.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0))
    xd = part.Directions.CreateDirection(pt, NXOpen.Vector3d(1.0, 0.0, 0.0))
    zd = part.Directions.CreateDirection(pt, NXOpen.Vector3d(0.0, 0.0, 1.0))
    xf = part.Xforms.CreateXformByPointXDirZDir(
        pt, xd, zd, NXOpen.SmartObject.UpdateOption.WithinModeling, 1.0)
    return part.CoordinateSystems.CreateCoordinateSystem(
        xf, NXOpen.SmartObject.UpdateOption.WithinModeling)


def helix_point(s):
    """The analytic helix point at arc length s: r = R and z = p*theta/2pi."""
    th = s / ARC_PER_RAD
    return (RADIUS * math.cos(th), RADIUS * math.sin(th), PITCH * th / TWO_PI)


def match_against(got, want, label):
    """(ok, detail) -- pairwise against the analytic points, z-sorted."""
    say("%s pairwise:" % label)
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else None
        w = want[i] if i < len(want) else None
        if g is None or w is None:
            say("%s   i=%d got=%s want=%s" % (label, i, g, w))
            continue
        say("%s   i=%d C=(%.4f,%.4f,%.4f) want=(%.4f,%.4f,%.4f) dev=%.4f"
            % (label, i, g[0], g[1], g[2], w[0], w[1], w[2],
               max(abs(g[0] - w[0]), abs(g[1] - w[1]), abs(g[2] - w[2]))))
    if len(got) != len(want):
        return False, "instances=%d expected=%d" % (len(got), len(want))
    worst = 0.0
    for g, w in zip(got, want):
        worst = max(worst, max(abs(g[0] - w[0]), abs(g[1] - w[1]),
                               abs(g[2] - w[2])))
    return worst <= POS_TOL, "max_dev=%.4f mm (tol %.2f)" % (worst, POS_TOL)


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()
    part = new_part(session, PART)
    HB = NXOpen.Features.HelixBuilder
    GU = NXOpen.GeometricUtilities
    ST = GU.PatternSpacingSpacingType

    # ================================================ route A: the Helix pattern
    axis = part.Axes.CreateAxis(
        NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    check("REG_AXIS_FACTORY", isinstance(axis, NXOpen.Axis),
          "Axes.CreateAxis(Point3d, Vector3d, UpdateOption) -> %s; the old probe "
          "passed NXOpen.Axis.Null in the Point3d slot and crashed"
          % type(axis).__name__)

    hd = GU.HelixPattern
    want_opts = ["AngleHelixPitchAndSpan", "AngleHelixPitchAndTurns",
                 "CountAngleDistance", "CountHelixPitchAndSpan",
                 "CountHelixPitchAndTurns"]
    got_opts = sorted(n for n in dir(hd.SizeOptions) if not n.startswith("_")
                      and n != "ValueOf")
    check("REG_HELIXPATTERN_SIZEOPTIONS", got_opts == sorted(want_opts),
          "HelixPattern.SizeOptions = %s" % got_opts)

    seed_a = block(part, (RADIUS - SEED / 2.0, -SEED / 2.0, -SEED / 2.0),
                   "%.1f" % SEED, "%.1f" % SEED, "%.1f" % SEED)
    pba = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    pba.FeatureList.SetArray([seed_a])
    pbo = NXOpen.Features.PatternFeatureBuilder
    pba.PatternMethod = pbo.PatternMethodOptions.Simple
    pba.OutputOption = pbo.OutputOptions.PatternFeature
    pda = pba.PatternService
    pda.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Helix
    hda = pda.HelixDefinition
    hda.SizeOption = hd.SizeOptions.CountHelixPitchAndTurns
    for attr, val in (("CountOfInstances", "%.0f" % COPIES_NATIVE),
                      ("NumberOfTurns", "%.1f" % NATIVE_TURNS),
                      ("HelixPitch", "%.1f" % PITCH)):
        try:
            set_expr(hda, attr, val)
        except Exception as exc:
            say("HELIXPATTERN_SET_FAILED %s: %s: %s"
                % (attr, type(exc).__name__, str(exc)[:120]))
    msg = ""
    try:
        hda.RotationAxis = NXOpen.Point3d(0.0, 0.0, 0.0)
        msg = "accepted a Point3d (no exception)"
    except Exception as exc:
        msg = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    check("REG_HELIXPATTERN_AXIS_TYPE", "NXOpen.Axis" in msg,
          "HelixPattern.RotationAxis wants NXOpen.Axis only -> %s" % msg)
    hda.RotationAxis = axis
    check("REG_HELIXPATTERN_AXIS_READBACK",
          type(hda.RotationAxis).__name__ == "Axis",
          "RotationAxis <- the CreateAxis result, readback is a %s"
          % type(hda.RotationAxis).__name__)

    before = set(int(b.Tag) for b in part.Bodies)
    if not pba.Validate():
        say("HELIXPATTERN_VALIDATE=False")
    pba.CommitFeature()
    pba.Destroy()
    new_a = [b for b in part.Bodies if int(b.Tag) not in before]
    got_a = sorted(centroids(part, new_a), key=lambda c: c[2])
    want_a = [helix_point(TURN_ARC * (k + 1.0) / (COPIES_NATIVE - 1.0))
              for k in range(COPIES_NATIVE - 1)]
    ok_a, det_a = match_against(got_a, want_a, "NATIVE")
    check("REG_HELIXPATTERN_INSTANCES", len(new_a) == COPIES_NATIVE - 1,
          "CountOfInstances=%.0f counts the seed -> %d new bodies (%s)"
          % (COPIES_NATIVE, len(new_a), det_a))
    check("REG_HELIXPATTERN_ON_HELIX", ok_a,
          "every instance must sit on z = p*theta/2pi at r = %.0f: %s"
          % (RADIUS, det_a))

    # ============================== route B, step 1: a two-turn helix as a curve
    csys = make_csys(part)
    check("REG_HELIX_CSYS", type(csys).__name__ == "CartesianCoordinateSystem",
          "csys=%s" % type(csys).__name__)

    hb = part.Features.CreateHelixBuilder(NXOpen.Features.Helix.Null)
    hb.Type = HB.Types.AlongVector
    hb.SizeOption = HB.SizeOptions.Radius
    hb.TurnDirection = HB.TurnDirections.RightHand
    hb.LengthMethod = HB.LengthMethods.Turns
    try:
        hb.CoordinateSystem = csys
        csys_ok = hb.CoordinateSystem is not None
        csys_msg = "%s" % type(hb.CoordinateSystem).__name__
    except Exception as exc:
        csys_ok = False
        csys_msg = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    check("REG_HELIX_CSYS_ASSIGN", csys_ok,
          "CoordinateSystem <- csys: %s (the getter starts at None, the setter "
          "takes the object directly)" % csys_msg)

    law_msg = []
    for owner, attr, val in ((hb, "SizeLaw", "%.4f" % RADIUS),
                             (hb, "PitchLaw", "%.4f" % PITCH)):
        try:
            law = getattr(owner, attr)
            law_msg.append("%s.Value.%s" % (attr, set_expr(law, "Value", val)))
        except Exception as exc:
            law_msg.append("%s FAILED %s: %s" % (attr, type(exc).__name__,
                                                 str(exc)[:120]))
    try:
        law_msg.append("Turns." + set_expr(hb, "Turns", "%.1f" % TURNS))
    except Exception as exc:
        law_msg.append("Turns FAILED %s: %s" % (type(exc).__name__, str(exc)[:120]))
    say("HELIX_PARAMS " + " | ".join(law_msg))

    ok = True
    detail = []
    for attr, want in (("SizeLaw", RADIUS), ("PitchLaw", PITCH)):
        try:
            got = float(getattr(hb, attr).Value.Value)
            detail.append("%s=%.3f" % (attr, got))
            ok = ok and abs(got - want) < 1e-3
        except Exception as exc:
            detail.append("%s read failed %s" % (attr, str(exc)[:60]))
            ok = False
    try:
        t = float(hb.Turns.RightHandSide)
        detail.append("Turns=%.3f" % t)
        ok = ok and abs(t - TURNS) < 1e-6
    except Exception as exc:
        detail.append("Turns read failed %s" % str(exc)[:60])
        ok = False
    check("REG_HELIX_PARAMS", ok, " ".join(detail))

    helix = hb.CommitFeature()
    hb.Destroy()
    spline = None
    for e in helix.GetEntities():
        spline = e
    check("REG_HELIX_FEATURE",
          getattr(helix, "FeatureType", "") == "HELIX" and spline is not None,
          "feature=%s entity=%s" % (getattr(helix, "FeatureType", "?"),
                                    type(spline).__name__ if spline else None))

    arc = spline.GetLength()
    check("REG_HELIX_LENGTH", abs(arc - ARC_ANALYTIC) <= LEN_TOL * ARC_ANALYTIC,
          "length=%.4f analytic=%.4f (turns*sqrt((2*pi*r)^2+p^2))"
          % (arc, ARC_ANALYTIC))

    # ------------------------------------- route B, step 2: pattern along it
    seed = block(part, (RADIUS - SEED / 2.0, -SEED / 2.0, -SEED / 2.0),
                 "%.1f" % SEED, "%.1f" % SEED, "%.1f" % SEED)

    def along_path(mode, ncopies, dist_attr, dist_value, percent):
        """Run one along-path pattern; returns (ok, message, centroids)."""
        before_b = set(int(b.Tag) for b in part.Bodies)
        try:
            pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
            pb.FeatureList.SetArray([seed])
            pb.PatternMethod = pbo.PatternMethodOptions.Simple
            pb.OutputOption = pbo.OutputOptions.PatternFeature
            pd = pb.PatternService
            pd.PatternType = GU.PatternDefinition.PatternEnum.AlongPath
            apd = pd.AlongPathDefinition
            rule = part.ScRuleFactory.CreateRuleCurveDumb([spline])
            apd.XPath.AddToSection([rule], spline, NXOpen.NXObject.Null,
                                   NXOpen.NXObject.Null,
                                   NXOpen.Point3d(0.0, 0.0, 0.0),
                                   NXOpen.Section.Mode.Create, False)
            sp = apd.XOnPathSpacing
            if mode is not None:
                sp.SpaceType = mode
            set_expr(sp, "NCopies", str(ncopies))
            if dist_attr:
                b = getattr(sp, dist_attr)
                b.IsPercentUsed = percent
                b.Expression.RightHandSide = dist_value
                msg = "%s=%s IsPercentUsed=%r SpaceType=%d" % (
                    dist_attr, dist_value, b.IsPercentUsed, sp.SpaceType.value)
            else:
                msg = "SpaceType=%d (distance untouched)" % sp.SpaceType.value
            if not pb.Validate():
                pb.Destroy()
                return False, "Validate() False: " + msg, []
            pb.CommitFeature()
            pb.Destroy()
            new = [b for b in part.Bodies if int(b.Tag) not in before_b]
            return True, msg, sorted(centroids(part, new), key=lambda c: c[2])
        except Exception as exc:
            return False, "%s: %s" % (type(exc).__name__, str(exc)[:200]), []

    enum_got = {}
    enum_msg = []
    for name in ("Offset", "Span", "PitchAndSpan", "Pitch", "List"):
        try:
            enum_got[name] = getattr(ST, name).value
        except Exception as exc:
            enum_msg.append("%s missing (%s)" % (name, str(exc)[:60]))
    check("REG_ALONGPATH_SPACING_ENUM",
          enum_got.get("Offset") == 0 and enum_got.get("Span") == 1
          and enum_got.get("Pitch") == 3 and enum_got.get("List") == 4,
          "PatternSpacingSpacingType values: %s %s" % (enum_got, " ".join(enum_msg)))

    # the pitch distances must come from the MEASURED spline length, not from the
    # closed form: the spline is 254.4901 mm against an analytic 254.4906, and a
    # 1e-4 mm overshoot on the pitch puts the last instance just past the end of
    # the path, where it is silently dropped (measured). Four steps of arc/4 fit.
    step = arc / 4.0
    want_p = [helix_point(step * (i + 1)) for i in range(4)]
    ok_p, msg_p, got_p = along_path(ST.Pitch, NCOPIES, "OnPathPitchDistance",
                                    "%.5f" % step, False)
    ok_m, det_m = match_against(got_p, want_p, "PITCH") if ok_p else (False, msg_p)
    check("REG_ALONGPATH_PITCH", ok_p and ok_m,
          "Pitch mode, on-path pitch %.5f mm (arc/4 of the measured path), "
          "NCopies=%d -> %s" % (step, NCOPIES, det_m))

    ok_q, msg_q, got_q = along_path(ST.Pitch, NCOPIES + 1, "OnPathPitchDistance",
                                    "%.5f" % step, False)
    ok_m2, det_m2 = match_against(got_q, want_p, "PITCH_N6") if ok_q else (False, msg_q)
    check("REG_ALONGPATH_TRUNCATED", ok_q and ok_m2,
          "NCopies=%d against a path that fits 4 pitches gives the same 4 "
          "instances (%s)" % (NCOPIES + 1, det_m2))

    want_s = [helix_point(arc * i / 3.0) for i in (1, 2, 3)]
    ok_s, msg_s, got_s = along_path(ST.Span, 4, "OnPathSpanDistance",
                                    "%.5f" % arc, False)
    ok_m3, det_m3 = match_against(got_s, want_s, "SPAN") if ok_s else (False, msg_s)
    check("REG_ALONGPATH_SPAN", ok_s and ok_m3,
          "Span mode, span = the whole path, NCopies=4 -> span/(NCopies-1) "
          "spacing, %s" % det_m3)

    want_o = [helix_point(TURN_ARC * k) for k in (1, 2)]
    ok_o, msg_o, got_o = along_path(None, 8, None, None, True)
    ok_m4, det_m4 = match_against(got_o, want_o, "OFFSET") if ok_o else (False, msg_o)
    check("REG_ALONGPATH_OFFSET_DEFAULT", ok_o and ok_m4,
          "default Offset spacing with NCopies=8 put instances one whole turn "
          "apart and ignored the distance slots (%s)" % det_m4)

    ufs.Part.Save()
    size = os.path.getsize(PART) if os.path.exists(PART) else 0
    check("REG_ARTIFACTS_LANDED", size > 0, "PART=%s size=%d" % (PART, size))

    # Native-error probe LAST (same rule as test 26): the wrong argument shape for
    # Axes.CreateAxis takes the process down a native path. Judge it by the message,
    # never by the exit code.
    crash = ""
    try:
        part.Axes.CreateAxis(NXOpen.Axis.Null, NXOpen.Xform.Null,
                             NXOpen.SmartObject.UpdateOption.WithinModeling)
        crash = "returned normally (the recorded crash no longer reproduces)"
    except Exception as exc:
        crash = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    check("REG_AXIS_FACTORY_ARGS", "memory access violation" in crash,
          "Axes.CreateAxis(NXOpen.Axis.Null, Xform.Null, ...) -> %s (this is the "
          "call that made an earlier probe call the factory dead)" % crash)

    failed = [n for n, v in RESULTS if not v]
    say("TEST28_CASES=%d" % len(RESULTS))
    if failed:
        say("TEST28_FAIL failed=%s" % failed)
        return
    say("TEST28_DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        say("TEST28_FATAL:\n" + traceback.format_exc()[-800:])
        say("TEST28_FAIL uncaught")
