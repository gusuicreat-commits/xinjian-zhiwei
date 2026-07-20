# 芯鉴知微设备上传协议（Phase 2）

## 设计边界

当前 ESP32 型号、传感器型号、接线、采样周期和厂商字段尚未确定。协议使用通用数据模型；设备适配层负责把具体硬件输出映射为标准字段，服务端不按厂商或型号写死分支。

## 认证与传输

- 传输：HTTP + JSON。
- 请求头：`Content-Type: application/json`、`X-Device-ID`、`X-Device-Token`。
- 令牌：由管理员通过 CLI 创建，设备私密配置保存；不得写入固件示例、日志或 Git。
- 时间：ISO 8601 且必须包含时区，建议设备使用 UTC。

## 通用载荷

日志：

```json
{
  "level": "error",
  "message": "TODO[待补充]: 设备日志",
  "event_code": "TODO[待补充]: 通用事件码",
  "occurred_at": "2026-01-01T00:00:00Z",
  "sensor_snapshot": {},
  "is_test_data": true
}
```

读数：

```json
{
  "sensor_type": "TODO[待补充]: 传感器类别",
  "metric_key": "TODO[待补充]: 指标键",
  "value": 0.0,
  "unit": "TODO[待补充]: 单位",
  "observed_at": "2026-01-01T00:00:00Z",
  "metadata": {},
  "is_test_data": true
}
```

心跳：

```json
{
  "observed_at": "2026-01-01T00:00:00Z",
  "firmware_version": "TODO[待补充]: 固件版本",
  "metadata": {},
  "is_test_data": true
}
```

示例均为协议占位内容，不代表真实设备、采集数据或生产参数。真实硬件确定后，应新增适配配置和协议测试，而不是更改通用字段语义。

Phase 3 的 `simulator/` 严格复用本协议。模拟器字段通过 `XINJIAN_*` 环境变量映射，所有上传强制设置 `is_test_data=true`；设计细节见 `docs/simulator-design.md`。
