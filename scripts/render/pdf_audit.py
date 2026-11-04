# -*- coding: utf-8 -*-
"""图纸 PDF 文本层审计。

NX 12 的 PDF 正文多是矢量轮廓：一页往往只有 8–16 个可提取词。因此：

  - 词数低于阈值时只报 NO_SIGNAL，不把"0 重叠"当成版面正确；
  - 标题栏/中文技术要求由 NX 模型侧回读（gb_drawing.title_block 的
    读回断言），PDF 侧只负责页数、页面尺寸、可提取 token 与重叠；
  - 软连字符 U+00AD、零宽字符先归一化再比较。

token 判定与版面判定分开：给了 `expect` 就只对 expect 负责；没给 expect
且词数不足则 NO_SIGNAL。
"""
import os
import re
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from deliverable import FAIL, NO_SIGNAL, PASS  # noqa: E402

_SOFT = re.compile(u"[\u00ad\u200b\u200c\u200d\ufeff]")


def normalize(text):
    return _SOFT.sub("", text).strip()


def _overlaps(words):
    boxes = []
    for w in words:
        x0, y0, x1, y1 = w[:4]
        if x1 > x0 and y1 > y0:
            boxes.append((x0, y0, x1, y1, w[4]))
    pairs = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 0.5 or iy <= 0.5:
                continue
            inter = ix * iy
            amin = min((a[2] - a[0]) * (a[3] - a[1]),
                       (b[2] - b[0]) * (b[3] - b[1]))
            if amin > 0 and inter / amin > 0.30:
                pairs.append((a[4], b[4]))
    return pairs


def audit(path):
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            return {"path": os.path.abspath(path), "available": False,
                    "reason": "pymupdf not installed", "pages": []}
    doc = fitz.open(path)
    pages = []
    for page in doc:
        words = page.get_text("words")
        tokens = [normalize(w[4]) for w in words]
        tokens = [t for t in tokens if t]
        rect = page.rect
        pages.append({
            "width_mm": round(rect.width * 25.4 / 72.0, 2),
            "height_mm": round(rect.height * 25.4 / 72.0, 2),
            "words": len(tokens),
            "tokens": tokens,
            "drawings": len(page.get_drawings()),
            "overlaps": _overlaps(words),
        })
    return {"path": os.path.abspath(path), "available": True,
            "pages": pages, "page_count": len(pages)}


def pdf_gate(path, expect=None, min_words=3):
    """返回 {verdict, codes, notes}；expect 给了就只对出现的 token 负责。"""
    data = audit(path)
    if not data.get("available", True):
        return {"verdict": NO_SIGNAL, "codes": ["DELIV_E_PDF_UNAVAILABLE"],
                "notes": [data.get("reason", "pymupdf missing")]}
    pages = data["pages"]
    if not pages:
        return {"verdict": FAIL, "codes": ["DELIV_E_PDF_EMPTY"],
                "notes": ["no page"]}
    all_tokens = [t for p in pages for t in p["tokens"]]
    codes, notes = [], []
    if expect:
        missing = [t for t in expect if t not in all_tokens]
        if missing:
            codes.append("DELIV_E_PDF_TOKEN")
            notes.append("missing tokens: " + ",".join(missing))
    for i, p in enumerate(pages):
        if p["overlaps"]:
            codes.append("DELIV_E_PDF_OVERLAP")
            notes.append("page %d overlap %r" % (i, p["overlaps"][:3]))
    if codes:
        return {"verdict": FAIL, "codes": codes, "notes": notes}
    if expect:
        return {"verdict": PASS, "codes": [], "notes": []}
    if len(all_tokens) < min_words:
        return {"verdict": NO_SIGNAL, "codes": ["DELIV_E_PDF_NO_TEXT"],
                "notes": ["words=%d < %d (vector text)" %
                          (len(all_tokens), min_words)]}
    return {"verdict": PASS, "codes": [], "notes": []}
