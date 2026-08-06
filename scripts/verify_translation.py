#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_translation.py — 自动验证 PDF 翻译 Markdown 文档的完整性。

用法:
    python verify_translation.py <translation.md> [--max-eq N] [--assets-dir DIR] [--expect-imgs N]

检查项:
    [1] 公式编号 1..N 齐全、无多余（基于 \tag{N}）
    [2] $$ 块级公式配对（行首 $$ 数量为偶数）
    [3] 行内 $ 数量为偶数（配对）
    [4] 无反斜杠括号 \\\\( 和 \\\\) 残留（Cursor/VS Code 预览不支持）
    [5] 关键章节存在
    [6] 图片引用与 assets 目录文件对应
    [7] 可选: 关键公式字符串存在性检查（--key 'pattern' 可多次传入）

退出码: 0 = 全部通过, 1 = 存在问题
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


def check_eq_numbers(c: str, max_eq: int) -> list:
    nums = set()
    for m in re.finditer(r"\\tag\{(\d+)\}", c):
        nums.add(int(m.group(1)))
    missing = [n for n in range(1, max_eq + 1) if n not in nums]
    extra = sorted(nums - set(range(1, max_eq + 1)))
    out = []
    if missing:
        out.append(f"[1] 缺失公式编号: {missing}")
    if extra:
        out.append(f"[1] 多余公式编号: {extra}")
    return out


def check_math_delimiters(c: str) -> list:
    out = []
    dl = [l for l in c.split("\n") if l.strip() == "$$"]
    if len(dl) % 2 != 0:
        out.append(f"[2] $$ 块级公式数量为奇数 ({len(dl)})，未配对")
    st = c.replace("$$", "")
    sc = st.count("$")
    if sc % 2 != 0:
        out.append(f"[3] 行内 $ 数量为奇数 ({sc})，未配对")
    leftover = c.count("\\(") + c.count("\\)")
    if leftover > 0:
        out.append(f"[4] 残留 \\( 或 \\) 共 {leftover} 处（应改为 $...$）")
    return out


def check_sections(c: str, sections: list) -> list:
    out = []
    for s in sections:
        if s not in c:
            out.append(f"[5] 缺失章节/段落: {s}")
    return out


def check_images(c: str, assets_dir: str, expect: int) -> list:
    out = []
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", c)
    if expect and len(refs) != expect:
        out.append(f"[6] 图片引用数 {len(refs)} != 期望 {expect}")
    if assets_dir and os.path.isdir(assets_dir):
        files = set(os.listdir(assets_dir))
        for ref in refs:
            base = os.path.basename(ref)
            if base not in files:
                out.append(f"[6] 引用的图片不存在: {base}")
        # 反向: assets 中未被引用的文件
        used = {os.path.basename(r) for r in refs}
        for f in sorted(files):
            if f not in used and f.lower().endswith(".png"):
                out.append(f"[6] assets 中未引用的图片: {f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", help="翻译文档路径")
    ap.add_argument("--max-eq", type=int, default=0, help="期望的最大公式编号（如 38）")
    ap.add_argument("--assets-dir", default="", help="图片资源目录")
    ap.add_argument("--expect-imgs", type=int, default=0, help="期望图片数")
    ap.add_argument("--section", action="append", default=[], help="必须存在的章节文本，可多次")
    ap.add_argument("--key", action="append", default=[], help="必须存在的关键公式字符串，可多次")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        print(f"错误: 文件不存在 {args.md}")
        sys.exit(1)

    c = open(args.md, encoding="utf-8").read()
    issues = []

    if args.max_eq:
        issues += check_eq_numbers(c, args.max_eq)
    issues += check_math_delimiters(c)
    if args.section:
        issues += check_sections(c, args.section)
    if args.assets_dir or args.expect_imgs:
        issues += check_images(c, args.assets_dir, args.expect_imgs)
    for k in args.key:
        if k not in c:
            issues.append(f"[7] 关键公式缺失: {k[:80]}")

    if issues:
        print("发现以下问题:")
        for i in issues:
            print("  -", i)
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
