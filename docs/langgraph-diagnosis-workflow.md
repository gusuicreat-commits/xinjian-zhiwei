# LangGraph V2 智能诊断工作流

最后更新：2026-09-02

## 定位

LangGraph 是 FastAPI 模块化单体内部的状态编排层，只负责节点顺序、状态流转、条件分支、Checkpoint 和教师审核的暂停恢复。它不替代规则引擎，不让模型自主规划，也不引入多智能体。

现有 `/diagnosis/devices/*/run`、`/diagnosis/results/*/ai-explanation`、学生反馈、教师审核和确定性降级能力继续保留。V2 新工作流记录使用 `graph_version=langgraph-v2`。

## 状态图

```text
START
  → context_builder
  → rule_engine
  → fault_tree_analyzer
  → ai_reasoning
  → knowledge_service
  → ai_explanation
  → escalation_handler
  → feedback_handler（interrupt）
      ├→ unresolved → escalation_handler → ai_reasoning
      ├→ resolved → persist_result
      └→ request_teacher_help → teacher_review
             ├→ approve/edit → persist_result
             └→ reject       → reject_result
  → END
```

八个 V2 核心节点分别负责构建状态、规则判定、故障树候选生成、受约束 AI 原因排序、结构化知识校验、教学语言解释、反馈接收和升级决策。`teacher_review`、`persist_result`、`reject_result` 是审核与持久化基础设施节点。

## DiagnosisState

核心状态包含：

```text
device_status / experiment_type / logs / sensor_values / experiment_context
error_type / evidence / possible_causes / knowledge_context
historical_failures / hint_level / student_feedback
attempt_count / missing_evidence / next_verification_action
evidence_conflict / need_teacher_help / diagnosis_status
```

状态还保存不可变的 workflow/student/session/device 归属、诊断结果 ID、规则与故障树版本、输入指纹、节点轨迹、耗时和错误摘要。日志、反馈备注和知识内容进入 Checkpoint 前均经过脱敏和长度限制。

## 决策边界

- `rule_engine` 是 `error_type` 与确定性证据的唯一来源。
- `fault_tree_analyzer` 使用显式证据排序候选原因。
- `ai_reasoning` 只能使用故障树已有 `cause_id`，引用证据 ID 并输出离散支持等级；越界即回退。
- `knowledge_service` 只匹配已批准、根因已确认、事实锁定且质量检查通过的结构化 `KnowledgeCase`。
- `ai_explanation` 解释受约束推理结果，不能改变规则事实、证据或故障树原因空间。
- `feedback_handler` 暂停并等待学生反馈，恢复后把反馈作为新证据继续同一诊断。
- `escalation_handler` 根据失败次数、异常持续时间、提示等级、证据分和学生反馈决定是否请求教师介入。
- 教师可修订解释文字和步骤，不能修改底层规则事实。

## 状态、业务记录与 Checkpoint

- LangGraph Checkpoint 保存可恢复的运行状态。
- `diagnosis_workflow_runs` 保存可查询的业务状态、版本、节点轨迹、匹配审计和最终结果。
- `diagnosis_workflow_reviews` 保存教师审核，数据库唯一约束保证终结节点重放幂等。
- 每次读取或恢复前重新验证 workflow、学生、实验会话和设备归属。
- AI 调用审计通过 `workflow_run_id` 关联工作流，重放不会重复调用已经完成的 AI 请求。
- 推理和解释使用独立 `call_stage`，首次和各反馈轮次分别幂等审计。
- AI、Checkpoint 或 Provider 失败时，规则与故障树的确定性结果仍可用。

## 知识与未来扩展

第一阶段不执行 RAG、Embedding、向量搜索或 LLM 重排。知识内容位于 `backend/knowledge/`，运行时按实验类型、错误类型和证据字段显式匹配。

未来只有在知识规模与评测证明有必要时，才在 `knowledge/embedding/`、`knowledge/vector_store/`、`knowledge/rag/` 增加可选检索层；该层不得改变规则证据、故障树排序和状态图的确定性升级边界。
