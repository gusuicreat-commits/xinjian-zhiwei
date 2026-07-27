# P1–P11 独立发布审计证据

审计日期：2026-07-27

版本：`1.0.0`
迁移 Head：`20260727_0014`

本表只映射仓库中可复核的实现和自动化证据。所有场景、评测、账号、知识和处置记录均为
合成或测试数据；它们不构成真实硬件准确率、正式专业知识或生产就绪证明。

| 阶段 | 核心能力 | 主要文件 | 数据库迁移 | 核心接口/命令 | 主要测试 |
| --- | --- | --- | --- | --- | --- |
| P1 | 设备协议 V1：批量、幂等、序列与乱序策略、时间质量、限流 | `backend/app/schemas/device.py`、`backend/app/services/device_ingest.py` | `20260727_0009`、`20260727_0010` | `POST /api/v1/device/ingest`、`DELETE /api/v1/device/test-runs/{id}` | `backend/tests/test_device_protocol_v1.py` |
| P2 | 十个版本化虚拟场景、重放、报告和定向清理 | `simulator/scenario_specs/`、`simulator/xinjian_simulator/dsl.py` | 使用 P1 测试追踪字段 | `xinjian-simulator run/replay/cleanup` | `simulator/tests/test_dsl.py`、`test_scenarios.py` |
| P3 | 合成诊断/检索评测、原因 Top-1/Top-3、必需步骤、禁止结论、Episode、时延和 AI 计数 | `backend/app/evaluation/runner.py`、`backend/evaluation/` | 不写持久业务库；Episode 使用隔离内存库 | `python -m app.cli.run_synthetic_evaluation` | `backend/tests/test_synthetic_evaluation.py` |
| P4 | 七类角色、会话、权限分离、班级/设备资源范围 | `backend/app/services/rbac.py`、`backend/app/api/v1/routes/auth.py` | `20260727_0011` | `/api/v1/auth/session`、`/me`、`/classes`、`/devices` | `backend/tests/test_classroom_auth.py`、`test_knowledge_api.py` |
| P5 | 模板草稿/审核/发布/停用/替代、正式硬件事实门禁、发布版本不可变 | `backend/app/services/experiment_templates.py`、`routes/experiments.py` | `20260727_0012` | `/api/v1/experiments/templates`、`/templates/{id}/versions`、`/template-versions/{id}/status` | `backend/tests/test_experiment_templates.py` |
| P6 | 文件解析、来源和版本、块编辑/拆分/合并、三角色审核、正式检索隔离 | `backend/app/services/knowledge.py`、`knowledge_files.py`、`routes/knowledge.py` | 沿用 `20260720_0007`，`0014` 对齐元数据 | `/api/v1/knowledge/*` | `backend/tests/test_knowledge_api.py`、`test_knowledge_workspace.py` |
| P7 | 学生求助、教师队列、认领/转交/解决/无法确认、时间线、班级越权保护 | `backend/app/services/interventions.py`、`routes/interventions.py` | `20260727_0013` | `/api/v1/teacher-workflow/diagnoses/{id}/intervention`、`/interventions`、`/actions`、`/timeline` | `backend/tests/test_interventions.py` |
| P8 | 健康探针、安全头、请求/上传限制、安全日志、保留 dry-run、备份与隔离恢复 | `backend/app/main.py`、`backend/app/services/device_ingest.py`、`scripts/backup_database.sh`、`restore_drill.sh` | 无新增业务表 | `/health/live`、`/health/ready`、`/health/dependencies` | `backend/tests/test_health.py`、`test_security.py`、协议与知识上传测试 |
| P9 | 统一版本、锁文件、CI、迁移门禁、敏感信息扫描 | `VERSION`、`.github/workflows/ci.yml`、`scripts/verify.sh`、`security_scan.sh` | `20260727_0014` | `scripts/verify.sh`、`scripts/check_version.py` | CI YAML 解析、全套自动化与空库迁移 |
| P10 | 加载/空/错误/断网状态、有限重试、键盘/ARIA、路由懒加载和图表分块 | `frontend/src/api/resilience.ts`、`frontend/src/router/index.ts`、学生/教师视图与图表组件 | 不适用 | `/student`、`/teacher`、`/readiness` | Vitest 9 项；Playwright 4 项 |
| P11 | 精确前缀 seed/reset、合成演示手册、六维 readiness 门禁 | `backend/app/cli/seed_demo.py`、`reset_demo.py`、`routes/readiness.py`、`frontend/src/views/ReadinessView.vue` | 使用 P4/P7 表 | `seed_demo`、`reset_demo`、`GET /api/v1/readiness/status` | `backend/tests/test_readiness.py`，隔离数据库 seed/reset 验收 |

## 审计边界

- 当前 Git 历史的实际审计起点是 `650dbbe0fea65ec5b49cf9b0eb6a5b7fad77b0c9`；
  任务中给出的 `12aa663c60bede4ddd172786134b4b5d02802446` 是其祖先，不是审计开始时的
  `HEAD`。未改写历史。
- 持久 PostgreSQL 只包含历史测试、模拟器、合成知识和 Mock AI 验收数据；没有真实
  ESP32、正式用户、正式模板或正式知识。
- 合成评测的 `30/30` 与检索 `10/10` 只表示固定测试集符合当前示例规则预期。
- 六维 readiness 的软件和演示维度可通过；真实硬件、正式知识、正式组织数据和生产
  部署仍受阻。
