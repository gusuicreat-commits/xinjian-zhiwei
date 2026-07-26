# Phase 9.5 DeepSeek 解释增强与 Provider 无关诊断设计

## 当前结论

Phase 9.5 固定生产对话 Provider 为 DeepSeek 官方 API，模型为
`deepseek-v4-flash`，显式使用非思考模式。它仍只是可选解释增强，不是诊断
前置条件。`AI_ENABLED=false` 且仓库没有真实 API Key，所以默认不会发起外部
请求；学生端仍显示完整确定性解释。

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
  → 可选 DeepSeek 非思考解释
```

`diagnosis_results` 与 `guidance_history` 在 AI 调用前已经确定。AI 返回内容只作为解释增强保存到 `ai_call_records`，不能改写错误类型、规则证据、原因评分或基础提示。

## Provider 抽象

- `AIClient.complete_json()`：接收系统提示与用户 JSON，返回原始 JSON 文本及可选 Token 计数。
- `EmbeddingClient.embed()`：接收检索文本，返回配置维度的查询向量。
- 默认实现为 `DisabledAIClient` 和 `DisabledEmbeddingClient`。
- 生产配置选择 DeepSeek，但继续复用 `OpenAICompatibleClient`，没有复制平行诊断逻辑。
- Provider 适配层为 DeepSeek 请求发送 `thinking: {"type": "disabled"}`，不默认启用长推理。
- Mock、Disabled 和本地扩展 Client 保留用于测试或明确扩展；本地 Client 不进入生产默认路由。
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

生产路由为：确定性模板 → 策略判断 → PostgreSQL 缓存 → DeepSeek
`deepseek-v4-flash` 非思考模式 → Pydantic 校验 → 确定性降级。正式表达为
`cache → deepseek → deterministic_fallback`，不执行本地小模型到云模型、
简单模型到复杂模型或便宜模型到昂贵模型的自动分层。缓存命中不计 Provider
调用次数。真实调用前检查每 Episode、每设备每小时、单次预算、每日人民币
预算和输入 Token；输出 Token 由请求参数限制。

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

模型请求统一经过 `phase9.5-allowlist-v1`：

- 设备 ID 转换为稳定的不可逆短哈希；
- 只保留 Episode/Diagnosis、错误码、规则、证据、原因、Hint Level 和限制；
- 日志仅选取最近 3–10 条与当前规则直接相关的记录，并对文本再次脱敏；
- 传感器读数转换为样本数、最小值、最大值和最新值等聚合；
- 知识正文按配置截断，不发送来源私有 URI；
- 学生技术问题在发送前应用同一脱敏规则。

学生姓名、学号、班级实名、手机号、身份证号、邮箱、账号密码、设备令牌、
Authorization、DeepSeek Key、数据库密码/连接串、Wi-Fi 密码、教师私人备注、
完整原始请求、无关日志和环境变量都不进入 Prompt 或审计。

## 结构化输出

输出字段包括 `error_type`、`summary`、`evidence`、`possible_causes`、`steps`、`hint_level`、`need_teacher_help` 和 `limitations`。

- `error_type` 必须属于规则命中；没有规则但存在异常信号时只能使用通用 `UNCLASSIFIED_ANOMALY`，不得虚构硬件故障码；
- `evidence` 必须逐字选自服务端生成的规则证据；
- 原因引用的 `knowledge_chunk_ids` 必须属于本次检索结果；
- 不认识的字段会被拒绝；
- 失败后按有限次数重试，最终仍失败则降级。

## 审计

`ai_call_records` 保存成功、失败和跳过三类记录，包括触发原因、Episode、缓存、
最后路由、`route_path`、Provider/模型、Prompt 版本与哈希、尝试次数、耗时、结构化输出、
知识引用、Token、校验和降级原因。审计输入只保存匿名标识、内容哈希、计数、
规则/错误码/知识块 ID 和隐私控制摘要，不保存完整 Prompt、完整日志、API Key
或 Authorization。典型路径包括 `cache_hit`、`cache_miss → deepseek_success`、
`cache_miss → deepseek_failed → deterministic_fallback` 和
`ai_disabled → deterministic_only`。

## 待项目方提供

- `已确定: DeepSeek 官方 API、deepseek-v4-flash、非思考模式`
- `TODO[待补充]: 服务端 DeepSeek API Key、人民币预算和数据外发审批`
- `TODO[待补充]: Embedding Provider、模型、维度和服务端密钥`
- `TODO[待补充]: 经授权、审核并完成向量化的正式知识`
- `TODO[待补充]: 数据外发、隐私、日志脱敏和保留政策`
- `TODO[待补充]: 真实诊断准确率、误报率、漏报率与人工审核标准`

## 测试知识与阶段边界

Phase 9 最终验收允许保留一组 `is_test_data=true` 的合成知识：DHT11 读取失败、设备离线、温湿度越界和无关 LED 案例。来源键为 `phase9.synthetic-acceptance`，版本为 `phase9-acceptance-v1`，审核人引用明确标为自动化验收；配套四维向量由固定测试机制生成，不调用外部 Embedding 服务。它们只验证结构化过滤、全文检索、pgvector 和 RRF，不能作为课程资料、硬件说明书或真实专业知识。

Phase 9.5 完成的是生产决策、运行边界、脱敏和知识治理补强，不包含真实收费
调用、真实固件或正式部署。Phase 10 尚未开始。
