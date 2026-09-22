# 翻译质量：全文理解、语境术语、原译对照

当前执行者负责理解与审校，`translation_workbench.py` 组装材料并检查对齐和版本。工具不调用模型，不凭正则证明准确性。可在主会话执行，也可将生成的 messages 交给已授权的批量模型。

默认使用 [agent-flow.md](agent-flow.md) 中的状态机自动推进这些阶段。下文说明底层数据与校对要求，通常不需要代理手工编排每一步。

本文件 review 仅指翻译对照校对，与 paper-reading（精读理解）和 paper-review（学术审稿）分开。内部上下文用于译文消歧，不自动变成精读交付件。

## 1. 论文上下文

提取全文并确认页数覆盖后，先通读摘要、引言、方法、实验和结论，再扫描其余章节。生成简洁的 `paper-context.json`：研究问题、对象、方法组成、术语定义、符号/缩写、主要结论及适用边界。每项事实带来源单元 `evidence_ids`；原文未说明的保持不确定，不用领域常识填空。

上下文用于消歧，不能覆盖当前段落的实际表述。实验中的“成功率”不能自动替换其他段落的“准确率”。原文矛盾或疑似笔误保留并译注，不擅自统一不同章节的论断强度。

给段落、图注、表格、算法、定理、文献分配稳定 ID。长段可按句群拆分，避免在缩写、公式或指代中间切开；可读性优先于机械逐句对应。ID 分配后不在翻译时重编号，每单元记录 PDF 物理页码及可选 section/bbox。

## 2. 语境术语库

`glossary.json` 每项含 `id/source/target/sense/unit_ids/status/variants`。`sense` 说明本篇词义，`unit_ids` 限定适用范围，`status` 为 approved 或 candidate。当前执行者依据原文消歧后可批准本篇术语，无需逐词询问用户；用户已有明确译法优先。

默认 flow 进一步要求 domain、definition、example，并验证 example 为适用单元中的原文；旧 workbench 文件可继续使用较小的兼容格式。flow 可导入用户确认的跨论文术语，仍需按本篇词义匹配。

同一 source 可以有多个 sense 和不同 target，例如控制策略的 policy 与安全规定的 policy。批准前检查范围重叠处是否冲突。缩写首次出现给中文全称并保留必要缩写，之后一致地简写；variants 只列经确认的等价表达，不用于掩盖词义变化。

跨论文词库可存于本技能 `assets/personal-glossary.json`（确需时再创建），额外记录领域、来源论文和确认来源。新论文先匹配定义并作为 candidate；用户明确修正或要求记住的译法可以写入个人库，不能将模型本次猜测升级成永久偏好。修改词库不能静默改变已完成论文。

## 3. 数据契约

把上下文、术语与来源单元组装为 `document.json`，作为本次翻译的输入快照：

```json
{
  "schema_version": 1,
  "context": [
    {"text": "研究对象为机器人控制策略；此句仅涉及仿真。", "evidence_ids": ["p001-b001"]}
  ],
  "glossary": [
    {"id": "control-policy", "source": "policy", "target": "策略", "sense": "机器人控制决策规则", "unit_ids": ["p001-b001"], "status": "approved", "variants": ["控制策略"]}
  ],
  "units": [
    {"id": "p001-b001", "page": 1, "kind": "prose", "source": "The robot control policy may improve performance in simulation."}
  ]
}
```

context、glossary 与对应旁车文件同步后冻结快照。kind 支持 heading/prose/caption/table/algorithm/theorem/reference。译文为 `{"units":[{"id":"p001-b001","text":"该机器人控制策略可能改善仿真中的表现。"}]}`，ID 与来源严格一一对应且保持顺序。允许在同一 ID 内重排语序，不跨 ID 搬移内容。

缓存 profile 增加 inputs，例如 `{"document":"document.json","context":"paper-context.json","glossary":"glossary.json"}`，路径相对于 profile 文件。缓存工具自动记录并重核这些文件的哈希；修改任意文件需创建新缓存。旧 profile 仍可读，新质量流程必须登记上述依赖。

## 4. 初译 → 对照审校 → 可选润色 → 终审

以下以技能根目录为工作目录。packet 输出含 system/user messages 的 JSON，不是译文；当前执行者读取消息并执行任务，或由已授权 API 执行，响应另存。

```powershell
python scripts/translation_workbench.py packet --stage draft --document work/document.json --ids p001-b001 --out work/draft-packet.json
python scripts/translation_workbench.py check --document work/document.json --translations work/translations.json --out work/check-before-review.json
python scripts/translation_workbench.py packet --stage review --document work/document.json --translations work/translations.json --out work/review-packet.json
python scripts/translation_workbench.py packet --stage polish --document work/document.json --translations work/translations.json --out work/polish-packet.json
python scripts/translation_workbench.py check --document work/document.json --translations work/translations.json --review work/translation-review.json --out work/text-qa.json
```

`--ids` 接受逗号分隔的源 ID，用于控制提示长度。工具附带全文上下文、关联术语、上下文证据和邻段作为只读资料；证据过大时细分来源单元并重建快照，不截断证据假装完整。逐块响应按源顺序汇总成全篇 translations.json 后做全篇检查。分块审校需基于同一份冻结译文，合并全部 review.units 和 decisions，不能混合不同哈希的记录。

首轮对照审校解决误译；仅在中文表达仍需改善时润色。润色后保存新译文，再生成 review packet 复核最终文字，最后运行带 review 的 check。译文未修改时可复用首轮合格审校，不强制空跑额外轮次。

审校覆盖：

- coverage：遗漏/增译、限定语、括注、脚注和解释。
- logic：否定、条件、因果与相关、比较基准、主语、跨段指代。
- claim_strength：may/can/suggest/show/demonstrate、显著性、泛化与实验条件；不能把“未观察到差异”译成“证明没有差异”。
- terminology：词义、译法一致性、缩写首现及符号含义。
- numbers_units：数字、正负、范围、百分数与百分点、单位、样本量、图表引用。
- readability：自然中文同时保持原意，流畅不能抵消遗漏。

特殊内容另查图注子图对应 panel_mapping、表格单元格/脚注 cells_footnotes、算法变量/控制流程 variables_control_flow、定理条件/量词 conditions_quantifiers、文献检索身份 bibliographic_identity。工具要求记录覆盖，语义必须由执行者核对。

## 5. 审校结果和门槛

review packet 给出精确 document_sha256、translation_sha256 与响应结构。reviewer 记录真实执行者/模型；每单元填写 verdict（passed/needs_review）、已完成 checks、尚未解决 findings。findings 指出原文片段、译文片段、原因与建议修正；passed 必须无遗留问题。

- 硬错误：缺失/多出/错序 ID、空译文、占位符 ID 或次数变化。不能用说明豁免，必须修正。
- 候选差异：阿拉伯数字集合变化、指定范围内未出现批准术语。合法格式或译法差异可在 review.decisions 中以 issue ID 为键记录原文依据与接受原因；其他情况修正译文。候选既不能自动放行，也不能直接定性为误译。

最终 check 核验输入/译文哈希、审校覆盖、硬错误和候选处理。退出码 0 表示文本阶段 reviewed，2 表示 needs_review，1 表示输入/运行错误；reviewed 不等于整篇 ready，仍需 PDF 图表核对、HTML 构建与视觉验收。

阿拉伯数字比较不识别所有中文数字、等价单位、公式内数字或否定错误；不能取代原译对照。扫描区、关键结论、歧义指代及密集公式增加证据核对，风险按实际内容判断，不靠模型自报置信度。

## 6. 迭代评测

tests/fixtures 中的 translation-case.json 与 translation-good.json 是原创合成材料，覆盖两种 policy 词义、条件与论断强度、图注及表格；用于验证工具行为，不证明真实论文质量已经提升。

真实评测用用户熟悉且本地可用的固定片段，保留原 PDF 区域及人工审定译文，分别统计漏译/增译、逻辑与论断强度错误、术语错误、数值错误、人工修改量和调用成本。比较同一材料与模型配置下启用前后结果，记录 reviewer 和证据；没有真实评测时不宣称提升百分比。
