# ESP32 + DHT11 首个实验固件

本实现面向内部实验，用户于2026-09-28确定首轮采购组合为 **ESP32-DevKitC V4（ESP32-WROOM-32E）+ 四针裸 DHT11**。开发框架固定为 PlatformIO、Espressif32 `7.0.1`、Arduino core `3.20017.x`，JSON 库固定为 ArduinoJson `7.4.2`。`platformio.ini` 中的版本锁定是可复现构建边界，不代表当前已完成硬件验收。

当前固件版本为 `0.2.5`；协议仍为 V1。选型决定与到货验证状态统一见[真实性看板](../../docs/project-truth-status.md)，用户报告硬件已具备，实物身份、接线与功能仍待核验。

## 已实现行为

- 按 Aosong DHT11 单总线时序发起真实读取，校验 40 位帧和 8 位校验和，并拒绝越界值。读取失败只生成 `DHT11_READ_FAILED` 日志，不会生成虚构温湿度。
- DHT11 返回前一次转换结果。上电后第一次有效帧只用于 priming；下一次有效帧才发布温度和湿度，并在 `metadata.measurement_semantics=previous_conversion` 中保留转换触发与读取完成的单调时间。
- 每个请求含唯一 `requestId`、本次启动内递增的 `sequenceNo`、`bootId`、`uptimeMs`、固件版本和 `isTestData`。设备时间未通过 NTP 校准时省略 `occurredAt`，服务端按既定规则记录 `server_fallback`。
- 采样间隔以驱动实际触发时间为准，成功或失败都至少间隔3秒；HTTP重试后重新读取单调时间，不补采错过的周期。启动首次触发前等待至少3秒，覆盖传感器仍供电的板卡复位。
- 运行时长、采样触发和读取完成使用 ESP-IDF `esp_timer_get_time()` 的 64 位单调时钟，不对已回绕的 `millis()` 仅作类型转换。
- 配好上传身份后，LittleFS 先保存一个冻结批次，再判断联网状态。会话 ID、请求体、记录数、重试次数和回执确认状态一起保存。缓存满时暂停新的传感器读取，恢复后重新 priming，不把暂停前转换当作新测量；这是单批次缓存，不保证断网期间连续采样。
- 写入必须达到完整长度且读回一致，才原子改名。挂载、读写、内容损坏或改名失败时停止采样和上传，保留文件，不自动格式化。首次使用没有文件系统时，需要负责人单独初始化；不能用自动格式化绕过错误。
- 成功响应必须是 200/201、请求 ID 相同、记录数相同且每条状态为 `accepted`。先持久化已确认状态再清理；清理失败只重试删除，即使重启或断网也不重新发送已确认批次。确认状态尚未落盘就断电的窗口仍可能重放原请求，由服务端幂等处理。
- 重试预算为每个冻结批次 3 次；预算用尽后暂停并保留数据。HTTPS 没有 CA 证书时拒绝发送；明文 HTTP 只有显式编译开关才能用于隔离测试，该开关不允许HTTPS跳过证书校验；无效协议和缺失CA不消耗发送预算，原请求保留。

## 接线与采购约束

`3.3V -> DHT11 VDD`，`GND -> GND`，`DATA -> GPIO4`，DATA 与 3.3V 之间外接 `4.7kΩ` 上拉。传感器线尽量保持短（首个实验建议不超过 20cm）。四针裸传感器的第三针 NC 不接。不要把 DHT11 当 I2C 设备，厂商 V1.3 要求请求间隔严格大于 2 秒；本项目最小请求间隔与配置周期均为 3 秒。

## 本地配置

复制 `include/secrets.example.h` 为未提交的 `include/secrets.h`，填入服务器地址、设备凭据和实验会话 ID。默认配置为空，因此固件仍可在无网络、无硬件时编译并以串口输出真实读取结果或失败日志；它不会输出模拟读数。

```bash
pio run -d firmware/esp32_dht11
pio run -d firmware/esp32_dht11 -t upload   # 只有接入真实开发板后执行
pio device monitor -d firmware/esp32_dht11
```

## 验证边界

源代码、协议 JSON、帧解码和持久化策略可在无硬件条件下编译/主机测试；GPIO 波形、传感器准确度、Wi-Fi、TLS、服务端真实回执仍需接入真实硬件和内部实验会话后实测。实测前保持 `XJ_IS_TEST_DATA=1`，不要把串口预览当作平台已接收。

来源登记在 `docs/sources.json`；需要重新取得被忽略的原始资料时运行
`python firmware/esp32_dht11/docs/fetch_sources.py`，脚本只访问登记过的官方 URL 并校验 SHA-256。
协议请求样例见 `docs/protocol-example.json`；运行 `python scripts/check_firmware_protocol.py`
会同时使用后端批次及逐记录校验。编译后运行 `python scripts/test_firmware_host.py`，使用实际
固件源码及 ArduinoJson，模拟文件、网络、重启和回执故障，并覆盖 2^31 和 2^32 毫秒两侧的时钟边界。
这些检查不等于实物连续运行数十天已经验收。

## 选定手册的数据约束

固件0.2.5按 Aosong V1.3_20170331（PDF第3—5页）解析：负温度符号位位于温度小数字节的最高位，小数有效值为0—9，湿度小数字节为0。超出该版本标称量程（温度−20—60℃、湿度5—95%RH）的帧作为range失败，不作为有效读数上传；不推断传感器损坏。采购版本不同须先复核手册与解码契约。

`python scripts/test_firmware_host.py` 编译真实解码函数，覆盖手册正负温度示例、零附近、量程边界、校验和/小数字节异常，以及生产批次序列化的负号保留；GPIO测试替身不证明物理时序正确。新来源关联见 DHT11 包 `metadata.content_registry`，原始附件清单仍在 `docs/sources.json`；身份hash核对与内容审阅、实测验收分开。

## 首次初始化与操作入口

完整操作与六类排查见[内部实验指南](../../docs/experiments/dht11-internal-lab.md)，到货时按[执行清单](../../docs/experiments/dht11-arrival-checklist.md)逐项记录。`platformio.ini`显式配置`board_build.filesystem = littlefs`；`pio run -d firmware/esp32_dht11 -t buildfs`只生成初始化镜像。仅对确认没有需保留记录的新设备，按指南核对端口后使用uploadfs；该操作替换文件系统，不可用于清除未决请求或试错。生产启动仍不自动格式化。实物烧录、挂载和掉电效果保持待验证。
