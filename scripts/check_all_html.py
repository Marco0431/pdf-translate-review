# -*- coding: utf-8 -*-
"""
check_all_html.py — 自包含 HTML 全量复查：编号重叠 + 图片 + 渲染残留。

用途:
    交付前的最后一道自动检查。对每个 HTML 注入探针脚本，用无头浏览器加载后报告：
      formulas      KaTeX 公式块数量
      overlaps      编号与公式仍然重叠的数量（探针会先执行 fix_wide 的缩放逻辑）
      images        图片总数 / 可解码数 / 破图数 / 非内嵌（相对路径）数量
      leftoverDollar 未渲染的残留 $ 数量
      katexSpans    KaTeX 渲染出的公式节点数

用法:
    python check_all_html.py out.html
    python check_all_html.py --dir out/ --edge "C:/Program Files/.../msedge.exe"

退出码: 0 = 全部通过；1 = 存在重叠/破图/非内嵌图片/渲染残留

依赖: 本机安装 Microsoft Edge 或 Google Chrome（自动探测，可用 --edge 指定）
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

SCRIPT = """
<div id="probe"></div>
<div id="result">pending</div>
<script>
window.addEventListener('load', function () {
  // 与 fix_wide.py 注入脚本相同的逻辑：先按需缩小超宽公式
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
  document.getElementById('result').textContent = 'RESULT::' + out.join(' ## ');
});
</script>
"""


def find_browser(explicit: str = "") -> str:
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


def collect(paths, dirs):
    out = []
    for p in paths:
        if os.path.exists(p):
            out.append(p)
        else:
            print(f"[跳过] 不存在: {p}")
    for d in dirs:
        if not os.path.isdir(d):
            print(f"[跳过] 不是目录: {d}")
            continue
        for dirpath, _sub, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith(".html"):
                    out.append(os.path.join(dirpath, f))
    return out


def check_one(browser: str, src: str, tmp: str, timeout: int):
    """返回 (stat_dict, raw_str)；失败返回 (None, 原因)。"""
    c = open(src, encoding="utf-8").read()
    style = re.search(r"<style>.*?</style>", c, re.S)
    body = re.search(r"<body>(.*)</body>", c, re.S)
    if not style or not body:
        return None, "NO_STYLE/BODY"
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            + style.group(0) + "</head><body>" + body.group(1) + SCRIPT
            + "</body></html>")
    open(tmp, "w", encoding="utf-8").write(html)
    r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--allow-file-access-from-files", "--virtual-time-budget=8000",
                        "--window-size=1400,2000", "--dump-dom", tmp],
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    m = re.search(r"RESULT::([^<]+)", r.stdout or "")
    if not m:
        return None, "NO_RESULT"
    raw = m.group(1).strip()
    stat = {}
    for part in raw.split("##"):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        stat[k.strip()] = v.strip()
    return stat, raw


def judge(stat: dict):
    """从统计里挑出硬性失败项。"""
    problems = []
    if stat.get("overlaps", "0") != "0":
        problems.append(f"编号重叠 {stat['overlaps']} 处")
    if "broken:" in stat.get("images", ""):
        broken = re.search(r"broken:(\d+)", stat["images"])
        if broken and broken.group(1) != "0":
            problems.append(f"破图 {broken.group(1)} 张")
    if "nonEmbedded:" in stat.get("images", ""):
        ne = re.search(r"nonEmbedded:(\d+)", stat["images"])
        if ne and ne.group(1) != "0":
            problems.append(f"非内嵌图片 {ne.group(1)} 张（相对路径，离线会失效）")
    if stat.get("leftoverDollar", "0") != "0":
        problems.append(f"残留未渲染 $ {stat['leftoverDollar']} 处")
    return problems


def main():
    ap = argparse.ArgumentParser(description="自包含 HTML 全量复查")
    ap.add_argument("html", nargs="*", help="待检查的 HTML 文件")
    ap.add_argument("--dir", action="append", default=[], help="待检查的目录（递归），可多次")
    ap.add_argument("--edge", default="", help="浏览器可执行文件路径（默认自动探测）")
    ap.add_argument("--timeout", type=int, default=120, help="单个文件超时秒数（默认 120）")
    args = ap.parse_args()

    files = collect(args.html, args.dir)
    if not files:
        print("没有待检查的 HTML 文件")
        sys.exit(1)
    browser = find_browser(args.edge)
    if not browser:
        print("错误: 未找到 Edge/Chrome，请用 --edge 指定可执行文件路径")
        sys.exit(1)

    tmp = os.path.join(tempfile.gettempdir(), "check_all_probe.html")
    failed = 0
    for p in files:
        stat, raw = check_one(browser, p, tmp, args.timeout)
        name = os.path.basename(p)
        if stat is None:
            print(f"{name}: {raw}")
            failed += 1
            continue
        problems = judge(stat)
        print(f"{name}: {raw}")
        if problems:
            failed += 1
            for pr in problems:
                print(f"    ! {pr}")

    print(f"\n检查 {len(files)} 个文件, {failed} 个存在问题")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
