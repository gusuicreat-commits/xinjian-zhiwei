# 芯鉴知微系统架构

最后更新：2026-09-04

## 1. V2 架构目标

V2 在现有 MVP 上增加证据驱动的 Diagnosis Workflow 和版本化 Experiment Package，不推翻设备采集、规则、故障树、结构化知识、AI 治理、学生端和教师端。采用 FastAPI 模块化单体、LangGraph 流程编排、PostgreSQL 业务库和 Vue 3 前端，不引入多智能体、自主规划、向量数据库或 RAG 核心链路。

本轮实现以《芯鉴知微 V2 最终架构文档：完整对话总结与技术决策》（2026 年 9 月）为开发基线，落实 Evidence、Deterministic Diagnosis、Constrained Reasoning、Teaching Workflow 和 Knowledge Lifecycle 五层边界。

## 2. 逻辑架构

```text
[嵌入式设备 / 传感器]
       | HTTP + JSON + device token
       v
[FastAPI /api/v1]
       |-- 设备认证、校验、限流与幂等采集
       |-- Experiment Package Resolver：锁定实验与已发布版本
       |-- DiagnosisContext 归一化 + 标准证据落库
       |-- LangGraph Diagnosis Workflow
       |     |-- 规则引擎：异常类型 + 确定性证据
       |     |-- 故障树：候选原因 + 证据排序
       |     |-- AI 受约束原因排序：候选集内推理 + 证据白名单
       |     |-- KnowledgeCase 结构化校验与经验补充
       |     |-- 可选 AI 结构化解释
       |     `-- 学生反馈、提示升级与教师介入
       |-- 校验、审计、Checkpoint 与确定性降级
       v
[PostgreSQL]
       ^
       |
[学生端 / 教师端] -- Axios --> [FastAPI]
```

LangGraph 只管理节点顺序、状态流转、条件分支和暂停恢复，不替代规则判断。AI 可以在故障树限定的原因空间内综合证据、重排原因并输出离散支持等级，但不能改变规则错误类型、创造新原因或引用白名单以外的证据。支持等级不是统计概率。

## 3. 核心目录

```text
backend/
├── experiment_packages/       # 数据化、可审核、可测试的实验交付包
│   ├── dht11_temperature_humidity/
│   └── gpio_led_output/
├── app/
│   ├── diagnosis/             # DiagnosisContext、DiagnosisState、规则与故障树
│   ├── experiment_packages/   # 严格 Schema、跨引用校验、包测试和 Manifest
│   ├── knowledge/             # 结构化案例加载与确定性匹配代码
│   ├── ai/                    # LangGraph 编排、AI Provider、脱敏与输出校验
│   ├── models/                # 业务与 KnowledgeCase 数据模型
│   ├── schemas/
│   └── services/
├── knowledge/                 # 内容与代码分离
│   ├── cases/                 # 五类实验的 YAML 案例
│   ├── templates/             # 案例导入/审核模板
│   └── rules/                 # 显式匹配字段规则
└── migrations/
```

MVP 中不存在 `knowledge/embedding/`、`knowledge/vector_store/` 或 `knowledge/rag/`。它们是有明确需求和验收指标后才增加的扩展层。

## 4. V2 DiagnosisState

一次诊断的运行状态由 `DiagnosisState` 承载，核心字段为：

```text
device_status / experiment_type / logs / sensor_values / experiment_context
error_type / evidence / possible_causes / knowledge_context
historical_failures / hint_level / student_feedback
attempt_count / missing_evidence / next_verification_action
evidence_conflict / need_teacher_help / diagnosis_status
```

状态中还保留 `experiment_record_id`、`experiment_version_id`、`experiment_package_hash`、`state_revision`、工作流 ID、规则版本、故障树版本、输入指纹、节点轨迹和耗时指标，用于版本锁定、幂等执行、审计与恢复。日志和传感器状态进入 Checkpoint 前会被脱敏和限量；完整业务快照仍由现有 `diagnosis_results` 权限边界管理。

## 5. Experiment Package 与证据治理

实验差异不再通过新增 Python 分支实现，而是放进数据化实验包。包是开发和交付格式，PostgreSQL 中经过校验、审核并发布的固定版本才是运行时真相。

```text
metadata.yaml
hardware.yaml
diagnosis/rules.yaml
diagnosis/fault_tree.yaml
knowledge/concepts.yaml
knowledge/cases.yaml
teaching/steps.yaml
teaching/hints.yaml
tests/normal_cases.yaml
tests/fault_cases.yaml
```

导入时服务端执行严格字段校验、硬件/规则/原因/证据跨引用校验、正常与故障样例测试，并重新生成每个文件和整个包的 SHA-256。版本按 `draft → pending → approved → published` 发布，已存在的 `experiment + version` 不能覆盖；发布新版本后，旧版本变为 `superseded`，历史诊断仍可按原版本重放。

`diagnosis_evidence` 将证据分为 `raw_payload` 和 `normalized_value`。规则证据、标准化事件和标准化观测都有独立证据 ID；AI 只能引用本次诊断已经落库的证据 ID。

## 6. V2 诊断流程

```text
context_builder
  → rule_engine
  → fault_tree_analyzer
  → knowledge_context
  → ai_reasoning
  → knowledge_validation
  → ai_explanation
  → escalation_handler
  → feedback_handler（LangGraph interrupt）
      ├─ unresolved → escalation_handler → knowledge_context（继续同一诊断）
      ├─ resolved → persist_result + KnowledgeCaseDraft
      └─ request_teacher_help → teacher_review
```

1. `context_builder` 复用 `DiagnosisContext`，构建脱敏、有限的 V2 状态。
2. `rule_engine` 是异常类型与确定性证据的唯一判定节点。
3. `fault_tree_analyzer` 根据证据排序原因，并计算初始提示等级。
4. `knowledge_context` 在推理前按显式字段匹配已审核案例，提供实验定义、正常条件、标准故障映射和教师确认案例。
5. `ai_reasoning` 只能在故障树候选集中排序，输出 `high/medium/low/unknown`、`used_evidence_ids`、缺失证据、冲突和允许的下一验证动作。
6. `knowledge_validation` 在推理后独立校验实验规范、证据 ID、故障树候选集、规则结果和允许的验证动作；失败时不发布为学生建议并转教师。
7. `ai_explanation` 把通过校验的推理与知识结果转换成学生可理解的结构化建议。
8. `feedback_handler` 暂停工作流等待学生反馈；反馈作为新证据恢复同一 LangGraph thread。
9. `escalation_handler` 根据尝试次数、异常持续时间、提示等级、未知结论和证据冲突，决定继续推理或请求教师介入。

`teacher_review`、`persist_result` 和 `reject_result` 是审核与持久化基础设施节点，不属于 AI 推理能力。

## 7. KnowledgeCase 与内容治理

绑定实验包的新诊断，以 PostgreSQL 中该 `experiment_version`
的不可覆盖快照里 `knowledge/cases.yaml` 为知识真相源；未绑定实验包的旧请求继续使用
`knowledge_cases` 表。两种来源共用同一组核心字段：

- `id`、`experiment_type`、`error_type`、`symptom`；
- `normal_state`、`evidence`、`possible_causes`、`solution_steps`；
- `teacher_notes`、`review_status`、`source_ref`、`version`、`is_test_data`。
- `facts`、`root_cause_status`、`confirmed_by`、`solution_record`；
- `facts_locked`、`quality_check_passed`、`ai_generated_fields`、`source_type`。

YAML 文件是可审阅的交付源文本，PostgreSQL 记录是运行时数据。实验包案例随整包校验、审核和发布，运行时只从当前诊断锁定的包版本重建可信知识引用，不会跨实验或跨版本混用。旧 `backend/knowledge/cases/` 文件仍可通过 `python -m app.cli.sync_knowledge_cases` 幂等同步到全局表，用于兼容未包化流程。无论来源如何，只有同时满足 `approved + confirmed + facts_locked + quality_check_passed` 的案例可进入诊断。

诊断案例沉淀采用 `KnowledgeCaseDraft`，不允许 AI 自动写入正式知识库：

```text
事实数据与规则过程
  → 学生 resolved 反馈
  → 模板生成事实绑定草稿（根因仍为 unknown）
  → 可选 AI 表达字段优化并保存模型/Prompt 审计
  → 事实字段一致性检查
  → 教师确认根因与真实解决动作
  → approved KnowledgeCase
```

AI 优化时不得修改 `experimentType`、`errorType`、`normalState`、`evidence`、`possibleCauses` 或 `solutionSteps`。只有教师/正式审核角色可将草稿发布为正式案例。

## 8. 关键架构决策

| 决策 | MVP 选择 | 理由 |
| --- | --- | --- |
| 后端形态 | FastAPI 模块化单体 | 减少部署与联调复杂度 |
| 工作流 | 单一 LangGraph 状态图 | 流程可控、可恢复、节点可审计 |
| 实验扩展 | 通用引擎 + 版本化 Experiment Package | 新实验以数据包交付，不增加核心 Python 分支 |
| 运行时真相 | PostgreSQL 中的已发布包版本 | 诊断可重放，发布后不可静默修改 |
| 证据 | 原始值与标准化值分层持久化 | AI 引用真实存在的证据 ID，来源可追溯 |
| 数据库 | PostgreSQL | 统一业务与结构化知识治理 |
| 诊断优先级 | 规则 → 故障树 → 知识 → AI | 判定确定、证据可追溯、AI 可降级 |
| 知识匹配 | 精确字段 + 证据加分 | 小规模知识下更稳定、可解释 |
| RAG / Embedding | MVP 不引入 | 当前不是大规模搜索问题 |
| AI 推理 | 候选集内排序 + 证据白名单 | 允许综合推理，但不扩大故障空间 |
| AI 解释 | 可替换 `AIClient` 的受约束表达层 | 生成结构化教学建议，不接管规则判定 |
| Agent | 不引入多智能体或自主规划 | 避免不可控执行与额外状态复杂度 |
| API | `/api/v1` | 保持设备协议和前端兼容性 |

## 9. 安全、审计与兼容

- 设备令牌和用户密码哈希保存；Provider 密钥只从服务端环境变量读取。
- AI 前的 allowlist 会匿名化设备、聚合读数、截取相关日志并删除身份、令牌和密钥。
- AI 输出不能修改错误类型、规则证据或故障树分数。
- AI 推理与解释按首次运行及反馈轮次分别审计，`call_stage` 包含反馈 ID，保留每轮输入输出。
- 学生确认产生的案例先进入 `knowledge_case_drafts`；未经过教师审核不会被诊断主链匹配。
- V1 数据表和对外 API 保留；新运行记录使用 `graph_version=langgraph-v2`，历史记录仍可审计。
- 未绑定 Experiment Package 的旧调用继续走原 Experiment Definition 兼容路径；新任务可在 `experiment_assignments.experiment_version_id` 锁定发布版本。
- 已存在数据库中的 `needs_rag`、`embedding_version`、`retrieval_audit` 和部分 `chunk_id` 字段暂保留为升级兼容容器。新流程固定 `needs_rag=false`、`embedding_version=null`，`retrieval_audit.mode=structured_case_match`，它们不表示 MVP 仍在执行 RAG。

## 10. 未来 RAG 扩展

当结构化案例数量、跨文档问答需求或同义表达召回问题超过显式匹配能力时，再增加：

```text
knowledge/
├── embedding/       # 可重建的派生索引
├── vector_store/    # pgvector 或其他存储适配器
└── rag/             # 召回、重排、引用与评测
```

扩展时不改变 `KnowledgeCase`、规则引擎、故障树和 AI 输出契约；向量只是可重建的检索索引，不是诊断事实源。

运行拓扑与部署边界另见 [运行架构](runtime-architecture.md)；AI 输入、输出与校验详见 [V2 AI 诊断设计](ai-diagnosis-design.md)。
