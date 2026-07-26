# 芯鉴知微实现状态

最后更新：2026-07-25（Phase 9.5 实现与运行验收）

## 总体状态

- 当前阶段：Phase 9.5 DeepSeek 生产路由、隐私最小化和知识治理收口已完成代码实现，版本为 `0.9.5`。
- 当前真实模式：DeepSeek 官方 API、`deepseek-v4-flash` 和非思考模式已选定；但 `AI_ENABLED=false`、没有真实 API Key、没有数据外发审批，也没有正式知识，因此系统仍执行确定性规则、故障树与模板。
- Embedding：Provider、模型和维度仍未确定；正式 RAG 只允许 `approved` 且非测试知识，当前数据库只有明确测试标记的 Phase 9 合成资料和测试向量。
- Docker：backend/frontend 已重建为 `0.9.5` 且健康；PostgreSQL 原容器与数据卷保留，只由后端启动流程应用增量迁移。
- Phase 10 尚未开始；没有新增真实 ESP32 固件或硬件型号配置。

## Phase 9.5 实现情况

- [x] 固定生产 Provider 为 DeepSeek 官方 API、Base URL 为 `https://api.deepseek.com`、模型为 `deepseek-v4-flash`，显式发送 `thinking.type=disabled`。
- [x] 保留统一 `AIClient`、Disabled/Mock、严格 Pydantic、缓存、预算、Token、有限重试和确定性降级。
- [x] 默认生产路径收敛为 `cache → deepseek → deterministic_fallback`；没有实现多模型分层。
- [x] 状态接口即使 AI 关闭也能显示已选 Provider、模型、非思考模式和生产路由，但不返回 Base URL 或密钥。
- [x] 新增 `phase9.5-allowlist-v1`：匿名设备标识、3–10 条相关日志、读数/心跳摘要、知识正文限长和自由文本脱敏。
- [x] 明确删除令牌、Authorization、API Key、密码、Wi-Fi、学生身份、联系方式、教师私人备注、来源内部 URI和无关日志。
- [x] 审计只保存输入哈希、数量、规则/知识标识、路由、Token/费用占位和安全错误分类，不保存原始 Prompt、密钥或 Provider 原始错误体。
- [x] `ai_call_records.route_path` 记录缓存命中、DeepSeek 成功、失败降级或跳过链路。
- [x] 知识状态扩展为 `draft`、`pending`、`technical_reviewed`、`approved`、`rejected`、`withdrawn`、`superseded`。
- [x] 整理人、技术审核人、正式批准人职责分离；禁止整理人自审及技术审核人与正式批准人为同一人。
- [x] 正式来源要求治理类型、URI、版本、整理人和适用硬件；官方资料要求页码/章节定位，已验证案例要求最终修复动作和根因置信度。
- [x] AI 生成知识只能从草稿开始；正式 RAG 仍只检索 `approved` 且非测试知识。
- [x] README 与独立文档补齐硬件/网络/后端边界、局域网与公网场景、隐私、费用、知识优先级、部署、持久化和备份恢复。

## 数据库迁移

- 保留原迁移链至 `20260724_0007_phase9_lightweight_diagnosis.py`。
- 新增 `20260725_0008_phase95_runtime_governance.py`，只增加：
  - `ai_call_records.route_path`，并为历史记录回填可读路由；
  - `knowledge_reviews.reviewer_role`，并将历史审核回填为 `legacy_unspecified`。
- 迁移已由 `0.9.5` 后端启动流程应用到长期 PostgreSQL。
- `alembic current` 与 `alembic heads` 均为唯一 `20260725_0008 (head)`。
- `alembic check` 返回 `No new upgrade operations detected`；pgvector 列保留已知的类型识别警告，不产生迁移差异。

## 验证结果

| 验证项 | 命令/方式 | 当前结果 |
| --- | --- | --- |
| 后端静态检查 | `backend/.venv/bin/ruff check .` | 通过 |
| 后端测试 | `backend/.venv/bin/pytest -q` | 63 passed |
| Phase 9.5 配置 | 专项测试 | DeepSeek 默认配置、非思考载荷、旧新环境变量别名通过 |
| 隐私最小化 | 专项测试 | 身份/令牌/密码/URI 删除，相关日志限量，读数聚合，安全审计通过 |
| 单一路由 | 专项测试 | DeepSeek 成功、缓存命中与超时确定性降级通过；Mock 仅被调用 1 次 |
| 知识治理 | 专项测试 | 三角色流转、直接批准拒绝、七状态 RAG 门禁、案例元数据通过 |
| 前端 ESLint | `npm run lint` | 通过 |
| 前端类型检查 | `npm run type-check` | 通过 |
| 前端单元测试 | `npm run test -- --run` | 7 passed |
| 学生/教师端浏览器测试 | `npm run test:e2e` | 4 passed |
| 前端生产构建 | `npm run build` | `0.9.5` 通过；仅有原 ECharts 517 kB 分块提示 |
| 模拟器静态检查 | `simulator/.venv/bin/ruff check .` | 通过 |
| 模拟器测试 | `simulator/.venv/bin/pytest -q` | 8 passed |
| PostgreSQL 迁移 | `alembic current/heads/check` | 唯一 `20260725_0008 (head)`；无待生成操作 |
| 数据保留 | PostgreSQL 只读计数 | 设备/日志/读数/诊断仍为 6/18/12/18 |
| 测试知识保留 | PostgreSQL 只读计数 | 来源/文档/块/向量仍为 1/4/4/4 |
| Phase 9 运行记录保留 | PostgreSQL 只读计数 | Episode/AI 审计/缓存仍为 1/2/1 |
| Docker 0.9.5 | `docker compose up -d --build`、健康检查 | 三服务 healthy；API 返回 `0.9.5` |
| AI 运行门禁 | `GET /api/v1/diagnosis/ai/status` | DeepSeek 已选；enabled/configured=false；非思考；生产路由正确 |

本阶段没有配置真实 API Key，没有发起 DeepSeek 或其他收费调用。成功/超时测试均使用进程内 `MockDeepSeek`，测试字符串不是生产凭据。

## 当前数据库的真实边界

重建后只读计数如下：

| 数据 | 记录数 | 真实性 |
| --- | ---: | --- |
| 设备 | 6 | 阶段验收/测试设备 |
| 心跳 | 12 | 模拟器或测试 |
| 日志 | 18 | 模拟器或测试 |
| 传感器读数 | 12 | 模拟器或测试 |
| 诊断 | 18 | 基于上述测试数据 |
| 提示历史 | 17 | 测试诊断派生 |
| 反馈 | 2 | 前端/API 验收 |
| 知识来源/文档/块/向量 | 1/4/4/4 | Phase 9 合成验收数据 |
| Episode/AI 审计/缓存 | 1/2/1 | Phase 9 Mock 验收记录 |

**没有真实设备数据，没有正式知识，没有真实 AI 调用记录。** Phase 9.5 迁移只增加治理与审计列，没有导入业务数据。

## 已知边界与风险

1. DeepSeek 虽已选定，但真实服务端密钥、费用预算、限流、外发审批和联调窗口未提供。
2. 没有正式知识；当前合成知识与测试向量默认被正式查询排除。
3. 没有真实设备数据；规则阈值、故障树原因和提示仍是示例/占位参数，未受说明书或真实故障样本验证。
4. Embedding Provider、模型和维度仍待确认，优先评估本地生成以减少外发与费用。
5. 正式学生、教师、班级、实验任务和角色授权仍未建立；临时凭据不能证明真实身份。
6. Phase 9.5 没有实现实时流式 AI、批量离线分析、多模型分层或 AI 自动批准知识。
7. 前端构建仍有 ECharts 517 kB 非阻塞分块提示；Docker `npm ci` 同时报告依赖审计告警，本阶段未在无独立评估时升级依赖。

## 后续门禁

进入真实 AI 联调或 Phase 10 前，项目方仍需提供或确认：

1. DeepSeek 服务端 API Key、人民币预算、调用上限、数据外发审批与保留政策；
2. 可授权知识来源、版本、定位、适用硬件、整理人、技术审核人和正式批准人；
3. Embedding Provider/模型/维度或本地 Embedding 方案；
4. ESP32、传感器、原理图、接线、GPIO、电压、采样和正式错误码协议；
5. 带真值的正常/故障数据、已确认根因、最终修复动作和量化验收指标；
6. 局域网部署机器、地址、备份恢复、监控和正式身份权限方案。

在这些信息未确认前，必须保持 `AI_ENABLED=false`，不得将 Mock、合成知识、测试向量或示例规则描述为真实 AI 与专业诊断能力。Phase 10 尚未开始。
