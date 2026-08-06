# pdf-translate-review

将学术 PDF 论文翻译为不含原文的**中文图文 Markdown**，并完成**精读**与**逐字审查**的 Cursor Agent Skill。

## 特性

- **忠实翻译**：输出纯中文翻译 + 公式 + 图片，不并列英文原文，公式保留原文编号。
- **逐字审查**：内置验证脚本 + 方法论，确保每个公式与原文逐字一致，杜绝"凭记忆补公式"导致的错误。
- **公式安全**：统一使用 `$...$` / `$$...$$` 语法，兼容 Cursor / VS Code / Typora 预览。
- **图文并茂**：自动嵌入论文原图，图片相对路径引用。
- **精读输出**：论文定位 / 要解决的问题 / 方法核心 / 实验设计 / 局限思考。

## 安装

```bash
# 克隆到 Cursor 用户级 skills 目录
git clone https://github.com/Marco0431/pdf-translate-review.git \
  ~/.cursor/skills/pdf-translate-review
```

重启 Cursor 后生效。之后说"翻译这篇论文"或"把这个 PDF 翻译并审查"，即可自动触发。

## 目录结构

```
pdf-translate-review/
├── SKILL.md                          # 主说明：翻译→精读→审查全流程
├── reference/
│   └── verification-guide.md         # 审查方法论（含踩坑清单）
└── scripts/
    ├── verify_translation.py         # 自动验证翻译文档完整性
    └── zoom_formula.py              # 公式区域高清渲染 / 坐标提取
```

## 使用

### 触发

- 用户要求"翻译论文/PDF"、"translate this paper"
- 用户要求"精读论文"
- 用户要求"审查/核对/逐字核对"翻译

### 工作流

```
① 准备 → ② 提取（文本+图片+渲染图）→ ③ 翻译 → ④ 精读 → ⑤ 审查（逐字核对）→ ⑥ 交付
```

### 脚本

```bash
# 自动验证翻译文档（检查编号、公式配对、无 \( 残留、章节、图片、关键公式）
python scripts/verify_translation.py 翻译.md \
  --max-eq 38 --assets-dir assets --expect-imgs 15 \
  --key 'J_i^{-T}u_i + f_{\text{rob},i}'

# 定位并高清渲染 PDF 公式区域（核对括号/上下标）
python scripts/zoom_formula.py paper.pdf --page 4 --list --kw "Emult" --kw "etrac"
python scripts/zoom_formula.py paper.pdf --page 4 --crop 0.02,0.30,0.55,0.35 --dpi 1200 --out eq12.png
```

## 为什么需要"逐字审查"

PDF 文本层提取对公式极不可靠：公式常是矢量/图片对象，提取时会**丢括号、丢上下标、混淆 `I` 与 `1`**。本 skill 强制要求用 **800–1600 DPI 渲染图逐字确认公式**，并用自动脚本兜底检查，从根本上避免"公式与原文不符"的问题。详见 `reference/verification-guide.md`。

## License

MIT
