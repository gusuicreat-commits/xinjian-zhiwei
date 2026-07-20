# 芯鉴知微实现状态

最后更新：2026-07-20（Phase 4）

## 总体状态

- 当前阶段：Phase 4 实现、测试、镜像构建和实际 PostgreSQL 诊断验收完成。
- 下一阶段：Phase 5 尚未开始。
- Git：Phase 3 已提交为 `aa3005095d45907e1fd2c84d6b8ae238e8c4cb12 feat: complete phase 3 device simulator`；Phase 4 变更尚未提交。
- 运行状态：原 PostgreSQL、backend、frontend 容器保持运行，未因本阶段停止或替换；Phase 4 新镜像已构建并通过一次性容器验收。

## Phase 4 实现情况

- [x] 统一 `DiagnosisContext` 覆盖日志、心跳、读数、最后在线时间和可选实验模板快照。
- [x] YAML 规则通过 Pydantic 严格加载，规则文件按名称、规则按优先级与 ID 确定性排序。
- [x] 事实解析器和运算符表替代按错误类型堆叠的条件分支。
- [x] 实现 `SENSOR_READ_FAILED`、`DEVICE_OFFLINE`、`VALUE_OUT_OF_RANGE` 三类核心规则。
- [x] 每个命中结果包含对应日志、离线时间或越界读数与边界证据。
- [x] 相同上下文和规则集产生相同匹配内容及 SHA-256 输入指纹。
- [x] 修改 YAML 阈值无需修改主程序，并由自动化测试验证。
- [x] 诊断结果保存规则版本/哈希、指纹、命中规则、证据、上下文快照和测试数据标记。
- [x] 新增设备认证的诊断运行 API，不暴露或保存原始令牌。

## 数据库迁移

- 新增 `20260720_0002_phase4_diagnosis_results.py`。
- 新增 `diagnosis_results` 表及设备/创建时间、输入指纹索引。
- 已在现有 PostgreSQL 实际执行，`alembic current` 返回 `20260720_0002 (head)`。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 后端 Ruff | `ruff check app tests`、`ruff format --check app tests` | 通过 |
| 后端测试 | `pytest` | 21 passed |
| 模拟器回归 | Ruff、格式、`pytest -W error` | 8 passed |
| 前端回归 | ESLint、Prettier、Vitest、类型检查、构建 | 2 tests passed，构建通过 |
| Compose 镜像 | `docker compose build backend frontend` | 0.4.0 镜像构建通过 |
| PostgreSQL 迁移 | 一次性 Phase 4 后端容器 | `20260720_0002 (head)` |
| 实际诊断 API | 随机临时设备 + TestClient + PostgreSQL | 三类规则全部命中，HTTP 201 |
| 证据持久化 | 查询 `diagnosis_results` | 3 组证据，测试标记为 true |
| 容器保持运行 | `docker compose ps` | 原三个服务均持续 healthy |

## 本地验收数据

Phase 4 创建了一个随机后缀、名称明确标记为 acceptance test 的临时设备，并写入一条错误日志、一条通用越界读数和一条诊断结果。载荷及结果均标记为测试数据，不代表真实硬件、实验或生产结果；随机令牌未输出或写入仓库。

## 已知问题与风险

1. 正式实验模板模型尚未建立，Phase 4 暂由诊断请求注入通用指标范围快照；后续应改为服务端加载并授权。
2. 诊断运行暂沿用设备令牌认证；学生与教师权限将在业务模型阶段补齐。
3. `VALUE_STUCK` 等可选规则未提前实现，避免越过核心三类验收范围。
4. AI Provider、ESP32/传感器型号和字段、知识库来源及生产参数仍未确定，接口和文档保持通用占位。
5. 新镜像已构建，但为遵守“不停止当前 Docker 容器”的要求，当前长期运行 backend/frontend 未替换；下次获准更新运行环境时再滚动到 0.4.0。

## 下一阶段

Phase 5 将基于 Phase 4 的结构化证据实现故障树、原因评分和分层提示。用户再次明确输入“继续下一阶段”前，不进入 Phase 5。
