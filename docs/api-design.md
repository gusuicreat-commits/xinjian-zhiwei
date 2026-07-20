# 芯鉴知微 API 设计（Phase 5）

## 通用约定

- API 前缀：`/api/v1`。
- 请求和响应：JSON，时间戳必须为包含时区的 ISO 8601 字符串。
- 未声明字段：拒绝并返回 422，避免设备字段拼写错误被静默忽略。
- 测试数据：必须显式设置 `is_test_data: true`。
- 原始请求：入库到对应记录的 `raw_payload`，用于追溯；认证头不会写入原始载荷。

## 设备认证

日志、读数和心跳接口要求：

```text
X-Device-ID: <device_key>
X-Device-Token: <secret token>
```

状态接口从路径取得 `device_id`，只要求 `X-Device-Token`。数据库只保存 PBKDF2-SHA256 哈希；未知设备、停用设备或令牌不匹配统一返回 401，避免泄漏设备是否存在。

## 接口

### POST `/device/logs`

必填字段：`level`、`message`、`occurred_at`。可选字段：`event_code`、`sensor_snapshot`、`is_test_data`。`level` 仅接受 `debug`、`info`、`warning`、`error`、`critical`。

### POST `/device/readings`

必填字段：`sensor_type`、`metric_key`、有限数值 `value`、`observed_at`。可选字段：`unit`、`metadata`、`is_test_data`。字段是通用指标表达，不绑定硬件厂商或型号。

### POST `/device/heartbeat`

必填字段：`observed_at`。可选字段：`firmware_version`、`metadata`、`is_test_data`。服务端以接收时间更新 `devices.last_seen_at`，设备上报时间单独保留，避免设备时钟偏差影响在线判断。

### GET `/device/{device_id}/status`

返回 `online`、`offline` 或 `never_seen`。离线阈值由 `DEVICE_OFFLINE_AFTER_SECONDS` 配置，默认开发值为 90 秒。

### POST `/diagnosis/devices/{device_id}/run`

使用路径设备 ID 和 `X-Device-Token` 认证。请求包含 1 至 604800 秒的回看窗口，以及可选的通用实验模板快照 `template_id + metric_ranges`。响应返回持久化结果 ID、规则集版本、输入指纹、按优先级排序的命中规则及证据。

Phase 4 尚未建立实验模板和用户权限模型，模板快照是显式的临时接口边界，不表示设备端有权定义生产阈值。相关业务模型确定后应改为服务端加载模板。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用设备 ID 和设备令牌认证。根据已保存的诊断上下文运行 YAML 故障树并保存原因排序、证据、提示等级和提示文本。同一诊断结果与同一故障树存在唯一约束，重复调用返回已有历史，不重复增加失败次数。

### GET `/diagnosis/devices/{device_id}/guidance`

返回当前设备的提示历史，按创建时间倒序排列。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。当前用户与教师角色尚未建立，因此使用环境变量 `REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为临时、默认关闭的审阅边界；未配置返回 503，凭据错误返回 401。正式角色模型落地后必须替换该临时边界。

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 设备不存在、已停用或令牌无效 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 503 | 教师审阅凭据尚未配置，介入列表默认关闭 |

当前不提供学生、教师账号或知识库 API，也不提供公开设备注册接口。
