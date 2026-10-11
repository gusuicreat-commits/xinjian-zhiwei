# ESP32-S3 + SHT31 现行固件

这是用户提供的 ESP-IDF 现行程序的可构建工程。`main/main.c` 保持原样，板子只通过 USB 串口输出数据；电脑端由仓库内的 [`bridge/`](../../bridge/) 负责按设备协议 V1 上传，固件本身没有 Wi-Fi 和令牌。

## 硬件与接线

| SHT31 | ESP32-S3-N16R8 | 说明 |
| --- | --- | --- |
| VCC | 3.3V | SHT31 供电范围允许 3.3V |
| GND | GND | 共地 |
| SDA | GPIO8 | I²C SDA |
| SCL | GPIO9 | I²C SCL |
| ADDR | GND 或低 | 地址 `0x44`（当前源码） |
| ADDR | 3.3V 或高 | 地址 `0x45`，需要把源码中的 `SHT31_ADDR` 改为 `0x45` |

I²C 速率是 100 kHz，程序启用了 ESP32 内部上拉。SHT31 数据手册建议仍使用外接上拉（例如 SDA/SCL 各 10 kΩ），实际接线应以所用模块和供电为准。ESP32-S3-N16R8 的 Octal PSRAM 会占用 GPIO35/36/37；本程序使用的 GPIO8/9 可用，且没有启用 PSRAM 配置。

## 构建、烧录和监视

在已安装并启用 ESP-IDF 的终端中执行：

```bash
idf.py set-target esp32s3
idf.py build
idf.py flash
idf.py monitor
```

也可以一次执行：

```bash
idf.py set-target esp32s3 build flash monitor
```

现行 `main.c` 使用旧版 `driver/i2c.h` API，按 ESP-IDF 5.x 构建；较新的 IDF 版本可能给出弃用警告。已验证的 IDF 版本为 v5.3.2：总控使用官方 Docker 镜像 `espressif/idf:v5.3.2` 为 esp32s3 构建成功，app 大小为 `0x37960` 字节；本轮没有复跑该构建。

串口为 115200 8N1。电脑端桥打开串口时会主动保持 DTR/RTS 关闭，避免原生 USB 串口被复位；COMTool 与桥不能同时占用同一个串口。

## 串口输出契约

每行 UTF-8、行尾为 `\n`，桥只严格识别以下三类文本（允许首尾空白和 `\r\n`）：

```text
SHT31 传感器启动!
温度: 26.56 ℃ | 湿度: 40.80 %RH
读取失败！检查接线或者把地址改成0x45
```

温度数值可能为负。ESP-ROM/ESP-IDF 启动日志、断开时的半行乱码和其他文本不属于设备数据，桥会计数并写入 stderr，不会上传。

## 已知限制

- 不校验 SHT31 返回数据的 CRC。
- I²C 写命令的返回值被现行程序忽略；读操作失败才输出“读取失败”。
- 只依赖 ESP32 内部上拉；数据手册建议根据总线和模块增加外接上拉。
- 现行程序没有固件版本号、设备时间、Wi-Fi 或令牌；桥使用登记版本 `esp32s3-sht31-1.0.0`，并以电脑收到串口行的 UTC 时间作为观测时间。
- 以上限制是现行程序的事实记录，本任务不修改 `main/main.c`。
