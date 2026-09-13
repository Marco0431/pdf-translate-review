# -*- coding: utf-8 -*-
"""check_crop_fidelity.py — verify that every image embedded in a translation deliverable
faithfully reproduces the region of the source PDF that its slot claims, and that the slot
itself is numbered correctly.

Method
------
1. extract every `data:` image from the HTML body in document order, with its declared
   identity (alt text plus the neighbouring 图 N / 公式 N caption) and a content hash;
2. build candidate regions from the PDF's own structure — one region per equation number
   `(N)` and one per figure caption `Fig. N` — and locate each image by multi-scale
   `cv2.matchTemplate` against those regions. Working region-by-region rather than page-by-page
   makes the search both precise (an equation strip is compared against equations, not
   against running text) and fast, and it names the region the image actually came from;
3. score with TM_SQDIFF_NORMED (primary) and TM_CCOEFF_NORMED (cross-check) and compare the
   embedded raster with a freshly rendered 600-dpi crop of the matched region: missing ink,
   extra ink, ink IoU and perceptual distance;
4. run a solid-blob detector for the PartialBiGrasp-style corruption (a stretchy glyph
   collapsed into a filled rectangle) plus a vanished-glyph detector;
5. compare the declared number with the number of the region the image actually matched —
   which is what catches an image sitting under the wrong equation number.

Two questions are answered independently for every image:
  * FIDELITY  — does the image faithfully reproduce the matched PDF region?
  * PLACEMENT — is that region the one the slot declares?

Outputs machine-readable JSON plus per-image evidence PNGs
(embedded | fresh PDF crop | red = PDF ink the crop lost, blue = ink present only in the crop).

Read-only: the deliverable and the source PDF are only ever opened for reading.

Usage
-----
  python check_crop_fidelity.py --registry registry.json --out OUTDIR [--only A,B] [--jobs N]
  python check_crop_fidelity.py --html D.html --pdf S.pdf --name X --out OUTDIR
  python check_crop_fidelity.py --selftest   # needs CROP_FIDELITY_PRE_DIR / CROP_FIDELITY_PDF
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time

import cv2
import numpy as np
import pymupdf

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ---------------------------------------------------------------- constants

DISCOVER_DPI = 150
FINE_DPI = 600
SRC_DPIS = [150, 200, 300, 600, 400, 240, 170, 130, 110, 96, 72]
PX_PER_PT_600 = FINE_DPI / 72.0

# score bands, from the earlier audits' precedent
BAND_CLEAN, BAND_MINOR, BAND_NONMATCH = 0.0003, 0.0092, 0.16
GOOD_CCOEFF = 0.80            # a region match below this is not considered a placement

EQNUM_RE = re.compile(r'^\((\d{1,3})\)$')
FIGCAP_RE = re.compile(r'^(?:Fig\.?|Figure|FIGURE)\s*\.?\s*(\d{1,2})\b', re.I)
TABCAP_RE = re.compile(r'^(?:Table|TABLE|表)\s*\.?\s*(\d{1,2})\b')
CAP_ZH_RE = re.compile(r'图\s*(\d{1,3})\s*[:：]')


# ---------------------------------------------------------------- HTML side

def _strip_tags(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&')
          .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
    return re.sub(r'\s+', ' ', s).strip()


def _decode_data_uri(src):
    if not src.startswith('data:'):
        return None, None
    try:
        payload = src.split(',', 1)[1]
        b = base64.b64decode(payload + '=' * (-len(payload) % 4))
    except Exception:
        return None, None
    try:
        g = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception:
        g = None
    return b, g


def declared_identity(rec):
    """What the HTML claims this image is, and where that claim came from.

    Handles the alt conventions in this corpus ("公式 13", "图 5", "图 3：caption…",
    "assets/eq12.png", "") plus the neighbouring 图 N：caption as an independent read.
    """
    alt = (rec.get('alt') or '').strip()
    ctx_a = (rec.get('ctx_after') or '')
    ctx_b = (rec.get('ctx_before') or '')

    def parse(s):
        if not s:
            return None, None, None
        m = re.search(r'(?:公式|式)\s*[:：]?\s*\(?(\d{1,3})\)?', s)
        if m:
            return 'eq', int(m.group(1)), 'zh_eq'
        m = re.search(r'\b(?:eq|equation)[_\-\s]*(\d{1,3})\b', s, re.I)
        if m:
            return 'eq', int(m.group(1)), 'asset_eq'
        m = re.search(r'(?:表)\s*[:：]?\s*(\d{1,3})', s)
        if m:
            return 'tab', int(m.group(1)), 'zh_tab'
        m = re.search(r'\b(?:tab|table)[_\-\s]*(\d{1,3})\b', s, re.I)
        if m:
            return 'tab', int(m.group(1)), 'asset_tab'
        m = CAP_ZH_RE.search(s)
        if m:
            return 'fig', int(m.group(1)), 'zh_fig'
        m = re.search(r'图\s*(\d{1,3})', s)
        if m:
            return 'fig', int(m.group(1)), 'zh_fig_bare'
        m = re.search(r'\b(?:fig|figure)[_\-\s]*(\d{1,3})\b', s, re.I)
        if m:
            return 'fig', int(m.group(1)), 'asset_fig'
        return None, None, None

    kind, num, how = parse(alt)
    src = 'alt' if kind else 'none'
    if kind is None:
        if CAP_ZH_RE.match(ctx_a.strip()):
            kind, num, how, src = 'fig', int(CAP_ZH_RE.match(ctx_a.strip()).group(1)), 'zh_fig', 'ctx_after'
        else:
            k2, n2, h2 = parse(ctx_a[:140])
            if k2:
                kind, num, how, src = k2, n2, h2, 'ctx_after'
    if kind is None:
        m = CAP_ZH_RE.search(ctx_b[-200:])
        if m:
            kind, num, how, src = 'fig', int(m.group(1)), 'zh_fig', 'ctx_before'

    ctx_kind = ctx_num = None
    if CAP_ZH_RE.match(ctx_a.strip()):
        ctx_kind, ctx_num = 'fig', int(CAP_ZH_RE.match(ctx_a.strip()).group(1))
    else:
        ck, cn, _ = parse(ctx_a[:140])
        if ck:
            ctx_kind, ctx_num = ck, cn
    if ctx_kind is None:
        m = CAP_ZH_RE.search(ctx_b[-200:])
        if m:
            ctx_kind, ctx_num = 'fig', int(m.group(1))

    return dict(declared_kind=kind, declared_num=num, declared_src=src, declared_how=how,
                declared_label=(f'{kind}{num}' if kind else None),
                ctx_kind=ctx_kind, ctx_num=ctx_num,
                label_conflict=bool(kind and ctx_kind and (kind, num) != (ctx_kind, ctx_num)))


def load_html_images(path):
    raw = open(path, encoding='utf-8', errors='replace').read()
    b0 = raw.find('<body')
    body = raw[b0:] if b0 >= 0 else raw
    body = re.sub(r'<script.*?</script>', ' ', body, flags=re.S | re.I)
    body = re.sub(r'<style.*?</style>', ' ', body, flags=re.S | re.I)
    imgs = []
    for i, m in enumerate(re.finditer(r'<img\b[^>]*?>', body, re.I)):
        tag = m.group(0)
        src = (re.search(r'src\s*=\s*"([^"]*)"', tag, re.I) or [None, ''])[1]
        alt = (re.search(r'alt\s*=\s*"([^"]*)"', tag, re.I) or [None, ''])[1]
        cls = (re.search(r'class\s*=\s*"([^"]*)"', tag, re.I) or [None, ''])[1]
        b, g = _decode_data_uri(src)
        rec = dict(idx=i, alt=alt, cls=cls, pos=m.start(),
                   is_data=bool(b), nbytes=len(b) if b else 0,
                   sha=hashlib.sha256(b).hexdigest() if b else '',
                   dims=[int(g.shape[1]), int(g.shape[0])] if g is not None else None,
                   ctx_before=_strip_tags(body[max(0, m.start() - 3000):m.start()])[-300:],
                   ctx_after=_strip_tags(body[m.end():m.end() + 3000])[:300],
                   _gray=g)
        rec.update(declared_identity(rec))
        imgs.append(rec)
    return imgs


# ---------------------------------------------------------------- PDF structure

def pdf_anchors(doc, eq_right_frac=0.42):
    """Equation numbers, figure captions and table captions, per page."""
    out = {}
    for pno in range(doc.page_count):
        pg = doc[pno]
        W, H = pg.rect.width, pg.rect.height
        eqs, figs, tabs = [], [], []
        for w in pg.get_text('words'):
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            m = EQNUM_RE.match(txt.strip())
            if m and x0 > W * eq_right_frac:
                eqs.append(dict(n=int(m.group(1)), box=[x0, y0, x1, y1]))
        for blk in pg.get_text('blocks'):
            x0, y0, x1, y1, txt = blk[0], blk[1], blk[2], blk[3], blk[4]
            t = txt.strip()
            m = TABCAP_RE.match(t)
            if m:
                tabs.append(dict(n=int(m.group(1)), box=[x0, y0, x1, y1],
                                 text=re.sub(r'\s+', ' ', t)[:70]))
                continue
            m = FIGCAP_RE.match(t)
            if m:
                figs.append(dict(n=int(m.group(1)), box=[x0, y0, x1, y1],
                                 text=re.sub(r'\s+', ' ', t)[:70]))
        out[pno + 1] = dict(eqs=eqs, figs=figs, tabs=tabs, W=W, H=H)
    return out


def candidate_regions(anchors, rend):
    """Every place in the PDF a figure/equation/table image could legitimately come from.

    Equation: the band on the same line as its '(N)' number, from the column margin to the
    number, tall enough for a multi-line display equation.
    Figure:   the column band above the 'Fig. N' caption.
    Table:    the band above the 'Table N' caption.
    """
    regs = []
    for p in sorted(anchors):
        a = anchors[p]
        for e in a['eqs']:
            x0, y0, x1, y1 = e['box']
            regs.append(dict(kind='eq', num=e['n'], page=p,
                             rect=[round(a['W'] * 0.04, 1), round(y0 - 46, 1),
                                   round(x1 + 18, 1), round(y1 + 26, 1)]))
        for f in a['figs']:
            x0, y0, x1, y1 = f['box']
            regs.append(dict(kind='fig', num=f['n'], page=p,
                             rect=[round(max(0.0, x0 - 10), 1), round(max(0.0, y0 - 400), 1),
                                   round(min(a['W'], x1 + 10), 1), round(y1 + 2, 1)],
                             caption=f['text']))
        for t in a['tabs']:
            x0, y0, x1, y1 = t['box']
            regs.append(dict(kind='tab', num=t['n'], page=p,
                             rect=[round(max(0.0, x0 - 10), 1), round(max(0.0, y0 - 400), 1),
                                   round(min(a['W'], x1 + 10), 1), round(y1 + 2, 1)],
                             caption=t['text']))
    return regs


class Renderer:
    """Cached page rasteriser over a read-only PyMuPDF document."""

    def __init__(self, pdf_path):
        self.doc = pymupdf.open(pdf_path)
        self.pages = self.doc.page_count
        r = self.doc[0].rect
        self.W, self.H = r.width, r.height
        self._low = None
        self._reg_low = {}
        self._fine = {}
        self._fine_order = []

    def low_pages(self):
        if self._low is None:
            out = []
            for p in range(self.pages):
                pm = self.doc[p].get_pixmap(dpi=DISCOVER_DPI, colorspace=pymupdf.csGRAY)
                out.append(np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width))
            self._low = out
        return self._low

    def region_low(self, page, rect):
        key = (page, tuple(rect))
        if key not in self._reg_low:
            if len(self._reg_low) > 400:
                self._reg_low.clear()
            self._reg_low[key] = self.crop_pt(page, rect, DISCOVER_DPI)
        return self._reg_low[key]

    def crop_pt(self, page, rect, dpi=FINE_DPI):
        pm = self.doc[page - 1].get_pixmap(dpi=dpi, clip=pymupdf.Rect(*rect),
                                           colorspace=pymupdf.csGRAY)
        return np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width)

    def fine_page(self, page):
        if page not in self._fine:
            self._fine[page] = self.crop_pt(page, [0, 0, self.W, self.H], FINE_DPI)
            self._fine_order.append(page)
            while len(self._fine_order) > 3:
                self._fine.pop(self._fine_order.pop(0), None)
        return self._fine[page]

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass


# ---------------------------------------------------------------- matching

def _resize_to(g, w, h):
    interp = cv2.INTER_AREA if (w * h) < (g.shape[0] * g.shape[1]) else cv2.INTER_CUBIC
    return cv2.resize(g, (max(1, w), max(1, h)), interpolation=interp)


def _match(page, tmpl, method):
    if tmpl.shape[0] >= page.shape[0] or tmpl.shape[1] >= page.shape[1]:
        return None, None
    if page.shape[0] < 8 or page.shape[1] < 8:
        return None, None
    r = cv2.matchTemplate(page, tmpl, method)
    if method == cv2.TM_SQDIFF_NORMED:
        mn, _mx, mnl, _mxl = cv2.minMaxLoc(r)
        return float(mn), (int(mnl[0]), int(mnl[1]))
    _mn, mx, _mnl, _mxl = cv2.minMaxLoc(r)
    return float(mx), (int(_mxl[0]), int(_mxl[1]))


def _fit_scales(g, shape, scales):
    out = []
    for s in scales:
        w, h = int(round(g.shape[1] * s)), int(round(g.shape[0] * s))
        if w < 10 or h < 8 or w >= shape[1] or h >= shape[0]:
            continue
        out.append((s, w, h))
    return out


def _ink_cov(t, win, tol=1):
    """Symmetric ink containment between a resized template and a candidate window.

    Returns min(share of region ink the crop covers, share of crop ink the region explains)
    — near 1.0 for a correct placement, low for a blank or unrelated window. Normalised
    correlation alone is unsafe here because a mostly-white template matches blank space
    almost perfectly. The dilation tolerance is deliberately tight: a generous one lets a
    downscaled template cover almost any glyph texture and destroys the discrimination.
    """
    if t.size == 0 or win.size == 0:
        return 0.0
    mi, ri = ink_mask(t), ink_mask(win)
    if mi is None or ri is None:
        return 0.0
    mi_n, ri_n = int(mi.sum()), int(ri.sum())
    if mi_n < 60 or ri_n < 60:
        return 0.0
    if mi_n < 0.004 * t.size:
        return 0.0
    k = np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)
    md = cv2.dilate(mi.astype(np.uint8), k, 1) > 0
    rd = cv2.dilate(ri.astype(np.uint8), k, 1) > 0
    cov_pdf = float((ri & md).sum()) / ri_n
    cov_emb = float((mi & rd).sum()) / mi_n
    return min(cov_pdf, cov_emb)


# coarse scale ladder: the embedded crops are resampled, so the effective source DPI is often
# not a round number. 10% steps span renders from 1200 dpi down to 72 dpi at DISCOVER_DPI.
COARSE_SCALES = [round(float(x), 5) for x in np.geomspace(1200.0 / 1200.0 * 0.125, 2.0834, 30)]


def _scan(g, raster, scales, topk=1):
    """Best placements of g inside one raster, ranked on ink cover (correlation breaks ties)."""
    hits = []
    for s, w, h in _fit_scales(g, raster.shape, scales):
        t = _resize_to(g, w, h)
        v, loc = _match(raster, t, cv2.TM_CCOEFF_NORMED)
        if v is None:
            continue
        win = raster[loc[1]:loc[1] + h, loc[0]:loc[0] + w]
        cov = _ink_cov(t, win)
        if cov > 0.0:
            hits.append((cov, v, loc, s, w, h))
    hits.sort(key=lambda x: (-x[0], -x[1]))
    return hits[:topk]


def _coarse_ladder():
    """Scale ladder for the coarse (DISCOVER_DPI) passes.

    Embedded crops are resampled, so the effective source DPI is frequently not a round
    number and a sparse ladder misses the correct scale. The range is bounded to physically
    plausible source resolutions (72..900 dpi): without that bound the search drifts to
    absurdly small scales, where TM_SQDIFF_NORMED and TM_CCOEFF_NORMED alike are meaningless.
    """
    lo, hi = DISCOVER_DPI / 900.0, DISCOVER_DPI / 72.0
    return sorted(set(round(float(x), 5) for x in
                      list(np.geomspace(lo, hi, 46)) +
                      [DISCOVER_DPI / float(d) for d in SRC_DPIS]))


COARSE_LADDER = _coarse_ladder()


def _match_pick(raster, t):
    """Locate a template by normalised correlation AND report the squared difference there.

    TM_CCOEFF_NORMED is used to choose the alignment and the scale, because it has a genuine
    peak at the correct one. TM_SQDIFF_NORMED does not: its minimum sits at the smallest
    scale tried, since a blurred, low-contrast template minimises the normalised squared
    difference against any light background. SQDIFF is therefore kept as the reported
    difference metric, evaluated at the alignment correlation selects, not as the search
    criterion.
    """
    if t.shape[0] >= raster.shape[0] or t.shape[1] >= raster.shape[1]:
        return None
    if raster.shape[0] < 8 or raster.shape[1] < 8:
        return None
    r = cv2.matchTemplate(raster, t, cv2.TM_CCOEFF_NORMED)
    _mn, cc, _mnl, loc = cv2.minMaxLoc(r)
    win = raster[loc[1]:loc[1] + t.shape[0], loc[0]:loc[0] + t.shape[1]]
    if win.shape != t.shape:
        return None
    sq = float(np.sum((t.astype(np.float64) - win.astype(np.float64)) ** 2) /
               max(1.0, np.sqrt(np.sum(t.astype(np.float64) ** 2) *
                                np.sum(win.astype(np.float64) ** 2))))
    return float(cc), sq, (int(loc[0]), int(loc[1]))


def _coarse_in(g, raster, ladder=None):
    """Best placement of g inside a raster. -> (ccoeff, sqdiff, loc, scale, w, h)"""
    best = None
    for s, w, h in _fit_scales(g, raster.shape, ladder or COARSE_LADDER):
        t = _resize_to(g, w, h)
        r = _match_pick(raster, t)
        if r is None:
            continue
        cc, sq, loc = r
        if best is None or cc > best[0]:
            best = (cc, sq, loc, s, w, h)
    return best


def _fine_around(g, rend, page, box150, scale150, pad=(0.35, 0.60), span=0.14, step=0.01):
    """600-dpi refinement in a padded window around a coarse placement.

    The coarse pass fixes the location and the scale to within a few percent, so the fine
    pass only needs a narrow band of scales.
    """
    fine = rend.fine_page(page)
    k = FINE_DPI / float(DISCOVER_DPI)
    x, y, w, h = box150
    px = int(np.clip(pad[0] * w * k, 120, 1800))
    py = int(np.clip(pad[1] * h * k, 220, 1800))
    x0 = max(0, int(x * k) - px)
    y0 = max(0, int(y * k) - py)
    x1 = min(fine.shape[1], int((x + w) * k) + px)
    y1 = min(fine.shape[0], int((y + h) * k) + py)
    win = fine[y0:y1, x0:x1]
    if win.size == 0:
        return None
    base = scale150 * k
    scales = sorted(set(round(float(base * f), 6)
                        for f in np.arange(1.0 - span, 1.0 + span + 1e-9, step)) |
                    set(600.0 / d for d in (150, 200, 240, 300, 400, 600)))
    bcc, bsq, bb = -2.0, None, None
    for s, w2, h2 in _fit_scales(g, win.shape, scales):
        t = _resize_to(g, w2, h2)
        r = _match_pick(win, t)
        if r is None:
            continue
        cc, sq, loc = r
        if cc > bcc:
            bcc, bsq, bb = cc, sq, (loc[0], loc[1], w2, h2)
    if bb is None:
        return None
    kk = PX_PER_PT_600
    return dict(sqdiff=float(bsq), ccoeff=float(bcc), origin=(x0, y0), box=bb, window=win,
                box_pt=[round((x0 + bb[0]) / kk, 1), round((y0 + bb[1]) / kk, 1),
                        round((x0 + bb[0] + bb[2]) / kk, 1),
                        round((y0 + bb[1] + bb[3]) / kk, 1)],
                scale600=round(float(bb[2] / max(1.0, g.shape[1])), 6))


def region_at(regions, page, box_pt):
    """Which structural region does this box sit in? Smallest containing region wins."""
    cx = 0.5 * (box_pt[0] + box_pt[2])
    cy = 0.5 * (box_pt[1] + box_pt[3])
    best = None
    for r in regions:
        if r['page'] != page:
            continue
        x0, y0, x1, y1 = r['rect']
        if x0 - 6 <= cx <= x1 + 6 and y0 - 6 <= cy <= y1 + 6:
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, r)
    return best[1] if best else None


COVER_SQDIFF_EQ = 0.02   # equation strips: a region counts as reproduced below this
COVER_SQDIFF_FIG = 0.12  # figures: resampling costs more, so the bar is looser
COVER_CCOEFF = 0.60
DECLARED_OK = 0.020        # a slot this close to its declared region is a faithful crop
FINE_ACCEPT = 0.055        # below this a 600-dpi placement is a real match somewhere


def _region_placement(g, rend, r):
    """Two-tier placement of g inside one structural region. -> dict or None

    The coarse pass works in the region's own raster frame, so its location must be shifted
    by the region's origin before the fine pass, which works in page pixels.
    """
    low = rend.region_low(r['page'], r['rect'])
    if low.size == 0:
        return None
    c = _coarse_in(g, low)
    if c is None:
        return None
    cc0, sq0, loc0, s0, w0, h0 = c
    kr = DISCOVER_DPI / 72.0
    loc_page = (loc0[0] + r['rect'][0] * kr, loc0[1] + r['rect'][1] * kr)
    f = _fine_around(g, rend, r['page'], (loc_page[0], loc_page[1], w0, h0), s0)
    if f is None:
        return None
    f['region'] = r
    f['coarse_ccoeff'] = round(float(cc0), 5)
    f['coarse_sqdiff'] = round(float(sq0), 6)
    f['coarse_loc_page'] = [round(loc_page[0], 1), round(loc_page[1], 1)]
    return f


def locate(g, rend, regions, anchors=None, declared=None, max_alt=3):
    """Locate the image and decide the two questions separately.

    FIDELITY  — how well does the matched 600-dpi crop reproduce the image?
    PLACEMENT — is the matched region the one the slot's number declares?

    Tier 1 scores the image against the region its own number declares. That single test
    answers both questions for a correctly placed image, and it is the cheap path.
    Tier 2 runs only when Tier 1 fails: it shortlists every region by a coarse sweep and
    re-scores the best few at 600 dpi, which names the region the image actually came from.
    """
    res = dict(page=None, box600=None, rect_pt=None, scale600=None, sqdiff=None, ccoeff=None,
               hit_kind=None, hit_num=None, stage='none', candidates=[], ambiguous=False,
               declared_sqdiff=None, declared_ccoeff=None, tier=0)
    if not regions:
        res['stage'] = 'no_regions'
        return res

    declared_regs = []
    if declared and declared[0] and declared[1]:
        declared_regs = [r for r in regions
                         if r['kind'] == declared[0] and r['num'] == declared[1]]

    # ---------- Tier 1: the slot's own region
    dec = None
    for r in declared_regs[:3]:
        p = _region_placement(g, rend, r)
        if p and (dec is None or p['sqdiff'] < dec['sqdiff']):
            dec = p
    if dec is not None:
        res['declared_sqdiff'] = round(dec['sqdiff'], 8)
        res['declared_ccoeff'] = round(dec['ccoeff'], 5)
        if dec['sqdiff'] <= DECLARED_OK:
            res.update(_pack(dec, dec['region']))
            res['tier'] = 1
            return res

    # ---------- Tier 2: search every region
    scored = []
    for r in regions:
        if declared_regs and any(r is d for d in declared_regs):
            continue
        c = _coarse_in(g, rend.region_low(r['page'], r['rect']))
        if c is None:
            continue
        scored.append((c[0], r, c))
    scored.sort(key=lambda x: -x[0])
    alts = []
    for cc0, r, c in scored[:max_alt]:
        p = _region_placement(g, rend, r)
        if p:
            alts.append(p)

    pool = ([dec] if dec else []) + alts
    if not pool:
        # ---------- last resort: whole-page scan
        fb = _page_fallback(g, rend)
        if fb is None:
            res['stage'] = 'unmatchable'
            return res
        res.update(fb)
        r = region_at(regions, res['page'], res['box_pt'])
        if r:
            res.update(hit_kind=r['kind'], hit_num=r['num'], rect_pt=list(r['rect']),
                       caption=r.get('caption'))
        res['tier'] = 3
        return res

    pool.sort(key=lambda d: d['sqdiff'])
    best = pool[0]
    res.update(_pack(best, best['region']))
    res['tier'] = 2
    res['candidates'] = [dict(kind=d['region']['kind'], num=d['region']['num'],
                              page=d['region']['page'], sqdiff=round(d['sqdiff'], 8),
                              ccoeff=round(d['ccoeff'], 5),
                              coarse_ccoeff=d.get('coarse_ccoeff'),
                              coarse_sqdiff=d.get('coarse_sqdiff')) for d in pool[:6]]
    if len(pool) > 1:
        c0, c1 = pool[0], pool[1]
        k0 = (c0['region']['kind'], c0['region']['num'])
        k1 = (c1['region']['kind'], c1['region']['num'])
        if k0 != k1 and c1['sqdiff'] < max(0.0015, c0['sqdiff'] * 2.5):
            res['ambiguous'] = True
            res['ambiguous_with'] = f'{k1[0]}{k1[1]} (sqdiff {round(c1["sqdiff"], 8)})'
    return res


def _declared_pad(rect, fx, fy):
    return [rect[0]-(rect[2]-rect[0])*fx, rect[1]-(rect[3]-rect[1])*fy,
            rect[2]+(rect[2]-rect[0])*fx, rect[3]+(rect[3]-rect[1])*fy]

def _pack(p, r):
    ox, oy = p['origin']
    x, y, w, h = p['box']
    return dict(stage='fine', page=r['page'], sqdiff=round(p['sqdiff'], 8),
                ccoeff=round(p['ccoeff'], 5), scale600=p['scale600'],
                box600=[int(ox + x), int(oy + y), int(w), int(h)], box_pt=p['box_pt'],
                hit_kind=r['kind'], hit_num=r['num'], rect_pt=list(r['rect']),
                caption=r.get('caption'),
                _region=p['window'][y:y + h, x:x + w])


def _page_fallback(g, rend):
    """Whole-document scan, used only when no structural region explains the image."""
    pages = rend.low_pages()
    best = None
    for p in range(1, rend.pages + 1):
        c = _coarse_in(g, pages[p - 1])
        if c is None:
            continue
        if best is None or c[0] > best[0]:
            best = (c[0], p, c)
    if best is None:
        return None
    _cc, p, c = best
    f = _fine_around(g, rend, p, (c[2][0], c[2][1], c[4], c[5]), c[3], pad=(0.5, 0.5))
    if f is None or f['sqdiff'] > 0.20:
        return None
    return dict(page=p, sqdiff=round(f['sqdiff'], 8), ccoeff=round(f['ccoeff'], 5),
                box600=[0, 0, 0, 0], box_pt=f['box_pt'], scale600=f['scale600'],
                _region=f['window'], tier=3)


# ---------------------------------------------------------------- metrics

def image_type(g):
    """'halftone' for photographs / shaded renders, 'lineart' for text and line drawings."""
    if g is None or g.size == 0:
        return 'unknown'
    hist = cv2.calcHist([g], [0], None, [256], [0, 256]).ravel()
    mid = float(hist[40:216].sum()) / float(g.size)
    return 'halftone' if mid > 0.18 else 'lineart'


INK_LIMITS = {          # (missing_frac, extra_frac) above which the disagreement is real
    'lineart': (0.05, 0.05),
    'halftone': (0.35, 0.35),
    'unknown': (0.20, 0.20),
}


def ink_mask(g):
    if g is None or g.size == 0:
        return None
    _t, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b > 0


def _comps(mask, min_area=12):
    n, lab, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    out = []
    for kk in range(1, n):
        x, y, w, h, area = (int(stats[kk][0]), int(stats[kk][1]), int(stats[kk][2]),
                            int(stats[kk][3]), int(stats[kk][4]))
        if area < min_area:
            continue
        out.append(dict(x=x, y=y, w=w, h=h, area=area,
                        fill=round(area / float(max(1, w * h)), 3),
                        ar=round(h / float(max(1, w)), 2)))
    return out


def blob_report(mask):
    """Solid near-black blobs: very high fill ratio inside their own bounding box."""
    if mask is None or not mask.any():
        return [], 0
    tot = int(mask.sum())
    blobs = []
    for c in _comps(mask):
        if c['fill'] >= 0.82 and c['w'] >= 4 and c['h'] >= 4 and c['area'] >= 60:
            frac = c['area'] / float(tot)
            if frac >= 0.008:
                d = dict(c)
                d['frac'] = round(frac, 4)
                blobs.append(d)
    blobs.sort(key=lambda d: -d['area'])
    return blobs, tot


def stretchy_glyphs(mask, min_h_frac=0.25, min_ar=2.2, min_area=40):
    """Tall thin components: big delimiters, stretchy braces/brackets, integral signs."""
    if mask is None or not mask.any():
        return []
    H = mask.shape[0]
    out = [c for c in _comps(mask, min_area=min_area)
           if c['h'] >= min_h_frac * H and c['ar'] >= min_ar]
    out.sort(key=lambda d: -d['area'])
    return out


def pair_metrics(g_emb, g_region):
    out = dict(ok=False)
    if g_emb is None or g_region is None or g_emb.size == 0 or g_region.size == 0:
        return out
    if g_emb.shape != g_region.shape:
        g_emb = _resize_to(g_emb, g_region.shape[1], g_region.shape[0])
    mi, ri = ink_mask(g_emb), ink_mask(g_region)
    if mi is None or ri is None:
        return out
    out['ok'] = True
    out['dims'] = [int(g_region.shape[1]), int(g_region.shape[0])]
    out['img_type'] = image_type(g_emb)
    k = np.ones((3, 3), np.uint8)
    md = cv2.dilate(mi.astype(np.uint8), k, 1) > 0
    rd = cv2.dilate(ri.astype(np.uint8), k, 1) > 0
    missing = ri & ~md          # PDF has ink here, the crop does not
    extra = mi & ~rd            # the crop has ink the PDF does not
    ri_n, mi_n = int(ri.sum()), int(mi.sum())
    out.update(ink_emb=mi_n, ink_pdf=ri_n,
               missing_ink=int(missing.sum()), extra_ink=int(extra.sum()),
               missing_frac=round(missing.sum() / float(max(1, ri_n)), 5),
               extra_frac=round(extra.sum() / float(max(1, mi_n)), 5),
               ink_iou=round(int((mi & ri).sum()) / float(max(1, int((mi | ri).sum()))), 5),
               ink_ratio=round(mi_n / float(max(1, ri_n)), 4))
    bl_emb, _ = blob_report(mi)
    bl_pdf, _ = blob_report(ri)
    out['blobs_embedded'] = bl_emb[:6]
    out['blobs_pdf'] = bl_pdf[:6]
    out['blob_extra'] = [b for b in bl_emb if b['fill'] >= 0.9 and b['area'] >= 120][:6]
    vanished = [c for c in _comps(missing, min_area=30) if c['fill'] < 0.75]
    vanished.sort(key=lambda d: -d['area'])
    out['vanished_components'] = vanished[:6]
    out['vanished_area'] = int(sum(c['area'] for c in vanished))
    out['stretchy_pdf'] = len(stretchy_glyphs(ri))
    out['stretchy_emb'] = len(stretchy_glyphs(mi))
    a = cv2.resize(g_emb, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(g_region, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    out['ahash_dist'] = int(np.abs(a - b).mean().round())
    return out


def read_gray(path):
    """cv2.imread that tolerates non-ASCII paths (OpenCV cannot handle them on Windows)."""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None


def write_img(path, img):
    """cv2.imwrite that tolerates non-ASCII paths."""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or '.png', img)
    if not ok:
        return False
    try:
        buf.tofile(path)
        return True
    except OSError:
        return False


def evidence_png(path, g_emb, g_region):
    if g_emb is None or g_region is None:
        return False
    if g_emb.shape != g_region.shape:
        g_emb = _resize_to(g_emb, g_region.shape[1], g_region.shape[0])
    mi, ri = ink_mask(g_emb), ink_mask(g_region)
    h, w = g_region.shape
    ov = np.full((h, w, 3), 255, np.uint8)
    if mi is not None and ri is not None:
        k = np.ones((3, 3), np.uint8)
        md = cv2.dilate(mi.astype(np.uint8), k, 1) > 0
        rd = cv2.dilate(ri.astype(np.uint8), k, 1) > 0
        ov[mi & ri] = (175, 175, 175)
        ov[ri & ~md] = (0, 0, 235)      # red  = PDF ink the crop lost
        ov[mi & ~rd] = (235, 90, 0)     # blue = ink present only in the crop
    canvas = np.full((h, w * 3, 3), 255, np.uint8)
    canvas[:, :w] = cv2.cvtColor(g_emb, cv2.COLOR_GRAY2BGR)
    canvas[:, w:2 * w] = cv2.cvtColor(g_region, cv2.COLOR_GRAY2BGR)
    canvas[:, 2 * w:] = ov
    for x in (w, 2 * w):
        canvas[:, x:x + 1] = (0, 0, 0)
    return write_img(path, canvas)


# ---------------------------------------------------------------- severity

def severity_of(r):
    """Rank the defect so the report can order worst-first."""
    f = set(r.get('flags') or [])
    if 'DUPLICATE_BYTES' in f:
        return ('critical', 0)
    if r.get('placement', {}).get('mismatch'):
        return ('critical', 1)
    if 'UNMATCHED' in f:
        return ('critical', 2)
    m = r.get('metrics') or {}
    if not m.get('ok'):
        return ('unknown', 5)
    iou = m.get('ink_iou', 1.0)
    miss, extra = m.get('missing_frac', 0.0), m.get('extra_frac', 0.0)
    lim_m, lim_e = INK_LIMITS.get(m.get('img_type'), INK_LIMITS['unknown'])
    cc = (r.get('locate') or {}).get('ccoeff')
    if iou < 0.35 or miss > 3 * lim_m or extra > 3 * lim_e or (cc is not None and cc < 0.40):
        return ('major', 3)
    if iou < 0.60 or miss > lim_m or extra > lim_e:
        return ('major', 4)
    if iou < 0.80:
        return ('moderate', 6)
    if miss > lim_m / 2 or extra > lim_e / 2:
        return ('minor', 7)
    return ('ok', 9)


# ---------------------------------------------------------------- per image

def audit_image(im, rend, regions, anchors, by_sha, dump_all=False, ev_dir=None):
    idx = im['idx']
    flags = []
    out = dict(idx=idx, declared_kind=im['declared_kind'], declared_num=im['declared_num'],
               declared_src=im['declared_src'], declared_how=im.get('declared_how'),
               ctx_kind=im['ctx_kind'], ctx_num=im['ctx_num'],
               label_conflict=im.get('label_conflict', False), cls=im['cls'])

    if im['_gray'] is None:
        out['flags'] = ['UNDECODABLE']
        out['severity'] = ['critical', 2]
        return out

    peers = [i for i in by_sha.get(im['sha'], []) if i != idx]
    if peers:
        flags.append('DUPLICATE_BYTES')
        out['duplicate_of_idx'] = peers

    declared = (im['declared_kind'], im['declared_num'])
    loc = locate(im['_gray'], rend, regions, anchors, declared)
    out['locate'] = {k: v for k, v in loc.items() if not k.startswith('_')}
    region = loc.get('_region')
    if loc.get('page') is None or region is None:
        flags.append('UNMATCHED')
        out['flags'] = flags
        out['severity'] = list(severity_of(out))
        return out
    m = pair_metrics(im['_gray'], region)
    out['metrics'] = m
    sq, cc = loc.get('sqdiff'), loc.get('ccoeff')
    out['band'] = ('unknown' if sq is None else
                   'clean' if sq <= BAND_CLEAN else
                   'minor' if sq <= BAND_MINOR else
                   'suspect' if sq <= BAND_NONMATCH else 'nonmatch')
    if cc is not None and cc < 0.70:
        flags.append('LOW_CORRELATION')
    if m.get('ok'):
        lim_m, lim_e = INK_LIMITS.get(m.get('img_type'), INK_LIMITS['unknown'])
        if m['missing_frac'] > lim_m:
            flags.append('INK_MISSING')
        if m['extra_frac'] > lim_e:
            flags.append('INK_EXTRA')
        if m.get('img_type') == 'lineart':
            if m.get('blob_extra'):
                flags.append('SOLID_BLOB')
            if m.get('vanished_area', 0) > 40:
                flags.append('GLYPH_VANISHED')
            if m.get('stretchy_pdf', 0) > m.get('stretchy_emb', 0) and m['missing_frac'] > 0.02:
                flags.append('STRETCHY_GLYPH_LOSS')

    k = PX_PER_PT_600
    box_pt = loc.get('box_pt')
    if box_pt:
        page_area = rend.W * rend.H
        out['page_area_frac'] = round(((box_pt[2] - box_pt[0]) * (box_pt[3] - box_pt[1]))
                                     / float(page_area), 4)
        if out['page_area_frac'] > 0.45:
            flags.append('PAGE_REGION')

    # ---- PLACEMENT
    dk, dn = im['declared_kind'], im['declared_num']
    plc = dict(declared=im['declared_label'], matched_kind=loc.get('hit_kind'),
               matched_num=loc.get('hit_num'), mismatch=False, why=None,
               tier=loc.get('tier'), ambiguous=bool(loc.get('ambiguous')))
    if dk and dn and loc.get('hit_kind') == dk and loc.get('hit_num') is not None:
        if loc['hit_num'] != dn and not loc.get('ambiguous'):
            plc.update(mismatch=True,
                       why=f'slot {dk}{dn} reproduces {dk}{loc["hit_num"]} '
                           f'(sqdiff {loc.get("sqdiff")})')
    elif dk and dn and loc.get('hit_kind') is not None and loc.get('ambiguous'):
        pass                                   # identity not decidable at this resolution
    out['placement'] = plc
    if plc['mismatch']:
        flags.append('SLOT_MISMATCH')
    if im.get('label_conflict'):
        flags.append('LABEL_CONFLICT')
    # declared-slot test failed but the alternative is itself a poor match -> flag fidelity
    ds = loc.get('declared_sqdiff')
    if ds is not None and ds > DECLARED_OK and not plc['mismatch']:
        flags.append('NOT_AT_DECLARED_SLOT')

    # ---- evidence
    label = im['declared_label'] or f'img{idx:03d}'
    if ev_dir:
        ev = os.path.join(ev_dir, f'img{idx:03d}_{label}.png')
        if evidence_png(ev, im['_gray'], region):
            out['evidence'] = f'evidence/img{idx:03d}_{label}.png'
        if dump_all or flags:
            write_img(os.path.join(ev_dir, f'img{idx:03d}_{label}_emb.png'), im['_gray'])
            write_img(os.path.join(ev_dir, f'img{idx:03d}_{label}_pdf.png'), region)

    out['flags'] = flags
    out['severity'] = list(severity_of(out))
    return out


# ---------------------------------------------------------------- per paper

def audit_paper(name, html_path, pdf_path, outdir, max_images=None, dump_all=False):
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    ev_dir = os.path.join(outdir, 'evidence')
    os.makedirs(ev_dir, exist_ok=True)
    rec = dict(name=name, html=html_path, pdf=pdf_path, images=[], errors=[])
    try:
        imgs = load_html_images(html_path)
    except Exception as e:
        rec['errors'].append('HTML_READ_FAIL: ' + str(e)[:200])
        return rec
    try:
        rend = Renderer(pdf_path)
    except Exception as e:
        rec['errors'].append('PDF_OPEN_FAIL: ' + str(e)[:200])
        return rec
    anchors = pdf_anchors(rend.doc)
    regions = candidate_regions(anchors, rend)
    rec['pdf_pages'] = rend.pages
    rec['pdf_page_pt'] = [round(rend.W, 1), round(rend.H, 1)]
    rec['n_images'] = len(imgs)
    rec['n_regions'] = len(regions)
    rec['n_eq_anchors'] = sum(len(a['eqs']) for a in anchors.values())
    rec['n_fig_anchors'] = sum(len(a['figs']) for a in anchors.values())

    by_sha = {}
    for im in imgs:
        if im['sha']:
            by_sha.setdefault(im['sha'], []).append(im['idx'])

    for im in (imgs if max_images is None else imgs[:max_images]):
        try:
            r = audit_image(im, rend, regions, anchors, by_sha, dump_all=dump_all,
                            ev_dir=ev_dir)
        except Exception as e:
            r = dict(idx=im['idx'], flags=['ERROR'], error=str(e)[:200],
                     severity=['unknown', 5])
        r.update(alt=im['alt'], sha=im['sha'], nbytes=im['nbytes'], dims_emb=im['dims'],
                 ctx_before=im['ctx_before'], ctx_after=im['ctx_after'],
                 declared_label=im['declared_label'])
        rec['images'].append(r)
    # ---- coverage: which PDF equations/figures does the deliverable actually reproduce?
    covered, dup = {}, {}
    for r in rec['images']:
        loc = r.get('locate') or {}
        kk, nn = loc.get('hit_kind'), loc.get('hit_num')
        if kk not in ('eq', 'fig', 'tab') or nn is None:
            continue
        sq, cc = loc.get('sqdiff'), loc.get('ccoeff')
        lim = COVER_SQDIFF_EQ if kk == 'eq' else COVER_SQDIFF_FIG
        if sq is None or sq > lim or (cc is not None and cc < COVER_CCOEFF):
            continue
        covered.setdefault((kk, nn), []).append(r['idx'])
    for key, idxs in covered.items():
        if len(idxs) > 1:
            dup[f'{key[0]}{key[1]}'] = idxs
    missing = [f'{r["kind"]}{r["num"]}' for r in regions
               if (r['kind'], r['num']) not in covered]
    rec['coverage'] = dict(regions_total=len(regions),
                           regions_with_image=len(covered),
                           duplicated=sorted(dup.items()),
                           without_image=sorted(set(missing)))
    by_sev, by_flag = {}, {}
    for r in rec['images']:
        sev = (r.get('severity') or ['unknown'])[0]
        by_sev[sev] = by_sev.get(sev, 0) + 1
        for f in (r.get('flags') or []):
            by_flag[f] = by_flag.get(f, 0) + 1
    rec['severity_counts'] = by_sev
    rec['flag_counts'] = by_flag
    rend.close()
    rec['elapsed_s'] = round(time.time() - t0, 1)
    json.dump(rec, open(os.path.join(outdir, 'result.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return rec


def _worker(args):
    key, html, pdf, outdir = args
    try:
        rec = audit_paper(key, html, pdf, outdir)
        return dict(key=key, n=rec.get('n_images'), done=len(rec['images']),
                    elapsed=rec.get('elapsed_s'), errors=rec.get('errors'),
                    n_regions=rec.get('n_regions'),
                    n_eq=rec.get('n_eq_anchors'), n_fig=rec.get('n_fig_anchors'))
    except Exception as e:
        return dict(key=key, errors=[str(e)[:300]])


# ---------------------------------------------------------------- selftest

def selftest(pre_dir=None, pdf=None, live_html=None):
    """Validate against the known PartialBiGrasp corruption: the archived PRE-FIX crops
    (stretchy glyphs collapsed) must score clearly worse than the repaired live ones.

    The fixtures are not shipped with the repo: point CROP_FIDELITY_PRE_DIR at a folder of
    pre-fix `...eq<N>.png` crops and CROP_FIDELITY_PDF at the source PDF (or pass --pdf /
    --html). Without them the selftest skips instead of failing."""
    pre_dir = pre_dir or os.environ.get('CROP_FIDELITY_PRE_DIR')
    pdf = pdf or os.environ.get('CROP_FIDELITY_PDF')
    print('=== selftest: pre-fix vs repaired PartialBiGrasp equation crops')
    if not pre_dir or not os.path.isdir(pre_dir):
        print('  pre-fix crops not found (set CROP_FIDELITY_PRE_DIR); skipping')
        return
    if not pdf or not os.path.isfile(pdf):
        print('  source PDF not found (set CROP_FIDELITY_PDF); skipping')
        return
    rend = Renderer(pdf)
    anchors = pdf_anchors(rend.doc)
    regions = candidate_regions(anchors, rend)
    targets = (5, 13, 15, 16, 17, 18, 21)

    def run(g, eqn, tag, fname):
        loc = locate(g, rend, regions, anchors, ('eq', eqn))
        line = f'  {tag:8s} decl=eq{eqn:<3d} {fname[:22]:22s} {g.shape[1]:5d}x{g.shape[0]:4d}'
        if loc.get('page') and loc.get('_region') is not None:
            mm = pair_metrics(g, loc['_region'])
            line += (f' -> {loc["hit_kind"]}{loc["hit_num"]} p{loc["page"]:<2d}'
                     f' sqdiff={loc["sqdiff"]:.6f} cc={loc["ccoeff"]:.3f}'
                     f' iou={mm.get("ink_iou")} miss={mm.get("missing_frac")}'
                     f' extra={mm.get("extra_frac")} blob+={len(mm.get("blob_extra") or [])}'
                     f' van={mm.get("vanished_area")}')
        else:
            line += '  UNMATCHED'
        print(line)

    for f in sorted(os.listdir(pre_dir)):
        m = re.search(r'eq(\d+)\.png$', f)
        if m and int(m.group(1)) in targets:
            g = read_gray(os.path.join(pre_dir, f))
            if g is not None:
                run(g, int(m.group(1)), 'PRE-FIX', f)
    print()
    if live_html and os.path.isfile(live_html):
        for im in load_html_images(live_html):
            if im['declared_kind'] == 'eq' and im['declared_num'] in targets:
                run(im['_gray'], im['declared_num'], 'LIVE', im['alt'] or '')
    rend.close()


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--registry')
    ap.add_argument('--html')
    ap.add_argument('--pdf')
    ap.add_argument('--name')
    ap.add_argument('--out', default='fidelity_out')
    ap.add_argument('--only', default=None)
    ap.add_argument('--max-images', type=int, default=None)
    ap.add_argument('--dump-all', action='store_true')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()

    if a.selftest:
        selftest(pdf=a.pdf, live_html=a.html)
        return
    if a.html and a.pdf:
        rec = audit_paper(a.name or 'adhoc', a.html, a.pdf,
                          os.path.join(a.out, a.name or 'adhoc'),
                          max_images=a.max_images, dump_all=a.dump_all)
        print(json.dumps({kk: v for kk, v in rec.items() if kk != 'images'},
                         ensure_ascii=False))
        return

    reg = json.load(open(a.registry, encoding='utf-8'))
    keys = [kk for kk in reg if not a.only or kk in {x.strip() for x in a.only.split(',')}]
    jobs = []
    for kk in keys:
        v = reg[kk]
        if v.get('status') != 'OK' or not v.get('inv', {}).get('decodable'):
            print(f'{kk}: skip ({v.get("status")}, '
                  f'{v.get("inv", {}).get("decodable")} decodable images)', flush=True)
            continue
        jobs.append((kk, v['html_snap'], v['pdf_snap'],
                     os.path.join(a.out, re.sub(r'[^\w\-.]', '_', kk))))
    jobs.sort(key=lambda j: -reg[j[0]]['inv']['decodable'])

    if a.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            for r in ex.map(_worker, jobs):
                print(f'{r["key"]:34s} imgs={r.get("n")} done={r.get("done")} '
                      f'regions={r.get("n_regions")} eq={r.get("n_eq")} fig={r.get("n_fig")} '
                      f'{r.get("elapsed")}s {r.get("errors") or ""}', flush=True)
    else:
        for j in jobs:
            r = _worker(j)
            print(f'{r["key"]:34s} imgs={r.get("n")} done={r.get("done")} '
                  f'regions={r.get("n_regions")} eq={r.get("n_eq")} fig={r.get("n_fig")} '
                  f'{r.get("elapsed")}s {r.get("errors") or ""}', flush=True)


if __name__ == '__main__':
    main()
