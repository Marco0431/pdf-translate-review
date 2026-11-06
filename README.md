[English quick start](README.en.md) · **简体中文**

# pdf-translate-review

把学术 PDF 论文翻译成**保留原图、公式与表格的中文文档**，对照原文校对，再按需生成可离线阅读的单文件 HTML。包含 Agent Skills 与本地 Python / Node.js 工具，面向需要完整译文的论文读者。

**English:** Agent skills and local tools for translating academic PDFs into Chinese Markdown or self-contained offline HTML, with original figures, equation verification, translation review, resumable batch workflows, and optional Zotero archiving. Translation is performed by the agent; the scripts handle extraction, checks, state, and rendering.

[安装](#安装) · [无需论文的试跑](#无需论文的试跑) · [使用示例](#使用示例) · [单篇技能](SKILL.md) · [批量技能](skills/paper-translate-html/SKILL.md) · [反馈](#问题反馈与贡献)

## 从这里开始

| 你想做什么 | 入口 | 交付内容 |
|---|---|---|
| 翻译一篇论文，并逐项核对公式、图表 | [pdf-translate-review](SKILL.md) | 中文图文 Markdown；可选离线 HTML |
| 批量翻译、续跑失败任务或归档到 Zotero | [paper-translate-html](skills/paper-translate-html/SKILL.md) | 每篇译文、来源映射、校对与归档状态 |
| 已有译文，检查公式或生成离线文件 | [两条产出流水线](#两条产出流水线) | 结构/语法检查与 HTML 构建工具 |

需要支持 `SKILL.md` 的代理环境及下方列出的本地依赖。`review` 指**译文与原文对照校对**；这些脚本不独立调用翻译模型，也不能用自动检查代替原文与页面的人工/代理复核。

如果你想在 Zotero 阅读时选中段落即时追问，可另看 [AskGPT](https://github.com/Marco0431/askgpt-zotero)；本仓库面向完整译稿的制作与校对，是独立的技能工作流。

## 无需论文的试跑

先用仓库内的合成样本体验“原文 + 译文 + 术语 → 校对材料”。只需要 Git 和 Python（测试使用 Python 3.12），无需 PDF、模型账户或第三方 Python 包。以下命令在克隆后的仓库根目录执行：

```sh
git clone https://github.com/Marco0431/pdf-translate-review.git
cd pdf-translate-review
python skills/paper-translate-html/scripts/translation_workbench.py packet --stage review --document skills/paper-translate-html/tests/fixtures/translation-case.json --translations skills/paper-translate-html/tests/fixtures/translation-good.json --out review-demo.json
```

成功后会生成 `review-demo.json`，其中包含 5 个来源片段及对应译文。样本特意把同一个英文词 `policy` 分别译为控制“策略”和安全“规定”，并保留仿真条件与真实机器人表现尚未确认的限制；这是校对材料的演示，**没有调用模型或完成校对**。生成文件可直接用文本编辑器查看，用完可删除。

准备处理自己的 PDF 时，继续下方安装与使用示例；整个流程的模型执行由你的代理环境负责，账户费用和论文数据处理方式取决于所用代理及模型服务。离线 HTML 指交付文件可离线阅读，不代表模型翻译过程离线运行。

## 使用示例

安装后，把本地 PDF 路径交给代理，例如：

```text
使用 pdf-translate-review 翻译 ./paper.pdf，输出到 ./out/。
保留全部章节、原图、公式编号和表格，只输出中文译文。
逐项对照原文校对，并生成离线自包含 HTML；报告未通过或未完成的检查。
```

`paper.pdf` 是你提供的输入文件，仓库未附带示例论文或已完成的论文译稿。以下命令对应现有脚本，先提取资料；**翻译与校对由代理完成**后，再构建 HTML：

```bash
python scripts/extract_pdf.py paper.pdf --out out/
# 按 SKILL.md 完成翻译、配图和原译对照，将译文保存为 out/translation.md
python scripts/build_html.py out/translation.md out/translation.html
```

HTML 构建成功后仍需执行下方[验收流程](#流水线-b离线自包含-html)，包括图片保真、公式渲染与原文核对。无需 PDF 的小型示例可查看现有[翻译回归样本](skills/paper-translate-html/tests/fixtures/translation-case.json)及[对照译文](skills/paper-translate-html/tests/fixtures/translation-good.json)；它们是明确标注的合成测试材料，不是论文翻译效果展示。

## 工作流

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

### 批量翻译技能

本仓库同时维护 [paper-translate-html](skills/paper-translate-html/SKILL.md)：批量翻译、按语境管理术语、原译对照校对、可恢复缓存及 Zotero 归档。`review` 指翻译质量校对；论文精读交给 `paper-reading`，默认不追加精读或学术评价。

批量技能位于 `skills/paper-translate-html/`，可直接指定该 SKILL.md 使用；也可将该目录安装到用户 skills 目录，与 pdf-translate-review 并列。两个技能共用本仓库的 PDF/HTML 工具。直接在 bundled 目录执行时，共享脚本路径为 `../../scripts/`；并列安装时为 `../pdf-translate-review/scripts/`。只复制技能文件，不复制其他仓库的 .git 或私人术语库。

```bash
python -m unittest discover -s skills/paper-translate-html/tests -v
```

提示默认紧凑序列化，plan 按预算将相邻完整段落组批；不截断来源证据、不跳过语义校对。参数与限制见 [效率说明](skills/paper-translate-html/references/efficiency.md)。

默认使用 [译准执行流程](skills/paper-translate-html/references/agent-flow.md)：当前代理按状态机完成全文准备、语境术语、初译、原译校对、定点修正和风险复核。支持中断续跑与逐字证据检查，不要求额外 API 密钥；模型任务仍由当前代理执行。文本流程通过后继续 PDF 图表及 HTML 视觉验收，不能把文本通过当作整篇交付完成。

### 单篇翻译技能

```bash
# Cursor 用户级 skills 目录
git clone https://github.com/Marco0431/pdf-translate-review.git ~/.cursor/skills/pdf-translate-review
cd ~/.cursor/skills/pdf-translate-review
```

其他 Agent：把仓库目录放入对应的 skills 路径即可，核心是 `SKILL.md`。

如果已经按上方试跑命令克隆过仓库，可直接使用该目录的 `SKILL.md`，或将完整仓库放入代理的技能目录；无需重复克隆。下面的依赖命令都应在含 `package.json` 的仓库根目录运行。

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
├── SKILL.md                            # Agent skill 入口：翻译 → 对照校对 → 审查 → 交付全流程
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
    ├── check_crop_fidelity.py          # 检查：内嵌图与原 PDF 逐张对位（保真 + 槽位编号）
    ├── check_image_ghosts.py           # 检查：内嵌图“重影”（截图二次曝光）——墨迹记账判据
    ├── sync_zotero.py                  # 归档：把修好的 HTML 覆盖到 Zotero 附件存储
    └── vendor_katex.py                 # 部署：导出 KaTeX/markdown-it 离线资源到 vendor 目录
```

## 两条产出流水线

### 流水线 A：图文 Markdown（翻译与校对）

```bash
# ① 提取：文本基准 + 页面渲染图 + 内嵌图片（公式结构后续用渲染图核对）
python scripts/extract_pdf.py paper.pdf --out out/

# ② 按图注列出全部图，再裁剪成 out/assets/figN.png（裁完逐张目视核对）
python scripts/extract_figs_by_caption.py paper.pdf --list
python scripts/extract_figs_by_caption.py paper.pdf -o out/assets --dpi 300 --col-x 300

# ③ 翻译与校对：产出 translation.md（引用 assets/figN.png）

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
python scripts/check_crop_fidelity.py --html out.html --pdf paper.pdf --name Proj --out fidelity/   # 内嵌图与原文逐张对位（交付 HTML 时必跑）
python scripts/check_image_ghosts.py --html out.html --pdf paper.pdf --out ghosts/           # 内嵌图重影检查（交付 HTML 时必跑）

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

[MIT](LICENSE)

## 问题反馈与贡献

[报告问题](https://github.com/Marco0431/pdf-translate-review/issues/new?template=bug_report.md)时，请提供失败的命令、操作系统、Python / Node.js 版本、预期结果和报错。公式或图片问题请附上页码及可公开的最小片段；不要上传未经授权的整篇论文、私人 Zotero 数据或凭据。

欢迎提供可公开复现的图表边界案例、术语歧义案例和安装说明修正。改动批量校对工具时可运行 `python -m unittest discover -s skills/paper-translate-html/tests -v`。更多入口见 [文档索引](llms.txt)。
