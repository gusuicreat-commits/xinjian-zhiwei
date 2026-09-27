# 芯鉴知微 API 设计

代码核对日期：2026-09-27。本文按使用入口解释契约；精确字段与枚举见对应版本的 FastAPI OpenAPI（`/docs`）及 `backend/app/schemas/`、`backend/app/diagnosis/workflow_schemas.py`。服务层权限、幂等和跨字段约束不能仅从 OpenAPI 推断。持续规则见 [开发准则](development-guidelines.md)，部署与实际验收见 [实现状态](implementation-status.md)。

## 通用约定

- API 前缀：`/api/v1`。
- 通常请求和响应使用 JSON；文件上传、CSV 导出等按各端点定义。旧单条遥测要求带时区时间；批量设备协议对缺失或不可信设备时间有明确回退规则。
- 声明为严格模型的请求拒绝未知字段；`metadata` 等扩展对象按各 Schema 保留。不能将自由字典等同于整份请求免校验。
- 测试数据显式标记；常规接口为 `is_test_data: true`，批量协议为 `isTestData: true`。
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
[设备协议](device-protocol.md)。同设备的查重、限额检查、批次和回执保存由短数据库事务串行保护；原请求重放不再占用新额度。该额度为批次与三个旧逐条上传端点合计。四个入口都在解析JSON前限制实际流式字节数，等待设备锁后重新鉴权；旧端点每次成功写入计次，没有请求幂等身份。

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
- `/readiness/status`：已批准文档、合格兼容案例、可加载的正式发布包分别列示；新增检查项状态`unverified`，无验收依据的软件/演示/硬件/组织布尔值保持false并说明待核实。
- `/ops/status`：`pending_interventions`计open/claimed/unconfirmed；新增`resolved_awaiting_close`单列待关闭。`active_sessions`排除过期、撤销及停用用户。

### POST `/diagnosis/devices/{device_id}/run`

使用正式学生 Bearer 身份、路径设备 ID 和有效实验会话；设备令牌只兼容明确测试设备。`X-Experiment-Session-ID` 未传时只兼容唯一有效会话；无法唯一确定返回 409。请求含 1 至 604800 秒的回看窗口和可选旧模板参数。响应返回持久化诊断 ID、规则集版本、输入指纹、命中规则、证据及 `issues`。新学生端显式检查优先使用下述检查命令入口。

可选模板快照是旧调用兼容边界，不表示设备端有权定义生产阈值。新任务应由服务端锁定已审核发布的实验包版本。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用与确定性诊断相同的学生身份及有效会话，核验诊断原归属。根据已保存上下文生成指导；新记录按“诊断＋故障树＋问题”唯一，旧无问题关联记录保留“诊断＋故障树”唯一。重复调用返回已有记录，不制造失败轮次。

### GET `/diagnosis/results/{diagnosis_result_id}/evidence`

沿用正式学生身份及会话检查，必须匹配诊断原始归属；只有设备相同并不够。响应包含证据 UUID、类型、来源类型、来源记录 ID、标准化值和时间，不返回 `raw_payload`。AI 引用还须与具体候选相关，不能任取同诊断中的无关证据。

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

返回当前已验证实验会话中的提示历史，按创建时间倒序排列；不把设备上一位学生的指导混入。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。该兼容查询仍使用环境变量
`REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为默认关闭的知识/运维工作区边界；未配置
返回 503，凭据错误返回 401。教师前端不再调用此兼容接口，而是使用正式 Bearer 会话的
`/teacher/dashboard`。

### GET `/diagnosis/ai/status`

返回 AI 框架、已选定的 Provider/模型、结构化知识门禁、传输类型、生产路由和 Prompt 版本状态。第一阶段不返回 Embedding 或 RAG 状态。该接口不返回 Base URL、API Key 或其他密钥。

### POST `/diagnosis/results/{diagnosis_result_id}/ai-explanation`

使用学生身份和有效会话，只能解释属于当前会话的诊断结果；设备令牌仅限测试兼容。请求体可选 `user_question`。工作流先用显式字段匹配已审核结构化案例，将实验规范供给受约束原因排序；推理后再校验证据 ID、候选集、规则结果和允许动作。AI 不能修改确定性错误类型，也不能引用本次匹配之外的知识。

送往 Provider 的上下文先经过 `phase9.5-allowlist-v1` 最小化：设备标识匿名化；日志只保留最多 3–10 条相关项；读数和心跳转换为统计摘要；令牌、密钥、Wi-Fi、学生身份、联系方式和自由文本中的敏感片段被删除或遮蔽。知识正文按字符上限截断，原始 Prompt 不写入审计表。

未配置密钥、知识未就绪、预算受限、知识查询失败、AI 超时或输出校验失败时仍返回确定性结果；`enhancement_status` 和 `route_path` 记录缓存、Provider、降级或跳过原因。

结构化策略触发原因通过 `trigger_reason` 返回并写入审计。已知高置信单规则、只读页面刷新和教师统计不会触发 Provider；低置信、未知异常、多规则、Episode 升级或显式自然语言追问才可能进入缓存和 Provider 路由。知识引用记录案例 ID、来源、版本、审核状态和显式字段匹配依据，不包含向量/RRF 分数。

### `/diagnosis-workflows/*`

- `POST /diagnosis-workflows/devices/{device_id}`：使用学生账号 Bearer（设备凭据仅兼容明确测试设备）和必填
  `X-Experiment-Session-ID` 启动 LangGraph 工作流。响应的 `id` 与
  `diagnosis_id` 相同，`graph_thread_id` 必为 `diagnosis:{diagnosis_id}`。
- `GET /diagnosis-workflows/devices/{device_id}/latest`：仅获取该
  student/experiment_session/device 三元组的最新流程。
- `GET /diagnosis-workflows/{diagnosis_id}`：学生身份、设备和实验会话归属同时一致才可读取；设备凭据仅限测试兼容。
- `GET /diagnosis-workflows/review-queue/pending`：教师 Bearer + `intervention.manage`；教师按班级范围过滤，管理员可查全部。
- `GET /diagnosis-workflows/review-queue/recent`：同权限查看最近 50 条已审核流程及追加式审核历史。
- `GET /diagnosis-workflows/metrics/summary`：同范围聚合流程状态、恢复、节点耗时、AI Token/成本和学生解决率。响应内 `needs_rag_count` 是旧 Schema 兼容字段，新流程固定为 0。
- `POST /diagnosis-workflows/{workflow_id}/review`：提交 `approve/edit/reject`。`edit` 可修订解释文案，不能修改规则证据、证据分和 Level。

响应状态包括 `created/collecting/deterministic_analysis/retrieving/ai_analysis/
waiting_feedback/waiting_teacher/completed/rejected/failed`；其中 `retrieving` 仍用于当前 `knowledge_context` 结构化匹配阶段，不表示执行 RAG。工作流不替换原有确定性诊断 API；功能关闭或
checkpoint 不可用时，原有 API 仍可返回确定性结果。响应中的 `node_metrics`、
`retrieval_audit`、规则/日志引用、故障树候选、知识引用和 `reviews` 用于可观察、可追溯
展示；不返回知识正文、Prompt、认证信息或密钥。

### POST `/student/session`

正式学生先通过 `/auth/session` 取得个人账号 Bearer，选择任务并创建实验会话；本接口用 Bearer、`X-Device-ID` 与会话头验证当前会话，返回 `auth_mode=student_account`。设备ID/令牌仅兼容明确标记的测试设备，不能作为正式学生身份；本接口本身不创建用户或签发令牌。

### GET `/student/dashboard`

按学生账号、设备与有效实验会话读取设备状态、该会话最近 100 条日志、最近 500 条读数、诊断、对应提示、
最新反馈及该诊断对应的教师处置状态。处置状态只包含公开结果，不返回教师私人备注。

### GET `/student/feedback-recovery`

使用学生账号 Bearer、设备ID和必需的 `X-Experiment-Session-ID`（设备认证仅限测试兼容）找回该实验会话的反馈确认记录，不要求浏览器保留原诊断 ID 或请求 UUID。接口仅查询，不提交反馈、不确认处理状态、不恢复诊断图；响应带 `Cache-Control: no-store`。

| 字段 | 含义 |
| --- | --- |
| `pending` | 当前会话最早的至多 20 条未决记录，包含之前诊断的记录 |
| `latest_applied` | 当前会话按提交时间排序的最近一条已应用记录；没有时为 null |
| `has_more_pending` | 是否还有未返回的未决记录；处理当前记录后重新查询 |

每条记录包含 `id`、`diagnosis_result_id`、目标 `episode_id`、UUID `request_id`、`action`、原始 `note`、`created_at`、`processing_status` 和 `is_test_data`。原备注保留空白与换行，供同载荷重放；接口不返回其他学生备注、认证凭据或完整诊断状态。

先核对设备、会话与学生，再逐条校验诊断/工作流原归属；不按当前设备绑定补造历史归属。旧记录缺少请求键、会话或有效处理状态时不纳入找回结果。无效设备凭据返回 401，缺会话头 422，越界、无效或停用学生的会话返回 403。

已关闭但归属有效的会话可以查询回执；这不赋予继续处理未消费反馈的权限。前端展示待确认记录，由用户明确点击后沿用原 `diagnosis_result_id`、`request_id`、action/note 调用现有 POST。若请求从未到达服务器，且浏览器记录也已丢失，服务端不能找回它。

### POST `/student/diagnoses/{diagnosis_result_id}/feedback`

保存 `resolved`、`unresolved` 或 `request_teacher_help`。使用学生账号 Bearer 和设备ID（设备认证仅限测试兼容），并且必须提供
`X-Experiment-Session-ID`；JSON 必须包含 UUID `request_id`，以及 action、可选 note 和目标 `episode_id`。多问题诊断必须明确目标；只有唯一适用问题时可走兼容选择。

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
| 相同 request_id、相同 action/note/episode_id | 已应用则返回原反馈（仍为 201）；未决则恢复或补确认原提交，不重复推进 |
| 相同 request_id、不同 action/note/episode_id | 409，无新增副作用 |
| 新 request_id | 视为有意的新尝试，受会话和工作流状态约束；有其他未决反馈时 409 |
| 网络结果不明或 503 | 保留原 request_id 和原载荷重试；503 detail.code 为 `DIAGNOSIS_FEEDBACK_RETRY_REQUIRED` |

重放也必须先通过归属校验。关闭会话可重放已完成响应或补确认已经消费的反馈，不能因此继续执行未消费的新操作。
反馈继承诊断的 `is_test_data`。求助仍通过已核实的课堂绑定幂等创建工单；无合法反馈归属时不先保存反馈兜底。

调用方应同步更新；部署前按[实现状态](implementation-status.md)核对代码迁移Head并在目标环境验证。
[完整流程问题整改](archive/workflow-remediation.md)保留0027阶段的历史记录；个人账号准入已在2026-09-19实施。

### 实验会话开始、结束与教师释放

- `GET /student/assignments`、`GET /student/experiment-sessions`：查询当前学生可用任务和会话。
- `POST /student/experiment-sessions`：使用 `request_id`、设备和任务 ID 开始会话，检查当前资格及设备占用并固定包版本。
- `POST /student/experiment-sessions/{id}/end`：提交 `request_id`、`expected_version` 和 completed/cancelled 原因。
- `GET /teacher/experiment-sessions`、`GET /teacher/experiment-sessions/{id}`：受权 teacher/admin 查询原任务班级范围中的会话。
- `POST /teacher/experiment-sessions/{id}/release`：需 `assignment.manage`、`request_id`、`expected_version` 和非空原因；显式取消占用，不修改其他会话、不关闭故障或工单。

同身份同载荷返回原回执，冲突 409；原回执重试仍核验当前权限。撤销学生资格不会自动把旧会话或历史数据交给下一名学生。

### GET `/teacher/dashboard`

要求 `/auth/session` 签发的 Bearer 会话，且账号必须具有 `teacher` 或 `admin` 角色。
教师只统计授课班级绑定的设备；管理员可查看全部设备。返回在线/离线/未上报与异常数量、
互斥状态图、错误排行、七日趋势、最新异常、最近日志，以及学生求助工单与自动 Level 4
建议合并后的介入列表。同一诊断已有工单时不会重复显示自动建议。正式实验结果尚未导入
时，完成率保持 `null`，不会生成虚构进度。

### POST `/teacher-workflow/interventions/{case_id}/actions`

要求具有 `intervention.manage` 权限且能访问工单记录所属班级。前端常用 `claim → resolve → close`；请求必须携带 `expected_version`，新客户端同时持久化 `request_id`。同身份同载荷重放，版本或载荷冲突返回 409；缺请求身份的旧客户端仍兼容版本检查。

`resolve` 要求说明，只有明确公开的解决事件可以显示给学生；私密说明不能从冗余摘要泄漏。工单解决/关闭只改变工单状态，不自动关闭问题、更不证明硬件恢复。

明确结束目标问题另用 `POST /teacher-workflow/interventions/{case_id}/problem-resolution`，必填 UUID `request_id` 和 `expected_revision`；可选 `recovery_diagnosis_id` 必须通过新相关恢复证据检查。无恢复依据时仅记录教师报告。旧工单没有可靠问题关联时拒绝猜测。

## 知识库接口

来源登记、文件导入、知识块编辑和检索管理接口仍使用临时 `X-Review-Token` 工作区
边界；文档审核状态流转使用 `/auth/session` 签发的 Bearer 会话，并校验知识整理人、
正式批准人两个独立 RBAC 角色。仓库没有预置正式审核账号。

### GET `/knowledge/status`

返回结构化知识模式、来源/文档数量、案例数量、已审核案例和待审核案例数量。第一阶段不返回或依赖向量、Embedding Provider 与维度。

### GET `/knowledge/case-drafts/pending`

教师或正式批准人查看由已解决诊断事实生成、且通过质量检查的案例草稿。草稿保留原诊断、学生反馈、规则与故障树版本引用，不会被诊断主链使用。

### POST `/knowledge/case-drafts/{draft_id}/approve`

教师或正式批准人提交稳定 `case_id`、`confirmed_root_cause`、`final_solution_steps` 和 `confirmation_note`。还需符合 `confirmation_material` 的事实来源要求；候选外根因不能直接发布。服务端按草稿原状态和内部版本条件更新，并与正式案例插入同事务提交；来源草稿唯一，审批竞争返回 409。成功才创建 `approved + confirmed + facts_locked + quality_check_passed` 的正式案例。

### POST `/knowledge/case-drafts/{draft_id}/ai-polish`

可选调用已配置 AI，只生成标题、症状描述、教学说明和解决摘要。服务端强制保留 `sourceIds`，禁止修改事实字段或在根因未确认时使用确定因果措辞，并保存模型与 Prompt 审计。调用不持草稿锁；模型返回后重验权限、状态和版本，迟到冲突返回 409，已发生调用仍记账。

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
| 401 | 登录或设备认证无效、过期，或要求正式账号 |
| 403 | 当前身份没有权限，或对象超出学生/会话/班级范围 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 409 | 资源重复、非法状态流转、实验包版本已存在或审核条件不满足 |
| 413 | 请求体、批次数量或提取文本超过配置上限 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 429 | 新批次超过设备速率限制 |
| 503 | 工作区未配置或工作流基础设施暂不可用；常规模型失败由确定性降级处理 |

正式学生总览使用个人账号及会话，设备凭据仅限测试兼容；部分知识整理工作区仍由审阅令牌保护。教师聚合使用正式 Bearer 账号、班级范围和 RBAC。项目不提供公开设备注册。默认
`AI_ENABLED=false`，是否启用 Provider 由部署方明确配置和审批；统一 `AIClient` 是可替换边界。


### 教学参考可选响应字段（2026-09-20）

学生dashboard的`guidance[].hints[].teaching`与指导API的同名字段保存`teaching-reference-v1`快照。
字段包括status（available/missing/unavailable）、experiment_version_id、package_version、package_hash、
is_test_data、concepts（concept_id/description/references）和steps（step_id/title/expected_state/prerequisite_step_ids）。
旧记录缺字段或null时不补造内容。steps只作实验参考，不属于新的允许动作或设备证据；
expected_state是预期，不是实测。读取不生成新指导、反馈或模型调用，权限沿用所属诊断与会话。

## 重新检查命令（2026-09-20）

`POST /api/v1/diagnosis-workflows/devices/{device_id}` 保持原请求字段，新增可选
`request_id`（UUID）、`baseline_id`、`target_episode_id`。新前端总是传身份和所见基准。
身份作用域为经验证的当前实验会话；目标问题必须属于基准。原参数校验通过后才接收命令。
返回201的原工作流对象增加 `check`：身份、基准、工作流、检查时间、状态、数据时间范围、
新记录数、测试标记及逐问题对比。`no_new_data` 返回原工作流，不新增诊断或模型调用。
不同身份但输入相同的并发检查可共用结果；新输入遇过期基准409，不能自动换身份重试。

`GET /api/v1/diagnosis-workflows/devices/{device_id}/checks/latest` 只读回执（没有则null），
权限及会话验证与启动一致。`pending`回执包含原请求参数，供丢失浏览器记录时显式恢复，
不包含私有输入快照。工作流latest也带最近check；前端必须核对诊断ID后组合展示。
网络中断/503保留身份；同身份不同参数409。401/403/409/422不自动重新提交。
历史诊断不补造对比记录，GET不会触发图执行。
