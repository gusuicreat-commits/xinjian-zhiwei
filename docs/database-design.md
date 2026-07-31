# 芯鉴知微数据库设计（1.0.0）

## 迁移基线

- 数据库：PostgreSQL 16 + pgvector。
- 迁移工具：Alembic。
- 目标版本：`20260730_0015`。
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
P2 的可空 `test_run_id` 只标记合成场景运行并建立索引，用于设备范围的精确定向清理。

### `diagnosis_results`

保存评估时间、规则集版本与哈希、规范化输入指纹、命中规则、证据、完整上下文快照、`DiagnosisCore`、确定性解释、AI 增强状态和测试数据标记。

### `diagnosis_episodes`

按设备、可选实验标识、主要错误码和时间窗口聚合重复异常，保存开始/最近出现时间、失败次数、当前提示等级、最新诊断、AI 调用次数和解决来源。

### `guidance_history`

每次故障树提示保存设备、来源诊断、树 ID/标题/状态/版本/哈希、首次发现时间、连续失败次数、持续时间、提示等级、教师介入标记、排序原因、提示文本和测试数据标记。`diagnosis_result_id + fault_tree_id` 唯一，避免重复调用制造虚假升级。

### `diagnosis_feedback`

保存设备对指定诊断结果提交的解决状态、可选备注、测试数据标记和创建时间。Phase 6 尚无学生账号，因此反馈只关联设备与诊断，不创建虚构的 `student_id`；正式身份模型建立后需新增可审计的用户关联。

### `knowledge_sources`

保存稳定来源标识、治理来源类型、标题、URI、版本、许可证、授权范围、可扩展元数据和测试标记。正式来源类型分为 `official_hardware`、`course_material`、`confirmed_parameter`、`verified_case` 和 `supplementary`；正式来源必须记录 URI 与版本。

### `knowledge_documents`

保存来源关联、文档标题、媒体类型、语言、外部存储 URI、内容哈希、解析器名称/版本、审核状态和测试标记。新导入文档从 `draft` 开始，状态可为 `draft`、`pending`、`approved`、`rejected`、`withdrawn` 或 `superseded`。`source_id + content_hash` 唯一，保证重复导入幂等。

### `knowledge_chunks`

保存文档内顺序、文本、内容哈希、字符数、页码/章节/字符范围等通用定位 JSON、结构化过滤元数据和审核状态。元数据用于记录资料整理人、内容来源方式、适用硬件；真实案例还记录最终修复动作与 `confirmed/high/medium/low/unknown` 根因确认等级。官方资料必须有页码、章节或段落定位。只有 `approved` 知识块可参与正式检索。

### `knowledge_embeddings`

保存知识块、Provider、模型、维度、pgvector `vector` 向量及测试标记。向量列当前不固定维度，避免 Provider 未确定时写死模型；每次写入和查询仍校验维度一致。

### `knowledge_reviews`

追加保存文档审核决定、`reviewer_role`、审核人引用、备注和时间。当前有效角色为资料整理人和正式批准人；审核状态流转必须使用 Bearer 账号，服务层强制角色校验并禁止整理人正式批准自己提交的资料。历史记录为追加式审计，不因角色目录收敛而删除。

### `ai_call_records`

追加保存诊断与 Episode 关联、触发原因、缓存状态、最后路由、完整 `route_path`、Provider/模型、Prompt 版本与哈希、状态、耗时、结构化输出、知识引用、Token、成本占位、校验和降级原因。输入快照只保存匿名标识、哈希、计数与隐私控制摘要；失败和跳过记录同样保留。

### `ai_explanation_cache`

以规则、故障树、知识、Prompt、Schema 和规范化核心输入生成的稳定指纹保存已校验解释，记录来源 Provider/模型、过期时间和命中次数。

### P4–P7 课堂与治理表

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
- 诊断反馈按设备/创建时间建立索引，并以外键关联设备和诊断结果。
- 知识文档按审核状态/创建时间索引；知识块按审核状态/文档索引。
- 向量按 Provider/模型索引；正式模型维度确定后再评估 HNSW 或 IVFFlat 索引。
- 知识来源删除时级联文档、知识块、向量和审核记录。
- AI 调用按诊断/创建时间和状态/创建时间建立索引，诊断删除时级联调用记录。
- `diagnosis_episodes` 按设备、状态和最近出现时间索引，聚合同一设备、实验和错误窗口内的重复故障。
- `ai_explanation_cache` 以稳定指纹唯一约束并按过期时间索引。
- PostgreSQL 为审核知识块内容建立 `simple` 配置的 GIN 全文检索表达式索引；pgvector 保持可选。

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

用户、班级和实验模板通用框架已经建立，但正式用户、班级、任务与模板内容仍待人工
录入和审核。知识库与 AI 审计表已经建立；仅有测试记录和禁用真实 Provider 只代表
框架通过验收，不能冒充正式知识或真实 AI 诊断。

Phase 9 最终验收数据库保留一组明确测试标记的合成知识、测试向量、测试 Episode、Mock 调用审计与缓存。P1 只新增协议结构与测试，不导入正式资料、真实学生信息或真实设备数据。所有测试记录均可由来源键、测试设备和 `is_test_data` 追溯；正式查询默认排除测试知识。
