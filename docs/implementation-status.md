# 芯鉴知微实现状态

最后更新：2026-07-19（Phase 3）

## 总体状态

- 当前阶段：Phase 3 实现、单元测试和实际 API/PostgreSQL 场景验收全部完成。
- 下一阶段：Phase 4 尚未开始。
- Git：Phase 2 已提交为 `714b808 feat: complete phase 2 device ingestion`；Phase 3 变更尚未提交。
- 运行状态：PostgreSQL、backend、frontend 容器保持运行。

## Phase 3 实现情况

- [x] 创建独立 `simulator/` Python 包和虚拟环境配置。
- [x] 创建统一环境变量配置、HTTP 客户端、场景动作和循环 runner。
- [x] 实现 `normal`：心跳、测试日志和两个通用指标读数。
- [x] 实现 `read-failure`：心跳和读取失败日志，不发送伪造读数。
- [x] 实现 `offline`：首周期上传后停止所有请求。
- [x] 实现 `out-of-range`：两个可配置越界值及警告日志。
- [x] 实现 `value-stuck`：连续发送完全相同的可配置值。
- [x] 提供统一 CLI 及五个独立入口脚本。
- [x] 所有上传载荷强制设置 `is_test_data=true`。
- [x] API、设备 ID、令牌、字段、单位、数值、间隔和超时均通过环境变量配置。
- [x] 令牌不进入配置对象 `repr`、运行输出、示例文件或 Git。
- [x] 具体 ESP32、传感器型号及生产字段没有写死。

## 主要新增与修改文件

- 模拟器核心：`simulator/xinjian_simulator/`。
- 场景入口：`normal_device.py`、`sensor_read_failure.py`、`offline_device.py`、`out_of_range.py`、`value_stuck.py`。
- 配置与依赖：`simulator/pyproject.toml`、`simulator/.env.example`。
- 测试：`simulator/tests/`。
- 文档：`simulator/README.md`、`docs/simulator-design.md` 及根 README。
- 版本：后端、前端和模拟器统一为 `0.3.0`。

## 数据库迁移

无。Phase 3 复用 Phase 2 的设备采集表和 `20260719_0001`，没有修改数据库结构。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 模拟器 Ruff | `ruff check .` | 通过 |
| 模拟器格式 | `ruff format --check .` | 15 files formatted |
| 模拟器测试 | `pytest -W error` | 8 passed，0 warning |
| Python 3.9 语法 | `compileall` 使用独立缓存目录 | 通过 |
| normal | 实际 API + PostgreSQL | 心跳 1、日志 1、读数 2 |
| read-failure | 实际 API + PostgreSQL | 心跳 1、错误日志 1、读数 0 |
| out-of-range | 实际 API + PostgreSQL | 心跳 1、警告日志 1、读数 2 |
| value-stuck | 实际 API + PostgreSQL | 心跳/日志/读数各 4，distinct value = 1 |
| offline | 初始心跳后静默约 95 秒 | 状态接口返回 `offline` |
| 测试数据标记 | PostgreSQL `bool_and(is_test_data)` | 所有 Phase 3 场景均为 true |
| Phase 2 回归 | 后端 pytest | 12 passed |
| 前端回归 | ESLint、Prettier、Vitest、类型检查、构建 | 全部通过 |
| 浏览器 E2E | Chrome + 容器前端 | Phase 3 页面 1 passed |

## 本地验收数据

Phase 3 复用了 `phase2-acceptance-test-device`，并写入明确测试记录：心跳 8 条、读数 8 条，以及对应 `TEST_*` 日志。这些记录只用于开发验收，不代表真实设备或实验数据。

## 已知问题与风险

1. 模拟器使用同步 HTTP 和固定周期，尚未实现网络失败重试、抖动或并发设备；真实设备联调阶段再补充。
2. 离线场景需要真实等待后端阈值，默认开发配置为 90 秒。
3. Phase 4 尚未实现规则诊断，因此当前场景只产生稳定证据，不自动输出异常结论。
4. AI Provider、具体硬件、知识来源和生产参数继续保持占位与可配置状态。
5. Phase 3 变更尚未提交 Git。

## 下一阶段

Phase 4 将定义 `DiagnosisContext`、YAML 规则加载和确定性匹配，优先识别读取失败、设备离线和数值越界。用户再次明确输入“继续下一阶段”前，不进入 Phase 4。
