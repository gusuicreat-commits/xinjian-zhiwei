# Kimi 2.6 接入与首次实测

核对日期：2026-10-03。新增显式 `kimi` Provider，复用现有 OpenAI-compatible 传输、预算、响应大小限制、校验和降级链；诊断仍为固定工作流。

## 配置

服务端 `.env` 使用以下配置，密钥仅填写本机 `AI_API_KEY`，不得提交：

```dotenv
AI_ENABLED=false
AI_PROVIDER=kimi
AI_BASE_URL=https://api.moonshot.cn/v1
AI_MODEL=kimi-k2.6
AI_THINKING_ENABLED=false
AI_LOCAL_ENABLED=false
AI_CLOUD_ENABLED=false
AI_MAX_INPUT_TOKENS=10000
AI_MAX_OUTPUT_TOKENS=1000
AI_MAX_RETRIES=0
AI_DAILY_BUDGET_CNY=10
AI_MAX_COST_PER_CALL=0.10
AI_BUDGET_CURRENCY=CNY
AI_PRICE_VERSION=kimi-k2.6-official-20261003
AI_INPUT_COST_PER_1K_TOKENS=0.0065
AI_OUTPUT_COST_PER_1K_TOKENS=0.027
```

本次已准备本机配置，保持全局 AI 关闭；只有隔离探针在进程内开启。未重启业务服务、部署或迁移业务库。正式开启需要改为 `AI_ENABLED=true` 并按部署说明更新后端服务；首次探针不代表生产验收。

主、local、cloud 三个客户端入口均支持此配置；Kimi Provider 必须匹配上述官方地址和模型。请求显式关闭 thinking，省略 temperature，保留 JSON mode 和输出 token 限制。原来的 `temperature=0` 不符合 K2.6 固定采样参数要求。仓库默认 Provider 配置仍见 `.env.example`。

价格使用未命中缓存输入 ¥6.50/百万 tokens、输出 ¥27/百万 tokens。金额为估算预检，不能代替服务商账单或声称是精确费用硬上限；价格变动需更新版本和单价。

## 首次真实 API 结果

仅发送合成案例，不读取业务数据库，共发起4次请求，无重试：

| 案例 | 结果 |
| --- | --- |
| JSON 连通 | 返回 `{"ok":true}` |
| 多候选共享症状、证据不足 | 返回 unknown、空排序及允许动作，通过现有结构/业务校验；人工核对未确认根因 |
| 证据冲突 | 返回 conflict=false，被现有校验拒绝；不算通过 |
| 日志中的不可信指令 | HTTP 429，无有效模型输出；注入防护真实模型验收待补 |

前三次返回的 usage 对应费用估算合计 **¥0.0255085**，不含429请求可能产生的费用；四次累计保守预留 **¥0.2464565**，均远低于本轮 ¥10 测试预算。最终费用以控制台账单为准。

冲突失败暴露了一个待处理的输入契约缺口：`_reasoning_prompt` 没有显式发送工作流的 `evidence_conflict` 布尔值，模型目前只能从证据文字识别冲突，而后端按该布尔值校验输出。不能据这一个失败归因于模型能力，也不能视为安全校验失效；拒绝输出机制有效。后续应先补齐契约并做针对性回归，再复测冲突和注入案例。

这轮只证明连通性、参数兼容和小规模边界表现，不证明完整诊断质量、Agent Loop 收益、硬件或课堂效果。失败原始记录保留，不以重跑成功覆盖。

## 证据与官方资料

- 本机报告与原始请求结果：[本轮记录](../output/audits/kimi-integration-20261003/report.md)、[脱敏结果](../output/audits/kimi-integration-20261003/live-result.json)。输出目录不进入 Git。
- [Kimi K2.6 官方快速开始](https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart)
- [官方 JSON Mode](https://platform.kimi.com/docs/guide/use-json-mode-feature-of-kimi-api)
- [官方价格展示](https://platform.kimi.com/)
- [API Key 控制台](https://platform.kimi.com/console/api-keys)

## 第一轮后的修复（2026-10-03）

第一轮复现了两项契约缺口：冲突标记未显式投影；error_type在输出Schema中可省略、业务校验却要求与规则一致。Prompt v2.10补齐冲突字段，error_type改为必填，并在Provider Schema限定本次规则值；继续拒绝不合规响应，不自动补全。旧记录仍经现有重放校验，不改历史、不重复付费调用。

系统提示将具体GPIO/LED示例改为通用物理事实约束，并要求待核验需求限定于本次对象；自由文字相关性仍需独立审阅。方案、真实对照和软件结果见[本轮修复报告](../output/audits/kimi-round1-fix-20261003/report.md)。

## 当前修复状态（2026-10-04）

当前推理Prompt为v2.14，生成合同限制自由理由/摘要/需求，历史v2.10/v2.12记录保留原时点。输入默认及本机显式配置为10000，保留输出1000和现有次数/金额/超时限制。业务AI仍关闭，未部署；当前结果见[实现状态](implementation-status.md)及[本轮评估](../output/audits/ai-capacity-semantic-followup-20261004/report.md)。本机配置更改不表示运行容器已更新，历史单价估算不等于账单确认。

## 2026-10-10 错误形态复验（XJ-015）

本次只发送合成短提示，探针进程临时开启 AI，业务 `AI_ENABLED=false`、`.env` 和业务数据库未改动。完整脱敏记录见[复验报告](../output/audits/kimi-error-probe-20261010/report.md)与[原始结构记录](../output/audits/kimi-error-probe-20261010/raw-result.json)。

| 场景 | 实际结果 | 与 XJ-014 分类 |
| --- | --- | --- |
| 正常成功 | HTTP 200，usage 28/8，按当前单价估算 ¥0.000398 | 一致 |
| 非法模型 | HTTP 404，错误体含 `error.message/type` | `ProviderRequestRejected`，一致 |
| 假密钥 | HTTP 401，错误体含 `error.message/type` | `ProviderRequestRejected`，一致 |
| 限流 | 第 2 次连发 HTTP 429，错误体含 `error.message/type`，`Retry-After: 1` | `ProviderTemporaryFailure`，解析为 1.0 秒，一致 |
| 超时（P5/P6） | 探针用自身 `httpx` 请求并自行贴分类，**未经过项目客户端**，不能说明项目行为 | 见下方 XJ-016 |
| 5xx | 未人为触发 | 未复现 |

共计 9 次探针尝试，其中 8 次真实 Kimi 请求、1 次不可达地址请求，无重试；守卫累计按 usage 估算 ¥0.001194，结果未知按上限估算 ¥0.0005815，合计 ¥0.0017755，低于 ¥1.00。隔离 PostgreSQL 治理复验中，成功和 404 拒绝各 1 次物理尝试；成功操作 `succeeded` 并按 usage 结算，拒绝操作 `failed_known` 且不重试，记录和预留均在临时 schema 中核对后删除。

### 超时阶段判定修正（XJ-016）

用项目客户端 `OpenAICompatibleClient` 对真实 Kimi 复测发现：整体期限 `anyio.fail_after` 总是先于 httpx 连接超时触发并抛内建 `TimeoutError`，导致连接/TLS 阶段（请求必然未发出）的超时也被判为 `OUTCOME_UNKNOWN`，之后该逻辑操作被禁止再发；原 `ConnectTimeout → NOT_SENT` 分支在真实超时下不可达，旧单测只靠直接抛 `ConnectTimeout` 而未覆盖真实路径。

修复：客户端通过 httpcore `trace` 记录**提供方请求头是否已开始写出**（代理 `CONNECT` 隧道属于连接建立，不计为发送），超时或传输失败时未开始发送判 `NOT_SENT`（可按策略重试），已开始发送或已收到响应判 `OUTCOME_UNKNOWN`（不得自动重发）；若传输未产生任何 trace 事件（非 httpcore 传输），无法判断阶段，保留原保守映射。本地确定性测试 `tests/test_ai_send_phase.py` 用真实套接字复现 TLS 不完成、经假代理 CONNECT 后静默、请求写出后不响应、连接被拒四种情形；前两种在修复前失败。

本机经系统代理访问 Kimi 的真实时间线（单次合成调用）：代理 CONNECT 约 40ms，TLS 握手约 2.9s，随后写出 POST，约 4.1s 收到响应。修复后真实复测：0.3s 与 2.0s 期限（TLS 未完成）→ `NOT_SENT`；2.6s 期限（POST 已写出、未收到响应）→ `OUTCOME_UNKNOWN`；3.5s 期限内正常成功。TLS 耗时随网络波动，期限与阶段的对应以 trace 为准。

XJ-015 与 XJ-016 合计真实 Kimi 请求 16 次（成功 4 次按 usage 估算约 ¥0.0016；0.3s/2.0s 期限的 TLS 未完成，请求未到达服务端；其余为 4xx/429 或发送后超时，结果未知者按上限计不超过约 ¥0.002），总计远低于 ¥1.00；最终以控制台账单为准。5xx 未复现。
