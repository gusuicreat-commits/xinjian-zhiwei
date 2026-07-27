# 芯鉴知微部署说明（1.0.0）

## 开发模式

开发者电脑安装 Docker Desktop，在项目根目录维护不提交 Git 的 `.env`，然后运行：

```bash
docker compose up -d --build
docker compose ps
```

默认入口：

- 前端：`http://localhost:8080`
- 后端健康检查：`http://localhost:8000/api/v1/health`
- OpenAPI：`http://localhost:8000/docs`
- PostgreSQL：仅 Compose 内部可见

没有 DeepSeek Key 时保持 `AI_ENABLED=false`。本地开发、测试、模拟器、规则、故障树和前端不依赖公网。

## 实验室局域网试运行

推荐在实验室固定电脑、小型主机或学院服务器运行同一套 Docker Compose。为该机器配置固定局域网 IP，并保证 ESP32、学生电脑、教师电脑和服务器之间可达。

设备固件中的 API 地址应指向服务器局域网地址，不得使用学生电脑自己的 `localhost`。浏览器同样访问服务器局域网地址。第一版不要求购买域名、公网 IP 或云服务器。

试运行前至少确认：

1. 实验室 Wi-Fi 允许设备与服务器互访；
2. 服务器防火墙开放统一 Web/API 入口；
3. PostgreSQL 不直接暴露给设备或浏览器；
4. `.env` 中数据库密码和设备凭据已经替换；
5. 正式知识、审核责任和测试数据边界明确；
6. 已演练断网后确定性诊断；
7. 数据卷有可恢复备份。

如需 DeepSeek，只有服务器需要访问公网。公网中断时设备上传、数据库、规则、故障树、本地 RAG 和前端继续运行。

## 正式部署

正式部署可选校园网服务器、学校私有云、学院服务器或合规国内云服务器。进入该阶段前必须补齐：

- HTTPS、域名和证书轮换；
- 防火墙、反向代理和访问限流；
- 正式学生/教师账号、角色授权和多班级隔离；
- 设备注册、令牌轮换、撤销与审计；
- 数据库自动备份、恢复演练和灾难恢复；
- 应用日志、指标、告警和故障值班流程；
- 数据保留周期、隐私政策和数据外发审批；
- DeepSeek 预算、限流、密钥托管和调用审计。

Phase 9.5 不执行正式生产部署。

## 数据持久化、备份和恢复边界

Compose 使用 `postgres_data` 命名卷。容器重建不应删除该卷。备份必须包含 PostgreSQL 业务表、pgvector 向量、Alembic 版本和恢复校验；仅复制容器文件系统不是备份。

开发阶段可以使用 `pg_dump`/`pg_restore` 演练，但正式备份位置、加密、保留周期、恢复时间目标和负责人尚待项目方确认。未经确认不得自动上传数据库备份到第三方服务。

仓库提供：

```bash
scripts/backup_database.sh /explicit/existing-directory/backup.dump
scripts/restore_drill.sh /explicit/path/backup.dump
PYTHONPATH=backend backend/.venv/bin/python -m app.cli.retention_dry_run --days 30
```

备份拒绝覆盖；恢复使用临时隔离数据库并在退出时删除该临时库，不删除 Compose 数据卷。
保留命令只报告候选数量，实际删除策略仍待项目方确认。

## DeepSeek 配置边界

仓库只提供非敏感配置：

```text
AI_ENABLED=false
AI_PROVIDER=deepseek
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
AI_THINKING_ENABLED=false
AI_API_KEY=
```

真实 Key 只能通过服务器密钥管理或不提交 Git 的 `.env` 注入。即使 Key 存在，`AI_ENABLED=false` 也不会调用；启用后仍受策略、缓存、次数、Token、预算、隐私和结构校验门禁。

## 验收

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 frontend
curl http://127.0.0.1:8000/api/v1/health
curl -I http://127.0.0.1:8080/student
```

验收必须同时验证无公网和无 Key 场景能返回确定性诊断，不能只验证容器启动。
