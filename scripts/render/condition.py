# -*- coding: utf-8 -*-
"""Condition README figures: trim white borders, cap the pixel size, save.

Drawings come out of NX as A3 sheets with wide white margins, and the offline
renders carry a 7% margin; both waste README width, so every figure is trimmed
to its non-white bounding box and then capped.

If a render-time sidecar (<src>.scalebar.json, written by render_stl.py) is
present, a scale bar is drawn AFTER the trim into a white strip added below the
figure: drawing it at render time would pin the ink bounding box to the render
corner and defeat the trim.

usage: condition.py <in.png> <out.png> [max_w] [max_h] [pad]
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

src, dst = sys.argv[1], sys.argv[2]
maxw = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
maxh = int(sys.argv[4]) if len(sys.argv) > 4 else 1100
pad = int(sys.argv[5]) if len(sys.argv) > 5 else 14

im = Image.open(src).convert("RGB")
a = np.asarray(im)
ink = (a < 244).any(axis=2)
rows, cols = np.where(ink)
if len(rows) == 0:
    raise SystemExit("no ink found in %s" % src)
y0, y1 = max(rows.min() - pad, 0), min(rows.max() + 1 + pad, a.shape[0])
x0, x1 = max(cols.min() - pad, 0), min(cols.max() + 1 + pad, a.shape[1])
im = im.crop((x0, y0, x1, y1))
w, h = im.size
scale = min(maxw / float(w), maxh / float(h), 1.0)
if scale < 1.0:
    im = im.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                   Image.LANCZOS)

side = src + ".scalebar.json"
if os.path.exists(side):
    with open(side, encoding="utf-8") as f:
        sb = json.load(f)
    # px/mm after crop+resize, relative to the render canvas width
    ppm = sb["px_per_mm"] * (im.size[0] / float(a.shape[1]))
    bar_px = sb["length_mm"] * ppm
    strip = 40
    need_w = int(round(bar_px)) + 56
    canvas = Image.new("RGB", (max(im.size[0], need_w), im.size[1] + strip),
                       (255, 255, 255))
    canvas.paste(im, (0, 0))
    dr = ImageDraw.Draw(canvas)
    dark = (44, 56, 70)
    x1b = canvas.size[0] - 28
    y1b = canvas.size[1] - 16
    x0b = x1b - bar_px
    dr.line([x0b, y1b, x1b, y1b], fill=dark, width=3)
    for x in (x0b, x1b):
        dr.line([x, y1b - 7, x, y1b + 7], fill=dark, width=3)
    dr.text((x0b + 6, y1b - 24), sb["label"], fill=dark)
    im = canvas

im.save(dst, optimize=True)
print("%-34s -> %-30s %dx%d  %d bytes" %
      (src.split("/")[-1], dst.split("/")[-1], im.size[0], im.size[1],
       len(open(dst, "rb").read())))
