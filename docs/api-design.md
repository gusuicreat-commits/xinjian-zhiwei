# 芯鉴知微 API 设计（Phase 2）

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

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 设备不存在、已停用或令牌无效 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |

Phase 2 不提供学生、教师、诊断或知识库 API，也不提供公开设备注册接口。
