#!/usr/bin/env node
/**
 * md_to_offline_html.js — 把翻译 Markdown 构建成"离线自包含 HTML"（Node 版一键脚本）。
 *
 * 用途:
 *   公式在构建时用 KaTeX renderToString 预渲染成静态 HTML，KaTeX 的 CSS 与 woff2 字体
 *   全部内嵌为 data URI，Markdown 里引用的本地图片也转成 base64。产出的 HTML 不依赖
 *   任何外网 CDN、不需要浏览器执行 JS 渲染公式，离线双击即可阅读。
 *
 * 用法:
 *   node md_to_offline_html.js translation.md out.html
 *
 * 说明:
 *   - 依赖从脚本目录向上逐级查找 node_modules，通常先在本仓库根目录执行 npm install；
 *   - 需要"公式编号防重叠 + 超宽公式自适应"时，请用 build_html.py（本脚本 + 两项后处理）；
 *   - 图片路径相对于传入的 Markdown 文件所在目录解析，缺失的图片会打印警告并保持原引用。
 *
 * 依赖: npm install katex markdown-it markdown-it-texmath
 */
const fs = require('fs');
const path = require('path');

// ---------- 0. 参数检查（先校验再做事） ----------
const args = process.argv.slice(2);
const USAGE = '用法: node md_to_offline_html.js <translation.md> <out.html>';
if (args[0] === '--help' || args[0] === '-h') {
  console.log(USAGE);
  process.exit(0);
}
if (args.length < 2) {
  console.log(USAGE);
  process.exit(1);
}

const mdIt = require('markdown-it');
const texmath = require('markdown-it-texmath');
const katex = require('katex');

// ---------- 1. 读取 KaTeX CSS 并内嵌字体 ----------
// 用 require.resolve 定位 katex 安装位置，避免依赖固定的 node_modules 相对路径
let katexDist;
try {
  katexDist = path.join(path.dirname(require.resolve('katex/package.json')), 'dist');
} catch (e) {
  console.error('未找到 katex，请先在本仓库根目录执行: npm install');
  process.exit(1);
}
let css = fs.readFileSync(path.join(katexDist, 'katex.min.css'), 'utf-8');

// 将 url(fonts/xxx.woff2) 替换为 data URI
const fontRe = /url\(fonts\/([^)]+\.woff2)\)/g;
let fontCount = 0;
css = css.replace(fontRe, (m, fname) => {
  const fp = path.join(katexDist, 'fonts', fname);
  if (!fs.existsSync(fp)) return m;
  const b64 = fs.readFileSync(fp).toString('base64');
  fontCount++;
  return `url(data:font/woff2;base64,${b64})`;
});
console.log(`内嵌字体: ${fontCount} 个 woff2`);

// ---------- 2. Markdown -> HTML（公式构建时渲染） ----------
const mdParser = mdIt({
  html: false,
  linkify: true,
  typographer: false,
}).use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { throwOnError: false, output: 'html' },
});

function inlineImages(mdText, baseDir) {
  return mdText.replace(/!\[([^\]]*)\]\(([^)]+\.(?:png|jpe?g|gif|svg))\)/g, (m, alt, p) => {
    if (/^(https?:|data:)/.test(p)) return m;
    const full = path.normalize(path.join(baseDir, p));
    if (!fs.existsSync(full)) {
      console.log(`  ! 图片缺失: ${p}`);
      return m;
    }
    const ext = path.extname(full).slice(1).toLowerCase();
    const mime = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', svg: 'image/svg+xml' }[ext] || 'image/png';
    const b64 = fs.readFileSync(full).toString('base64');
    return `![${alt}](data:${mime};base64,${b64})`;
  });
}

function build(inFile, outFile) {
  let md = fs.readFileSync(inFile, 'utf-8');
  const baseDir = path.dirname(path.resolve(inFile));
  md = inlineImages(md, baseDir);

  const body = mdParser.render(md);
  const title = path.basename(inFile, path.extname(inFile));

  // 统计 KaTeX 渲染的公式数
  const katexSpans = (body.match(/class="katex"/g) || []).length;
  const leftoverDollar = (body.match(/\$/g) || []).length;

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${title}</title>
<style>
/* ===== KaTeX (内嵌, 离线可用) ===== */
${css}
/* ===== 页面样式 ===== */
body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1.2em; line-height: 1.8; color: #222; }
h1 { border-bottom: 3px solid #2c4a7c; padding-bottom: 8px; color: #1a1a2e; }
h2 { color: #2c4a7c; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 2em; }
h3 { color: #3d5e99; }
h4 { color: #4a6a9e; }
p { text-align: justify; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; border: 1px solid #ddd; border-radius: 4px; }
blockquote { border-left: 4px solid #2c4a7c; background: #f3f6fb; margin: 1em 0; padding: 8px 16px; color: #333; border-radius: 0 4px 4px 0; }
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; }
pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
table { border-collapse: collapse; margin: 1em auto; }
th, td { border: 1px solid #ddd; padding: 6px 12px; }
th { background: #f3f6fb; }
/* 数学公式：display block + 满宽，避免编号压到公式上 */
.katex-display { margin: 1.2em 0; overflow-x: auto; overflow-y: hidden; }
.katex-display > .katex { display: block; text-align: center; }
.katex-display > .katex > .katex-html { width: 100%; }
li { margin: 4px 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 2em 0; }
</style>
</head>
<body>
${body}
</body>
</html>`;

  fs.writeFileSync(outFile, html, 'utf-8');
  console.log(`${path.basename(inFile)} -> ${path.basename(outFile)}`);
  console.log(`  KaTeX 渲染公式: ${katexSpans} 个, 残留 \$: ${leftoverDollar}, 大小: ${(html.length / 1024).toFixed(0)} KB`);
}

// ---------- 3. 主流程 ----------
build(args[0], args[1]);
