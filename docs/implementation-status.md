# 芯鉴知微实现状态

最后更新：2026-07-25（Phase 9 最终验收）

## 总体状态

- 当前阶段：Phase 9 轻量、确定性优先的通用框架已完成代码实现，版本为 `0.9.0`。
- 当前真实模式：AI/Embedding Provider 均未确认，系统默认执行确定性规则、故障树与模板；数据库中的知识与向量仅为明确测试标记的验收数据。
- Docker：backend/frontend 已重建为 Phase 9 `0.9.0` 且健康；PostgreSQL 容器和数据卷未重建。
- Phase 10 尚未开始。

## Phase 9 实现情况

- [x] 建立统一 `AIClient` 与 `EmbeddingClient` 协议，Provider 和传输配置不写死。
- [x] 提供默认禁用实现和可选 OpenAI-compatible 传输适配器。
- [x] 新增 `DiagnosisEpisode` 聚合重复故障，并用 `DiagnosisCore` 与模板保证 AI 关闭时解释完整。
- [x] 新增结构化过滤、PostgreSQL 全文检索、可选 pgvector 与 RRF 融合；Embedding 未配置时仍可全文检索。
- [x] 新增低置信、多规则、未知异常、用户追问和 Episode 升级等调用策略。
- [x] 新增稳定指纹、PostgreSQL 解释缓存、Episode/设备频率限制、单次与每日预算和 Token 上限。
- [x] 支持缓存、本地 Provider、云端 Provider、确定性模板的降级顺序；没有写死具体厂商。
- [x] 使用严格 Pydantic Schema 校验结构化输出。
- [x] 错误类型必须来自规则，证据必须来自规则白名单，知识引用必须来自本次检索结果。
- [x] Provider 异常、超时、非法 JSON、结构不符或虚构证据时有限重试并降级。
- [x] 扩展 `ai_call_records`，记录触发原因、Episode、缓存、路由、Token、耗时、校验和降级，不保存 API Key。
- [x] 学生端以确定性解释为主，并明确 AI 只是可选增强。
- [x] README 和独立设计文档明确正式知识、Provider、硬件和生产边界。

## 数据库迁移

- 保留迁移 `20260723_0006_phase9_ai_framework.py`，新增兼容迁移 `20260724_0007_phase9_lightweight_diagnosis.py`。
- `ai_call_records` 关联 `diagnosis_results`，保存 Provider/模型、Prompt、耗时、尝试次数、受限输入、结构化输出、知识引用、Token 计数和失败原因。
- 新增 `diagnosis_episodes`、`ai_explanation_cache`，扩展诊断结果、知识块和 AI 审计字段，并为知识全文检索建立 GIN 索引。
- 迁移已由 `0.9.0` 后端启动流程应用到长期 PostgreSQL，现为 `20260724_0007`。

## 验证结果

| 验证项 | 命令/方式 | 当前结果 |
| --- | --- | --- |
| 后端静态检查 | `ruff check .` | 通过 |
| 后端测试 | `pytest` | 59 passed |
| Phase 9 降级 | 未配置 Provider 调用解释接口 | `skipped + rules_only`，审计记录已保存 |
| Phase 9 成功路径 | 注入明确测试 Fake AIClient | Pydantic、证据白名单和审计通过 |
| Phase 9 失败关闭 | Fake AIClient 返回虚构证据 | `failed + rules_only`，规则结果未修改 |
| 前端类型检查 | `npm run type-check` | 通过 |
| 前端单元测试 | `vitest run` | 7 passed |
| 学生/教师端浏览器测试 | `playwright test` | 4 passed |
| 前端生产构建 | `npm run build` | 0.9.0 通过；仅有 ECharts 517 kB 分块提示 |
| 模拟器回归 | Ruff、`pytest` | 8 passed |
| PostgreSQL 迁移 | 后端启动执行 `alembic upgrade head` | `20260724_0007 (head)` |
| ORM/迁移一致性 | `alembic check` | 通过；PostgreSQL 专用 FTS 表达式索引由 0007 显式管理 |
| 测试知识幂等 | 连续两次执行 seed CLI | 始终为 1 来源、4 文档、4 知识块、4 测试向量 |
| 混合检索 | 结构化条件、自然语言、精确错误码 | DHT11 均排首位；FTS、测试向量与 RRF 分数可追踪 |
| Episode 运行验收 | 同设备同实验连续 5 次失败 | 聚合为 1 个 Episode，`failure_count=5`，最终测试解决 |
| 缓存运行验收 | 同指纹连续两次 Mock 增强 | Provider 仅调用 1 次，第二次缓存命中，`hit_count=1` |
| 数据保留 | PostgreSQL 只读计数 | 原 5 台设备、13 条日志、12 条读数、13 条诊断均保留；验收后为 6/18/12/18 |
| Phase 9 验收记录 | PostgreSQL 只读计数 | Episode 1、测试来源/文档/块/向量 1/4/4/4、AI 审计 2、缓存 1 |
| Docker 0.9.0 | `docker compose up -d --build`、健康检查、API 版本 | 三服务 healthy；API 返回 `0.9.0` |
| AI 运行门禁 | `GET /api/v1/diagnosis/ai/status` | Provider/Embedding 均未配置，transport=`disabled` |

## 已知边界与风险

1. **没有真实 AI 调用。** 当前 Provider、模型、Base URL 和密钥为空，默认传输为 `disabled`。
2. **没有正式知识。** 当前 1 个来源、4 个文档、4 个知识块和 4 个 pgvector 记录全部是合成测试数据；默认正式检索会排除。
3. **没有真实设备数据。** 当前数据库业务记录来自阶段验收测试或模拟器。
4. **规则仍是示例。** YAML 阈值、故障树原因和提示不是经真实硬件、说明书或行业资料验证的专业知识。
5. OpenAI-compatible 适配器只是通用传输能力，不代表选定 OpenAI 或任何具体厂商。
6. 真实 Provider 接入前必须确认日志与设备数据外发、脱敏、费用、限流和保留政策。
7. 正式学生、教师、班级、实验任务和角色授权仍未建立。
8. ECharts 公共渲染分块约 517 kB，属于已知非阻塞构建性能提示。

## 下一步门禁

开始真实 AI 联调前必须至少确认：

1. 经授权并审核的知识来源、版本和审核人；
2. Embedding Provider、模型、维度、服务地址和数据政策；
3. AI Provider、模型、服务地址、服务端密钥、费用与限流；
4. 日志/设备数据是否允许外发以及脱敏要求；
5. 用于验收的真实或带真值故障数据和准确率指标。

以上信息未确认时，系统必须保持 AI 本地/云端开关关闭，并使用确定性诊断；不得将 Mock Client、合成知识或测试向量描述为真实 AI 与专业知识能力。Phase 10 尚未开始。
