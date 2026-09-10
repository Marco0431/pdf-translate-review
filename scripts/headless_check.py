# -*- coding: utf-8 -*-
"""
headless_check.py — 用无头浏览器（Edge/Chrome）加载自包含 HTML，报告渲染体检结果。

用途:
    交付自包含 HTML 前的一次快速体检：确认 KaTeX 是否渲染出公式、公式编号与公式
    是否重叠、内嵌 base64 图片是否全部解码成功、是否残留未渲染的 $。

用法:
    python headless_check.py out.html
    python headless_check.py out.html --edge "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    python headless_check.py out.html --timeout 120

输出:
    formulas / overlaps / images(loaded:broken) / leftoverDollar / katexSpans 统计。

依赖:
    本机安装 Microsoft Edge 或 Google Chrome（脚本自动探测常见安装路径，可用 --edge 指定）。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROBE = """
<div id="probe-result">pending</div>
<script>
window.addEventListener('load', function () {
  // 与 fix_wide.py 注入脚本相同的逻辑：编号与公式重叠时缩小字号
  var tags = document.querySelectorAll('.katex-tag');
  for (var i = 0; i < tags.length; i++) {
    var t = tags[i];
    var disp = t.closest('.katex-display') || t.parentElement;
    if (!disp) continue;
    var base = t.parentElement.querySelector('.katex-base');
    if (!base) continue;
    var shrink = 0;
    while (shrink < 6) {
      var tr = t.getBoundingClientRect();
      var br = base.getBoundingClientRect();
      if (tr.left >= br.right - 2) break;
      shrink++;
      disp.style.fontSize = (100 - shrink * 7) + '%';
    }
  }
  var out = [];
  var tags = document.querySelectorAll('.katex-tag');
  var overlap = 0;
  for (var i = 0; i < tags.length; i++) {
    var base = tags[i].parentElement.querySelector('.katex-base');
    if (!base) continue;
    var t = tags[i].getBoundingClientRect();
    var b = base.getBoundingClientRect();
    if (t.left < b.right - 2) overlap++;
  }
  out.push('formulas:' + tags.length);
  out.push('overlaps:' + overlap);
  var imgs = document.querySelectorAll('img');
  var loaded = 0, broken = 0, nonEmbedded = 0;
  for (var j = 0; j < imgs.length; j++) {
    if (imgs[j].naturalWidth > 0) loaded++; else broken++;
    var src = imgs[j].getAttribute('src') || '';
    if (src.indexOf('data:') !== 0) nonEmbedded++;
  }
  out.push('images:' + imgs.length + ' loaded:' + loaded + ' broken:' + broken
           + ' nonEmbedded:' + nonEmbedded);
  // 只统计正文文本节点里的 $（排除探针 script、样式与代码块，避免自计数/误报）
  var skip = {SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1};
  var dollar = 0;
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  while (walker.nextNode()) {
    var el = walker.currentNode.parentElement;
    if (el && skip[el.tagName]) continue;
    dollar += (walker.currentNode.nodeValue.match(/\\$/g) || []).length;
  }
  out.push('leftoverDollar:' + dollar);
  out.push('katexSpans:' + document.querySelectorAll('.katex').length);
  document.getElementById('probe-result').textContent = 'PROBE::' + out.join(' ## ');
});
</script>
"""


def find_browser(explicit: str = "") -> str:
    """探测本机 Edge/Chrome 可执行文件路径。"""
    candidates = [
        explicit,
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/microsoft-edge",
        "/usr/bin/google-chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ""


def build_probe_html(src_html: str, dump_path: str) -> None:
    """把待检查 HTML 与体检脚本拼成临时文件（不改动原文件）。"""
    c = open(src_html, encoding="utf-8").read()
    style = re.search(r"<style>.*?</style>", c, re.S)
    body = re.search(r"<body>(.*)</body>", c, re.S)
    if not style or not body:
        print("错误: 未找到 <style> 或 <body>（不是自包含 HTML？）")
        sys.exit(1)
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            + style.group(0) + "</head><body>" + body.group(1) + PROBE
            + "</body></html>")
    open(dump_path, "w", encoding="utf-8").write(html)


def main():
    ap = argparse.ArgumentParser(description="无头浏览器渲染体检：公式/编号重叠/图片/渲染残留")
    ap.add_argument("html", help="待检查的 HTML 文件")
    ap.add_argument("--edge", default="", help="浏览器可执行文件路径（默认自动探测）")
    ap.add_argument("--timeout", type=int, default=90, help="超时秒数（默认 90）")
    args = ap.parse_args()

    src = os.path.abspath(args.html)
    if not os.path.exists(src):
        print(f"错误: 文件不存在 {src}")
        sys.exit(1)
    browser = find_browser(args.edge)
    if not browser:
        print("错误: 未找到 Edge/Chrome，请用 --edge 指定可执行文件路径")
        sys.exit(1)

    tmp = os.path.join(tempfile.gettempdir(), "headless_check_probe.html")
    build_probe_html(src, tmp)

    cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--allow-file-access-from-files", "--virtual-time-budget=8000",
           "--window-size=1400,2000", "--dump-dom", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout,
                       encoding="utf-8", errors="replace")
    m = re.search(r"PROBE::([^<]+)", r.stdout or "")
    print(f"{os.path.basename(src)}: {m.group(1).strip() if m else 'NO_RESULT'}")
    if not m:
        print("stderr:", (r.stderr or "")[:300])
        sys.exit(1)


if __name__ == "__main__":
    main()
