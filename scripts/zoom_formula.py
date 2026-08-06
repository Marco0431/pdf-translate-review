#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zoom_formula.py — 公式核对辅助工具：提取公式行坐标 + 高清裁剪渲染。

文本层提取的公式常丢括号/下标，必须用渲染图逐字确认。本工具提供:

用法:
    # 1) 列出某页含关键符号的文本行及其坐标（判断公式结构）
    python zoom_formula.py paper.pdf --page 4 --list --kw "Emult" "eta" "rrob"

    # 2) 按页面比例裁剪并高清渲染（肉眼核对括号/上下标）
    python zoom_formula.py paper.pdf --page 4 --crop 0.02,0.30,0.55,0.35 --dpi 1200 --out eq12.png

    # 3) 按绝对坐标裁剪（--crop 用 PDF 点坐标）
    python zoom_formula.py paper.pdf --page 4 --crop-abs 40,318,300,328 --dpi 1600 --out eq.png

依赖: PyMuPDF (fitz)
"""
import argparse
import os
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def list_lines(page, keywords):
    """列出页面中包含任一关键词的文本行及 bbox 坐标。"""
    d = page.get_text("dict")
    rows = []
    for block in d["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            txt = "".join(s["text"] for s in line["spans"])
            if any(k.lower() in txt.lower() for k in keywords):
                x0, y0, x1, y1 = line["bbox"]
                rows.append((round(x0, 1), round(y0, 1), txt))
    rows.sort(key=lambda r: (r[1], r[0]))
    print(f"页面 {page.number + 1} 中匹配行 ({len(rows)}):")
    for x, y, t in rows:
        print(f"  x={x:7} y={y:7}  {t}")


def crop_render(page, crop, dpi, out):
    """按给定区域渲染高清图。"""
    import fitz

    if crop is None:
        clip = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    else:
        x0, y0, x1, y1 = crop
        clip = fitz.Rect(x0, y0, x1, y1)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    pix.save(out)
    print(f"已保存 {out} ({pix.width}x{pix.height}, dpi={dpi})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="PDF 路径")
    ap.add_argument("--page", type=int, required=True, help="页码（从 1 开始）")
    ap.add_argument("--list", action="store_true", help="列出匹配关键词的文本行")
    ap.add_argument("--kw", action="append", default=[], help="列表模式的关键词，可多次")
    ap.add_argument("--crop", type=str, default="", help="按页面比例裁剪: x0,y0,x1,y1（0~1）")
    ap.add_argument("--crop-abs", type=str, default="", help="按绝对点坐标裁剪: x0,y0,x1,y1")
    ap.add_argument("--dpi", type=int, default=1200, help="渲染 DPI")
    ap.add_argument("--out", default="formula_zoom.png", help="输出图片路径")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        print(f"错误: 文件不存在 {args.pdf}")
        sys.exit(1)

    import fitz

    doc = fitz.open(args.pdf)
    if args.page < 1 or args.page > doc.page_count:
        print(f"错误: 页码 {args.page} 超出范围 1..{doc.page_count}")
        sys.exit(1)
    page = doc[args.page - 1]

    if args.list:
        if not args.kw:
            print("列表模式需要 --kw 关键词")
            sys.exit(1)
        list_lines(page, args.kw)

    crop = None
    if args.crop_abs:
        vals = [float(v) for v in args.crop_abs.split(",")]
        if len(vals) != 4:
            print("错误: --crop-abs 需要 x0,y0,x1,y1 四个值")
            sys.exit(1)
        crop = vals
    elif args.crop:
        vals = [float(v) for v in args.crop.split(",")]
        if len(vals) != 4:
            print("错误: --crop 需要 x0,y0,x1,y1 四个值")
            sys.exit(1)
        x0, y0, x1, y1 = vals
        w, h = page.rect.width, page.rect.height
        crop = [x0 * w, y0 * h, x1 * w, y1 * h]

    if crop:
        crop_render(page, crop, args.dpi, args.out)
    elif not args.list:
        print("请提供 --list、--crop 或 --crop-abs 之一")

    doc.close()


if __name__ == "__main__":
    main()
