# 芯鉴知微设备协议 V1

## 状态与边界

设备协议 V1 已在无真实硬件条件下完成服务端、模拟器和自动化测试。当前 ESP32
型号、传感器型号、GPIO、电压、接线、采样频率和正式指标字段仍待用户确认；协议只定义
通用传输语义，不把任何厂商、型号或生产参数写死。仓库中的协议样例和模拟器请求均为
`isTestData=true` 的合成测试数据。

## 认证与端点

- 端点：`POST /api/v1/device/ingest`
- 请求头：`Content-Type: application/json`、`X-Device-ID`、`X-Device-Token`
- 传输：HTTP JSON；生产环境必须在受控网络中使用 HTTPS
- 兼容端点：`/device/logs`、`/device/readings`、`/device/heartbeat` 继续可用
- 令牌：服务端只保存 PBKDF2-SHA256 哈希；令牌不得进入 Git、日志或示例

## 请求结构

```json
{
  "protocolVersion": "1.0",
  "schemaVersion": "1",
  "requestId": "123e4567-e89b-12d3-a456-426614174000",
  "bootId": "synthetic-boot-id",
  "sequenceNo": 10,
  "sentAt": "2026-07-27T08:00:00Z",
  "uptimeMs": 12345,
  "firmwareVersion": "TODO[待确认]: 正式固件版本",
  "isTestData": true,
  "records": [
    {
      "type": "heartbeat",
      "occurredAt": "2026-07-27T08:00:00Z",
      "payload": {
        "metadata": {
          "source": "synthetic-example"
        }
      }
    },
    {
      "type": "reading",
      "occurredAt": "2026-07-27T08:00:01Z",
      "payload": {
        "sensor_type": "TODO[待确认]: 通用传感器类别",
        "metric_key": "TODO[待确认]: 指标键",
        "value": 0,
        "unit": "TODO[待确认]: 单位",
        "metadata": {}
      }
    },
    {
      "type": "log",
      "occurredAt": "2026-07-27T08:00:02Z",
      "payload": {
        "level": "error",
        "message": "synthetic example log",
        "event_code": "TODO[待确认]: 正式错误码",
        "sensor_snapshot": {}
      }
    }
  ]
}
```

`requestId` 必须是 UUID。`bootId` 标识一次设备启动，`sequenceNo` 在同一启动中单调递增。
`sentAt` 和 `occurredAt` 建议使用带时区的 ISO 8601 UTC 时间；`uptimeMs` 为可选非负数。
批次至少一条、默认最多 100 条，默认请求体最多 262144 字节，单设备默认每分钟最多
120 个新请求。这些都是部署保护参数，不是硬件采样参数，可通过后端环境变量调整。

## 响应结构

```json
{
  "requestId": "123e4567-e89b-12d3-a456-426614174000",
  "deviceId": "synthetic-device",
  "acceptedAt": "2026-07-27T08:00:03Z",
  "idempotentReplay": false,
  "retryable": false,
  "records": [
    {
      "index": 0,
      "type": "heartbeat",
      "id": "stored-record-uuid",
      "status": "accepted",
      "timeQuality": "device_reported"
    }
  ]
}
```

## 幂等、乱序与时间语义

- 幂等键是数据库内部设备 ID 与 `requestId` 的组合。
- 服务端保存规范化请求的 SHA-256。相同请求重放返回原结果并设置
  `idempotentReplay=true`，不会重复写记录。
- 相同 `requestId` 携带不同载荷返回 `409 INGESTION_REQUEST_CONFLICT`。
- 同一设备、`bootId`、`sequenceNo` 被另一个请求占用时返回
  `409 INGESTION_SEQUENCE_CONFLICT`。
- 乱序批次仍保存历史，但较小的 `sequenceNo` 不会回退 `devices.last_seen_at` 或
  `devices.firmware_version`。
- 服务端统一保存 `server_received_at`。缺失、无法解析、无时区、早于 2020 年或明显在
  未来的设备时间使用服务器接收时间，并标记 `timeQuality=server_fallback`。
- 在线状态以服务端接收时间计算，不信任设备时钟。

## 原子性与重试

批次采用全有或全无策略：任一记录结构或业务字段无效，整个批次返回
`422 INGESTION_RECORD_INVALID`，不创建请求记录，也不保存部分日志、读数或心跳。

模拟器仅对网络错误、超时、408、425、429 和 5xx 重试；每次重试复用完全相同的
`requestId` 和请求体，默认最多 3 次，延迟为 0.25 秒、0.5 秒的指数退避。其他 4xx
被视为不可重试的协议或认证错误。

## 稳定错误

新端点的业务错误位于 FastAPI `detail` 字段中，并包含：

```json
{
  "detail": {
    "error_code": "INGESTION_RECORD_INVALID",
    "message": "batch record validation failed; no records were stored",
    "request_id": "request UUID",
    "details": {},
    "retryable": false
  }
}
```

稳定错误码包括 `UNSUPPORTED_PROTOCOL_VERSION`、`UNSUPPORTED_SCHEMA_VERSION`、
`INGESTION_REQUEST_CONFLICT`、`INGESTION_SEQUENCE_CONFLICT`、
`INGESTION_RECORD_INVALID`、`INGESTION_BATCH_TOO_LARGE`、
`INGESTION_BODY_TOO_LARGE` 和 `INGESTION_RATE_LIMITED`。

## 兼容与演进

- `protocolVersion=1.0` 和 `schemaVersion=1` 是当前唯一支持组合。
- 新增可选字段时保持旧客户端可用；破坏性字段语义变更必须增加 schema 版本。
- 真实硬件接入时应新增设备适配配置和契约测试，不改变通用字段含义。
- 正式固件、GPIO、传感器字段、单位、采样/批量策略和错误码仍为待确认输入。

## 实验包 2.0.1 的证据语义补充（2026-09-09）

DHT11 日志的组件标识可放在 `payload.sensor_snapshot.component_id`，例如 `dht11`；接口标识可放在同层 interface_id，未填时按组件的已声明接口解析。错误码映射仍由版本化实验包控制，当前错误码为未验证示例，不宣称等于真实驱动输出。

LED reading 的 metric_key 使用 level（旧值，来源未知）、gpio_command_level（命令）、gpio_actual_level（电气观测）或 led_physically_on（光学观测）。后三者分别要求 metadata.measurement_source 为 command / electrical_measurement / optical_observation；缺失或不匹配时标准观测 status=unknown。命令与电气观测还需 metadata.command_id 相同，且满足包配置的响应窗口才参与比较。数据契约支持这些语义不代表当前设备已经实现电气/光学检测，真实来源仍 pending_hardware。

不接受把固件变量 level=1 当作 LED 已亮的证明；不得伪造光学来源声明。所有测试报文保持测试标记。
