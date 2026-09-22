# 质量与离线交付

## 公式、图表和格式

公式重建必须有可读原图佐证，无法可靠恢复时内嵌清晰原图并保留编号。原图裁剪也要检查边界、上下标、编号与出处，不能将其描述为无条件“100% 忠实”。视觉检查分辨率按清晰度提高，不强制所有页超高 DPI。

图以图注和页面位置定位，多子图完整保留标签，矢量文字不能因位图 bbox 被裁掉。检查边界上下文和图注语义，裁掉紧邻正文，不能只凭文件名和像素尺寸配图。

表格保留表头、单位、脚注、数值与显著性标记。简单表转 Markdown，复杂表用安全 HTML 表格（先确认渲染器支持，不能在禁用原生 HTML 的模板里直接插入）；无法可靠重建时保留表图并翻译标题/注释，记录 `table_image_fallback` 及无法编辑的限制。不要静默丢弃表格。

Codex 对话中行内数学使用 `\(...\)`，块级使用 `$$...$$`。本地 Markdown 源与渲染器按实际支持配置：部分本地版本的 `pdfx build` 会将反斜杠定界符归一为 dollars 模式；仓库旧构建器与 `verify/katex` 检查器仅认识 dollars，构建/检查前需准备归一化的临时副本并保留原稿。先确认实际脚本是否具备归一化功能，不把本地功能当作所有版本都有。不能全局宣称某种定界符永远不可用。

HTML 默认静态预渲染公式，内嵌实际使用的字体、图片和样式；仅在部署环境适合时使用内嵌 auto-render。参考文献/DOI 普通链接可保留，离线要求是阅读与渲染不依赖网络。正文采用 UTF-8、合理行宽、目录锚点、移动视口；宽表/公式可横向滚动，不能为挤下内容缩到难以阅读。打印布局与正常阅读应都可用。

## 验收分层

文本阶段先按 [translation-quality.md](translation-quality.md) 生成 text-qa.json，确认原译对齐与最终版本对照审校。工具的 reviewed 只表示文本阶段通过，不跳过以下图表与渲染核对。

1. **内容完整性**：按来源清单检查章节、正文块、图表、附录和参考文献；占位符已正确还原，数字/单位差异已核对。原始编号可以不连续。
2. **结构检查**：公式语法、图片解码与映射、表格列数/单元格、重复内容和可见源码残留。计数相等不能证明语义对应。
3. **渲染检查**：实际浏览器打开，等待字体与图片加载，查看宽屏/窄屏下公式编号、长表、图注与页面边界。静态检查不是视觉验证。
4. **忠实性复核**：高风险公式、关键结论和数值、OCR 区、复杂图表重点对照原 PDF；用户要求逐页核对时逐页做。记录具体页码与覆盖范围，不虚称全文逐字复核。

`qa.json` 至少记录每项 `name/status(passed|failed|skipped)/evidence`，另记 `visual_review` 覆盖页码与待查项。检查依赖不可用时写 skipped；缺失必要验收时状态为 `needs_review`。

`warnings.json` 是问题数组，每项含 `code`、`severity(error|warning|info)`、`stage`、`block_id`（可空）、`page`（可空）、`message`、`resolved`。修复后保留记录并标记 resolved，不只在日志打印。

- 阻止 ready：未译正文、缺章节/图表、关键数值未确认、错配图片、截断公式、破图、外部渲染依赖、可见推理/模板残留、必需检查失败/未执行。
- 可带说明 ready：经过核对的公式原图或表格原图回退、非关键排版限制；读者须能得到完整信息。
- 检查器误报：保存原因和复核证据，标记解决；不能整类关闭检查后声称全部通过。

## 共享工具的真实边界

共享工具可以来自同级 `pdf-translate-review/scripts`，或者本技能打包仓库根目录的 scripts。以独立安装布局为例，所有已发布版本均可用的基础步骤如下；`--help` 确认实际参数后执行：

```powershell
python ../pdf-translate-review/scripts/build_html.py work/translation.md work/translation.html
python ../pdf-translate-review/scripts/check_source_leaks.py work/translation.html
python ../pdf-translate-review/scripts/check_img_dims.py work/translation.html
python ../pdf-translate-review/scripts/check_all_html.py work/translation.html
```

在仓库 skills/paper-translate-html 内执行时把上述脚本前缀改为 `../../scripts/`。若已安装版本有 pdfx.py，可改用 build/check 组合命令及 --json 输出；否则将各检查结果汇总进 qa.json，不编造统一入口。

check_img_order.py 的 `--expected 1,2,3` 仅适合解析器覆盖的图号；verify_translation.py 的 `--max-eq` 不适合附录编号/跳号。源码检查器可能把合法重复图等视为错误，结合来源清单核实。check_crop_fidelity.py / check_image_ghosts.py 的像素核对用于疑似裁图缺失、重影或精细审查；它依赖候选区域推断，不能取代目视。

源码检查器可能把 KaTeX CSS 中未内嵌的备用字体 URL 漏掉；额外检查 `src/srcset`、样式 `url()`、`@import` 与脚本引用，实际断网打开验证。检测到缺失资源时修复或标待复核，不因某个脚本退出 0 就跳过交付标准。
