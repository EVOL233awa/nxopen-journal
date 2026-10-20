# -*- coding: utf-8 -*-
"""Render binary STL geometry to shaded PNG with feature edges (host side).

The NX 12 batch session cannot export an image (measured: the UF
route raises a memory access violation, the Gateway builder commits and writes
no file), so the README solid-model figures are rendered on the host from the
STL the same parts export.  Z-buffer, flat shading, feature edges by dihedral
angle, so the result looks like a NX shaded-with-edges view.

usage:
  render_stl.py <in.stl> <out.png> [w] [h] [--az A] [--el E] [--scalebar MM TEXT]
  render_stl.py <scene.json>          # multi-part scene, see SCENE_KEYS below

scene.json:
  {"out": "...png", "w": 1400, "h": 1000, "az": 38, "el": 27,
   "scalebar": [10, "10 mm"],          # optional, model units are mm
   "parts": [{"stl": "...stl", "translate": [0,0,0],
              "rotate_z": 0, "color": [0.66, 0.71, 0.78]}, ...]}
"""
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

DEFAULT_COLOR = (0.66, 0.71, 0.78)


def read_stl(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:5].lower().startswith(b"solid") and b"facet" in data[:2048].lower():
        verts, faces = [], []
        tri = []
        for ln in data.decode("ascii", "replace").splitlines():
            s = ln.strip().lower()
            if s.startswith("vertex"):
                p = s.split()
                tri.append([float(p[1]), float(p[2]), float(p[3])])
                if len(tri) == 3:
                    verts.extend(tri)
                    faces.append([len(verts) - 3, len(verts) - 2, len(verts) - 1])
                    tri = []
        return np.array(verts, float), np.array(faces, int)
    n = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + 50 * n], dtype=np.uint8).reshape(n, 50)
    tri = rec[:, 12:48].copy().view("<f4").reshape(n, 3, 3).astype(float)
    return tri.reshape(-1, 3), np.arange(n * 3).reshape(n, 3)


def weld(verts, ndigits=4):
    key = np.round(verts, ndigits)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    return uniq, inv.reshape(-1)


def feature_edges(uniq, faces, cos_limit=math.cos(math.radians(25.0))):
    """Edges whose two adjacent faces differ by more than 25 degrees."""
    n = np.cross(uniq[faces[:, 1]] - uniq[faces[:, 0]],
                 uniq[faces[:, 2]] - uniq[faces[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    n = n / ln[:, None]
    pairs = {}
    for fi, f in enumerate(faces):
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            k = (a, b) if a < b else (b, a)
            pairs.setdefault(k, []).append(fi)
    out = []
    for k, fl in pairs.items():
        if len(fl) == 1:
            out.append(k)
        elif float(np.dot(n[fl[0]], n[fl[1]])) < cos_limit:
            out.append(k)
    return out


def body_groups(faces):
    """Split triangles into connected solids (shared vertices weld them)."""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for f in faces:
        for v in f:
            parent.setdefault(v, v)
        for a, b in ((f[0], f[1]), (f[1], f[2])):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    roots, out = {}, np.zeros(len(faces), int)
    for i, f in enumerate(faces):
        r = find(f[0])
        if r not in roots:
            roots[r] = len(roots)
        out[i] = roots[r]
    return out, len(roots)


def load_scene(spec):
    """Return (verts, faces, face_color_index, colors, color_alpha), merged."""
    verts, faces, fcol = [], [], []
    colors = []
    calpha = []
    for part in spec["parts"]:
        pa = float(part.get("alpha", 1.0))
        v, f = read_stl(part["stl"])
        v, inv = weld(v)          # weld per part so body_split sees shared verts
        f = inv[f]
        rz = math.radians(float(part.get("rotate_z", 0.0)))
        if rz:
            c, s = math.cos(rz), math.sin(rz)
            v = v.dot(np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]))
        t = np.array(part.get("translate", [0.0, 0.0, 0.0]), float)
        v = v + t[None, :]
        base = len(verts)
        verts.extend(v)
        faces.append(f + base)
        if part.get("split_bodies"):
            grp, ngrp = body_groups(f)
            pal = [tuple(c) for c in part.get("palette",
                                               spec.get("palette", [DEFAULT_COLOR]))]
            idx = [len(colors) + (g % len(pal)) for g in range(ngrp)]
            colors.extend(pal[i % len(pal)] for i in range(ngrp))
            palpha = part.get("body_alphas")
            calpha.extend([float(palpha[g]) if palpha else pa
                           for g in range(ngrp)])
            fcol.append(np.array([idx[g] for g in grp], int))
            print("  part %-28s tris=%d  solids=%d"
                  % (os.path.basename(part["stl"]), len(f), ngrp))
        else:
            ci = len(colors)
            colors.append(tuple(part.get("color", DEFAULT_COLOR)))
            calpha.append(pa)
            fcol.append(np.full(len(f), ci, int))
            print("  part %-28s tris=%d  translate=%s"
                  % (os.path.basename(part["stl"]), len(f), list(t)))
    return (np.array(verts, float), np.concatenate(faces),
            np.concatenate(fcol), colors, calpha)


def render(spec, dst):
    W, H = int(spec.get("w", 1400)), int(spec.get("h", 1000))
    az, el = float(spec.get("az", 38.0)), float(spec.get("el", 27.0))
    verts, faces, fcol, colors, calpha = load_scene(spec)
    uniq, idx = weld(verts)
    faces = idx[faces]
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & \
           (faces[:, 2] != faces[:, 0])
    faces, fcol = faces[keep], fcol[keep]
    print("  merged triangles=%d  welded verts=%d" % (len(faces), len(uniq)))

    a, e = math.radians(az), math.radians(el)
    rz = np.array([[math.cos(a), -math.sin(a), 0.0],
                   [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(e), -math.sin(e)],
                   [0.0, math.sin(e), math.cos(e)]])
    M = rx.dot(rz)
    p = uniq.dot(M.T)
    # Depth = -z, i.e. the camera sits on the +z side of the model.  A part is
    # built sitting on z = 0, so viewing from -z would show its underside and
    # hide anything standing on it (measured on the assembly figure, where the
    # pin was hidden under the plate).  Screen x/y are untouched, so this is a
    # view from the other side, not a mirror.
    p[:, 2] = -p[:, 2]
    xmin, ymin = p[:, 0].min(), p[:, 1].min()
    xmax, ymax = p[:, 0].max(), p[:, 1].max()
    span = max(xmax - xmin, ymax - ymin)
    margin = 0.07
    scale = (1.0 - 2 * margin) * min(W, H) / span

    def to_px(pts):
        px = (pts[:, 0] - (xmin + xmax) / 2.0) * scale + W / 2.0
        py = H / 2.0 - (pts[:, 1] - (ymin + ymax) / 2.0) * scale
        return np.stack([px, py, pts[:, 2] * scale], axis=1)

    pv = to_px(p)

    fn = np.cross(p[faces[:, 1]] - p[faces[:, 0]], p[faces[:, 2]] - p[faces[:, 0]])
    ln = np.linalg.norm(fn, axis=1)
    ln[ln == 0] = 1.0
    fn = fn / ln[:, None]
    fn = fn * np.where(fn[:, 2] > 0, -1.0, 1.0)[:, None]

    # The camera looks along +z (the z-buffer keeps the smaller z), so the
    # visible faces carry -z normals; the light has to live in that same
    # hemisphere or every face clips to the ambient term and the model renders
    # almost black.  It is mostly a headlight with a slight up-left offset: a
    # steeper screen-space light (up = +y) leaves a floor-like face - whose
    # screen normal points down - in shadow, which is why the first version came
    # out dark even after the hemisphere was fixed.
    light = np.array([-0.28, 0.18, -0.94])
    light = light / np.linalg.norm(light)
    lam = np.clip(fn.dot(light), 0.0, 1.0)
    shade = 0.30 + 0.70 * lam
    base = np.array(colors)[fcol]
    col = np.clip(base * shade[:, None], 0, 1)

    zbuf = np.full((H, W), np.inf)
    img = np.ones((H, W, 3))
    tri_px = pv[faces]
    # Two coplanar faces (the top of one solid lying in the top of another) come
    # out of the barycentric interpolation a hair apart pixel by pixel, which
    # paints the shared region as speckle.  Snapping the depth to 1e-4 of the
    # model span makes exact ties tie again, and the stable sort below decides
    # them the same way everywhere.
    snap = 1e-4 * max(1.0, span * scale)

    def raster(order, blend=None):
        """Draw triangles in the given order.  blend=None is opaque (the depth
        buffer decides); otherwise the face colour is mixed over what is already
        there with that alpha and the depth buffer is left alone, which is what
        makes an overlapping pair readable: the translucent solid shows the one
        behind it through the shared region instead of z-fighting with it."""
        for fi in order:
            t = tri_px[fi]
            x0 = max(int(np.floor(t[:, 0].min())), 0)
            x1 = min(int(np.ceil(t[:, 0].max())) + 1, W)
            y0 = max(int(np.floor(t[:, 1].min())), 0)
            y1 = min(int(np.ceil(t[:, 1].max())) + 1, H)
            if x1 <= x0 or y1 <= y0:
                continue
            xs = np.arange(x0, x1) + 0.5
            ys = np.arange(y0, y1) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            ax, ay = t[0, 0], t[0, 1]
            bx, by = t[1, 0], t[1, 1]
            cx, cy = t[2, 0], t[2, 1]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-12:
                continue
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * t[0, 2] + w1 * t[1, 2] + w2 * t[2, 2]
            z = np.round(z / snap) * snap
            sub = zbuf[y0:y1, x0:x1]
            if blend is None:
                hit = inside & (z < sub)
                if not hit.any():
                    continue
                sub[hit] = z[hit]
                img[y0:y1, x0:x1][hit] = col[fi]
            else:
                # a coincident surface still counts as "in front" here, so the
                # shared region gets blended rather than left to the tie-break
                hit = inside & (z <= sub + snap)
                if not hit.any():
                    continue
                tile = img[y0:y1, x0:x1]
                tile[hit] = tile[hit] * (1.0 - blend) + col[fi] * blend

    # alpha is per colour entry, so a split multi-solid part can blend as one
    # while a two-part scene keeps the solid one opaque
    face_alpha = np.array(calpha)[fcol]
    opaque = np.where(face_alpha >= 1.0 - 1e-9)[0]
    clear = np.where(face_alpha < 1.0 - 1e-9)[0]
    raster(opaque[np.argsort(-tri_px[opaque][:, :, 2].mean(axis=1),
                             kind="stable")])
    for a_val in sorted(set(face_alpha[clear].round(4)), reverse=True):
        group = clear[np.isclose(face_alpha[clear], a_val)]
        # translucent faces are laid down back to front, so a farther one is
        # already in the buffer when the nearer one blends over it
        raster(group[np.argsort(-tri_px[group][:, :, 2].mean(axis=1),
                                kind="stable")], blend=float(a_val))

    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    dark = (44, 56, 70)
    edges = feature_edges(uniq, faces)
    tol = 1e-6 * max(1.0, span * scale)
    for a_i, b_i in edges:
        pa, pb = pv[a_i], pv[b_i]
        ix, iy = int((pa[0] + pb[0]) / 2.0), int((pa[1] + pb[1]) / 2.0)
        if 0 <= ix < W and 0 <= iy < H:
            if (pa[2] + pb[2]) / 2.0 > zbuf[iy, ix] + tol:
                continue
        dr.line([float(pa[0]), float(pa[1]), float(pb[0]), float(pb[1])],
                fill=dark, width=1)

    sb = spec.get("scalebar")
    if sb:
        # The bar itself is drawn by condition.py AFTER the white-border trim.
        # Drawn here it pins the ink bounding box to this corner, so the trim
        # can no longer remove the empty margin between model and bar (the
        # flange figure came out pinned to the left half of its frame because
        # of exactly this).  The sidecar carries px/mm through the trim.
        sidecar = dst + ".scalebar.json"
        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump({"px_per_mm": scale, "w": W, "h": H,
                       "length_mm": float(sb[0]), "label": str(sb[1])}, f)
        print("  scalebar %s: %g mm = %.2f px/mm -> %s"
              % (str(sb[1]), float(sb[0]), scale, sidecar))

    im.save(dst)
    print("  wrote %s  %dx%d  edges=%d  %.2f px/mm"
          % (dst, W, H, len(edges), scale))
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return 2
    if args[0].lower().endswith(".json"):
        with open(args[0], encoding="utf-8") as f:
            spec = json.load(f)
        print("scene %s" % args[0])
        return render(spec, spec["out"])

    if len(args) < 2:
        print(__doc__)
        return 2
    src, dst = args[0], args[1]
    numeric = [a for a in args[2:] if not a.startswith("--")]
    spec = {"out": dst, "parts": [{"stl": src}]}
    if len(numeric) > 0:
        spec["w"] = int(numeric[0])
    if len(numeric) > 1:
        spec["h"] = int(numeric[1])
    for flag, key in (("--az", "az"), ("--el", "el")):
        if flag in args:
            spec[key] = float(args[args.index(flag) + 1])
    if "--scalebar" in args:
        i = args.index("--scalebar")
        spec["scalebar"] = [float(args[i + 1]), args[i + 2]]
    print("single %s" % src)
    return render(spec, dst)


if __name__ == "__main__":
    sys.exit(main())
