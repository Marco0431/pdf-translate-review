# -*- coding: utf-8 -*-
"""
build_html.py — 一键把翻译 Markdown 构建成"离线自包含 HTML"（含编号防重叠后处理）。

用途:
    HTML 流水线的总入口，等价于依次执行:
      1) node md_to_offline_html.js <md> <out>   # KaTeX 预渲染 + 字体/图片 base64 内嵌
      2) fix_overlap.py <out>                    # 补"公式编号防重叠"CSS
      3) fix_wide.py <out>                       # 注入"超宽公式自适应缩放"脚本
    得到不依赖外网、不依赖 JS 渲染公式、离线可读的单文件 HTML。

用法:
    python build_html.py translation.md out.html
    python build_html.py translation.md out.html --no-post-fix   # 只要纯渲染结果

依赖:
    Node.js + 在仓库根目录执行过 npm install（katex / markdown-it / markdown-it-texmath）
"""
import argparse
import os
import subprocess
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fix_overlap import fix_html as fix_overlap_html  # noqa: E402
from fix_wide import inject as fix_wide_inject        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="翻译 Markdown -> 离线自包含 HTML")
    ap.add_argument("md", help="翻译 Markdown 路径")
    ap.add_argument("out", help="输出 HTML 路径")
    ap.add_argument("--no-post-fix", action="store_true",
                    help="不追加编号防重叠 CSS / 超宽公式缩放脚本")
    args = ap.parse_args()

    md = os.path.abspath(args.md)
    out = os.path.abspath(args.out)
    if not os.path.exists(md):
        print(f"错误: 文件不存在 {md}")
        sys.exit(1)

    renderer = os.path.join(HERE, "md_to_offline_html.js")
    if not os.path.exists(renderer):
        print(f"错误: 缺少渲染脚本 {renderer}")
        sys.exit(1)

    print("[1/3] 渲染 Markdown -> 自包含 HTML ...")
    r = subprocess.run(["node", renderer, md, out], text=True,
                       capture_output=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout or "")
    if r.returncode != 0:
        print("渲染失败:", (r.stderr or "").strip()[:500])
        print("提示: 先在仓库根目录执行 npm install")
        sys.exit(1)

    if args.no_post_fix:
        print(f"[完成] {out}")
        return

    print("[2/3] 追加公式编号防重叠 CSS ...")
    print("      已修复" if fix_overlap_html(out) else "      无需修复（已存在）")
    print("[3/3] 注入超宽公式自适应缩放脚本 ...")
    print("      已注入" if fix_wide_inject(out) else "      无需注入（已存在）")

    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"[完成] {out}  ({size_mb:.1f} MB)")
    print("建议: python check_all_html.py " + os.path.basename(out) + "   # 全量复查")


if __name__ == "__main__":
    main()
