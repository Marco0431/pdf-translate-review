# 审查方法论（PDF 翻译逐字核对指南）

本指南解决一个核心问题：**如何确保翻译文档的每个公式、每句翻译都与原文一致**。

## 为什么必须用渲染图核对公式

PDF 的文本层提取（`to_markdown` / `page.get_text`）对公式极不可靠：

| 现象 | 原因 | 后果 |
|---|---|---|
| 公式整块空白 | 公式是矢量/图片对象，无文本层 | 若凭记忆补写 → 必错 |
| 丢括号 | 大括号/矩阵括号常是独立绘制 | `J_i^{-T}(u_i+f_i)` 被读成 `J_i^{-T}u_i+f_i` |
| 丢上下标 | 上下标是单独文本块 | 下标错、`(I-η)` vs `(1-η)` 分不清 |
| `1` 与 `I` 混淆 | 视觉近似 | 柔顺度因子 `(1-η_f)` 被写成 `(I-η_f)` |
| 乘积范围不明 | 括号丢失 | `(I-η_cop)(e_trac-η_cop e_cop)` vs `(I-η_cop)e_trac-η_cop e_cop` 判错 |

**结论**：文本层只作为翻译的文字基准；**公式的精确结构必须用页面渲染图（800–1600 DPI 裁剪）逐字确认**。

---

## 核对流程

### 第 1 步：建立核对基准

1. 用 `pymupdf4llm` 提取全文文本 → `meta/paper.md`（文字基准）。
2. 用 fitz 渲染每页 150 DPI 整页图 → `page_NN.png`（定位公式位置）。

### 第 2 步：定位公式

用 `scripts/zoom_formula.py` 的列表模式定位含关键符号的行：

```bash
python scripts/zoom_formula.py paper.pdf --page 4 --list \
  --kw "Emult" "eta" "rrob" "etrac"
```

输出含 x/y 坐标的文本行。**同一行内多个片段 + 不同 y 坐标**常表示大括号/分数结构，需裁剪确认。

### 第 3 步：裁剪高清渲染

```bash
# 按页面比例裁剪（如第 4 页中部 30%~35% 区域）
python scripts/zoom_formula.py paper.pdf --page 4 \
  --crop 0.02,0.30,0.55,0.35 --dpi 1200 --out eq12.png

# 或按绝对坐标（先用 --list 拿到 bbox）
python scripts/zoom_formula.py paper.pdf --page 4 \
  --crop-abs 40,318,300,328 --dpi 1600 --out eq12_tight.png
```

用 Read 工具查看渲染图，**逐字符确认**：括号范围、上下标、`I` vs `1`、乘积因子作用范围、加减号。

### 第 4 步：逐式比对

对照原文图，逐式核对文档中的公式。重点核对：
- 右侧结构：`J_i^{-T}u_i+f_i` vs `J_i^{-T}(u_i+f_i)`；
- 括号：`(I-η_cop)(e_trac-η_cop e_cop)` 中 `(I-η_cop)` 乘整个括号还是只乘首项；
- 下标：`η_f,1` vs `η_f,2`、`k_stiff` vs `k_stiff,i`、`D(q)` vs `D(q̇)`；
- 编号：每个公式的 `\tag{N}` 与原文编号一致，不拆分、不合并。

### 第 5 步：自动验证

```bash
python scripts/verify_translation.py 翻译.md \
  --max-eq 38 \
  --assets-dir assets \
  --expect-imgs 15 \
  --section "## 摘要" --section "# 精读" \
  --key 'J_i^{-T}u_i + f_{\text{rob},i}' \
  --key 'D(\dot{q}) = \begin{bmatrix}'
```

该脚本检查：编号齐全、`$$`/`$` 配对、无 `\(` `\)` 残留、章节存在、图片引用对应、关键公式存在。**必须全部通过**。

### 第 6 步：翻译核对

逐段比对文本层与文档翻译，重点检查：
- 数字/单位/参数：`120 cm`、`0.9 kg`、`1 ms`、`0.28 ms`、`2 N`、`2 mm`、`10 N`；
- 条件取值：`η_cop,1=η_cop,2=0.8`、`η_f,1=η_f,2=0`；
- 引文编号 `[n]`、作者名（Krüger、Sun 等）、专有名词（Franka Panda、ACADO、qpOASES）。

### 第 7 步：反复检查

修正后**重跑第 5 步**。若要求"反复检查"，至少三轮：初查 → 修正 → 复查 → 再修正 → 终查。每一轮都重新跑自动验证，直到 0 问题。

---

## 常见陷阱清单（血泪经验）

1. **凭记忆补公式**：文本层空白时，绝不可凭印象写。必须渲染原图。
2. **`C_i` 后漏乘/多乘**：原文 `C_i(r,ṙ)`（阻尼项已是力矩）vs 错误的 `C_i(r,ṙ)ṙ`。
3. **漏 `J_i^T` 或 `J_i^{-T}`**：工作空间控制律常含雅可比转置，方向（正/逆）要看清。
4. **`(I-η)` 的作用范围**：`(I-η_cop)` 是乘整个括号还是只乘 `e_trac`，直接决定式(13)推导是否正确。
5. **`1` 与 `I`**：柔顺度说明文字可能是 `(1-η_f)` 而公式里是 `(I-η_f)`——原文内部就不统一，两处都要按原文保留，可加注释。
6. **公式编号拆子式**：原文一个编号的公式（如式 12、17、35），不要拆成 12a/12b/35a/35e。
7. **行内公式用 `\(...\)`**：Cursor/VS Code 预览不支持，必须用 `$...$`。
8. **原文笔误**：如式(33) 第二行力项下标不对称。忠实保留原文 + 加 `> 注释` 指出，不要"善意修正"。

---

## 原文笔误的处理规范

若发现原文公式笔误（如下标不对称、`(I-η)` vs `(1-η)` 混用、推导不自洽）：

1. **公式本体**：忠实保留原文写法；
2. **加注释**：在该公式下方用 `> 注释：原文此处...` 说明，指出疑似笔误及按对称性应为何；
3. **不擅自改公式**：宁可保留原文笔误加注释，也不可"修成自认为正确的形式"。

---

## 附录：可选 PDF 输出方案

Markdown 交付后，如需生成 PDF：

### 方案 A：KaTeX + Playwright（推荐，公式完美）

1. 本地安装 KaTeX：`npm install katex`
2. 把 Markdown 转 HTML，用 KaTeX 渲染 `$$...$$` 和 `$...$`：
   ```bash
   pandoc 翻译.md -f markdown -t html --katex -s -o report.html
   ```
   （若 pandoc 处理复杂公式失败，改用 content.json 手写 HTML 生成器，KaTeX `throwOnError:false`）
3. Playwright 打印 PDF：
   ```js
   const { chromium } = require('playwright');
   // page.pdf({ format: 'A4', printBackground: true })
   ```
4. 中文需在 HTML 里设置中文字体（如 `Microsoft YaHei`）。

### 方案 B：minimax-pdf skill

用 `minimax-pdf` skill 的 REFORMAT 管道，但需注意其 matplotlib mathtext **不支持** `\boldsymbol`/`\boxed`/`align` 等复杂 LaTeX，且需注入中文字体。复杂论文优先方案 A。
