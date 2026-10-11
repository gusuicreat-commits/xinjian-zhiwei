# ESP32-S3 + SHT31 内部实验指南

日期：2026-10-11。对象：项目成员在隔离测试环境中完成 SHT31 实物的内部技术验收。硬件基线、证据状态与待确认项以[真实性看板](../project-truth-status.md)为准；本文只给顺序、命令和记录要求，不代表教师、课程或精度验收。

## 1. 范围与门槛

板子运行同学写的现行程序（`firmware/esp32s3_sht31`，原样入库），只打印串口；电脑端串口桥 `bridge/` 负责上传。五道门槛都要留原始证据，才能写“内部技术功能验收通过”。

| 门槛 | 要证明什么 | 关键证据 | 2026-10-11 状态 |
| --- | --- | --- | --- |
| T0 软件就绪 | 程序可构建，桥测试通过 | 构建日志、`build/esp32s3_sht31.bin` SHA-256、测试输出 | 完成：ESP-IDF v5.3.2 构建通过；桥测试与协议检查通过 |
| T1 板上本地采集 | 真机读到温湿度或如实报错 | 串口日志、接线照片、模块型号 | 部分：已持续读数；缺接线照片与逐项核对 |
| T2 平台接入 | 记录入库并归属到会话 | requestId、回执、入库记录、会话 ID | 部分：隔离平台入库一致；会话归属未做 |
| T3 异常与恢复 | 拔线触发异常，恢复后能重新判断 | 前后诊断 ID、证据 ID、串口与桥日志 | 待做 |
| T4 平台中断与重连 | 后端中断时不丢批，恢复后不重复入库 | 桥退出汇总、ingestion_requests 记录 | 待做 |

## 2. 器材与断电接线

器材：ESP32-S3-N16R8 开发板、SHT31 模块、面包板与杜邦线、能传数据的 USB 线。接线必须在断电状态下完成并拍照登记。

| SHT31 引脚 | ESP32-S3 | 说明 |
| --- | --- | --- |
| VIN / VDD | 3V3 | 手册范围 2.15–5.5 V，项目用 3.3 V |
| GND | GND | 共地 |
| SDA | GPIO8 | 程序 `I2C_SDA_GPIO 8` |
| SCL | GPIO9 | 程序 `I2C_SCL_GPIO 9` |
| ADDR（如有） | 悬空或 GND | 地址 0x44；接 3V3 为 0x45，需同步改程序 |

程序只启用 ESP32 内部上拉；手册建议 SDA、SCL 外接上拉（如 10 kΩ）。先看模块是否自带上拉电阻并记录。线长建议 20 cm 以内。N16R8 的 GPIO35–37 被 PSRAM 占用，不能外接。

## 3. 构建、烧录与串口确认（T0、T1）

1. 构建：在 `firmware/esp32s3_sht31` 执行 `idf.py set-target esp32s3` 与 `idf.py build`（ESP-IDF v5.3.2，或官方镜像 `espressif/idf:v5.3.2`）。记录 bin 的 SHA-256。
2. 板上已有现行程序时不必重烧；需要时 `idf.py -p <串口> flash`。macOS 上串口为 `/dev/cu.usbmodem*`。
3. 用 COMTool 等串口助手以 115200 观察，**不要勾选 DTR、RTS**。应每秒左右出现一行 `温度: … ℃ | 湿度: … %RH`；启动时有 `SHT31 传感器启动!`。
4. 串口出现 `waiting for download` 表示板子被复位进下载模式，程序没在运行；拔插 USB 恢复。
5. 保存至少 1 分钟串口日志，登记模块型号、接线照片和是否有外部上拉。

## 4. 平台准备与接入（T2）

平台必须是隔离测试环境，绝不连接正在使用的业务库。按[内部测试环境准备](internal-lab-preparation.md)迁移数据库、创建测试管理员、导入并测试发布 `sht31_temperature_humidity` 包，用 `prepare_internal_experiment` 以 `--device-kind hardware` 准备实物身份，再由学生账号开始会话，记录会话 ID。

串口桥只能在串口助手关闭后运行（两者不能同时占用串口）：

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/pip install -e 'bridge[dev]'
bridge/.venv/bin/xinjian-serial-bridge --port /dev/cu.usbmodemXXXX --dry-run   # 先不联网
read -rs XJ_DEVICE_TOKEN; export XJ_DEVICE_TOKEN
bridge/.venv/bin/xinjian-serial-bridge --port /dev/cu.usbmodemXXXX \
  --base-url http://127.0.0.1:18080 --device-id <device_key> --session-id <会话ID>
```

通过条件：末行串口读数与平台入库值一致；每个 requestId 都有 `accepted` 回执；记录挂到该会话；Ctrl-C 后桥汇总的“未发送、丢弃”均为 0。只有服务端有记录才算到达，桥回显不等于已入库。

## 5. 异常与恢复（T3）

1. 正常运行至少 2 分钟，确认学生端有读数、无读取失败异常。
2. 断电，只拔掉 SDA（另做一轮只拔 SCL），上电。串口应出现失败行，桥上传 `SHT31_READ_FAILED`。
3. 窗口内累计失败达到包规则阈值后，学生端应出现读取失败异常和排查步骤；候选原因保持“待验证”，不能写成已确认根因。
4. 断电恢复接线，上电取得新读数后，在学生端点“检查当前数据”，记录前后诊断 ID 与证据 ID。

## 6. 平台中断与重连（T4）

桥运行中停掉后端约 1 分钟再恢复。期间串口应继续回显，桥按顺序排队（上限 20 批）。恢复后核对排队批次全部入库且每个 requestId 只入库一次；退出汇总无丢弃。重启板子（拔插 USB）时，桥应收到启动行并换新 bootId。

## 7. 排查卡

| 现象 | 先查什么 |
| --- | --- |
| 构建失败 | ESP-IDF 是否为 5.x（已验证 5.3.2）、是否先 `set-target esp32s3` |
| 没有串口输出或 `waiting for download` | DTR/RTS 是否被勾选、串口是否被占用；拔插 USB |
| 一直是读取失败 | 断电核对供电、共地、SDA/SCL 是否接反、ADDR 电平、上拉与线长 |
| 读数偶尔离谱 | 程序不校验 CRC：先查接触与干扰，再用另一只传感器对照 |
| 串口有读数，平台没有 | 桥是否运行、设备 ID 与令牌（401/403 桥会停止）、后端地址、汇总里的丢弃数 |
| 数据已到，诊断仍为未知 | 证据是否够触发规则、记录是否归属到会话 |

## 8. 记录模板

```text
日期/操作人：
板子与模块型号（照片编号）：            外部上拉：有 / 无 / 未知
程序版本与 bin SHA-256：                ESP-IDF 版本：
串口设备名：                            桥版本（git 提交）：
测试平台地址与数据库（确认非业务库）：
设备 ID / 会话 ID / 包版本与 hash：
T1 串口日志文件：                        T2 requestId 与回执：
T3 断开的线与时间、失败行数、诊断 ID（前/后）：
T4 中断起止时间、桥汇总（sent/unsent/discarded）：
未解决问题：
```

## 9. 来源

官方资料保存在被 Git 忽略的 `data/knowledge/raw/esp32s3-sht31/`，登记与校验见 `firmware/esp32s3_sht31/docs/sources.json`：Sensirion SHT3x-DIS 数据手册 Version 7（2022-12）、ESP32-S3-DevKitC-1 v1.1 用户指南、ESP32-S3-WROOM-1 与 ESP32-S3 数据手册。DHT11 时期的施工方案、内部指南与到货清单已删除，见[删除索引](../archive/README.md)。
