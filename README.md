# pdf-translate-review

把学术 PDF 论文翻译成**不含原文的中文图文文档**，并完成**精读**与**逐字审查**的 Agent Skill（基于 `SKILL.md`，Cursor / Claude Code / Codex 等 Agent 通用）。

## 为什么需要它

"PDF 抽文本 → 直接翻"看起来省事，实际处处是坑：

- **公式**：PDF 里的公式常是矢量/位图对象，文本层提取会**丢括号、丢上下标、把 `I` 认成 `1`**——直接照抄文本层，公式必然出错；
- **图片**：PDF 内嵌对象顺序 ≠ 论文图号。按"出现顺序"取图，会出现 `fig1.png` 其实是公式截图、论文图 4 被当成图 6 的情况，整篇图文错位；
- **表格**：跨栏/跨页表格容易被整表漏译，只在正文留一句"见表 X"；
- **公式组**：多行共享一个编号的公式组可能**跨页**，只查编号所在页就会误判"原文没有此式"。

本 skill 把这些教训固化成**流程 + 脚本 + 检查清单**：公式必须基于 800–1600 DPI 渲染图逐字核对；图片必须按 `Fig.` 图注定位；交付前用脚本做结构兜底验证。

## 特性

- **忠实翻译**：纯中文 + 公式 + 原图，不并列英文；公式保留原文编号；原文笔误保留原样并加 `> 注释`
- **逐字审查**：审查方法论（含真实翻车案例）+ 自动验证脚本，交付前至少两轮核对
- **图片按图注配对**：两栏 / 跨栏 / 多子图按图注区间裁剪，禁止按内嵌对象顺序
- **表格全量转译**：`TABLE I…` 全部转成 Markdown 表格，表头、数值、单位逐一核对
- **公式陷阱案例库**：括号范围歧义、跨页公式组、上下标误读、多行共享编号等真实案例与识别要点
- **预览兼容**：统一 `$...$` / `$$...$$` 语法，避免 `\(...\)` 在部分预览器中不渲染

## 安装

```bash
# Cursor 用户级 skills 目录
git clone https://github.com/Marco0431/pdf-translate-review.git ~/.cursor/skills/pdf-translate-review
```

其他 Agent：把仓库目录放入对应的 skills 路径即可，核心是 `SKILL.md`。

依赖：

```bash
python -m pip install pymupdf pymupdf4llm
```

## 目录结构

```
pdf-translate-review/
├── SKILL.md                            # 主说明：翻译 → 精读 → 审查全流程
├── reference/
│   └── verification-guide.md           # 审查方法论与踩坑清单
└── scripts/
    ├── verify_translation.py           # 翻译文档自动验证（编号/分隔符/括号配对/图片/关键式）
    ├── zoom_formula.py                 # 公式区域高清渲染与坐标定位，肉眼核对
    └── extract_figs_by_caption.py      # 按 Fig. 图注定位并裁剪图片（两栏适用）
```

## 使用

### 触发方式

- "翻译这篇论文" / "把这个 PDF 翻译并审查"
- "精读论文"
- "核对 / 逐字核对这份翻译"

### 工作流

```
① 准备 → ② 提取（文本 + 图 + 页面渲染图）→ ③ 翻译 → ④ 精读 → ⑤ 审查（逐字核对）→ ⑥ 交付
```

### 脚本

```bash
# ① 列出论文全部 Fig. 图注（页 / 栏 / 坐标 / 文本），两栏排版也适用
python scripts/extract_figs_by_caption.py paper.pdf --list

# ② 按图注区间自动裁剪出 assets/figN.png（默认 300 dpi；裁完必须逐张目视核对）
python scripts/extract_figs_by_caption.py paper.pdf -o assets
python scripts/extract_figs_by_caption.py paper.pdf -o assets --dpi 300 --col-x 300 --pad 20

# ③ 自动验证翻译文档（编号齐全、$$/$ 配对、无 \( 残留、图片一一对应、关键式存在）
python scripts/verify_translation.py 中文翻译.md \
  --max-eq 48 --assets-dir assets --expect-imgs 12 \
  --key 'J_i^{-T}u_i'

# ④ 关键公式高清渲染，核对括号范围与上下标（--list 先定位，再 --crop 精裁）
python scripts/zoom_formula.py paper.pdf --page 4 --list --kw "E_mult"
python scripts/zoom_formula.py paper.pdf --page 4 --crop 0.02,0.30,0.55,0.35 --dpi 1200 --out eq12.png
```

## 审查为什么必须"逐字"

PDF 文本层对公式极不可靠：公式常是矢量/图片对象，抽取时会丢括号、丢上下标、混淆字形。仅靠"看起来对"或 LaTeX 语法检查**无法**发现语义错误——例如

- `[(I-\eta)\,e_1 - \eta\, e_2]`（两项相减）被写成 `[(I-\eta)(e_1 - \eta e_2)]`（整体相乘）：两种写法语法都合法，只有对照推导链才能暴露矛盾；
- 多行共享编号的公式组跨页，漏掉前一页的部分；
- 下标 `D_1^{q_1}` 被误读成 `D_{q_1}`。

因此本 skill 强制要求：**放大页面渲染图逐项确认**，并用 `verify_translation.py` 做结构性兜底；两者都通过才算交付。完整案例与检查方法见 `reference/verification-guide.md`。

## License

MIT
