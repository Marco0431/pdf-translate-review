---
name: pdf-translate-review
description: >-
  Translate an academic PDF paper into a faithful Chinese translation (without
  the original English text), embed original figures, then critically read it and
  rigorously verify the translation against the original PDF page by page.
  Optionally build a self-contained offline HTML (KaTeX pre-rendered, fonts and
  images embedded as data URIs). Use when the user asks to 翻译论文/PDF, translate
  a paper, produce a Chinese translation of a paper, 精读论文, demands a
  translation be checked for formula and text accuracy (审查/核对/逐字核对), or
  asks for an offline/self-contained HTML version (离线 HTML/自包含 HTML).
---

# PDF 翻译 · 精读 · 审查

将学术 PDF 论文翻译为不含原文的中文图文文档，完成精读与逐字审查，并按需产出离线自包含 HTML。

## 核心原则

1. **翻译忠实**：公式必须与原文逐字一致，不得凭记忆补写。翻译使用领域惯用表述，但不得改变物理含义。
2. **公式严格**：所有公式保留原文编号；文本公式用 `$...$`（行内）、`$$...$$`（块级），**不用 `\(...\)` / `\[...\]`**（部分 Markdown 预览器不识别，会显示为源码）。
3. **图片按图注配对**：图片必须按论文 `Fig.` 图注定位提取，内容与编号双重核对；不得按 PDF 内嵌对象顺序取图。
4. **审查必做**：交付前逐字核对公式、翻译与图片，反复检查，不允许"看起来对"。

---

## 工作流总览

```
① 准备  → 定位 PDF，建工作目录
② 提取  → 文本 + 按图注裁剪的图片 + 页面渲染图 + 表格清单
③ 翻译  → 逐节忠实翻译，公式保编号，表格全量转译
④ 精读  → 结构 / 方法 / 公式 / 实验 / 点评
⑤ 审查  → 逐字核对公式、图片、表格、翻译；自动验证；反复检查
⑥ 交付  → 图文 Markdown；可选离线自包含 HTML
```

---

## ① 准备

1. 定位 PDF 文件。
2. 建立独立工作目录（提取物与译文分开放，例如 `out/`、`out/assets/`、`out/meta/`）。
3. 确认依赖可用：`python -m pip install pymupdf pymupdf4llm`；需要 HTML 产出时在仓库根目录执行 `npm install`。

## ② 提取

```bash
python scripts/extract_pdf.py paper.pdf --out out/
```

得到 `out/paper.md`（文本基准）、`out/assets/raw/`（逐页 150 DPI 渲染图 + PDF 内嵌图片对象）、`out/meta/`（pages/figures/source 元数据）。

**关键认识**：PDF 中公式常是矢量或图片对象，文本层会丢公式、丢括号、丢上下标，甚至把 `I` 与 `1` 混淆。因此：

- `paper.md` 只作为翻译的**文字基准**；
- 公式的**精确结构必须用页面渲染图逐字确认**（见 ⑤）。

### 2.1 图片提取：按图注定位

**规则**：一张图的内容由它的图注（`Fig. N`）定义，而与 PDF 内嵌对象顺序无关。内嵌对象顺序既包含公式截图，也不保证与图号同序。

步骤：

1. 列出全文 `Fig.` 图注（页码 / 栏位 / y 坐标 / 文本），确定图总数 M：
   ```bash
   python scripts/extract_figs_by_caption.py paper.pdf --list
   ```
2. 每张图 = **同栏内、该图注上方、上一条图注下方**的整块区域；有图像块时按图像块合并裁剪，矢量图/组合图时按栏内区间裁剪：
   ```bash
   python scripts/extract_figs_by_caption.py paper.pdf -o out/assets --dpi 300 --col-x 300 --pad 20
   ```
3. 两栏排版按图注 x 坐标判定栏位，左右栏各自裁剪；跨栏大图单独处理。
4. **逐张目视核对**（用 Read 打开图片）：内容与 `Fig. N` 图注语义一致、图文完整无裁切（顶部/底部图例被切掉就调整边界重裁）。
5. 以图注为基准统计图总数 M，译文中的图片数必须等于 M；附录、分栏底部、跨页处的图容易漏。

### 2.2 表格提取：原文所有表格都要转译

1. 定位全文表格标题（常见形态 `TABLE I`、`TABLE 1`，含页码/栏位）。
2. 渲染每张表（600 DPI 左右）看清**表头、全部行、数值、单位、符号上下标**。
3. 每个表都**完整转译为 Markdown 表格**：表标题、列头、全部数值与单位、符号用行内公式。
4. 跨栏表在单页内也要按栏裁剪完整；跨页表把两页部分合并成一张表。
5. **只在正文写"见表 X"而不转译表格内容视为未完成**。

## ③ 翻译

- **不含原文**：输出纯中文翻译 + 公式 + 图片，不并列英文原文。
- **公式**：每个公式用 `$$...$$` 块级显示，`\tag{N}` 保留原文编号；行内符号用 `$...$`。
- **符号说明**：变量符号首次出现处给出含义。
- **章节**：保留原文章节结构（摘要 / 引言 / 各节 / 结论 / 附录），中文标题可附原文编号。
- **图片**：按原文位置嵌入 `assets/figN.png`，图下方写"图 N"标题；`figN.png` 的内容必须与 `Fig. N` 图注一一对应。
- **表格**：每个表用 Markdown 表格完整转译，放在正文引用处附近。
- **原文笔误**：忠实保留原文写法，并在下方加 `> 注释` 说明疑似笔误与理由，不擅自"修正"。

## ④ 精读

在翻译之后追加"# 精读"部分：

- **论文定位**：一句话概括贡献。
- **要解决的问题**：背景、现有方法局限、核心痛点。
- **方法/核心创新**：关键公式含义、设计动机、与现有方法对比。
- **实验设计**：实验设置、关键结果、结果解读。
- **局限与思考**：方法局限、未解决问题。

精读中引用的公式编号必须与翻译部分一致。

## ⑤ 审查（必做，逐字核对）

同步执行 [reference/verification-guide.md](reference/verification-guide.md)，并至少做两轮。

### 5.1 公式核对

文本层提取的公式不可信。必须：

1. 用 `scripts/zoom_formula.py` 定位公式行坐标并渲染 **800–1600 DPI** 裁剪图，肉眼逐字符确认；
2. 逐式比对译文公式与原文，记录差异；
3. 重点核对以下抽象要点（每一项都放大渲染图确认）：
   - **上下标归属**：确认每个字符是下标、上标还是同行正常字号；下标与上标位置不同会改变符号含义，并用文中参数表交叉验证符号命名；
   - **分数 vs 加号**：确认是否存在分数线、分子分母结构，避免把"加号 + 列向量"误读成分数，也避免把分数误读成并列项；
   - **函数自变量**：确认自变量本身是否带导数点（形如 `D(q)` 与 `D(\dot{q})` 是不同函数）；
   - **括号范围**：`[(I-a)b - ac]` 与 `[(I-a)(b-c)]` 两种 LaTeX 语法都合法但语义不同——必须逐项确认**减号两侧各被谁相乘**。发现括号范围可疑时，用该公式**下游推导式**反推验证：把两种结构分别代入后续推导，能推出原文下一式的才是正确结构；
   - **多行共享编号**：多行矩阵 / 方程组共用一个编号时，确认共享关系与原文一致，不得拆成 `12a/12b`；
   - **跨页公式组**：多式共用编号的公式组可能跨页（编号标注在末式），判定"原文没有此式"必须把**编号所在页与其前一页的两栏全部**渲染核对后才能下结论；
   - **不补写**：原文未给出的公式（如未显式写出的矩阵）不得补写；确有合理补充必须加 `> 注释：原文此处未给出…，此为译者补充。`。
4. 发现错误后**同步修改三处**：译文正文、精读章节、HTML 内嵌公式源（`<annotation encoding="application/x-tex">`）——同一公式常在多处出现，必须一致。

### 5.2 图片-图注一致性核对（必做）

1. 列出论文全部 `Fig.` 图注（编号应连续 1..M）；
2. 列出译文全部"图 N"标题与引用的 `assets/figN.png`；
3. 逐一比对：数量相等、编号连续、图 N 标题语义与 `Fig. N` 图注一致；
4. 用 Read 逐张目视确认图片内容（而非只看文件名）；
5. 检查图片在文档中的出现顺序与图注编号顺序一致；
6. 同一图片文件不得被两次引用表示两张不同图（组合图要按边界拆成两幅）；
7. 自动化辅助：
   ```bash
   python scripts/check_img_order.py out.html --expected 1,2,3,4,5
   python scripts/check_img_dims.py out.html
   ```

### 5.3 表格核对

提取原文全部表格标题，与译文中的 Markdown 表格一一比对：数量相等、表头一致、每行数值与单位一致、符号上下标一致；正文"见表 X"必须伴随实际表格。

### 5.4 自动验证

```bash
# 结构兜底：编号齐全、$$/$ 配对、无 \( 残留、括号与环境配对、图片一一对应、关键式存在
python scripts/verify_translation.py translation.md \
  --max-eq 38 --assets-dir assets --expect-imgs 15 \
  --section "## 摘要" --section "# 精读" \
  --key 'J_i^{-T}u_i' --check-english

# 公式语法：逐条用 KaTeX 渲染，列出失败公式（真实语法错误，不是"看起来像"）
node scripts/verify_katex_md.js translation.md
```

### 5.5 翻译核对

逐段比对 PDF 文本层与译文：数字、单位、参数、实验条件、引文编号、专有名词。

### 5.6 反复检查

修正后重跑 5.4 与 5.2；若要求"反复检查"，至少三轮：初查 → 修正 → 复查 → 再修正 → 终查。每一轮都重跑自动验证，直到 0 问题。

## ⑥ 交付

**产出 A：图文 Markdown**（默认）

`translation.md` + `assets/` 图片目录，相对路径引用。需要单文件分发时内嵌图片：

```bash
python scripts/md_self_contained.py translation.md --out translation_one_file.md
```

**产出 B：离线自包含 HTML**（需要公式排版 / 单文件分发时）

```bash
python scripts/build_html.py translation.md out.html     # KaTeX 预渲染 + 字体/图片 base64 + 编号防重叠
python scripts/check_all_html.py out.html                # 全量复查：重叠/图片/渲染残留
python scripts/headless_check.py out.html                # 单文件快速体检
```

HTML 的修复与归档工具：

```bash
python scripts/fix_overlap.py out.html     # 编号压公式：追加覆盖 CSS（幂等）
python scripts/fix_wide.py out.html        # 超宽公式：注入自适应缩放脚本（幂等）
python scripts/sync_zotero.py out.html --target-dir <DIR>
python scripts/sync_zotero.py out.html --zotero-storage <ZOTERO_STORAGE> --key <ATTACHMENT_KEY>
```

---

## 附加资源

- 审查方法论与命令清单：[reference/verification-guide.md](reference/verification-guide.md)
- 提取：`scripts/extract_pdf.py`（文本+页面图+图片对象）、`scripts/extract_figs_by_caption.py`（按图注裁剪）、`scripts/ocr_formula.py`（公式截图 OCR 辅助）
- 核对：`scripts/zoom_formula.py`（公式高清渲染）、`scripts/verify_translation.py`（文档结构验证）、`scripts/verify_katex_md.js`（公式语法验证）
- HTML：`scripts/md_self_contained.py`（图片内嵌 Markdown）、`scripts/render_body.js`（Markdown→KaTeX 静态 HTML）、`scripts/md_to_offline_html.js`（Node 一键自包含 HTML）、`scripts/build_html.py`（Python 一键构建）、`scripts/vendor_katex.py`（导出 KaTeX 离线资源）
- 检查：`scripts/fix_overlap.py`、`scripts/fix_wide.py`、`scripts/check_img_order.py`、`scripts/check_img_dims.py`、`scripts/headless_check.py`、`scripts/check_loaded_all.py`、`scripts/check_all_html.py`
- 归档：`scripts/sync_zotero.py`
