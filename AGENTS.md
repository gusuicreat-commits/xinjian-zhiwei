# 芯鉴知微项目开发入口

适用于本仓库全部开发、重构、评测、文档与部署工作。

## 开始工作前

1. 阅读 `README.md` 和 `docs/development-guidelines.md`；后者是项目开发约束的维护位置，尤其遵守第 19 节“模型规范内核”。不在本文件复制规则正文。
2. 涉及诊断、AI、知识或实验包时，阅读 `docs/ai-diagnosis-design.md` 及对应模块设计；涉及评测时阅读 `docs/evaluation.md` 和 `docs/test-reporting.md`。
3. 当前真实性和待验收事项以 `docs/project-truth-status.md`、`docs/implementation-status.md` 及本次实际检查为准。历史报告不能证明当前代码、硬件或生产环境已通过。

## 用户指定规范

用户于 2026-09-17 要求后续开发严格遵循《芯鉴知微模型规格与开发实施规范》的内核。完整原文保存在 `docs/references/model-spec-2026-09-17.md`，来源为 ChatGPT 对话“模型规范撰写”（`6aab5ab7-24e8-83ea-8ddd-5fbe74085804`）。

原文是来源快照；持续生效的内核、示例解释与建议的适用边界统一维护在 `docs/development-guidelines.md` 第 19 节。不能把原文中的示意 Schema、模型推荐、历史配置或实施清单当作已验证实现，也不能用现有实现偏离规范的事实为偏离辩护。

变更前对照上述约束，变更后执行与影响相称的检查。跨越架构边界时，按开发准则形成可审查决策，同步契约、实现、测试和文档。用户当前明确要求及更高优先级约束优先。
