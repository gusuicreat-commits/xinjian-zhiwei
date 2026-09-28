# 芯鉴知微系统架构

代码核对日期：2026-09-27。本文是当前模块和数据流的地图，不是部署或硬件验收报告。
持续规则以 [开发准则](development-guidelines.md) 为唯一维护位置；能力与未验收事项见
[实现状态](implementation-status.md) 和 [项目真实性看板](project-truth-status.md)。

## 1. 系统组成与边界

系统采用 FastAPI 模块化单体、PostgreSQL、固定 LangGraph 状态图和 Vue 3 前端。
ESP32 固件和模拟器通过 HTTP 协议上传数据，不直接访问数据库或模型服务。
AI 默认关闭；规则、故障树、教学参考和教师处置不以 Provider 可用为前提。
当前没有 RAG、向量检索、自主规划或多智能体诊断。

```text
ESP32 固件 / 模拟器
  → 设备认证与协议校验 → 幂等批次与遥测记录 → PostgreSQL
                                                   ↑
学生账号 → 实验会话 → 显式检查命令 → 冻结输入 → 固定诊断流程
                                                   ↓
                               诊断、问题、证据、指导、调用审计
                                                   ↓
                      学生反馈 / 教师工单 / 诊断审核 / 案例草稿

工作区实验包 → 校验 → 导入草稿 → 审核发布 → 数据库固定版本
                                             ↓
                                     会话与诊断锁定版本
```

设备报告、规则异常、候选根因、学生报告已解决、教师结案和硬件恢复是不同事实。
上述节点之间靠持久化身份关联，不能以设备当前绑定或“最新一条记录”补造历史归属。

## 2. 模块地图

| 模块 | 职责与主要入口 |
| --- | --- |
| `backend/app/api/` | HTTP 认证、角色权限、请求及响应契约；学生身份由 `dependencies.py` 统一解析 |
| `services/device_protocol.py`、`device_ingest.py` | 批次记录归一化、设备事务锁、限流、幂等回执、全批次写入 |
| `services/data_scope.py`、`experiment_sessions.py` | 数据原始归属、有效会话、设备占用与交接 |
| `services/diagnosis_checks.py` | 显式重新检查的请求身份、输入快照、原请求恢复和前后对比 |
| `diagnosis/`、`services/diagnosis.py` | 通用上下文、证据映射、规则与故障树计算 |
| `services/diagnosis_episode.py`、`guidance.py`、`student_feedback.py` | 多问题关联、故障生命周期、指导及反馈；计数按各自语义分开 |
| `ai/diagnosis_graph.py`、`services/diagnosis_workflow.py` | 固定节点编排、业务流水、暂停恢复与审核 |
| `ai/governance.py`、`context_sanitizer.py` | 三个模型入口共用调用治理与外发清洗，各入口保留独立字段白名单 |
| `experiment_packages/`、`services/experiment_packages.py` | 数据包 Schema、交叉引用、样例测试、版本完整性与发布 |
| `knowledge/`、`services/teaching_materials.py` | 受审核案例匹配、事实绑定草稿、只读教学参考 |
| `services/interventions.py` | 工单状态、公开与私密事件、幂等操作及问题解决报告 |
| `frontend/src/` | 按学生/教师任务展示已有授权数据，保存未决请求身份；刷新只读 |
| `firmware/esp32_dht11/`、`simulator/` | 采样与协议发送；模拟数据始终保留测试身份 |

跨模块改动按[规则与执行位置对应表](development-guidelines.md#rule-map)核对全部入口。

## 3. 数据接入与归属

批量入口在同一设备的短事务中重新校验设备与会话、查重、检查额度并写入回执及遥测。
数据库唯一约束防止相同请求身份或序列被重复写入；同身份同载荷重放原结果，内容冲突拒绝。
协议外层和每条记录都要校验，离线固件先保存冻结批次再发送。详细错误码和固件存储边界见
[设备协议](device-protocol.md) 与 [固件目录](../firmware/esp32_dht11/)。

遥测保存可空 `experiment_session_id`，诊断保存创建时会话范围；工作流另有学生、设备和会话外键。
归属不明的历史资料不能从今天的设备绑定推断后展示给学生。设备密钥只代表上传设备；正式学生
操作使用个人 Bearer 会话，设备凭据登录仅兼容明确测试设备。

## 4. 检查、诊断与反馈

学生启动或重新检查先经过 `diagnosis_checks`：同会话请求身份对应同一命令；输入、参数、
数据截止范围和实验版本固定后进入图。相同输入不制造新的诊断轮次。页面刷新、回执查询和
切换视图不运行诊断，也不发起模型调用。

新检查复用相同输入的旧结果时，重新读取问题的处理状态和解决来源，保存为新回执；
旧请求重放仍返回原回执，不改写历史，也不新增诊断或模型调用。

图的前半段固定为：

```text
context_builder → rule_engine → fault_tree_analyzer → knowledge_context
                → ai_reasoning → knowledge_validation
```

后半段有明确分支，不能理解为每次都运行所有节点：

- 知识校验拒绝进入 `teacher_review`；通过才进入 `ai_explanation`。
- 无异常的解释后直接持久化；首次异常解释后进入 `escalation_handler`；反馈后的再次解释回到等待反馈。
- `feedback_handler` 恢复后进入升级判断：未解决可回到知识、推理和解释；有剩余问题继续等待；
  达到教师条件转审核；满足结束条件才持久化。
- 教师 `approve/edit` 进入持久化，`reject` 进入拒绝节点。工单结案不是这条审核边。

“仍未解决”使用原诊断快照；“用最新数据重新检查”走新的显式检查命令，不给旧图静默换输入。
`DiagnosisState` 保存有界流程状态；`state_revision` 是审计修订，不能充当数据库并发锁。
实际状态定义和图边分别见 `diagnosis/workflow_schemas.py` 与 `ai/diagnosis_graph.py`。

反馈在串行锁、生命周期锁、工作流行锁等待后重新校验当前身份；模型或 checkpoint 操作后，
返回回执前再次检查。归属有效的关闭会话只允许重放完成回执或确认已消费反馈，不能继续新操作。

## 5. 问题、知识和 AI 的交接

一次诊断可通过 `diagnosis_issues` 关联多个持久化问题（Episode）。指导、反馈和工单绑定明确问题；
异常证据轮次、采样失败数、排查尝试数、等待教师时间分别记录。相关新证据修订防止旧反馈覆盖新问题。
恢复仍要求相关、时间可信的新证据及完整判据，不能把旧异常离开窗口当成恢复。

运行时实验真相来自数据库固定包快照。会话已固定的版本不会因任务改版自动迁移；旧版 `superseded`
仍可供固定会话使用，`revoked` 阻断教学使用。包内容、证据和教学参考的完整契约见
[实验包设计](experiment-package-design.md)。

包内案例和兼容全局案例都经过批准、根因确认、事实锁定、质量检查及适用范围过滤。
学生解决反馈只生成事实绑定草稿；正式案例审批、草稿更新和来源唯一性由同一事务保护。
AI 润色只处理表达字段，迟到结果不能覆盖审批。全局案例发布不会改写旧实验包。

推理、解释、润色共用持久化预算预留及调用记账；失败调用也记账。模型输入按各入口白名单清洗，
必需引用和敏感值冲突时放弃增强。模型输出验证与自然语言语义判断仍是不同验收项，详见
[AI 工作流设计](ai-diagnosis-design.md)。

## 6. 存储、兼容与验证边界

业务表由 Alembic 管理；LangGraph PostgreSQL saver 单独维护 checkpoint 表。业务提交与
checkpoint 不是一个原子事务，因此检查命令和反馈保留身份、状态及恢复记录。真实并发须在
PostgreSQL 独立连接验证，SQLite 的开发锁结果不能替代。

旧模板、未包化 Experiment Definition、历史 `needs_rag`/`retrieved_chunks` 字段和向量表保留兼容。
结构化匹配节点仍使用 `retrieving` 这个状态名；它不代表当前执行向量检索。
旧字段和历史迁移不是重启 RAG 的授权；扩展需要独立需求、设计和验收。

维护时从 [API 契约](api-design.md)、[数据库设计](database-design.md) 和
[测试与评测](evaluation.md) 定位影响。代码检查、模型语义、硬件测量、课堂试用和部署确认分别记录；
本文不把历史测试数量视为当前通过，也不把本地迁移 Head 视为运行数据库状态。
