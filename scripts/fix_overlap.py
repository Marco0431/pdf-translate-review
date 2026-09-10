# -*- coding: utf-8 -*-
"""
fix_overlap.py — 给自包含 HTML 追加 CSS，修复"公式编号压到公式上"的重叠问题。

用途:
    部分 HTML 模板写了 `.katex-display > .katex { display: inline-block }`，公式容器
    收缩为内容宽度，导致右对齐的公式编号（.katex-tag）绝对定位压在公式上。本脚本在
    </style> 前追加一段覆盖规则，恢复 block 布局并把公式容器撑满整行。

用法:
    python fix_overlap.py out.html                  # 单个文件
    python fix_overlap.py out1.html out2.html       # 多个文件
    python fix_overlap.py --dir out/                # 目录（递归处理 *.html）

说明:
    幂等：已含修复标记的文件会跳过；改完可用 check_all_html.py 复查重叠数。

依赖: 无（Python 标准库）
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

MARKER = "公式编号防重叠修复"

FIX_CSS = """
/* === 公式编号防重叠修复 ===
   若模板里 ".katex-display > .katex" 是 inline-block，公式容器会收缩为内容宽度，
   右对齐的 .katex-tag 就会压到公式上。下面恢复标准 block 布局。 */
.katex-display > .katex { display: block !important; text-align: center; }
.katex-display > .katex > .katex-html { width: 100%; }
"""


def fix_html(path: str) -> bool:
    """追加修复 CSS；返回 True 表示本次写入，False 表示已修复/不适用。"""
    c = open(path, encoding="utf-8").read()
    if MARKER in c:
        return False  # 已修复
    if "</style>" not in c:
        return False
    c = c.replace("</style>", FIX_CSS + "</style>", 1)
    open(path, "w", encoding="utf-8").write(c)
    return True


def iter_html(paths, dirs):
    for p in paths:
        if not os.path.exists(p):
            print(f"[跳过] 不存在: {p}")
            continue
        yield p
    for d in dirs:
        if not os.path.isdir(d):
            print(f"[跳过] 不是目录: {d}")
            continue
        for dirpath, _sub, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith(".html"):
                    yield os.path.join(dirpath, f)


def main():
    ap = argparse.ArgumentParser(description="修复 HTML 公式编号与公式重叠（追加 CSS）")
    ap.add_argument("html", nargs="*", help="待修复的 HTML 文件")
    ap.add_argument("--dir", action="append", default=[], help="待修复的目录（递归），可多次")
    args = ap.parse_args()

    if not args.html and not args.dir:
        ap.print_help()
        sys.exit(1)

    fixed = []
    for p in iter_html(args.html, args.dir):
        if fix_html(p):
            fixed.append(p)
    print(f"已修复 {len(fixed)} 个文件:")
    for f in fixed:
        print(" -", f)


if __name__ == "__main__":
    main()
