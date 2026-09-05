# 芯鉴知微

面向高校嵌入式与物联网实验课程的证据驱动诊断平台。系统接收真实设备状态、日志和传感器数据，用确定性规则识别异常，用故障树限定原因空间，用结构化知识提供实验约束，再由受约束 AI 辅助排序和生成学生可理解的建议。

当前版本保留既有设备接入、规则诊断、教师处置和前端功能，并已升级为状态驱动的 LangGraph 工作流。第一阶段不使用 RAG、Embedding 或向量检索作为诊断链路。

> 当前仓库可以完成合成数据下的端到端验证，但尚未获得完整真实硬件资料、正式知识和课堂真值数据，因此不能宣称已验证真实硬件故障诊断能力。

## 诊断主链

```text
设备数据
  -> DiagnosisContext / DiagnosisState
  -> 规则引擎
  -> 故障树候选原因
  -> 推理前结构化知识供给
  -> 受约束 AI 原因排序
  -> 推理后知识校验
  -> 结构化解释与排查步骤
  -> 学生反馈 / 提示升级 / 教师介入
```

AI 不覆盖规则结果，不引入候选集合外的原因，只能引用本次诊断真实落库的证据 UUID；证据不足、模型不可用或输出不合规时返回 `unknown` 或使用确定性降级。

## 主要能力

- 设备日志、传感器读数和心跳的认证、批量接入、幂等与乱序处理。
- 统一 `DiagnosisContext`、规则引擎、故障树和标准证据模型。
- LangGraph 状态流转、反馈循环、提示升级和教师审核暂停点。
- 推理前 Knowledge Context 与推理后 Knowledge Validation。
- Experiment Package：硬件、证据映射、规则、故障树、案例、教学内容和测试独立于 Python 代码。
- DHT11 与 LED 两个合成示例包；其内容明确标记为测试数据，不代表真实硬件验收。
- 学生诊断反馈与教师工单闭环。
- 虚拟设备场景、合成评测、就绪状态和部署门禁。

## 本地运行

准备本地配置后启动：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

默认地址：

- 学生/教师前端：`http://localhost:8080`
- API：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- 就绪页：`http://localhost:8080/readiness`
- 健康检查：`http://localhost:8000/health/ready`

后端启动时自动执行 Alembic 升级。历史初始迁移依赖 PostgreSQL `vector` 扩展，因此 Compose 使用 pgvector 镜像；当前业务代码并不运行向量检索。

## 合成演示

创建一组带 `is_test_data=true` 的演示身份和数据：

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-
```

终端输出的设备 ID/令牌用于学生端，用户名/密码用于教师端。凭据只显示一次，不会写入 Git。演示和清理流程见 [演示手册](docs/demo-runbook.md)。

## 验证

运行完整本地门禁：

```bash
scripts/verify.sh
```

如默认虚拟环境不满足 Python 3.10+，可显式指定解释器：

```bash
BACKEND_PYTHON=/path/to/python scripts/verify.sh
```

数据库/部署变更还应运行：

```bash
docker compose build
docker compose up -d
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend alembic check
```

## 当前数据边界

- 仓库中的实验包、场景、知识和 AI 响应均是合成或 Mock 测试资料。
- 缺少真实设备、BOM、原理图、GPIO/供电规范、故障真值和教师正式审核时，具体参数必须保持可配置或待确认。
- AI 默认关闭，仓库不包含真实 Provider Key。
- 历史向量表、Embedding 字段和 `needs_rag` 等兼容结构暂时保留，用于读取旧记录，不属于当前诊断主链。

## 开发入口

后续开发前请先阅读：

- [文档索引](docs/README.md)
- [开发准则](docs/development-guidelines.md)
- [系统架构](docs/architecture.md)
- [AI 诊断设计](docs/ai-diagnosis-design.md)
- [Experiment Package 设计](docs/experiment-package-design.md)
- [当前实现状态](docs/implementation-status.md)

安全要求：只提交 `.env.example`；禁止提交密钥、令牌、密码、证书、生产连接串和真实个人数据。原始知识资料、数据库备份、虚拟环境、构建产物及测试报告应保持在 Git 忽略范围内。
