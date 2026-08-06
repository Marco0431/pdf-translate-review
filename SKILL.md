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

如需图片资源（论文插图、公式截图），可复用 paper-reading skill 的 `extract_paper.py`，或用 fitz 按页面裁剪保存。

## ③ 翻译

- **不含原文**：输出纯中文翻译 + 公式 + 图片，不并列英文原文。
- **公式**：每个公式用 `$$...$$` 块级显示，`\tag{N}` 保留原文编号。行内符号用 `$...$`。
- **符号说明**：变量符号（如 `$r_{\text{rob},i}$`）在首次出现处给出含义。
- **章节**：保留原文章节结构（摘要 / 引言 / 各节 / 结论 / 附录），可用中文标题 + 原文编号。
- **图片**：论文每个图嵌在对应位置，用相对路径 `assets/figN.png`，图下方写"图 N"标题。
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

### 5.2 自动验证

运行 `scripts/verify_translation.py`，检查：
- 公式编号 1..N 齐全、无多余；
- `$$` 块配对、行内 `$` 偶数配对、**无 `\(` `\)` 残留**；
- 关键公式字符串存在于文档；
- 章节完整；
- 图片引用与 assets 文件一一对应。

### 5.3 翻译核对

逐段比对 PDF 文本层与文档翻译：
- 数字、单位、参数（如 `120 cm`、`0.9 kg`、`1 ms`、`0.28 ms`、`2 N`）；
- 实验条件（如 `η_cop,1 = η_cop,2 = 0.8`）；
- 引文编号、作者名、专有名词。

### 5.4 反复检查

修正后**重跑 5.2 验证**，直到全部通过。若用户要求"反复检查"，至少进行三轮：初查 → 修正 → 复查 → 再修正 → 终查。

## ⑥ 交付

- 输出图文 Markdown：`<论文名>_中文翻译与精读.md` + `assets/` 图片文件夹，相对路径引用。
- 若用户要 PDF：用 minimax-pdf skill 或 KaTeX + Playwright 方案生成（见 reference/verification-guide.md 附录）。

---

## 附加资源

- 详细审查方法论与命令：[reference/verification-guide.md](reference/verification-guide.md)
- 自动验证脚本：[scripts/verify_translation.py](scripts/verify_translation.py)
- 公式区域高清渲染脚本：[scripts/zoom_formula.py](scripts/zoom_formula.py)
