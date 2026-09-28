# 芯鉴知微设备协议 V1

## 状态与边界

代码核对日期：2026-09-27。本文说明当前服务端传输契约，不是实物验收结果。仓库已有
ESP32-DevKitC V4/WROOM-32E、裸DHT11、GPIO4、3.3V和3秒采样的候选配置，以及0.2.2固件；
具体构建、接线来源和待实测范围见[固件说明](../firmware/esp32_dht11/README.md)。
通用协议不把这些候选参数变成所有设备的固定要求。下面的通用样例及模拟器输入为
`isTestData=true`合成数据，真实字段应与锁定实验包和设备适配一致。

## 认证与端点

- 端点：`POST /api/v1/device/ingest`
- 请求头：`Content-Type: application/json`、`X-Device-ID`、`X-Device-Token`；正式会话数据还应携带原始 `X-Experiment-Session-ID`，缺省归属规则见下节
- 传输：HTTP JSON；生产环境必须在受控网络中使用 HTTPS
- 兼容端点：`/device/logs`、`/device/readings`、`/device/heartbeat` 继续可用
- 令牌：服务端只保存 PBKDF2-SHA256 哈希；令牌不得进入 Git、日志或示例

## 会话归属与学生可见性

三类遥测记录保存可空的 `experiment_session_id`，不会根据设备今天绑定谁回填历史数据。
当前接收逻辑由 [设备路由](../backend/app/api/v1/routes/device.py) 与
[data_scope.py](../backend/app/services/data_scope.py) 共同执行：

- 显式会话头必须对应已认证设备，并有可解析的原学生、任务关联；越界拒绝。为接收迟到数据，
  摄入可以验证已结束的原会话，这不等于允许该学生继续操作实验。
- 正式会话的记录时间须落在保存的使用区间内；区间外仍可接收入库，但会话关联保持空，
  不改挂当前学生。时间先按下述时间质量规则处理，设备自行声明时间不是物理真实性认证。
- 无会话头时，仅兼容唯一有效且学生、班级、任务、会话均有测试标记的演示会话，并检查
  记录不早于会话开始。正式数据即使存在唯一活动会话，也不由此自动获得归属。
- 没有可用会话或有多个活动会话时，摄入保留空关联；这不同于学生仪表盘的空态/409规则。
- 回执 `accepted` 只证明该记录已保存，不能证明它已通过学生可见性检查。无法确定归属的记录
  保留供受权管理检查，不向学生展示，不自动补造来源。

全部遥测写入在等待设备锁后再次校验凭据和显式会话。同一请求重放原记录，不因设备交接改写既有归属。

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
`sentAt` 和 `occurredAt` 建议使用带时区的 ISO 8601 UTC 时间；`uptimeMs` 为可选非负JSON整数，完整范围见容量章节。
批次至少一条、默认最多 100 条，默认请求体最多 262144 字节，单设备默认每分钟最多
120 次遥测写入（批次与三个旧逐条端点合计）。这些是可通过后端环境变量调整的部署保护参数，
不是硬件采样参数；逐条请求每次成功写入计一次，原批次回执重放不重复计次。

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

同设备的四个写入端点在设备行锁下重新鉴权并检查合计额度，抢最后一个额度失败返回 429；
批次的查重、序号检查、业务记录与回执同事务提交。不同设备的锁独立。会话命令沿用
actor→device 锁顺序，摄入只锁 device，不反向索取 actor 锁。
所有入口解析 JSON 前按实际流式字节限制大小，不信任 Content-Length；超限返回 413，
未解析身份时错误中的 request_id 为 null。

## 原子性与重试

批次采用全有或全无策略：业务记录校验失败返回 `422 INGESTION_RECORD_INVALID`，不创建成功回执，也不保存部分日志、读数或心跳。外层请求/字段类型不合法可能先被FastAPI拒绝，仍为422，但错误体是框架校验列表，不能把所有422都当成同一个业务错误码。

模拟器仅对网络错误、超时、408、425、429 和 5xx 重试；每次重试复用完全相同的
`requestId` 和请求体，默认最多 3 次，延迟为 0.25 秒、0.5 秒的指数退避。其他 4xx
被视为不可重试的协议或认证错误。

## 稳定错误

批次业务层的协议错误位于 FastAPI `detail` 字段中，结构如下；这不是所有依赖/Schema错误的统一格式：

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
`INGESTION_BODY_TOO_LARGE` 和 `INGESTION_RATE_LIMITED`。锁内重验失败还可能返回 `INVALID_DEVICE_TOKEN` 或 `INGESTION_SESSION_INVALID`。

认证依赖使用 `detail.code`（例如缺凭据422、无效凭据401）；会话依赖可能返回字符串detail；请求Schema失败使用FastAPI校验列表。客户端先判断HTTP状态，再解析对应结构，不假定任何失败都有 `detail.error_code`。等待后的令牌失效同样可以是401，但来自协议错误结构。

## 兼容与演进

- `protocolVersion=1.0` 和 `schemaVersion=1` 是当前唯一支持组合。
- 新增可选字段时保持旧客户端可用；破坏性字段语义变更必须增加 schema 版本。
- 真实硬件接入时应新增设备适配配置和契约测试，不改变通用字段含义。
- 新设备的固件、GPIO、字段、单位、采样与批量策略须明确登记和校验；当前DHT11候选固件已有代码契约，实物表现仍待验证。

## 记录语义与硬件事实边界

DHT11 日志的组件标识可放在 `payload.sensor_snapshot.component_id`，例如 `dht11`；接口标识可放在同层 interface_id，未填时按组件的已声明接口解析。错误码映射由版本化实验包控制；当前DHT11固件代码会输出 `DHT11_READ_FAILED`，包映射为 `sensor.read_failed`。代码约定不能证明每种真实故障都会输出该错误，更不能凭它确认唯一根因。

LED reading 的 metric_key 使用 level（旧值，来源未知）、gpio_command_level（命令）、gpio_actual_level（电气观测）或 led_physically_on（光学观测）。后三者分别要求 metadata.measurement_source 为 command / electrical_measurement / optical_observation；缺失或不匹配时标准观测 status=unknown。命令与电气观测还需 metadata.command_id 相同，且满足包配置的响应窗口才参与比较。数据契约支持这些语义不代表当前设备已经实现电气/光学检测，真实来源仍 pending_hardware。

不接受把固件变量 level=1 当作 LED 已亮的证明；不得伪造光学来源声明。所有测试报文保持测试标记。

## 序号与运行时长容量

`sequenceNo` 和可选的 `uptimeMs` 接受 JSON 整数，范围为 `0..9007199254740991`
（`2^53-1`，与浏览器安全整数范围一致）。不接受字符串、布尔值、小数、负值或超上限值；
无效值在整批写入前返回 `422`。`uptimeMs` 缺失或为 `null` 仍表示未提供，不补零。

请求记录、心跳、日志、读数四张表均以 `BIGINT` 保存这两个字段。旧字段名、毫秒单位、
请求身份、载荷摘要和去重规则不变，不截断、不取余、不通过归零绕过容量限制。

迁移 `0032` 仅扩大这八个字段，历史值及关联原样保留。存在超过 32 位范围的数据时，
降级迁移会明确拒绝；不能为了回退而截断、删除新数据。实际环境升级需评估 ALTER TABLE
的锁与耗时并先备份，本地测试通过不代表运行数据库已经升级。
