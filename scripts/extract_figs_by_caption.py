# -*- coding: utf-8 -*-
"""
extract_figs_by_caption.py — 按论文图注（Fig. N）定位并裁剪图片，生成 assets/figN.png。

用途:
    为译文准备插图。一张图的内容由它的图注定义，与 PDF 内嵌对象顺序无关，
    因此本脚本以图注为锚点反向裁剪图注上方区域，避免图片与图号错位。

用法:
  python extract_figs_by_caption.py paper.pdf --list                  # 只列出图注（页/栏/y/文本）
  python extract_figs_by_caption.py paper.pdf -o out_dir              # 自动裁剪全部图 -> out_dir/figN.png
  python extract_figs_by_caption.py paper.pdf -o out_dir --dpi 300 --col-x 300 --pad 20

原理（关键）:
  - 每张图 = 同栏内"上一条图注底部 → 本条图注顶部"区间里的全部图像块；
  - 若区间内无图像块（矢量图），裁剪整个区间区域；
  - 自动裁剪后必须逐张用 Read 目视核对（内容与图注语义一致、无裁切），
    不合适时用 --crop/手工 fitz 微调重裁。

依赖: PyMuPDF (fitz) —— python -m pip install pymupdf
"""
import argparse
import os
import re


def list_captions(doc, col_x=300):
    caps = []
    for pno in range(doc.page_count):
        page = doc[pno]
        d = page.get_text("dict")
        for blk in d["blocks"]:
            if blk.get("type") != 0:
                continue
            lines = blk.get("lines", [])
            if not lines:
                continue
            first = "".join(s["text"] for s in lines[0]["spans"])
            # 图注特征：首行 'Fig. N.' 带句点（正文引用是 'Fig. N shows...' 无句点）
            m = re.match(r"Fig(?:ure)?\.?\s*(\d+)[.:]\s*", first.strip())
            if not m:
                continue
            if len(lines) > 6:
                continue
            num = int(m.group(1))
            x0, y0, x1, y1 = blk["bbox"]
            col = "L" if x0 < col_x else "R"
            txt = " ".join("".join(s["text"] for s in ln["spans"]).strip() for ln in lines)
            caps.append({"page": pno, "num": num, "col": col,
                         "x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": txt})
    caps.sort(key=lambda c: (c["page"], c["col"], c["y0"]))
    return caps


def _blocks(page):
    d = page.get_text("dict")
    imgs = []
    texts = []
    for blk in d["blocks"]:
        if blk.get("type") == 1:
            imgs.append(blk["bbox"])
        else:
            lines = blk.get("lines", [])
            if not lines:
                continue
            t = "".join(s["text"] for s in lines[0]["spans"]).strip()
            if t.startswith("Fig."):
                continue  # 图注/正文引用不作上边界
            texts.append(blk["bbox"])
    return imgs, texts


def crop_region(doc, cap, prev_y1, col_x=300, pad=6, dpi=300):
    """返回 (rect, 命中图像块?) —— 图注区间 [prev_y1, cap.y0] 内的区域"""
    page = doc[cap["page"]]
    imgs, texts = _blocks(page)
    if cap["col"] == "L":
        lx0, lx1 = 0, col_x
    else:
        lx0, lx1 = col_x, page.rect.width
    top0 = max(prev_y1 or 40.0, 40.0)
    cap_top = cap["y0"]
    same_col = [b for b in imgs if b[0] >= lx0 - 30 and b[2] <= lx1 + 30]
    # 区间内的图像块（底边在区间底之下、顶边在区间顶之上）
    in_zone = [b for b in same_col if b[1] >= top0 - 60 and b[3] <= cap_top + 20]
    if in_zone:
        b = [min(x[0] for x in in_zone), min(x[1] for x in in_zone),
             max(x[2] for x in in_zone), max(x[3] for x in in_zone)]
        # 组合图（矢量曲线+小块照片嵌入）时图像块覆盖不全 -> 退回区域裁剪
        if b[2] - b[0] >= (lx1 - lx0) * 0.55:
            return (b[0] - pad, b[1] - pad, b[2] + pad, cap_top - pad), True
    # 矢量图/组合图：整个区间区域（顶部=上一图注底边，避免夹带图注残字）
    return (lx0 + pad, top0, lx1 - pad, cap_top - pad), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-o", "--out", default="assets")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--col-x", type=float, default=300, help="两栏分界 x（pt），默认 300")
    ap.add_argument("--pad", type=float, default=6)
    args = ap.parse_args()

    import fitz
    doc = fitz.open(args.pdf)
    caps = list_captions(doc, args.col_x)
    if args.list:
        for c in caps:
            print(f"p{c['page']+1:02d} {c['col']} y={c['y0']:.0f} Fig.{c['num']}: {c['text'][:80]}")
        print("total:", len(caps))
        return
    os.makedirs(args.out, exist_ok=True)
    seen = {}
    for c in caps:
        key = (c["page"], c["col"])
        prev = seen.get(key)  # 上一条图注的底部 y
        rect, has_img = crop_region(doc, c, prev, args.col_x, args.pad, args.dpi)
        pix = doc[c["page"]].get_pixmap(dpi=args.dpi, clip=fitz.Rect(*rect))
        fn = os.path.join(args.out, f"fig{c['num']}.png")
        pix.save(fn)
        tag = "img" if has_img else "area"
        print(f"Fig.{c['num']} <- p{c['page']+1:02d} ({c['col']}) {tag} {pix.width}x{pix.height} {fn}")
        seen[key] = c["y1"]
    doc.close()


if __name__ == "__main__":
    main()