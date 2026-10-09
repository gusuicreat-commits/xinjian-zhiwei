# 芯鉴知微项目开发入口

适用于本仓库全部开发、重构、评测、文档与部署工作。

## 开始工作前

1. 阅读 `README.md` 和 `docs/development-guidelines.md`；后者是项目开发约束的唯一维护位置。按任务查阅[模型规范内核](docs/development-guidelines.md#model-core)、[业务规则](docs/development-guidelines.md#business-rules)、[修复 Bug](docs/development-guidelines.md#fix-bugs)和[AI质检](docs/development-guidelines.md#ai-quality)，再用[规则对应表](docs/development-guidelines.md#rule-map)定位所有入口与反例。不在本文件复制规则正文。
2. 涉及诊断、AI、知识或实验包时，阅读 `docs/ai-diagnosis-design.md` 及对应模块设计；涉及评测时阅读 `docs/evaluation.md` 和 `docs/test-reporting.md`。
3. 当前真实性和待验收事项以 `docs/project-truth-status.md`、`docs/implementation-status.md` 及本次实际检查为准。历史报告不能证明当前代码、硬件或生产环境已通过。

## 开发流程

1. 每个任务单一目的，改动控制在可审查规模；按“复现→定位→方案→修改→测试”推进。
2. 执行与验收分离；验收须独立复跑真实链路，核对实际差异、持久化与副作用，不能只看执行方报告。
3. 新增/删除接口或改变鉴权须同步登记 `backend/app/api/access_policy.py`，通过 `tests/test_access_policy.py`。
4. 新增流水线派生测试数据须用 `backend/tests/pipeline.py`，通过 `tests/test_fixture_provenance.py`，手工构造白名单仅降不升。
5. 新的宽泛异常捕获受 `tests/test_error_handling_gate.py` 门禁约束，复用 `app/core/errors.py` 分类，捕获白名单仅降不升。
6. 完成相关验证、核对契约与文档、清理无用临时文件后再提交；提交仍须在任务授权范围内。

## 用户指定规范

用户于 2026-09-17 要求后续开发严格遵循《芯鉴知微模型规格与开发实施规范》的内核。完整原文保存在 `docs/references/model-spec-2026-09-17.md`，来源为 ChatGPT 对话“模型规范撰写”（`6aab5ab7-24e8-83ea-8ddd-5fbe74085804`）。

原文是来源快照；持续生效的内核、示例解释与建议的适用边界统一维护在[模型规范内核](docs/development-guidelines.md#model-core)。不能把原文中的示意 Schema、模型推荐、历史配置或实施清单当作已验证实现，也不能用现有实现偏离规范的事实为偏离辩护。

变更前对照上述约束，变更后执行与影响相称的检查。跨越架构边界时，按开发准则形成可审查决策，同步契约、实现、测试和文档。用户当前明确要求及更高优先级约束优先。
