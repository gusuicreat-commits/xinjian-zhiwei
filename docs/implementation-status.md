# 芯鉴知微实现状态

最后更新：2026-07-19（Phase 2）

## 总体状态

- 当前阶段：Phase 2 实现、本地测试、Alembic 迁移和 Docker/PostgreSQL 运行验收全部完成。
- 下一阶段：Phase 3 尚未开始。
- Git：已在 `main` 建立 Phase 1 基线提交；Phase 2 变更尚未提交。
- 验收数据：本地开发数据库包含一个明确标记的 Phase 2 测试设备，以及日志、读数、心跳各一条 `is_test_data=true` 的验收记录；它们不代表真实硬件或实验数据。

## Phase 2 实现情况

- [x] 创建 SQLAlchemy 2 declarative base、会话和四个通用模型：Device、DeviceLog、SensorReading、DeviceHeartbeat。
- [x] 创建 Alembic 环境和初始迁移 `20260719_0001`。
- [x] 后端容器启动时先执行 `alembic upgrade head`。
- [x] 使用带随机盐的 PBKDF2-SHA256 哈希保存设备令牌。
- [x] 提供交互式设备创建 CLI，不回显或保存明文令牌。
- [x] 实现 `POST /api/v1/device/logs`。
- [x] 实现 `POST /api/v1/device/readings`。
- [x] 实现 `POST /api/v1/device/heartbeat` 并更新服务端 `last_seen_at`。
- [x] 实现 `GET /api/v1/device/{device_id}/status`。
- [x] 保存经过校验的原始 JSON 请求、服务端接收时间和测试数据标记。
- [x] 对缺字段、额外字段、非有限数值和无时区时间戳返回 422。
- [x] 对未知、停用或令牌错误的设备统一返回 401。
- [x] 传感器采用 `sensor_type`、`metric_key`、`value`、`unit` 和 `metadata` 通用模型，没有写死硬件型号或厂商字段。

## 主要修改与新增文件

- 数据层：`backend/app/db/`、`backend/app/models/`。
- 认证：`backend/app/core/security.py`、`backend/app/api/dependencies.py`。
- API 与服务：`backend/app/api/v1/routes/device.py`、`backend/app/services/device_ingest.py`。
- Schema：`backend/app/schemas/device.py`。
- 迁移：`backend/alembic.ini`、`backend/migrations/`。
- 启动与运维：`backend/app/startup.py`、`backend/app/cli/create_device.py`、`backend/Dockerfile`。
- 测试：`backend/tests/conftest.py`、`test_device_api.py`、`test_security.py`。
- 文档：`README.md`、`docs/api-design.md`、`docs/database-design.md`、`docs/device-protocol.md`。

## 数据库迁移

- Revision：`20260719_0001`。
- 新建：`devices`、`device_logs`、`sensor_readings`、`device_heartbeats`。
- 启用：`vector` 扩展（幂等创建）。
- 实际数据库：`alembic current` 为 `20260719_0001 (head)`。
- 一致性：`alembic check` 返回 `No new upgrade operations detected`。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| Ruff | `backend/.venv/bin/ruff check .` | 通过 |
| pytest | `pytest -W error` | 12 passed，0 warning |
| Python 3.9 语法 | `compileall` 使用独立缓存目录 | 通过 |
| Alembic head | `alembic heads` | `20260719_0001 (head)` |
| 离线迁移 SQL | `alembic upgrade head --sql` | 完整生成 |
| 实际迁移 | 后端容器启动入口 | PostgreSQL 升级成功 |
| 模型/迁移一致性 | 容器内 `alembic check` | 无待生成操作 |
| 合法日志上传 | 实际容器 API | 201，数据库可查询 |
| 合法读数上传 | 实际容器 API | 201，数据库可查询 |
| 合法心跳上传 | 实际容器 API | 201，`last_seen_at` 已更新 |
| 状态查询 | 实际容器 API | 200，返回 `online` |
| 非法令牌 | 实际容器 API | 401，未写入 |
| 缺少必填字段 | 实际容器 API | 422 |
| Compose | `docker compose ps` | PostgreSQL、backend、frontend 全部 healthy |
| 健康接口 | `GET /api/v1/health` | 200，版本 `0.2.0` |
| 前端回归 | ESLint、Prettier、Vitest、类型检查与生产构建 | 全部通过，2 tests passed |
| 容器浏览器 E2E | Chrome + `http://127.0.0.1:8080` | 1 passed，显示 Phase 2 运行链路 |

## 已知问题与风险

1. AI Provider、具体硬件、知识来源和生产参数尚未确定；README 已明确统一接口、通用模型与占位规则，后续不得写死。
2. 当前只实现设备侧数据接收，尚无学生、教师、实验或设备管理权限 API。
3. 设备令牌轮换、撤销审计和上传限流将在安全加固阶段补充；当前可通过 `is_active=false` 停用设备。
4. Swagger UI 静态资源仍依赖 CDN，离线部署优化留待部署阶段。
5. Docker Hub 在当前网络超时，基础镜像继续使用可覆盖的 AWS Public ECR Docker Official Images 镜像源。

## 下一阶段

Phase 3 将实现明确标记为测试数据的设备模拟器，包括正常、读取失败、离线、越界和数值不变场景。用户再次明确输入“继续下一阶段”前，不进入 Phase 3。
