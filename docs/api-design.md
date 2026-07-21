# 芯鉴知微 API 设计（Phase 8）

## 通用约定

- API 前缀：`/api/v1`。
- 请求和响应：JSON，时间戳必须为包含时区的 ISO 8601 字符串。
- 未声明字段：拒绝并返回 422，避免设备字段拼写错误被静默忽略。
- 测试数据：必须显式设置 `is_test_data: true`。
- 原始请求：入库到对应记录的 `raw_payload`，用于追溯；认证头不会写入原始载荷。

## 设备认证

日志、读数和心跳接口要求：

```text
X-Device-ID: <device_key>
X-Device-Token: <secret token>
```

状态接口从路径取得 `device_id`，只要求 `X-Device-Token`。数据库只保存 PBKDF2-SHA256 哈希；未知设备、停用设备或令牌不匹配统一返回 401，避免泄漏设备是否存在。

## 接口

### POST `/device/logs`

必填字段：`level`、`message`、`occurred_at`。可选字段：`event_code`、`sensor_snapshot`、`is_test_data`。`level` 仅接受 `debug`、`info`、`warning`、`error`、`critical`。

### POST `/device/readings`

必填字段：`sensor_type`、`metric_key`、有限数值 `value`、`observed_at`。可选字段：`unit`、`metadata`、`is_test_data`。字段是通用指标表达，不绑定硬件厂商或型号。

### POST `/device/heartbeat`

必填字段：`observed_at`。可选字段：`firmware_version`、`metadata`、`is_test_data`。服务端以接收时间更新 `devices.last_seen_at`，设备上报时间单独保留，避免设备时钟偏差影响在线判断。

### GET `/device/{device_id}/status`

返回 `online`、`offline` 或 `never_seen`。离线阈值由 `DEVICE_OFFLINE_AFTER_SECONDS` 配置，默认开发值为 90 秒。

### POST `/diagnosis/devices/{device_id}/run`

使用路径设备 ID 和 `X-Device-Token` 认证。请求包含 1 至 604800 秒的回看窗口，以及可选的通用实验模板快照 `template_id + metric_ranges`。响应返回持久化结果 ID、规则集版本、输入指纹、按优先级排序的命中规则及证据。

Phase 4 尚未建立实验模板和用户权限模型，模板快照是显式的临时接口边界，不表示设备端有权定义生产阈值。相关业务模型确定后应改为服务端加载模板。

### POST `/diagnosis/results/{diagnosis_result_id}/guidance`

使用设备 ID 和设备令牌认证。根据已保存的诊断上下文运行 YAML 故障树并保存原因排序、证据、提示等级和提示文本。同一诊断结果与同一故障树存在唯一约束，重复调用返回已有历史，不重复增加失败次数。

### GET `/diagnosis/devices/{device_id}/guidance`

返回当前设备的提示历史，按创建时间倒序排列。

### GET `/diagnosis/interventions`

返回达到 Level 4 的设备与故障树记录。当前用户与教师角色尚未建立，因此使用环境变量 `REVIEW_ACCESS_TOKEN` 和 `X-Review-Token` 作为临时、默认关闭的审阅边界；未配置返回 503，凭据错误返回 401。正式角色模型落地后必须替换该临时边界。

### POST `/student/session`

使用设备 ID 与设备令牌完成临时学生端会话验证。响应明确返回 `auth_mode=device_credential_placeholder`；该接口不创建用户，也不签发服务端学生令牌。

### GET `/student/dashboard`

使用设备凭据读取当前设备状态、最近 100 条日志、最近 500 条读数、最新诊断、对应提示及最新反馈。实验任务模型尚未建立，因此任务始终明确返回 `configured=false`，不会生成虚构任务。

### POST `/student/diagnoses/{diagnosis_result_id}/feedback`

保存 `resolved`、`unresolved` 或 `request_teacher_help`。只能反馈当前凭据所属设备的诊断结果；其他设备或不存在的结果返回 404。反馈继承诊断的 `is_test_data` 标记。

### POST `/teacher/session`

使用 `X-Review-Token` 验证临时教师审阅会话。该接口不创建教师账号，也不签发服务端会话；`REVIEW_ACCESS_TOKEN` 未配置时返回 503。

### GET `/teacher/dashboard`

返回设备在线/离线/未上报与异常数量、互斥的设备状态图数据、全部诊断记录的错误排行与七日趋势、最新异常设备、最近 80 条设备日志及 Level 4 介入队列。学生、班级和实验任务尚未建模，对应结构明确返回 `configured=false`，实验完成率返回 `null`。知识卡片返回实际知识来源、文档、审核知识块和向量数量。

## 知识库接口

以下接口全部使用临时 `X-Review-Token` 边界；没有正式教师身份模型时不开放匿名知识导入或审核。

### GET `/knowledge/status`

返回框架状态、是否存在可检索内容、来源数、文档数、待审核数、审核通过知识块数、向量数，以及当前 Embedding Provider/模型/维度是否配置。空库返回 200 和明确说明，不创建占位记录。

### GET/POST `/knowledge/sources`

查询或登记资料来源。`source_key` 是外部稳定标识；同时保存类型、标题、来源 URI、版本、许可证、授权范围、元数据和 `is_test_data`。重复 `source_key` 返回 409。

### POST `/knowledge/sources/{source_id}/documents/text`

只接收已经提取的 `text/*` 文本，不直接解析 PDF、DOCX 或扫描件。服务端规范化换行、按可配置字符窗口切分、保存字符定位和 SHA-256；同一来源重复导入相同内容返回原文档并设置 `idempotent_replay=true`。

### PATCH `/knowledge/documents/{document_id}/review`

接受 `approved` 或 `rejected`、审核人引用和备注。来源未记录 `authorization_scope` 时不能批准。审核状态同步到文档的全部知识块，并追加不可覆盖的审核历史。

### POST `/knowledge/documents/{document_id}/embeddings`

保存外部适配器生成的向量。文档必须先审核通过；同一请求中的维度必须一致。配置了 Provider/模型/维度后请求必须完全匹配；未配置时只允许 `is_test_data=true` 的测试向量，正式向量返回 503。

### POST `/knowledge/search`

请求显式携带查询向量、Provider、模型和限制条件。只检索审核通过且维度匹配的知识块，默认排除来源、文档或向量任一层标记为测试的数据。响应包含来源、版本、URI、文档、知识块定位、相似度和测试标记。

## 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 状态查询成功 |
| 201 | 上传内容已保存 |
| 401 | 设备不存在、已停用或令牌无效 |
| 404 | 诊断结果不存在或不属于当前设备 |
| 409 | 来源重复、授权缺失、文档未审核或 Embedding 配置不一致 |
| 413 | 提取文本超过配置的最大字符数 |
| 422 | 缺少认证头、字段缺失、类型错误、时间戳无时区或存在额外字段 |
| 503 | 教师审阅凭据或正式 Embedding Provider 尚未配置 |

当前提供设备凭据保护的临时学生 API，以及审阅令牌保护的教师聚合和知识库管理 API；不提供正式账号、班级、实验任务、自动 Embedding、AI 诊断或公开设备注册接口。
