# -*- coding: utf-8 -*-
"""
fix_wide.py — 给自包含 HTML 注入"超宽公式编号避让"脚本。

用途:
    公式很长（接近或超过正文宽度）时，右对齐的编号仍可能压住公式尾部。本脚本在
    </body> 前注入一段自包含 JS：加载后检测 .katex-tag 与 .katex-base 是否重叠，
    重叠则逐步缩小该公式的字号（最多 6 档），直到编号与公式分离。

用法:
    python fix_wide.py out.html                     # 单个文件
    python fix_wide.py out1.html out2.html          # 多个文件
    python fix_wide.py --dir out/                   # 目录（递归处理 *.html）

说明:
    幂等：已注入过的文件会跳过；脚本无外部依赖，不改动公式内容与图片。
"""
import argparse
import os
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MARKER = "超宽公式编号避让"

SCRIPT = """
<script>
/* === 超宽公式编号避让 ===
   公式宽度接近/超过容器宽度时，右对齐的编号会压到公式上。
   检测到重叠则逐步缩小所在公式的字号，直到编号与公式分离。 */
(function () {
  function fixOverlap() {
    var tags = document.querySelectorAll('.katex-tag');
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i];
      var disp = t.closest('.katex-display') || t.parentElement;
      if (!disp || disp._katexFixed) continue;
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
      if (shrink > 0) disp._katexFixed = true;
    }
  }
  window.addEventListener('load', fixOverlap);
  document.addEventListener('DOMContentLoaded', fixOverlap);
  setTimeout(fixOverlap, 400);
})();
</script>
"""


def inject(path: str) -> bool:
    """注入避让脚本；返回 True 表示本次写入，False 表示已注入/不适用。"""
    c = open(path, encoding="utf-8").read()
    if MARKER in c:
        return False
    if "</body>" not in c:
        return False
    c = c.replace("</body>", SCRIPT + "\n</body>", 1)
    open(path, "w", encoding="utf-8").write(c)
    return True


def iter_html(paths, dirs):
    for p in paths:
        if not os.path.exists(p):
            print(f"[跳过] 不存在: {p}")
            continue
        yield p
    for d in dirs:
        if not os.path.isdir(d):
            print(f"[跳过] 不是目录: {d}")
            continue
        for dirpath, _sub, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith(".html"):
                    yield os.path.join(dirpath, f)


def main():
    ap = argparse.ArgumentParser(description="注入超宽公式编号避让脚本")
    ap.add_argument("html", nargs="*", help="待处理的 HTML 文件")
    ap.add_argument("--dir", action="append", default=[], help="待处理的目录（递归），可多次")
    args = ap.parse_args()

    if not args.html and not args.dir:
        ap.print_help()
        sys.exit(1)

    fixed = []
    for p in iter_html(args.html, args.dir):
        if inject(p):
            fixed.append(p)
    print(f"已注入 {len(fixed)} 个文件:")
    for f in fixed:
        print(" -", f)


if __name__ == "__main__":
    main()
