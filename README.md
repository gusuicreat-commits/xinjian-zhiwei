# 芯鉴知微

面向高校嵌入式与物联网实验课程的智能分析平台。当前完成 Phase 1 项目骨架：Vue 3 前端、FastAPI 后端、PostgreSQL + pgvector 容器配置，以及前后端健康检查链路。

## 当前能力

- `GET /api/v1/health` 返回后端服务状态。
- 前端启动后通过统一 Axios 客户端读取健康状态。
- Compose 定义 PostgreSQL、后端和前端三个服务及健康检查。
- 后端提供结构化日志、配置校验、pytest 和 Ruff。
- 前端提供 TypeScript、Vue Router、Pinia、Element Plus、ECharts、Vitest、Playwright、ESLint 和 Prettier 基础配置。

业务数据模型、设备 API 和认证将在后续阶段实现。

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

## 项目文档

- [项目上下文](docs/PROJECT_CONTEXT.md)
- [系统架构](docs/architecture.md)
- [开发计划](docs/development-plan.md)
- [实现状态](docs/implementation-status.md)
