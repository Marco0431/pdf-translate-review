# -*- coding: utf-8 -*-
"""
check_source_leaks.py — 交付件源码级复查：把"读者实际会看到什么"逐项判死。

解决的问题：译文正文正确、公式也重建了，但交付的 HTML 里仍有一批**读者可见的源代码**，
或渲染器根本没接手的公式。这类问题在 Markdown 阶段查不出来，必须查最终 HTML。

检查项（任一不为零即报错）：
  1. leftover_delim      该页自己配置的定界符没配成对（`$`、`\\(`、`\\[` 等）
  2. latex_in_prose      非数学文本里残留的 LaTeX 命令 / 转义符号（`\\frac`、`\\|`）
  3. doubled_backslash   **双反斜杠**：`\\\\bar`、`\\\\|`、`\\\\mathrm` 这类把单个反斜杠
                         写成了两个。矩阵/数组/cases 环境里 `\\\\` 是换行符，属正常，已排除
  4. prose_script        非数学文本里残留的 `_{…}` / `^{…}` 上下标
  5. delim_split_by_tag  定界符（或公式体）被行内标签切成两半——auto-render 只在**单个
                         文本节点内**匹配定界符，跨元素永远匹配不到
  6. span_malformed      数学 span 的花括号/圆括号/方括号不配对，或 `\\left` 没有 `\\right`
                         ——它不可能是完整公式，说明被截断了
  7. md_residue          可见文本里的 Markdown 残留：`**粗体**`、`_斜体_`、段首 `> `
  8. katex_errors        KaTeX 解析失败回退块（`class="katex-error"`，读者看到红色源码）
  9. dup_image_bytes     同一张图被两个不同标签引用（图注错位；组合图没拆）
 10. external_refs       外链 script/link/url(http)（自包含被破坏）
 11. broken_images       图片解码失败或非 data: 内嵌

**最重要的两条设计原则**（都是踩过的坑）：

* **没有报错 ≠ 渲染正确。** KaTeX 对 `$\\\\|\\\\bar{v}_L\\\\|$` 不报错——它照渲染，只是把
  `\\\\` 当成换行、把 `\\\\bar` 拆成字母 `bar`，于是范数变成单竖线、`\\bar` 变成字面量。
  所以检查器必须**读公式体本身**，不能只数报错数。
* **必须按该页自己的 `delimiters` 配置判"渲染了没有"。** 页面上写的是 `\\(…\\)` 而定界符
  只配了 `$` 时，浏览器不会处理它；反过来只有配置里有的定界符才算已渲染。

本脚本按**页面自带的 auto-render 算法**逐文本节点匹配定界符（与 KaTeX 的
`splitAtDelimiters` / `findEndOfMath` 等价，已用交付件内嵌的 auto-render bundle 逐节点
比对验证）。因此它能看见"标签把定界符切开""定界符没配成对"这两类跨节点问题——把可见文本
简单拼接、或把 `$…$` 整段遮掉的写法都看不见。

用法:
    python check_source_leaks.py out.html
    python check_source_leaks.py --dir out/            # 递归检查目录下所有 html
    python check_source_leaks.py --dir out/ --json r.json
    python check_source_leaks.py --no-dupe-scan out.html   # 跳过图片字节扫描（大文件提速）
    python check_source_leaks.py --selftest                # 跑内置回归样本后退出

改过本脚本之后，除了跑真实交付件，还要跑 `--selftest`：它把这两类缺陷的最小样本与几个
合法写法各跑一遍（坏的必须报错、好的必须通过）。**若坏样本也报通过，说明新检查项没生效。**

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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                            # noqa: BLE001
    pass

# --------------------------------------------------------------------------- #
# 读者可见视图
# --------------------------------------------------------------------------- #
# 这些标签的子树是"逐字文本"而不是正文：KaTeX auto-render 默认就忽略它们，
# 页面里写「（LaTeX 的 <code>\star</code>）」是在**说明**命令名，不是源码泄漏。
VERBATIM = {"script", "style", "pre", "code", "textarea", "option", "noscript"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# '<' 后面不是 ASCII 字母 / '/' / '!' / '?' 时，HTML 分词器把它当正文字符。
# 有的交付件正文里有裸 '<'（如 `\(0<\theta\le1\)`），用 /<[^>]*>/ 会把后面的正文
# 整段当成标签吃掉，于是漏报。
_TAG = re.compile(r"<[A-Za-z/!?][^>]*>", re.S)
_NAME = re.compile(r"^<([A-Za-z][\w:-]*)")
_CLOSE = re.compile(r"^</\s*([A-Za-z][\w:-]*)\s*>")
_CLASS = re.compile(r"class\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", re.I)


def _class_of(seg, name_match):
    m = _CLASS.search(seg[len(name_match.group(0)):-1])
    return (m.group(1) or m.group(2) or m.group(3) or "") if m else ""


def _is_open(seg, name_match):
    return not (seg.rstrip().endswith("/>")
                or name_match.group(1).lower() in VOID)


class VisibleDoc(object):
    """
    同一份偏移量下的两种视图：

    ``masked``  与源文件等长的字符串，读者看不到的字符换成空格（换行保留），
                用来**扫描**可见的 `$`、反斜杠、Markdown 记号。
    ``visible`` 逐字符布尔，True = 读者可见的正文（非标签、非逐字子树、非 KaTeX
                输出），用来**切分**文本节点。
    """

    def __init__(self, src):
        self.src = src
        n = len(src)
        vis = bytearray([1]) * n
        for m in _COMMENT.finditer(src):
            for k in range(m.start(), m.end()):
                vis[k] = 0
        i = 0
        while i < n:
            if vis[i] == 0 or src[i] != "<":
                i += 1
                continue
            m = _TAG.match(src, i)
            if not m:
                i += 1
                continue
            seg = m.group(0)
            o = _NAME.match(seg)
            blank_subtree = False
            if o and _is_open(seg, o):
                name = o.group(1).lower()
                blank_subtree = (
                    name in VERBATIM
                    or (_class_of(seg, o).split() or [""])[0].startswith("katex"))
            if blank_subtree:
                depth, j = 1, m.end()
                while j < n and depth:
                    if vis[j] == 0 or src[j] != "<":
                        j += 1
                        continue
                    m2 = _TAG.match(src, j)
                    if not m2:
                        j += 1
                        continue
                    s2 = m2.group(0)
                    c2, o2 = _CLOSE.match(s2), _NAME.match(s2)
                    if c2:
                        depth -= 1
                    elif o2 and _is_open(s2, o2):
                        depth += 1
                    j = m2.end()
                for k in range(m.start(), j):
                    vis[k] = 0
                i = j
                continue
            for k in range(m.start(), m.end()):
                vis[k] = 0
            i = m.end()
        self.visible = vis
        self.masked = "".join(
            src[k] if vis[k] else ("\n" if src[k] == "\n" else " ")
            for k in range(n))

    def nodes(self):
        """[(文本, 与上一节点之间的标签), ...]：读者可见的文本节点，按序。"""
        src, vis, n = self.src, self.visible, len(self.visible)
        out, pending = [], None
        i = 0
        while i < n:
            if not vis[i]:
                if src[i] == "<":
                    t = _TAG.match(src, i)
                    if t:
                        pending = t.group(0)
                        i = t.end()
                        continue
                pending = pending or "<blanked>"
                i += 1
                continue
            j = i
            while j < n and vis[j]:
                j += 1
            text = src[i:j]
            if text.strip():
                out.append((text, pending))
            pending = None
            i = j
        return out


# --------------------------------------------------------------------------- #
# auto-render 算法（与页面内嵌 bundle 逐节点比对验证过）
# --------------------------------------------------------------------------- #
def find_end_of_math(delimiter, text, start_index):
    index = start_index
    brace_level = 0
    length = len(delimiter)
    while index < len(text):
        ch = text[index]
        if brace_level <= 0 and text[index:index + length] == delimiter:
            return index
        if ch == "\\":
            index += 1
        elif ch == "{":
            brace_level += 1
        elif ch == "}":
            brace_level -= 1
        index += 1
    return -1


_BEGIN_RE = re.compile(r"^\\begin\{")


def split_at_delimiters(text, delimiters):
    """[(kind, data), ...]，kind ∈ {text, math}。delimiters 按页面声明顺序。"""
    out = []
    while True:
        pos = -1
        for left, _right, _disp in delimiters:
            p = text.find(left)
            if p != -1 and (pos == -1 or p < pos):
                pos = p
        if pos == -1:
            break
        if pos > 0:
            out.append(("text", text[:pos]))
            text = text[pos:]
        chosen = None
        for d in delimiters:
            if text.startswith(d[0]):
                chosen = d
                break
        if chosen is None:
            out.append(("text", text[:1]))
            text = text[1:]
            continue
        end = find_end_of_math(chosen[1], text, len(chosen[0]))
        if end == -1:
            break                       # 与 auto-render 一致：直接停下
        raw = text[:end + len(chosen[1])]
        data = raw if _BEGIN_RE.match(raw) else text[len(chosen[0]):end]
        out.append(("math", data))
        text = text[end + len(chosen[1]):]
    if text != "":
        out.append(("text", text))
    return out


def _unescape_js(s):
    return s.replace("\\\\", "\\")


def configured_delims(html):
    """
    该页 renderMathInElement 真正配置的定界符，返回 [(left, right, display), ...]。
    取不到则返回空表——意味着该页不做客户端渲染，任何定界符都算"泄漏"。
    """
    for call in re.finditer(r"renderMathInElement\s*\(([^;]{0,2000})", html, re.S):
        m = re.search(r"delimiters\s*:\s*\[(.*?)\]\s*[,}]", call.group(1), re.S)
        if not m:
            continue
        body = m.group(1)
        triples, i = [], 0
        while True:
            lm = re.compile(
                r"left\s*:\s*(['\"])((?:\\\\.|(?!\1).)*)\1").search(body, i)
            if not lm:
                break
            rm = re.compile(
                r"right\s*:\s*(['\"])((?:\\\\.|(?!\1).)*)\1").search(body, lm.end())
            if not rm:
                break
            dm = re.search(r"display\s*:\s*(true|false)",
                           body[rm.end():rm.end() + 40])
            triples.append((_unescape_js(lm.group(2)), _unescape_js(rm.group(2)),
                            dm.group(1) == "true" if dm else False))
            i = rm.end()
        if triples:
            return triples
    return []


# --------------------------------------------------------------------------- #
# 公式体检
# --------------------------------------------------------------------------- #
MATRIX_ENVS = ("matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
               "smallmatrix", "array", "aligned", "align", "align*", "alignat",
               "alignat*", "alignedat", "gathered", "gather", "gather*",
               "cases", "split", "subarray", "dcases", "rcases", "eqnarray",
               "eqnarray*", "multline", "multline*", "CD")
DOUBLE_CMD = re.compile(r"\\\\[A-Za-z]+")
LATEX_IN_PROSE = re.compile(r"\\[A-Za-z]{2,}|\\[^A-Za-z\s]")
PROSE_SCRIPT = re.compile(r"[_^]\{[^{}\s]{1,32}\}")
MD_BOLD = re.compile(r"\*\*[^*\n]{1,80}\*\*")
MD_ITAL = re.compile(r"(?<![\w\\])_(摘要|索引词|∗|[\u4e00-\u9fff]{1,20})_(?![\w])")
MD_QUOTE = re.compile(r"^>\s", re.M)
MARKER = "\x00"


def _env_spans(text):
    spans = []
    for m in re.finditer(r"\\begin\{([^}]*)\}", text):
        env = m.group(1).strip()
        if env in MATRIX_ENVS:
            e = re.search(r"\\end\{" + re.escape(env) + r"\}", text[m.end():])
            spans.append((m.start(), m.end() + e.end() if e else len(text)))
    return spans


def _in_spans(p, spans):
    return any(a <= p < b for a, b in spans)


def _delim_ok(tex, opener, closer):
    depth, i = 0, 0
    while i < len(tex):
        c = tex[i]
        if c == "\\":
            i += 2                      # 跳过 \( \) \{ \} 这类转义
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def span_problems(tex):
    """一条数学 span 不可能是完整公式的理由。"""
    out = []
    if not _delim_ok(tex, "{", "}"):
        out.append("unbalanced_braces")
    for o, c, name in (("(", ")", "parens"), ("[", "]", "brackets")):
        if not _delim_ok(tex, o, c):
            out.append("unbalanced_" + name)
    if tex.count("\\left") != tex.count("\\right"):
        out.append("unclosed_left")
    return out


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

    doc = VisibleDoc(html)
    text = doc.masked
    delims = configured_delims(html)

    res = {
        "file": path,
        "configured_delims": [d[0] for d in delims],
        "leftover_delim": [],
        "latex_in_prose": [],
        "doubled_backslash": [],
        "prose_script": [],
        "delim_split_by_tag": [],
        "span_malformed": [],
        "math_spans": 0,
        "text_nodes": 0,
    }

    nodes = doc.nodes()
    res["text_nodes"] = len(nodes)
    pieces_by_node = []
    for k, (node, boundary) in enumerate(nodes):
        pieces = split_at_delimiters(node, delims)
        pieces_by_node.append(pieces)
        for kind, data in pieces:
            if kind == "math":
                res["math_spans"] += 1
                for prob in span_problems(data):
                    res["span_malformed"].append(
                        {"node": k, "why": prob, "tex": data[:120]})
                spans = _env_spans(data)
                for m in DOUBLE_CMD.finditer(data):
                    if not _in_spans(m.start(), spans):
                        res["doubled_backslash"].append(
                            {"node": k, "cmd": m.group(0), "tex": data[:120]})
                continue
            for left, _r, _disp in delims:
                for m in re.finditer(re.escape(left), data):
                    res["leftover_delim"].append(
                        {"node": k, "boundary": boundary, "delimiter": left,
                         "context": data[max(0, m.start() - 40):m.start() + 60]})
            for m in LATEX_IN_PROSE.finditer(data):
                res["latex_in_prose"].append(
                    {"node": k, "boundary": boundary, "token": m.group(0),
                     "context": data[:160]})
            for m in PROSE_SCRIPT.finditer(data):
                res["prose_script"].append(
                    {"node": k, "boundary": boundary, "token": m.group(0),
                     "context": data[:160]})
    # 完全不渲染的页面（无 delimiters 配置）：双反斜杠也要查
    if res["math_spans"] == 0:
        spans = _env_spans(text)
        for m in DOUBLE_CMD.finditer(text):
            if not _in_spans(m.start(), spans):
                res["doubled_backslash"].append(
                    {"node": -1, "cmd": m.group(0), "tex": ""})
    # 标签边界是否改变了页面实际匹配到的公式
    for k in range(1, len(nodes)):
        prev_t, _pb = nodes[k - 1]
        cur_t, cur_b = nodes[k]
        if not cur_b:
            continue
        apart = [d for kind, d in pieces_by_node[k - 1] if kind == "math"]
        apart += [d for kind, d in pieces_by_node[k] if kind == "math"]
        joined = [d for kind, d in
                  split_at_delimiters(prev_t + MARKER + cur_t, delims)
                  if kind == "math"]
        if joined != apart:
            res["delim_split_by_tag"].append(
                {"node": k, "boundary": cur_b,
                 "left_tail": prev_t[-40:], "right_head": cur_t[:40],
                 "matched_apart": [x[:60] for x in apart],
                 "matched_joined": [x[:60] for x in joined]})

    res["md_residue"] = (MD_BOLD.findall(text) + MD_ITAL.findall(text)
                         + MD_QUOTE.findall(text))

    markup = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    markup = re.sub(r"<script.*?</script>", "", markup, flags=re.S)
    res["katex_errors"] = len(re.findall(r'<span class="katex-error"', markup))

    res["external_refs"] = [s for s in re.findall(
        r'<(?:script|link)[^>]*?(?:src|href)="([^"]*)"', html)
        if s.startswith(("http", "//"))] \
        + re.findall(r"url\(\s*['\"]?(?:https?:)?//", html)

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
            except Exception:                                # noqa: BLE001
                res["broken_images"] += 1
                continue
            kind, w, h = image_dims(data)
            if kind == "?" or w == 0:
                res["broken_images"] += 1
            by_sha.setdefault(hashlib.sha256(data).hexdigest(), []).append((i, alt))
    res["dup_image_bytes"] = [{"sha": k[:12], "index_alt": v}
                              for k, v in by_sha.items()
                              if len(v) > 1 and len({a for _i, a in v}) > 1]
    res["ok"] = not (res["leftover_delim"] or res["latex_in_prose"]
                     or res["doubled_backslash"] or res["prose_script"]
                     or res["delim_split_by_tag"] or res["span_malformed"]
                     or res["md_residue"] or res["katex_errors"]
                     or res["dup_image_bytes"] or res["external_refs"]
                     or res["non_embedded_images"] or res["broken_images"])
    return res


def _example(items, key, n=6):
    return [x[key] for x in items[:n]]


# --------------------------------------------------------------------------- #
# 自检：把"已知坏"和"已知好"的最小样本跑一遍。
#
# 存在的理由：这两类缺陷正是**旧版检查器的盲区**——把 `$…$` 整段遮掉就看不见公式体写错，
# 把可见文本跨标签拼接就看不见定界符被切开。所以改检查器之后必须回归：**坏的必须报错、
# 好的必须通过**；若两边都通过，说明新检查项根本没生效。
# --------------------------------------------------------------------------- #
BS = chr(92)
SELFTEST = [
    # (名称, HTML 片段, 期望不合格)
    ("双反斜杠：\\\\|\\\\bar{v}_L\\\\|",
     '<p>' + "<p>范数 $" + BS + BS + "|" + BS + BS + "bar{v}_L" + BS + BS + "|$ 结束。</p>",
     True),
    ("单反斜杠（正确）",
     "<p>范数 $" + BS + "|" + BS + "bar{v}_L" + BS + "|$ 结束。</p>", False),
    ("范数写成单竖线（渲染无错但有歧义）",
     "<p>范数 $(|" + BS + "bar{v}_L|)$ 结束。</p>", False),
    ("定界符被 <em> 切开",
     "<p>距离 $(|" + BS + "bar{x}$<em>$R - " + BS + "bar{x}$<em>L|) 继续。</p>", True),
    ("一对 \\( \\) 被标签分到两个文本节点",
     "<p>增益 " + BS + "(K<em>" + BS + ") 为常数。</p>", True),
    ("定界符跨块级标签",
     "<p>$$</p><p>x=1</p><p>$$</p>", True),
    ("公式体被截断（括号不配对）",
     "<p>距离 $(|" + BS + "bar{x}$ 结束。</p>", True),
    ("正文残留 " + BS + "command",
     "<p>系数 " + BS + "gamma_i(z_i) 由相位索引。</p>", True),
    ("正文残留上下标",
     "<p>其中 (x_{sym,th}) 为阈值。</p>", True),
    ("矩阵里的 \\\\ 换行符（合法）",
     "<p>$A = " + BS + "begin{bmatrix} 1 & 0 " + BS + BS + " 0 & 1 "
     + BS + "end{bmatrix}$</p>", False),
    ("<code> 里说明 LaTeX 命令（合法）",
     "<p>（LaTeX 的 <code>" + BS + "star</code>）</p>", False),
]


def selftest():
    bad = 0
    for name, frag, want_fail in SELFTEST:
        html = ("<html><head><script>renderMathInElement(document.body,"
                "{delimiters:[{left:'$$',right:'$$',display:true},"
                "{left:'$',right:'$',display:false},"
                "{left:'" + BS + BS + "(',right:'" + BS + BS + ")',display:false}]"
                "});</script></head><body>" + frag + "</body></html>")
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as f:
            f.write(html)
            tmp = f.name
        try:
            r = check_file(tmp, dupe_scan=False)
        finally:
            os.unlink(tmp)
        got = not r["ok"]
        ok = got == want_fail
        bad += not ok
        fired = [k for k in ("leftover_delim", "latex_in_prose",
                             "doubled_backslash", "prose_script",
                             "delim_split_by_tag", "span_malformed") if r[k]]
        print(f"{'PASS' if ok else 'FAIL'}  {name:<40} "
              f"期望{'不合格' if want_fail else '通过'} "
              f"实际{'不合格' if got else '通过'} {fired}")
    print(f"\n自检 {len(SELFTEST)} 项，{bad} 项不符合预期")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="交付件源码级复查")
    ap.add_argument("html", nargs="*", help="待检查的 HTML")
    ap.add_argument("--dir", action="append", default=[], help="递归检查目录，可多次")
    ap.add_argument("--json", default="", help="把完整结果写成 JSON")
    ap.add_argument("--no-dupe-scan", action="store_true", help="跳过图片字节重复扫描")
    ap.add_argument("--selftest", action="store_true",
                    help="跑内置回归样本（坏的必须报错、好的必须通过）后退出")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

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
        except Exception as e:                               # noqa: BLE001
            print(f"{os.path.basename(f)}: 读取失败 {e!r}")
            bad += 1
            continue
        results.append(r)
        name = os.path.basename(f)
        if r["ok"]:
            print(f"OK   {name}  (delims={r['configured_delims']} "
                  f"math={r['math_spans']} imgs={r['images']})")
            continue
        bad += 1
        print(f"FAIL {name}  (页内定界符={r['configured_delims']} "
              f"数学 span={r['math_spans']})")
        if r["leftover_delim"]:
            print(f"     ! 未配对的定界符 {len(r['leftover_delim'])} 处，"
                  f"例：{_example(r['leftover_delim'], 'delimiter')}")
        if r["latex_in_prose"]:
            print(f"     ! 正文残留 LaTeX {len(r['latex_in_prose'])} 处，"
                  f"例：{_example(r['latex_in_prose'], 'token')}")
        if r["doubled_backslash"]:
            print(f"     ! 双反斜杠命令 {len(r['doubled_backslash'])} 处，"
                  f"例：{_example(r['doubled_backslash'], 'cmd')}"
                  f"（双反斜杠会渲染成换行 + 字面量，KaTeX 不报错）")
        if r["prose_script"]:
            print(f"     ! 正文残留上下标 {len(r['prose_script'])} 处，"
                  f"例：{_example(r['prose_script'], 'token')}")
        if r["delim_split_by_tag"]:
            print(f"     ! 定界符/公式被标签切断 {len(r['delim_split_by_tag'])} 处：")
            for x in r["delim_split_by_tag"][:3]:
                print(f"       标签 {x['boundary'][:30]!r} 处 "
                      f"…{x['left_tail'][-20:]!r} | {x['right_head'][:20]!r}…"
                      f" 分段匹配={x['matched_apart']} 合并匹配={x['matched_joined']}")
        if r["span_malformed"]:
            print(f"     ! 不可能成形的数学 span {len(r['span_malformed'])} 处：")
            for x in r["span_malformed"][:3]:
                print(f"       [{x['why']}] `{x['tex']}`")
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
