# 芯鉴知微实现状态

最后更新：2026-09-04

诊断图版本：`langgraph-v2`

数据库迁移 Head：`20260904_0026`

## 总体结论

当前架构已经升级为“通用诊断引擎 + 版本化实验包 + 标准证据层 + 证据驱动诊断工作流”。V2 复用现有设备采集、确定性诊断、知识治理、AI 降级和教师审核，没有引入 RAG、多智能体或 Agent 自主规划。

当前仍不是经过真实硬件数据验证的专业故障诊断产品。真实设备数据、正式硬件参数、正式课程资料和生产 AI 调用仍需项目方提供或批准。

## V2 增量调整

| 项目 | 当前状态 | 说明 |
| --- | --- | --- |
| `DiagnosisContext` | 保留 | 仍是日志、心跳、读数、实验定义与设备信息的统一输入 |
| `DiagnosisState` | 已升级 | 保存一次诊断的上下文、规则、原因、知识、反馈、提示与状态 |
| Experiment Package | 已新增 | 数据化封装硬件、规则、故障树、知识、教学步骤、提示和测试 |
| 实验包版本发布 | 已新增 | PostgreSQL 保存不可覆盖快照，支持校验、导入、审核、发布和旧版本重放 |
| 诊断版本锁定 | 已新增 | 任务、工作流和诊断结果可绑定同一 `experiment_version_id` |
| 标准证据表 | 已新增 | 原始载荷与标准化值分开保存，规则和 AI 使用可追溯证据 ID |
| LangGraph | 已升级至 V2 | 负责节点顺序、状态流转、条件分支、Checkpoint 和审核暂停恢复 |
| 规则引擎 | 保留 | 负责异常类型和确定性证据，AI 不得覆盖 |
| 故障树 | 保留 | 负责候选原因、证据排序、分级提示和教师介入 |
| AI 原因推理 | 已升级 | 只在故障树候选集中重排，输出支持等级、证据 ID、缺失证据、冲突和验证动作 |
| `KnowledgeCase` | 新增 | 使用实验类型、错误类型和证据字段做确定性匹配 |
| 知识双阶段 | 已升级 | 推理前匹配 approved 案例并供给约束；推理后以确定性代码校验输出 |
| 外置知识文件 | 新增 | `backend/knowledge/cases/`、`templates/`、`rules/`，诊断函数不再硬编码实验经验 |
| AI 解释 | 保留 | 输入仅为已确定数据、规则、故障树和匹配案例；输出经严格结构校验 |
| 学生反馈节点 | 已升级 | interrupt 等待学生反馈，并恢复同一 LangGraph thread 持续诊断 |
| 升级处理节点 | 新增 | 根据失败次数、异常持续时间、提示等级和反馈决定教师介入 |
| 案例草稿闭环 | 已升级 | resolved 只生成 unknown 根因草稿；教师确认根因和真实修复动作后入库 |
| AI 分阶段审计 | 新增 | `reasoning` 与 `explanation` 分别幂等记录和校验 |
| RAG 条件分支 | 已移出主链 | 诊断图不再计算或跳转 `needs_rag` |
| Embedding 实现 | 已移出 MVP | 不再创建或调用线上 Embedding Client |
| 向量搜索 API | 已关闭 | 知识 API 不再暴露向量写入和搜索端点 |
| RAG 环境变量 | 已删除 | `.env.example` 与 Compose 不再配置 RAG Top-K、RRF 或 Embedding Provider |

## 当前诊断工作流

```text
context_builder
  → rule_engine
  → fault_tree_analyzer
  → knowledge_context
  → ai_reasoning
  → knowledge_validation
  → ai_explanation
  → escalation_handler
  → feedback_handler
      ├─ unresolved → knowledge_context（下一轮）
      ├─ resolved → persist_result
      └─ request_teacher_help → teacher_review
```

`knowledge_context` 在推理前供给已审核的实验定义、正常条件、故障映射和教师确认案例。对已绑定实验包的诊断，案例只从该版本的 PostgreSQL 包快照读取；推理后还会从这份可信快照重新装载，防止状态中的案例内容或 ID 被篡改。`ai_reasoning` 不能扩展故障树原因空间；非法输出自动回退确定性排序。`knowledge_validation` 在推理后独立检查实验规范、证据 ID、候选集、规则结果和允许动作；它不是 RAG 分支。没有已审核案例时记录 `validated_without_case`，但不阻断诊断。

## 实验包落地状态

已新增 `backend/experiment_packages/`，首批有两个完整包：

1. `dht11_temperature_humidity@2.0.0`；
2. `gpio_led_output@2.0.0`。

两个包都包含元数据、硬件连接、证据映射、规则、故障树、概念、教师确认案例、教学步骤、四级提示、正常样例和故障样例。它们通过同一个通用加载器、规则引擎和诊断接口运行，没有为 DHT11 或 LED 新增专用 Python 判断函数。

实验包接口已增加：

- `POST /api/v1/experiments/packages/validate`：只校验，不写数据库；
- `POST /api/v1/experiments/packages/import`：校验后导入不可覆盖的草稿版本；
- `GET /api/v1/experiments/package-versions`：查看版本和校验结果；
- `POST /api/v1/experiments/package-versions/{id}/status`：管理员审核、发布或撤销；
- `GET /api/v1/diagnosis/results/{id}/evidence`：查看本次诊断的标准化证据和来源。

`20260904_0026` 是纯增量迁移：新增实验、实验版本、实验包工件和标准证据表，并给任务、诊断结果、工作流增加可空的版本关联；没有删除旧表、回填猜测数据或中断旧接口。

## DiagnosisState 状态

V2 核心状态字段已落地，并增加 `attempt_count`、`missing_evidence`、`next_verification_action`、`evidence_conflict`、`evidence_registry` 和 `allowed_verification_actions`。推理使用离散支持等级，不把模型分数解释成统计概率。

已有 ID、规则/故障树版本、输入指纹、节点轨迹、耗时和 V1 兼容字段继续保留。数据库增加包版本关联和 `state_revision`；其余细粒度过程字段继续由 LangGraph Checkpoint 管理，避免无必要地扩表。

## 结构化知识状态

已建立 `knowledge_cases` 数据表与 `20260901_0022` 迁移，字段覆盖正常状态、常见异常、判断依据、可能原因、排查步骤、教师经验、审核状态、来源和版本。

已建立五个初始 YAML 案例：

1. DHT11 温湿度实验；
2. LED 实验；
3. 按键实验；
4. 光敏传感器实验；
5. 超声波实验。

这些内容目前均为 `pending`，目的是建立结构和审核流程，不得对外宣称为已经过硬件验证的正式知识。运行前执行：

```bash
cd backend
python -m app.cli.sync_knowledge_cases
```

只有 `approved + confirmed + facts_locked + quality_check_passed` 的案例才会被主链匹配。

新增 `knowledge_case_drafts` 表与审核服务。学生提交 `resolved` 只证明现象恢复，草稿根因保持 `unknown`。AI 只能填表达字段并记录模型、Prompt 和 Token 审计；修改证据、原因或步骤会被拒绝。教师批准时必须确认故障树内根因、真实解决步骤和确认说明。

## AI 边界

- AI 不直接判断硬件故障。
- AI 输入是脱敏后的设备状态、相关日志、读数聚合、规则结果、故障树结果和匹配案例。
- AI 输入包含当前 V2 `DiagnosisState` 的受控投影。
- AI 推理输出必须使用已有 `cause_id` 和证据白名单；无法判断时返回 `unknown`。
- AI 输出的核心字段是 `error_type`、`evidence`、`possible_causes`、`steps`、`hint_level`、`need_teacher_help`。
- `error_type` 和 `evidence` 必须来自后端白名单，案例引用必须来自本次匹配结果。
- AI 关闭、超时、限流、预算不足或输出非法时，使用确定性结果。
- 工作流最终提示等级和教师介入决定由后端 `escalation_handler` 写入，AI 输出不能覆盖。

## 兼容边界

为避免本次小调整破坏已有数据库和审计重放，部分历史字段与迁移仍保留：

- `diagnosis_workflow_runs.needs_rag` 新流程固定为 `false`；
- `embedding_version` 新流程固定为 `null`；
- `retrieval_audit` 用于存储结构化案例匹配审计，`mode=structured_case_match`；
- 旧 `chunk_id`/`knowledge_references` 容器中的新值为 `case_id`，不表示向量 Chunk；
- `hybrid_retrieval` 只保留一个会明确拒绝调用的升级兼容门面，不包含检索逻辑。
- V1 已完成记录继续可读；新记录默认写入 `graph_version=langgraph-v2`。
- `ai_call_records` 由原来的“每工作流一条”升级为“每工作流、每调用阶段/反馈轮次一条”，支持持续诊断审计。

这些兼容字段将在后续独立数据迁移中清理，不影响 MVP 当前不使用 RAG 的运行事实。

## 未来 RAG 路线

当结构化案例规模和查询需求证明显式匹配不足时，再依次新增 `knowledge/embedding/`、`knowledge/vector_store/` 和 `knowledge/rag/`。扩展层只使用已审核 `KnowledgeCase` 产生可重建索引，不改变规则证据、故障树排序和 AI 输出校验边界。

## 仍需项目方提供或确认

1. 硬件 BOM、型号/版本、原理图、接线、GPIO、供电和安全限制。
2. 传感器字段、单位、量程、精度、采样策略和正式错误码。
3. 五类实验的正式正常状态、故障真值、最终修复动作与教师审核结论。
4. AI Key、预算、频率上限、数据外发、隐私与保留审批。
5. 正式用户、课程、班级、任务和设备绑定清单。
6. 生产网络、域名、HTTPS、监控告警、备份责任与验收指标。

上述输入未完成前，readiness 应保持 `blocked`，不得对外宣称具备已验证的真实硬件故障诊断能力。

## 验证状态

| 检查 | 2026-09-04 结果 |
| --- | --- |
| 后端 Ruff | 通过 |
| Python 语法编译 | `backend/app` 与迁移脚本通过 |
| Docker 后端镜像 | 使用 Python 3.12 与锁定依赖构建通过 |
| 迁移 Head | `20260904_0026 (head)` |
| 实验包校验 | DHT11、LED 各 9 项 Schema、引用和包内样例检查通过 |
| 实验包定向测试 | 5/5 通过：双包同引擎、版本不可覆盖、数据库运行时、管理 API、标准证据落库与包内案例供给 |
| V2 状态图验收 | 9 个核心节点与 23 个核心状态字段通过；推理前知识供给、推理后独立校验、未解决反馈续诊、证据 ID、`unknown` 回退和无 RAG 分支均通过 |
| 结构化知识验收 | 5 个外置案例加载通过；精确匹配命中实验类型、错误类型和证据 |
| 案例沉淀闭环 | unknown 根因草稿、AI 表达字段防篡改、教师根因/修复动作确认和正式案例四重门槛通过 |
| 确定性合成评测 | 30/30 错误类型精确匹配；原因 Top-1/Top-3 与必需步骤均为 100%；禁止性声明 0 命中；AI Provider 调用 0 |
| 前端类型检查 | 通过 |
| 前端 ESLint | 通过 |
| 前端 Vitest | 5 个文件、26 个测试全部通过 |
| V2 后端定向测试 | 31 个推理、AI 案例整理、知识双阶段校验、结构化匹配与 LangGraph 工作流测试通过 |
| 后端全量 pytest | 184 通过，1 跳过 |
| PostgreSQL 全量迁移 | 在独立临时数据库从初始版本升级至 `20260904_0026` 通过，`alembic check` 无模型差异，临时数据库已删除 |

本地历史 `backend/.venv` 仍是 Python 3.9 且没有 LangGraph，不符合当前 Python 3.10+ 要求，因此全量 pytest 使用独立 Python 3.13 临时环境，PostgreSQL 迁移使用项目 Python 3.12 容器验证。已取消的向量召回指标不再列入 V2 验收。
