# 芯鉴知微实现状态

- 最后更新：2026-09-05
- 仓库版本：`1.0.0`
- 诊断图版本：`langgraph-v2`
- 数据库迁移 Head：`20260904_0026`

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
- AI 只能引用本次诊断真实写入 `diagnosis_evidence` 的 UUID，不再生成伪证据 ID。
- `knowledge_validation` 在推理后校验错误类型、候选原因、证据 ID、实验一致性和允许动作。
- AI 关闭、失败、超时或越界时使用确定性降级或 `unknown`。
- 学生反馈恢复同一工作流；教师审核是受权限控制的暂停点。

## 3. Experiment Package

已实现十工件实验包、严格 Pydantic Schema、跨引用校验、Manifest/包 SHA-256、包内正常/故障样例、数据库快照、审核发布和运行时版本锁定。

当前完整示例包：

1. `dht11_temperature_humidity@2.0.0`
2. `gpio_led_output@2.0.0`

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
- 固定持久化证据 UUID 集合；
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
