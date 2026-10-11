# ESP32-S3 SHT31 串口桥

串口桥读取现行 ESP32-S3 + SHT31 固件的一行输出，把可识别的温湿度和读取失败转换为设备协议 V1 批次，发送到 `POST /api/v1/device/ingest`。令牌只从环境变量 `XJ_DEVICE_TOKEN` 读取。

## 安装

```bash
cd bridge
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

`.venv/` 已在 Git 忽略规则中。开发检查：

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

## 运行

实时读取（本机板子示例）：

```bash
# 按回车后输入令牌，再按回车；输入不回显，也不写进命令历史
read -rs XJ_DEVICE_TOKEN
export XJ_DEVICE_TOKEN
bridge/.venv/bin/xinjian-serial-bridge \
  --port /dev/cu.usbmodem1201 --baud 115200 \
  --base-url http://localhost:8000 --device-id YOUR_DEVICE_ID
```

回放保存的串口文本：

```bash
bridge/.venv/bin/xinjian-serial-bridge --replay serial.txt \
  --base-url http://localhost:8000 --device-id YOUR_DEVICE_ID
```

离线查看将发送的 JSON（不读取令牌、不联网）：

```bash
bridge/.venv/bin/xinjian-serial-bridge --replay serial.txt --dry-run
```

实时模式会把收到的原始行原样回显到终端。桥打开串口后先释放 RTS、再释放 DTR，关闭和重连前也使用同一顺序，因此不会主动复位正在运行的 ESP32-S3 程序。`--reconnect` 可在串口断开后持续重试。

电脑上的串口只能由一个程序独占。运行桥时不要同时用 COMTool 打开同一 `/dev/cu.usbmodem*`，否则其中一个程序可能无法打开、读不到完整行，或在双方切换控制线时干扰串口状态。若串口出现 `waiting for download`，说明板子误入了下载模式；拔掉再插回 USB 即可恢复运行。

## 映射与时间

- 温湿度行产生两条 `reading`：`SHT31/temperature/°C` 和 `SHT31/humidity/%RH`。
- 失败行产生一条 `log`：`level=error`、`event_code=SHT31_READ_FAILED`，消息为原行文本。
- 启动行产生 `SHT31_BOOT` 信息日志，并换新 `bootId`；同一 boot 内批次 `sequenceNo` 从 0 递增。
- 每批默认最多 50 条记录或等待 5 秒，服务端限制以内。批次重试复用同一 `requestId`。
- 实时模式的记录带 `occurredAt`（电脑收到行的 UTC 毫秒时间，尾部 `Z`），metadata/sensor_snapshot 带 `time_source=host_serial_receive` 和 `source=serial_bridge`。
- 回放模式不伪造时间，省略 `occurredAt`，metadata/sensor_snapshot 使用 `time_source=replay_unknown`。
- 心跳只在自上次心跳以来收到过可识别行时随批次发出；串口静默不会补心跳，也不会补读数。
- ESP-ROM/ESP-IDF 日志和乱码只计数并输出 stderr，不上传。实时串口的字节块先累积到换行（包括超时返回的半行、被切开的 UTF-8 字符）；断开或退出时残留半行丢弃并计数，不跨重连拼接。

默认 `isTestData=true`，可用 `--no-is-test-data` 显式关闭。批量上传失败时内存等待队列最多保留 20 批（另有 1 批正在发送）；超限会明确报告丢弃的批数。服务端成功只接受 HTTP 200/201，并核对回执 `requestId` 与记录数。

实时模式用独立发送线程上传，串口读取、原样回显和批次生成不会被服务端阻塞；队列按生成顺序发送。408、429、5xx 和网络错误会有界重试后继续排队，401/403 会报告凭据错误并以非零状态退出，其他 4xx 会丢弃当前批次并计数。Ctrl-C、SIGTERM、串口断开退出或回放结束时，对尚未完成的批次各做一次最后发送尝试，共享 15 秒期限。到期停止开启新请求，并在 stderr 汇总 `sent`（收到合法回执）、`unsent`（尚未确认成功，包括在途请求）、`discarded`（队列超限或永久拒绝）批次数。401/403 后不再收尾上传，未确认的批次计入 `unsent`。

队列只在内存中，退出后不会保留未发送批次。超时的在途请求可能已被服务端接收，桥无法确认这一点，因此归入 `unsent`。离线 `--dry-run` 的 `sent` 仅表示已输出的 JSON 批次数；实时 `--dry-run` 的串口回显放在 stderr，stdout 只包含 JSON。

桥的测试只需本包 dev 依赖。后端协议校验由后端环境独立执行：

```bash
PYTHONPATH=backend:bridge backend/.venv/bin/python scripts/check_serial_bridge_protocol.py
```
