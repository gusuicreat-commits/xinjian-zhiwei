# 设备模拟器

本目录只生成明确标记为 `is_test_data=true` 的测试数据，用于在没有真实硬件时验证设备 API。模拟器不绑定具体 ESP32、传感器型号、字段或生产配置。

场景每个周期使用设备协议 V1 批量上传当次日志、读数和心跳。批次携带稳定
`requestId`、启动 ID 和递增序列号；网络错误、超时、408/425/429/5xx 会复用同一请求
执行有限指数退避，协议或认证类 4xx 不重试。旧单条客户端方法只为兼容测试保留。

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
协议版本、Schema 版本、最大重试次数和退避基数同样可配置；默认值只用于协议验收。

## 场景

版本化场景命令：

```bash
xinjian-simulator list
xinjian-simulator validate
xinjian-simulator run normal --iterations 1
xinjian-simulator run recovery --iterations 2
xinjian-simulator report <test-run-uuid>
xinjian-simulator replay <test-run-uuid>
xinjian-simulator cleanup <test-run-uuid>
```

也可运行对应脚本：`normal_device.py`、`sensor_read_failure.py`、`out_of_range.py`、`value_stuck.py` 和 `offline_device.py`。

- `normal`：持续发送心跳、日志和两个通用指标读数。
- `read-failure`：发送心跳和 `TEST_SENSOR_READ_FAILED` 测试日志，不伪造读数。
- `out-of-range`：发送心跳、测试警告和两个可配置越界值。
- `value-stuck`：连续发送相同的可配置值，为后续规则诊断提供稳定场景。
- `offline`：首个周期发送一次心跳和暂停通知，后续周期不再上传；超过后端离线阈值后状态变为 `offline`。
- `intermittent-failure`：正常、失败、恢复的确定性时间线，并包含测试延迟。
- `recovery`：读取失败后恢复正常读数。
- `multi-device-classroom`：要求显式提供三组测试设备凭据，不自动创建虚构设备。

场景规范位于 `scenario_specs/`，运行报告位于 Git 忽略的 `.simulator-runs/`。每个运行
都通过 UUID 标记服务端批次，可定向清理且不会影响其他数据。统一测试边界和验收方式见
`../docs/evaluation.md`。

## 测试

```bash
cd simulator
pytest
ruff check .
ruff format --check .
```
