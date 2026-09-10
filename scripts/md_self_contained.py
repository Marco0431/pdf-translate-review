# -*- coding: utf-8 -*-
"""
md_self_contained.py — 把翻译 Markdown 转成自包含版本（图片 base64 内嵌）。

用途:
    相对路径引用的图片一旦离开工作目录就会失效（例如把文档上传到附件存储、单独
    发给别人）。本工具把 `![alt](assets/xxx.png)` 全部替换成 data URI，产出单文件
    Markdown，放到任何位置图片都不丢。

用法:
    python md_self_contained.py translation.md              # 输出 translation_自包含.md
    python md_self_contained.py translation.md --out one_file.md

说明:
    - 只处理本地相对路径图片；已是 data:/http(s) 的引用保持不变；
    - 找不到的图片会打印警告并保留原引用，不会静默丢图。

依赖: 无（Python 标准库）
"""
import argparse
import base64
import mimetypes
import os
import re
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def inline_images(md_text: str, base_dir: str) -> str:
    def repl(m):
        alt = m.group(1)
        path = m.group(2)
        if re.match(r"^(https?:|data:)", path):
            return m.group(0)
        full = os.path.normpath(os.path.join(base_dir, path.replace("\\", "/")))
        if not os.path.exists(full):
            print(f"  ! 图片缺失: {path}")
            return m.group(0)
        with open(full, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        mime, _ = mimetypes.guess_type(full)
        mime = mime or "image/png"
        return f'![{alt}](data:{mime};base64,{b64})'

    # 匹配 ![alt](任意相对路径) 中的本地图片
    return re.sub(r"!\[([^\]]*)\]\(([^)]+\.(?:png|jpe?g|gif|svg))\)", repl, md_text)


def main():
    ap = argparse.ArgumentParser(description="把 Markdown 的图片引用内嵌为 base64，产出单文件")
    ap.add_argument("md", help="翻译 Markdown 路径")
    ap.add_argument("--out", default="", help="输出路径（默认 <原名>_自包含.md）")
    args = ap.parse_args()

    md = os.path.abspath(args.md)
    if not os.path.exists(md):
        print(f"错误: 文件不存在 {md}")
        sys.exit(1)

    base_dir = os.path.dirname(md)
    out = args.out or os.path.splitext(md)[0] + "_自包含.md"

    c = open(md, encoding="utf-8").read()
    c2 = inline_images(c, base_dir)
    open(out, "w", encoding="utf-8").write(c2)

    imgs = len(re.findall(r"data:image", c2))
    print(f"{os.path.basename(md)} -> {os.path.basename(out)}")
    print(f"  内嵌图片 {imgs} 张, 大小 {os.path.getsize(out) // 1024} KB")


if __name__ == "__main__":
    main()
