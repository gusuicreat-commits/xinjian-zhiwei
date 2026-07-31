# 芯鉴知微 API 设计（P1 设备协议 V1）

## 通用约定

- API 前缀：`/api/v1`。
- 请求和响应：JSON，时间戳必须为包含时区的 ISO 8601 字符串。
- 未声明字段：拒绝并返回 422，避免设备字段拼写错误被静默忽略。
- 测试数据：必须显式设置 `is_test_data: true`。
- 原始请求：入库到对应记录的 `raw_payload`，用于追溯；认证头不会写入原始载荷。

## 设备认证

日志、读数和心跳接口要求：

```text
X-Device-ID: <device_key>
X-Device-Token: <secret token>
```

状态接口从路径取得 `device_id`，只要求 `X-Device-Token`。数据库只保存 PBKDF2-SHA256 哈希；未知设备、停用设备或令牌不匹配统一返回 401，避免泄漏设备是否存在。

## 接口

### POST `/device/ingest`

设备协议 V1 的幂等批量入口。请求携带 `protocolVersion`、`schemaVersion`、UUID
`requestId`、`bootId`、`sequenceNo`、可选设备时间/运行时/固件信息，以及日志、读数
和心跳记录数组。服务端采用全有或全无事务；同一请求重放不重复写入，相同序列冲突返回
409，缺失或不可信设备时间使用服务端接收时间并标记时间质量。默认限制为每批 100 条、
262144 字节、单设备每分钟 120 个新请求。完整契约、错误码和重试语义见
`docs/device-protocol.md`。

下列三个单条上传端点继续保留，以兼容 Phase 2 客户端；新模拟器默认使用批量入口。

### DELETE `/device/test-runs/{test_run_id}`

使用设备凭据定向删除当前设备、指定 `testRunId` 下的合成批次及其日志、读数和心跳。
只有 `isTestData=true` 的批次能关联运行 ID；接口不会删除其他运行或非测试数据。

### POST `/device/logs`

必填字段：`level`、`message`、`occurred_at`。可选字段：`event_code`、`sensor_snapshot`、`is_test_data`。`level` 仅接受 `debug`、`info`、`warning`、`error`、`critical`。

### POST `/device/readings`

必填字段：`sensor_type`、`metric_key`、有限数值 `value`、`observed_at`。可选字段：`unit`、`metadata`、`is_test_data`。字段是通用指标表达，不绑定硬件厂商或型号。

### POST `/device/heartbeat`

必填字段：`observed_at`。可选字段：`firmware_version`、`metadata`、`is_test_data`。服务端以接收时间更新 `devices.last_seen_at`，设备上报时间单独保留，避免设备时钟偏差影响在线判断。

### GET `/device/{device_id}/status`

返回 `online`、`offline` 或 `never_seen`。离线阈值由 `DEVICE_OFFLINE_AFTER_SECONDS` 配置，默认开发值为 90 秒。

### P4–P11 新增边界

- `/auth/session`、`/auth/me`、`/auth/classes`：正式用户会话和资源范围。
- `/experiments/templates`、`/experiments/template-versions/*`：模板草稿与发布门禁。
- `/knowledge/sources/{id}/documents/file`、`/knowledge/documents/{id}/workspace`、
  `/knowledge/chunks/*`：文件导入与草稿分块工作区。
- `/teacher-workflow/*`：处置动作、时间线、课堂消息和 CSV 报告。
- `/health/live`、`/health/ready`、`/health/dependencies`、`/ops/status`：运维状态。
- `/readiness/status`：证据驱动的项目就绪门禁。

### POST `/diagnosis/devices/{device_id}/run`

使用路径设备 ID 和 `X-Device-Token` 认证。请求包含 1 至 604800 秒的回看窗口，以及可选的通用实验模板快照 `template_id + metric_ranges`。响应返回持久化结果 ID、规则集版本、输入指纹、按优先级排序的命中规则及证据。

Phase 4 尚未建立实验模板和用户权限模型，模板快照是显式的临时接口边界，不表示设备端有权定义生产阈值。相关业务模型确定后应改为服务端加载模板。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用设备 ID 和设备令牌认证。根据已保存的诊断上下文运行 YAML 故障树并保存原因排序、证据、提示等级和提示文本。同一诊断结果与同一故障树存在唯一约束，重复调用返回已有历史，不重复增加失败次数。

### GET `/diagnosis/devices/{device_id}/guidance`

返回当前设备的提示历史，按创建时间倒序排列。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。该兼容查询仍使用环境变量
`REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为默认关闭的知识/运维工作区边界；未配置
返回 503，凭据错误返回 401。教师前端不再调用此兼容接口，而是使用正式 Bearer 会话的
`/teacher/dashboard`。

### GET `/diagnosis/ai/status`

返回 Phase 9.5 框架、已选定的 DeepSeek Provider、`deepseek-v4-flash`、非思考模式、Embedding 客户端、知识门禁、传输类型、生产路由和 Prompt 版本状态。该接口不返回 Base URL、API Key 或其他密钥。即使 Provider 已选定，只要 `AI_ENABLED=false` 或未注入服务端密钥，状态仍明确为未启用，不会发起请求。

### POST `/diagnosis/results/{diagnosis_result_id}/ai-explanation`

使用设备凭据，只能解释当前设备的诊断结果。请求体可选 `user_question`。接口先确保故障树与 Episode 存在，以结构化过滤、全文检索和可选 pgvector 检索审核知识，再执行策略、预算、稳定指纹缓存及统一 `AIClient`。Phase 9.5 的唯一生产调用路径为 `cache → deepseek → deterministic_fallback`，不做多模型分层。AI 不能修改确定性错误类型；证据必须来自规则白名单，知识引用必须来自本次检索结果。

送往 Provider 的上下文先经过 `phase9.5-allowlist-v1` 最小化：设备标识匿名化；日志只保留最多 3–10 条相关项；读数和心跳转换为统计摘要；令牌、密钥、Wi-Fi、学生身份、联系方式和自由文本中的敏感片段被删除或遮蔽。知识正文按字符上限截断，原始 Prompt 不写入审计表。

未配置密钥、知识未就绪、预算受限、检索失败、AI 超时或输出校验失败时仍返回 201，并携带 `deterministic_result`；`enhancement_status` 保留兼容状态值，同时通过 `route_path` 明确记录 `cache_hit`、`cache_miss → deepseek_success`、`cache_miss → deepseek_failed → deterministic_fallback` 或跳过原因。成功时仍返回兼容字段 `mode=ai_enhanced` 和严格结构化解释。

结构化策略触发原因通过 `trigger_reason` 返回并写入审计。已知高置信单规则、只读页面刷新、教师统计和普通知识检索不会触发 Provider；低置信、未知异常、多规则、Episode 升级或显式自然语言追问才可能进入缓存和 Provider 路由。知识引用包含来源、版本、定位、审核状态、融合分数和全文/向量/RRF 分项分数。

### POST `/student/session`

使用设备 ID 与设备令牌完成临时学生端会话验证。响应明确返回 `auth_mode=device_credential_placeholder`；该接口不创建用户，也不签发服务端学生令牌。

### GET `/student/dashboard`

使用设备凭据读取当前设备状态、最近 100 条日志、最近 500 条读数、最新诊断、对应提示、
最新反馈及该诊断对应的教师处置状态。处置状态只包含公开结果，不返回教师私人备注。

### POST `/student/diagnoses/{diagnosis_result_id}/feedback`

保存 `resolved`、`unresolved` 或 `request_teacher_help`。只能反馈当前凭据所属设备的诊断
结果；其他设备或不存在的结果返回 404。反馈继承诊断的 `is_test_data` 标记。选择
`request_teacher_help` 时，若设备存在启用中的班级与学生绑定，服务端以诊断结果为唯一键
幂等创建 `intervention_cases` 工单和公开 `request_help` 事件；未配置归属时只保存反馈与
Episode 升级状态，不猜测学生或班级。

### GET `/teacher/dashboard`

要求 `/auth/session` 签发的 Bearer 会话，且账号必须具有 `teacher` 或 `admin` 角色。
教师只统计授课班级绑定的设备；管理员可查看全部设备。返回在线/离线/未上报与异常数量、
互斥状态图、错误排行、七日趋势、最新异常、最近日志，以及学生求助工单与自动 Level 4
建议合并后的介入列表。同一诊断已有工单时不会重复显示自动建议。正式实验结果尚未导入
时，完成率保持 `null`，不会生成虚构进度。

### POST `/teacher-workflow/interventions/{case_id}/actions`

要求具有 `intervention.manage` 权限且能访问工单所属班级。前端闭环使用
`claim → resolve → close`；每次请求必须携带当前 `expected_version`，并发版本不一致返回
409。`resolve` 必须提供公开解决说明，结果会通过学生 Dashboard 回显；解决或关闭同时将
对应诊断 Episode 标记为已解决。服务端仍支持转交、内部备注和“证据不足”状态，私人备注
不会进入学生端响应。

## 知识库接口

来源登记、文件导入、知识块编辑和检索管理接口仍使用临时 `X-Review-Token` 工作区
边界；文档审核状态流转使用 `/auth/session` 签发的 Bearer 会话，并校验知识整理人、
正式批准人两个独立 RBAC 角色。仓库没有预置正式审核账号。

### GET `/knowledge/status`

返回框架状态、是否存在可检索内容、来源数、文档数、待审核数、审核通过知识块数、向量数，以及当前 Embedding Provider/模型/维度是否配置。空库返回 200 和明确说明，不创建占位记录。

### GET/POST `/knowledge/sources`

查询或登记资料来源。`source_key` 是外部稳定标识；同时保存类型、标题、来源 URI、版本、许可证、授权范围、元数据和 `is_test_data`。正式来源类型限定为 `official_hardware`、`course_material`、`confirmed_parameter`、`verified_case` 或 `supplementary`，且必须提供 URI 和版本；重复 `source_key` 返回 409。

### POST `/knowledge/sources/{source_id}/documents/text`

只接收已经提取的 `text/*` 文本，不直接解析 PDF、DOCX 或扫描件。正式导入还必须提供整理人、适用硬件和内容来源类型；官方资料必须有页码、章节或段落定位，已验证案例必须记录最终修复动作与根因置信度。服务端规范化换行、按可配置字符窗口切分、保存字符定位和 SHA-256；同一来源重复导入相同内容返回原文档并设置 `idempotent_replay=true`。新文档从 `draft` 开始。

### PATCH `/knowledge/documents/{document_id}/review`

接受目标状态、审核角色、审核人引用和备注。正式流程为：

```text
draft --organizer--> pending
pending --formal_approver--> approved
```

正式批准人也可将 `pending` 驳回为 `rejected`；批准后还支持 `withdrawn` 和
`superseded`，相应资料可由整理员重新回到 `draft`。整理人不得正式批准自己提交的资料。
来源未记录 `authorization_scope` 时不能批准。状态同步到文档的全部知识块，并追加不可
覆盖的审核历史。

### POST `/knowledge/documents/{document_id}/embeddings`

保存外部适配器生成的向量。文档必须先审核通过；同一请求中的维度必须一致。配置了 Provider/模型/维度后请求必须完全匹配；未配置时只允许 `is_test_data=true` 的测试向量，正式向量返回 503。

### POST `/knowledge/search`

请求显式携带查询向量、Provider、模型和限制条件。只检索审核通过且维度匹配的知识块，默认排除来源、文档或向量任一层标记为测试的数据。响应包含来源、版本、URI、文档、知识块定位、相似度和测试标记。

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 设备不存在、已停用或令牌无效 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 409 | 来源重复、授权缺失、文档未审核或 Embedding 配置不一致 |
| 413 | 提取文本超过配置的最大字符数 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 503 | 知识工作区审阅凭据或正式 Embedding Provider 尚未配置 |

当前继续提供设备凭据保护的学生总览 API，以及审阅令牌保护的知识工作区管理 API；
教师聚合已迁移到正式 Bearer 账号、班级范围和 RBAC。长期数据库中的正式记录仍为 0，
也不提供公开设备注册。Phase 9.5 已固定 DeepSeek 官方 API、
`deepseek-v4-flash` 和非思考模式，但 `AI_ENABLED=false`、密钥为空，因此不代表已经
配置或调用真实 AI 服务。统一 `AIClient` 仍作为可替换边界。

当前数据库中的 `phase9.synthetic-acceptance` 来源及 `phase9-test-vector` 向量只用于
自动化验收，默认查询排除；它们不是正式知识或真实 Provider 产物。无真实硬件路线
P1–P11 已完成，但没有自动生成正式业务数据。
