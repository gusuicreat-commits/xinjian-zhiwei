# 芯鉴知微数据库设计

代码核对日期：2026-09-27。本文解释当前数据边界与关键约束；精确列定义见
[`backend/app/models/`](../backend/app/models/)，迁移历史见
[`backend/migrations/versions/`](../backend/migrations/versions/)。持续规则见
[开发准则](development-guidelines.md)，目标环境状态见 [实现状态](implementation-status.md)。

## 1. 迁移与存储基线

- 标准环境使用 PostgreSQL 16；历史初始迁移要求 `vector` 扩展，当前诊断不使用向量检索。
- Alembic 代码 Head 为 `20260927_0035`。这是仓库结构版本，不代表运行数据库已升级。
- 容器入口 `app.startup` 先执行迁移再启动 API；手工迁移、备份与回滚按 [部署说明](deployment.md) 执行。
- LangGraph checkpoint 表由 PostgreSQL saver 的 `setup()` 管理，不在 Alembic 中重复定义。
- 结构变更与历史数据处理遵守[数据变更要求](development-guidelines.md#data-change)。

## 2. 按业务分类的表

| 分类 | 表及用途 |
| --- | --- |
| 账号与授权 | `users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`auth_sessions`；账号、角色权限与可撤销会话 |
| 课堂 | `courses`、`classes`、`enrollments`、`teaching_assignments`、`experiment_assignments`、`device_bindings`；资格、授课范围、任务及当前设备绑定 |
| 实验会话 | `experiment_sessions`、`experiment_session_commands`；固定学生—任务—设备—包版本，保存状态版本和操作回执 |
| 设备采集 | `devices`、`ingestion_requests`、`legacy_ingestion_admissions`、`device_logs`、`sensor_readings`、`device_heartbeats`；设备身份、批次回执、旧入口准入计数、原始遥测和时间质量 |
| 诊断事实 | `diagnosis_results`、`diagnosis_evidence`；固定输入、规则结果、标准证据与解释快照 |
| 问题及指导 | `diagnosis_episodes`、`diagnosis_issues`、`guidance_history`、`diagnosis_feedback`；持久化故障、诊断到问题的关联、针对性指导和反馈 |
| 检查与流程 | `diagnosis_checks`、`diagnosis_workflow_runs`、`diagnosis_workflow_reviews`；显式检查身份、冻结输入、图业务流水与审核 |
| 实验内容 | `experiments`、`experiment_versions`、`experiment_package_artifacts`；固定包快照和工件索引 |
| 旧模板兼容 | `experiment_templates`、`experiment_template_versions`、`diagnostic_artifacts`；既有模板及诊断工件版本 |
| 知识内容 | `knowledge_sources`、`knowledge_documents`、`knowledge_chunks`、`knowledge_reviews`、`knowledge_cases`、`knowledge_case_drafts`；来源、资料整理审核、正式案例及事实草稿 |
| 模型调用 | `ai_usage_reservations`、`ai_call_records`、`ai_explanation_cache`；外发尝试的预算预留、调用审计和可重验缓存 |
| 记忆治理 | `memory_uses`、`memory_events`、`memory_impact_reviews`、`memory_cleanup_plans`；来源使用、停用、影响复核和固定缓存清理计划，不复制事实正文 |
| 教师处置 | `intervention_cases`、`intervention_events`、`classroom_messages`；工单、公开/私密事件与课堂消息 |
| 通用审计 | `audit_events`；身份、版本发布、会话管理、导出等事件 |
| 历史向量兼容 | `knowledge_embeddings`；保留旧结构，不是当前诊断真相源或检索依赖 |

## 3. 原始归属与采集约束

`device_bindings` 代表当前资源分配，不能证明历史数据属于谁。`experiment_sessions` 固定任务、
学生、设备及可空包版本；三类遥测各有可空 `experiment_session_id`。诊断的创建归属保存在
快照，工作流另以外键保存学生及会话；访问入口通过 `services/data_scope.py` 解析并核验。
无法证明归属的历史记录不自动成为学生可见记录。

`ingestion_requests` 保存请求 UUID、载荷哈希、boot/sequence、原成功回执、测试运行 ID 和接收时间：

- `(device_id, request_id)` 唯一：同身份同内容重放；同身份不同内容冲突。
- `(device_id, boot_id, sequence_no)` 唯一：同启动序列不能由另一请求占用。
- 同设备全部遥测写入在设备行锁内重新鉴权及检查合计额度；批次记录和回执、旧逐条记录和legacy_ingestion_admissions分别同事务提交。批次唯一约束独立兜底，旧接口无幂等身份。
- 批次及三张遥测表的 `sequence_no`、`uptime_ms` 为 `BIGINT`；HTTP 限定严格整数 `0..2^53-1`。
- 遥测通过可空 `ingestion_request_id` 回指批次；设备时间、服务端接收时间、`time_quality` 分开保留。

`raw_payload` 是经过接口校验保留的请求数据，不包含认证头；不等同于字节级网络抓包。
设备令牌与用户密码保存哈希，Bearer 会话也只保存令牌哈希。

## 4. 诊断、问题与反馈

`diagnosis_results` 保存固定上下文、规则版本/哈希、输入指纹、实验版本、测试标记、确定性结果
及解释。`diagnosis_evidence` 保存 UUID、来源类型/记录、规范化值和原始载荷；引用真实存在还不够，
候选引用必须与该候选和问题范围相关。

`diagnosis_episodes` 表示持续问题；新问题使用 `scope_key`，由会话、规则/包及组件范围等确定。
部分唯一索引 `uq_active_problem_scope` 限制同一非空范围只有一个 open/escalated 问题。
`diagnosis_issues` 用 `(diagnosis_result_id, issue_key)` 唯一键保存每次诊断中的问题归属、
证据键和证据修订；同一次诊断可关联多个问题。历史空范围不猜测迁移为新问题。

`guidance_history` 新记录唯一键为 `(diagnosis_result_id, fault_tree_id, episode_id)`；
`episode_id IS NULL` 的旧记录仍使用诊断＋树的部分唯一索引。指导保存树版本、计数、
异常持续时间、帮助等待时间、提示和可选教学参考全文快照。参考放在现有 hints JSON，旧行不回填。

`diagnosis_feedback` 保存原请求 UUID、会话、目标问题、action/note 和 pending/applied 状态。
`(diagnosis_result_id, request_id)` 唯一；同身份内容冲突返回 409，同身份重试不得重复推进。
问题证据修订用于阻止过时“已解决”反馈覆盖新相关异常。解决报告与硬件恢复来源分别记录。

短生命周期锁保护问题读取与变更；图恢复另有串行控制。不能把某个唯一索引或单个状态修订号
当成全部跨模块事务保证，实际锁边界见 `services/diagnosis_episode.py`、`student_feedback.py`。

## 5. 请求恢复与工作流

`diagnosis_checks` 唯一键为 `(session_id, request_id)`，保存原参数、载荷哈希、基准诊断、
输入签名、私有输入快照、工作流关联及回执。回执投影不返回私有输入；读取回执不运行检查。
新请求复用旧证据结论时，单次查询当前问题的 `status/resolution_source` 并保存到新回执；
原回执不更新。归属或目标无法核实时返回冲突，不从设备当前绑定补造关联。

`diagnosis_workflow_runs.id` 是流程身份，`graph_thread_id = 'diagnosis:' || id` 受数据库检查约束；
`diagnosis_result_id` 是另一个可空、唯一关联的诊断结果 ID，不能将两个 ID 混为一谈。
工作流保存学生、会话、图/规则/包版本、节点轨迹、指标、恢复次数和最终投影。
`state_revision` 只作业务修订；`diagnosis_workflow_reviews.workflow_run_id` 唯一，防止重复终结审核。

业务表与 checkpoint 不是分布式原子事务。检查和反馈依靠原请求身份、已消费状态和原流程恢复，
不能因丢响应就生成新身份。PostgreSQL 的独立连接测试是并发验收依据；SQLite 仅覆盖开发测试路径。

## 6. 内容版本与案例发布

`experiment_versions` 保存不可覆盖包快照、Manifest、hash、兼容范围、审核状态及当前标记；
`(experiment_id, version)` 与包 hash 分别唯一。工件表是索引，完整快照仍是真相源。
会话、任务、诊断和工作流可关联精确版本。发布新版本会替换当前标记，但不改写旧快照；
固定历史版本使用与撤回边界见 [实验包设计](experiment-package-design.md)。

资料文档以 `(source_id, content_hash)` 唯一，知识块保存来源定位、内容 hash、审核状态及适用注记。
已批准知识块是资料治理结果，不能直接等同于可用于诊断的正式案例。
诊断案例还须同时满足 approved、confirmed、facts_locked、quality_check_passed 及适用范围。

`knowledge_case_drafts.version_no` 用于条件更新；审批和插入正式案例在同一事务。
`knowledge_cases.source_draft_id` 可空且唯一，防止一份新草稿重复发布。旧来源关联留空；
润色等待模型时不持锁，返回后重验状态、版本与权限。

## 7. AI 与教师处置

`ai_usage_reservations` 每条对应一次外发尝试，含阶段、状态、预留/计入金额、Token、错误分类
和问题费用归因。`ai_call_records` 记录业务调用输出及路由；`(workflow_run_id, call_stage)`
限制工作流阶段重复审计。阶段包含反馈身份，不能把不同轮次误合并。成本不确定的失败不得当成零成本。
金额预留是估算门禁，不保证服务商账单硬上限。

`ai_explanation_cache` 用稳定指纹保存已校验解释；缓存仍须经过当前权限、版本、审核和输出契约检查。
原始秘密和完整 Prompt 不作为审计数据保存；字段范围以外发及审计投影代码为准。

`intervention_cases` 有目标问题、班级和 `version_no`；同活动问题只允许一个 open/claimed/unconfirmed
工单，旧无目标工单维持每诊断唯一。操作及回执保存在追加事件中；学生解决说明只读取明确公开的
解决事件，不能从历史冗余摘要绕过隐私。工单 resolve/close 不自动关闭问题；明确问题解决报告另走
版本/证据修订核验。

## 8. 迁移与历史检查

迁移文件维护逐版结构历史，本文仅保留影响操作的边界：`0031` 在存在无法无损合并的
多问题记录时拒绝降级，`0032` 在协议计数超过 32 位时拒绝缩列，`0033` 在有检查回执时
拒绝直接删表；`0034` 只为旧入口建立近期准入记录，不回填历史流量。其他降级也不能据此推断无损。
删除或级联行为不是历史清理授权，历史异常只读检查使用 `app.cli.audit_historical_integrity`。
验收要求见[验证规则](development-guidelines.md#validation)，备份、升级和回滚命令见
[部署说明](deployment.md)；当次执行结果保存在测试报告。

## 9. 记忆来源与生命周期

三类记忆沿用原业务事实：固定包配置、审核案例、任务/证据/反馈/Checkpoint。工作流的 `memory_context` 是有界只读投影，不是第二份事实库。具体契约见[AI设计](ai-diagnosis-design.md#memory-lifecycle-design)。

`memory_uses` 按来源类型、ID、版本、内容哈希及包身份记录目标和用途；确定性摘要键让重复执行不重复插入，与调用/工作流写入同事务。索引分别支持按来源反查、按诊断核验及按缓存目标处理。来源是多类对象，不能凭同名ID跨类型/包关联；服务核对来源，诊断外键使用RESTRICT，防止级联毁掉关系。

`memory_events.source_key` 唯一，停用与原案例/包状态同事务；待清理状态索引用于重试处理。`memory_impact_reviews` 的事件＋诊断唯一，复核使用预期版本和事件行锁，保留审计；权限来自原课堂。`memory_cleanup_plans` 固定操作者、截止时间和目标指纹，执行时重验，已完成重放原结果。当前只物理清理过期或精确关联的解释缓存，其他存储保留期未配置时禁止删除。

0035只新增治理表，不回填历史来源；旧审计仅按明确版本引用辅助查阅，缺哈希标为未知。治理表非空时拒绝降级删除。隔离库迁移与模型对照不代表运行库已升级。

## 上下文清单（无新迁移）

复用 `ai_call_records.input_snapshot.context_manifest`，合同 `context-manifest-v1`、策略 `whole-unit-applicability-v1`、投影 `case-applicability-v1`；未新增表，schema head仍为 `20260927_0035`。MemoryUse的matched保留匹配快照，provided只记录真实尝试提交的来源子集，cited按有效引用、derived记录缓存派生；选择后不读取新版本冒充调用时来源。清单不存原始正文。旧 `(workflow_run_id, call_stage)` 唯一性与历史记录不变；旧记录不回填。

资料包格式1.1的登记与案例条件复用现有包内容、solution_record JSON；P0–P3没有新迁移。当前建议读取检验策略清单，旧结果只读降级，不回填历史call、final_result、Checkpoint或幂等回执，不自动补模型调用。
