# 芯鉴知微

面向高校嵌入式与物联网实验课程的智能分析平台。当前已完成 Phase 8 通用知识库框架：在学生端与教师端基础上，后端已具备来源登记、文本切分、授权审核、向量保存和带引用检索能力；由于尚未提供正式资料和 Embedding Provider，当前知识库仍为空。

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

正式学生/教师账号、班级与实验任务、真实知识内容、自动 Embedding 和 AI 诊断将在后续阶段实现。

## 尚未确定的配置与实现边界

以下内容目前尚未由项目方确定。后续实现必须保持可配置、可替换和可追溯，不得把具体厂商、硬件型号、字段结构或生产配置写死在业务代码中。

### AI Provider

- 当前状态：Provider、模型名称、服务地址和生产密钥均未确定。
- 实现方式：后端通过统一 `AIClient` 接口接入模型服务，Provider 适配器可替换；模型、Base URL、超时和重试策略通过环境变量或配置对象注入。
- 默认行为：使用不发起外部请求的占位实现；AI 未配置或调用失败时，系统仍应返回规则诊断结果。
- 占位配置：`.env.example` 中的 `AI_PROVIDER`、`AI_BASE_URL`、`AI_MODEL` 和 `AI_API_KEY` 仅用于声明配置入口，不代表已选择任何厂商。

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

截至 2026-07-21，项目虽然已经建立知识库通用框架，但仍明确**没有**以下内容：

- 没有真实设备上传数据；现有心跳、日志、读数、诊断和提示历史全部标记为测试数据。
- 没有经确认的开发板/传感器型号、原理图、接线图、GPIO 映射、采样周期或正式字段协议。
- 没有设备说明书、传感器 datasheet、正式实验手册、维修案例、行业标准或论文作为诊断依据。
- 没有经真实故障数据验证的规则阈值、原因权重、置信区间或提示升级参数；当前 YAML 内容属于示例规则、占位故障树和待确认参数。
- 没有导入任何正式知识来源、知识文档、知识块、Embedding 或 pgvector 向量记录；现有五张知识表为空，不能描述成系统已经拥有知识数据。
- 没有 AI Provider、模型、API 凭据、`AIClient` 或模型调用；当前诊断完全属于确定性规则匹配。

在对外声明“真实硬件诊断可用”之前，以下资料必须由项目方提供或明确确认，并完成来源、版本和审核记录：

1. 具体硬件 BOM：开发板、传感器、LED/按键及外围器件的型号和版本。
2. 电路与接线资料：原理图、接线图、GPIO/接口映射、供电和上下拉要求及安全限制。
3. 官方技术资料：开发板说明书、传感器 datasheet、通信时序、量程、精度和采样限制。
4. 固件上传协议：正式日志格式、事件码、指标字段、单位、时间戳、心跳与重试策略。
5. 实验模板：实验目标、步骤、正常范围、采样频率、离线阈值和完成/失败判定。
6. 带真值的真实数据：正常样本、可控故障样本、已确认根因、修复动作和修复结果。
7. 经教师或工程人员审核的诊断规则：故障分类、证据条件、阈值、原因权重、置信标准和介入条件。
8. 可授权的知识来源：课程资料、设备手册、FAQ、维修案例、标准或论文，以及审核人和授权范围。
9. AI 使用决策：是否接入、Provider/模型、数据外发限制、隐私、费用、超时、降级和审核要求。
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
- 页面中的诊断仍完全来自 Phase 4/5 的确定性示例规则与占位故障树；没有调用 AI，也没有真实硬件数据支持。

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
- `PATCH /api/v1/knowledge/documents/{document_id}/review`：批准或拒绝文档，来源未记录授权范围时禁止批准。
- `POST /api/v1/knowledge/documents/{document_id}/embeddings`：保存外部适配器生成的向量；Provider 未确认时只接受测试向量。
- `POST /api/v1/knowledge/search`：按 Provider、模型和维度检索审核通过的知识块，默认排除测试数据并返回完整来源引用。
- 当前只实现提取后文本的通用导入接口，不声称已经解析 PDF、DOCX、扫描件或网页；这些格式须由后续来源适配器处理。
- 当前没有 AI 模型调用，诊断仍完全属于确定性规则与故障树；知识检索尚未接入诊断流水线。

详细数据结构、配置、文件位置和资料门禁见 [Phase 8 通用知识库框架](docs/knowledge-base.md)。

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
- [开发计划](docs/development-plan.md)
- [实现状态](docs/implementation-status.md)
