# 设备模拟器

核对日期：2026-09-27。本目录生成明确标记为 `is_test_data=true` 的测试数据，用于验证设备 API 和合成流程。默认字段是通用占位，不代表某款传感器或实际硬件；结果边界见 [测试与评测](../docs/evaluation.md)。

## 安装与配置

从仓库根目录：

```bash
cd simulator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

运行参数直接读取环境变量，不自动加载 `.env`。设备 ID/令牌必填，只使用已创建的测试设备；测试身份创建见 [演示手册](../docs/demo-runbook.md)。

```bash
export XINJIAN_API_BASE_URL=http://127.0.0.1:8000
export XINJIAN_DEVICE_ID=TODO_TEST_DEVICE_ID
export XINJIAN_DEVICE_TOKEN=TODO_LOCAL_SECRET
```

配置项见 [.env.example](.env.example) 与 [config.py](xinjian_simulator/config.py)，包括字段、单位、值、间隔、协议版本和重试。默认值仅用于软件测试。匹配具体实验包前需核对其证据映射；只把指标名改成 temperature 不构成硬件验证。

间隔、超时和重试延迟必须是有限正数，拒绝 NaN、无穷及非正值；重试次数必须是正整数。

当前客户端不发送实验会话 ID，依赖服务端允许的唯一有效会话兼容归属。无明确归属的记录不保证学生可见，不能以当前设备绑定推断历史数据。需要验证精确会话绑定、设备交接或跨会话重放时，使用后端相应专项测试/真实联调，而不是把模拟器的兼容上传当作全部覆盖。

## 版本化场景

```bash
xinjian-simulator list
xinjian-simulator validate
xinjian-simulator run normal --iterations 1
xinjian-simulator run recovery --iterations 2
```

`list` / `validate` 不上传数据。`run` 未指定 iterations 时执行场景定义的轮数；指定更多轮时**循环整个场景**。多设备场景按设备顺序执行，不是同时并发压测。

| 场景 | 实际行为 |
| --- | --- |
| `normal` | 心跳、日志和两个通用指标 |
| `read-failure` | 心跳与 `SENSOR_READ_FAILED` 合成日志，不伪造读数 |
| `out-of-range` | 心跳、`VALUE_OUT_OF_RANGE` 合成警告和配置值 |
| `value-stuck` | 同一个配置值重复上传 |
| `offline` | 第一轮心跳/日志，第二轮跳过上传；默认两轮结束后需继续等待服务端离线阈值 |
| `intermittent-failure` / `recovery` | 按定义轮流发送正常、异常或恢复形式的数据，不直接标记业务故障已恢复 |
| `wifi-jitter` | 按定义跳过上传或延迟执行；不操纵真实 Wi-Fi 链路 |
| `multi-anomaly` | 在合成时间线中组合多种异常输入 |
| `multi-device-classroom` | 显式提供三组测试设备凭据，逐设备执行，不创建设备 |

多设备还需 `XINJIAN_DEVICE_IDS` 与 `XINJIAN_DEVICE_TOKENS`，各包含三项逗号分隔值；基础单设备环境变量仍需设置。凭据不得保存到场景文件或 Git。

场景定义位于 [scenario_specs/](scenario_specs/)。`normal_device.py` 等根目录兼容脚本调用旧场景实现，其错误码、持续运行和报告行为可能不同；上述表对应版本化 CLI，不混用两套实现的结果。

## 上传与重试边界

每轮有动作时调用协议 V1 批量入口，同批次的 `requestId`、`bootId`、`sequenceNo` 与正文在网络重试中保持不变。超时/连接错误、408/425/429/5xx 按配置有限指数退避；其余认证/协议类 4xx 不重试。成功后再推进序列号。

这只是进程内重试，没有持久化离线队列；程序退出后不能靠重启恢复未确认批次。DSL 的 drop 会直接跳过该轮发送，不等于测试了 HTTP 重试。验证重启缓存请使用固件主机回归和实物测试。

## 报告、再次运行与清理

版本化 CLI 在首次发送前，将运行清单写到**当前工作目录**的 `.simulator-runs/<UUID>.json`（Git 忽略），随后更新进度和完成/中断状态。清单包含场景版本/哈希、运行身份、设备、轮数及已确认的返回记录 ID，不含令牌，也不是诊断正确性报告。异常中断保留最后已写入的清单；未收到回执的记录不一定列入其中，但仍可按 testRunId 清理服务端已接收的数据。

```bash
xinjian-simulator report <test-run-uuid>
xinjian-simulator replay <test-run-uuid>
xinjian-simulator cleanup <test-run-uuid>
```

- `report` 读取本机记录，须从相同工作目录执行。
- `replay` 读取旧报告的场景 ID 与轮数，再加载**当前**场景和环境配置，生成新 testRunId、批次与时间。它不校验旧哈希相同，也不重传原始载荷；不能称为完全相同输入或幂等验收。
- `cleanup` 使用本机报告及当前设备配置，通过服务端按设备/testRunId 定向清理测试数据；当前设备集合必须与清单一致。它不删除其他运行或正式记录，也不替代整组演示身份清理。

## 本目录检查

在 `simulator` 目录、已激活虚拟环境后：

```bash
pytest
ruff check .
```

完整项目验证使用仓库 [scripts/verify.sh](../scripts/verify.sh)，统一使用后端指定的 Python 环境并自动收集模拟器测试。模拟器成功上传、回归通过和真实硬件正常是不同结论，分别报告。
