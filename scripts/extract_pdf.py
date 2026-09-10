# -*- coding: utf-8 -*-
"""
extract_pdf.py — 从学术 PDF 提取文本、页面渲染图与内嵌图片对象，建立翻译工作目录。

用途:
    翻译流程的第一步：把 PDF 拆成"可翻译的文本 + 可目视核对的页面图 + 原始图片对象"。
    注意 pymupdf4llm 提取的文本层对公式不可靠（常丢括号、丢上下标），
    因此 paper.md 只作为文字基准，公式结构必须回到 assets/raw/ 的页面渲染图逐字确认。

用法:
    python extract_pdf.py paper.pdf [--out out/] [--dpi 150]

输出:
    out/
      paper.md          # pymupdf4llm 提取的 Markdown 文本（公式可能丢失，仅作文本基准）
      assets/raw/       # 逐页渲染图 + PDF 内嵌图片对象（xxx.pdf-00NN-XX.png）
      meta/             # pages.json / figures.json / source.json

依赖:
    python -m pip install pymupdf pymupdf4llm
"""
import argparse
import json
import os
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="从学术 PDF 提取文本、页面渲染图与图片对象")
    ap.add_argument("pdf", help="论文 PDF 路径")
    ap.add_argument("--out", default="", help="输出目录（默认 <pdf名>_extracted）")
    ap.add_argument("--dpi", type=int, default=150, help="页面渲染 DPI（默认 150）")
    args = ap.parse_args()

    pdf = os.path.abspath(args.pdf)
    if not os.path.exists(pdf):
        print(f"错误: 文件不存在 {pdf}")
        sys.exit(1)

    base = os.path.splitext(os.path.basename(pdf))[0]
    out = args.out or os.path.join(os.path.dirname(pdf), base + "_extracted")
    raw = os.path.join(out, "assets", "raw")
    meta = os.path.join(out, "meta")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(meta, exist_ok=True)

    try:
        import pymupdf4llm
        import fitz
    except ImportError:
        print("需要安装依赖: python -m pip install pymupdf pymupdf4llm")
        sys.exit(1)

    print(f"提取 {pdf} -> {out}")

    # 1) 文本提取
    print("  [1/3] 提取文本 ...")
    md_text = pymupdf4llm.to_markdown(pdf)
    with open(os.path.join(out, "paper.md"), "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"        paper.md ({len(md_text)} chars)")

    # 2) 页面渲染 + 内嵌图片对象导出
    print("  [2/3] 渲染页面与图片 ...")
    doc = fitz.open(pdf)
    figures = []
    pages = []
    for pno in range(doc.page_count):
        page = doc[pno]
        pix = page.get_pixmap(matrix=fitz.Matrix(args.dpi / 72, args.dpi / 72))
        page_png = os.path.join(raw, f"{base}.pdf-{pno + 1:04d}.png")
        pix.save(page_png)
        pages.append({"page": pno + 1, "png": os.path.basename(page_png)})

        # 导出图片对象（插图/公式截图）；顺序不等于图注编号，仅作素材
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                w, h = img[2], img[3]
                pixmap = fitz.Pixmap(doc, xref)
                if pixmap.n > 4:
                    pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                if pixmap.width > 8 and pixmap.height > 8:
                    fname = f"{base}.pdf-{pno + 1:04d}-{xref:02d}.png"
                    pixmap.save(os.path.join(raw, fname))
                    figures.append({"page": pno + 1, "xref": xref,
                                    "png": fname, "w": w, "h": h})
                pixmap = None
            except Exception:
                pass
    doc.close()
    print(f"        页面 {len(pages)} 张, 图片对象 {len(figures)} 个")

    # 3) 元数据
    print("  [3/3] 保存元数据 ...")
    with open(os.path.join(meta, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=1)
    with open(os.path.join(meta, "figures.json"), "w", encoding="utf-8") as f:
        json.dump(figures, f, ensure_ascii=False, indent=1)
    with open(os.path.join(meta, "source.json"), "w", encoding="utf-8") as f:
        json.dump({"pdf": pdf, "dpi": args.dpi}, f, ensure_ascii=False, indent=1)

    print("完成。")
    print("提示: 图片请用 extract_figs_by_caption.py 按 Fig. 图注裁剪，"
          "公式结构请用 assets/raw/*.png 逐字核对。")


if __name__ == "__main__":
    main()
