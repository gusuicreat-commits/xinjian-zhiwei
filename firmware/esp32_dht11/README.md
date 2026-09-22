# ESP32 + DHT11 首个实验固件

本实现面向内部实验，目标采购组合为 **ESP32-DevKitC V4（ESP32-WROOM-32E）+ 四针裸 DHT11**。开发框架固定为 PlatformIO、Espressif32 `7.0.1`、Arduino core `3.20017.x`，JSON 库固定为 ArduinoJson `7.4.2`。`platformio.ini` 中的版本锁定是可复现构建边界，不代表当前已完成硬件验收。

## 已实现行为

- 按 Aosong DHT11 单总线时序发起真实读取，校验 40 位帧和 8 位校验和，并拒绝越界值。读取失败只生成 `DHT11_READ_FAILED` 日志，不会生成虚构温湿度。
- DHT11 返回前一次转换结果。上电后第一次有效帧只用于 priming；下一次有效帧才发布温度和湿度，并在 `metadata.measurement_semantics=previous_conversion` 中保留转换触发与读取完成的单调时间。
- 每个请求含唯一 `requestId`、本次启动内递增的 `sequenceNo`、`bootId`、`uptimeMs`、固件版本和 `isTestData`。设备时间未通过 NTP 校准时省略 `occurredAt`，服务端按既定规则记录 `server_fallback`。
- LittleFS 使用临时文件改名保存一个冻结中的待发送批次。会话 ID、请求体、记录数和重试次数一起保存；网络失败、重启或会话配置改变都不会改写或自动丢弃原请求。成功响应必须是 200/201、请求 ID 相同、记录数相同且每条状态为 `accepted`，才清除缓存。
- 重试预算为每个冻结批次 3 次；预算用尽后暂停并保留数据。HTTPS 没有 CA 证书时拒绝发送；明文 HTTP 只有显式编译开关才能用于隔离测试。

## 接线与采购约束

`3.3V -> DHT11 VDD`，`GND -> GND`，`DATA -> GPIO4`，DATA 与 3.3V 之间外接 `4.7kΩ` 上拉。传感器线尽量保持短（首个实验建议不超过 20cm）。四针裸传感器的第三针 NC 不接。不要把 DHT11 当 I2C 设备，也不要把采样间隔缩短到 2 秒以内。

## 本地配置

复制 `include/secrets.example.h` 为未提交的 `include/secrets.h`，填入服务器地址、设备凭据和实验会话 ID。默认配置为空，因此固件仍可在无网络、无硬件时编译并以串口输出真实读取结果或失败日志；它不会输出模拟读数。

```bash
pio run -d firmware/esp32_dht11
pio run -d firmware/esp32_dht11 -t upload   # 只有接入真实开发板后执行
pio device monitor -d firmware/esp32_dht11
```

## 验证边界

源代码、协议 JSON、帧解码和持久化策略可在无硬件条件下编译/主机测试；GPIO 波形、传感器准确度、Wi-Fi、TLS、服务端真实回执仍需购买硬件并接入内部实验会话后实测。实测前保持 `XJ_IS_TEST_DATA=1`，不要把串口预览当作平台已接收。

来源登记在 `docs/sources.json`；需要重新取得被忽略的原始资料时运行
`python firmware/esp32_dht11/docs/fetch_sources.py`，脚本只访问登记过的官方 URL 并校验 SHA-256。
协议请求样例见 `docs/protocol-example.json`，可直接用后端 `DeviceBatchIngestRequest` 校验。
