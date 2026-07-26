# 芯鉴知微系统架构（Phase 9.5）

## 1. 架构目标

系统以可追溯的真实设备数据为基础，将采集、存储、确定性诊断、知识检索、AI 解释和教学反馈分层。第一版采用模块化单体后端，避免为尚未验证的规模引入微服务复杂度。

## 2. 逻辑架构

```text
[待确定的嵌入式设备 + 传感器适配器]
       | HTTP + JSON + device token
       v
[FastAPI /api/v1]
       |-- 请求校验与限流
       |-- 设备/用户/实验服务
       |-- 规则引擎（YAML）
       |-- 故障树（JSON/YAML）
       |-- Episode 事件聚合
       |-- 混合 RAG（PostgreSQL FTS + pgvector + RRF）
       |-- 确定性说明模板
       |-- AI 策略/缓存/可选增强
       v
[PostgreSQL + pgvector]
       ^
       |
[Vue 3 学生端 / 教师端] -- Axios --> [FastAPI]
```

Nginx 在部署阶段提供统一入口和静态资源服务。设备端、前端和后端之间只通过明确 API 交互。

## 3. 目标目录

```text
xinjian-zhiwei/
├── frontend/                 # Vue 3 学生端与教师端
├── backend/                  # FastAPI、业务服务与诊断流水线
│   └── app/
│       ├── api/
│       ├── core/
│       ├── models/
│       ├── schemas/
│       ├── repositories/
│       ├── services/
│       ├── diagnosis/        # rules、fault_tree、rag、anomaly
│       └── ai/               # clients、prompts、structured_output
├── device/                   # PlatformIO 设备项目
├── simulator/                # 明确标记的测试设备模拟器
├── data/knowledge/           # 本地原始资料与解析缓存（Git 忽略）
├── docs/
├── scripts/
├── tests/
├── compose.yaml
└── .env.example
```

Phase 9 已落地 `frontend/`、`backend/`、设备认证与采集 API、可配置测试模拟器、YAML 确定性规则诊断、可配置故障树与分层提示、学生/教师工作台、来源可追溯的知识框架，以及 Provider 无关的 AI/Embedding 客户端、结构化输出校验、审计和降级。当前没有正式知识资料或 Provider，空库和禁用状态不会冒充知识或 AI 能力。

## 4. 模块职责

### 设备端

- 通过待确定的硬件适配器采集通用指标、日志和心跳。
- 对网络错误重试并限制上传频率。
- 使用私密配置保存 Wi-Fi 和设备令牌；仓库只提交示例配置。
- 可生成低风险边缘错误码，但不执行云端诊断或自动硬件控制。

### FastAPI 后端

- 校验身份、请求大小、字段和时间戳。
- 保存业务字段及原始请求，保证诊断证据可追溯。
- 以 Repository/Service 分层管理数据库访问和业务逻辑。
- 统一编排规则、故障树、RAG 和 AI，不让前端越过后端访问内部服务。

### 诊断流水线

1. 从日志、心跳、读数和实验模板构造 `DiagnosisContext`，并把同设备、同实验、同主要错误在时间窗口内聚合为 `DiagnosisEpisode`。
2. YAML 规则与故障树生成不可被 AI 覆盖的 `DiagnosisCore`。
3. 在 Phase 8 同一知识表上执行结构化过滤、PostgreSQL FTS 关键词检索和可选 pgvector 检索，再以 RRF 融合。
4. 确定性模板根据核心证据、原因、知识与 Level 1–4 提示生成完整基础说明。
5. `AIExplanationPolicy` 只对低置信、冲突、未知、多异常、明确追问或升级场景放行；高置信已知异常默认零调用。
6. 放行后先查 PostgreSQL 指纹缓存；生产默认只调用 DeepSeek
   `deepseek-v4-flash` 非思考模式，不做多模型分层。
7. AI 输出经 Pydantic、证据白名单和知识引用校验；任何失败、限流或预算耗尽都返回确定性说明。

### 前端

- 学生端面向当前实验、设备、日志、趋势、诊断和反馈。
- 教师端面向班级进度、设备状态、错误统计和介入队列。
- 统一 API 类型和 Axios 客户端，完整处理加载、空、错误状态。

### PostgreSQL + pgvector

- 统一保存业务数据、诊断证据、调用记录、知识案例和向量。
- Alembic 是数据库结构唯一变更路径。
- 第一版不并行引入其他业务数据库、向量数据库或缓存。

## 5. 关键架构决策

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 后端形态 | FastAPI 模块化单体 | 第一版闭环优先，降低部署和联调复杂度 |
| 传输 | HTTP + JSON | ESP32 与浏览器易实现、易调试；第一版不引入 MQTT |
| 数据库 | PostgreSQL + pgvector | 业务和向量数据统一治理，减少重复基础设施 |
| 诊断优先级 | 规则/故障树先，AI 后 | 结果确定、可解释，并支持 AI 故障降级 |
| AI 接入 | DeepSeek 官方 API + 可替换 `AIClient` | 生产模型固定为 `deepseek-v4-flash` 非思考模式，业务逻辑仍不绑定厂商 |
| API 版本 | `/api/v1` | 稳定设备协议并支持后续兼容演进 |
| 容器基础镜像 | AWS Public ECR 的 Docker Official Images 镜像源 | 当前网络无法连接 Docker Hub；保留 `BASE_REGISTRY` 参数以便切换 |

## 6. 安全与可观测性基线

- 密码和设备令牌哈希保存；密钥只通过后端环境变量注入。
- 按角色校验学生、教师和管理员权限。
- 限制请求大小、设备上传速率和 AI 超时/重试。
- 日志不得记录密码、令牌或 AI 密钥。
- `phase9.5-allowlist-v1` 在模型调用前匿名化设备、截取关键日志、聚合读数并剔除学生身份、令牌、密码、Authorization、Wi-Fi 和教师私人备注。
- `ai_call_records` 保存模型名、完整路由路径、安全输入摘要、耗时、状态和失败分类，但不保存敏感输入或密钥。
- 健康检查、结构化日志和容器健康状态从 Phase 1 开始建立。

## 7. 当前架构风险

1. Git 已提交 Phase 1 至 Phase 9 基线；Phase 9.5 当前位于工作区，按任务要求不自动提交。
2. Docker Desktop 4.82.0 已安装，Compose 三服务运行验收通过；PlatformIO 仍不可用，将在设备阶段处理。
3. 本机 Python 3.9.6 与容器 Python 3.12 均用于分阶段验证；后续仍应持续验证二者行为一致。
4. Node.js v26.3.0 已通过本地 lint、Vitest、类型检查、构建和 Playwright，但生产容器固定使用 Node 22，降低部署兼容风险。
5. DeepSeek Provider、`deepseek-v4-flash` 和非思考模式已经确定；真实 API Key、正式预算、Embedding、ESP32 型号、接线、账号和知识来源仍待确认。
6. 设备令牌轮换、撤销审计、上传限流和生产保留策略尚未实现，将在安全加固阶段补充。
7. 背景 Word 的旧技术草案与固定方案有差异，已在 `PROJECT_CONTEXT.md` 中明确裁决，后续不得同时保留两套实现。
8. Phase 9.5 源码版本为 `0.9.5`，目标迁移为 `20260725_0008`；AI 总开关默认关闭，无 Key 时保持 Disabled。

物理拓扑、USB/Wi-Fi 职责、局域网/公网边界和三种部署模式见
[运行架构](runtime-architecture.md) 与 [部署说明](deployment.md)。Phase 10 尚未开始。
