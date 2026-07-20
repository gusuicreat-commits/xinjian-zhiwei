# 芯鉴知微设备模拟器设计（Phase 3）

## 目标

在没有真实 ESP32 和传感器时，以可重复、可配置且明确标记的测试数据验证设备上传闭环。模拟器只负责产生输入，不提前实现 Phase 4 规则诊断。

## 结构

- `SimulationConfig`：从 `XINJIAN_*` 环境变量读取 API、设备凭据、通用字段、数值和间隔。
- `DeviceApiClient`：统一添加设备认证头，发送日志、读数和心跳；输出不包含令牌。
- `Scenario`：将每个周期转换为一组 `UploadAction`。
- `runner`：连续或按指定次数运行场景，支持 `Ctrl+C` 停止。
- 五个入口脚本：调用同一核心实现，不复制协议逻辑。

## 场景语义

| 场景 | 行为 | 可重复证据 |
| --- | --- | --- |
| normal | 心跳、正常测试日志、两个通用读数 | 三类数据持续入库 |
| read-failure | 心跳和读取失败日志，不发送读数 | `TEST_SENSOR_READ_FAILED` |
| offline | 首周期心跳，之后完全停止上传 | 超过阈值后状态为 `offline` |
| out-of-range | 两个可配置极值与警告日志 | `TEST_VALUE_OUT_OF_RANGE` |
| value-stuck | 每周期发送同一配置值 | 多条记录的 distinct value 为 1 |

## 安全边界

- 每个上传载荷都由公共构造器加入 `is_test_data=true`。
- 令牌只能从 `XINJIAN_DEVICE_TOKEN` 读取，配置对象的 `repr` 不显示令牌。
- 默认字段使用 `generic-test-sensor`、`test_metric_*` 和 `test-unit`，不代表真实硬件或量程。
- 模拟器日志仅打印场景、动作和服务端记录 ID，不打印认证头或完整载荷。
- 离线场景通过真实停止心跳实现，不修改数据库时间或伪造状态。

## 非目标

Phase 3 不实现设备自动注册、规则判断、故障树、RAG、AI 或真实硬件协议。具体 ESP32、传感器型号和字段确定后，应通过配置映射接入。
