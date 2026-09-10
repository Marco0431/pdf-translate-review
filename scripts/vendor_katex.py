# -*- coding: utf-8 -*-
"""
vendor_katex.py — 把 KaTeX（与 markdown-it）的离线资源复制到指定目录，供自包含页面引用。

用途:
    给"需要本地静态资源"的场景（浏览器插件、离线模板、内部网页）准备 vendor 目录：
    复制 KaTeX 的 JS/CSS 与全部 woff2 字体，以及 markdown-it 的 UMD 浏览器版。
    字体齐全时页面公式与排版才能完全离线显示。

用法:
    python vendor_katex.py --out vendor/
    python vendor_katex.py --out vendor/ --katex-dir node_modules/katex/dist
    python vendor_katex.py --out vendor/ --markdown-it node_modules/markdown-it/dist/browser/markdown-it.umd.min.js

说明:
    - 未指定 --katex-dir 时，从 cwd 与脚本所在目录向上查找 node_modules/katex/dist；
    - markdown-it 为可选资源，找不到会跳过并提示；
    - 完成后打印各类资源大小，便于确认复制完整。

依赖: 先执行 npm install katex markdown-it（或自备 dist 目录）
"""
import argparse
import os
import shutil
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def find_katex_dist() -> str:
    """从 cwd 与脚本目录向上查找 node_modules/katex/dist。"""
    starts = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    seen = set()
    for start in starts:
        cur = start
        for _ in range(8):
            cand = os.path.join(cur, "node_modules", "katex", "dist")
            if cand not in seen:
                seen.add(cand)
                if os.path.isfile(os.path.join(cand, "katex.min.js")):
                    return cand
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return ""


def find_markdown_it() -> str:
    """从 cwd 与脚本目录向上查找 markdown-it 的 UMD 浏览器版。"""
    rel = os.path.join("node_modules", "markdown-it", "dist", "browser",
                       "markdown-it.umd.min.js")
    starts = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for start in starts:
        cur = start
        for _ in range(8):
            cand = os.path.join(cur, rel)
            if os.path.isfile(cand):
                return cand
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return ""


def main():
    ap = argparse.ArgumentParser(description="复制 KaTeX/markdown-it 离线资源到 vendor 目录")
    ap.add_argument("--out", required=True, help="输出目录（vendor 目录）")
    ap.add_argument("--katex-dir", default="", help="katex/dist 目录（默认自动查找 node_modules）")
    ap.add_argument("--markdown-it", default="", help="markdown-it UMD 文件（默认自动查找）")
    args = ap.parse_args()

    katex_dir = args.katex_dir or find_katex_dist()
    if not katex_dir or not os.path.isdir(katex_dir):
        print("错误: 未找到 katex/dist，请先 npm install katex 或用 --katex-dir 指定")
        sys.exit(1)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "katex", "fonts"), exist_ok=True)

    for fn in ("katex.min.js", "katex.min.css"):
        src = os.path.join(katex_dir, fn)
        if not os.path.exists(src):
            print(f"错误: 缺少 {src}")
            sys.exit(1)
        shutil.copyfile(src, os.path.join(out, "katex", fn))

    n = 0
    for f in sorted(os.listdir(os.path.join(katex_dir, "fonts"))):
        if f.endswith(".woff2"):
            shutil.copyfile(os.path.join(katex_dir, "fonts", f),
                            os.path.join(out, "katex", "fonts", f))
            n += 1

    mdi = args.markdown_it or find_markdown_it()
    if mdi and os.path.exists(mdi):
        shutil.copyfile(mdi, os.path.join(out, "markdown-it.min.js"))
        print("markdown-it:", os.path.getsize(os.path.join(out, "markdown-it.min.js")))
    else:
        print("提示: 未找到 markdown-it UMD（可选），已跳过")

    total = 0
    for root, _dirs, files in os.walk(out):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print("copied fonts:", n, "| vendor total bytes:", total)
    print("katex js:", os.path.getsize(os.path.join(out, "katex", "katex.min.js")))
    print("katex css:", os.path.getsize(os.path.join(out, "katex", "katex.min.css")))


if __name__ == "__main__":
    main()
