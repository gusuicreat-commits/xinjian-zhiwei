# 完整流程评测问题整改

日期：2026-09-12。范围：第二阶段三项软件问题，以及后续反馈找回、持续集成和真实浏览器联调。前轮结果保留在“验证记录”，本轮新增结果见“反馈找回与持续验收”。

## 项目负责人可读摘要

| 问题 | 本轮结论 |
| --- | --- |
| 这次发现了什么问题？ | 前轮已修复证据关联、重复处理和会话越界。本轮补齐关闭页面后找回未决反馈，并在真实联调中发现：没有历史诊断的新会话看不到启动按钮；旧诊断请求的晚响应也可能覆盖切换后的页面。 |
| 会造成什么现实影响？ | 学生重新打开页面后不知道上次提交是否成功，新会话可能无法开始诊断；切换实验后可能看到过时结果。只用页面 Mock 或后端测试，容易遗漏这些连接处的问题。 |
| 现在能不能解决？ | 已增加按会话查询的反馈找回面板，继续确认时沿用原请求和备注；补齐首次诊断入口及晚响应隔离。总门禁增加 PostgreSQL 流程评测和浏览器连接真实后端/数据库的验证，具体执行结果见下文。 |
| 如果不能，需要硬件还是教师确认？ | 修复上述软件问题不依赖硬件或教师。但失败日志能否区分真实根因、LED 是否发光、合理阈值需要硬件；教学步骤、验收标准和真实案例需要教师。本轮不升级这些事实状态。 |
| 下一步最应该做什么？ | 审阅本轮代码与本地门禁结果后，在目标环境完成 0027 迁移并配套发布前后端，观察一次云端 CI；硬件继续做正常—单因素故障—恢复对照。本轮未部署或推送。 |

## 三项问题如何修正

| 问题 | 原行为 | 当前代码行为 | 限定结论 |
| --- | --- | --- | --- |
| WF-ISSUE-01 候选证据关联 | 找不到原始日志/读数关联时，用第一条注册证据填空，DHT11 候选可能引用心跳 | 按故障树实际匹配的异常、事实和来源关联已落库证据；匹配不到保留空引用；AI 对每个原因的引用还必须属于该候选的 `evidence_refs`，推理后独立校验继续检查 | UUID 真实、属于当前诊断且关联匹配异常，是最低软件条件；不能据此确认 DATA 断开或器件损坏 |
| WF-ISSUE-02 反馈重试身份 | 同一 HTTP 请求重试会生成另一反馈并再次推进 | 请求必须带 UUID `request_id`；同诊断下同键同载荷重放原反馈，相同键不同 action/note 返回 409；真正的新尝试使用新键 | 不以文本永久去重；两次有意的“仍未解决”可以是不同尝试，但须遵守当前工作流状态 |
| WF-ISSUE-03 反馈归属 | 仅凭设备相同即可先写反馈，再恢复流程 | 写入前核对请求会话、学生、设备、诊断及工作流归属；越界在任何反馈、Episode、调用或草稿变更前拒绝；重放路径同样先校验归属 | 补齐现有实验会话边界，没有把当前设备凭据模式升级成完整学生账号登录 |

主要代码：[反馈入口](../backend/app/api/v1/routes/student.py)、[反馈提交服务](../backend/app/services/student_feedback.py)、[诊断恢复服务](../backend/app/services/diagnosis_workflow.py)、[故障树证据投影](../backend/app/ai/diagnosis_graph.py)、[推理校验](../backend/app/ai/reasoning.py)、[独立知识校验](../backend/app/knowledge/validation.py)。

## 反馈的重试、并发与恢复

一次逻辑反馈的身份是“诊断 + request_id”，反馈保存其原始载荷与实际实验会话。数据库唯一约束兜底防止并发创建重复记录；提交服务在串行化边界内判断新提交、重放或冲突。

1. **尚未接受：** 缺少请求字段、越界会话等请求在写入前拒绝。
2. **已接受、尚待流程确认：** 记录为 pending；网络失败或 503 时，客户端必须保留原键与原载荷。此时不能换新键绕过未决请求。
3. **流程尚未消费：** 同一请求继续恢复原 Checkpoint，不创建第二条反馈。
4. **流程已经消费、业务回执尚未保存：** 从 Checkpoint 核对该反馈 ID，补齐业务确认；不再送入一次学生反馈。已经关闭的会话只能完成这种已有处理的确认，不能借机执行新的反馈。
5. **已经应用：** 记录为 applied；同键同载荷返回原反馈，不重复推进、增加调用或生成草稿。

恢复调用使用同步 Checkpoint 保存。测试覆盖并发重复请求、HTTP 成功回执丢失、到达下一暂停点后业务确认丢失、Checkpoint 写入故障后重试，以及关闭会话的补确认边界。

这是针对这些具体失败窗口的恢复设计和回归，**不宣称业务数据库与 Checkpoint 存储已组成一个分布式原子事务**。连接/图重建和注入保存错误不等于整机断电、任意进程 kill、网络分区或生产负载验收。

## 学生页面如何配合

- 提交前将 `request_id` 与 action/note 存入当前标签页的 `sessionStorage`，按设备、实验会话、诊断隔离；该重试记录不保存设备 token。
- 自动重试、再次点击同一反馈或刷新页面后的重试沿用原载荷。未决期间选择另一种反馈会提示先重试原反馈，避免一个键代表两种意思。
- 收到成功响应后清除未决记录；下一次有意提交才生成新键。因此相同文字不会被永久去重。
- 重复点击不并发发送；切换会话后的晚响应不能覆盖另一学生页面。
- 400/401/403/404/422 的明确拒绝会清理本次未决记录并显示拒绝提示；409、503 和网络结果不明保留原记录。
- 页面加载时通过 `GET /student/feedback-recovery` 找回服务器已保存的当前会话反馈，包括较早诊断的未决记录；显示原动作、备注和最近已确认回执。查询本身不会提交或推进，用户点击“继续确认原反馈”后才恢复。
- 本地与服务端记录不一致时保留各自记录，不静默覆盖。存在未决记录或查询失败时拦住新的反馈，避免用新键绕过旧提交。
- `sessionStorage` 仍只承诺当前标签页保存。关闭页面后需重新提供有效的设备凭据和同一实验会话，才能找回服务端记录。**请求从未到达服务器且浏览器记录也丢失时，无法找回**；没有补造历史请求键或身份。

实现与测试：[重试记录](../frontend/src/api/feedbackRetry.ts)、[学生状态管理](../frontend/src/stores/studentDashboard.ts)、[状态边界测试](../frontend/src/stores/studentDashboard.test.ts)、[请求契约测试](../frontend/src/api/student.test.ts)、[存储边界测试](../frontend/src/api/feedbackRetry.test.ts)。

## 接口与数据库兼容变化

反馈 API `POST /api/v1/student/diagnoses/{diagnosis_result_id}/feedback` 现在要求：

- 继续携带已有设备认证头，并必须提供 `X-Experiment-Session-ID`。
- JSON 必须提供 UUID `request_id`；action/note 的内容语义保持不变。
- 缺少必需字段或非法 UUID 返回 422；会话归属不符返回 403；不存在或不属于设备的诊断仍按入口隐藏为 404；键与载荷冲突返回 409；需要原请求重试的处理失败返回 503。

新增迁移 [20260912_0027](../backend/migrations/versions/20260912_0027_feedback_request_scope.py)：为反馈增加可空的 `request_id`、`experiment_session_id`、`processing_status`，增加会话外键及 `(diagnosis_result_id, request_id)` 唯一约束。

**部署新后端前必须先升级数据库到 `20260912_0027`，并同步发布带请求键和会话头的前端/调用方。** 老调用方不能继续省略这些字段。迁移文件存在不等于迁移已在目标环境执行；本轮没有操作生产数据库。

历史反馈的新字段保留 NULL，不伪造请求键、学生归属或处理完成状态。旧的无会话归属诊断不能自动绑定给当前学生，其反馈返回 403；应保留历史事实，通过明确绑定的新实验会话开始后续诊断。

## 前轮验证记录（提交 3c7fcb1）

该轮完整流程集合为 **25 个合成场景，全部通过**。原始失败记录继续保留在 [第二阶段报告](workflow-evaluation-phase2.md)，该次结果保存在 [整改后 PostgreSQL 评测记录](../output/workflow-evaluation/remediation-postgres.json)。报告仅含合成输入和 Mock 输出，不能作为真实硬件准确率。

| 检查 | 本轮结果 |
| --- | --- |
| PostgreSQL 完整流程评测 | 25/25 passed |
| 反馈可靠性专项 | 42/42 passed；含 6 个 put 与 8 个 put_writes 故障点在 SQLite/PostgreSQL 双库下的 28 项注入，以及关闭会话已消费补确认/未消费拒绝边界 |
| 后端全量测试 | 330 passed，无 skipped/xfail；40.34 秒，1 项 Starlette/anyio 依赖弃用警告 |
| Alembic 迁移 | 空库升至 0027、带两条历史反馈的 0026 升至 0027、`alembic check`、单 Head 与重复键拒绝均通过；历史 NULL 保留 |
| Experiment Package 校验 | 两包各 10 项通过，均为 2.0.2，hash 不变 |
| 结构化知识、V2 工作流、合成诊断 CLI | 通过；合成诊断 30/30，未调用真实 Provider |
| 前端 Vitest | 8 个文件，43 passed |
| 学生端 Chrome Playwright | 4 passed；反馈路由实查 request_id 和会话头，使用 Mock API，不是浏览器连接真实后端的验收 |
| 前端 TypeScript、ESLint、生产构建 | 通过；依赖库已有构建注解警告不影响退出结果 |

后端回归入口：[完整流程评测](../backend/tests/test_workflow_evaluation.py)、[反馈可靠性](../backend/tests/test_feedback_reliability.py)、[候选证据映射](../backend/tests/test_candidate_evidence_mapping.py)。独立写定的合成预期保存在评测期望文件，不交给被测 AI；报告保留来源、UUID、输入/输出与单项检查，不包含登录密码或认证 token。

V2 CLI 原先的合法测试夹具没有为候选填写对应 Evidence 引用，因而被新关联校验正确拒绝；本轮补齐候选与夹具注册表的对应关系，没有放宽生产校验。这些只是 validator 合成条目，不称为真实落库或真实硬件 UUID；报告显式标记 `is_test_data`、`hardware_validation=not_run`、`teacher_confirmation=synthetic_fixture_only`。

该轮报告的代码与夹具 hash 在提交前已逐项核对；它记录前轮源代码，不代表后续修改后的 hash。AST 比较确认该轮图与基线的节点、边及条件边声明一致。历史 `phase2-postgres.json` 仍保留 13 passed / 3 failed，不用整改后的结果覆盖失败基线。

在隔离 PostgreSQL 测试库配置好 `XINJIAN_EVAL_POSTGRES_DSN` 和 `TEST_DIAGNOSIS_CHECKPOINT_DSN` 后，可从仓库根目录重跑。后者供可选 Checkpoint 集成测试使用，缺少时该项会跳过，不能得到本轮“无 skipped”的全量结果：

```bash
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation --postgres \
  --output output/workflow-evaluation/remediation-postgres.json
pytest backend/tests -o addopts='' -q -ra
```

缺失环境、未执行和失败继续分开记录，不通过豁免已知失败获得绿色报告。迁移验收与流程评测分别记录，ORM 创建测试表不能代替迁移升级验证。

本轮临时 PostgreSQL schema 清理后计数为 0，测试容器及迁移夹具临时文件已删除；保留可复查的评测报告。

## 反馈找回与持续验收（本轮）

前轮整改先提交为 `3c7fcb1`。本轮新增服务端只读找回、学生确认面板、首次诊断入口和旧响应隔离，以及 CI/本地门禁；没有新增数据库迁移。GET 契约见 [API 设计](api-design.md)，测试环境与复现参数见 [评测准则](evaluation.md)。

真实联调使用合成身份和设备报文、Mock Provider，但页面请求经过真实 HTTP、FastAPI、诊断图、PostgreSQL 业务表与 Checkpoint，数据库结构通过 Alembic 创建。两条场景分别验证正常反馈重放/刷新，以及 pending 后关页重登/纯读找回/明确点击后只推进一次。它们不同于现有 Mock API 页面测试，也不代表硬件或真实模型效果。

联调环境另修正两处测试工具问题：public 已迁移时，新 schema 必须有独立 Alembic 版本表，避免跳过迁移；Uvicorn 退出时必须展开清理并断言 schema 删除。早期尝试的残留已定向清理。提交检查还发现原演示材料的 `node_modules` 是符号链接，目录专用忽略规则没有覆盖，现改为同时匹配目录与链接；保留原材料。

| 检查 | 当前实际结果 |
| --- | --- |
| 后端全量 | 342 passed，无 skipped/xfail；35.25 秒，1 项依赖弃用警告 |
| 新增反馈找回专项 | 11 项，已包含在后端全量；覆盖双库、较早诊断、原备注、纯读/重放、归属、关闭会话、旧 NULL 与数量上限 |
| PostgreSQL 完整流程 | 25/25 passed；[本轮 JSON](../output/workflow-evaluation/local-postgres.json)，真实 Provider 调用 0，hardware_validation=not_run |
| 模拟器 | 16 passed |
| 两个 Experiment Package | 各 10 项校验通过，均为 2.0.2，内容与前轮提交不变 |
| 合成诊断/结构化知识/V2 CLI | 全部通过；合成诊断 30/30 |
| 数据库与主图 | Head 为 0027，alembic check 无差异；图节点、边和条件边与 3c7fcb1 一致，无包或迁移改动 |
| 前端单元测试 | 8 个文件、60 passed |
| Mock API 浏览器测试 | 7 passed：6 学生、1 教师 |
| 浏览器连接真实后端/数据库 | 2 passed；本地 Chrome，独立迁移/落库/清理断言均执行 |
| 其他门禁 | Ruff、ESLint、TypeScript、生产构建、版本一致性、提交路径/高置信密钥扫描及差异检查通过 |

完整门禁首次在提交路径检查处被上述依赖链接拦下；修正忽略规则后，该检查通过，并按脚本顺序执行全部剩余前端步骤。已通过的后端步骤未重复运行，未删测试或放宽扫描。前端本机 Node 26 有 localStorage 实验性提示、颜色环境提示及既有依赖 PURE 注解警告；CI 使用 Node 22，其实际运行尚待验证。

`.github/workflows/ci.yml` 已配置 PostgreSQL 流程评测、始终保留该步 JSON 和真实浏览器联调。缺专用 DSN 时本地门禁写 blocked 并退出 2，不借用应用数据库、不跳过后报绿。本轮是本机结果，未推送触发 GitHub CI、未部署；不能将“已配置”写成“云端已通过”。

最终核对：本轮 JSON 中 125 个源码文件及两份输入/预期文件的 hash 与工作区一致。测试结束后随机评测 schema 剩余 0，public 的设备、用户、反馈和工作流记录均保持 0；本轮临时 PostgreSQL 容器已删除，流程与浏览器结果保留在上述本地报告路径。

## 不变边界与剩余工作

- 保留 LangGraph 节点和边、规则—故障树—受约束 AI 分工、PostgreSQL Evidence 主设计与实验包版本机制。同步保存及反馈确认属于既有暂停恢复流程的可靠性修正，没有增加模型自由规划。
- DHT11 与 LED 实验包仍为 `2.0.2`，未新增硬件结论、教师签署、真实学生案例或自动 approved KnowledgeCase；未引入 RAG、Embedding、多智能体、自由 Agent 或新 AI 功能。
- GPIO、周期、连续失败阈值、DHT11 故障日志和可区分性、LED level 来源和物理发光仍 `pending_hardware`；课程标准、教师经验、操作建议及真实学生案例仍 `pending_teacher` / `pending_course_confirmation`。
- 当前学生认证仍以设备凭据和已有实验会话为基础。完整学生账号认证、真实模型语义质量、生产负载及任意崩溃恢复不是本轮完成项。
- 本轮改动在本地；未部署、未推送 GitHub。源码整改、隔离测试通过、目标环境部署和真实硬件验收分别报告。
