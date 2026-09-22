# 本机旧实现的接入边界

2026-09-22 已检查：

- 本技能：`C:/Users/Marco/.agents/skills/paper-translate-html`，链接目标为 `C:/Users/Marco/.cursor/skills/paper-translate-html`。
- 共享工具：同级 `pdf-translate-review/scripts/pdfx.py`。
- GitHub 仓库中的共享工具版本可能没有 pdfx.py：以实际文件为准，直接调用 build_html.py/check_source_leaks.py/check_img_dims.py/check_all_html.py；参见 quality.md。不要为匹配本机命令覆盖远程的其他更新。
- 本地参考项目：`G:/资料/paper-daily/scripts/translate_paper.py` 与 `translate_keepimg.py`。换机器时重新定位，不能将此路径当通用安装要求。

本次技能升级没有改动 paper-daily 项目。它们能产生候选 HTML，但尚未实现本技能完整的状态、缓存与归档协议。

## 已确认的行为

- 两个翻译入口都接受 `<paper.pdf> <out_dir> [--title T]`，没有 `--resume`、`--dry-run` 或批次账本参数；不要编造参数。
- `translate_paper.py` 虽有 `rebuild_formulas()`，当前 main 未调用，实际沿用原图路线。
- `_patch_rapidocr()` 直接写第三方安装库文件，**不是运行时 monkey patch**。不要直接运行这个有全局副作用的入口；需要复用时先在独立任务副本中移除此调用，处理对应提取异常并验证，不修改用户项目或全局环境来蒙混过关。
- `llm_call()` 可能将 `reasoning_content` 回填为译文；调用参数还固定含推理设置。使用前必须去掉该回退并按服务能力配置，空正式结果应记失败。
- 验证只打印告警，main 不会因此失败；没有保存足以支持逐块续跑的产物。两个入口的端点与模型默认值不同，应显式传入已授权环境配置。
- 旧图像识别/修复包含尺寸启发式与文件名模糊匹配，不足以证明图号正确；应使用来源映射并人工确认疑似项。
- 两个旧入口默认调用 generate_reading() 追加精读；新翻译流程默认不执行这一步。复用旧入口时在任务副本中关闭它，精读仅按用户明确要求由 paper-reading 单独交付。
- `translate_keepimg.py` 检查时属于用户未跟踪文件，保留原样。

## 推荐接入

当前代理直接按 pipeline 逐块操作，使用自带缓存工具和共享提取/构建脚本即可完成任务；不需要先整修整个旧项目。用户明确要求把旧流水线升级为自动程序时，再修改适配器接入来源清单、缓存、质量状态与归档账本，并实际测试。

共享构建器也是需验收的工具：图片缺失可能仅打印提示，字体备用 URL 可能未内嵌。保留检查失败和解决记录。
