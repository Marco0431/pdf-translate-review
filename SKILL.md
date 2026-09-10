---
name: pdf-translate-review
description: >-
  Translate an academic PDF paper into a faithful Chinese translation (without
  the original English text), embed original figures, then critically read it and
  rigorously verify the translation against the original PDF page by page. Use
  when the user asks to 翻译论文/PDF, translate a paper, produce a Chinese
  translation of a paper, 精读论文, or demands a translation be checked for
  formula and text accuracy (审查/核对/逐字核对).
---

# PDF 翻译 · 精读 · 审查

将学术 PDF 论文翻译为不含原文的中文图文 Markdown，并完成精读与逐字审查。

## 核心原则

1. **翻译忠实**：公式必须与原文逐字一致，不得凭记忆补写。翻译采用领域惯用表述，但不得改变物理含义。
2. **公式严格**：所有公式保留原文编号；文本公式用 `$...$`（行内）、`$$...$$`（块级），**绝不用 `\(...\)` / `\[...\]`**（Cursor/VS Code 预览不识别，会乱码）。
3. **审查必做**：交付前必须逐字核对公式与翻译，反复检查，不允许"看起来对"。

---

## 工作流总览

```
① 准备    → 定位 PDF，建工作目录
② 提取    → 文本 + 图片 + 页面渲染图
③ 翻译    → 逐节忠实翻译，公式保编号
④ 精读    → 结构 / 方法 / 公式 / 实验 / 点评
⑤ 审查    → 逐字核对公式、翻译、编号、分隔符、章节、图片
⑥ 交付    → 图文 Markdown（可选 PDF）
```

---

## ① 准备

1. 定位 PDF 文件（如用 Glob/Shell 搜索文件名关键词）。
2. 建立独立工作目录，例如 `_extracted_<论文名>`，与 PDF 同目录或临时目录。

## ② 提取

用 Python + `pymupdf4llm` 提取文本，并渲染每页高清图：

```bash
python -m pip install pymupdf4llm  # 首次
python - <<'PY'
import pymupdf4llm, fitz
pdf = r"path\to\paper.pdf"
md = pymupdf4llm.to_markdown(pdf)
open(r"workdir\paper.md", "w", encoding="utf-8").write(md)
doc = fitz.open(pdf)
for pno in range(doc.page_count):
    pix = doc[pno].get_pixmap(dpi=150)
    pix.save(rf"workdir\page_{pno+1:02d}.png")
doc.close()
PY
```

**关键**：PDF 中公式常是矢量/图片对象，`to_markdown` 提取的文本层会**丢失公式或丢括号**。因此：
- 文本层 `paper.md` 只作为翻译的**文字基准**；
- 公式的**精确结构必须用页面渲染图逐字确认**（见 ⑤ 审查）。

### 2.1 图片提取：必须按"图注"定位，禁止按内嵌对象顺序

**教训（Zhao2024 案例）**：曾按 PDF 内嵌对象顺序/`extract_paper.py` 的 raw 命名（`xxx.pdf-00NN-XX.png`）直接取图，结果某篇翻译的 `fig1.png`/`fig2.png` 实际是公式截图、`fig6.png`/`fig7.png` 实际是论文的图 4/图 5——PDF 内嵌对象顺序 **不等于** 论文图注编号。整篇翻译因此缺图、位置全乱。

正确做法（两栏排版也适用）：

1. 用 fitz 提取每页以 `Fig.` 开头的**图注文本行**（含页码与 x 坐标判断栏位），顺带记录图注全文：
   ```python
   import fitz
   doc = fitz.open(pdf)
   for pno in range(doc.page_count):
       for blk in doc[pno].get_text('dict')['blocks']:
           if blk.get('type') != 0: continue
           for ln in blk.get('lines', []):
               t = ''.join(s['text'] for s in ln['spans'])
               if t.strip().startswith('Fig.'):
                   print(pno+1, round(ln['bbox'][1]), ln['bbox'][0] < 300 and 'L' or 'R', t.strip()[:120])
   ```
2. 每张图 = 该图注**上方**紧邻的整块区域（图像块 bbox，或矢量图时按栏内边界裁剪）；两栏页面按图注 x 坐标取同栏、按左右两栏分别裁剪。
3. 按 300 dpi `page.get_pixmap(dpi=300, clip=fitz.Rect(...))` 裁剪保存为 `assets/figN.png`（N = 图注编号）。
4. **逐张目视核对**：裁剪后每张图必须与"图 N"标题语义对应（用 Read 打开图片检查），确认整张图完整无裁切（顶部/底部图例切掉即调整 clip 边界重裁）。
5. 以图注为基准统计论文**图总数 M**，翻译后的图清单应有 M 张；漏掉的图（常出现在附录、分栏底部）要补进翻译。

### 2.2 表格提取：原文所有 TABLE 必须转译

- 用 fitz 定位论文全部 `TABLE` 标题（正则 `^TABLE\s+[IVX]+`，含页码/栏位）；
- 渲染每张表（600 DPI 左右）看清**表头、全部行、数值、单位、符号上下标**（如 $D_1^{q1}$ = 0.9 [N·m]）；
- 每个表格必须**完整转译为 Markdown 表格**，保留：表头（原文标题中文 + 表格列头）、全部数值与单位（`[m]`、`[N/m]`、`[kg·m²/rad]`）、符号用行内公式；
- 表格通常跨栏但在单页内；若表格跨页，须把两页部分合并为一张完整表。**不得只在正文提及"见表 X"而不转译表格内容**（Zhao2024 案例：4 张表全漏，仅提及）。

## ③ 翻译

- **不含原文**：输出纯中文翻译 + 公式 + 图片，不并列英文原文。
- **公式**：每个公式用 `$$...$$` 块级显示，`\tag{N}` 保留原文编号。行内符号用 `$...$`。
- **符号说明**：变量符号（如 `$r_{\text{rob},i}$`）在首次出现处给出含义。
- **章节**：保留原文章节结构（摘要 / 引言 / 各节 / 结论 / 附录），可用中文标题 + 原文编号。
- **图片**：论文每个图嵌在对应位置，用相对路径 `assets/figN.png`，图下方写"图 N"标题；`figN.png` 的**内容必须与论文 `Fig. N` 的图注一一对应**（编号与内容双重核对，见 ② 2.1）。
- **表格**：论文每个表都用 Markdown 表格完整转译（标题 + 列头 + 全部行/数值/单位，符号用行内公式），放置在正文引用处附近；**只提及"见表 X"而不转译表格内容视为错误**（见 ② 2.2）。
- **原文笔误**：若原文公式有笔误（如下标不对称），**忠实保留原文**，并在下方加 `> 注释` 说明。

## ④ 精读

在翻译之后追加"# 精读"部分：
- **论文定位**：一句话概括贡献。
- **要解决的问题**：背景、现有方法局限、核心痛点。
- **方法/核心创新**：关键公式含义、设计动机、与现有方法对比。
- **实验设计**：实验设置、关键结果、结果解读。
- **局限与思考**：方法局限、未解决问题。
- 精读中引用的公式编号必须与翻译部分一致。

## ⑤ 审查（必做，逐字核对）

这是本 skill 区别于普通翻译的核心。**必须**按 [verification-guide.md](reference/verification-guide.md) 执行，并至少做两轮。

### 5.1 公式核对

文本层提取的公式**不可信**（丢括号、丢下标）。必须：

1. 用 fitz 的 `get_text('dict')` 提取公式行的坐标与文本，判断结构（如 `J_i^{-T} u_i` 还是 `J_i^{-T}(u_i+...)`）；
2. 对关键公式区域渲染 **800–1600 DPI** 裁剪图，肉眼确认括号、上下标、乘积范围；
3. 逐式比对文档公式与原文，记录差异。

**上下标与"分数 vs 加减"识别要点**（Zhao2024 (35) 案例教训）：
- 上标/下标位置必须放大看清：`D_1^{q1}`（下标 1、上标 q1）易被误认成 `D_{q1}`（下标 q1）或 `D_1^{q1}` 写成 `D_{q1}`；
- 行内"加号 + 列向量"结构易被误认成"分数"：原文 `D(q) = [D_1^{q1}+μq̇_1; D_1^{q2}+μq̇_2]`（加号、无除号）曾被误写成 `D(q̇) = [D_{q1}/(1+μq̇_1); ...]`（分数形式、分子分母颠倒）；
- 函数自变量也需核对：原文是 `D(q)` 不是 `D(q̇)`；
- **交叉验证**：用公式周边的参数表（如 TABLE III 中 `D_1^{q1}=0.9 [N·m]`）核对符号命名（下标 1、上标 q1 与表中一致）；
- **多行矩阵/列向量共同占用一个编号**（如 (35) 的 D(q)+J(q) 两式一组）时，确认共享编号关系与原文一致；原文没有给出的矩阵（如 M(q)、C(q,q̇) 显式形式）**不得补写**。若确有合理补充，须加 `> 注释：原文此处未给出...，此为译者补充。`
- **跨页公式组**（Zhao2024 (35) 二次教训）：多式共用编号的公式组可能**跨页**（编号标注在末式），前一页底部仍有同组公式（如动力学方程、M(q)、C(q,q̇) 在第 7 页底，D(q)、J(q) 在第 8 页顶）。检查方法：定位编号后，把**编号所在页的前一页底部两栏**也渲染出来核对；公式组遗漏判定（"原文没有"）必须以"编号前后页、两栏全部渲染检查后"为准，严禁只查编号所在页就下"原文无此式"结论并删除。

**括号范围 vs 乘法分配歧义**（Zhao2024 (12) 最新案例教训——语义错误、语法合法）：
- 症状：原文 $E_{mult,i} = (I-\eta_{f,i})\left[(I-\eta_{cop,i})\,e_{trac,i} - \eta_{cop,i}e_{cop,i}\right] - \eta_{f,i}e_{f,i}$（方括号内是"两项相减"：第一项被 $(I-\eta_{cop,i})$ 乘，第二项 $\eta_{cop,i}e_{cop,i}$ 在括号内但与第一项平级），被误译为 $(I-\eta_{f,i})\left[(I-\eta_{cop,i})(e_{trac,i} - \eta_{cop,i}e_{cop,i})\right] - \eta_{f,i}e_{f,i}$（把减法序列整体括进第二个乘数）。
- 为什么难发现：两种写法 LaTeX 语法都合法、`\left`/`\right` 都配对，**结构性校验（verify_translation.py）无法检出**；只有对照"推导链"（(12)→(13) 的推导）才能暴露矛盾——原文 (13) 是把 $(I-\eta_{cop,i})e_{trac,i} - \eta_{cop,i}e_{cop,i} \to 0$ 移项得出，若按错误结构展开则无法得到 (13)。
- 识别要点：方括号/圆括号内是 `a·b − c` 还是 `a·(b − c)`，必须**放大页面图逐项确认"减号两侧谁被乘法作用"**；并核对公式旁的**推导注释**——若注释承认"原文字面是 X 结构"而公式写成了 Y，二者必有一错。
- 修复：改 $\left[(I-a)(b-c)\right]$ 为 $\left[(I-a)\,b - a\,c\right]$，并同步修正 **HTML 内嵌 annotation**（`<annotation encoding="application/x-tex">`）与**精读章节**中引用的同一公式——同一公式常在三处出现（md 正文、md 精读、HTML），必须一致。
- 校验快捷法：`grep -n "left.*right" 文档` 对**语义**无效；正确做法是找出每篇公式的**推导下游式**并反推括号结构，或对含 `(I - X)` 类权重矩阵的公式逐一与页面图对照。

### 5.4 图片-图注一致性核对（必做）

图错位是翻译最常见的重大错误（Zhao2024 案例：fig1 是公式截图、fig6/7 实为图 4/5，导致"缺图、位置全乱"）。必须：

1. 列出论文**全部** `Fig.` 图注（编号应连续 1..N，含页码/栏位）；
2. 列出文档全部"图 N"标题与引用的 `assets/figN.png`；
3. 逐一比对：**数量相等、编号连续、图 N 标题语义与论文 Fig.N 图注一致**；
4. 用 Read 逐张目视确认 `figN.png` 内容（而非只对文件名）；
5. 检查文档中图片**出现顺序**与图注编号顺序一致（如正文引用"图 9–12 再看图 13"时，13/14 的图不应插在 9 之前）；
6. 同一图片文件**不得被两次引用**表示两张不同图（如需拆分组合图，用 fitz 按边界裁成两幅）。
7. **表格核对**：提取原文全部 `TABLE` 标题（`^TABLE\s+[IVX]+`），与文档中的 Markdown 表格一一比对（数量相等；表头、每行数值、单位、符号上下标一致）；正文"见表 X"必须伴随实际表格，不得只有提及。

### 5.5 自动验证

运行 `scripts/verify_translation.py`，检查：
- 公式编号 1..N 齐全、无多余；
- `$$` 块配对、行内 `$` 偶数配对、**无 `\(` `\)` 残留**；
- 关键公式字符串存在于文档；
- 章节完整；
- 图片引用与 assets 文件一一对应（每张引用都有文件、每个 assets 文件都被引用）。

### 5.6 翻译核对

逐段比对 PDF 文本层与文档翻译：
- 数字、单位、参数（如 `120 cm`、`0.9 kg`、`1 ms`、`0.28 ms`、`2 N`）；
- 实验条件（如 `η_cop,1 = η_cop,2 = 0.8`）；
- 引文编号、作者名、专有名词。

### 5.7 反复检查

修正后**重跑 5.5 验证**，直到全部通过。若用户要求"反复检查"，至少进行三轮：初查 → 修正 → 复查 → 再修正 → 终查。

## ⑥ 交付

- 输出图文 Markdown：`<论文名>_中文翻译与精读.md` + `assets/` 图片文件夹，相对路径引用。
- 若用户要 PDF：用 minimax-pdf skill 或 KaTeX + Playwright 方案生成（见 reference/verification-guide.md 附录）。

---

## 附加资源

- 详细审查方法论与命令：[reference/verification-guide.md](reference/verification-guide.md)
- 自动验证脚本：[scripts/verify_translation.py](scripts/verify_translation.py)
- 公式区域高清渲染脚本：[scripts/zoom_formula.py](scripts/zoom_formula.py)
- **按图注提取图片脚本**：[scripts/extract_figs_by_caption.py](scripts/extract_figs_by_caption.py)（`--list` 列出全部 Fig. 图注；默认自动按图注区间裁剪生成 `figN.png`；自动结果仍需逐张目视核对）
