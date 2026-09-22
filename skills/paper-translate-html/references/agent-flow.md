# 默认执行方式：当前代理驱动，状态机推进

用户只需给论文与输出要求。由执行技能的代理准备已核对的来源单元并执行后续循环，不把 JSON 文件管理或阶段编排交给用户。使用当前会话的语言与视觉能力，无需另配模型 API。

`translation_flow.py` 已实现编排、请求生成、校验、修正安排和恢复；模型推理仍由当前代理完成。它不自行调用远程模型，不启动后台任务，不自动读取 PDF 的视觉内容。PDF 提取/图表核对和 HTML 验收继续使用 pipeline/quality 中的工具。这是明确的能力边界，不可宣称完全无人值守 API 服务。

## 一次任务的闭环

1. 按 pipeline 提取 PDF，并用页面图确认阅读顺序和图表/公式映射。生成 `source-units.json`，使用现有 document.units 格式（id/page/kind/source）。原始完整 PDF、裁图区和占位符映射留在工作目录。OCR 疑点等放入 `source_flags`，不能用空文字替代失败提取。
2. 启动 flow。它先按预算安排所有来源单元的分析，全部覆盖之后才合并论文上下文与语境术语；单个分析批次已经覆盖全文时直接复用，避免多一次合并调用。没有完成全文准备时不会进入初译。
3. 重复 next → 执行 messages 中的任务 → 将正式 JSON 响应写入文件 → submit。工具返回下一阶段，代理继续，直到 text_reviewed 或 needs_review。next 同时保存请求，意外中断后仍返回同一任务。
4. 初译按相邻完整单元组批。原译对照校对覆盖全部单元，发现错误只修正对应单元；修正后针对最终版本重新做完整文本校对。中文确需改善才追加润色，润色后同样重校。
5. 表格、算法、定理、公式占位符、长单元、提取标记，以及模型提供了具体原文证据的风险触发第二次对照核验。第二次检查不附带先前“通过”的意见。它是独立的核对步骤，不代表使用了另一个独立模型。
6. 通过后 export；还原图片/公式/引用映射，生成 translation.md，构建 HTML 并执行视觉验收。只有这一步完成才能整篇 ready；Zotero 归档按独立授权和账本执行。

```powershell
python scripts/translation_flow.py start --source work/source-units.json --state work/.translation/flow.json
python scripts/translation_flow.py next --state work/.translation/flow.json --out work/.translation/request.json
# 代理读取 request.json 的 messages，完成任务，将正式结果写入 response.json。
python scripts/translation_flow.py submit --state work/.translation/flow.json --request-id <本次request_id> --response work/.translation/response.json
python scripts/translation_flow.py status --state work/.translation/flow.json
python scripts/translation_flow.py export --state work/.translation/flow.json --out-dir work/text-result
```

以上是代理内部调用示例。无需向用户逐项展示命令。请求/响应文件可循环复用，完整已接受响应保存在 flow 账本中；用户主要看到交付件和未解决问题。小任务不因“现代化”强制拆分成许多调用，默认每批最多 8 个完整单元，输入预算 24000 UTF-8 字节；仍需预留模型输出空间，字节数不等于 token 数。超预算报错，不删证据适配。

## 证据与术语

上下文每项含 text、evidence_ids、evidence_quotes。quote 必须逐字出现在对应原文单元，工具会检查。引用真实不意味着解释必然正确，代理必须自行核对条件与语义。

术语除现有 source/target/sense/unit_ids/status/variants 外，必须含 domain、definition、example；example 必须来自其适用单元。不同词义分开，冲突不自动覆盖。`start --glossary <个人术语JSON>` 可读入先前确认过的偏好，文件为列表，每项需要 confirmed_by_user=true 与 source/target/sense/domain/definition/example。只把用户真实确认过的术语放入此文件，不能由模型擅自填写确认标记。

该文件与来源文件在启动时记录哈希，变化后必须新建任务。运行期间不自动修改个人词库；新的修正只有得到用户明确认可才更新，以免一次误判影响后续论文。

风险不能只有置信度分数：模型风险项需要 unit_id、reason 与逐字 source_quote；脚本也根据真实内容类型和提取标记安排额外校对。语言规则无法穷尽所有风险，因此模型发现新疑点仍必须记录并修正。

未解决的校对 findings 必须包含 issue/source_quote/translation_quote/suggestion；原译摘录需与当前版本逐字匹配。漏译问题用译文就近文字作定位锚点。脚本验证出处，执行者负责判断语义；不能用泛泛的“有问题”替代可定位证据。

## 停止、恢复与交付状态

- 默认最多两轮语义修正，可在 start 用 --max-repairs（0..5）明确调整。到上限仍失败时 needs_review，不通过删掉疑点交付。
- 同一阶段连续两次响应不符合数据契约会停止为 needs_review，保留错误原因；第一次失败会把结构问题反馈给下一请求。
- 重复提交同一 request_id 和相同响应幂等；同一请求改交不同响应会拒绝，避免覆盖已接受证据。
- 账本以原子替换保存并核验校验和；同一任务保持单写入者。源文件或个人术语改变会拒绝继续用旧校对；不要手工改账本绕过检查。
- text_reviewed 只表示文本流程完成。导出的 translation.protected.md 仍含受保护占位符，是构建中间件，不能直接当最终译文。没有完成 PDF/HTML 视觉验收时不得标 ready 或自动归档。

测试用合成材料验证编排与错误分支。真实论文质量仍取决于提取、模型执行和视觉核对；不把单元测试通过描述为真实翻译质量提升百分比。
