# Phase 9.6：Phase 9.5 独立审计记录

审计日期：2026-07-26

审计范围：Phase 9 提交 `12aa663` 至 Phase 9.5 现有提交 `cf24597`

审计结论：通过，允许形成 Phase 9.5 封存提交；不得进入 P1。

## 1. 基线差异

总路线参考基线假设 Phase 9.5 尚未提交。实际开始审计时：

- 工作区已经干净；
- Phase 9.5 已由外部状态提交为 `cf24597 9.5`；
- 该提交的作者与提交者为项目现有 Git 身份；
- 本轮不修改、不删除、不 amend 该历史提交；
- 相对 `12aa663`，实际仍是33个修改文件、5个新增文件和0个删除文件，与路线记录一致。

Phase 9.6 使用实际仓库状态作为权威证据，并通过本审计记录和必要测试补强形成独立封存提交。

## 2. 范围审计

检查 `git diff 12aa663..cf24597` 的全部文件后确认：

- DeepSeek 固定值只进入配置、OpenAI-compatible 客户端、状态 Schema、测试夹具和说明文档；诊断业务服务没有复制平行的 DeepSeek 业务逻辑。
- 默认生产路由为 `cache → deepseek → deterministic_fallback`。
- Disabled、Mock、本地扩展、缓存、Episode/设备次数、预算、Token、Pydantic 和确定性降级仍然保留。
- 没有加入 P1 的协议 V1、批量上传、`request_id`、`boot_id` 或 `sequence_no`。
- 没有真实 PlatformIO/ESP32 固件、GPIO、电压、接线或课程参数。
- 本文记录的是 2026-07 的 Phase 9.6 历史审计；当时没有 LangChain/LangGraph。该限制已
  被 2026-08-13 的新工程设计替代：现在只在 FastAPI 单体内加入受控 LangGraph/
  LangChain，仍没有 Redis、消息队列、新向量数据库或新微服务。

## 3. AI 配置与路由

| 检查项 | 证据 | 结论 |
| --- | --- | --- |
| 默认开关 | `.env.example`、`compose.yaml`、`Settings.ai_enabled` | `false` |
| Provider | `Settings.ai_provider` | `deepseek` |
| Base URL | `Settings.ai_base_url` | `https://api.deepseek.com` |
| 模型 | `Settings.ai_model` | `deepseek-v4-flash` |
| 思考模式 | `OpenAICompatibleClient.build_request_payload` | `thinking.type=disabled` |
| 无 Key | `Settings.production_ai_configured`、运行状态 API | Disabled，健康检查成功 |
| 缓存命中 | Phase 9.5 专项测试 | Provider 调用次数不增加 |
| 成功路径 | `route_path` 专项断言 | `cache_miss → deepseek_success` |
| 超时路径 | Mock 超时专项断言 | 安全审计并确定性降级 |
| 非法 JSON | Phase 9.6 补强断言 | `AI_RESPONSE_INVALID_JSON`，确定性降级 |

没有配置、读取或调用真实 DeepSeek API Key，没有发起收费请求。

## 4. 隐私审计

`phase9.5-allowlist-v1` 在构造模型输入前执行：

- 稳定匿名设备短标识；
- 只选择当前故障相关的3–10条日志；
- 读数和心跳聚合；
- 知识正文限长并删除来源内部 URI；
- 实验、规则、证据、故障树和自由文本字段递归清洗；
- 审计只保存哈希、数量、规则/错误码/知识块 ID 和隐私控制摘要。

专项测试确认最终安全输入和审计均不包含学生姓名、学号、班级、设备令牌、Authorization、API Key、数据库密码、Wi-Fi 密码、邮箱、教师私人备注和无关完整日志。

## 5. 知识治理审计

> 本文最初记录的三角色流程已由 `20260730_0015` 收敛，以下为当前有效设计。

- 状态：`draft`、`pending`、`approved`、`rejected`、`withdrawn`、`superseded`。
- 角色：`organizer`、`formal_approver`。
- 禁止整理人正式批准自己提交的资料。
- 正式来源要求治理类型、URI、版本、整理人和适用硬件。
- 官方资料要求页码、章节或段落定位。
- 已验证案例要求最终修复动作和根因置信等级。
- AI 生成内容从 `draft` 开始，不能自动批准。
- 正式 RAG 同时过滤文档和知识块为 `approved`，并默认排除测试来源、文档和向量。

长期 PostgreSQL 当前只有1个测试来源、4个测试文档、4个测试知识块和4个测试向量；正式知识计数为0。

## 6. 数据库与数据保留

- Alembic current：`20260725_0008 (head)`。
- Alembic heads：唯一 `20260725_0008 (head)`。
- Alembic check：`No new upgrade operations detected`。
- 0008 新增 `ai_call_records.route_path` 和非空 `knowledge_reviews.reviewer_role`。
- PostgreSQL 原容器和数据卷未删除或重建。

审计时只读计数：

| 表/数据 | 数量 |
| --- | ---: |
| devices | 6 |
| device_heartbeats | 12 |
| device_logs | 18 |
| sensor_readings | 12 |
| diagnosis_results | 18 |
| guidance_history | 17 |
| diagnosis_feedback | 2 |
| knowledge_sources/documents/chunks/embeddings | 1/4/4/4 |
| diagnosis_episodes/ai_call_records/ai_explanation_cache | 1/2/1 |

与 Phase 9.5 验收前记录一致，原数据未减少。

## 7. 验证结果

| 验证 | 结果 |
| --- | --- |
| 后端 Ruff | 通过 |
| 后端 pytest | 63 passed |
| 前端 ESLint | 通过 |
| 前端类型检查 | 通过 |
| 前端 Vitest | 7 passed |
| 前端生产构建 | 通过；保留 ECharts 517 kB 非阻塞提示 |
| Playwright | 4 passed |
| 模拟器 Ruff | 通过 |
| 模拟器 pytest | 8 passed |
| Docker Compose | postgres/backend/frontend 全部 healthy |
| API health | `status=ok`、`version=0.9.5` |
| AI status | Provider 已选但 configured/enabled 均为 false |

## 8. 敏感与禁止事项

- 精确扫描只命中 `.env.example` 的 `POSTGRES_PASSWORD=TODO_CHANGE_ME_FOR_LOCAL_DEVELOPMENT` 开发占位值。
- 宽泛扫描命中的是 Schema 字段、脱敏正则、测试占位符和正常 Authorization 客户端构造，不是真实秘密。
- `.env` 未被 Git 跟踪。
- `frontend/dist`、Playwright 报告、测试结果、数据库文件和知识原件未被 Git 跟踪。
- 没有真实 AI 调用，没有真实硬件开发，没有 push。

## 9. 已知限制

- 没有真实设备数据、正式知识、真实故障真值或真实硬件诊断能力。
- ESP32/传感器型号、GPIO、电压、接线、采样、正常范围和安全限制仍待项目方提供。
- DeepSeek Key、正式预算、数据外发审批和保留政策仍待项目方提供。
- 正式身份、班级、课程、审核责任人、实验室网络和部署机器仍未建立。
- 前端仍有 ECharts 517 kB 分块提示；依赖安全升级属于后续阶段，不在 Phase 9.6 扩大范围。

## 10. 停止点

Phase 9.6 只审计、补强并封存 Phase 9.5。审计通过后停止，不开始 P1；后续必须等待用户明确输入“继续 P1”。
