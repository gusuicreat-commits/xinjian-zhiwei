# 芯鉴知微数据库设计（V2）

## 迁移基线

- 数据库：PostgreSQL 16。历史 pgvector 结构仅为兼容保留，MVP 运行链不使用向量检索。
- 迁移工具：Alembic。
- 目标版本：`20260912_0027`（本地代码；本轮尚未部署）。
- 后端启动时先执行 `alembic upgrade head`，成功后才启动 API。

## 表结构

### `devices`

保存稳定外部标识 `device_key`、展示名称、通用设备类别、可选硬件描述、令牌哈希、启用状态、最后服务端接收心跳时间、固件版本和可扩展元数据。硬件型号允许为空，不作为核心逻辑分支条件。

### `device_logs`

保存级别、消息、可选事件码、设备发生时间、传感器快照、原始请求、测试数据标记和服务端接收时间。

### `sensor_readings`

使用 `sensor_type + metric_key + value + unit` 表达通用指标，并保存设备观察时间、扩展元数据、原始请求、测试数据标记和服务端接收时间。

### `device_heartbeats`

保存每次心跳的设备观察时间、固件版本、扩展元数据、原始请求、测试数据标记和服务端接收时间。心跳同时更新 `devices.last_seen_at`。

### `ingestion_requests`

保存设备协议 V1 的 UUID 请求 ID、协议/Schema 版本、启动 ID、序列号、设备发送时间、
运行时、固件版本、规范化载荷 SHA-256、记录数、原始成功响应、测试标记和服务端接收
时间。`device_id + request_id` 和 `device_id + boot_id + sequence_no` 分别唯一，用于
持久化幂等与序列冲突检测。三个采集表通过可空 `ingestion_request_id` 回指批次，并保存
协议版本、启动 ID、序列号、运行时和 `time_quality`；旧单条接口产生的历史记录保持为空。
可空 `test_run_id` 只标记合成场景运行并建立索引，用于设备范围的精确定向清理。

### `diagnosis_results`

保存评估时间、规则集版本与哈希、规范化输入指纹、命中规则、证据、完整上下文快照、
`DiagnosisCore`、确定性解释、AI 增强状态和测试数据标记。新诊断可同时保存实验稳定 ID、
实验版本、定义 SHA-256 与 Knowledge Scope；旧诊断这些字段保持为空。

### `experiments`、`experiment_versions` 与 `experiment_package_artifacts`

`experiments` 保存稳定实验身份。`experiment_versions` 保存通过校验的完整实验包快照、
Manifest、包哈希、兼容范围、审核状态和当前版本标记；`experiment + version` 以及包哈希
均不可重复。`experiment_package_artifacts` 为包内硬件、规则、故障树、知识、教学和测试
文件建立可查询索引，但运行时真相仍是对应版本的不可变完整快照。

已发布版本不允许修改；发布新版本只把旧版本标记为 `superseded`，历史诊断仍绑定并可
读取旧版本。`experiment_assignments`、`diagnosis_results` 和
`diagnosis_workflow_runs` 可通过 `experiment_version_id` 锁定同一版本。

### `diagnosis_evidence`

保存每次诊断的标准化事件、观测和规则事实。`raw_payload` 保留来源数据，
`normalized_value` 保存通用引擎读取的标准结构，两者不混写。每条证据有稳定 UUID、来源
类型、来源记录 ID 和时间，并绑定诊断与实验版本；AI 只能引用本次诊断实际存在的证据 ID。

候选原因按实际匹配异常、事实和来源关联这些持久化 ID；AI 对一个候选的引用还须属于该候选
`evidence_refs`，不能从同诊断的无关证据中补位。引用身份与关联合法不证明真实根因。

### `diagnosis_episodes`

按设备、可选实验标识、主要错误码和时间窗口聚合重复异常，保存开始/最近出现时间、失败次数、当前提示等级、最新诊断、AI 调用次数和解决来源。

### `guidance_history`

每次故障树提示保存设备、来源诊断、树 ID/标题/状态/版本/哈希、配置来源与 Scope、首次
发现时间、历史失败次数（不是采样连续失败次数）、持续时间、提示等级、教师介入标记、排序原因、提示文本和测试数据
标记。`diagnosis_result_id + fault_tree_id` 唯一，避免重复调用制造虚假升级。

### `diagnosis_feedback`

保存指定诊断的反馈 action、可选 note、测试标记和创建时间。迁移 0027 新增可空的
`request_id`、`experiment_session_id`、`processing_status`：新请求必须带 UUID 请求键和实际实验会话，
处理状态区分 pending 与 applied；历史行保持 NULL，不猜测请求身份、归属或处理完成状态。

`(diagnosis_result_id, request_id)` 唯一约束保证同一诊断的一次逻辑反馈只能建一行；会话外键
使用 `ON DELETE RESTRICT`。同键同载荷重放原行，改变 action/note 返回 409；新键才表示新尝试。
服务端在任何写入前核对会话、学生、设备与诊断/工作流归属，旧诊断没有可信创建归属则拒绝反馈。

PostgreSQL 按诊断使用会话级 advisory lock，在现有图节点业务提交之间仍串行化反馈；SQLite
仅使用进程内锁，属于单进程开发/测试范围。数据库唯一约束独立兜底，不能将 SQLite 结果当作多进程并发验证。

同步 Checkpoint、原反馈 ID 和处理状态用于失败恢复：图尚未消费时恢复，已消费但业务确认丢失时补确认，
applied 则直接重放。业务表与 Saver 并未合并为分布式原子事务；限定验证范围见 [整改报告](workflow-remediation.md)。

### `knowledge_sources`

保存稳定来源标识、治理来源类型、标题、URI、版本、许可证、授权范围、可扩展元数据和测试标记。正式来源类型分为 `official_hardware`、`course_material`、`confirmed_parameter`、`verified_case` 和 `supplementary`；正式来源必须记录 URI 与版本。

### `knowledge_documents`

保存来源关联、文档标题、媒体类型、语言、外部存储 URI、内容哈希、解析器名称/版本、审核状态和测试标记。新导入文档从 `draft` 开始，状态可为 `draft`、`pending`、`approved`、`rejected`、`withdrawn` 或 `superseded`。`source_id + content_hash` 唯一，保证重复导入幂等。

### `knowledge_chunks`

保存文档内顺序、文本、内容哈希、字符数、页码/章节/字符范围等通用定位 JSON、结构化过滤元数据和审核状态。元数据用于记录资料整理人、内容来源方式、适用硬件；真实案例还记录最终修复动作与 `confirmed/high/medium/low/unknown` 根因确认等级。官方资料必须有页码、章节或段落定位。只有 `approved` 知识块可参与正式检索。

### `knowledge_embeddings`（历史兼容）

该表和 pgvector 列来自历史迁移，为旧数据可读和迁移可升级而保留。当前 MVP 不写入、不查询、不评测该表，诊断主链没有 Embedding 或向量检索。未来启用 RAG 时必须通过独立架构决策、数据迁移和召回评测重新定义，而不是直接复活旧逻辑。

### `knowledge_reviews`

追加保存文档审核决定、`reviewer_role`、审核人引用、备注和时间。当前有效角色为资料整理人和正式批准人；审核状态流转必须使用 Bearer 账号，服务层强制角色校验并禁止整理人正式批准自己提交的资料。历史记录为追加式审计，不因角色目录收敛而删除。

### `ai_call_records`

追加保存诊断、Episode 与可选工作流关联、触发原因、缓存状态、最后路由、完整
`route_path`、Provider/模型、Prompt 版本与哈希、状态、耗时、结构化输出、知识引用、
Token、成本占位、校验和降级原因。输入快照只保存匿名标识、哈希、计数与隐私控制
摘要；失败和跳过记录同样保留。`workflow_run_id + call_stage` 唯一，推理与解释按反馈轮次分别记录，
同一阶段的图工作流重放复用原审计，不重复累计预算或成本。

### `ai_explanation_cache`

以规则、故障树、知识、Prompt、Schema 和规范化核心输入生成的稳定指纹保存已校验解释，记录来源 Provider/模型、过期时间和命中次数。

### `diagnosis_workflow_runs` 与 `diagnosis_workflow_reviews`

前者保存 LangGraph 业务流水、设备/诊断关联、`diagnosis:<workflow_id>`、图/规则/
故障树/模型版本、节点路径/耗时、结构化案例匹配审计、恢复次数、证据分、Level、
审核请求和最终投影；后者追加保存唯一一次审核人与 `approve/edit/reject` 决定。
LangGraph checkpoint 表由官方
PostgreSQL saver 的 `.setup()` 独立管理，不在 Alembic 中重复定义。

### 课堂与治理表

- `users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`auth_sessions`：
  正式身份与不透明会话骨架。
- `courses`、`classes`、`enrollments`、`teaching_assignments`、
  `experiment_assignments`、`device_bindings`：课堂资源范围。
- `audit_events`：认证、模板、导出等不可覆盖审计事件。
- `experiment_templates`、`experiment_template_versions`、`diagnostic_artifacts`：
  模板及规则/故障树不可变版本。
- `intervention_cases`、`intervention_events`、`classroom_messages`：教师处置、私人备注、
  状态历史和课堂消息撤回。

## 关系与索引

- 三类采集记录都通过 `device_id` 外键关联 `devices`，V1 批次记录还关联
  `ingestion_requests`。
- 设备删除时级联其采集记录；生产环境执行删除前必须另行设计审计和保留策略。
- 日志按设备和发生时间建立联合索引。
- 读数按设备/观察时间及指标/观察时间建立联合索引。
- 心跳按设备和观察时间建立联合索引。
- 诊断结果按设备/创建时间建立联合索引，并为输入指纹建立索引。
- 提示历史按设备/创建时间及介入状态/创建时间建立索引。
- 诊断反馈按设备/创建时间建立索引，以外键关联设备、诊断及可空实验会话，并以诊断/请求键建立唯一约束。
- 知识文档按审核状态/创建时间索引；知识块按审核状态/文档索引。
- 历史向量索引仅为兼容保留，不属于当前性能门禁。
- 知识来源删除时级联文档、知识块、向量和审核记录。
- AI 调用按诊断/创建时间和状态/创建时间建立索引，诊断删除时级联调用记录。
- `diagnosis_episodes` 按设备、状态和最近出现时间索引，聚合同一设备、实验和错误窗口内的重复故障。
- `ai_explanation_cache` 以稳定指纹唯一约束并按过期时间索引。
- PostgreSQL 中历史全文/向量索引随迁移保留；当前诊断知识匹配不依赖这些索引。

## 安全与可追溯性

- `token_hash` 使用带随机盐的 PBKDF2-SHA256，不保存原始令牌。
- `raw_payload` 只保存经过 Pydantic 校验的请求体，不包含认证头。
- 测试和模拟记录必须设置 `is_test_data=true`。
- 所有结构变化必须新增 Alembic revision，不允许手工修改生产表结构。
- `20260727_0009` 增加协议请求表和三类采集记录的通用协议追踪列，不导入或修改任何
  现有业务数据。
- `20260727_0010` 只增加合成场景 `test_run_id` 与索引，不创建场景记录或测试数据。
- `20260727_0011` 增加课堂身份、RBAC、课程班级、任务绑定、会话和审计表。
- `20260727_0012` 增加版本化实验模板与诊断工件，并让任务绑定精确版本。
- `20260727_0013` 增加教师处置事件和课堂消息。
- `20260727_0014` 移除字段唯一索引之外的重复唯一约束，使升级库和全新库的
  SQLAlchemy 元数据一致；不修改业务数据。
- `20260730_0015` 删除 `teaching_assistant` 与 `technical_reviewer` 角色；已有助教
  账号迁移为教师，技术审核角色不自动获得正式批准权限。历史
  `technical_reviewed` 文档/块回退为 `pending`，审核历史继续保留。
- `20260813_0016` 增加诊断工作流与教师审核业务表；checkpoint 表继续由 LangGraph saver 自管。
- `20260813_0017` 增加有界节点指标、RAG 审计和恢复次数，不保存 Prompt、密钥或完整日志。
- `20260813_0018` 为每个工作流的正式审核增加唯一约束，使终结节点重放不产生重复审核。
- `20260813_0019` 为 AI 调用增加可空的工作流唯一外键，使图节点重放复用既有审计记录。
- `20260818_0021` 为诊断结果增加可空的实验 ID、版本、定义哈希与 Knowledge Scope，并为
  Guidance 增加故障树来源和 Scope；不回填或删除旧数据。
- `20260901_0022` 增加结构化 `knowledge_cases`，第一阶段不创建向量表。
- `20260901_0023` 将 AI 调用幂等键扩展为 `workflow_run_id + call_stage`，支持原因推理与解释分别审计。
- `20260901_0024` 增加事实绑定的 `knowledge_case_drafts`，只有教师审核后才能发布为正式案例。
- `20260902_0025` 增加根因状态、事实锁定、真实解决记录、AI 表达审计和反馈轮次调用阶段；正式案例必须教师确认根因。
- `20260904_0026` 增加版本化 Experiment Package、任务/诊断/工作流版本绑定、工作流状态修订号和标准证据表；所有旧关联均为可空，不删除或猜测回填历史数据。
- `20260912_0027` 增加反馈请求键、实验会话、处理状态及外键/唯一约束；历史字段留 NULL。已在隔离库验证空库升级、带两条历史反馈的 0026 升级、单 Head、模型差异与重复键拒绝；部署新后端前必须完成升级，不能靠 ORM 自动建表替代。

用户、班级和实验模板通用框架已经建立，但正式用户、班级、任务与模板内容仍待人工
录入和审核。知识库与 AI 审计表已经建立；仅有测试记录和禁用真实 Provider 只代表
框架通过验收，不能冒充正式知识或真实 AI 诊断。

测试、模拟和 Mock 记录必须可由来源键、测试设备、实验包版本和 `is_test_data` 追溯；正式查询默认排除测试知识。迁移只建立结构，不得自动生成正式资料、真实学生信息或真实设备数据。
