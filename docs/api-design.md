# 芯鉴知微 API 设计

最后更新：2026-09-12。本文描述当前代码契约；完整字段、枚举和响应 Schema 以对应版本的 FastAPI OpenAPI（`/docs`）为准。本轮反馈契约变更尚未部署。

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

下列三个单条上传端点继续保留，以兼容旧客户端；新模拟器默认使用批量入口。

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

### 其他接口分组

- `/auth/session`、`/auth/me`、`/auth/classes`：正式用户会话和资源范围。
- `/experiments/templates`、`/experiments/template-versions/*`：旧模板草稿与发布门禁。
- `/experiments/packages/*`、`/experiments/package-versions/*`：实验包校验、导入、版本查询和发布门禁。
- `/knowledge/sources/{id}/documents/file`、`/knowledge/documents/{id}/workspace`、
  `/knowledge/chunks/*`：文件导入与草稿分块工作区。
- `/teacher-workflow/*`：处置动作、时间线、课堂消息和 CSV 报告。
- `/health/live`、`/health/ready`、`/health/dependencies`、`/ops/status`：运维状态。
- `/readiness/status`：证据驱动的项目就绪门禁。

### POST `/diagnosis/devices/{device_id}/run`

使用路径设备 ID 和 `X-Device-Token` 认证。请求包含 1 至 604800 秒的回看窗口，以及可选的通用实验模板快照 `template_id + metric_ranges`。响应返回持久化结果 ID、规则集版本、输入指纹、按优先级排序的命中规则及证据。

可选模板快照是旧调用兼容边界，不表示设备端有权定义生产阈值。新任务应由服务端锁定已审核发布的实验包版本。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用设备 ID 和设备令牌认证。根据已保存的诊断上下文运行 YAML 故障树并保存原因排序、证据、提示等级和提示文本。同一诊断结果与同一故障树存在唯一约束，重复调用返回已有历史，不重复增加失败次数。

### GET `/diagnosis/results/{diagnosis_result_id}/evidence`

设备凭据只能读取属于本设备诊断的标准化证据。响应包含证据 UUID、类型、来源类型、来源
记录 ID、标准化值和时间，不返回 `raw_payload`。AI 推理引用的证据 ID 必须来自这个集合。

## Experiment Package 接口

### POST `/experiments/packages/validate`

接收以包内路径为键的 10 份结构化文档，只执行严格 Schema、跨引用、包内样例和哈希
检查，不写数据库。需要 `assignment.manage` 权限。

### POST `/experiments/packages/import`

通过校验后创建 `draft` 实验版本和工件索引。服务端重新生成 Manifest；相同
`experiment + version` 不允许覆盖。需要 `assignment.manage` 权限。

### GET `/experiments/package-versions`

返回实验身份、版本、兼容范围、包哈希、校验报告、状态和当前版本标记。

### POST `/experiments/package-versions/{version_id}/status`

管理员按 `draft → pending → approved → published` 发布，或将已发布版本标记为
`revoked/superseded`。发布新版本不会修改旧版本内容。

### GET `/diagnosis/devices/{device_id}/guidance`

返回当前设备的提示历史，按创建时间倒序排列。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。该兼容查询仍使用环境变量
`REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为默认关闭的知识/运维工作区边界；未配置
返回 503，凭据错误返回 401。教师前端不再调用此兼容接口，而是使用正式 Bearer 会话的
`/teacher/dashboard`。

### GET `/diagnosis/ai/status`

返回 AI 框架、已选定的 Provider/模型、结构化知识门禁、传输类型、生产路由和 Prompt 版本状态。第一阶段不返回 Embedding 或 RAG 状态。该接口不返回 Base URL、API Key 或其他密钥。

### POST `/diagnosis/results/{diagnosis_result_id}/ai-explanation`

使用设备凭据，只能解释当前设备的诊断结果。请求体可选 `user_question`。工作流先用显式字段匹配已审核结构化案例，将实验规范供给受约束原因排序；推理后再校验证据 ID、候选集、规则结果和允许动作。AI 不能修改确定性错误类型，也不能引用本次匹配之外的知识。

送往 Provider 的上下文先经过 `phase9.5-allowlist-v1` 最小化：设备标识匿名化；日志只保留最多 3–10 条相关项；读数和心跳转换为统计摘要；令牌、密钥、Wi-Fi、学生身份、联系方式和自由文本中的敏感片段被删除或遮蔽。知识正文按字符上限截断，原始 Prompt 不写入审计表。

未配置密钥、知识未就绪、预算受限、知识查询失败、AI 超时或输出校验失败时仍返回确定性结果；`enhancement_status` 和 `route_path` 记录缓存、Provider、降级或跳过原因。

结构化策略触发原因通过 `trigger_reason` 返回并写入审计。已知高置信单规则、只读页面刷新和教师统计不会触发 Provider；低置信、未知异常、多规则、Episode 升级或显式自然语言追问才可能进入缓存和 Provider 路由。知识引用记录案例 ID、来源、版本、审核状态和显式字段匹配依据，不包含向量/RRF 分数。

### `/diagnosis-workflows/*`

- `POST /diagnosis-workflows/devices/{device_id}`：使用设备凭据和必填
  `X-Experiment-Session-ID` 启动 LangGraph 工作流。响应的 `id` 与
  `diagnosis_id` 相同，`graph_thread_id` 必为 `diagnosis:{diagnosis_id}`。
- `GET /diagnosis-workflows/devices/{device_id}/latest`：仅获取该
  student/experiment_session/device 三元组的最新流程。
- `GET /diagnosis-workflows/{diagnosis_id}`：设备凭据和实验会话归属同时一致才可读取。
- `GET /diagnosis-workflows/review-queue/pending`：教师 Bearer + `intervention.manage`；教师按班级范围过滤，管理员可查全部。
- `GET /diagnosis-workflows/review-queue/recent`：同权限查看最近 50 条已审核流程及追加式审核历史。
- `GET /diagnosis-workflows/metrics/summary`：同范围聚合流程状态、恢复、节点耗时、AI Token/成本和学生解决率。响应内 `needs_rag_count` 是旧 Schema 兼容字段，新流程固定为 0。
- `POST /diagnosis-workflows/{workflow_id}/review`：提交 `approve/edit/reject`。`edit` 可修订解释文案，不能修改规则证据、证据分和 Level。

响应状态包括 `created/collecting/deterministic_analysis/retrieving/ai_analysis/
waiting_teacher/completed/rejected/failed`；其中 `retrieving` 是旧记录兼容状态，新图使用 `knowledge_context` 结构化匹配。工作流不替换原有确定性诊断 API；功能关闭或
checkpoint 不可用时，原有 API 仍可返回确定性结果。响应中的 `node_metrics`、
`retrieval_audit`、规则/日志引用、故障树候选、知识引用和 `reviews` 用于可观察、可追溯
展示；不返回知识正文、Prompt、认证信息或密钥。

### POST `/student/session`

使用设备 ID 与设备令牌完成临时学生端会话验证。响应明确返回 `auth_mode=device_credential_placeholder`；该接口不创建用户，也不签发服务端学生令牌。

### GET `/student/dashboard`

使用设备凭据读取当前设备状态、最近 100 条日志、最近 500 条读数、最新诊断、对应提示、
最新反馈及该诊断对应的教师处置状态。处置状态只包含公开结果，不返回教师私人备注。

### POST `/student/diagnoses/{diagnosis_result_id}/feedback`

保存 `resolved`、`unresolved` 或 `request_teacher_help`。继续使用设备认证头，并且必须提供
`X-Experiment-Session-ID`；JSON 必须包含 UUID `request_id`，以及 action 和可选 note。

```json
{
  "request_id": "655b30d0-27e4-4280-8769-c00f039fc88d",
  "action": "unresolved",
  "note": "完成本次检查，问题仍未解决。"
}
```

上例只说明报文结构；客户端每次有意的新反馈生成新 UUID，同一次提交重试保留原 UUID 和载荷。

服务端先校验会话—学生—设备—诊断/工作流归属，再写入反馈、Episode、工单、调用或案例草稿。
其他设备或不存在的诊断返回 404，会话归属不符或旧诊断缺少可信创建归属返回 403；缺少必需头/字段
或非法 UUID 返回 422。不会将无归属的旧诊断自动绑定给今天使用设备的学生。

| 同诊断下的请求 | 行为 |
| --- | --- |
| 相同 request_id、相同 action/note | 已应用则返回原反馈（仍为 201）；未决则恢复或补确认原提交，不重复推进 |
| 相同 request_id、不同 action/note | 409，无新增副作用 |
| 新 request_id | 视为有意的新尝试，受会话和工作流状态约束；有其他未决反馈时 409 |
| 网络结果不明或 503 | 保留原 request_id 和原载荷重试；503 detail.code 为 `DIAGNOSIS_FEEDBACK_RETRY_REQUIRED` |

重放也必须先通过归属校验。关闭会话可重放已完成响应或补确认已经消费的反馈，不能因此继续执行未消费的新操作。
反馈继承诊断的 `is_test_data`。求助仍通过已核实的课堂绑定幂等创建工单；无合法反馈归属时不先保存反馈兜底。

调用方应同步更新，部署新后端前先完成 Alembic `20260912_0027`。重试与历史记录兼容详情见
[完整流程问题整改](workflow-remediation.md)。当前仍是设备凭据与已有实验会话模式，不是新增完整学生账号认证。

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

返回结构化知识模式、来源/文档数量、案例数量、已审核案例和待审核案例数量。第一阶段不返回或依赖向量、Embedding Provider 与维度。

### GET `/knowledge/case-drafts/pending`

教师或正式批准人查看由已解决诊断事实生成、且通过质量检查的案例草稿。草稿保留原诊断、学生反馈、规则与故障树版本引用，不会被诊断主链使用。

### POST `/knowledge/case-drafts/{draft_id}/approve`

教师或正式批准人提交稳定 `case_id`、`confirmed_root_cause`、`final_solution_steps` 和 `confirmation_note`。服务端只创建 `approved + confirmed + facts_locked + quality_check_passed` 的正式案例。

### POST `/knowledge/case-drafts/{draft_id}/ai-polish`

可选调用已配置 AI，只生成标题、症状描述、教学说明和解决摘要。服务端强制保留 `sourceIds`，禁止修改事实字段或在根因未确认时使用确定因果措辞，并保存模型与 Prompt 审计。

### GET/POST `/knowledge/sources`

查询或登记资料来源。`source_key` 是外部稳定标识；同时保存类型、标题、来源 URI、版本、许可证、授权范围、元数据和 `is_test_data`。正式来源类型限定为 `official_hardware`、`course_material`、`confirmed_parameter`、`verified_case` 或 `supplementary`，且必须提供 URI 和版本；重复 `source_key` 返回 409。

### POST `/knowledge/sources/{source_id}/documents/text`

只接收已经提取的 `text/*` 文本，不直接解析 PDF、DOCX 或扫描件。正式导入还必须提供整理人、适用硬件和内容来源类型；官方资料必须有页码、章节或段落定位，已验证案例必须记录最终修复动作与受治理的根因状态。服务端规范化换行、按可配置字符窗口切分、保存字符定位和 SHA-256；同一来源重复导入相同内容返回原文档并设置 `idempotent_replay=true`。新文档从 `draft` 开始。

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

第一阶段不提供 Embedding 写入或向量搜索 API。历史向量表如仍存在，只作为旧版本兼容
数据，不进入当前诊断链路。未来启用 RAG 时必须新增独立版本化接口和验收门禁。

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 设备不存在、已停用或令牌无效 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 409 | 资源重复、非法状态流转、实验包版本已存在或审核条件不满足 |
| 413 | 提取文本超过配置的最大字符数 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 503 | 知识工作区审阅凭据、AI Provider 或诊断工作流基础设施不可用 |

当前继续提供设备凭据保护的学生总览 API，以及审阅令牌保护的知识工作区管理 API；
教师聚合使用正式 Bearer 账号、班级范围和 RBAC。项目不提供公开设备注册。默认
`AI_ENABLED=false`，是否启用 Provider 由部署方明确配置和审批；统一 `AIClient` 是可替换边界。
