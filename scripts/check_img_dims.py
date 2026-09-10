# -*- coding: utf-8 -*-
"""
check_img_dims.py — 核对 HTML 内嵌 base64 图片的像素尺寸（直接解析 PNG 头）。

用途:
    内嵌 base64 之后，图片"看起来有没有"不再说明问题：需要确认每张图都被完整嵌入、
    尺寸合理（不是被误裁的小块、也不是漏掉正文大图）。本脚本按出现顺序打印每张
    内嵌 PNG 的宽高，并标出可疑项（过小、或与上一张完全同尺寸同字节数）。

用法:
    python check_img_dims.py out.html
    python check_img_dims.py out.html --min-width 300

依赖: 无（Python 标准库）
"""
import argparse
import base64
import os
import re
import struct
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def png_size(raw: bytes):
    """从 PNG 头解析 (width, height)；非 PNG 返回 None。"""
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", raw[16:24])


def main():
    ap = argparse.ArgumentParser(description="核对内嵌 base64 图片的尺寸")
    ap.add_argument("html", help="自包含 HTML 路径")
    ap.add_argument("--min-width", type=int, default=200,
                    help="小于该宽度视为可疑（默认 200）")
    args = ap.parse_args()

    if not os.path.exists(args.html):
        print(f"错误: 文件不存在 {args.html}")
        sys.exit(1)

    c = open(args.html, encoding="utf-8").read()
    imgs = re.findall(r'data:image/png;base64,([A-Za-z0-9+/=]+)', c)
    print("内嵌图片数:", len(imgs))

    warn = []
    sigs = {}
    for i, b64 in enumerate(imgs):
        raw = base64.b64decode(b64)
        size = png_size(raw)
        dim = f"{size[0]}x{size[1]}" if size else "非 PNG/无法解析"
        print(f"  img[{i + 1}]: {dim}  ({len(raw) / 1024:.1f} KB)")
        if not size:
            warn.append(f"img[{i + 1}] 不是可解析的 PNG")
        elif size[0] < args.min_width:
            warn.append(f"img[{i + 1}] 宽度仅 {size[0]}px，疑似误裁/缩略图")
        key = (size, len(raw)) if size else None
        if key:
            sigs.setdefault(key, []).append(i + 1)
    for key, where in sigs.items():
        if len(where) > 1:
            warn.append(f"尺寸与字节数完全相同: 第 {where} 张 {key[0][0]}x{key[0][1]}"
                        "（可能是同一张图被重复引用）")

    if warn:
        print("\n发现以下问题:")
        for w in warn:
            print("  -", w)
        sys.exit(1)
    print("\nOK: 所有内嵌图片尺寸正常")


if __name__ == "__main__":
    main()
