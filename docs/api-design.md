# 芯鉴知微 API 设计

代码核对日期：2026-10-02。本文按使用入口解释契约；精确字段与枚举见对应版本的 FastAPI OpenAPI（`/docs`）及 `backend/app/schemas/`、`backend/app/diagnosis/workflow_schemas.py`。服务层权限、幂等和跨字段约束不能仅从 OpenAPI 推断。权限与状态规则见[开发准则](development-guidelines.md#business-rules)，部署与实际验收见 [实现状态](implementation-status.md)。

## 通用约定

- API 前缀：`/api/v1`。
- 通常请求和响应使用 JSON；文件上传、CSV 导出等按各端点定义。旧单条遥测要求带时区时间；批量设备协议对缺失或不可信设备时间有明确回退规则。
- 声明为严格模型的请求拒绝未知字段；`metadata` 等扩展对象按各 Schema 保留。不能将自由字典等同于整份请求免校验。
- 测试数据显式标记；常规接口为 `is_test_data: true`，批量协议为 `isTestData: true`。
- 原始请求：入库到对应记录的 `raw_payload`，用于追溯；认证头不会写入原始载荷。

## 登录与明确拒绝

`DELETE /auth/session` 使用 Bearer 撤销当前登录，成功或重复撤销返回204，不影响其他登录会话；缺失/未知令牌401。学生和教师主动退出立即清空本地内容，再确认服务端注销；网络失败显示“本机已退出，服务端退出未确认”。权限失效导致的本地重置不等于主动注销。不存在/停用账号也进行一次密码派生校验，统一失败语义。

`POST /auth/session` 在校验密码前为“连接来源 IP＋小写用户名”的哈希键原子预留额度；失败和在途请求共同受 `AUTH_LOGIN_MAX_FAILURES`（默认5）限制。PostgreSQL 的 `login_attempts` 表供多个 worker 和重启后的实例共享；不保存明文用户名、IP 或密码。预留有效期和失败后窗口均使用 `AUTH_LOGIN_WINDOW_SECONDS`（默认300秒）。过期检查不得签发令牌；成功与会话创建一起提交，只清理自身预留及已完成失败，不清理其他在途请求。全表最多10000条，每次准入最多清理500条过期记录，容量不足返回429。SQLite只用于单进程开发/测试。代理部署须正确配置可信代理，不能无条件信任客户端转发头。

学生开始实验的401/403/422是明确拒绝：客户端清除该待确认请求；401重新登录，403清空原权限内容并刷新任务，422重新选择参数。网络错误和5xx仍可能丢失已提交回执，必须保留原请求ID，不允许直接换任务重试。

旧模板编辑、审核、发布与版本创建采用同一父模板锁；锁后刷新版本状态和内容hash，拒绝旧快照写入，并重验账号及权限。模板代码、同模板版本号等明确身份冲突返回409，不产生半成品。

`/docs`、`/redoc`、`/docs/oauth2-redirect` 使用每次响应的脚本nonce及文档专用CSP，响应不缓存；Swagger/ReDoc脚本样式仍来自FastAPI默认CDN。JSON API维持 `default-src 'none'`，文档CSP不会全局开放脚本。

## 设备接入

### 设备认证

日志、读数和心跳接口要求：

```text
X-Device-ID: <device_key>
X-Device-Token: <secret token>
```

状态接口从路径取得 `device_id`，只要求 `X-Device-Token`。数据库只保存 PBKDF2-SHA256 哈希；未知设备、停用设备或令牌不匹配统一返回 401，避免泄漏设备是否存在。

项目不提供公开设备注册。

### POST `/device/ingest`

设备协议 V1 的幂等批量入口，全有或全无写入。同请求同载荷重放原回执，载荷或序号冲突返回 409。
设备认证、时间回退、共享限额、锁后鉴权、完整报文和错误结构统一见[设备协议](device-protocol.md)。
下列三个单条上传端点兼容旧客户端；它们没有请求幂等身份，每次成功写入都占用设备共享额度。

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

## 诊断与检查

### POST `/diagnosis/devices/{device_id}/run`

使用正式学生 Bearer 身份、路径设备 ID 和有效实验会话；设备令牌只兼容明确测试设备。`X-Experiment-Session-ID` 未传时只兼容唯一有效会话；无法唯一确定返回 409。请求含 1 至 604800 秒的回看窗口和可选旧模板参数。响应返回持久化诊断 ID、规则集版本、输入指纹、命中规则、证据及 `issues`。新学生端显式检查优先使用下述检查命令入口。

可选模板快照是旧调用兼容边界，不表示设备端有权定义生产阈值。新任务应由服务端锁定已审核发布的实验包版本。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用与确定性诊断相同的学生身份及有效会话，核验诊断原归属。根据已保存上下文生成指导；新记录按“诊断＋故障树＋问题”唯一，旧无问题关联记录保留“诊断＋故障树”唯一。重复调用返回已有记录，不制造失败轮次。

### GET `/diagnosis/results/{diagnosis_result_id}/evidence`

沿用正式学生身份及会话检查，必须匹配诊断原始归属；只有设备相同并不够。响应包含证据 UUID、类型、来源类型、来源记录 ID、标准化值和时间，不返回 `raw_payload`。AI 引用还须与具体候选相关，不能任取同诊断中的无关证据。

### GET `/diagnosis/devices/{device_id}/guidance`

返回当前已验证实验会话中的提示历史，按创建时间倒序排列；不把设备上一位学生的指导混入。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。该兼容查询仍使用环境变量
`REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为默认关闭的旧运维兼容查询边界；未配置
返回 503，凭据错误返回 401。教师前端不再调用此兼容接口，而是使用正式 Bearer 会话的
`/teacher/dashboard`。

### GET `/diagnosis/ai/status`

返回 AI 框架、已选定的 Provider/模型、结构化知识门禁、传输类型、生产路由和 Prompt 版本状态。第一阶段不返回 Embedding 或 RAG 状态。该接口不返回 Base URL、API Key 或其他密钥。

### POST `/diagnosis/results/{diagnosis_result_id}/ai-explanation`

使用学生身份和有效会话，只能解释属于当前会话的诊断结果；设备令牌仅限测试兼容。请求体可选 `user_question`。响应保留确定性错误类型，AI 仅解释当前允许的证据、原因和知识。

Provider 输入通过 `provider-allowlist-v4` 最小化和清洗，不返回或审计完整敏感 Prompt；字段白名单、输出校验与契约版本见[AI 工作流设计](ai-diagnosis-design.md)。

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

2026-10-04增量：工作流响应增加只读 `reported_evidence`（无来源时为空列表），从绑定诊断的持久证据投影，带来源与状态并清洗敏感值；等待反馈/教师期间即使 `final_result` 为空也可返回。它不扩展读取权限，不表示已确认根因。当前建议采用 `reasoning-facts-v2`，只显示规则许可的核验动作；模型自由 `missing_evidence` 和旧别名不能回退为当前指导。精确字段见 `workflow_schemas.py` 和[本轮评估](../output/audits/ai-residual-repair-20261004/report.md)。

### 重新检查命令

`POST /api/v1/diagnosis-workflows/devices/{device_id}` 接受可选
`request_id`（UUID）、`baseline_id`、`target_episode_id`。新前端总是传身份和所见基准。
身份作用域为经验证的当前实验会话；目标问题必须属于基准。原参数校验通过后才接收命令。
返回 201 的工作流对象包含 `check`：身份、基准、工作流、检查时间、状态、数据时间范围、
新记录数、测试标记及逐问题对比。`no_new_data` 返回原工作流，不新增诊断或模型调用。
不同身份但输入相同的并发检查可共用证据结论；每个新请求重新读取当前问题的
`handling_status/resolution_source` 并保存到新回执，不复制旧回执的处理状态。旧请求重放
仍返回原回执；问题关联无法核实或新输入遇过期基准时返回 409，不能自动换身份重试。

`GET /api/v1/diagnosis-workflows/devices/{device_id}/checks/latest` 只读回执（没有则null），
权限及会话验证与启动一致。`pending`回执包含原请求参数，供丢失浏览器记录时显式恢复，
不包含私有输入快照。工作流latest也带最近check；前端必须核对诊断ID后组合展示。
网络中断/503保留身份；同身份不同参数409。401/403/409/422不自动重新提交。
历史诊断不补造对比记录，GET不会触发图执行。

## 学生反馈与实验会话

### POST `/student/session`

正式学生先通过 `/auth/session` 取得个人账号 Bearer，选择任务并创建实验会话；本接口用 Bearer、`X-Device-ID` 与会话头验证当前会话，返回 `auth_mode=student_account`。设备ID/令牌仅兼容明确标记的测试设备，不能作为正式学生身份；本接口本身不创建用户或签发令牌。

### GET `/student/dashboard`

按学生账号、设备与有效实验会话读取设备状态、该会话最近 100 条日志、最近 500 条读数、诊断、对应提示、
最新反馈及该诊断对应的教师处置状态。处置状态只包含公开结果，不返回教师私人备注。

### 教学参考可选响应字段

学生dashboard的`guidance[].hints[].teaching`与指导API的同名字段保存`teaching-reference-v1`快照。
字段包括status（available/missing/unavailable）、experiment_version_id、package_version、package_hash、
is_test_data、concepts（concept_id/description/references）和steps（step_id/title/expected_state/prerequisite_step_ids）。
旧记录缺字段或null时不补造内容。steps只作实验参考，不属于新的允许动作或设备证据；
expected_state是预期，不是实测。读取不生成新指导、反馈或模型调用，权限沿用所属诊断与会话。

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

反馈在等待串行锁、生命周期锁、工作流行锁后重新核验当前身份、会话和原归属，返回前也重新鉴权；
等待期间被撤权的请求不能靠早先校验继续操作或取得回执。已提交的业务记录保留原身份用于恢复。
关闭会话可重放已完成响应或补确认已经消费的反馈，不能继续执行未消费的新操作。
反馈继承诊断的 `is_test_data`。求助仍通过已核实的课堂绑定幂等创建工单；无合法反馈归属时不先保存反馈兜底。

### 实验会话开始、结束与教师释放

- `GET /student/assignments`、`GET /student/experiment-sessions`：查询当前学生可用任务和会话。
- `POST /student/experiment-sessions`：使用 `request_id`、设备和任务 ID 开始会话，检查当前资格及设备占用并固定包版本。
- `POST /student/experiment-sessions/{id}/end`：提交 `request_id`、`expected_version` 和 completed/cancelled 原因。
- `GET /teacher/experiment-sessions`、`GET /teacher/experiment-sessions/{id}`：受权 teacher/admin 查询原任务班级范围中的会话。
- `POST /teacher/experiment-sessions/{id}/release`：需 `assignment.manage`、`request_id`、`expected_version` 和非空原因；显式取消占用，不修改其他会话、不关闭故障或工单。

同身份同载荷返回原回执，冲突 409；原回执重试仍核验当前权限。撤销学生资格不会自动把旧会话或历史数据交给下一名学生。

## 教师处置

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

## 知识库接口

### GET `/knowledge/case-drafts/pending`

教师或正式批准人查看由已解决诊断事实生成、且通过质量检查的案例草稿。草稿保留原诊断、学生反馈、规则与故障树版本引用，不会被诊断主链使用。

### POST `/knowledge/case-drafts/{draft_id}/approve`

教师或正式批准人提交稳定 `case_id`、`confirmed_root_cause`、`final_solution_steps` 和 `confirmation_note`。还需符合 `confirmation_material` 的事实来源要求；候选外根因不能直接发布。服务端按草稿原状态和内部版本条件更新，并与正式案例插入同事务提交；来源草稿唯一，审批竞争返回 409。成功才创建 `approved + confirmed + facts_locked + quality_check_passed` 的正式案例。

### POST `/knowledge/case-drafts/{draft_id}/ai-polish`

可选调用已配置 AI，只生成标题、症状描述、教学说明和解决摘要。服务端强制保留 `sourceIds`，禁止修改事实字段或在根因未确认时使用确定因果措辞，并保存模型与 Prompt 审计。调用不持草稿锁；模型返回后重验权限、状态和版本，迟到冲突返回 409，已发生调用仍记账。

## 记忆与影响复核

工作流响应新增严格、可空的 `memory_context`（`memory-v1`），包含 `facts/experiences/working`；老客户端可忽略。事实只陈述已保存配置，不声称实物确认；工作上下文最多50条证据ID、20条反馈并报告截断，不输出私密原文。当前资料不可用时 `teaching_available=false`，当前建议屏蔽，历史由单独受权入口提供。

以下路径均加 `/api/v1` 前缀并使用Bearer身份；读取不触发模型或诊断。列表用 `after_id` 游标、`limit` 上限100；影响列表按授权诊断扫描，空页也可能有下一游标，不能把空页当全量无影响。

| 路径 | 行为与权限 |
| --- | --- |
| `GET /memory/events` | 教师只看明确关联本班诊断的事件；管理员查看治理清单。审核角色本身不授予课堂历史权限 |
| `GET /memory/events/{id}/impacts` | 当前范围内的关联及复核结果，区分匹配、提供、引用、派生和旧版引用；缺关联不推断无影响 |
| `GET /memory/events/{id}/impacts/{diagnosis_id}/history` | 受权历史依据，明确不可作为当前建议 |
| `POST /memory/events/{id}/impacts/{diagnosis_id}/review` | 教师/管理员按原课堂复核，传预期版本；冲突409，相同操作者和原版本的相同内容可确认重试 |
| `GET /memory/events/{id}/package-candidates` | 管理员查同案例ID/版本的包候选；不证明来源相同，不自动撤包，改名副本仍未知 |
| `POST /memory/events/{id}/clear-caches` | 管理员清理账本精确关联的缓存；未追踪副本不声称已清除 |
| `POST /memory/cleanup-plans` | 管理员预览最多500条已过期缓存，固定目标；同时列出禁止删除的其他存储 |
| `GET /memory/cleanup-plans/{id}`、`POST .../{id}/execute` | 原管理员读取/按计划哈希执行；重验目标和到期时间，变化对象跳过，结果可重复确认 |

案例撤回和包撤销沿用原端点，分别产生停用事件；不新增自动联动撤包。复核只记录处置判断，不改诊断、确认根因、通知学生或切换版本。治理读接口返回 `Cache-Control: no-store`。

## 其他入口

- `/auth/session`、`/auth/me`、`/auth/classes`：正式用户会话和资源范围。
- `/experiments/templates`、`/experiments/template-versions/*`：旧模板草稿与发布门禁。
- `/experiments/packages/*`、`/experiments/package-versions/*`：实验包校验、导入、版本查询和发布门禁。
- `/teacher-workflow/*`：处置动作、时间线、课堂消息和 CSV 报告。
- `/health/live`、`/health/ready`、`/health/dependencies`、`/ops/status`：运维状态。
- `/readiness/status`：合格兼容案例、可加载的正式发布包分别列示；新增检查项状态`unverified`，无验收依据的软件/演示/硬件/组织布尔值保持false并说明待核实。
- `/ops/status`：`pending_interventions`计open/claimed/unconfirmed；新增`resolved_awaiting_close`单列待关闭。`active_sessions`排除过期、撤销及停用用户。

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 登录或设备认证无效、过期，或要求正式账号 |
| 403 | 当前身份没有权限，或对象超出学生/会话/班级范围 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 409 | 资源重复、非法状态流转、实验包版本已存在或审核条件不满足 |
| 413 | 请求体或批次数量超过配置上限 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 429 | 遥测写入超过设备共享速率限制，或登录失败/在途额度及总容量已满 |
| 503 | 工作流基础设施暂不可用；常规模型失败由确定性降级处理 |

## 上下文审计兼容

本次上下文建设未新增HTTP端点或公开响应字段。内部 `AIDiagnosisInput` 的私有准备元数据不会出现在模型JSON或公开Schema中。`AICallRecord.input_snapshot.context_manifest` 仅为现有审计JSON附加键，含来源身份/版本/hash、准确输入及Prompt指纹、预算与省略原因。`provider_attempted` 表示客户端尝试，不证明服务商接收或模型利用；缓存命中submitted为空并记录cache_origin。旧记录无清单表示历史未知，不按新策略补写。

### 资料包1.1与当前AI建议兼容

现有包导入端点接受格式1.0/1.1；1.1来源登记是严格JSON字段，不新增任意文档读取端点。全局案例确认材料允许有限`applicability_conditions`，缺少有效文字限制的历史案例仍可授权查阅，但不会进入新AI增强。源撤回影响候选可通过明确derived_from关联改名包案例，不自动撤包。

工作流当前读取、检查幂等返回和反馈后的读取共用只读建议投影。AI来源绑定冻结于相应快照`context_delivery.explanation_call_id`；旧策略或无绑定时返回确定性内容和`context_policy_status=legacy_enhancement_not_revalidated`，不改原回执或补调用。历史影响复核接口保留`usable_as_current_advice=false`，补充`historical_context_policy`。没有新增公共预检接口，预检仅为本地CLI。

## 内部测试实验准备CLI

维护者入口为`app.cli.prepare_internal_experiment`，提供plan/apply/status，操作见[准备说明](experiments/internal-lab-preparation.md)。没有新增HTTP接口；CLI显式选择测试PostgreSQL与已登录管理员令牌，调用共同初始化服务。包导入/状态流转仍由上述管理员接口负责，学生会话仍经原学生接口创建。初始化不绕过固定包、授权、测试标记或历史边界。

对象和成功审计同事务提交；同前缀同操作者同包hash/设备性质可恢复原回执，变更或残缺对象拒绝接管。plan/status不写入、不发放凭据；终端输出只含对象ID和状态，秘密由交互或环境变量输入。具体运行限制与回归入口见开发准则BR-LAB-PREP。

## 2026-09-30 共享校验修复契约

- 受保护写入在服务/最终图节点重验当前账号、登录会话、权限与记录归属；登录失效401、资格失效403，状态/版本冲突409。运行时身份引用不进入Checkpoint；已提交终态重放不重复审核。
- `DELETE /api/v1/device/test-runs/{id}`：引用或未完成冻结流程使整次清理返回409，不部分删除。无引用的测试运行可清理，空重放仍返回零计数。
- `GET /api/v1/student/experiment-session-commands/{request_id}`：当前账号只能读取本人且当前仍有资源访问权的会话命令回执。200返回`{status: "applied", request_id, result}`；404仅表示当前无可用回执，不能证明此前请求未执行。用于开始、结束和管理释放的正向恢复，不产生新命令。
- 页面明确拒绝时删除可执行载荷；若之前已有未知结果，则仅保留原请求编号并使用当前授权的只读接口核查。反馈409的恢复语义与普通版本409不同。
- 当前AI建议与设备状态说明共用资格校验；冻结绑定缺失、来源停用、契约或策略无效则确定性降级，不改历史记录、不额外调用Provider。

## 知识写入边界补充（2026-10-03）

来源与文档创建从当前已授权账号、服务器来源及显式测试请求保守派生`is_test_data`；文件提取后执行同一校验。测试账号编辑、拆分、合并、删除或审核已有正式文档返回403；测试输入命中已有正式正文去重时409，历史记录不自动改标记。审计继承账号与资源的测试性质。

分块PATCH在JSON解析前按文本请求字节预算及30秒总期限限制，Nginx采用相同预算。更新/合并在来源、文档锁后计算整文档总量；超限413且不改正文/审计。自动导入重叠由服务器记账，API不接受客户端额度。已有超限草稿允许严格缩减、禁止增长和超限等量替换；提交/批准时必须满足当前上限。合法上限、原有授权和独立审批约束继续生效。

## DHT11 学生受控查询（XJ-004，2026-10-09）

四个端点前缀均为 `/api/v1`。正式身份使用 `Authorization: Bearer ...`，并显式传
`X-Device-ID`（device_key）、`X-Experiment-Session-ID`。明确合成演示范围可沿用设备凭据，
但正式设备不能据此取得学生身份。开始/查看检查 `dashboard.read`；提交还检查
`feedback.create`。缺身份401，范围/资格无权403，未知或外部任务与无权采用相同拒绝形状，
不返回存在性信息；不支持的诊断场景或请求字段422，命令/版本冲突409。
来源查询或复核的临时故障、SQL语句/锁超时、死锁/序列化竞争、数据库连接失效返回503，
固定 `detail=query_temporarily_unavailable`，不包含异常正文或对象身份。整次事务回滚：
开始不创建任务/问题，查看不更改已保存状态，提交不写回执或消费问题；恢复后可重试同任务、
同问题和同 `request_id`。已保存的120秒累计执行预算耗尽仍为409 `query_execution_timeout`，
属于确定的任务上限，重试不重置已成功操作的累计预算。
503不是stale；manifest不一致、来源登记停用、包/范围修订变化、证据修改/删除仍为确定失效，
维持下表的stale投影。当前撤权优先返回无存在性信息的403。

| 方法与路径 | 请求 | 响应（200） |
| --- | --- | --- |
| POST `/student/diagnoses/{diagnosis_result_id}/queries` | 无请求体；诊断必须原属当前会话，场景仅 DHT11 `SENSOR_READ_FAILED` | 查询任务服务器投影；同会话＋诊断返回同任务，重新复核来源，不重新取证或登记问题 |
| GET `/student/diagnoses/{diagnosis_result_id}/queries` | 诊断ID，当前学生身份及会话 | 只读恢复：有任务则返回同一重验投影，没有则200 `null`；先验证诊断原属当前授权会话，无权/未知诊断同形403；不创建、不重新取证、不登记问题、不持久化重验产生的失效状态 |
| GET `/student/queries/{task_id}` | 任务ID，当前学生身份及会话 | 重验后的同一任务投影；来源失效返回200 `status=stale`、受影响需求的unknown判定与缺口，未失效需求保留，问题为空 |
| POST `/student/queries/{task_id}/answers` | `request_id` UUID、`question_id`、`question_version`、`value`（`matches_table/differs/unclear`），禁止其他字段 | 原子保存的回执：`id/request_id/value/created_at/is_test_data`；同ID同载荷返回原回执，同ID异载荷409；不同ID争答仅一个采用 |

任务投影只有 `id/contract_version/status/terminal_reason`、`requirements`（每需求的
`status/judgement/gap`）、一道允许的问题ID/版本/需求/选项/`synthetic`、计数、测试性质和
`root_cause_status=unconfirmed`、`physical_verification=not_asserted`。不外发原始载荷、
内部 manifest、身份或其他学生数据。四接口返回 `Cache-Control: no-store`。

会话结束后不开始、不交付查询结果、不接受新答复；仍有当前账号/班级/任务/设备权限的原提交人
可以用完全相同的 `request_id` 与载荷确认已成功回执，撤权后原回执也拒绝。
`unclear` 关闭唯一问题，保留 `observation_unknown`，不再追问。正式范围不登记合成题，
以 `finish_unknown/question_not_approved` 保留缺口。问题没有经教师确认的文本，当前API仅提供
合成结构目录的ID及枚举选项；XJ-005学生页按已知ID提供中文测试题目，正式教学题目仍待教师确认。

学生页加载/刷新/切页只读已有任务，显式点击“核对资料”才POST开始。答复网络结果未知或503时
保留同一UUID及载荷（按设备、实验会话、诊断隔离的sessionStorage，切换身份隔离响应，撤权清除执行内容），
显式重试才重发；409重新GET任务状态，401重新登录，403清空区域。程序GPIO比较、测试/失效标记
和根因未确认直接显示；未知代码保留可展开原文，不解释为原因或动作。
