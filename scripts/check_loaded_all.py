# -*- coding: utf-8 -*-
"""
check_loaded_all.py — 批量确认自包含 HTML 里的每张内嵌图片都能被浏览器解码。

用途:
    base64 内嵌图片写坏了（截断、MIME 写错）在编辑器里看不出来，浏览器里才会变成
    破图。本脚本对每个 HTML 注入一段检查脚本，用无头浏览器加载后统计每张 <img> 的
    naturalWidth：loaded 表示解码成功，broken 表示破图。

用法:
    python check_loaded_all.py out.html                       # 单个文件
    python check_loaded_all.py a.html b.html                  # 多个文件
    python check_loaded_all.py --dir out/                     # 目录（递归 *.html）
    python check_loaded_all.py --dir out/ --edge "C:/.../msedge.exe"

输出:
    每个文件一行 "文件名: imgs:loaded:broken"。
退出码: 0 = 全部图片解码成功, 1 = 存在破图或参数错误

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
<div id="result">pending</div>
<script>
window.addEventListener('load', function () {
  var imgs = document.querySelectorAll('img');
  var loaded = 0, broken = 0;
  for (var j = 0; j < imgs.length; j++) {
    if (imgs[j].naturalWidth > 0) loaded++; else broken++;
  }
  document.getElementById('result').textContent =
    'RESULT::' + imgs.length + ':' + loaded + ':' + broken;
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


def wrap(html_path: str, out_path: str) -> bool:
    """只保留 <style> 与 <body>，追加检查脚本（不改动原文件）。"""
    c = open(html_path, encoding="utf-8").read()
    style = re.search(r"<style>.*?</style>", c, re.S)
    body = re.search(r"<body>(.*)</body>", c, re.S)
    if not style or not body:
        return False
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            + style.group(0) + "</head><body>" + body.group(1) + SCRIPT
            + "</body></html>")
    open(out_path, "w", encoding="utf-8").write(html)
    return True


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


def main():
    ap = argparse.ArgumentParser(description="批量检查内嵌图片是否全部可解码")
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

    tmp = os.path.join(tempfile.gettempdir(), "check_loaded_probe.html")
    bad = 0
    for p in files:
        if not wrap(p, tmp):
            print(f"{os.path.basename(p)}: NO_STYLE/BODY")
            bad += 1
            continue
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--allow-file-access-from-files", "--virtual-time-budget=8000",
                            "--dump-dom", tmp],
                           capture_output=True, text=True, timeout=args.timeout,
                           encoding="utf-8", errors="replace")
        m = re.search(r"RESULT::([\d:]+)", r.stdout or "")
        if not m:
            print(f"{os.path.basename(p)}: NO_RESULT")
            bad += 1
            continue
        total, loaded, broken = (int(x) for x in m.group(1).split(":"))
        flag = "" if broken == 0 else "  <-- 有破图"
        print(f"{os.path.basename(p)}: imgs:loaded:broken = {total}:{loaded}:{broken}{flag}")
        if broken:
            bad += 1

    print(f"\n检查 {len(files)} 个文件, {bad} 个异常")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
