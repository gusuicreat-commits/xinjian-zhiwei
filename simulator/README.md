# Phase 3 设备模拟器

本目录只生成明确标记为 `is_test_data=true` 的测试数据，用于在没有真实硬件时验证设备 API。模拟器不绑定具体 ESP32、传感器型号、字段或生产配置。

## 安装

```bash
cd simulator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## 配置

所有运行参数通过环境变量注入。`XINJIAN_DEVICE_ID` 和 `XINJIAN_DEVICE_TOKEN` 必填；真实令牌只能保存在未提交的本地环境或密钥管理工具中。

```bash
export XINJIAN_API_BASE_URL=http://127.0.0.1:8000
export XINJIAN_DEVICE_ID=TODO_TEST_DEVICE_ID
export XINJIAN_DEVICE_TOKEN=TODO_LOCAL_SECRET
```

传感器类别、指标键、单位和场景数值都有 `XINJIAN_*` 配置入口，详见 `.env.example`。示例值仅为测试占位，不代表真实量程或采集结果。

## 场景

统一命令：

```bash
xinjian-simulator normal --iterations 1
xinjian-simulator read-failure --iterations 1
xinjian-simulator out-of-range --iterations 1
xinjian-simulator value-stuck --iterations 5 --interval-seconds 1
xinjian-simulator offline --iterations 3
```

也可运行对应脚本：`normal_device.py`、`sensor_read_failure.py`、`out_of_range.py`、`value_stuck.py` 和 `offline_device.py`。

- `normal`：持续发送心跳、日志和两个通用指标读数。
- `read-failure`：发送心跳和 `TEST_SENSOR_READ_FAILED` 测试日志，不伪造读数。
- `out-of-range`：发送心跳、测试警告和两个可配置越界值。
- `value-stuck`：连续发送相同的可配置值，为后续规则诊断提供稳定场景。
- `offline`：首个周期发送一次心跳和暂停通知，后续周期不再上传；超过后端离线阈值后状态变为 `offline`。

省略 `--iterations` 时持续运行，按 `Ctrl+C` 停止。离线场景的等待周期应覆盖后端 `DEVICE_OFFLINE_AFTER_SECONDS`。

## 测试

```bash
cd simulator
pytest
ruff check .
ruff format --check .
```
