# -*- coding: utf-8 -*-
"""
check_source_leaks.py — 交付件源码级复查：把"读者实际会看到什么"逐项判死。

解决的问题：译文正文正确、公式也重建了，但交付的 HTML 里仍有一批**读者可见的源代码**，
或渲染器根本没接手的公式。这类问题在 Markdown 阶段查不出来，必须查最终 HTML。

检查项（任一不为零即报错）：
  1. leftover_latex     可见文本里仍是原始 LaTeX 的反斜杠命令
  2. leftover_dollar    可见文本里残留的 `$`（公式没渲染 / 定界符配对失败）
  3. leftover_paren     可见文本里的 `\\(` `\\)`（该页渲染器未配置这对定界符）
  4. md_residue         可见文本里的 Markdown 残留：`**粗体**`、`_斜体_`、段首 `> `
  5. katex_errors       KaTeX 解析失败回退块（`class="katex-error"`，读者看到红色源码）
  6. dup_image_bytes    同一张图被两个不同标签引用（图注错位；组合图没拆）
  7. external_refs      外链 script/link/url(http)（自包含被破坏）
  8. broken_images      图片解码失败或非 data: 内嵌

**关键**：判"是否渲染"时，只把该页自己配置的定界符算作已渲染。很多页面把
`renderMathInElement` 的 delimiters 写成只有 `$$` 与 `$`，此时 `\\(...\\)` 不会被处理，
但肉眼看上去"公式源码在那儿、应该会渲染"——正是最常见的假阴性。

用法:
    python check_source_leaks.py out.html
    python check_source_leaks.py --dir out/            # 递归检查目录下所有 html
    python check_source_leaks.py --dir out/ --json r.json
    python check_source_leaks.py --no-dupe-scan out.html   # 跳过图片字节扫描（大文件提速）

退出码: 0 = 全部通过；1 = 有文件不合格
依赖: 仅标准库
"""
import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
from html.parser import HTMLParser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKIP_TAGS = {"script", "style", "pre", "code"}

# 页面上会真正渲染的定界符，取自其 renderMathInElement 配置；取不到则视为"什么都不渲染"
DELIM_RX = {
    "$$": re.compile(r"\$\$.*?\$\$", re.S),
    "$": re.compile(r"\$[^$\n]*?\$"),
    "\\(": re.compile(r"\\\(.*?\\\)", re.S),
    "\\[": re.compile(r"\\\[.*?\\\]", re.S),
    "\\begin{equation}": re.compile(r"\\begin\{equation\}.*?\\end\{equation\}", re.S),
    "\\begin{align}": re.compile(r"\\begin\{align\}.*?\\end\{align\}", re.S),
}
LATEX_ANY = re.compile(r"\\[A-Za-z]{2,}|\\[^A-Za-z\s]")
MD_BOLD = re.compile(r"\*\*[^*\n]{1,80}\*\*")
MD_ITAL = re.compile(r"(?<![\w\\])_(摘要|索引词|∗|[\u4e00-\u9fff]{1,20})_(?![\w])")
MD_QUOTE = re.compile(r"^>\s", re.M)


class VisibleText(HTMLParser):
    """收集"读者可见"的文本：跳过 script/style/pre/code 与 KaTeX 渲染子树。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.chunks = []

    def _skip(self):
        for tag, classes in self.stack:
            if tag in SKIP_TAGS:
                return True
            if any(c.startswith("katex") for c in classes):
                return True
        return False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.stack.append((tag, (d.get("class") or "").split()))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip() and not self._skip():
            self.chunks.append(data)


def configured_delims(html):
    """该页 renderMathInElement 真正配置的定界符集合；无配置返回空集。"""
    for call in re.findall(r"renderMathInElement\s*\(([^;]{0,900})", html, re.S):
        m = re.search(r"delimiters\s*:\s*\[(.*?)\]", call, re.S)
        if m:
            lefts = re.findall(r"left\s*:\s*['\"]((?:\\\\)?[^'\"]*)['\"]", m.group(1))
            # HTML 源码里是 JS 转义形式（\\(），还原成 JS 字符串
            return {x.replace("\\\\", "\\") for x in lefts}
    return set()


def image_dims(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9,
                          0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", w, h
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
            else:
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return "jpeg", 0, 0
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", w, h
    return "?", 0, 0


def check_file(path, dupe_scan=True):
    html = open(path, encoding="utf-8", errors="replace").read()
    body = html[html.find("<body>"):] if "<body>" in html else html
    body_ns = re.sub(r"<script.*?</script>", "", body, flags=re.S)

    parser = VisibleText()
    parser.feed(html)
    text = "".join(parser.chunks)

    delims = configured_delims(html)
    masked = text
    for d, rx in DELIM_RX.items():
        if d in delims:
            masked = rx.sub(lambda m: " " * len(m.group(0)), masked)

    res = {
        "file": path,
        "configured_delims": sorted(x.replace("\\", "") for x in delims),
        "leftover_latex": [m.group(0) for m in LATEX_ANY.finditer(masked)],
        "leftover_dollar": len(re.findall(r"\$", masked)),
        "leftover_paren": len(re.findall(r"\\\(|\\\)", masked)),
        "md_residue": (MD_BOLD.findall(masked) + MD_ITAL.findall(masked)
                       + MD_QUOTE.findall(masked)),
        "external_refs": [s for s in re.findall(
            r'<(?:script|link)[^>]*?(?:src|href)="([^"]*)"', html)
            if s.startswith(("http", "//"))]
            + re.findall(r"url\(\s*['\"]?(?:https?:)?//", html),
    }

    markup = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    markup = re.sub(r"<script.*?</script>", "", markup, flags=re.S)
    res["katex_errors"] = len(re.findall(r'<span class="katex-error"', markup))

    imgs = re.findall(r'<img\b[^>]*?src="([^"]*)"', body_ns)
    res["images"] = len(imgs)
    res["non_embedded_images"] = [s[:60] for s in imgs if not s.startswith("data:")]
    res["broken_images"] = 0
    by_sha = {}
    if dupe_scan:
        for i, m in enumerate(re.finditer(r"<img\b[^>]*?>", body_ns)):
            tag = m.group(0)
            src = (re.search(r'src="([^"]*)"', tag) or [None, ""])[1]
            alt = (re.search(r'alt="([^"]*)"', tag) or [None, ""])[1]
            if not src.startswith("data:image"):
                continue
            try:
                data = base64.b64decode(src.split(",", 1)[1] + "==")
            except Exception:
                res["broken_images"] += 1
                continue
            kind, w, h = image_dims(data)
            if kind == "?" or w == 0:
                res["broken_images"] += 1
            by_sha.setdefault(hashlib.sha256(data).hexdigest(), []).append((i, alt))
    res["dup_image_bytes"] = [{"sha": k[:12], "index_alt": v}
                              for k, v in by_sha.items()
                              if len(v) > 1 and len({a for _i, a in v}) > 1]
    res["ok"] = not (res["leftover_latex"] or res["leftover_dollar"]
                     or res["leftover_paren"] or res["md_residue"]
                     or res["katex_errors"] or res["dup_image_bytes"]
                     or res["external_refs"] or res["non_embedded_images"]
                     or res["broken_images"])
    return res


def main():
    ap = argparse.ArgumentParser(description="交付件源码级复查")
    ap.add_argument("html", nargs="*", help="待检查的 HTML")
    ap.add_argument("--dir", action="append", default=[], help="递归检查目录，可多次")
    ap.add_argument("--json", default="", help="把完整结果写成 JSON")
    ap.add_argument("--no-dupe-scan", action="store_true", help="跳过图片字节重复扫描")
    args = ap.parse_args()

    files = list(args.html)
    for d in args.dir:
        for root, _sub, names in os.walk(d):
            for n in sorted(names):
                if n.lower().endswith(".html"):
                    files.append(os.path.join(root, n))
    if not files:
        print("没有待检查文件")
        sys.exit(1)

    results, bad = [], 0
    for f in files:
        try:
            r = check_file(f, dupe_scan=not args.no_dupe_scan)
        except Exception as e:                                  # noqa: BLE001
            print(f"{os.path.basename(f)}: 读取失败 {e!r}")
            bad += 1
            continue
        results.append(r)
        name = os.path.basename(f)
        if r["ok"]:
            print(f"OK   {name}  (delims={r['configured_delims']} imgs={r['images']})")
            continue
        bad += 1
        print(f"FAIL {name}  (页内定界符={r['configured_delims']})")
        if r["leftover_latex"]:
            print(f"     ! 可见原始 LaTeX {len(r['leftover_latex'])} 处，"
                  f"例：{r['leftover_latex'][:6]}")
        if r["leftover_dollar"]:
            print(f"     ! 可见残留 $ {r['leftover_dollar']} 个")
        if r["leftover_paren"]:
            print(f"     ! 可见 \\( \\) {r['leftover_paren']} 处（该页未配置这对定界符）")
        if r["md_residue"]:
            print(f"     ! Markdown 残留 {len(r['md_residue'])} 处，"
                  f"例：{r['md_residue'][:4]}")
        if r["katex_errors"]:
            print(f"     ! KaTeX 解析失败回退 {r['katex_errors']} 处（读者看到红色源码）")
        if r["dup_image_bytes"]:
            print(f"     ! 同一张图被不同标签引用：{r['dup_image_bytes'][:3]}")
        if r["external_refs"]:
            print(f"     ! 外链：{r['external_refs'][:3]}")
        if r["non_embedded_images"]:
            print(f"     ! 非内嵌图片：{r['non_embedded_images'][:3]}")
        if r["broken_images"]:
            print(f"     ! 图片解码失败 {r['broken_images']} 张")

    if args.json:
        json.dump(results, open(args.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n结果已写入 {args.json}")
    print(f"\n检查 {len(files)} 个文件，{bad} 个不合格")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
