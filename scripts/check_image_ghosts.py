# -*- coding: utf-8 -*-
r"""check_image_ghosts.py — find "ghosted" crops among the images embedded in a
translation deliverable, and tell them apart from the harmless case where the
image was simply rendered by a different rasteriser.

The defect
----------
Some embedded crops were captured by screenshotting a rendered page while it was
painted twice (a CSS transition, a canvas redraw, a zoom change). The result is a
second, offset copy of the same strokes: text looks like it has a shadow, curves
look doubled. Byte-deduplication and figure-number checks cannot see it, and it
survives into every downstream PDF.

Why `mad` alone is not enough
-----------------------------
Comparing the embedded raster with a fresh render of the same PDF region at the
same size gives a mean absolute difference (`mad`). That number also rises for
images produced by another rasteriser (headless browser zoom) because the
anti-aliasing differs, and it rises again whenever the located region is off by a
pixel. Measured on this corpus, `mad` alone flags roughly one third of a healthy
corpus. What actually separates a ghost is *ink accounting*:

  ink_ratio         ink(embedded) / ink(fresh pdf)        ghost > 1.03, healthy ~1.0
  unexplained_rel   embedded ink that has no pdf ink within `--dilate` px
                                                          ghost >= 0.02, healthy < 0.01
  vanished_rel      pdf ink that has no embedded ink nearby
                                                          ghost ~ 0 (a ghost only adds),
                                                          mislocation makes this large too

A ghost adds a layer of strokes, so ink goes up, the extra strokes land where the
PDF has paper, and nothing disappears. A different rasteriser keeps `ink_ratio`
at ~1.0; a mislocated region makes `unexplained` and `vanished` rise together.

`med` (median per-pixel difference after re-rendering at the located scale) is
used first, as a location gate: it is ~0 for a correct location no matter how the
strokes were rasterised, and large when the region is wrong.

Usage
-----
  python check_image_ghosts.py --html deliverable.html --pdf source.pdf
  python check_image_ghosts.py --html D.html --pdf S.pdf --out OUTDIR
  python check_image_ghosts.py --html D.html --pdf S.pdf --out OUTDIR --evidence all

Exit status is 1 when at least one ghost was found (`--no-fail` to only report),
so it can be used as a gate in a pipeline.

Read-only: neither the HTML nor the PDF is ever modified.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys

import cv2
import numpy as np
import pymupdf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- constants

DISCOVER_DPI = 150          # the scale the multi-scale search works at
# Scale factors tried: embedded-image pixels per pixel of a DISCOVER_DPI render.
# 1.0 = 150 dpi, 0.5 = 300 dpi, 0.25 = 600 dpi, 2.0 = 75 dpi, ...
SCALES = (1.0, 2.0, 1.5, 4 / 3, 1.25, 2.5, 3.0, 2 / 3, 0.5, 0.4, 1 / 3,
          0.25, 0.2, 0.125)

INK_DARK = 170              # "this pixel is ink"

GHOST_UNEXPLAINED = 0.02
GHOST_INK_RATIO = 1.03
GHOST_INK_RATIO_MAX = 1.8   # beyond this the located region is simply the wrong one
MIN_INK_PX = 200            # too little ink in the located region to conclude anything
LOCATION_MED = 2.0          # median difference above this = location not found
LOCATION_IOU = 0.30         # ink-mask IoU below this = location not found

IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
SRC_RE = re.compile(r'src="data:image/(\w+);base64,([^"]+)"')
ALT_RE = re.compile(r'alt="([^"]*)"')
CV_LOAD = getattr(cv2, "IMREAD_UNCHANGED", -1)


# ---------------------------------------------------------------- HTML side

def html_images(path):
    """Every <img> of the file, in document order, base64 payloads decoded."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for i, m in enumerate(IMG_RE.finditer(raw)):
        tag = m.group(0)
        alt = ALT_RE.search(tag)
        src = SRC_RE.search(tag)
        rec = {"idx": i, "alt": alt.group(1) if alt else "", "tag": tag,
               "span": (m.start(), m.end()), "img": None, "bytes": None}
        if src:
            data = base64.b64decode(src.group(2) + "=" * (-len(src.group(2)) % 4))
            arr = cv2.imdecode(np.frombuffer(data, np.uint8), CV_LOAD)
            if arr is not None:
                if arr.ndim == 2:
                    arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                elif arr.shape[2] == 4:
                    arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
                rec["img"], rec["bytes"] = arr, data
        out.append(rec)
    return out


# ---------------------------------------------------------------- PDF side

class Renders:
    """Renders of one source PDF, cached per page at DISCOVER_DPI."""

    def __init__(self, pdf_path, dpi=DISCOVER_DPI, max_pages=None):
        self.doc = pymupdf.open(pdf_path)
        self.dpi = dpi
        self.max_pages = max_pages or self.doc.page_count
        self._gray = {}

    def n_pages(self):
        return min(self.max_pages, self.doc.page_count)

    def gray(self, pno):
        if pno not in self._gray:
            pm = self.doc[pno].get_pixmap(dpi=self.dpi, colorspace=pymupdf.csGRAY)
            self._gray[pno] = np.frombuffer(pm.samples, np.uint8).reshape(pm.height,
                                                                          pm.width)
        return self._gray[pno]

    def region_bgr(self, pno, rect_pt, dpi):
        pm = self.doc[pno].get_pixmap(dpi=int(round(dpi)), clip=pymupdf.Rect(*rect_pt),
                                      colorspace=pymupdf.csRGB)
        arr = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, 3)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass


def locate(renders, tmpl_gray, f, pad=6):
    """Best (page, x, y, ncc) for `tmpl_gray` scaled by `f` against 150-dpi pages."""
    th, tw = tmpl_gray.shape
    w, h = max(8, int(round(tw * f))), max(8, int(round(th * f)))
    t = tmpl_gray if abs(f - 1.0) < 1e-9 else cv2.resize(tmpl_gray, (w, h),
                                                        interpolation=cv2.INTER_AREA)
    best = None
    for pno in range(renders.n_pages()):
        page = renders.gray(pno)
        if t.shape[0] >= page.shape[0] or t.shape[1] >= page.shape[1]:
            continue
        # coarse sweep on a quarter-size page, then refine on the full-size page
        small_p = cv2.resize(page, (max(1, page.shape[1] // 4),
                                    max(1, page.shape[0] // 4)),
                             interpolation=cv2.INTER_AREA)
        small_t = cv2.resize(t, (max(1, w // 4), max(1, h // 4)),
                             interpolation=cv2.INTER_AREA)
        if (small_t.shape[0] < small_p.shape[0] and small_t.shape[1] < small_p.shape[1]):
            r = cv2.matchTemplate(small_p, small_t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
        else:
            mx, loc = -1.0, (0, 0)
        xa, ya = max(0, loc[0] * 4 - pad), max(0, loc[1] * 4 - pad)
        xb = min(page.shape[1], loc[0] * 4 + w + pad)
        yb = min(page.shape[0], loc[1] * 4 + h + pad)
        win = page[ya:yb, xa:xb]
        if win.shape[0] <= h or win.shape[1] <= w:
            continue
        r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _, mx2, _, loc2 = cv2.minMaxLoc(r)
        if best is None or mx2 > best["ncc"]:
            best = {"page": pno, "x": xa + loc2[0], "y": ya + loc2[1], "ncc": float(mx2)}
    return best


def rect_from_match(x, y, f, size_wh):
    """Pixel box at DISCOVER_DPI -> PDF points, for an image of `size_wh` pixels."""
    W, H = size_wh
    x0, y0 = x * 72.0 / DISCOVER_DPI, y * 72.0 / DISCOVER_DPI
    return [x0, y0, x0 + W * f * 72.0 / DISCOVER_DPI,
            y0 + H * f * 72.0 / DISCOVER_DPI]


def fresh_crop(renders, page, x, y, f, size_wh):
    """The same region, re-rendered at exactly the embedded image's pixel size."""
    W, H = size_wh
    arr = renders.region_bgr(page, rect_from_match(x, y, f, size_wh), DISCOVER_DPI / f)
    if (arr.shape[1], arr.shape[0]) != (W, H):
        arr = cv2.resize(arr, (W, H), interpolation=cv2.INTER_LANCZOS4)
    return arr


# ---------------------------------------------------------------- metrics

def ink_stats(asset_gray, clean_gray, dilate=2, ink=INK_DARK):
    if asset_gray.shape != clean_gray.shape:
        clean_gray = cv2.resize(clean_gray, (asset_gray.shape[1], asset_gray.shape[0]),
                                interpolation=cv2.INTER_LANCZOS4)
    ma = (asset_gray < ink).astype(np.uint8)
    mc = (clean_gray < ink).astype(np.uint8)
    k = np.ones((2 * dilate + 1, 2 * dilate + 1), np.uint8)
    near_c, near_a = cv2.dilate(mc, k), cv2.dilate(ma, k)
    unexp = int(((ma == 1) & (near_c == 0)).sum())
    van = int(((mc == 1) & (near_a == 0)).sum())
    ia, ic = int(ma.sum()), int(mc.sum())
    d = np.abs(asset_gray.astype(np.int16) - clean_gray.astype(np.int16))
    inter, union = int((ma & mc).sum()), int((ma | mc).sum())
    return {"ink_asset": ia, "ink_clean": ic, "ink_ratio": round(ia / max(ic, 1), 4),
            "unexplained": unexp, "unexplained_rel": round(unexp / max(ic, 1), 4),
            "vanished": van, "vanished_rel": round(van / max(ia, 1), 4),
            "ink_iou": round(inter / union, 4) if union else 1.0,
            "mad": round(float(d.mean()), 3), "med": float(np.median(d))}


def analyse(renders, item, scales=SCALES):
    """Locate one embedded image in the source PDF; return its metrics or None.

    The scale is chosen by the median pixel difference of the reconstructed crop,
    not by the correlation coefficient: correlation is not comparable across
    scales (a blurred template correlates well with any light background), while
    the median difference is ~0 exactly at the physically correct scale.
    """
    g = cv2.cvtColor(item["img"], cv2.COLOR_BGR2GRAY)
    size = (g.shape[1], g.shape[0])
    best = None
    for f in scales:
        loc = locate(renders, g, f)
        if not loc:
            continue
        try:
            clean = fresh_crop(renders, loc["page"], loc["x"], loc["y"], f, size)
        except Exception:
            continue
        st = ink_stats(g, cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY))
        st.update({"page": loc["page"], "x": loc["x"], "y": loc["y"], "f": f,
                   "ncc": round(loc["ncc"], 4), "size": list(size),
                   "clean": clean, "asset": item["img"]})
        if best is None or (st["med"], st["mad"]) < (best["med"], best["mad"]):
            best = st
    return best


def classify(st):
    if st is None:
        return "not-found", "no region of the source PDF matched this image"
    if (st["med"] > LOCATION_MED or st["ink_iou"] < LOCATION_IOU
            or st["ink_clean"] < MIN_INK_PX):
        return "unverified", "location unreliable (med %.2f, ink IoU %.2f)" % (
            st["med"], st["ink_iou"])
    if (st["unexplained_rel"] >= GHOST_UNEXPLAINED
            and st["vanished_rel"] <= st["unexplained_rel"] / 3
            and GHOST_INK_RATIO <= st["ink_ratio"] <= GHOST_INK_RATIO_MAX):
        return "ghost", ("the crop carries %.1f%% more ink than the source page, and %s"
                         " of it lands on paper — a second, offset copy of the strokes"
                         % ((st["ink_ratio"] - 1) * 100,
                            "%.1f%%" % (st["unexplained_rel"] * 100)))
    return "clean", ""


# ---------------------------------------------------------------- evidence

def write_evidence(path, st):
    """embedded | fresh crop | overlay: red = PDF ink the crop lost, blue = ink it added."""
    g = cv2.cvtColor(st["asset"], cv2.COLOR_BGR2GRAY)
    cg = cv2.cvtColor(st["clean"], cv2.COLOR_BGR2GRAY)
    ma, mc = (g < INK_DARK), (cg < INK_DARK)
    over = np.full((g.shape[0], g.shape[1], 3), 255, np.uint8)
    over[mc & ~ma] = (0, 0, 255)
    over[ma & ~mc] = (255, 0, 0)
    over[ma & mc] = (200, 200, 200)
    cv2.imwrite(path, np.hstack([cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), st["clean"], over]))


# ---------------------------------------------------------------- driver

def run(html, pdf, out=None, scales=SCALES, quiet=False, no_fail=False,
        evidence="ghost"):
    imgs = html_images(html)
    renders = Renders(pdf)
    rows, ghosts = [], []
    for it in imgs:
        if it["img"] is None:
            rows.append({"idx": it["idx"], "alt": it["alt"][:80], "class": "skip",
                         "why": "no data: URI"})
            continue
        st = analyse(renders, it, scales)
        cls, why = classify(st)
        row = {"idx": it["idx"], "alt": it["alt"][:80], "class": cls, "why": why}
        if st:
            row.update({k: st[k] for k in ("page", "x", "y", "f", "ncc", "size",
                                           "ink_asset", "ink_clean", "ink_ratio",
                                           "unexplained_rel", "vanished_rel",
                                           "ink_iou", "mad", "med")})
        rows.append(row)
        if cls == "ghost":
            ghosts.append(row)
        if out and st and (evidence == "all" or (evidence == "ghost" and cls == "ghost")):
            os.makedirs(out, exist_ok=True)
            write_evidence(os.path.join(out, "idx%03d_%s.png" % (it["idx"], cls)), st)
        if not quiet:
            print("  %-10s idx%-4d %-16s %s" % (cls, it["idx"],
                                                str(row.get("size", "-")),
                                                it["alt"][:44]), flush=True)
    renders.close()
    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    report = {"html": html, "pdf": pdf, "counts": counts, "images": rows}
    print("%s: %s" % (os.path.basename(html), counts))
    if out:
        os.makedirs(out, exist_ok=True)
        json.dump(report, open(os.path.join(out, "ghost_report.json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", os.path.join(out, "ghost_report.json"))
    if ghosts and not no_fail:
        print("GHOSTS FOUND: %d image(s) — re-crop them from the source PDF at 2x "
              "pixels and pin the display width to the old pixel count" % len(ghosts))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="find ghosted (double-painted) crops "
                                            "among a deliverable's embedded images")
    ap.add_argument("--html", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default=None, help="directory for the JSON report and evidence")
    ap.add_argument("--evidence", choices=("ghost", "all", "none"), default="ghost")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-fail", action="store_true",
                    help="always exit 0, even when ghosts are found")
    a = ap.parse_args()
    if not os.path.isfile(a.html) or not os.path.isfile(a.pdf):
        print("missing input", a.html, a.pdf)
        return 2
    return run(a.html, a.pdf, a.out, quiet=a.quiet, no_fail=a.no_fail,
               evidence=a.evidence)


if __name__ == "__main__":
    sys.exit(main())
