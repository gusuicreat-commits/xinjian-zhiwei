# 芯鉴知微项目上下文

> 来源：`docs/芯鉴知微_项目背景README_Codex版.docx`。本文件在 Phase 0 中提取并按当前总控约束整理；原始 Word 文档保持不变。若背景文档的早期建议与当前总控方案冲突，以当前总控方案为准。

## 1. 项目定义

芯鉴知微是面向高校嵌入式与物联网实验课程的智能分析平台。平台从 ESP32 等实验设备采集日志、心跳和传感器数据，基于真实运行证据识别异常，为学生生成可解释的排查步骤，并为教师提供班级进度、设备状态和高频错误看板。

项目不是普通 AI 聊天应用，也不是只有硬件或页面的演示。第一版必须形成以下闭环：

```text
ESP32 与传感器
  -> 日志、心跳、传感器数据
  -> 后端校验与存储
  -> 规则诊断
  -> 故障树原因排序
  -> 结构化知识上下文供给
  -> AI 在候选原因与证据白名单内辅助排序
  -> 结构化知识结果校验
  -> 大模型生成结构化教学建议
  -> 学生端排查与反馈
  -> 教师端班级状态与错误统计
```

核心原则是“设备提供事实、规则判断异常、故障树限定原因空间、知识库在推理前提供约束并在推理后校验、AI 受约束推理与解释、教师审核关键知识”。AI 不得替代确定性规则结论、创造候选集外故障或在缺乏证据时生成高支持原因。

## 2. 用户与核心价值

- 学生：从“灯不亮、传感器没数据”等表象快速定位接线、代码、供电、烧录或硬件问题。
- 教师：减少逐块实验板人工排查，快速识别异常学生、常见卡点和需要介入的设备。
- 课程团队：沉淀实验模板、错误案例、历史日志和解决反馈，形成可复用的教学数据资产。

## 3. 第一版 MVP

主线实验为 ESP32 + DHT11 温湿度实验。第一版至少跑通：

1. ESP32 连接 Wi-Fi，读取 DHT11，输出统一日志并通过 HTTP 上传。
2. 后端接收、校验和保存设备日志、心跳及传感器数据。
3. 规则引擎识别 `SENSOR_READ_FAILED`、`DEVICE_OFFLINE`、`VALUE_OUT_OF_RANGE`。
4. 故障树对可能原因排序，提示等级可逐步升级。
5. AI 在故障树候选集内综合证据，输出支持等级与证据 ID，失败时回退确定性排序。
6. 结构化知识库校验推理上下文并提供实验规范、案例和排查步骤；第一阶段不使用 RAG。
7. AI 解释输出通过 Pydantic 和白名单校验；AI 不可用时规则诊断仍工作。
8. 学生端展示设备状态、实时日志、传感器曲线、异常卡片和反馈操作。
9. 教师端展示在线/离线/异常设备、实验进度、高频错误和介入列表。

扩展知识范围包括 LED、按键、光敏和超声波实验，但第一版硬件联调只聚焦 ESP32 + DHT11。

## 4. 数据边界

设备端至少产生三类数据：

- 心跳：用于在线状态与 `last_seen_at`。
- 设备日志：包含级别、设备、学生、实验、消息、错误码、传感器快照和时间戳。
- 传感器读数：包含类型、值、单位、采集时间和可追溯原始请求。

诊断结果必须是稳定结构，至少包含：

- `errorType`
- `summary`
- `evidence`
- `possibleCauses`
- `steps`
- `hintLevel`
- `needTeacherHelp`

所有外部请求使用 Pydantic Schema；API 不直接返回 ORM 对象。设备令牌和密码必须哈希存储，敏感配置不得进入前端或 Git。

## 5. 固定技术路线

- 前端：Vue 3、TypeScript、Vite、Vue Router、Pinia、Axios、Element Plus、ECharts、Vitest、Playwright。
- 后端：Python、FastAPI、Pydantic、SQLAlchemy 2、Alembic、pytest、HTTPX。
- 数据库：PostgreSQL；未来需要 RAG 时再增加 pgvector 扩展。
- 设备端：ESP32、Arduino Framework、PlatformIO、Wi-Fi、HTTP、JSON、DHT11。
- 诊断：Python/YAML 规则、JSON/YAML 故障树、结构化 `KnowledgeCase`、统一 `AIClient`、Pydantic 结构化推理与解释；LangGraph 内嵌编排，不使用自由规划 Agent。
- 部署：Docker、Docker Compose、Nginx、GitHub Actions。

背景 Word 中的 `ai-service` 独立目录、Chroma/FAISS、pgvector RAG 等内容属于早期草案。当前方案将 AI 诊断内聚到 FastAPI 后端，并使用 PostgreSQL 结构化知识，避免第一阶段重复引入服务和数据库。

## 6. 主要业务实体

第一版至少包含：`users`、`classes`、`devices`、`experiments`、`experiment_templates`、`device_logs`、`sensor_readings`、`diagnosis_results`、`diagnosis_feedback`、`knowledge_cases`、`knowledge_case_drafts`、`ai_call_records`。

数据库结构必须通过 Alembic 迁移管理，不以手工修改表结构代替迁移。

## 7. API 边界

统一前缀为 `/api/v1`：

- 设备：日志、读数、心跳和设备配置/状态。
- 学生：实验、设备、日志、诊断和诊断反馈。
- 教师：看板、学生、设备、错误和学生详情。
- 诊断：运行诊断并查询结果。
- 知识库：检索、查看、新增和审核案例。

背景 Word 中无版本前缀的 `/api/...` 路由属于早期草案，后续实现采用 `/api/v1/...`。

## 8. 明确边界

历史第一版曾禁止 LangGraph；当前只在 FastAPI 模块化单体内引入受控状态编排，不引入自由规划 Agent 或多智能体。仍不引入 Spring Boot、微服务、Kubernetes、Redis、消息队列、MQTT、TinyML、图片接线识别、复杂机器学习模型或手机 App。前端不得直接访问数据库或 AI Provider，AI 不得直接执行硬件控制。

## 9. 待补充事实

- `TODO[待补充]: AI Provider、API 基址与模型名`
- `TODO[待补充]: ESP32 具体型号`
- `TODO[待补充]: DHT11 标准接线与 GPIO 规范`
- `TODO[待补充]: Wi-Fi 名称和密码（仅本地私密配置）`
- `TODO[待补充]: 数据库生产密码`
- `TODO[待补充]: 学生、教师和管理员账号策略`
- `TODO[待补充]: 课程实验手册与知识库来源及授权范围`
- `TODO[待补充]: 学校接口与校园网部署限制`
- `TODO[待补充]: 试运行班级、人数和验收指标`

## 10. 成功演示

最终至少证明三个场景：正常 DHT11 数据闭环、DHT11 读取失败的完整诊断闭环、AI Provider 关闭时的规则诊断降级。模拟器数据必须明确标记为测试数据，不得冒充真实设备或试运行结果。
