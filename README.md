# 芯鉴知微

面向高校嵌入式与物联网实验课程的智能分析平台。当前已完成 Phase 4：在可配置设备模拟链路上，加入确定性 YAML 规则诊断、证据记录和结果持久化。

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

故障树、用户业务模型和 AI 诊断将在后续阶段实现。

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

- 当前状态：教材、实验指导书、案例库、审核教师和授权范围均未确定。
- 实现方式：知识导入通过来源适配接口完成，并保存 `source_type`、`source_uri`、标题、版本、授权信息、审核状态和更新时间等可追溯元数据。
- 使用限制：来源和授权未确认的内容不得作为正式知识入库；占位内容必须标记为 `TODO[待补充]` 或测试数据。
- 检索约束：后续 RAG 输出必须携带来源引用，不能生成或伪造不存在的知识来源。

### 生产参数

- 当前状态：域名、服务器、数据库凭据、网络拓扑、账号权限、对象存储、监控和备份方案均未确定。
- 实现方式：通过环境变量、部署密钥或外部配置注入；仓库只保留无敏感信息的 `.env.example` 和开发默认值。
- 安全要求：不得提交真实密码、令牌、密钥、证书或生产连接串，也不得用开发占位值直接部署生产环境。

上述项目确定后，应优先补充配置和适配器，并同步更新 README、架构文档、环境变量示例和验收测试，而不是绕过接口在现有代码中加入厂商特例。

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

## 项目文档

- [项目上下文](docs/PROJECT_CONTEXT.md)
- [系统架构](docs/architecture.md)
- [API 设计](docs/api-design.md)
- [数据库设计](docs/database-design.md)
- [设备协议](docs/device-protocol.md)
- [模拟器设计](docs/simulator-design.md)
- [规则诊断设计](docs/diagnosis-rules.md)
- [开发计划](docs/development-plan.md)
- [实现状态](docs/implementation-status.md)
