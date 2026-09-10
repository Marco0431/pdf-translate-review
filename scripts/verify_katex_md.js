#!/usr/bin/env node
/**
 * verify_katex_md.js — 用本地 KaTeX 逐条校验翻译 Markdown 里的公式 LaTeX 语法。
 *
 * 用途:
 *   交付前拦截"LaTeX 语法错误"类问题：把文档里所有 $$...$$ 块级公式与 $...$ 行内公式
 *   抽出来逐条 renderToString（throwOnError: true），列出渲染失败的公式与错误信息。
 *   注意：语法通过不代表语义正确（括号范围、上下标仍需对照渲染图人工核对）。
 *
 * 用法:
 *   node verify_katex_md.js translation.md
 *
 * 退出码: 0 = 全部公式可渲染, 1 = 存在渲染失败或参数错误
 *
 * 依赖: npm install katex
 */
const fs = require('fs');
const katex = require('katex');

const mdPath = process.argv[2];
const USAGE = '用法: node verify_katex_md.js <translation.md>';
if (mdPath === '--help' || mdPath === '-h') {
  console.log(USAGE);
  process.exit(0);
}
if (!mdPath) {
  console.log(USAGE);
  process.exit(1);
}

let md;
try {
  md = fs.readFileSync(mdPath, 'utf-8');
} catch (e) {
  console.error('读取失败:', mdPath, e.message);
  process.exit(1);
}

// 提取块级公式（$$...$$，支持跨行）
const blockRegex = /\$\$([\s\S]+?)\$\$/g;
// 提取行内公式（$...$，单行内）
const inlineRegex = /(?<!\$)\$([^$\n]+?)\$(?!\$)/g;

const blocks = [];
let m;
while ((m = blockRegex.exec(md)) !== null) blocks.push(m[1].trim());
const inlines = [];
while ((m = inlineRegex.exec(md)) !== null) inlines.push(m[1].trim());

console.log(`块级公式: ${blocks.length}, 行内公式: ${inlines.length}`);

let failCount = 0;
const fails = [];

function test(tex, type, idx) {
  try {
    katex.renderToString(tex, { displayMode: type === 'block', throwOnError: true });
  } catch (e) {
    failCount++;
    fails.push({ type, idx, tex: tex.substring(0, 150), err: e.message.split('\n')[0] });
  }
}

blocks.forEach((t, i) => test(t, 'block', i));
inlines.forEach((t, i) => test(t, 'inline', i));

console.log(`\n=== 渲染失败: ${failCount} 个 ===`);
for (const f of fails.slice(0, 30)) {
  console.log(`[${f.type} #${f.idx}] ${f.tex}`);
  console.log(`    -> ${f.err}`);
}
if (fails.length > 30) console.log(`（其余 ${fails.length - 30} 条省略）`);
process.exit(failCount > 0 ? 1 : 0);
