# -*- coding: utf-8 -*-
"""
sync_zotero.py — 把修好的自包含 HTML 覆盖到 Zotero 附件存储目录。

用途:
    HTML 在外部工作目录里修好后，需要覆盖回 Zotero 的附件存储，Zotero 里打开的才是
    最新版。本脚本负责这次覆盖，并保留目标目录里原有的附件文件名。

用法:
    # 方式一：直接指定目标目录（Zotero 附件存储目录，或任意存放 HTML 的目录）
    python sync_zotero.py out.html --target-dir "<ZOTERO_STORAGE>/<ATTACHMENT_KEY>"

    # 方式二：给出 Zotero storage 根目录 + 附件 key，脚本拼出目标目录
    python sync_zotero.py out.html --zotero-storage "<ZOTERO_STORAGE>" --key <ATTACHMENT_KEY>

说明:
    - 目标目录里已有 .html 附件时，逐个覆盖（保持原文件名）；
    - 目标目录里没有 .html 时，按源文件名复制进去；
    - 目标目录不存在会报错退出，不会创建（避免 key 写错时静默建错目录）；
    - 本脚本不联网、不访问 Zotero API，只做本地文件覆盖。

依赖: 无（Python 标准库）
"""
import argparse
import os
import re
import shutil
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def resolve_target(args) -> str:
    if args.target_dir:
        return os.path.abspath(args.target_dir)
    if not args.zotero_storage or not args.key:
        print("错误: 需要 --target-dir，或同时给出 --zotero-storage 与 --key")
        sys.exit(1)
    if not re.fullmatch(r"[A-Za-z0-9]{8}", args.key):
        print("错误: 附件 key 应为 8 位字母数字（Zotero 附件目录名）")
        sys.exit(1)
    return os.path.join(os.path.abspath(args.zotero_storage), args.key.upper())


def main():
    ap = argparse.ArgumentParser(description="把自包含 HTML 覆盖到 Zotero 附件存储目录")
    ap.add_argument("html", help="修复后的 HTML 文件")
    ap.add_argument("--target-dir", default="", help="目标目录（最高优先级）")
    ap.add_argument("--zotero-storage", default="", help="Zotero storage 根目录")
    ap.add_argument("--key", default="", help="Zotero 附件 key（storage 下的 8 位目录名）")
    args = ap.parse_args()

    src = os.path.abspath(args.html)
    if not os.path.exists(src):
        print(f"错误: 源文件不存在 {src}")
        sys.exit(1)
    target = resolve_target(args)
    if not os.path.isdir(target):
        print(f"错误: 目标目录不存在 {target}")
        sys.exit(1)

    htmls = [f for f in os.listdir(target) if f.lower().endswith(".html")]
    if htmls:
        for fn in htmls:
            dst = os.path.join(target, fn)
            shutil.copyfile(src, dst)
            print(f"[已同步] {fn} ({os.path.getsize(dst) // 1024} KB)")
    else:
        dst = os.path.join(target, os.path.basename(src))
        shutil.copyfile(src, dst)
        print(f"[已复制] {os.path.basename(src)} ({os.path.getsize(dst) // 1024} KB)")
        print("提示: 目标目录里没有 .html 附件，已按源文件名复制；"
              "请确认这就是 Zotero 中该附件对应的目录。")


if __name__ == "__main__":
    main()
