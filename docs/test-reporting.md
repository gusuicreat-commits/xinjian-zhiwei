# 测试报告约定

本文维护报告位置、格式、退出码和保留方式。运行依赖与命令见 [测试与评测](evaluation.md)，交付证据要求见 [开发准则](development-guidelines.md#validation)。

## 位置与生成范围

| 内容 | 位置 | 生成条件与 Git 边界 |
| --- | --- | --- |
| 本机流程摘要 | `output/workflow-evaluation/local-latest.md` | `verify.sh` 流程步骤或同名 CLI 输出；Git 忽略 |
| 简明机器结果、源码和输入指纹 | 同目录 `local-latest.json` | 同上；不是整个 verify 的聚合报告 |
| 完整排错附件 | 同目录 `local-latest.details.json.gz` | 按 details 策略生成；Git 忽略 |
| CI 流程结果 | 同目录 `ci-postgres.*` | Markdown 写入 Job Summary，目录上传 artifact |
| 浏览器结果 | `frontend/playwright-report/`、`frontend/test-results/` | CI 上传这两个目录；Mock E2E 本机默认仅 list 输出，真实联调生成 HTML/JSON，失败按配置保存截图 |
| 专项取证 | `output/audits/` 与 `output/workflow-evaluation/` 中明确命名的结果 | 按需保存，Git 忽略；并非每次 verify 都自动生成 |

自动运行报告不新增到 `docs/`。指南、要求映射和有独特决策价值的历史记录可以保留在文档目录，但必须标明用途和日期；不能把一次报告复制成第二份持续规则。

## 完整流程报告

使用 [流程评测命令](evaluation.md#3-分层定位失败)。`--output` 必填且以 `.json` 结尾，工具同时生成同名 Markdown；`verify.sh` 默认使用 `output/workflow-evaluation/local-latest.json`，可通过 `WORKFLOW_EVALUATION_REPORT` 改名。

| 参数 | 保存内容 |
| --- | --- |
| `--details failures`（默认） | 简明结果，加失败/执行错误场景的完整 gzip 附件 |
| `--details all` | 简明结果，加全部已执行场景的完整附件，适用于保留专项取证 |
| `--details none` | 仅简明结果；失败项名称仍保留 |

简明格式标记为 `report_format=workflow-summary-v1`。`cases` 保存场景状态、检查数量及失败项，不包含全部快照/预期/实际值；这些内容从附件读取。通过场景的完整材料必须显式使用 `--details all`。

| 退出码 | 完整流程含义 |
| --- | --- |
| 0 | 全部流程场景的软件检查通过 |
| 1 | 断言失败或执行错误 |
| 2 | 数据库环境受阻，或场景未完成 |

## 合成诊断报告

`run_synthetic_evaluation` 使用 `evaluation_version=7-code-and-semantic-separated`：`code_checks_passed` 表示代码检查，`pattern_scan` 只记录出现的片段；`semantic_review` 未审阅时为 `not_run` / `judgement=null`，总体 `status=incomplete`。该 CLI 退出 0 只代表代码检查通过，与完整流程 CLI 的退出码语义不同。

旧版 `passed`、`forbidden_claims` 或 v6 字段不作为当前消费契约。两类报告均不证明真实模型语义、硬件或课堂效果已通过。

## 保留与敏感信息

- 同一路径的新运行覆盖上次摘要与 JSON；本次没有附件时会删除该路径对应的旧附件，避免串读。需保留失败基线时使用独立文件名，不依赖 `latest`。
- 其他历史文件不自动删除。历史链接用于溯源，文件缺失时应标记证据不可取得，不能用旧文字补作通过。
- CI 的流程与浏览器 artifact 保留 14 天；这是项目配置，不代表本机清理策略。Job Summary 中本机相对链接不是在线附件地址，应从该次 Actions artifact 下载。
- 摘要只描述本次流程评测。后端、前端、固件、迁移等结果分别附实际命令、环境、源码状态与退出码；不得借用历史数量拼成“全量通过”。失败后未执行的后续步骤应写未执行。
- 详细附件可能包含合成请求、快照和页面内容。保留测试边界，分享前核对凭据和个人信息；历史只读清单只保留记录 ID、固定原因与数量，不导出私密正文。

## 格式实现与参考

实际写入规则见 [reporting.py](../backend/app/evaluation/reporting.py)；上传范围见 [CI](../.github/workflows/ci.yml)；浏览器格式见 [Mock 配置](../frontend/playwright.config.ts) 与 [真实联调配置](../frontend/playwright.integration.config.ts)。

外部设计参考：[Playwright Reporters](https://playwright.dev/docs/test-reporters)、[GitHub artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data)、[Job Summary](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)。实际项目行为以上述仓库配置为准。

## 上下文评测报告

`context-evaluation-v1` 同名JSON/Markdown输出到 `output/context-evaluation/`；JSON保留逐项代码断言、归因、输入/源码指纹、语义/真实Provider/硬件/保留集状态。代码退出0不等于语义通过，1是检查失败或执行错误，2是必需软件材料缺失/损坏。语义缺材料为not_run/null；0次真实调用、Token和费用未知不得写成已验证的成本收益。软件服务/并发/浏览器门禁另存本次审计报告，不把纯选择器报告扩称端到端验收。

资料包预检使用`package-context-preview-v1`：分开structure、source_traceability、stage_coverage；来源identity比对与内容可信性分开。报告仅存定位、长度、有限条件状态、固定省略原因和指纹，不保存私密审核正文或完整Prompt。输入/预期分离，严格评测与普通分析退出语义不同，见[预检命令](evaluation.md#package-context-preview)。P4概念解释检查须单列未实施，不能随P0–P3软件门禁标通过。


## 受控查询报告

`query-evaluation-v1` 将 Markdown/JSON 保存到显式 `--output` 路径（必须为 `.json`）。
逐例保存真实固定图 A、B0_scripted、确定性查询、相同材料合同探针/实际推理服务回放、步骤、计数、
输入/预期/答复指纹与独立断言。选择替身次数不计真实 Provider 调用；合成语义未审为 `not_run/null`。
退出0表示所选软件断言通过，1表示断言/执行失败，real模式未满足门禁返回2且无调用。
整体 `status=incomplete` 不因软件通过而改成全面通过。源码/环境基线、费用核对、PG/进程测试和缺陷
失败基线另留在本轮专项目录；费用不能合并重叠历史账本或用估算冒充账单。


真实调度报告格式 `query-real-v1`：`binding.provider_execution` 明确区分 `real_kimi` 与
`injected_test_double`。`pairs` 保存每组A/B0/确定性查询、规则同材料回放、原服务调用审计和检查；
`comparison` 分开新增材料、选择差异及规则/AI状态，不生成诊断正确率或教学得分。
`usage` 来自同一库的原有预留表，区分有usage的估算和未结预留；替身账本中的金额只是软件测试值，
不是真实费用。`execution_status=completed` 仅表示所选批次已运行，整体 `status=incomplete` 仍保留。
`running_pair` 非空时保留中断现场，不能删除账本或换任务身份续扣。预算不足、探针失败、软件断言失败
分别保留原因；人工审阅未执行仍为 `not_run/null`。报告不得隐去模型回退或知识未就绪的分母。
