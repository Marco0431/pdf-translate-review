# -*- coding: utf-8 -*-
"""
check_img_order.py — 检查 HTML 中"图片出现顺序"与"图注编号顺序"是否一致。

用途:
    图文错位的典型信号：图片顺序与图注编号顺序不一致、两条图注之间夹了 0 张或 2 张图、
    同一个图片源被两条不同图注引用（组合图没拆开）。本脚本解析 HTML body，输出
    图注编号序列与每条图注前出现的图片数，并给出告警。

用法:
    python check_img_order.py out.html
    python check_img_order.py out.html --expected 1,2,3,4,5      # 声明期望的图编号集合
    python check_img_order.py out.html --caption-regex "<strong>图\\s*(\\d+)"

输出:
    img 总数 / 图注编号序列 / 每条图注前图片数 / 重复图片源 与 编号跳跃或乱序告警。

依赖: 无（Python 标准库）
"""
import argparse
import os
import re
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_CAPTION_RE = r"<strong>图\s*(\d+)"


def main():
    ap = argparse.ArgumentParser(description="检查图片顺序与图注编号顺序是否一致")
    ap.add_argument("html", help="自包含 HTML 路径")
    ap.add_argument("--caption-regex", default=DEFAULT_CAPTION_RE,
                    help="图注编号正则（默认匹配 <strong>图 N）")
    ap.add_argument("--expected", default="",
                    help="期望的图编号集合，逗号分隔，如 1,2,3,4,5")
    args = ap.parse_args()

    if not os.path.exists(args.html):
        print(f"错误: 文件不存在 {args.html}")
        sys.exit(1)

    c = open(args.html, encoding="utf-8").read()
    body = c[c.find("<body>"):] if "<body>" in c else c

    imgs = re.findall(r"<img\b[^>]*?src=\"([^\"]*)\"", body, re.S)
    captions = re.findall(args.caption_regex, body)

    print(f"img 总数: {len(imgs)}")
    print(f"图注编号序列: {captions}")

    warn = []

    # 每条图注之前出现的图片数
    pos = 0
    counts = []
    for cap in captions:
        m = re.search(args.caption_regex, body[pos:])
        if not m:
            break
        idx = pos + m.start()
        n = len(re.findall(r"<img\b", body[pos:idx]))
        counts.append(f"图{cap}:{n}img")
        pos = idx + 1
    print("每条图注前图片数:", counts)
    for item in counts:
        if not item.endswith(":1img"):
            warn.append(f"图注 {item} 前不是恰好 1 张图（可能缺图或多图）")

    # 编号顺序
    nums = [int(x) for x in captions]
    if nums != sorted(nums):
        warn.append(f"图注编号不是递增顺序: {nums}")
    if len(set(nums)) != len(nums):
        dup = sorted({n for n in nums if nums.count(n) > 1})
        warn.append(f"图注编号重复: {dup}")

    # 重复图片源（同一张图被引用两次表示两幅不同图）
    seen = {}
    for i, src in enumerate(imgs):
        key = src if not src.startswith("data:") else src[:120] + f"#{len(src)}"
        seen.setdefault(key, []).append(i + 1)
    for key, where in seen.items():
        if len(where) > 1:
            warn.append(f"同一图片源被引用 {len(where)} 次（第 {where} 张）: {key[:60]}")

    # 与期望编号集合比对
    if args.expected:
        exp = [int(x) for x in args.expected.replace(" ", "").split(",") if x]
        missing = [n for n in exp if n not in nums]
        extra = [n for n in nums if n not in exp]
        if missing:
            warn.append(f"缺失图编号: {missing}")
        if extra:
            warn.append(f"多出图编号: {extra}")

    if warn:
        print("\n发现以下问题:")
        for w in warn:
            print("  -", w)
        sys.exit(1)
    print("\nOK: 图片顺序与图注编号一致")


if __name__ == "__main__":
    main()
