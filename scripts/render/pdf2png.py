# -*- coding: utf-8 -*-
"""Rasterise page 1 of a PDF to PNG (host side, pymupdf).

usage: pdf2png.py <in.pdf> <out.png> [zoom]
"""
import os
import sys

import fitz

src, dst = sys.argv[1], sys.argv[2]
zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 2.6
doc = fitz.open(src)
page = doc[0]
pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
pix.save(dst)
print("pdf2png %s -> %s  %dx%d  %.1f KB  (pages=%d)"
      % (os.path.basename(src), os.path.basename(dst), pix.width, pix.height,
         os.path.getsize(dst) / 1024.0, doc.page_count))
