# -*- coding: utf-8 -*-
"""
ocr_formula.py — 公式/表格截图 OCR 辅助：放大后识别图片文字，供人工重建 LaTeX。

用途:
    当页面渲染图上的公式看不清、或文本层完全丢失时，用 OCR 得到"可能包含哪些字符"
    的线索。OCR 结果只作为提示，不能直接当作公式真值——上下标、括号范围、分数线
    必须回到高清渲染图人工确认。

用法:
    python ocr_formula.py eq12.png                 # 单张图片
    python ocr_formula.py crops/                   # 目录下全部 PNG
    python ocr_formula.py eq12.png --upscale 4     # 放大倍数（默认 3）

输出:
    每行公式片段与其置信度，按 y 坐标排序。

依赖:
    python -m pip install pillow rapidocr-onnxruntime
"""
import argparse
import io
import os
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ocr_png(path: str, upscale: int = 3) -> str:
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    img = Image.open(path).convert("RGB")
    if upscale > 1:
        w, h = img.size
        img = img.resize((w * upscale, h * upscale), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    result, _ = engine(buf.read())
    if not result:
        return "(无识别结果)"
    # result: [[box, text, score], ...]，按 y 坐标分档后排序
    result.sort(key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))
    return " | ".join(f"{text} ({score:.2f})" for _box, text, score in result)


def main():
    ap = argparse.ArgumentParser(description="公式截图 OCR（放大后识别，供人工重建 LaTeX）")
    ap.add_argument("path", help="图片路径或图片目录")
    ap.add_argument("--upscale", type=int, default=3, help="识别前放大倍数（默认 3）")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"错误: 路径不存在 {args.path}")
        sys.exit(1)

    if os.path.isdir(args.path):
        files = sorted(f for f in os.listdir(args.path) if f.lower().endswith(".png"))
        if not files:
            print("目录下没有 PNG 文件")
            sys.exit(1)
        for f in files:
            print(f"== {f} ==")
            print(ocr_png(os.path.join(args.path, f), args.upscale))
    else:
        print(ocr_png(args.path, args.upscale))


if __name__ == "__main__":
    main()
