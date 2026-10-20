# -*- coding: utf-8 -*-
"""Text-layer check of the PDF exported by 19_drafting_annotation.py.

NX's embedded Python (3.6.1) has no PDF reader, so the value level check of the
drafting annotations lives here and runs on the host interpreter. It answers the
question the journal itself cannot: did the two hole-pitch dimensions render the
real model values (70 / 40) instead of a silently mis-associated distance, and
did the note and leader label make it into the plot at all?

Usage:
    python verify_anno_pdf.py <pdf> [--dump]

--dump prints every text token, which is how the EXPECT list below was derived.

Token layer limitations (NX 12 PDF export, measured):
  - CJK text has no ToUnicode mapping, so Chinese requirements/table text is
    invisible here (drafting-annotation.md section 10).
  - The diameter glyph Ø is dropped the same way: the "4x<O>8" label renders
    visually but its text-layer token is just "8". Diameter values therefore
    cannot be checked in the text layer; verify them on a rendered image.
Exit code 0 = all expected tokens found, 1 = missing, 3 = no pymupdf here.
"""
import sys

try:
    import pymupdf as fitz
except ImportError:  # older wheels expose only the deprecated alias
    try:
        import fitz
    except ImportError:
        print("SKIP: no pymupdf in this interpreter")
        raise SystemExit(3)

# 70 / 40 = the hole pattern pitch in x / y, from 01_bracket.py (independent of
# whatever the dimension association resolved to); "R2." and "4x" are the ASCII
# remainders of the technical-requirement note and of the leader label.
EXPECT = ["70", "40", "R2.", "4x"]


def main():
    if len(sys.argv) < 2:
        print("usage: verify_anno_pdf.py <pdf> [--dump]")
        return 2
    path = sys.argv[1]
    doc = fitz.open(path)
    tokens = []
    for page in doc:
        tokens.extend(w[4] for w in page.get_text("words"))
    print("PDF pages=%d tokens=%d" % (doc.page_count, len(tokens)))
    if "--dump" in sys.argv:
        print("TOKENS: " + " ".join(tokens))
        return 0
    missing = [t for t in EXPECT if t not in tokens]
    if missing:
        print("VERIFY_FAIL missing " + ",".join(missing))
        print("TOKENS: " + " ".join(tokens))
        return 1
    print("VERIFY_PASS " + " ".join(EXPECT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
