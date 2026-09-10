#!/usr/bin/env node
/**
 * render_body.js — 把翻译 Markdown 渲染成 HTML 片段（body），公式用 KaTeX 预渲染。
 *
 * 用途:
 *   HTML 流水线的"渲染"环节：只输出 <body> 内部片段，供上层脚本（如 build_html.py
 *   或自定义模板）拼装完整页面。与 md_to_offline_html.js 的区别是它不做页面组装、
 *   不内嵌字体，只负责"Markdown + 公式 -> 静态 HTML"。
 *
 * 用法:
 *   node render_body.js translation.md body.html
 *
 * 说明:
 *   使用 throwOnError: true，公式 LaTeX 语法有错时直接报错退出（便于拦截错误公式）；
 *   若希望渲染容错，请改用 md_to_offline_html.js。
 *
 * 依赖: npm install katex markdown-it markdown-it-texmath
 */
const fs = require('fs');
const mdIt = require('markdown-it');
const texmath = require('markdown-it-texmath');
const katex = require('katex');

const src = process.argv[2];
const dst = process.argv[3];
const USAGE = '用法: node render_body.js <translation.md> <body.html>';
if (src === '--help' || src === '-h') {
  console.log(USAGE);
  process.exit(0);
}
if (!src || !dst) {
  console.log(USAGE);
  process.exit(1);
}

let md;
try {
  md = fs.readFileSync(src, 'utf-8');
} catch (e) {
  console.error('读取失败:', src, e.message);
  process.exit(1);
}

const mdParser = mdIt({ html: false, tables: true, linkify: true }).use(texmath, {
  engine: katex, delimiters: 'dollars', katexOptions: { throwOnError: true },
});

let html;
try {
  html = mdParser.render(md);
} catch (e) {
  console.error('渲染失败:', e.message);
  process.exit(1);
}
const leftover = (html.match(/\$/g) || []).length;
console.error('残留 $ 数量:', leftover);
fs.writeFileSync(dst, html);
console.error('body 已输出，长度:', html.length);
