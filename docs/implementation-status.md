# 芯鉴知微实现状态

- 最后更新：2026-09-12
- 仓库版本：`1.0.0`
- 诊断图版本：`langgraph-v2`
- 数据库迁移 Head：`20260912_0027`（本地代码；部署前需升级）

## 1. 总体结论

当前代码已形成“通用诊断引擎 + 版本化 Experiment Package + 标准证据 + 状态驱动工作流”的 V2 基线。设备采集、规则、故障树、结构化知识、受约束 AI、学生反馈和教师审核在同一条可审计链路中协作。

这是一套已通过合成数据自动化验证的工程框架，不是已经通过真实硬件验收的成品。真实设备参数、故障真值、正式知识、正式课堂数据和生产配置仍待项目方提供与确认。

## 2. 当前诊断流程

```text
context_builder
  -> rule_engine
  -> fault_tree_analyzer
  -> knowledge_context
  -> ai_reasoning
  -> knowledge_validation
  -> ai_explanation
  -> escalation_handler
  -> feedback_handler
       ├─ unresolved -> escalation_handler -> knowledge_context
       ├─ resolved -> persist_result / 案例草稿
       └─ request_teacher_help -> teacher_review
```

已落地的核心约束：

- 规则引擎是 `error_type` 的唯一判断者。
- 故障树限定候选原因；支持分只用于排序，不是概率。
- `knowledge_context` 在 AI 推理前提供实验定义、正常条件、故障映射和已确认案例。
- `ai_reasoning` 只能重排候选原因，不能引入新故障。
- AI 只能引用本次诊断真实写入 `diagnosis_evidence` 且属于对应候选 `evidence_refs` 的 UUID，不生成伪证据或借用无关引用。
- `knowledge_validation` 在推理后校验错误类型、候选原因、证据 ID、实验一致性和允许动作。
- AI 关闭、失败、超时或越界时使用确定性降级或 `unknown`。
- 学生反馈恢复同一工作流；教师审核是受权限控制的暂停点。

## 3. Experiment Package

已实现十工件实验包、严格 Pydantic Schema、跨引用校验、Manifest/包 SHA-256、包内正常/故障样例、数据库快照、审核发布和运行时版本锁定。

当前完整示例包：

1. `dht11_temperature_humidity@2.0.2`
2. `gpio_led_output@2.0.2`

两者使用同一通用加载、规则、故障树和证据链，没有在核心 Python 代码中增加按实验名称判断的专用分支。两个包和案例均明确标记为测试数据，尚未经过真实硬件或教师正式审核。

已有 API 支持包校验、导入、版本查询和状态流转。已发布版本通过现有服务/API 不可覆盖；新版本发布后旧版本仍可用于历史重放。

当前限制：`metadata.compatibility.engine` 尚未执行语义版本判断；concepts 和 steps 工件已校验/存储，但未被所有教学路径完整消费；数据库没有为包不可变性提供完整触发器兜底。

## 4. 证据治理

`diagnosis_evidence` 已将来源原始值和规范化值分开保存，并关联诊断、实验包版本、来源记录和发生时间。规则事实、Observation 和 Event 都有真实 UUID。

本轮严谨性修正：

- 移除了 `device:status`、`log:*`、`history:*` 等运行时伪证据 ID 的生成逻辑。
- AI 推理前从数据库读取当前诊断的证据行，形成唯一可引用白名单。
- 图等价性测试校验证据注册表和故障树引用都是持久化证据 UUID 的子集。
- 使用测试实验包产生的 `DiagnosisResult` 和 `DiagnosisWorkflowRun` 会继承测试标记。

## 5. 结构化知识

当前有两条知识路径：

- 已绑定包的新流程：只从当前 `experiment_version_id` 的 PostgreSQL 不可变包快照加载案例。
- 未绑定包的兼容流程：从 `knowledge_cases` 表加载外置 YAML 同步的案例。

两条路径都要求正式案例满足 `approved + confirmed + facts_locked + quality_check_passed`。匹配按实验、错误类型和显式证据字段执行，不使用语义向量相似度。实验包案例已经增加错误类型过滤，避免同实验下错误类型不匹配的案例进入推理。

兼容目录目前包含 DHT11、LED、按键、光敏、超声波五类初始案例，均为 `pending` 或测试资料；当前不能当作正式教师知识。

案例沉淀采用草稿闭环：学生解决反馈只产生根因 `unknown` 的事实草稿，AI 仅能润色表达字段，教师确认根因和真实解决动作后才能发布。

## 6. AI 与 LangGraph

LangGraph 已负责节点顺序、状态流转、条件分支、Checkpoint、反馈恢复和教师审核，不允许模型自主选择节点、工具或执行计划。

AI 可参与候选原因排序和解释，但受到以下白名单约束：

- 固定规则错误类型；
- 固定故障树 `cause_id` 集合；
- 固定持久化证据 UUID 集合，并按候选关联进一步限定；
- 固定知识案例 ID 和允许排查动作；
- 严格 JSON Schema、脱敏、长度限制、预算、缓存和调用审计。

AI Provider 默认关闭，仓库没有真实 Key。Mock、禁用和确定性降级测试通过，不代表真实 Provider 已完成质量、成本或隐私验收。

## 7. 已移出当前架构的内容

- 删除未被生产代码使用的 LangChain 诊断 Tools 和直接 `langchain` 依赖。
- 删除旧混合检索评测数据和 Recall/MRR/RRF 文档基线。
- 当前图不包含 RAG 分支，不调用 Embedding，不查询向量数据库。
- 前端不再展示 RAG 计数，并把故障树分数显示为“证据支持分”，不表述为概率。

为兼容旧数据库和 API，历史 `knowledge_embeddings` 表、`needs_rag`、`embedding_version`、`retrieval_audit`、`retrieved_chunks` 等结构暂时保留。新工作流固定 `needs_rag=false`、`embedding_version=null`，其中的知识引用只表示结构化案例。

Compose 与 CI 使用 pgvector PostgreSQL 镜像，是因为不可修改的初始迁移包含 `CREATE EXTENSION vector`；这不是当前业务对向量检索的依赖。

## 8. 设备、课堂和前端

保留并验证的既有能力包括：

- 设备令牌认证、单条/批量接入、请求幂等、顺序冲突、时间质量、速率和大小限制。
- 测试运行 UUID、场景重放和设备范围的定向清理。
- 用户、角色、权限、课程、班级、选课、授课、任务和设备绑定模型。
- 学生设备会话、状态/日志/趋势/诊断展示、反馈和请求教师帮助。
- 教师 Bearer 会话、班级范围、异常聚合、工单认领/解决/关闭、追加审计和私人备注隔离。
- Readiness 对真实硬件、正式知识、课堂数据、AI 和生产条件分别给出状态，不用服务存活冒充业务就绪。

## 9. 已知限制

- 未解决反馈会重新执行知识供给、推理和解释，但不会自动重新采集设备上下文。
- `state_revision` 是业务审计计数，不是 Checkpoint 或数据库并发锁。
- 推理后校验是确定性身份/集合/动作/基本规范校验，不是完整电气安全证明系统。
- 新实验的正式参数和案例必须由真实资料与教师审核补齐。
- 历史兼容字段和表尚未完成独立数据迁移清理。
- 生产域名、HTTPS、密钥托管、监控告警、备份责任和数据保留策略尚未完成现场配置。

## 10. 本轮验证结果

2026-09-05 已完成：

| 检查 | 结果 |
| --- | --- |
| Ruff | backend 与 simulator 通过 |
| 后端 pytest | 184 个用例收集；183 通过，1 个可选 PostgreSQL 场景跳过 |
| 定向 V2/实验包测试 | 通过 |
| 合成诊断 | 30/30；错误类型、Top-1/Top-3、必需步骤均满足门禁 |
| 禁止性陈述 | 0 命中 |
| 实验包校验 | DHT11、LED 各 9 项检查通过 |
| 结构化知识校验 | 5 个案例文件加载和显式字段匹配通过 |
| V2 证据工作流 CLI | 原因/证据约束、双阶段知识、反馈续诊和教师案例闭环通过 |
| 模拟器 pytest | 16 个用例通过 |
| 前端 ESLint / TypeScript | 通过 |
| 前端 Vitest | 5 个文件、26 个用例通过 |
| 前端生产构建 | 通过 |
| Playwright 端到端 | Chromium 5 个用例通过 |

具体长期约束和完成标准见 [开发准则](development-guidelines.md)，测试解释边界见 [测试与评测准则](evaluation.md)。

## 11. 未来 RAG 路线

只有在已审核案例规模、同义表达召回问题和真实标注评测证明结构化匹配不足后，才考虑新增 `knowledge/embedding/`、`knowledge/vector_store/` 和 `knowledge/rag/`。未来向量索引只能是已审核知识的可重建派生物，不能改变规则事实、故障树候选空间、证据白名单或教师审核门槛。

## 12. 实验包信息可信化（2026-09-09）

本轮仅更新包内容和所需的通用诊断/证据语义，未改 LangGraph 节点、边或暂停恢复机制，未改发布状态机、AI 原因/UUID 白名单，未新增数据库迁移或 RAG。

- 两包 2.0.1 draft，案例 test_data/unverified（使用现有 draft/unknown 枚举），教师确认字段清空；故障树 placeholder。
- DHT11 以 failure_count_in_window 表达累计失败；连续计数 null，阈值待校准。
- LED 分离命令、电气测量、光学观测；旧 level 来源未知；以命令关联和有效时间窗比较，不固定要求 HIGH。
- 通用基础规则统一处理 DEVICE_OFFLINE、HEARTBEAT_STALE、DATA_STALE；实验包声明运行预期。normal_assessment 显式保存正常/异常/未知及各条件，不以零规则命中作为正常。
- DHT11 组件归一化及 Evidence 类型一致性已补充 HTTP 和持久化回归测试。
- 当前 GPIO、读数周期、LED 响应窗口、level 实际来源、真实故障表现和教师/学生案例仍 pending_hardware 或待课程确认；没有硬件测试结果。

具体字段与兼容性见 [实验包设计](experiment-package-design.md)。本轮没有向运行数据库导入或发布新包。

本轮验证（Python 3.13 隔离环境 `/tmp/xinjian-trust-venv`）：

| 检查 | 结果 |
| --- | --- |
| Experiment Package 校验 | DHT11、LED 各 10 项通过 |
| 后端全量 `pytest backend/tests -o addopts='' -q` | 200 passed、1 skipped；8.00 秒 |
| 跳过项 | 未配置 TEST_DIAGNOSIS_CHECKPOINT_DSN 的可选 PostgreSQL Checkpoint 集成测试 |
| Ruff | backend/app、backend/tests 全部通过 |
| git diff --check | 通过 |

测试有一项依赖库弃用警告（Starlette 使用 anyio BlockingPortal 旧别名），无测试失败。测试数据仍为合成输入；没有真实硬件验证。本次未修改原 Python 3.9 虚拟环境，也未运行生产数据库操作。

校验时包 hash：

- DHT11：`809925e695a0ca53c43b63d66aa51c8a8e430cd344276e5d8b718cfeeb366ded`
- LED：`68163bbdfe09b6cc607f96ab47b1c9f93c5e11065b3a527db0849ea491c6cfe3`

## 13. 项目真实性治理（2026-09-09，工作区 2.0.2）

新增 [项目真实性看板](project-truth-status.md)。保留前轮已完成修正，本轮新增实验包逐项硬件/教师/课程待确认注记，清楚区分设备证据、规则异常与候选根因；修正 LED 显式观测携带 pin 时的原始映射重叠，新增三类报文回归。包升为 2.0.2 草稿，没有修改任何数据库发布版本。本轮未再修改诊断主流程或 AI 功能。

### 项目负责人可读摘要

- **发现的问题：** 主要误导性判断已修正，但教师/课程的待确认责任还不够明确；部分 LED 原始报文会被重复匹配而拒绝。
- **现实影响：** 演示资料可能被当成教学依据；携带更多信息的报文反而无法处理。
- **现在能解决吗：** 标记和报文冲突已解决；代码不能替代真实硬件和教师确认。
- **还需要谁：** 硬件负责人验证板卡、日志、阈值和观测来源，教师确认课程验收与真实案例。
- **下一步：** 先取得准确器件清单和指导书，再按计划做正常—单因素故障—恢复对照。

### 本轮验证记录

- Python 3.13 隔离环境：`/tmp/xinjian-trust-venv`。
- `python -m app.cli.verify_experiment_packages`：DHT11、LED 各 10 项通过，均为 2.0.2。
- `pytest backend/tests -o addopts='' -q`：203 passed、1 skipped，9.26 秒。跳过项为未配置 TEST_DIAGNOSIS_CHECKPOINT_DSN 的可选 PostgreSQL Checkpoint 测试；有一项依赖库弃用警告，无失败。
- `ruff check backend/app backend/tests`、`git diff --check`、真实性看板表格与本地链接检查均通过。
- DHT11 包 hash：`de34ad455e03c3b164049a864fb3df3f764af475b3bb0ed9d12ab13c8151f058`。
- LED 包 hash：`0668d10dd6e551af43dd95bf31e904bcf5c03da01b3beb689868923ade7ee59a`。

本次仅使用合成自动化输入，没有新增真实硬件结果、教师确认或学生案例，也没有导入、审核发布数据库中的包版本。剩余待办逐项见真实性看板。

## 14. ClawEval 适配第一阶段（2026-09-12）

完成已批准的评测与输出约束修正，要求、反例及来源逐项记录在 [评测要求对应表](evaluation-requirements.md)。

### 项目负责人可读摘要

- **发现的问题：** 原禁止表述检查没有读取实际解释；无证据也可能获得 high 支持等级，解释还可包含允许范围之外的操作。
- **现实影响：** 测试通过不能说明学生收到的建议符合约束，候选原因容易被过度解读。
- **本轮解决：** 检查实际渲染结果，新增能使错误实现失败的反例；收紧证据和操作校验，将解释摘要及限制说明交给后端生成，同时检查缓存和历史输出路径。
- **仍需谁确认：** 证据与根因的真实关联需要硬件实验，教学步骤和案例真实性需要教师。自由推理文字的完整语义质量仍是后续评测事项。
- **下一步：** 审核本轮要求映射和验证边界，再决定是否推进完整流程评测。

### 变更与兼容

- 合成评测扫描实际解释，报告明确标记为精确短语检查，未执行语义评价。包内故障样例改为异常类型集合精确匹配，不能夹带额外异常。
- high 必须引用有效白名单证据，不能隐藏输入冲突；降级不再借用无关注册证据，没有可关联证据时允许 unknown。
- 解释步骤逐字匹配允许动作，摘要和限制使用后端模板。摘要个性化因此减少；此保护不覆盖全部自由推理字段或教师编辑文本。
- 实际 Prompt 哈希参与缓存键；缓存读取重新验证。缺少当前输出契约的旧审计记录保留原文，但不作为当前有效 AI 建议返回，也不因此重新调用模型。
- LangGraph 节点和边、PostgreSQL 证据主设计、Experiment Package 版本机制不变。没有引入 RAG、自由 Agent、语义 Judge 或数据库迁移。

### 验证记录

| 检查 | 结果 |
| --- | --- |
| 后端全量 `pytest backend/tests -o addopts='' -q -ra` | 230 passed、1 skipped，9.28 秒 |
| 跳过项 | 未配置 `TEST_DIAGNOSIS_CHECKPOINT_DSN` 的可选 PostgreSQL Checkpoint 集成测试 |
| Experiment Package 校验 | DHT11、LED 各 10 项通过；均为 2.0.2，包 hash 与上一节一致 |
| `verify_v2_evidence_workflow` | 通过；合成流程验证，`rag_enabled=false` |
| `run_synthetic_evaluation` | 30/30 合成样例通过；检查 6 个禁用短语，未命中；真实模型调用为 0 |

使用 `/tmp/xinjian-trust-venv` 的 Python 3.13。测试有一项 Starlette/anyio 弃用警告。测试未连接真实硬件或生产数据库；没有新增教师确认、真实学生案例或批准知识。全部待硬件、待课程状态保持原样。

## 15. 完整流程评测第二阶段（2026-09-12）

本节保留发现问题时的历史结果；当前修复状态见第 16 节。

第一阶段已保存为独立本地提交 `97c4d27`。第二阶段新增合成输入/独立预期、隔离环境、HTTP 与真实图评测器、JSON 报告 CLI 及篡改反例；不改生产流程、包、模型、接口或 Schema。说明和负责人摘要见 [第二阶段报告](workflow-evaluation-phase2.md)。

- 隔离 PostgreSQL CLI：16 场景，13 passed、3 failed，退出 1。已复现候选引用心跳、重复反馈推进、反馈缺请求会话归属三个问题；保留失败，不自动修改生产契约。
- 真实图恢复：关闭并重建 PostgreSQL 连接与诊断图后，状态/证据/审计不变，后续反馈及教师审核完成；不声称进程 kill 或断电验证。
- 后端全量：配置本次临时容器的两个 DSN，`pytest backend/tests -o addopts='' -q -ra` 得到 251 passed、3 strict xfailed、无跳过，12.97 秒。三个 xfailed 均为新报告的既有缺口；不是通过。
- 两个 2.0.2 包各 10 项校验、V2 工作流 CLI、Ruff 和差异检查通过。Starlette/anyio 一项既有弃用警告。
- 本轮没有真实 Provider 调用、硬件测试或教师知识签署；未发布实验包、未推送 GitHub。当前 CLI 为独立验收入口，尚未自动接入既有 CI。

## 16. 完整流程问题整改（2026-09-12）

已修正第二阶段三项问题：候选不再借用无关证据；反馈使用稳定请求键区分重试和新尝试；所有反馈写入和重放先校验实验会话归属。负责人五问摘要、兼容变化和具体证明范围见 [整改报告](workflow-remediation.md)。

- **现实影响与修复：** 防止“有 UUID 但依据不相关”、一次反馈重复推进，以及其他学生会话改变原诊断；增加丢回执、并发和保存故障的恢复边界。
- **反馈契约：** 必需 `X-Experiment-Session-ID` 和 UUID `request_id`；同键同载荷重放，改载荷 409；新尝试新键。前端保存当前标签页未决记录，成功才清除，关闭标签页不承诺保留。
- **迁移兼容：** 新增 0027，为反馈增加可空请求键、会话和处理状态，以及外键/唯一约束。旧记录保留 NULL，无归属诊断反馈 403；不按当前绑定伪造历史身份。部署前先升级数据库并配套更新调用方。
- **恢复边界：** 同步 Checkpoint，原反馈已消费时补业务确认；未消费时沿原请求恢复。关闭会话不能继续消费未应用反馈。没有引入跨存储分布式事务，也未完成任意进程崩溃/断电验收。
- **架构：** AST 比较确认节点、边和条件边与基线一致；实验包 2.0.2 及 hash 不变，未引入 RAG 或新 AI 功能。

| 检查 | 结果 |
| --- | --- |
| PostgreSQL 完整流程 CLI | 25/25 passed；新报告 `output/workflow-evaluation/remediation-postgres.json`；代码/夹具 hash 与工作区一致 |
| 后端全量 | 330 passed，无 skipped/xfail；40.34 秒，1 项 Starlette/anyio 弃用警告 |
| 反馈可靠性专项 | 42/42 passed；包括双库 28 项 Checkpoint 保存故障注入、并发重复请求、回执丢失和关闭会话边界 |
| Alembic | 空库与带两条历史反馈的 0026 升级到 0027、单 Head、模型差异、重复键拒绝通过 |
| 实验包/知识/V2/合成 CLI | 两包各 10 项通过；结构化知识及 V2 通过；30/30 合成诊断通过 |
| 前端 | 43 unit、4 学生端 Chrome E2E；lint、type-check、生产构建通过。E2E 使用 Mock API |

V2 CLI 仅补齐合成 validator 夹具的候选引用，不称这些条目为真实硬件 UUID；显式标记硬件未验证、教师仅为合成角色。原 `phase2-postgres.json` 的 13 passed / 3 failed 保留，原 strict xfail 已移除。

本轮没有真实硬件、真实模型或教师签署；GPIO、日志、阈值、LED 观测与课程事实仍待确认。学生认证仍为设备凭据与实验会话模式，未升级完整学生账号系统。当前未部署、未推送 GitHub，后续按兼容要求安排部署和硬件对照。
