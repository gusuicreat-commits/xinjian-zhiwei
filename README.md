# 芯鉴知微

面向高校嵌入式与物联网实验课程的智能分析平台。当前完成的是 Phase 9.5 轻量 AI 诊断架构：系统先聚合故障 Episode，再由规则、故障树、已审核知识和模板生成完整解释；AI 仅在低置信、规则冲突、未知异常、持续升级或用户追问等场景按策略增强。生产对话模型已固定为 DeepSeek 官方 API 的 `deepseek-v4-flash` 非思考模式，并保留统一 `AIClient` 边界；由于尚未提供服务端密钥、正式知识、Embedding 配置和外发授权，当前运行模式仍是“确定性诊断，AI 增强关闭”。

## 当前能力

- `GET /api/v1/health` 返回后端服务状态。
- 前端启动后通过统一 Axios 客户端读取健康状态。
- Compose 定义 PostgreSQL、后端和前端三个服务及健康检查。
- 后端提供结构化日志、配置校验、pytest 和 Ruff。
- 前端提供 TypeScript、Vue Router、Pinia、Element Plus、ECharts、Vitest、Playwright、ESLint 和 Prettier 基础配置。
- Alembic 在后端容器启动时自动升级数据库到当前版本。
- 设备令牌仅以 PBKDF2-SHA256 哈希保存，API 不记录或返回原始令牌。
- 日志、读数和心跳保存原始 JSON 请求及 `is_test_data` 标记，支持数据追溯。
- 独立模拟器通过环境变量配置 API、测试设备凭据、通用指标字段和场景数值。
- 所有模拟器载荷强制标记为测试数据，不冒充真实设备或实验结果。
- 统一 `DiagnosisContext` 从日志、心跳、读数和可选实验模板快照构造诊断输入。
- YAML 规则稳定识别读取失败、设备离线和数值越界，结果包含命中规则与原始证据。
- 规则加载、事实解析和运算符匹配相互解耦，调整阈值或新增现有事实组合无需修改主流程。
- 三棵 YAML 故障树为同一异常输出多个有证据的候选原因，并按分数稳定排序。
- 提示根据连续失败次数或异常持续时间升级到 Level 1–4，Level 4 进入教师介入列表。
- 学生端通过真实后端聚合 API 展示任务占位状态、设备状态、最近日志与读数、最新诊断和提示。
- “已解决、未解决、请求教师协助”反馈保存到 PostgreSQL，并继承诊断的测试数据标记。
- 教师端从 PostgreSQL 聚合设备在线状态、最新异常、全部诊断错误频次、七日趋势、设备日志和 Level 4 介入记录。
- 班级进度、实验完成率和学生身份没有数据模型时明确返回 `configured=false`，不生成演示人数或虚构名单。
- Phase 8 建立五张知识表、可配置文本切分、来源授权门禁、审核记录和 Provider 无关的向量存储。
- 知识检索只返回审核通过的知识块，并携带来源、版本、URI、文档定位和测试数据标记。
- Embedding Provider 未配置时拒绝正式向量，只允许明确标记的测试向量用于框架测试。
- Phase 9 新增 `DiagnosisCore`、确定性解释模板和 `DiagnosisEpisode`，AI 关闭时也能返回证据、原因、步骤、提示等级、教师介入状态及限制说明。
- 知识检索采用结构化过滤 + PostgreSQL 全文检索 + 可选 pgvector 的轻量混合检索；未配置 Embedding 时仍可使用全文检索。
- Phase 9.5 的唯一生产调用路径为 `cache → deepseek → deterministic_fallback`；统一 `AIClient`、禁用/Mock/缓存/预算/Token/Pydantic 与确定性降级能力继续保留。
- AI 上下文执行最小化白名单：设备标识匿名化、日志限量、传感器/心跳聚合，且不发送令牌、密钥、Wi-Fi、学生身份或原始自由文本敏感内容。
- AI 解释接口只允许引用确定性规则证据和本次检索到的知识块，不能修改规则错误类型。
- 每次 AI 决策的触发原因、Episode、缓存、路由、Token、成本占位、耗时、校验和降级原因保存到 `ai_call_records`，密钥不入库。
- 相同规则、故障树、知识版本和输入生成稳定指纹，成功解释可保存到 PostgreSQL `ai_explanation_cache`；单 Episode、单设备小时和每日预算均有配置门禁。
- AI 未配置、知识未就绪、检索失败、超时或输出非法时，接口保存跳过/失败审计并返回原规则与故障树结果。

正式学生/教师账号、班级与实验任务、真实知识内容、Embedding 配置、真实 AI 联调和真实硬件验证将在后续阶段实现。

## 尚未确定的配置与实现边界

以下内容目前尚未由项目方确定。后续实现必须保持可配置、可替换和可追溯，不得把具体厂商、硬件型号、字段结构或生产配置写死在业务代码中。

### AI Provider

- 已确定：生产 Provider 为 DeepSeek 官方 API，Base URL 为 `https://api.deepseek.com`，模型为 `deepseek-v4-flash`，使用非思考模式；不做多模型分层。
- 尚未提供：真实 `AI_API_KEY`、费用预算、并发/限流、数据外发审批和正式联调窗口。
- 实现方式：后端继续通过统一 `AIClient`/`EmbeddingClient` 接口隔离厂商传输；超时、重试、预算、Token、知识门禁和上下文上限通过环境变量或配置对象注入。
- 默认行为：`.env.example` 保持 `AI_ENABLED=false`、`AI_API_KEY=`；未显式启用或缺少密钥时不发起外部请求，失败时始终返回确定性诊断。

### ESP32 与传感器

- 当前状态：开发板型号、传感器型号、接线方式、采样频率和业务字段均未确定。
- 实现方式：采用通用设备、传感器、指标和读数模型。建议以 `device_id`、`sensor_type`、`metric_key`、`value`、`unit`、`observed_at` 和可扩展 `metadata` 表达采集数据。
- 扩展方式：具体硬件协议、字段映射和校验规则由设备配置或适配器提供，不在核心业务模型中固定某一种开发板或传感器。
- 占位行为：真实设备接入前使用明确标记为测试数据的模拟器，不把模拟数据描述为真实采集结果。

### 知识库来源

- 当前状态：通用数据表、文本导入、切分、审核、向量保存和检索接口已经实现；教材、实验指导书、案例库、审核教师、授权范围以及正式知识记录仍未确定或提供。
- 实现方式：知识导入通过来源适配接口完成，并保存 `source_type`、`source_uri`、标题、版本、授权信息、审核状态、内容哈希和更新时间等可追溯元数据。
- 使用限制：来源和授权未确认的内容不得作为正式知识入库；占位内容必须标记为 `TODO[待补充]` 或测试数据。
- 检索约束：当前向量检索已经强制只返回审核通过的知识块并携带来源；后续 RAG 输出也必须保留引用，不能生成或伪造不存在的知识来源。
- 文件位置：本地原始资料放在被 Git 忽略的 `data/knowledge/raw/`，解析结果放在 `data/knowledge/processed/`；生产原文件应放在经授权的对象存储，不能把内部或版权资料直接提交到仓库。

### 生产参数

- 当前状态：域名、服务器、数据库凭据、网络拓扑、账号权限、对象存储、监控和备份方案均未确定。
- 实现方式：通过环境变量、部署密钥或外部配置注入；仓库只保留无敏感信息的 `.env.example` 和开发默认值。
- 安全要求：不得提交真实密码、令牌、密钥、证书或生产连接串，也不得用开发占位值直接部署生产环境。

上述项目确定后，应优先补充配置和适配器，并同步更新 README、架构文档、环境变量示例和验收测试，而不是绕过接口在现有代码中加入厂商特例。

## 真实诊断资料门禁

截至 2026-07-25，项目虽然已经建立知识库和 AI 通用框架，但仍明确**没有**以下内容：

- 没有真实设备上传数据；现有心跳、日志、读数、诊断和提示历史全部标记为测试数据。
- 没有经确认的开发板/传感器型号、原理图、接线图、GPIO 映射、采样周期或正式字段协议。
- 没有设备说明书、传感器 datasheet、正式实验手册、维修案例、行业标准或论文作为诊断依据。
- 没有经真实故障数据验证的规则阈值、原因权重、置信区间或提示升级参数；当前 YAML 内容属于示例规则、占位故障树和待确认参数。
- 没有导入任何正式知识来源或正式向量。数据库仅保留一组明确标记为 `is_test_data=true` 的 Phase 9 合成验收知识与测试向量，不能描述成课程知识或专业依据。
- 对话 AI 的 Provider、模型、Base URL 和非思考模式已经确定；但没有 API 凭据、外发授权或正式模型调用记录。Embedding Provider/模型仍未确定，当前诊断仍完全属于确定性规则匹配。

在对外声明“真实硬件诊断可用”之前，以下资料必须由项目方提供或明确确认，并完成来源、版本和审核记录：

1. 具体硬件 BOM：开发板、传感器、LED/按键及外围器件的型号和版本。
2. 电路与接线资料：原理图、接线图、GPIO/接口映射、供电和上下拉要求及安全限制。
3. 官方技术资料：开发板说明书、传感器 datasheet、通信时序、量程、精度和采样限制。
4. 固件上传协议：正式日志格式、事件码、指标字段、单位、时间戳、心跳与重试策略。
5. 实验模板：实验目标、步骤、正常范围、采样频率、离线阈值和完成/失败判定。
6. 带真值的真实数据：正常样本、可控故障样本、已确认根因、修复动作和修复结果。
7. 经教师或工程人员审核的诊断规则：故障分类、证据条件、阈值、原因权重、置信标准和介入条件。
8. 可授权的知识来源：课程资料、设备手册、FAQ、维修案例、标准或论文，以及审核人和授权范围。
9. AI 运行授权：服务端 API Key、数据外发限制与审批、隐私责任人、费用预算、限流和正式联调窗口；Provider/模型已由 Phase 9.5 固定。
10. 生产与验收要求：账号角色、设备注册、部署网络、数据保留、备份审计、准确率/误报率/漏报率目标和试运行范围。

任何一项尚未确认时，必须继续使用通用接口或明确的 `TODO[待补充]`/`placeholder`，不得用开发示例值冒充真实专业知识。

## 本地开发

### 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

验证：

```bash
cd backend
ruff check .
pytest
alembic upgrade head
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认打开 `http://localhost:5173`，并把 `/api` 代理到 `http://localhost:8000`。

验证：

```bash
cd frontend
npm run lint
npm run test
npm run build
```

## Docker Compose

先创建本地环境文件并替换开发占位密码：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

服务地址：

- 前端：`http://localhost:8080`
- 后端 API：`http://localhost:8000/api/v1/health`
- Swagger：`http://localhost:8000/docs`
- PostgreSQL：仅在 Compose 内部网络中暴露 `5432`，不映射到宿主机。

Dockerfile 默认从 AWS Public ECR 的 Docker Official Images 仓库获取 Python、Node.js 和 Nginx 基础镜像，以兼容 Docker Hub 认证端点不可达的网络；可在构建时通过 `BASE_REGISTRY` build argument 替换镜像注册表。

日志：

```bash
docker compose logs backend
docker compose logs frontend
```

不要提交 `.env`、真实数据库密码、设备令牌或 AI 密钥。

## Phase 2 设备 API

设备请求使用 `X-Device-Token`，日志、读数和心跳接口还需使用 `X-Device-ID`。令牌必须是高熵随机值，并通过交互式命令创建，不能写入源码、README 或版本控制：

```bash
docker compose exec backend python -m app.cli.create_device \
  --device-id TODO_DEVICE_ID \
  --display-name "TODO[待补充]: 设备名称" \
  --device-type "TODO[待补充]: 通用设备类别"
```

可用接口：

- `POST /api/v1/device/logs`
- `POST /api/v1/device/readings`
- `POST /api/v1/device/heartbeat`
- `GET /api/v1/device/{device_id}/status`

传感器数据使用通用字段 `sensor_type`、`metric_key`、`value`、`unit`、`observed_at` 和 `metadata`。具体开发板、传感器型号及厂商字段只能通过后续适配器或配置映射接入，不能修改核心模型来写死某个硬件。

## Phase 3 设备模拟器

模拟器位于 `simulator/`，支持以下场景：

- `normal`
- `read-failure`
- `offline`
- `out-of-range`
- `value-stuck`

安装和运行：

```bash
cd simulator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

export XINJIAN_API_BASE_URL=http://127.0.0.1:8000
export XINJIAN_DEVICE_ID=TODO_TEST_DEVICE_ID
export XINJIAN_DEVICE_TOKEN=TODO_LOCAL_SECRET
xinjian-simulator normal --iterations 1
```

真实令牌不得写入脚本、README、`.env.example` 或 Git。具体传感器字段和场景值由 `XINJIAN_*` 环境变量映射，详见 `simulator/.env.example`。

## Phase 4 规则诊断

诊断运行接口为 `POST /api/v1/diagnosis/devices/{device_id}/run`，沿用设备令牌认证。请求可提供通用实验模板范围：

```json
{
  "lookback_seconds": 3600,
  "experiment_template": {
    "template_id": "TODO[待补充]",
    "metric_ranges": {
      "TODO_METRIC_KEY": {"minimum": 0, "maximum": 100}
    }
  }
}
```

示例字段和值仅说明接口结构，不代表已确定传感器、实验模板或生产阈值。Phase 4 尚无实验模板业务表，因此模板快照由调用方显式注入；对应模型确定后应由服务端加载并校验授权。规则说明见 `docs/diagnosis-rules.md`。

## Phase 5 故障树与提示

- `POST /api/v1/diagnosis/results/{diagnosis_result_id}/guidance`：为已有规则诊断生成或幂等读取提示。
- `GET /api/v1/diagnosis/devices/{device_id}/guidance`：设备令牌保护的提示历史。
- `GET /api/v1/diagnosis/interventions`：临时审阅接口，需要 `X-Review-Token`；`REVIEW_ACCESS_TOKEN` 未配置时默认返回 503，保持关闭。

计划要求中的“DHT11 读取失败、LED 不亮、按键无反应”以 `status: placeholder` 的课程示例模板保存，不代表硬件选型已经确定。模板不包含板卡型号、引脚或生产阈值，实际课程与硬件确认后须通过 YAML 配置审核替换。详见 `docs/fault-tree-guidance.md`。

## Phase 6 学生端

- 登录页暂时使用 `X-Device-ID` 与设备令牌调用 `POST /api/v1/student/session` 验证。令牌只保存在浏览器 `sessionStorage`，关闭标签页后失效，不写入服务端日志或仓库。
- `/student` 工作台通过 `GET /api/v1/student/dashboard` 读取当前设备的真实数据库记录，并完整处理加载、无数据、正常、异常和请求错误状态。
- `POST /api/v1/student/diagnoses/{diagnosis_result_id}/feedback` 保存 `resolved`、`unresolved` 或 `request_teacher_help`。当前反馈属于设备维度，不得解释为已实现学生身份。
- 正式学生账号、班级、实验任务和角色授权尚不存在，所以任务卡明确返回 `configured=false`。这些模型必须在项目方确认身份与课程结构后建立，不能用虚构账号或任务填充。
- 页面中的诊断仍完全来自 Phase 4/5 的确定性示例规则与占位故障树；Phase 9 状态卡会明确显示 Provider/Embedding 是否就绪，默认不会调用 AI，也没有真实硬件数据支持。

## Phase 7 教师端

- `/teacher/login` 暂时使用 `REVIEW_ACCESS_TOKEN` 对应的审阅令牌验证；令牌只保存在当前标签页的 `sessionStorage`。环境变量为空时接口返回 503 并保持关闭。
- `/teacher` 通过 `GET /api/v1/teacher/dashboard` 读取真实数据库聚合，包含设备状态、错误排行、七日趋势、异常设备、按设备筛选的日志和 Level 4 介入记录。
- ECharts 设备状态、横向错误排行和错误趋势图支持窗口自适应；班级进度因班级/学生/任务模型尚未建立而显示明确空状态，不伪造完成率。
- 当前异常对象只能定位到设备，不能声称已识别“异常学生”；知识卡片读取 Phase 8 实际来源、文档、待审核知识块和向量数量。
- 统计保留 `is_test_data` 来源标记。没有测试标记也不等同于真实硬件已验证，数据真实性仍以来源审计为准。

## Phase 8 通用知识库框架

- `GET /api/v1/knowledge/status`：返回来源、文档、待审核文档、已审核知识块、向量数量和 Provider 配置状态。
- `POST /api/v1/knowledge/sources`：登记来源标识、类型、标题、版本、URI、授权范围和测试标记。
- `POST /api/v1/knowledge/sources/{source_id}/documents/text`：导入已经提取的 `text/*` 内容，按配置切分并以内容哈希幂等去重。
- `PATCH /api/v1/knowledge/documents/{document_id}/review`：按整理人、技术审核人和正式批准人的职责执行 `draft → pending → technical_reviewed → approved`，并支持拒绝、撤回和被替代。
- `POST /api/v1/knowledge/documents/{document_id}/embeddings`：保存外部适配器生成的向量；Provider 未确认时只接受测试向量。
- `POST /api/v1/knowledge/search`：按 Provider、模型和维度检索审核通过的知识块，默认排除测试数据并返回完整来源引用。
- 当前只实现提取后文本的通用导入接口，不声称已经解析 PDF、DOCX、扫描件或网页；这些格式须由后续来源适配器处理。
- Phase 9 已能在 Provider 与知识均就绪时调用本接口检索；当前空库和禁用 Provider 会触发门禁，诊断仍完全属于确定性规则与故障树。

详细数据结构、配置、文件位置和资料门禁见 [Phase 8 通用知识库框架](docs/knowledge-base.md)。

## Phase 9 轻量 AI 诊断框架

- `GET /api/v1/diagnosis/ai/status`：返回框架、AI Provider、Embedding 客户端、知识门禁和 Prompt 版本状态，不返回密钥。
- `POST /api/v1/diagnosis/devices/{device_id}/run`：兼容原字段，并新增 `deterministic_result`、`explanation`、`ai_enhancement` 和 `episode`。
- `POST /api/v1/diagnosis/results/{diagnosis_result_id}/ai-explanation`：设备凭据保护的按需增强入口，可选提交 `user_question`；没有 AI 时仍返回确定性解释。
- `AI_ENABLED=false` 与 `KNOWLEDGE_EMBEDDING_TRANSPORT=disabled` 是默认值；DeepSeek Provider 参数虽然已经确定，仍只有显式启用且配置真实服务端密钥后才允许外部请求。
- `AI_REQUIRE_KNOWLEDGE=true` 默认要求存在匹配的已审核知识；全文检索无需 Embedding，向量配置就绪后通过 RRF 与全文结果融合。
- AI 输入由 `phase9.5-allowlist-v1` 清洗：设备 ID 匿名化，日志只选相关的 3–10 条，心跳与读数聚合为摘要，知识正文限长；不包含设备令牌、审阅令牌、Provider 密钥、Wi-Fi、学生身份或其他敏感上下文。
- AI 输出必须满足稳定 JSON Schema；错误类型必须来自规则命中，证据必须逐字来自规则证据白名单，知识引用必须来自本次检索结果。
- 唯一生产路由为缓存、DeepSeek、确定性模板降级；调用次数、小时频率、每日人民币预算和输入/输出 Token 都可配置。
- 学生端以“诊断解释/确定性结果”为主，明确 AI 不是诊断前置条件。当前没有真实密钥、外发授权和正式知识，因此增强保持不可用。

AI 默认不是诊断前置条件。单条已知规则具有完整证据与确定性步骤、相同 Episode 重复上报、页面刷新、教师统计查询和普通知识检索都不会自行触发 Provider。低置信、未知异常、多规则或多异常组合、Episode 升级、学生主动追问以及教师明确请求案例草稿时，策略才允许进入缓存与 Provider 路由；每次判断保存具体 `trigger_reason`。

所有 Provider 关闭、知识不足、输入过长、预算超限、Provider 超时或 Pydantic 校验失败时，系统返回已经生成的 `DiagnosisCore` 和确定性模板，不返回空白卡片，也不把“未调用 AI”作为系统故障。费用单价、单次预算、每日预算、输入/输出 Token 都是可选配置，未确认前不写死真实价格。

RAG 流程为：审核与测试标记门禁 → `experiment_id/error_code/device_type` 等结构化过滤 → PostgreSQL `simple` 全文检索 → 可选 pgvector 排名 → RRF 融合 → 来源、版本、定位、审核状态和分项分数输出。正式检索默认排除测试知识；只有显式 `include_test_data=true` 的验收路径才可使用测试知识与 `phase9-test-vector` 合成向量。测试向量不代表已选择 Embedding Provider。

## Phase 9.5 运行与治理收口

- 固定生产对话模型为 DeepSeek 官方 API 的 `deepseek-v4-flash`，显式关闭思考模式；统一 `AIClient` 继续作为厂商隔离接口。
- 生产路径只有 `cache → deepseek → deterministic_fallback`，本地 Provider 扩展能力不作为生产默认路径。
- 审计只保存匿名标识、输入摘要哈希、数量、路由、Token/费用占位和安全错误分类，不保存原始 Prompt、密钥或 Provider 原始错误体。
- 正式知识采用七状态治理，整理、技术审核和正式批准三种角色分离；只有 `approved` 且非测试知识能进入正式 RAG。
- 运行边界、局域网/公网场景、设备责任边界、隐私最小化与知识优先级见 [运行架构](docs/runtime-architecture.md)。
- 开发、局域网演示和正式部署的配置、持久化、备份恢复与检查命令见 [部署说明](docs/deployment.md)。

### 真实使用流程

1. 外部传感器通过跳线连接 ESP32；ESP32 固件负责采样、生成统一日志/读数/心跳 JSON，USB 仅用于供电、烧录和串口调试。
2. ESP32 通过 Wi-Fi 和 HTTP 将 JSON 上传到局域网中的后端 API，不直接访问 PostgreSQL，也不持有 DeepSeek 密钥。
3. 后端完成设备认证、持久化、规则与故障树诊断、知识检索和隐私清洗；需要 AI 增强时才按生产路由调用 DeepSeek。
4. 学生端读取当前设备状态、趋势和诊断反馈；教师端读取聚合状态、异常、介入列表和知识治理入口。
5. 公网部署必须额外配置 HTTPS、域名/反向代理、正式身份权限、密钥管理、备份、监控和数据外发审批，不能直接沿用开发占位凭据。

当前 Phase 9.5 已完成代码实现；Phase 10 尚未开始，也没有新增 ESP32 固件。

实现与安全边界详见 [Phase 9 AI 诊断设计](docs/ai-diagnosis-design.md)。

## 项目文档

- [项目上下文](docs/PROJECT_CONTEXT.md)
- [系统架构](docs/architecture.md)
- [API 设计](docs/api-design.md)
- [数据库设计](docs/database-design.md)
- [设备协议](docs/device-protocol.md)
- [模拟器设计](docs/simulator-design.md)
- [规则诊断设计](docs/diagnosis-rules.md)
- [故障树与分层提示](docs/fault-tree-guidance.md)
- [通用知识库框架](docs/knowledge-base.md)
- [Provider 无关 AI 诊断框架](docs/ai-diagnosis-design.md)
- [Phase 9.5 运行架构](docs/runtime-architecture.md)
- [部署说明](docs/deployment.md)
- [开发计划](docs/development-plan.md)
- [实现状态](docs/implementation-status.md)
