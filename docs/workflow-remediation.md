# 完整流程评测问题整改

更新：2026-09-15。范围：完整流程问题、反馈找回，以及 PDF 反例整改。各轮历史结果分别保留；最新结果见“PDF 反例整改”。

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

## PDF 反例整改（2026-09-15）

### 项目负责人可读摘要

| 问题 | 本轮结论 |
| --- | --- |
| 发现什么？ | 关键词误拦否定句、漏掉改写；固定限制抹去具体信息；Rubric 二元写法未完整记录。 |
| 有何影响？ | 正确表述被当错，未命中关键词被误当好；学生不知道还缺哪项检查。 |
| 现在解决了吗？ | 改正判定范围，扫描只记线索；报告把代码通过与语义未执行分开。解释保留具体待核验项、冲突和本次异常，补齐二元 Rubric。完整自由文字语义判断仍未实现，不报通过。 |
| 还需谁确认？ | 教师/独立审阅者判断具体语义条目，硬件负责人提供故障真值和实际测量；本轮不伪造这些材料。 |
| 下一步？ | 审阅新版报告与输出，再按四条 Rubric 逐项审阅真实输入/回答；若要引入模型裁判，单独决定，不能自动增加评分。 |

### 对应反例与行为

- “当前不能宣称真实硬件验证通过”：关键词会被记录，但没有语义失败判定。
- “本系统已经通过实物设备的验证，可以放心使用”：不命中关键词也不会得到语义通过。两者的语义 judgement 均为 null、status 为 not_run；整体合成报告为 incomplete。
- 精确规则结果被注入 `FABRICATED_ERROR`：代码检查仍失败，合成 CLI 退出 1。没有删除这类强制检查或降低匹配要求。
- “缺少供电测量记录”：若在当前推理的 missing_evidence 中，会以“推理提出的待核验项（未确认）”保留在限制说明、数据库输出及回放中。它不是已确认的硬件事实；解释模型单独编写的“已确认供电正常”不直接采纳。
- 根因 reason 自由文字仍可能与结构化 low 支持矛盾：本轮没有假装能用关键词修好这个既有语义缺口。SEM-01 明确登记要求但未执行，保持待独立审阅。

二元条目在 `backend/evaluation/semantic_rubrics.json`，每条只描述符合侧、只检查一件事，判断仅允许“符合/不符合”；未审阅不产生判断，没有分数、评级或总分。格式测试验证条目存在、唯一、长度和报告覆盖，不宣称自动检查自然语言定义的质量。

### 兼容与范围

- 合成 JSON 升为 `7-code-and-semantic-separated`：顶层 passed 替换为 code_checks_passed；forbidden_claims 替换为 pattern_scan；semantic_review 明确每条未运行。代码通过时整体仍 incomplete。CLI 退出 0 仅表示代码检查，verify 收尾同步说明范围。
- 解释输出契约升为 `explanation-boundary-v2`，旧 v1 审计不改写，按既有策略不符合当前契约时返回确定性降级；缓存指纹包含实际契约输入。
- 无前端字段或数据库迁移变更；没有改 LangGraph 节点/边、两个 2.0.2 包、原规则/故障树、AI 候选/证据白名单。没有新 AI 功能、模型裁判或 RAG。
- 旧审计探针与报告保留在 `output/audits/pdf-interpretation-2026-09-15/`，反映整改前 API；对应反例现在进入正式回归测试，不改写原失败记录。

### 当前实际验证

| 检查 | 结果 |
| --- | --- |
| 后端全量（包含 PostgreSQL 测试） | 349 passed，无 skipped/xfail，56.71 秒 |
| PostgreSQL 完整流程软件场景 | 25/25 passed；`output/audits/pdf-remediation-2026-09-15/workflow-postgres.json` |
| 两个实验包 | 各 10 项通过，均为 2.0.2，hash 未变 |
| 合成诊断 CLI | 30 项精确规则检查通过，正常退出；语义未运行，整体报告 incomplete，不称为完整语义验收通过 |
| CLI 失败路径 | 注入精确错误枚举后退出 1 |
| 静态检查 | Ruff、安全扫描、差异检查通过 |

回归入口：`test_evaluation_contract.py` 的否定/改写/精确错误/具体限制/二元条目测试，以及 `test_ai_diagnosis.py::test_specific_pending_information_survives_persistence_and_replay`。合成 JSON 保存在 `output/audits/pdf-remediation-2026-09-15/synthetic.json`。

本轮未重跑浏览器联调或云端 CI，未部署、未推送；没有真实 Provider、硬件测试或教师签署。测试在本轮临时环境执行，历史测试数量不算作本轮结果。

本轮收尾核对：报告内 125 个源码 hash 和 2 个输入/预期 hash 与当前文件一致；临时库未遗留评测 schema，临时 PostgreSQL 容器已删除。

## 追加复查与完整回归（2026-09-15）

### 项目负责人可读摘要

这次复查发现两个真实漏洞：推理已经说“不知道”，解释层仍可能重新拿故障树候选生成原因；测试案例或未确认根因的案例，也可能被当作教师确认资料传给推理。前者会让系统前后矛盾，后者会夸大资料可信度。

这两项已修复，并先用反例复现失败、再验证修复通过：

- 明确的 unknown、空推理结果禁止解释层重新引入候选；unknown 中残留旧候选也不能绕过。未接入推理阶段的旧调用保留原兼容路径。
- 教师确认案例只接受非测试资料、confirmed 根因且根因值非空的参考。测试资料保留测试标识，未确认内容不填入 confirmed_root_cause。普通故障映射仍检查实验类型和异常类型，不因移出教师案例列表而跳过校验。
- LangGraph 只修正文案，节点、边和运行流程未改；实验包、数据库迁移和模型功能未改。

这些软件问题现在可以解决。实际硬件结论、教师签署仍需对应负责人确认；自由推理文字的语义质量仍是未执行的独立审阅，不能用此次测试通过来证明。下一步应按二元 Rubric 审阅实际回答并安排硬件验证。

### 本次实际结果

| 检查 | 结果 |
| --- | --- |
| 后端全量，含隔离 PostgreSQL 测试 | 354 passed，58.63 秒，无跳过 |
| 模拟器 | 16 passed |
| 前端单元测试 | 60 passed |
| 浏览器页面回归 | 7 passed |
| Chrome + 真实 FastAPI + 隔离 PostgreSQL 联调 | 2 passed，覆盖重复提交幂等及关闭页面后恢复 |
| PostgreSQL 完整流程评测 | 25/25 passed |
| DHT11 / LED 实验包 | 各 10 项通过，2.0.2，hash 不变 |
| 其他门禁 | Ruff、前端 lint/type-check/build、结构化知识校验、V2 证据流程校验、版本一致性、安全扫描、git diff 检查通过 |
| 合成诊断报告 | code_checks_passed=true；语义 not_run，整体 incomplete |

前端工具输出了 Node localStorage、Rollup 依赖注释和颜色环境变量提示，没有导致测试或构建失败。本轮未调用真实模型、未做真实硬件实验、未推送或部署。

报告：`output/audits/pdf-recheck-2026-09-15/workflow-postgres.json`、同目录 `synthetic.json`。浏览器联调结果保留在同目录 `browser-integration.json`。旧报告保留原样，不能把旧次数算入新结果。

收尾：125 个源码和 2 份评测输入/预期的 hash 与报告一致；随机测试 schema 剩余 0。本轮临时数据库容器与 Python 环境已删除，报告已保留。

## 报告整理（2026-09-16）

自动报告按 [固定存放约定](test-reporting.md) 分成 Markdown 摘要、简明 JSON、按需 gzip 排错附件，默认只保存失败用例的完整轨迹。旧记录原地保留并从 Git 改动列表排除，主流程及检查条件不变。

本轮后端 361 项通过；PostgreSQL 流程 25/25 通过；新版实际摘要 40 行、JSON 352 行。新报告专项覆盖失败证据保留、退出码、完整/关闭附件选项及仅清理同名旧附件。Ruff、CI YAML 解析、脚本语法、安全扫描、差异检查通过。源码指纹已核对；临时 schema 剩余 0。CI 摘要与附件上传已配置但尚未推送验证；前端本轮未重跑。真实硬件和独立语义审阅仍未完成。
