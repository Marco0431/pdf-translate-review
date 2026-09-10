#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_translation.py — 自动验证 PDF 翻译 Markdown 文档的完整性。

用途:
    交付前的结构兜底检查：确认公式编号无缺失、公式分隔符配对、括号与环境配对、
    图片引用与文件一一对应、关键章节与关键公式存在，并可选检测成段英文残留。

用法:
    python verify_translation.py <translation.md> [--max-eq N] [--assets-dir DIR] [--expect-imgs N]

检查项:
    [1] 公式编号 1..N 齐全、无多余、无异常重复（基于 \tag{N} / \text{(N)}）
    [2] $$ 块级公式配对（行首 $$ 数量为偶数）
    [3] 行内 $ 数量为偶数（配对）
    [4] 无反斜杠括号 \\\\( 和 \\\\) 残留（Cursor/VS Code 预览不支持）
    [5] 关键章节存在
    [6] 图片引用与 assets 目录文件对应
    [7] 可选: 关键公式字符串存在性检查（--key 'pattern' 可多次传入）
    [8] 每个公式块内 \\left/\\right 与环境配对（排除 \\rightarrow 误报）
    [9] 括号范围歧义提示（相邻括号组且第二组含减号，需人工确认；可 --no-ambiguity-check 关闭）
   [10] 可选: --check-english 检测成段英文原文残留

退出码: 0 = 全部通过, 1 = 存在问题

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


def check_eq_numbers(c: str, max_eq: int, allow_dup: list = None) -> list:
    # 支持三种编号写法: \tag{1a}（字母子式）、\text{(28a)}（cases 内编号）、\tag{28}
    allow_dup = allow_dup or []
    nums = set()
    tags = []
    for m in re.finditer(r"\\tag\{([^}]+)\}", c):
        tags.append(m.group(1))
        if m.group(1).isdigit():
            nums.add(int(m.group(1)))
    for m in re.finditer(r"\\text\{\((\d+)[a-z]?\)\}", c):
        nums.add(int(m.group(1)))
    missing = [n for n in range(1, max_eq + 1) if n not in nums]
    extra = sorted(nums - set(range(1, max_eq + 1)))
    out = []
    if missing:
        out.append(f"[1] 缺失公式编号: {missing}")
    if extra:
        out.append(f"[1] 多余公式编号: {extra}")
    # 同一编号出现 3 次以上视为异常（正文 + 附录各一次属正常；原文复合公式可用
    # --allow-dup 白名单放行，例如一个编号下含多行矩阵/方程组的编号）
    from collections import Counter
    dup = {k: v for k, v in Counter(tags).items() if v > 2 and k.isdigit()}
    for n in allow_dup:
        dup.pop(str(n), None)
    if dup:
        out.append(f"[1] 编号重复次数异常: {dup}")
    return out


def check_english(c: str) -> list:
    """[10] 检测成段英文原文残留（纯中文翻译文档不应出现整段英文正文）。"""
    out = []
    for mk in ["English original", "**English**"]:
        if mk in c:
            out.append(f"[10] 含英文原文标记: {mk}")
    for i, l in enumerate(c.split("\n")):
        s = l.strip()
        if not s:
            continue
        if s.startswith("$$") or s.startswith("![") or s.startswith("#") or s.startswith("|"):
            continue
        if s.startswith("`") or s.startswith("http"):
            continue
        if s.startswith("- [") or s.startswith("["):   # 参考文献列表 / 图片
            continue
        if s.startswith(">"):                          # 引用块（元信息 / 注释）
            continue
        if "\\" in s:                                  # LaTeX 命令行
            continue
        # 长且完全不含中日韩字符的正文行 = 疑似漏译的英文原文
        # （含中文的说明行、元信息行不算；参考文献/代码/公式行已在上面跳过）
        letters = sum(1 for ch in s if ch.isascii() and ch.isalpha())
        if letters > 60 and not re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", s):
            out.append(f"[10] 疑似英文原文 L{i + 1}: {s[:80]}")
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


def check_brackets(c: str, ambiguity: bool = True) -> list:
    """[8] 括号配对（块级，防 rightarrow 误报）+ [9] 括号范围歧义提示。"""
    out = []
    blocks = re.findall(r"\$\$(.+?)\$\$", c, re.S)
    for bi, b in enumerate(blocks):
        left = len(re.findall(r"\\left(?!arrow)", b))
        right = len(re.findall(r"\\right(?!arrow)", b))
        if left != right and (left > 0 or right > 0):
            out.append(f"[8] 公式块{bi}: \\left {left} vs \\right {right} :: {b[:80]}")
        for env in re.findall(r"\\begin\{(\w+)\}", b):
            if b.count(f"\\begin{{{env}}}") != b.count(f"\\end{{{env}}}"):
                out.append(f"[8] 公式块{bi}: 环境 {env} 不配对")
        # [9] 括号范围歧义提示：相邻两个括号组，且第二组内含减号。形如
        #     (I-a)b - ac 与 (I-a)(b-c) 的 LaTeX 语法都合法但语义不同，
        #     必须放大渲染图确认"减号两侧各被谁相乘"。此项只做提示，需人工判定。
        if not ambiguity:
            continue
        pats = [r"\\left\((.{1,80}?)\\right\)\s*\\left\((.{1,140}?)\\right\)",
                r"(?<!\\left)\(([^()]{1,80})\)\s*\(([^()]{1,140})\)"]
        for pat in pats:
            for m in re.finditer(pat, b, re.S):
                g2 = m.group(2)
                if not re.search(r"[-−]", g2):
                    continue
                if re.search(r"\\frac|\\begin\{", g2):
                    continue
                out.append(f"[9] 公式块{bi}: 相邻括号组且第二组含减号，"
                           f"需确认乘法作用范围 :: {m.group(0)[:80]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", help="翻译文档路径")
    ap.add_argument("--max-eq", type=int, default=0, help="期望的最大公式编号（如 38）")
    ap.add_argument("--assets-dir", default="", help="图片资源目录")
    ap.add_argument("--expect-imgs", type=int, default=0, help="期望图片数")
    ap.add_argument("--section", action="append", default=[], help="必须存在的章节文本，可多次")
    ap.add_argument("--key", action="append", default=[], help="必须存在的关键公式字符串，可多次")
    ap.add_argument("--check-english", action="store_true", help="检测成段英文原文残留")
    ap.add_argument("--no-ambiguity-check", action="store_true",
                    help="关闭 [9] 括号范围歧义提示（默认开启，可能对合法公式误报）")
    ap.add_argument("--allow-dup", action="append", default=[],
                    help="允许重复出现的编号（原文同一编号含多式），可多次")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        print(f"错误: 文件不存在 {args.md}")
        sys.exit(1)

    c = open(args.md, encoding="utf-8").read()
    issues = []

    if args.max_eq:
        issues += check_eq_numbers(c, args.max_eq, args.allow_dup)
    issues += check_math_delimiters(c)
    issues += check_brackets(c, ambiguity=not args.no_ambiguity_check)  # [8] 配对 + [9] 歧义提示
    if args.check_english:
        issues += check_english(c)
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
