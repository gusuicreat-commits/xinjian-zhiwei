# LangGraph + LangChain AI 辅助诊断工作流

## 定位与兼容性

本实现将 LangGraph 作为 FastAPI 模块化单体内部的控制平面，LangChain 作为受控
Runnable 与强类型工具层。它不建第二个 AI 服务、不建第二个向量库，也不替换
已有确定性诊断主链。旧端点 `/diagnosis/devices/*/run` 和
`/diagnosis/results/*/ai-explanation` 保持兼容；学生只在明确点击时启动新工作流。

硬边界仍是：

- YAML 规则确定错误类型，故障树确定原因排序、证据分和 Level 1–4。
- LLM 只能生成自然语言解释，不得修改规则证据、证据分和 Level。
- AI 仍经过已有 `AIClient`、隐私白名单、指纹缓存、预算、重试和 Pydantic 校验；
  任一门禁失败都返回确定性结果。
- RAG 只查询已有 PostgreSQL FTS + pgvector + RRF，正式数据只允许
  `approved` 且非测试知识。

## 状态图

```text
START
  → collect_context            # 只存 ID 引用和统计摘要
  → run_rules                 # 复用 DiagnosisContext + YAML rules
  → run_fault_tree            # 复用 guidance/core/deterministic explanation
  → assess_evidence
      ├→ retrieve_knowledge → explain_for_student   # 证据不足时查 approved RAG
      └→ explain_for_student                         # 证据充分时直接解释
                         # 确定性优先；仅在策略放行时由 LangChain 包装受治理 AI 服务
  → approval_gate
      ├→ persist_result      # 证据充足且无强制审核
      └→ teacher_review      # LangGraph interrupt
             ├→ approve/edit → persist_result
             └→ reject       → reject_result
  → END
```

Level 4、证据分低于 `DIAGNOSIS_TEACHER_REVIEW_SCORE`、需要 RAG 但没有可用知识，
或 AI 结果与规则错误类型冲突时进入教师中断。教师 `edit` 只能修订总结、
候选原因文案、步骤和限制，服务端仍从 `diagnosis_results` 恢复并固定规则事实。

## State、业务记录与 checkpoint

- `DiagnosisState` 不保存数据库 Session、认证头、API Key 或完整原始日志。
- `diagnosis_workflow_runs.id` 就是全局唯一的 `diagnosis_id`；`thread_id` 只放在
  LangGraph runtime config，且数据库强制其精确为 `diagnosis:<diagnosis_id>`。
- `experiment_sessions` 固化 `student_user_id / experiment_assignment_id / device_id`
  三元归属；每个 workflow 必须保存同一份 student/session/device 快照。
- 任何 checkpoint 读取、可观测性恢复、教师 interrupt resume 之前，服务端都会将
  workflow 快照与 `experiment_sessions` 重新比对；Graph 每个节点还会校验
  checkpoint State 中的三元组和当前认证设备，任一不一致即失败闭合。
- `diagnosis_workflow_runs` 保存业务状态、图/规则/故障树/模型版本、节点路径和最终投影。
- `diagnosis_workflow_reviews` 保存审核人、`approve/edit/reject`、备注和修订；同一流程至多
  一个正式审核，终结节点重放由数据库唯一约束保证幂等。
- LangGraph saver 自管 `checkpoints`、`checkpoint_blobs`、`checkpoint_writes` 等运行表；
  Alembic 只管业务表，二者不混用。
- checkpoint 中的学生问题与审核内容先脱敏；业务表保留受 RBAC 保护的原始审核审计。
- 终结节点在同一数据库事务内写最终状态与审核，恢复失败不产生虚假审核；节点重放不
  产生重复业务记录。
- AI 审计以唯一 `workflow_run_id` 关联工作流；checkpoint 重放复用原调用记录，不重复
  Provider 调用、预算扣减、成本统计或 Episode AI 次数。

本地测试和单进程开发可使用 `memory`。`APP_ENV=production` 会强制
`DIAGNOSIS_CHECKPOINT_BACKEND=postgres`，避免将不可恢复的内存状态误用于生产。
当前后端与 SQLAlchemy 服务是同步调用，因此首版使用同步 `graph.invoke` 与
`PostgresSaver`，不把同一 Session 跨线程或后台传递。

## API 与权限

| 接口 | 认证 | 用途 |
| --- | --- | --- |
| `POST /api/v1/diagnosis-workflows/devices/{device_id}` | 设备凭据 + `X-Experiment-Session-ID` | 在唯一学生实验会话中创建并执行 |
| `GET /api/v1/diagnosis-workflows/devices/{device_id}/latest` | 设备凭据 + 会话头 | 只读取该 student/session/device 的最新状态 |
| `GET /api/v1/diagnosis-workflows/{diagnosis_id}` | 设备凭据 + 会话头 | 三元归属一致时才返回 |
| `GET /api/v1/diagnosis-workflows/review-queue/pending` | Bearer + `intervention.manage` | 教师只看授课班级，管理员看全部 |
| `GET /api/v1/diagnosis-workflows/review-queue/recent` | 同上 | 最近 50 条已审核流程和审核历史 |
| `GET /api/v1/diagnosis-workflows/metrics/summary` | 同上 | 流程/RAG/恢复/节点耗时/AI Token 与成本/学生解决率 |
| `POST /api/v1/diagnosis-workflows/{workflow_id}/review` | 同上 | 恢复 interrupt 并批准、修订或驳回 |

并发审核通过 PostgreSQL 行锁串行化，重复审核已终结的工作流返回 409；跨学生、跨实验会话、跨设备或跨班级
访问返回 403/404；图功能关闭时
启动或审核返回 503，原确定性诊断 API 不受影响。

## 证据与可观测性

- 结果和审核 payload 同时保留规则 ID、`log:*` / `reading:*` 引用、故障树候选、
  approved 知识来源/chunk/版本/分数、限制和审核历史；知识正文不会由 API 回传。
- 每个节点记录有界 `node/duration_ms/status`，失败只保存异常类型，不保存 Provider 原始
  错误或敏感输入；RAG 审计保存 query、top-k、分数和最终采用的 chunk 引用。
- 教师指标按权限范围聚合状态、RAG 次数、恢复次数、节点平均耗时、AI 调用/Token/估算
  成本、修订率、驳回率和学生最新反馈解决率。正式“正确诊断率”仍须真实标注真值，
  不由系统用合成数据伪造。

## 部署

1. 通过 Alembic 升级业务表：`cd backend && alembic upgrade head`。
2. 配置不含 SQLAlchemy driver 前缀的 Psycopg DSN，例如
   `postgresql://user:password@postgres:5432/xinjian_zhiwei`。
3. 在单一部署/迁移步骤运行
   `python -m app.cli.setup_diagnosis_checkpoints`。该命令是幂等的，应优先于多 worker 启动。
4. 正常运行保持 `DIAGNOSIS_CHECKPOINT_SETUP=false` 和
   `LANGGRAPH_STRICT_MSGPACK=true`。

开发环境如需启动时自动 setup，可临时设置
`DIAGNOSIS_CHECKPOINT_SETUP=true`；多实例生产不应将它作为每进程常规行为。

## 验收边界

自动测试覆盖：30 个 golden case 与旧规则逐字段等价、checkpoint 不含原日志/令牌、
三类审核、修订不覆盖证据分和 Level、设备/教师权限、顺序/并发审核保护、终结节点重放
幂等、只读工具白名单、prompt injection/非法结构关闭和生产 checkpoint 配置门禁。
合成 RAG 有 54 条标注查询和 6 条多相关查询，生产同源检索在默认 10/10/5 候选限额下
得到 Top-1 87.04%、Top-3 90.74%、Recall@5 93.83%、MRR@5 89.72%、Hit Rate@5
94.44%，有 4 条可审计 miss；100 条合成
结构化输出通过率 100%，但这两者都不代表真实 Embedding 或真实模型质量。本机 Compose
PostgreSQL 已完成官方 saver 建表、重复 setup 和关闭旧连接后新连接恢复验证，集成测试
记录已删除；生产同源 PostgreSQL FTS + pgvector + RRF 也已在一次性空库完成 54 条查询
验收，指标与 SQLite 基线一致，测试库随后删除。生产多 worker、真实进程强杀恢复时延和
并发负载仍必须在试运行环境验收。
业务事务与官方 saver checkpoint 无法组成一个跨组件原子事务，代码通过终结节点幂等和
有界协调重放收敛；Provider 若恰在返回后、审计落库前发生进程级崩溃，仍需依赖供应商
幂等键或生产对账才能给出严格的外部调用 exactly-once 保证。AI 审计与后续
`DiagnosisResult.ai_enhancement` / Episode 计数属于两次提交：若恰在两次提交间崩溃，审计与
成本不会重复，但这两个派生投影可能暂时落后，应由生产对账任务按 `workflow_run_id` 修复。
