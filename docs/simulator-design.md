# 虚拟实验室与场景模拟器（P2）

## 边界

虚拟实验室只生成 `isTestData=true` 的合成数据，不代表真实 ESP32、传感器、课程任务或
故障真值。场景参数均为可配置测试值；尚未确认的硬件字段和生产参数不写死。

## 场景 DSL

版本化 YAML 位于 `simulator/scenario_specs/`。Schema V1 必须包含：

- `schema_version`、稳定 `id`、场景 `version` 和标题；
- 固定整数 `seed`，用于重放标识；
- `devices`，声明所需测试设备数量；
- 有序 `cycles`，每周期声明通用动作和 `drop/latency_ms` 网络条件。

加载器拒绝未知动作、未知网络字段、负延迟、空时间线和不支持的 Schema。每个规范生成
稳定 SHA-256 并进入报告，重放时记录原运行 ID、相同场景版本、哈希、种子和周期数。

内置场景：

- `normal`
- `read-failure`
- `offline`
- `out-of-range`
- `value-stuck`
- `intermittent-failure`
- `recovery`
- `multi-device-classroom`

## CLI

```bash
cd simulator
xinjian-simulator list
xinjian-simulator validate
xinjian-simulator validate recovery
xinjian-simulator run recovery --iterations 2
xinjian-simulator report <test-run-uuid>
xinjian-simulator replay <test-run-uuid>
xinjian-simulator cleanup <test-run-uuid>
```

运行报告保存到本地忽略目录 `.simulator-runs/`，包含报告 Schema、运行 UUID、场景版本/
哈希、种子、周期数、设备 ID、服务端记录 ID、完成时间和合成数据标记，不保存设备令牌。

多设备场景要求显式提供数量匹配的 `XINJIAN_DEVICE_IDS` 和
`XINJIAN_DEVICE_TOKENS` 逗号分隔值；缺失时拒绝运行，不自动编造设备或凭据。

## 可追溯与定向清理

每个协议批次通过 `testRunId` 关联运行 UUID，且服务端只允许
`isTestData=true` 的请求携带该字段。`DELETE /api/v1/device/test-runs/{test_run_id}`
使用设备凭据，只删除该设备、该运行 UUID 下的请求和三类采集记录。它不会按时间范围、
场景名称或模糊条件删除，更不会删除数据库卷、其他测试运行或非测试记录。

## 可重复性与网络语义

- YAML 版本、哈希、种子和周期顺序固定；
- `drop=true` 的周期不上传；
- `latency_ms` 在发送前注入确定延迟；
- P1 客户端对可重试错误复用相同请求并指数退避；
- `recovery` 明确先产生合成读取失败，再产生正常读数；
- `multi-device-classroom` 对每个显式配置设备执行相同版本场景并共享运行 UUID。

## 验收

自动化测试覆盖十个规范加载、哈希、离线丢包、Wi-Fi 抖动、组合异常、恢复时间线、
多设备声明、协议批次、
重试复用和运行 UUID 定向清理。真实设备、真实课堂和真实故障仍未参与验收。
