# 芯鉴知微

面向高校嵌入式与物联网实验课程的实时日志分析、确定性诊断、知识检索和教师处置平台。

当前源码与 Docker 运行版本为 `1.0.0`。《无真实硬件条件下后续开发总路线》的 P1–P11
通用框架已经完成；需要人工提供的真实硬件资料、正式知识、正式课堂数据和生产参数没有
被猜测或自动生成，统一显示为待提供或受阻。

> 当前结论：系统可完成测试设备协议接入、合成场景复现、示例规则诊断、知识治理、
> 学生/教师端展示和运维验收，但**没有真实设备数据，不具备已验证的真实硬件故障诊断
> 能力**。

## 当前能力

### 设备协议与虚拟实验室

- `POST /api/v1/device/ingest` 支持日志、读数和心跳的原子批量上报。
- 使用 UUID `requestId`、载荷哈希、`bootId + sequenceNo` 实现持久化幂等和冲突检测。
- 乱序数据保留历史但不回退设备当前状态；设备时间不可信时标记
  `server_fallback`。
- 旧单条上报接口继续兼容；每设备批次、请求体和速率均有限制。
- 模拟器提供 10 个版本化 YAML 合成场景，以及校验、运行、重放、报告和按运行清理。
- 所有模拟数据强制标记为测试数据；多设备凭据必须由人工配置。

### 诊断、评测与 AI

- 统一 `DiagnosisContext` 从日志、心跳、读数和可选实验模板构造确定性输入。
- 版本化 Experiment Definition、统一 Observation/Event Normalizer、Expected Behavior 和
  common/interface/component/experiment 作用域规则与故障树已接入；新增实验默认是配置任务。
- YAML 示例规则和占位故障树生成可追溯证据、候选原因和 Level 1–4 提示。
- 合成基线包含 30 个诊断、54 个检索和 6 个禁止性陈述测试；检索直接调用生产同源
  `hybrid_retrieve`，门禁为 Recall@5 不低于 80%。
- AI 通过统一客户端、严格 Schema、缓存、预算、审计和确定性降级隔离 Provider。
- Phase 9.5 默认对话路由选择 DeepSeek 兼容配置，但 `AI_ENABLED=false`，仓库没有真实
  Key，本轮没有真实或收费调用。
- Embedding Provider/模型/维度尚未确认；未配置时不会伪造向量。
- LangGraph 将上下文、规则、故障树、RAG、受治理 AI 和教师审核组成可恢复状态图；LangChain 只作为结构化 Runnable 和只读工具适配层。
- 学生端可显式启动辅助诊断；Level 4、低证据分或知识不足时暂停，由有班级范围的教师批准、修订或驳回。

### 课堂、模板、知识和教师处置

- 用户、角色、权限、课程、班级、选课、授课、实验任务和设备绑定模型已建立。
- 实验模板与规则/故障树工件支持版本化审核发布；缺失字段或 TODO 参数不能发布，
  已发布版本不可修改。
- 知识工作区支持 TXT、Markdown、CSV、DOCX 和可提取文本的 PDF；支持草稿编辑、
  切分、合并、删除、元数据和六状态审核。
- 扫描 PDF 无可提取文本时明确失败，当前没有实现或伪装 OCR。
- 教师处置支持认领、备注、转交、解决、关闭、乐观锁、私人备注隔离、课堂消息撤回、
  时间线和 CSV 审计。
- 已绑定学生身份的设备在学生端选择“请求教师协助”后，会自动创建班级范围的教师工单；
  教师端可认领、填写公开解决说明并关闭，学生端会回显“等待认领 / 处理中 / 已解决 /
  待补充证据 / 已关闭”状态。未绑定学生与班级的设备仍只保存反馈和 Episode 升级状态，
  不会伪造工单归属。
- 正式用户、班级、模板、知识和处置记录当前均为 0。

### 前端与交付

- 学生端显示任务占位、设备状态、日志、趋势、诊断证据、提示和反馈；异常卡片新增
  确定性优先的设备状态解释，并可折叠查看原始错误码、日志、读数、规则与故障树证据。
- 教师端显示设备聚合、异常排行、趋势、介入列表和知识状态。
- 路由懒加载、图表独立分块、日志分页、有限重试、错误分类、最后数据保留、键盘焦点
  与图表文本/表格兜底已完成。
- `/readiness` 展示数据库、协议、虚拟实验室、真实硬件、正式知识、AI、课堂数据和
  生产部署的证据与阻塞项。
- CI 与 `scripts/verify.sh` 覆盖 Python/前端检查、合成评测、安全扫描、生产构建和
  Playwright 端到端测试。

## 当前数据边界

长期 PostgreSQL 中只保留历史阶段的测试/模拟/Mock 验收数据：

| 数据 | 数量 |
| --- | ---: |
| 设备 / 心跳 / 日志 / 传感器读数 | 7 / 12 / 18 / 12 |
| 诊断 / 提示 / 反馈 | 18 / 17 / 2 |
| 合成知识来源 / 文档 / 块 / 向量 / 审核 | 1 / 4 / 4 / 4 / 4 |
| Episode / Mock AI 审计 / 缓存 | 1 / 2 / 1 |
| 合成演示用户 / 课程 / 班级 / 设备绑定 / 角色目录 | 2 / 1 / 1 / 1 / 5 |
| P1 协议批次、正式用户、正式班级、模板、教师处置 | 全部 0 |

没有真实设备数据，没有正式知识，没有真实 AI 调用。当前 YAML 阈值、原因权重和提示
升级条件属于示例规则、占位规则或待确认参数，不是硬件说明书或行业标准结论。

## 就绪状态

运行后访问：

- 前端就绪页：`http://localhost:8080/readiness`
- API：`GET http://localhost:8000/api/v1/readiness/status`
- 存活探针：`GET http://localhost:8000/health/live`
- 就绪探针：`GET http://localhost:8000/health/ready`
- 依赖状态：`GET http://localhost:8000/health/dependencies`

当前预期总体状态为 `blocked`：数据库和协议为 `ready`，虚拟实验室为 `test_only`，
AI 为 `not_required`，真实硬件、正式知识、课堂数据和生产部署为 `blocked`。

## 本地运行

复制无敏感信息的环境模板并替换本地开发占位值：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

服务地址：

- 前端：`http://localhost:8080`
- 后端 API：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- PostgreSQL：只在 Compose 内部网络暴露，不映射宿主机端口。

后端启动前自动执行 `alembic upgrade head`。当前唯一迁移 Head 为
`20260818_0021`。生产 LangGraph 使用 PostgreSQL checkpoint，并在部署步骤单独运行
`python -m app.cli.setup_diagnosis_checkpoints`；开发/测试默认使用内存 saver。

### 登录凭据与三个诊断地址

- 学生页面 `/login` 使用“设备 ID + 设备令牌”。设备 ID 是公开设备标识；令牌创建时
  只显示一次，PostgreSQL 只保存不可逆哈希，因此不能从已有设备记录中找回原令牌。
- 教师页面 `/teacher/login` 使用正式“用户名 + 密码”。登录后由
  `POST /api/v1/auth/session` 签发短期 Bearer 会话；只有 `teacher` 或 `admin` 角色
  能进入教师总览，教师数据按授课班级与设备绑定范围隔离。
- `http://localhost:8000/docs` 是 FastAPI 自动生成的 Swagger 开发者接口文档，可查看
  和调试 API；它不是学生或教师业务页面，受保护接口仍需相应凭据。
- `http://localhost:8080/readiness` 是项目交付就绪门禁，展示真实硬件、正式知识、
  正式课堂数据和生产部署是否具备。它处于 `blocked` 不等于服务宕机。
- `http://localhost:8000/api/v1/health` 是轻量存活接口。返回 200 只证明后端进程能够
  响应及其版本信息，不证明数据库、真实数据、知识或生产条件已经就绪。

可重复生成一组明确标记为合成测试数据的页面登录凭据：

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-ui-
```

输出中的 `student_page_device_id` / `student_page_device_token` 用于学生页；
`teacher_page_username` / `teacher_page_password` 用于教师页。设备令牌与随机密码不会写入
Git；请在终端显示后立即保存到本地密码管理器。`rbac_student_*` 是课堂资源 API 的学生
账号，目前不是设备中心学生总览页的登录方式。

页面闭环演示顺序：

1. 用上述设备凭据进入学生端，打开“诊断与反馈”，点击“请求教师协助”。
2. 学生端显示“求助已提交，等待教师认领”；该请求只会进入设备绑定班级的教师范围。
3. 用上述教师账号进入教师端，在“需要教师介入的设备”中找到“学生主动求助”，依次
   点击“认领”和“解决”，并填写会同步给学生的处理结果。
4. 刷新学生端可看到“教师正在处理”或“教师已标记为解决”及公开处理说明；教师端可在
   已解决后关闭工单。自动 Level 4 建议仍会显示为“系统建议介入”，但不会与同一诊断的
   学生工单重复展示。

## 验证

完整本地门禁：

```bash
scripts/verify.sh
```

LangGraph/LangChain 依赖要求后端 Python 3.10+。如默认 `backend/.venv` 不符合，
重建该虚拟环境，或使用 `BACKEND_PYTHON=/path/to/python scripts/verify.sh`。

Docker 与迁移验收：

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend alembic check
```

合成评测：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.cli.run_synthetic_evaluation
```

备份与隔离恢复演练：

```bash
scripts/backup_database.sh /explicit/new/path/xinjian.dump
scripts/restore_drill.sh /explicit/path/xinjian.dump
```

备份脚本拒绝覆盖已有文件；恢复脚本只使用临时独立数据库，不删除现有数据卷。

## 合成演示

演示命令只创建带指定前缀和 `is_test_data=true` 的对象，不会生成正式用户或真实数据。
密码由命令随机生成并只显示一次：

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-
docker compose exec backend python -m app.cli.reset_demo \
  --prefix demo- \
  --confirm demo-
```

本轮已用 `demo-ui-` 前缀创建一组页面登录测试数据；全部标记
`is_test_data=true` / `synthetic-demo`，不计入正式课堂 readiness。随机凭据只在执行
终端和本轮交付说明中显示，不写入仓库。完整流程见 [演示手册](docs/demo-runbook.md)。

## 仍需人工提供或确认

1. 开发板/传感器与外围器件 BOM、版本、原理图、接线、GPIO、供电和安全限制。
2. 正式字段、单位、量程、精度、采样/心跳/重试策略和错误码。
3. 实验目标、步骤、正常范围、完成条件，以及带真值的正常/故障样本、根因和修复结果。
4. 可授权知识文件、URI、版本、适用硬件、许可证，以及知识整理员与正式批准人的审核结论。
5. 正式用户、课程、班级、角色、任务和设备绑定清单。
6. AI Key、预算/限流、数据外发与保留审批；Embedding 方案。
7. 生产域名、HTTPS、网络、密钥管理、监控、备份责任、保留期限和验收指标。

这些输入未确认时，具体厂商、硬件型号、传感器字段、阈值和生产参数必须继续通过可配置
接口、通用数据模型或明确占位实现，不得写死在核心业务代码中。

## 安全与版本控制

- 只提交 `.env.example`，禁止提交 `.env`、密码、令牌、密钥、证书和生产连接串。
- 原始知识文件放在被 Git 忽略的 `data/knowledge/raw/`；解析中间物放在
  `data/knowledge/processed/`。
- `node_modules`、虚拟环境、缓存、构建产物、Playwright 报告、模拟器报告、数据库文件
  和备份文件均应保持忽略。
- 设备只持有设备凭据，不直接访问 PostgreSQL，也不持有 AI Provider 密钥。
- AI 审计只保存匿名摘要、哈希、计数、路由和安全错误分类，不保存原始密钥或完整
  Provider 错误体。

## 项目文档

- [实现状态与验收结果](docs/implementation-status.md)
- [P1–P11 独立发布审计证据](docs/p1-p11-release-audit.md)
- [设备协议 V1](docs/device-protocol.md)
- [虚拟实验室](docs/simulator-design.md)
- [合成评测](docs/evaluation.md)
- [系统架构](docs/architecture.md)
- [可迁移实验诊断框架与新增实验指南](docs/experiment-diagnostic-framework.md)
- [API 设计](docs/api-design.md)
- [数据库设计](docs/database-design.md)
- [规则诊断](docs/diagnosis-rules.md)
- [故障树与提示](docs/fault-tree-guidance.md)
- [知识库框架](docs/knowledge-base.md)
- [AI 诊断设计](docs/ai-diagnosis-design.md)
- [LangGraph + LangChain 辅助诊断工作流](docs/langgraph-diagnosis-workflow.md)
- [运行架构](docs/runtime-architecture.md)
- [部署说明](docs/deployment.md)
- [演示手册](docs/demo-runbook.md)
- [发布检查清单](docs/release-checklist.md)
