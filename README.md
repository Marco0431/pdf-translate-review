# pdf-translate-review

把学术 PDF 论文翻译成**不含原文的中文图文文档**，完成**精读**与**逐字审查**，并可按需产出**离线自包含 HTML** 的完整工具链 + Agent Skill（`SKILL.md`，Cursor / Claude Code / Codex 等 Agent 通用）。

```
PDF ──提取──> 文本基准 + 按图注裁剪的原图 + 页面渲染图
   ──翻译──> 中文图文 Markdown（公式保留编号，表格全量转译）
   ──审查──> 逐字核对公式 / 图片 / 表格 / 翻译（脚本兜底 + 渲染图复核）
   ──交付──> ① 图文 Markdown   ② 离线自包含 HTML（KaTeX 预渲染 + 字体/图片内嵌）
   ──归档──> 覆盖回 Zotero 附件存储
```

## 为什么需要它

"PDF 抽文本 → 直接翻"看起来省事，实际处处是坑：

- **公式**：PDF 里的公式常是矢量/位图对象，文本层提取会丢括号、丢上下标、把 `I` 认成 `1`——照抄文本层，公式必然出错；
- **图片**：PDF 内嵌对象顺序不等于论文图号，按"出现顺序"取图会导致图片与图注错位、缺图；
- **表格**：跨栏/跨页表格容易被整表漏译，只在正文留一句"见表 X"；
- **公式组**：多行共享一个编号的公式组可能跨页，只查编号所在页就会误判"原文没有此式"；
- **HTML 交付**：公式编号可能压到公式上、图片可能仍是相对路径导致离线打开丢图。

本工具链把这些规则固化成**流程 + 脚本 + 检查清单**：公式必须基于 800–1600 DPI 渲染图逐字核对；图片必须按 `Fig.` 图注定位；交付前用脚本做结构兜底与渲染体检。

## 特性

- **忠实翻译**：纯中文 + 公式 + 原图，不并列英文；公式保留原文编号；原文笔误保留原样并加 `> 注释`
- **图片按图注配对**：两栏 / 跨栏 / 多子图按图注区间裁剪，禁止按内嵌对象顺序取图
- **表格全量转译**：全部表格转成 Markdown 表格，表头、数值、单位、符号逐一核对
- **公式陷阱清单**：括号范围歧义、跨页公式组、上下标误读、多行共享编号等识别要点（见 `reference/verification-guide.md`）
- **结构 + 语法双重验证**：`verify_translation.py` 查编号/分隔符/括号/图片，`verify_katex_md.js` 逐条渲染公式
- **离线自包含 HTML**：KaTeX 构建时预渲染、字体与图片全部 base64 内嵌，编号防重叠 + 超宽公式自适应
- **交付后归档**：一键覆盖回 Zotero 附件存储

## 安装

```bash
# Cursor 用户级 skills 目录
git clone https://github.com/Marco0431/pdf-translate-review.git ~/.cursor/skills/pdf-translate-review
```

其他 Agent：把仓库目录放入对应的 skills 路径即可，核心是 `SKILL.md`。

依赖：

```bash
python -m pip install pymupdf pymupdf4llm     # 提取 PDF（必需）
python -m pip install pillow rapidocr-onnxruntime   # 公式截图 OCR 辅助（可选）
npm install                                    # Markdown -> HTML 流水线（需要时）
```

`npm install` 会安装 `katex`、`markdown-it`、`markdown-it-texmath`；HTML 的构建、校验、无头体检脚本依赖它。无头体检脚本需要本机安装 Microsoft Edge 或 Google Chrome（可自动探测，也可用 `--edge` 指定路径）。

## 目录结构

```
pdf-translate-review/
├── SKILL.md                            # Agent skill 入口：翻译 → 精读 → 审查 → 交付全流程
├── reference/
│   └── verification-guide.md           # 审查方法论、命令清单与公式陷阱清单
├── package.json                        # Node 依赖（katex / markdown-it / markdown-it-texmath）
└── scripts/
    ├── extract_pdf.py                  # 提取：文本 + 页面渲染图 + 内嵌图片对象 + 元数据
    ├── extract_figs_by_caption.py      # 提取：按 Fig. 图注定位并裁剪图片（两栏适用）
    ├── ocr_formula.py                  # 提取：公式截图 OCR 辅助（放大后识别，供人工重建）
    ├── zoom_formula.py                 # 校对：公式行定位 + 800–1600 DPI 高清裁剪
    ├── verify_translation.py           # 校对：译文结构验证（编号/分隔符/括号/图片/关键式）
    ├── verify_katex_md.js              # 校对：逐条渲染公式，报告 LaTeX 语法错误
    ├── md_self_contained.py            # HTML：把 Markdown 图片内嵌为 base64 单文件
    ├── render_body.js                  # HTML：Markdown -> KaTeX 静态 HTML 片段
    ├── md_to_offline_html.js           # HTML：一键 Markdown -> 离线自包含 HTML（Node）
    ├── build_html.py                   # HTML：一键构建（渲染 + 编号防重叠 + 超宽自适应）
    ├── fix_overlap.py                  # HTML：修复公式编号与公式重叠（追加覆盖 CSS）
    ├── fix_wide.py                     # HTML：注入超宽公式自适应缩放脚本
    ├── check_img_order.py              # 检查：图片顺序与图注编号一致性
    ├── check_img_dims.py               # 检查：内嵌 base64 图片尺寸核对（防误裁/重复）
    ├── headless_check.py               # 检查：单文件无头渲染体检（公式/重叠/图片/残留）
    ├── check_loaded_all.py             # 检查：批量确认内嵌图片全部可解码
    ├── check_all_html.py               # 检查：批量全量复查（重叠 + 图片 + 渲染残留）
    ├── sync_zotero.py                  # 归档：把修好的 HTML 覆盖到 Zotero 附件存储
    └── vendor_katex.py                 # 部署：导出 KaTeX/markdown-it 离线资源到 vendor 目录
```

## 两条产出流水线

### 流水线 A：图文 Markdown（精读 + 翻译）

```bash
# ① 提取：文本基准 + 页面渲染图 + 内嵌图片（公式结构后续用渲染图核对）
python scripts/extract_pdf.py paper.pdf --out out/

# ② 按图注列出全部图，再裁剪成 out/assets/figN.png（裁完逐张目视核对）
python scripts/extract_figs_by_caption.py paper.pdf --list
python scripts/extract_figs_by_caption.py paper.pdf -o out/assets --dpi 300 --col-x 300

# ③ 翻译 + 精读：产出 translation.md（引用 assets/figN.png）

# ④ 审查：结构验证 + 公式语法验证；公式用高清渲染图逐字复核
python scripts/zoom_formula.py paper.pdf --page 4 --list --kw "eta" "J" "D"
python scripts/zoom_formula.py paper.pdf --page 4 --crop 0.02,0.30,0.55,0.35 --dpi 1200 --out eq12.png
python scripts/verify_translation.py translation.md --max-eq 38 --assets-dir assets --expect-imgs 15 --check-english
node scripts/verify_katex_md.js translation.md

# ⑤ 单文件分发（可选）：图片内嵌为 base64
python scripts/md_self_contained.py translation.md --out translation_one_file.md
```

### 流水线 B：离线自包含 HTML

```bash
# ① 构建：KaTeX 预渲染 + 字体/图片 base64 + 编号防重叠 + 超宽公式自适应
python scripts/build_html.py translation.md out.html

# ② 全量复查：编号重叠 / 图片解码 / 非内嵌图片 / 渲染残留
python scripts/check_all_html.py out.html
python scripts/headless_check.py out.html          # 单文件快速体检
python scripts/check_loaded_all.py --dir out/     # 批量图片解码检查

# ③ 局部修复（幂等，可对已有 HTML 单独执行）
python scripts/fix_overlap.py out.html            # 编号压公式
python scripts/fix_wide.py out.html               # 超宽公式缩放脚本

# ④ 归档到 Zotero 附件存储
python scripts/sync_zotero.py out.html --zotero-storage <ZOTERO_STORAGE> --key <ATTACHMENT_KEY>
python scripts/sync_zotero.py out.html --target-dir <DIR>       # 或直接指定目录
```

需要把 KaTeX 资源复制到浏览器插件 / 内部网页的 vendor 目录时：

```bash
python scripts/vendor_katex.py --out vendor/
```

## 审查为什么必须"逐字"

PDF 文本层对公式极不可靠：公式常是矢量/图片对象，抽取时会丢括号、丢上下标、混淆字形。仅靠"看起来对"或 LaTeX 语法检查**无法**发现语义错误——例如

- `[(I-a)\,b - a\,c]`（两项相减）被写成 `[(I-a)(b - c)]`（整体相乘）：两种写法语法都合法，只有对照下游推导才能暴露矛盾；
- 多行共享编号的公式组跨页，漏掉前一页的部分；
- 下标 `D_1^{q1}` 被误读成 `D_{q1}`。

因此本工具链要求：**放大页面渲染图逐项确认**，配合 `verify_translation.py` 的结构兜底与 `verify_katex_md.js` 的语法验证，三者都通过才算交付。完整方法与命令见 `reference/verification-guide.md`。

## License

MIT
