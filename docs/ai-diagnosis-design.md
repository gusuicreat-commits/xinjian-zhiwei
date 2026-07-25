# Phase 9 Provider 无关 AI 诊断设计

## 当前结论

Phase 9 完成的是可配置、可审计、失败可降级的轻量框架，不是正式 AI 诊断上线。当前没有已确认的 AI/Embedding Provider、模型、密钥或正式知识，默认配置不会发起任何外部请求，学生端仍能显示完整确定性解释。

## 不可覆盖的主链路

```text
设备数据库记录
  → DiagnosisEpisode 事件聚合
  → YAML 规则与故障树
  → DiagnosisCore
  → 结构化过滤 + PostgreSQL FTS + pgvector + RRF
  → 确定性说明模板
  → AIExplanationPolicy
  → 指纹缓存
  → 可选本地/云端 AI 解释
```

`diagnosis_results` 与 `guidance_history` 在 AI 调用前已经确定。AI 返回内容只作为解释增强保存到 `ai_call_records`，不能改写错误类型、规则证据、原因评分或基础提示。

## Provider 抽象

- `AIClient.complete_json()`：接收系统提示与用户 JSON，返回原始 JSON 文本及可选 Token 计数。
- `EmbeddingClient.embed()`：接收检索文本，返回配置维度的查询向量。
- 默认实现为 `DisabledAIClient` 和 `DisabledEmbeddingClient`。
- 可选 `openai-compatible` 只是传输协议适配器，不表示选定任何厂商。
- Provider 名称、Base URL、模型、密钥、超时和重试全部由后端环境变量注入，前端和数据库不保存密钥。

## 事件、核心与确定性说明

- `DiagnosisEpisode` 按设备、可选实验模板和主要错误码聚合重复异常；页面刷新和只读查询不更新事件或触发 AI。
- `DiagnosisCore` 固化错误类型、置信度、规则证据、原因排序、步骤、提示等级和规则/故障树/知识版本。
- 确定性模板直接从 `DiagnosisCore` 生成摘要、证据解释、候选原因和 Level 1–4 步骤。它在 AI 完全关闭时仍是完整结果。
- AI 只能生成 explanation，不能修改 `DiagnosisCore`。

## 混合检索

- 继续使用 Phase 8 的 `knowledge_sources/documents/chunks/embeddings/reviews`，不新建知识库。
- 先按审核状态、错误码、规则、实验和通用硬件元数据过滤。
- PostgreSQL 使用 `simple` 配置执行全文检索；SQLite 测试使用等价词项评分。
- Embedding 客户端可用时追加 pgvector 排名，不可用时关键词检索独立降级。
- 两路排名使用 Reciprocal Rank Fusion，去重后只返回已审核 Top K 和来源。

## 调用策略

高置信已知异常、重复 Episode、单纯刷新/查询、只执行知识检索和核心未变化时默认不调用 AI。低置信、证据冲突、多规则、未知异常、学生追问、教师总结或标准步骤多次无效时可以放行。策略输出 `should_call`、`trigger_reason`、`preferred_route` 和输入/输出 Token 上限。

策略判断与 Provider 是否已配置分离：先判断语义上是否需要增强，再检查缓存和运行门禁。这样即使 Provider 后续关闭，相同指纹的已校验缓存仍可复用；没有缓存时才明确记录 `AI_NOT_CONFIGURED` 并返回确定性模板。页面刷新、教师统计和普通知识检索只读数据库，不调用此路由。

## 缓存、预算与路由

稳定指纹只包含实验/硬件、主要错误、设备状态、排序后的规则与证据代码、Top 原因、知识块、提示等级及规则/故障树/知识/Prompt/Schema 版本，不包含无关时间戳、数据库 ID 或原始日志顺序。

路由顺序为：确定性模板 → 策略跳过 → PostgreSQL 缓存 → 可选本地 OpenAI-compatible → 可选云端 OpenAI-compatible → 校验 → 确定性降级。缓存命中不计 Provider 调用次数。真实调用前检查每 Episode、每设备每小时、单次预算、每日预算和输入 Token；输出 Token 通过兼容传输参数限制。

稳定指纹包含规则、故障树、知识块、Hint Level、Prompt、Schema、输出语言和可选用户问题；不包含诊断数据库 ID、时间戳或日志顺序。修改任一语义版本或输出语言都会失效缓存。

## 调用门禁

默认 `AI_REQUIRE_KNOWLEDGE=true`。以下任一条件成立时不调用 AI，直接返回规则结果：

1. 策略判定为高置信已知异常或核心上下文未变化；
2. AI 总开关、目标路由或 Provider 未配置；
3. Episode/设备调用上限或每日预算已耗尽；
4. Provider 调用失败、超时或限流；
5. 输出不是合法 JSON或不符合 Pydantic Schema；
6. 错误类型、证据或知识引用越过服务端白名单。

## 输入和隐私

模型输入包含受数量上限约束的设备状态、日志、心跳、传感器读数、规则命中、故障树结果和知识引用。设备令牌、审阅令牌、数据库密码和 Provider API Key 不进入 Prompt、审计快照或响应。

当前上下文仍可能包含设备日志正文。真实 Provider 接入前必须由项目方确认数据外发范围、隐私策略和日志脱敏要求。

## 结构化输出

输出字段包括 `error_type`、`summary`、`evidence`、`possible_causes`、`steps`、`hint_level`、`need_teacher_help` 和 `limitations`。

- `error_type` 必须属于规则命中；没有规则但存在异常信号时只能使用通用 `UNCLASSIFIED_ANOMALY`，不得虚构硬件故障码；
- `evidence` 必须逐字选自服务端生成的规则证据；
- 原因引用的 `knowledge_chunk_ids` 必须属于本次检索结果；
- 不认识的字段会被拒绝；
- 失败后按有限次数重试，最终仍失败则降级。

## 审计

`ai_call_records` 保存成功、失败和跳过三类记录，包括触发原因、Episode、缓存、路由、Provider/模型、Prompt、尝试次数、耗时、结构化输出、知识引用、Token、校验和降级原因。完整日志/读数正文沿用原诊断上下文追溯，不在 AI 审计表重复保存；API Key 永不保存。

## 待项目方提供

- `TODO[待补充]: AI Provider、模型、Base URL、服务端密钥和费用限制`
- `TODO[待补充]: Embedding Provider、模型、维度和服务端密钥`
- `TODO[待补充]: 经授权、审核并完成向量化的正式知识`
- `TODO[待补充]: 数据外发、隐私、日志脱敏和保留政策`
- `TODO[待补充]: 真实诊断准确率、误报率、漏报率与人工审核标准`

## 测试知识与阶段边界

Phase 9 最终验收允许保留一组 `is_test_data=true` 的合成知识：DHT11 读取失败、设备离线、温湿度越界和无关 LED 案例。来源键为 `phase9.synthetic-acceptance`，版本为 `phase9-acceptance-v1`，审核人引用明确标为自动化验收；配套四维向量由固定测试机制生成，不调用外部 Embedding 服务。它们只验证结构化过滤、全文检索、pgvector 和 RRF，不能作为课程资料、硬件说明书或真实专业知识。

Phase 9 已完成；Phase 10 尚未开始。
