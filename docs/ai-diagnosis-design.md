# V2 AI 诊断工作流设计

最后更新：2026-09-04

## 1. V2 结论

V2 将 AI 诊断升级为由 LangGraph 编排的证据驱动流程，同时保留现有确定性诊断、知识治理、AI 降级和教师审核能力。LangGraph 是流程控制器，不是自由规划 Agent；AI 是受规则、故障树候选集和证据白名单约束的诊断助手。

实现基线为《芯鉴知微 V2 最终架构文档：完整对话总结与技术决策》，其中“事实不能由 AI 生成、确定事项由规则优先、AI 推理必须说明证据、允许 unknown、知识发布门槛高于学生回答”作为代码级约束。

当前仍不使用 RAG、Embedding、pgvector 或向量检索。核心问题是把设备真实数据、确定性诊断、学生反馈和教学排查建议连成稳定闭环，而不是从大规模文档中搜索知识。

取消 RAG 的直接原因：

- 首批知识只覆盖 DHT11、LED、按键、光敏传感器和超声波五类实验，规模小且字段稳定。
- 故障类型和证据必须来自规则，原因排序必须来自故障树；相似度不应参与硬件故障判定。
- 引入 Embedding Provider、向量维度、索引和召回评测会扩大部署面和失败面，不提升当前 MVP 的核心可验证性。
- 结构化字段匹配可以给出“为什么匹配”的精确记录，更适合教学场景审核。

## 2. DiagnosisState

`DiagnosisState` 是一次异常诊断的唯一流程状态，核心契约为：

```python
class DiagnosisState(TypedDict, total=False):
    device_status: dict
    experiment_type: str | None
    logs: list[dict]
    sensor_data: list[dict]
    sensor_values: list[dict]
    experiment_context: dict
    experiment_version_id: str | None
    experiment_package_hash: str | None
    error_type: str | None
    evidence: list[dict]
    possible_causes: list[dict]
    knowledge_context: list[dict]
    hint_level: int
    student_feedback: dict | None
    historical_failures: int
    attempt_count: int
    missing_evidence: list[str]
    next_verification_action: str | None
    evidence_conflict: bool
    need_teacher_help: bool
    diagnosis_status: str
```

内部还保存工作流归属、实验包版本、状态修订号、指纹、节点轨迹、耗时、确定性结果和审核状态。V1 字段别名暂时保留，以兼容已有数据库记录和 API。

## 3. LangGraph 诊断主链

```text
context_builder
  → rule_engine
  → fault_tree_analyzer
  → knowledge_context
  → ai_reasoning
  → knowledge_validation
  → ai_explanation
  → escalation_handler
  → feedback_handler（暂停等待学生）
      ├─ unresolved → 提升 hint_level → knowledge_context
      ├─ resolved → persist_result
      └─ request_teacher_help → teacher_review
```

节点职责：

- `context_builder`：复用 `DiagnosisContext` 构建设备、日志、传感器和实验状态。
- `rule_engine`：确定异常类型和证据；AI 无权覆盖。
- `fault_tree_analyzer`：排序可能原因并计算提示等级。
- `knowledge_context`：在 AI 推理前供给已审核的实验定义、正常条件、故障映射和教师确认案例。
- `ai_reasoning`：在已有 `cause_id` 集合中重排原因，输出离散支持等级并绑定证据 ID；越界或失败时回退故障树结果。
- `knowledge_validation`：在 AI 推理后校验实验规范、证据 ID、候选原因、规则结果和允许动作，不调用模型。
- `ai_explanation`：基于推理和知识校验结果生成学生可理解的结构化说明。
- `feedback_handler`：使用 LangGraph interrupt 等待 resolved、unresolved 或 request_teacher_help，并以原工作流 thread 恢复。
- `escalation_handler`：使用失败次数、异常持续时间、当前提示等级和学生反馈决定升级或教师介入。

AI 完全关闭、超时或输出不合法时，状态图仍使用规则、故障树和匹配知识生成确定性结果。`teacher_review`、`persist_result` 和 `reject_result` 是流程基础设施，不是新增智能体。

## 4. 模块职责边界

### 规则引擎

- 从 `DiagnosisContext` 读取状态、日志、读数和实验预期。
- 输出错误类型、规则 ID、观测值与证据引用。
- 它是异常类型的唯一判定者，AI 不得新增或改写。
- 规则来自本次诊断绑定的已发布 Experiment Package；旧调用仍可使用原文件定义兼容路径。

### 故障树

- 只分析与已命中规则相关的候选原因。
- 使用明确证据给原因排序，生成分级提示和教师介入建议。
- 原因是待验证假设，不得表述为已确认的硬件损坏。

### 结构化知识库

- 只返回 `review_status=approved` 的案例。
- 首先精确匹配 `error_type`，再校验 `experiment_type`，最后用显式证据字段加分。
- 输出实验规范、排查步骤、教师经验和来源版本。
- 不做语义召回、相似文本扩展、向量排名或 LLM 重排。

### AI 智能推理

- 输入包括设备事实、规则结果、故障树候选原因、实验上下文和历史失败次数。
- 输出为结构化 `ranked_causes`，每项包含 `cause_id`、`cause`、`support_level`、`used_evidence_ids` 和 `reason`。
- `cause_id` 必须来自故障树；`used_evidence_ids` 必须来自证据注册表；`error_type` 必须与规则结果一致。
- 不允许提出新的故障类型；无法形成可靠排序时输出 `conclusion=unknown`。
- Provider 不可用、输出非法或引用越界时，系统使用故障树确定性排序并记录降级原因。

### AI 解释器

- AI 是受约束的“表达层”，不是硬件故障判定器。
- 只能选择规则已有的 `error_type` 和证据。
- 只能引用本次已匹配案例的 `case_id`。
- 只能解释已经约束的原因排序、知识案例和排查步骤，不能再次自由生成原因。
- 不进行工具规划、节点选择或自主循环；状态分支完全由后端函数决定。

## 5. AI 输入与输出

推理输入是知识校验前的设备证据、规则结果、故障树候选集和实验上下文；解释输入再加入结构化知识校验结果。学生身份、设备令牌、密码、Authorization、Wi-Fi 密码、API Key 和教师私密备注不进入 Prompt。

推理阶段的核心输出为：

```json
{
  "error_type": "SENSOR_READ_FAILED",
  "conclusion": "ranked",
  "ranked_causes": [
    {
      "cause_id": "gpio_config",
      "cause": "GPIO 配置错误",
      "support_level": "high",
      "used_evidence_ids": ["8f6...证据UUID", "b31...证据UUID"],
      "reason": "设备在线但读取持续失败，现有证据更符合配置问题。"
    }
  ],
  "summary": "...",
  "limitations": [],
  "missing_evidence": ["尚未核对实际 DATA 接线"],
  "next_verification_action": "核对代码中的 GPIO 与实际 DATA 接线是否一致。",
  "conflict": false
}
```

对外的核心结构为：

```json
{
  "errorType": "SENSOR_READ_FAILED",
  "evidence": ["log_event_count: 3"],
  "possibleCauses": ["..."],
  "steps": ["..."],
  "hintLevel": 2,
  "needTeacherHelp": false
}
```

当前 Python API 内部使用 snake_case，并可附带 `summary` 和 `limitations`；这两个字段不改变上述核心契约。

后端使用错误类型白名单、候选原因 ID 白名单、已落库证据 ID 白名单和案例 ID 白名单验证输出。最终 `hint_level` 与 `need_teacher_help` 由 `escalation_handler` 的确定性结果覆盖生成内容，因此 AI 不能改变规则结论或升级决策。

## 6. 实验包约束

AI 不读取任意目录或执行实验包代码。实验包只允许 YAML/JSON 数据和系统固定的规则 DSL。进入诊断前，服务端必须完成：

1. 严格 Schema 校验，未知字段直接拒绝；
2. 硬件、规则、故障树原因、证据类型和案例之间的跨引用校验；
3. 包内正常/故障样例测试；
4. SHA-256 完整性校验；
5. 管理员审核发布。

每次诊断固定保存 `experiment_id + experiment_version_id + package_hash`。AI 看到的是这一固定版本产生的设备事实、规则结果、候选原因和知识上下文，不能跨实验或跨版本拼接结论。

## 7. 知识案例模型

```json
{
  "id": "dht11.sensor-read-failed.v1",
  "experimentType": "dht11_temperature_humidity",
  "errorType": "SENSOR_READ_FAILED",
  "symptom": "...",
  "normalState": {},
  "evidence": [],
  "possibleCauses": [],
  "solutionSteps": [],
  "teacherNotes": "...",
  "reviewStatus": "pending",
  "sourceRef": "knowledge/cases/dht11.yaml",
  "version": "1"
}
```

产品层简写 `experiment / causes / steps` 分别映射到数据库字段 `experiment_type / possible_causes / solution_steps`，不另建第二套知识模型。

新实验的案例放在各自实验包的 `knowledge/cases.yaml`。整包发布后，诊断按锁定的 `experiment_version_id` 从 PostgreSQL 包快照取得案例，推理后再从该可信快照重新装载并校验 ID。旧 `backend/knowledge/cases/` 和 `knowledge_cases` 表继续服务未包化的兼容请求。诊断代码不包含实验经验常量；两类案例都必须通过四重审核门槛才能匹配。

## 8. AI 辅助案例沉淀

案例不是由 AI 自动生成并直接发布。当前闭环为：

1. 保存设备事实、规则结果、故障树过程和诊断版本；
2. 学生提交 `resolved`，系统生成 `KnowledgeCaseDraft`，但 `root_cause.status` 保持 `unknown`；
3. 模板把实验、错误类型、证据、候选原因和步骤绑定到事实快照；
4. AI 只能生成 `title/symptomDescription/teachingNote/solutionSummary`，且每项保留 `sourceIds`；
5. 质量检查失败的草稿停留在 `draft`；
6. 通过检查的草稿进入 `pending_review`；
7. 教师必须确认故障树内的根因和真实解决动作，批准后才生成 `approved + confirmed + facts_locked + quality_check_passed` 的 `KnowledgeCase`。

该流程保证 AI 只能整理表达，不能创造未经学生确认、规则记录或教师审核的事实。

## 9. 失败、反馈与审计

- 没有案例匹配时仍返回规则与故障树结果。
- AI 未配置、超时、限流、预算不足或结构校验失败时，降级为确定性说明。
- `ai_call_records` 保存触发原因、模型、Prompt/Schema 版本、耗时、Token、案例 ID、校验结果和降级原因，不保存密钥或完整敏感输入。
- 旧审计表中的 `chunk_id`/`knowledge_references` 字段暂作升级兼容容器；MVP 新记录中其值是结构化 `case_id`，不表示 RAG Chunk。
- LangGraph Checkpoint 保存可恢复状态，`diagnosis_workflow_runs` 保存可查询的业务审计；两者不替代原始设备数据和诊断结果表。
- 学生反馈继续写入现有 `diagnosis_feedback`，同时恢复 `waiting_feedback` 的 LangGraph checkpoint；未解决会继续同一诊断而不是重建自由 Agent。
- `ai_call_records.call_stage` 区分首次和各反馈轮次的 `reasoning/explanation`，分别保存 Prompt 版本、输入快照、结构化输出、校验状态和降级原因。

## 10. 保持工程简洁

- 单一状态图，不引入多智能体。
- 节点顺序由代码声明，不允许模型自主规划。
- AI Provider 使用现有轻量客户端，不叠加复杂 LangChain Agent 封装。
- 第一阶段没有 RAG 分支、Embedding 调用或向量数据库依赖。

## 11. 未来 RAG 扩展路线

RAG 只在知识规模、查询类型和召回评测证明有必要时增加：

1. 保持 `KnowledgeCase` 与审核状态为业务真相源。
2. 新增 `knowledge/embedding/` 作为案例到向量的派生索引层。
3. 新增 `knowledge/vector_store/` 作为 pgvector 或其他存储适配层。
4. 新增 `knowledge/rag/` 作为召回、重排、引用和评测层。
5. 在独立特性开关下将 RAG 作为“追加参考”，不修改规则证据或故障树排序。
6. 通过真实标注集验证 Recall@K、错误引用率、时延、成本和教师采纳率后才能进入默认主链。

这三个未来目录当前不创建，避免空实现被误认为可用能力。
