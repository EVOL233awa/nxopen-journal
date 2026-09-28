# -*- coding: utf-8 -*-
# Test 32: the two PatternEnum members test 28 does not reach -- Polygon and
# General.
#
# Measured 2026-09-23, NX 12.0.0.27, headless batch. Every case builds its OWN
# part: probe 34 ran four polygon cases in one part, the first commit was refused
# and every later property assignment then reported error text that did not
# belong to the call being made ("Expecting int type, found str" for an Axis
# assignment). With a fresh part and a fresh builder per case all of them
# committed cleanly (probe 36), so the cases here are separated on purpose.
#
# POLYGON
#   pd.PatternType = PatternDefinition.PatternEnum.Polygon
#   pg = pd.PolygonDefinition                       (NXOpen.GeometricUtilities.PolygonPattern)
#   pg.RotationAxis = <NXOpen.Axis>                 the axis through the pattern centre
#   pg.NumberOfSides.RightHandSide = '6'            an EXPRESSION: assigning the
#     int 6 raises TypeError "Expecting Unicode str type, found int" (measured)
#   pg.PolygonSizeOption = PolygonPattern.SizeOptions.Inscribed   (or Circumscribed)
#   pg.PolygonSpacing.SpaceType = PatternSpacingSpacingType.PolygonCountPerSide
#     ^ the spacing is a read-only property holding a writable object; the enum is
#       the module level PatternSpacingSpacingType (members: Offset=0 Span=1
#       PitchAndSpan=2 Pitch=3 List=4 PolygonCountPerSide=5 PolygonPitchAlongSide=6)
#   pg.PolygonSpacing.NCopies.RightHandSide = '2'
#   Measured layout (probe 38, 2026-09-23): the regular polygon has its VERTICES on
#   the circle of radius R (the seed centroid's distance from the axis) and its
#   phase set by the seed, so the seed itself is a vertex. Every side is then cut
#   into NCopies-1 equal steps, i.e. NCopies-1 instances sit on each side with the
#   shared vertex counted once -> sides*(NCopies-1) instances in total. Readings:
#     N=6 NCopies=2 ->  6 bodies, radii [17.5000],               gaps all 60.0000
#     N=6 NCopies=3 -> 12 bodies, radii [15.1554, 17.5000],      gaps all 30.0000
#     N=6 NCopies=4 -> 18 bodies, radii [15.4335, 17.5000],      gaps 19.1066/21.7868
#     N=6 NCopies=5 -> 24 bodies, radii [15.1554, 15.7743, 17.5], gaps 13.8979/16.1021
#     N=4 NCopies=3 ->  8 bodies, radii [12.3744, 17.5000],      gaps all 45.0000
#     N=4 NCopies=4 -> 12 bodies, radii [13.0437, 17.5000],      gaps 26.5651/36.8698
#   The unequal gaps from NCopies=4 on are the visible proof that the spacing runs
#   ALONG each side (equal chord steps) rather than at equal angles: for N=6 the
#   3-per-side layout puts the interior pair at 19.1066/21.7868 deg, not 20/20.
#   NCopies=1 gives 0 instances per side and the commit is refused with NXException
#   "Update undo happened." (probe 38, kept as the stage 7 negative control).
#   seed centroid at r=12.5 -> 6 bodies at r=12.5000, so R really follows the seed.
#   PolygonSizeOption Inscribed and Circumscribed produced IDENTICAL readings in
#   every configuration measured (NCopies 2, 3 and 4, N=4 and 6), so this test does
#   not claim a difference between them.
#   ⚠ An axis that does NOT pass through the origin has no working recipe here: with
#   the axis based at (30,10,0) and the seed 17.5 away from it, the 6 copies landed
#   at radii 16.0078..48.5412 from the ORIGIN with gaps 5.6693..296.5524 deg, and
#   assigning RotationCenter that same point changed nothing (probe 38). Keep the
#   polygon axis through the origin.
#   Leaving PolygonSpacing at its Offset default instead laid out 17 instances on
#   two different radii (probe 32), which is why the mode is set explicitly here.
#
# GENERAL
#   pd.PatternType = PatternDefinition.PatternEnum.General
#   gd = pd.GeneralDefinition                       (NXOpen.GeometricUtilities.GeneralPattern)
#   gd.FromLocationType = GeneralPattern.FromLocationOptions.Point
#     ^ a nested enum; the module level name GeneralPatternFromLocationOptionsMemberType
#       is the value type and has no members reachable from Python
#   gd.FromLocationPoint = <NXOpen.Point>           the seed's reference location
#   gd.ToPoints is an NXOpen.Section, NOT a point list: fill it with a selection
#   intent rule built from points --
#     rule = part.ScRuleFactory.CreateRuleCurveDumbFromPoints(points)
#     gd.ToPoints.AddToSection([rule], points[0], NXObject.Null, NXObject.Null,
#                              Point3d(0,0,0), Section.Mode.Create, False)
#   Measured: 3 target points -> 3 new bodies whose centroids are exactly those
#   points (deviation 4.4e-15 mm), and the seed body stays where it was. Committing
#   with ToPoints left empty is refused with NXException "Update undo happened."
#   (measured in probe 32) - that is the stage 5 negative control.
#
# REFERENCE
#   pd.PatternType = PatternDefinition.PatternEnum.Reference
#   rd = pd.ReferenceDefinition                    (NXOpen.GeometricUtilities.ReferencePattern)
#   rd.ReferencedPattern.SetValue(<pattern feature>, NXOpen.View.Null,
#                                 NXOpen.Point3d(0,0,0))
#     ^ ReferencedPattern is NOT writable (assigning it raises AttributeError
#       "not writable", probe 39). It is an NXOpen.SelectNXObject: the read-only
#       property hands out a selection OBJECT, and the selection is filled with
#       SetValue(selection, view, point) - the same shape as
#       MirrorPattern.ExistingPlane (: SelectISurface) and
#       SpiralPattern.HorizontalRef (: HorizontalReference). Reading the property
#       back with GetValue() returns (object, view, point), which is how the tests
#       confirm the selection took.
#   rd.SetBaseInstance(i, j) / rd.ResetBaseInstance() choose WHICH instance of the
#   referenced pattern is mapped onto the seed: with a 3-up linear pattern at pitch
#   30 that the seed sits on, the default base instance reproduces the referenced
#   offsets (0, 30, 60) from the seed's own position, while SetBaseInstance(1, 0)
#   shifts the whole layout by one pitch (-30, 0, 30). Both measured 2026-09-23.
#
# MIRROR -- measured refusal, kept as a negative control
#   pd.PatternType = PatternDefinition.PatternEnum.Mirror is reachable and
#   MirrorDefinition.PlaneOption / NewPlane / ExistingPlane all behave (the plane
#   reads back as the object that was assigned, and md.Validate() returns True),
#   but pb.CommitFeature() is refused with NXException "Feature cannot be
#   mirrored." - and so is pb.Validate(), before any geometry work. Twenty
#   controlled commits over probes 41 to 47 all failed the same way, covering:
#   a Plane smart object, a datum plane object, a Plane built from a datum
#   feature, a fixed plane, a planar face of another body, PlaneOption Existing
#   and New (and both filled at once), PatternMethod Simple and Variational,
#   all three OutputOptions, the type set before and after the feature list, a
#   real display view in the selection, an explicit reference point, and both a
#   Block (base feature) and a simple Hole (child feature) as the seed. So the
#   refusal is in the Pattern Feature builder, not in the inputs. Mirroring
#   features is done with Features.MirrorFeatureBuilder instead (test 03).
#
# SPIRAL
#   pd.PatternType = PatternDefinition.PatternEnum.Spiral
#   sd = pd.SpiralDefinition                       (NXOpen.GeometricUtilities.SpiralPattern)
#   sd.SizeSpiralType = SpiralPattern.SpiralDefineSize.NumberOfTurns (or TotalAngle)
#   sd.NumberOfTurns / RadialPitch / TotalAngle are Expressions (RightHandSide)
#   sd.PitchAlongSpiral is an OnPathDistancePatternSpacing: SpaceType = Pitch, and
#     the distance hangs off OnPathPitchDistance.Expression (IsPercentUsed made no
#     measured difference here, unlike the AlongPath case in test 28)
#   sd.SpiralNormal = <NXOpen.Direction>          the spiral's plane normal
#   sd.HorizontalRef.HorizontalRefVector = <Direction>   the WORKING form;
#     HorizontalRef.HorizontalRefObject is a selection and leaving it empty makes
#     the commit fail with "No section curves or points created." (stage 12)
#   Measured baseline (seed 5 mm block, centroid on +x at r=20; turns=1,
#   RadialPitch=10, along pitch=20, normal +z, horizontal ref +x): 2 bodies, the
#   seed at (r=20.0000, 0.0000 deg, z=0) and one instance at (r=21.4797..21.4799,
#   20.5051..20.5052 deg, z=0) over two runs. The instance layout of larger
#   configurations is NOT an origin-centred Archimedean spiral: with turns=2,
#   RadialPitch=20, along=10 the 26 instances span radii 9.86 to 59.19 mm and
#   their radii are not monotonic in the angle about the origin (a least-squares
#   fit for spiral centre and pitch left a 1.8 mm residual), and turns=1 with
#   along=40 produced no instance at all. The stage below therefore pins the
#   measured baseline, and the layout law is explicitly NOT claimed.
import math
import os
import sys
import traceback

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities
import NXOpen.UF

PART_POLY_HEX = "pat32_hex.prt"
PART_POLY_SQUARE = "pat32_square.prt"
PART_POLY_HEX_C4 = "pat32_hex_c4.prt"
PART_POLY_HEX_C1 = "pat32_hex_c1.prt"
PART_POLY_HEX_FAR = "pat32_hex_far.prt"
PART_GENERAL = "pat32_general.prt"
PART_GENERAL_EMPTY = "pat32_general_empty.prt"
PART_REFERENCE = "pat32_reference.prt"
PART_REFERENCE_BASE = "pat32_reference_base.prt"
PART_MIRROR = "pat32_mirror.prt"
PART_SPIRAL = "pat32_spiral.prt"
PART_SPIRAL_NOHREF = "pat32_spiral_nohref.prt"
SEED = 5.0
SEED_CENTRE_R = 17.5          # the polygon radius the layout follows (measured)
SEED_CENTRE_R_FAR = 12.5
POS_TOL = 1e-3
GENERAL_TOL = 1e-6
REF_PITCH = 30.0              # x spacing of the linear pattern used as the reference
REF_COPIES = 3
REF_SEED_Y = 60.0             # the reference pattern's seed sits this far off in y
SPIRAL_R = 20.0               # spiral seed's distance from the origin
SPIRAL_TURNS = 1
SPIRAL_RADIAL_PITCH = 10
SPIRAL_ALONG_PITCH = 20
# measured over two runs (probe 41 and probe 45): r 21.4797 / 21.4799, angle
# 20.5051 / 20.5052 deg, so the tolerances below are deliberately not tighter
SPIRAL_R_TOL = 1e-2
SPIRAL_ANGLE_TOL = 2e-2
SPIRAL_INSTANCE_R = 21.4798
SPIRAL_INSTANCE_ANGLE = 20.5052
MIRROR_REFUSAL = "cannot be mirrored"
NO_HREF_REFUSAL = "No section curves or points"
POLYGON_ENUMS = ["AlongPath", "Circular", "General", "Helix", "Linear", "Mirror",
                 "Polygon", "Reference", "Spiral"]
FROM_POINT = (17.5, 0.0, 30.0)
TO_POINTS = ((0.0, 0.0, 30.0), (40.0, 0.0, 30.0), (40.0, 30.0, 30.0))

FAILED_STAGES = []


def say(msg):
    sys.stdout.write(str(msg) + "\n")
    sys.stdout.flush()


def stage(name, fn):
    try:
        fn()
        say("STAGE_OK " + name)
    except Exception as exc:
        FAILED_STAGES.append(name)
        say("STAGE_FAIL " + name + " :: " + str(exc))


def new_part(session, ufs, name):
    target = os.path.abspath(name)
    if os.path.exists(target):
        os.remove(target)
    fn = session.Parts.FileNew()
    fn.Units = NXOpen.Part.Units.Millimeters
    fn.TemplateFileName = "model-plain-1-mm-template.prt"
    fn.NewFileName = name
    fn.UseBlankTemplate = False
    part = fn.Commit()
    fn.Destroy()
    session.Parts.SetWork(part)
    ufs.Part.SetDisplayPart(part.Tag)
    return part


def block(part, origin, size):
    b = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    b.SetOriginAndLengths(NXOpen.Point3d(*origin), "%.4f" % size, "%.4f" % size,
                          "%.4f" % size)
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
        out.append((int(b.Tag), c.X, c.Y, c.Z))
    return out


def layout(part):
    """(radius, angle_deg, z) of every body in the part, angle sorted."""
    rows = []
    for _tag, x, y, z in centroids(part, list(part.Bodies)):
        rows.append((math.hypot(x, y), math.degrees(math.atan2(y, x)) % 360.0, z))
    return sorted(rows, key=lambda r: r[1])


def positions(part):
    """(body tag, x, y, z) of every body, tag sorted."""
    return sorted(centroids(part, list(part.Bodies)), key=lambda c: c[0])


def linear_pattern(part, seed, pitch, copies):
    """The linear pattern the reference pattern points at, along +x from the seed."""
    pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        pb.FeatureList.SetArray([seed])
        pb.PatternMethod = \
            NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
        pb.OutputOption = \
            NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
        GU = NXOpen.GeometricUtilities
        pd = pb.PatternService
        pd.PatternType = GU.PatternDefinition.PatternEnum.Linear
        rect = pd.RectangularDefinition
        rect.XDirection = part.Directions.CreateDirection(
            NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(1.0, 0.0, 0.0),
            NXOpen.SmartObject.UpdateOption.WithinModeling)
        rect.XSpacing.SpaceType = GU.PatternSpacing.SpacingType.Pitch
        rect.XSpacing.PitchDistance.RightHandSide = "%d" % int(pitch)
        rect.XSpacing.NCopies.RightHandSide = "%d" % copies
        return pb.CommitFeature()
    finally:
        pb.Destroy()


def datum_plane_x(part, x):
    pt = part.Points.CreatePoint(NXOpen.Point3d(x, 0.0, 0.0))
    dr = part.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    db = part.Features.CreateDatumPlaneBuilder(NXOpen.Features.Feature.Null)
    db.SetPointAndDirection(pt, dr)
    feat = db.CommitFeature()
    db.Destroy()
    return feat


def polygon_points(sides, ncopies, seed_centre_r, phase_deg=0.0):
    """Where the polygon pattern puts its instances, worked out without NX.

    The polygon's vertices are on the circle of radius seed_centre_r, one of them
    under the seed (phase_deg is that vertex's angle); each side is cut into
    ncopies-1 equal steps, so ncopies-1 instances lie on every side and the shared
    vertex is counted once: sides*(ncopies-1) instances.
    """
    out = []
    step = 2.0 * math.pi / sides
    for s in range(sides):
        a0 = math.radians(phase_deg) + s * step
        for k in range(ncopies - 1):
            t = k / float(ncopies - 1)
            out.append((seed_centre_r * ((1.0 - t) * math.cos(a0) +
                                         t * math.cos(a0 + step)),
                        seed_centre_r * ((1.0 - t) * math.sin(a0) +
                                         t * math.sin(a0 + step))))
    return sorted(out, key=lambda p: math.atan2(p[1], p[0]))


def polygon_case(session, ufs, label, part_name, sides, seed_centre_r, ncopies,
                 expect_refusal=False):
    part = new_part(session, ufs, part_name)
    axis = part.Axes.CreateAxis(NXOpen.Point3d(0.0, 0.0, 0.0),
                                NXOpen.Vector3d(0.0, 0.0, 1.0),
                                NXOpen.SmartObject.UpdateOption.WithinModeling)
    seed = block(part, (seed_centre_r - SEED / 2.0, -SEED / 2.0, -SEED / 2.0), SEED)
    # the FEATURE tag is not the BODY tag; the pre-existing-body comparison below
    # works on body tags, so capture the body's
    seed_body_tag = int(list(part.Bodies)[0].Tag)
    pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        pb.FeatureList.SetArray([seed])
        pb.PatternMethod = NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
        pb.OutputOption = NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
        pd = pb.PatternService
        GU = NXOpen.GeometricUtilities
        pd.PatternType = GU.PatternDefinition.PatternEnum.Polygon
        pg = pd.PolygonDefinition
        pg.RotationAxis = axis
        # NumberOfSides is an Expression: the int assignment must raise, otherwise
        # a later NX build changed the type contract
        try:
            pg.NumberOfSides.RightHandSide = sides
            raise RuntimeError("NumberOfSides accepted an int; it is an Expression "
                               "and wants a str")
        except RuntimeError:
            raise
        except Exception as exc:
            if "Unicode str" not in str(exc) and "str" not in str(exc):
                raise RuntimeError("NumberOfSides rejected an int with %s: %s"
                                   % (type(exc).__name__, exc))
        pg.NumberOfSides.RightHandSide = "%d" % sides
        pg.PolygonSizeOption = GU.PolygonPattern.SizeOptions.Inscribed
        pg.PolygonSpacing.SpaceType = \
            GU.PatternSpacingSpacingType.PolygonCountPerSide
        pg.PolygonSpacing.NCopies.RightHandSide = "%d" % ncopies
        if expect_refusal:
            try:
                pb.CommitFeature()
                raise RuntimeError("%s: NCopies=%d was accepted, but ncopies-1 = 0 "
                                   "instances per side cannot be laid out"
                                   % (label, ncopies))
            except RuntimeError:
                raise
            except Exception as exc:
                say("POLYGON_%s_REFUSED %s: %s" % (label.upper(),
                                                   type(exc).__name__, exc))
                return None
        before = set(int(b.Tag) for b in part.Bodies)
        pb.CommitFeature()
    finally:
        pb.Destroy()
    rows = layout(part)
    want = polygon_points(sides, ncopies, seed_centre_r)
    if len(rows) != len(want):
        raise RuntimeError("%s: the pattern produced %d instance(s), the analytic "
                           "layout of %d sides x %d per side gives %d"
                           % (label, len(rows), sides, ncopies - 1, len(want)))
    got = sorted(((r * math.cos(math.radians(a)), r * math.sin(math.radians(a)))
                  for r, a, _z in rows),
                 key=lambda p: math.atan2(p[1], p[0]))
    worst = 0.0
    for (gx, gy), (wx, wy) in zip(got, want):
        worst = max(worst, math.hypot(gx - wx, gy - wy))
    if worst > POS_TOL:
        raise RuntimeError("%s: an instance is %.4f mm away from the analytic "
                           "layout of radius %.4f (want %s, measured %s)"
                           % (label, worst, seed_centre_r,
                              [(round(x, 4), round(y, 4)) for x, y in want],
                              [(round(x, 4), round(y, 4)) for x, y in got]))
    all_bodies = list(part.Bodies)
    kept = [b for b in all_bodies if int(b.Tag) in before]
    if len(kept) != 1 or int(kept[0].Tag) != seed_body_tag:
        raise RuntimeError("%s: the pre-existing seed body is not part of the "
                           "pattern result (kept tags %s)"
                           % (label, [int(b.Tag) for b in kept]))
    seed_c = centroids(part, kept)[0]
    if abs(seed_c[2]) > POS_TOL or abs(seed_c[1] - seed_centre_r) > POS_TOL:
        raise RuntimeError("%s: the seed body sits at (%.4f,%.4f,%.4f); the instance "
                           "at 0 degrees is the seed itself, so it stays on the +x "
                           "axis at r=%.4f"
                           % (label, seed_c[1], seed_c[2], seed_c[3], seed_centre_r))
    say("POLYGON_%s sides=%d copies=%d per_side=%d bodies=%d worst_dev=%.2e "
        "seed_kept=(%.4f,%.4f,%.4f) radii=%s"
        % (label.upper(), sides, ncopies, ncopies - 1, len(rows), worst,
           seed_c[1], seed_c[2], seed_c[3],
           sorted(set(round(r, 4) for r, _a, _z in rows))))
    return worst


def reference_case(session, ufs, label, part_name, base_instance=None):
    """A linear pattern at REF_PITCH/REF_COPIES, then a reference pattern that
    copies its layout onto a second seed REF_SEED_Y away in y."""
    part = new_part(session, ufs, part_name)
    seed_a = block(part, (-SEED / 2.0, -SEED / 2.0, -SEED / 2.0), SEED)
    refpat = linear_pattern(part, seed_a, REF_PITCH, REF_COPIES)
    want_a = sorted((i * REF_PITCH, 0.0, 0.0) for i in range(REF_COPIES))
    got_a = sorted((round(c[1], 4), round(c[2], 4), round(c[3], 4))
                   for c in centroids(part, list(part.Bodies)))
    if got_a != want_a:
        raise RuntimeError("%s: the linear pattern being referenced is at %s, expected %s"
                           % (label, got_a, want_a))
    before_b = set(int(b.Tag) for b in part.Bodies)
    seed_b = block(part, (-SEED / 2.0, REF_SEED_Y - SEED / 2.0, -SEED / 2.0), SEED)
    b_tags = [int(b.Tag) for b in part.Bodies if int(b.Tag) not in before_b]
    if len(b_tags) != 1:
        raise RuntimeError("%s: the second seed produced %d bodies" % (label, len(b_tags)))
    seed_b_body = b_tags[0]
    pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        pb.FeatureList.SetArray([seed_b])
        pb.PatternMethod = \
            NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
        pb.OutputOption = \
            NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
        pd = pb.PatternService
        pd.PatternType = NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Reference
        rd = pd.ReferenceDefinition
        rd.ReferencedPattern.SetValue(refpat, NXOpen.View.Null,
                                      NXOpen.Point3d(0.0, 0.0, 0.0))
        # the selection is the only way in: ReferencedPattern itself refuses
        # assignment ("not writable"), so read it back to prove the SetValue took
        picked = rd.ReferencedPattern.GetValue()[0]
        if picked is None or int(picked.Tag) != int(refpat.Tag):
            raise RuntimeError("%s: the referenced-pattern selection came back as %r, not the "
                               "linear pattern feature %d"
                               % (label, picked, int(refpat.Tag)))
        if base_instance is not None:
            rd.SetBaseInstance(base_instance[0], base_instance[1])
        pb.CommitFeature()
    finally:
        pb.Destroy()
    every = positions(part)
    if len(every) != 2 * REF_COPIES:
        raise RuntimeError("%s: the part holds %d bodies after the reference pattern, expected "
                           "%d" % (label, len(every), 2 * REF_COPIES))
    # the reference pattern lays the whole family out around the seed: the seed
    # body keeps its own position and stands in for the base instance, so the
    # commit adds REF_COPIES-1 bodies, not REF_COPIES
    family = [r for r in every if abs(r[2] - REF_SEED_Y) < POS_TOL]
    if len(family) != REF_COPIES:
        raise RuntimeError("%s: the referenced layout holds %d bodies at y=%.4f, expected %d "
                           "(the seed plus %d copies)"
                           % (label, len(family), REF_SEED_Y, REF_COPIES, REF_COPIES - 1))
    if seed_b_body not in [r[0] for r in family]:
        raise RuntimeError("%s: the seed body %d did not survive the reference pattern"
                           % (label, seed_b_body))
    offsets = sorted(round(r[1], 4) for r in family)
    if base_instance is None:
        want = sorted(i * REF_PITCH for i in range(REF_COPIES))
        why = "with the default base instance the seed stands in for instance 0 of the "\
              "referenced pattern, so the family repeats its offsets"
    else:
        want = sorted((i - base_instance[0]) * REF_PITCH for i in range(REF_COPIES))
        why = "base instance %s maps referenced instance %d onto the seed, so the whole "\
              "family shifts by -%g" % (base_instance, base_instance[0],
                                        base_instance[0] * REF_PITCH)
    if any(abs(g - w) > POS_TOL for g, w in zip(offsets, want)):
        raise RuntimeError("%s: the family sits at x=%s, expected %s (%s)"
                           % (label, offsets, want, why))
    for r in family:
        if abs(r[3]) > POS_TOL:
            raise RuntimeError("%s: body %d sits at (%.4f,%.4f,%.4f); the reference pattern "
                               "keeps the seed's own y=%.4f and z=0"
                               % (label, r[0], r[1], r[2], r[3], REF_SEED_Y))
    say("REFERENCE_%s bodies=%d family_x=%s y=%.4f" %
        (label.upper(), len(every), offsets, REF_SEED_Y))
    return offsets


def main():
    session = NXOpen.Session.GetSession()
    ufs = NXOpen.UF.UFSession.GetUFSession()

    def s0_enums():
        got = sorted(n for n in dir(NXOpen.GeometricUtilities.PatternDefinition
                                    .PatternEnum)
                     if not n.startswith("_") and n != "ValueOf")
        if got != sorted(POLYGON_ENUMS):
            raise RuntimeError("PatternEnum members are %s, expected %s"
                               % (got, sorted(POLYGON_ENUMS)))
        say("PATTERN_ENUMS=%s" % got)

    def s1_polygon_hex():
        polygon_case(session, ufs, "hex", PART_POLY_HEX, 6, SEED_CENTRE_R, 2)

    def s2_polygon_square():
        # the control: NumberOfSides drives the count and the angle step, so a
        # hard coded six would show up here
        polygon_case(session, ufs, "square", PART_POLY_SQUARE, 4, SEED_CENTRE_R, 2)

    def s3_polygon_copies_per_side():
        # NCopies=4 -> three instances on every side, 18 bodies. The analytic model
        # puts each side's interior pair at unequal angles (19.1066 and 21.7868),
        # so this stage fails if NX spaced them at equal angles instead
        polygon_case(session, ufs, "hex_c4", PART_POLY_HEX_C4, 6, SEED_CENTRE_R, 4)

    def s4_polygon_radius_follows_seed():
        # the same hexagon with the seed closer to the axis: the analytic layout is
        # built from the seed's own distance, so a hard coded 17.5 radius would show
        # up as 18 bodies landing 5 mm off
        polygon_case(session, ufs, "hex_far", PART_POLY_HEX_FAR, 6,
                     SEED_CENTRE_R_FAR, 2)

    def s5_polygon_copies_one_refused():
        polygon_case(session, ufs, "hex_c1", PART_POLY_HEX_C1, 6, SEED_CENTRE_R, 1,
                     expect_refusal=True)

    def s6_general_points():
        part = new_part(session, ufs, PART_GENERAL)
        GU = NXOpen.GeometricUtilities
        GP = GU.GeneralPattern
        seed = block(part, (FROM_POINT[0] - SEED / 2.0, FROM_POINT[1] - SEED / 2.0,
                            FROM_POINT[2] - SEED / 2.0), SEED)
        # 同 polygon_case：拿体标签，不拿特征标签
        seed_body_tag = int(list(part.Bodies)[0].Tag)
        pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            pb.FeatureList.SetArray([seed])
            pb.PatternMethod = \
                NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
            pb.OutputOption = \
                NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
            pd = pb.PatternService
            pd.PatternType = GU.PatternDefinition.PatternEnum.General
            gd = pd.GeneralDefinition
            gd.FromLocationType = GP.FromLocationOptions.Point
            gd.FromLocationPoint = part.Points.CreatePoint(NXOpen.Point3d(*FROM_POINT))
            targets = [part.Points.CreatePoint(NXOpen.Point3d(*p)) for p in TO_POINTS]
            rule = part.ScRuleFactory.CreateRuleCurveDumbFromPoints(targets)
            gd.ToPoints.AddToSection([rule], targets[0], NXOpen.NXObject.Null,
                                     NXOpen.NXObject.Null,
                                     NXOpen.Point3d(0.0, 0.0, 0.0),
                                     NXOpen.Section.Mode.Create, False)
            data = gd.ToPoints.GetSectionData()
            if not data:
                raise RuntimeError("ToPoints holds no section data after "
                                   "AddToSection")
            before = set(int(b.Tag) for b in part.Bodies)
            pb.CommitFeature()
        finally:
            pb.Destroy()
        new = [b for b in part.Bodies if int(b.Tag) not in before]
        got = sorted((c[1], c[2], c[3]) for c in centroids(part, new))
        want = sorted(TO_POINTS)
        if len(got) != len(want):
            raise RuntimeError("the general pattern made %d instance(s), expected "
                               "%d" % (len(got), len(want)))
        worst = 0.0
        for g, w in zip(got, want):
            worst = max(worst, max(abs(g[i] - w[i]) for i in range(3)))
        if worst > GENERAL_TOL:
            raise RuntimeError("an instance is %.6f mm away from its target point"
                               % worst)
        kept = [b for b in part.Bodies if int(b.Tag) in before]
        if len(kept) != 1 or int(kept[0].Tag) != seed_body_tag:
            raise RuntimeError("the seed body did not survive the pattern (kept "
                               "tags %s, seed body %d)"
                               % ([int(b.Tag) for b in kept], seed_body_tag))
        seed_c = centroids(part, kept)[0]
        if max(abs(seed_c[1] - FROM_POINT[0]), abs(seed_c[2] - FROM_POINT[1]),
               abs(seed_c[3] - FROM_POINT[2])) > POS_TOL:
            raise RuntimeError("the seed moved to (%.4f,%.4f,%.4f); the from "
                               "location mapping sends copies to the targets and "
                               "leaves the seed alone" % seed_c[1:])
        say("GENERAL instances=%d worst_dev=%.2e section_data=%d seed=(%.4f,%.4f,"
            "%.4f)" % (len(got), worst, len(data), seed_c[1], seed_c[2], seed_c[3]))

    def s7_general_without_to_points():
        # negative control: an empty ToPoints section cannot commit
        part = new_part(session, ufs, PART_GENERAL_EMPTY)
        GU = NXOpen.GeometricUtilities
        GP = GU.GeneralPattern
        seed = block(part, (0.0, 0.0, 0.0), SEED)
        pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            pb.FeatureList.SetArray([seed])
            pb.PatternMethod = \
                NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
            pb.OutputOption = \
                NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
            pd = pb.PatternService
            pd.PatternType = GU.PatternDefinition.PatternEnum.General
            gd = pd.GeneralDefinition
            gd.FromLocationType = GP.FromLocationOptions.Point
            gd.FromLocationPoint = part.Points.CreatePoint(NXOpen.Point3d(0.0, 0.0, 0.0))
            try:
                pb.CommitFeature()
                raise RuntimeError("a general pattern with an empty ToPoints "
                                   "section committed; ToPoints is what places the "
                                   "instances and the measured refusal is gone")
            except RuntimeError:
                raise
            except Exception as exc:
                say("GENERAL_EMPTY_REFUSED %s: %s" % (type(exc).__name__,
                                                      str(exc)[:90]))
        finally:
            pb.Destroy()

    def s8_reference_layout():
        reference_case(session, ufs, "layout", PART_REFERENCE)

    def s9_reference_base_instance():
        # SetBaseInstance(1, 0) moves the base to referenced instance 1, which
        # shifts the whole layout by one pitch; a recipe that ignored it would
        # repeat the offsets of stage 8 instead
        got = reference_case(session, ufs, "base1", PART_REFERENCE_BASE,
                             base_instance=(1, 0))
        want = sorted((i - 1) * REF_PITCH for i in range(REF_COPIES))
        if any(abs(g - w) > POS_TOL for g, w in zip(got, want)):
            raise RuntimeError("base instance 1,0 gave %s, expected %s" % (got, want))

    def s10_mirror_refused():
        # NX 12 refuses to commit a Mirror pattern (see the header): the plane
        # input is proven good by MirrorDefinition.Validate() returning True and
        # by the selection reading back, and the refusal then comes from the
        # builder. If a later NX build starts committing it, this stage fails and
        # the recorded boundary has to be revisited.
        GU = NXOpen.GeometricUtilities
        part = new_part(session, ufs, PART_MIRROR)
        seed = block(part, (SPIRAL_R - SEED / 2.0, -SEED / 2.0, -SEED / 2.0), SEED)
        datum = datum_plane_x(part, 0.0)
        pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            pb.FeatureList.SetArray([seed])
            pb.PatternMethod = \
                NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
            pb.OutputOption = \
                NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
            pd = pb.PatternService
            pd.PatternType = GU.PatternDefinition.PatternEnum.Mirror
            md = pd.MirrorDefinition
            md.PlaneOption = GU.MirrorPattern.PlaneOptions.Existing
            md.ExistingPlane.SetValue(datum.DatumPlane, NXOpen.View.Null,
                                      NXOpen.Point3d(0.0, 0.0, 0.0))
            picked = md.ExistingPlane.GetValue()[0]
            if picked is None or int(picked.Tag) != int(datum.DatumPlane.Tag):
                raise RuntimeError("the mirror plane selection came back as %r, not datum "
                                   "plane %d" % (picked, int(datum.DatumPlane.Tag)))
            if not md.Validate():
                raise RuntimeError("MirrorDefinition.Validate() is False, so this stage no "
                                   "longer isolates the builder-level refusal")
            try:
                pb.CommitFeature()
                raise RuntimeError("the Mirror pattern committed; NX 12 refused it when this "
                                   "test was written, so the recorded boundary is gone")
            except RuntimeError:
                raise
            except Exception as exc:
                if MIRROR_REFUSAL not in str(exc):
                    raise RuntimeError("the Mirror pattern was refused with %s: %s, not with "
                                       "the recorded %r"
                                       % (type(exc).__name__, str(exc)[:120],
                                          MIRROR_REFUSAL))
                say("MIRROR_REFUSED %s: %s" % (type(exc).__name__, str(exc)[:80]))
        finally:
            pb.Destroy()
        left = len(list(part.Bodies))
        if left != 1:
            raise RuntimeError("the refused mirror left %d bodies behind, expected just the "
                               "seed" % left)
        say("MIRROR_BODIES_AFTER_REFUSAL=%d" % left)

    def spiral_case(part_name, with_href, expect_refusal):
        GU = NXOpen.GeometricUtilities
        part = new_part(session, ufs, part_name)
        seed = block(part, (SPIRAL_R - SEED / 2.0, -SEED / 2.0, -SEED / 2.0), SEED)
        pb = part.Features.CreatePatternFeatureBuilder(NXOpen.Features.Feature.Null)
        try:
            pb.FeatureList.SetArray([seed])
            pb.PatternMethod = \
                NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
            pb.OutputOption = \
                NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
            pd = pb.PatternService
            pd.PatternType = GU.PatternDefinition.PatternEnum.Spiral
            sd = pd.SpiralDefinition
            sd.SizeSpiralType = GU.SpiralPattern.SpiralDefineSize.NumberOfTurns
            sd.NumberOfTurns.RightHandSide = "%d" % SPIRAL_TURNS
            sd.RadialPitch.RightHandSide = "%d" % SPIRAL_RADIAL_PITCH
            sd.PitchAlongSpiral.SpaceType = GU.PatternSpacing.SpacingType.Pitch
            sd.PitchAlongSpiral.OnPathPitchDistance.Expression.RightHandSide = \
                "%d" % SPIRAL_ALONG_PITCH
            sd.SpiralNormal = part.Directions.CreateDirection(
                NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
                NXOpen.SmartObject.UpdateOption.WithinModeling)
            if with_href:
                # HorizontalRefVector is the working form; HorizontalRefObject is a
                # selection and leaving it empty is what stage 12 reproduces
                sd.HorizontalRef.HorizontalRefVector = \
                    part.Directions.CreateDirection(
                        NXOpen.Point3d(0.0, 0.0, 0.0),
                        NXOpen.Vector3d(1.0, 0.0, 0.0),
                        NXOpen.SmartObject.UpdateOption.WithinModeling)
            if expect_refusal:
                try:
                    pb.CommitFeature()
                    raise RuntimeError("a spiral with no horizontal reference committed; the "
                                       "measured refusal %r is gone" % NO_HREF_REFUSAL)
                except RuntimeError:
                    raise
                except Exception as exc:
                    if NO_HREF_REFUSAL not in str(exc):
                        raise RuntimeError("the spiral with no horizontal reference was "
                                           "refused with %s: %s"
                                           % (type(exc).__name__, str(exc)[:120]))
                    say("SPIRAL_NOHREF_REFUSED %s: %s" % (type(exc).__name__,
                                                          str(exc)[:80]))
                    return None
            pb.CommitFeature()
        finally:
            pb.Destroy()
        rows = layout(part)
        if len(rows) != 2:
            raise RuntimeError("the spiral pattern made %d bodies; the measured baseline is "
                               "the seed plus one instance" % len(rows))
        for _r, _a, z in rows:
            if abs(z) > POS_TOL:
                raise RuntimeError("a spiral instance sits at z=%.4f; SpiralNormal is +z, so "
                                   "the layout is planar" % z)
        r0, a0, _z0 = rows[0]
        r1, a1, _z1 = rows[1]
        if abs(r0 - SPIRAL_R) > POS_TOL or a0 > SPIRAL_ANGLE_TOL:
            raise RuntimeError("the first instance is at (r=%.4f, angle=%.4f); the seed is "
                               "the instance at r=%.4f and 0 deg"
                               % (r0, a0, SPIRAL_R))
        if abs(r1 - SPIRAL_INSTANCE_R) > SPIRAL_R_TOL or \
                abs(a1 - SPIRAL_INSTANCE_ANGLE) > SPIRAL_ANGLE_TOL:
            raise RuntimeError("the second instance is at (r=%.4f, angle=%.4f deg); two runs "
                               "measured (%.4f, %.4f)" % (r1, a1, SPIRAL_INSTANCE_R,
                                                          SPIRAL_INSTANCE_ANGLE))
        say("SPIRAL_R=%.4f SPIRAL_ANGLE=%.4f" % (r1, a1))
        return r1, a1

    def s11_spiral_instances():
        spiral_case(PART_SPIRAL, True, False)

    def s12_spiral_without_href():
        spiral_case(PART_SPIRAL_NOHREF, False, True)

    stage("pattern_enums", s0_enums)
    stage("polygon_hexagon", s1_polygon_hex)
    stage("polygon_square", s2_polygon_square)
    stage("polygon_copies_per_side", s3_polygon_copies_per_side)
    stage("polygon_radius_follows_seed", s4_polygon_radius_follows_seed)
    stage("polygon_copies_one_refused", s5_polygon_copies_one_refused)
    stage("general_to_points", s6_general_points)
    stage("general_empty_to_points", s7_general_without_to_points)
    stage("reference_layout", s8_reference_layout)
    stage("reference_base_instance", s9_reference_base_instance)
    stage("mirror_refused", s10_mirror_refused)
    stage("spiral_instances", s11_spiral_instances)
    stage("spiral_without_horizontal_ref", s12_spiral_without_href)

    if FAILED_STAGES:
        say("TEST32_FAIL stages=" + ",".join(FAILED_STAGES))
        return
    say("TEST32_DONE hex_r=%.4f hex_far_r=%.4f general_tol=%.0e layout_tol=%.0e ref_pitch=%g "
        "spiral_r=%.4f" % (SEED_CENTRE_R, SEED_CENTRE_R_FAR, GENERAL_TOL, POS_TOL,
                           REF_PITCH, SPIRAL_INSTANCE_R))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say(traceback.format_exc()[-600:])
        say("TEST32_FAIL uncaught")
