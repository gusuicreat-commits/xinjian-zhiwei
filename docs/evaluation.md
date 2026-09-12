# 测试与评测准则

最后更新：2026-09-12

## 1. 评测边界

仓库内自动评测全部使用合成、Mock 或明确测试标记的数据，只证明代码符合已提交的 Schema、规则、状态流转和安全约束。它不能证明真实硬件诊断准确率、传感器参数正确性、教师知识有效性或生产环境可用性。

第一阶段不评测向量召回，不保留 Recall@K、MRR、RRF 或 Embedding 基线。当前知识验收关注结构化字段匹配、版本隔离、审核状态和推理前/推理后约束。

## 2. 自动化测试层次

### 静态和构建门禁

- Ruff：后端、迁移、CLI 和模拟器静态检查。
- Python 3.10+ 运行时检查。
- ESLint、TypeScript 类型检查、Vitest 和前端生产构建。
- 安全扫描与项目版本一致性检查。

### 后端行为测试

- 设备认证、批量幂等、序列冲突、时间质量、限流和定向测试数据清理。
- `DiagnosisContext` 归一化、规则命中、故障树排序、Episode 聚合和重复调用不升级。
- Experiment Package 严格 Schema、跨文件引用、内容哈希、状态流转、运行时版本锁定和证据落库。
- LangGraph 节点顺序、Checkpoint、暂停恢复、反馈分支、教师审核和确定性降级。
- AI 原因只能来自候选集合，证据只能来自本次诊断实际落库的证据 UUID，错误类型不可覆盖。
- 原因引用还须属于该候选实际匹配的证据集合，不得借用当前诊断中的无关 UUID。
- 推理前知识供给和推理后知识校验；错误实验、错误类型、未审核、未锁定事实和测试数据不得越界。
- 案例草稿的事实锁定、AI 表达字段限制和教师确认发布。
- 学生/教师认证、班级范围、处置乐观锁和私人备注隔离。

### 合成诊断评测

`backend/evaluation/golden_cases.json` 当前包含 30 个确定性用例，覆盖正常、读取失败、离线、数值越界、边界值、未知事件和多规则冲突。门禁包括：

- 错误类型精确匹配；
- 原因 Top-1 / Top-3 与必需排查步骤；
- 无证据时不得产生高置信结论；
- 对实际渲染的确定性解释做禁止短语扫描，0 命中；该项不等于语义评价；
- Episode 重复故障按预期聚合；
- 默认评测不调用真实 AI Provider。

阈值针对提交的确定性合成规则设为严格通过，不应解释为真实世界准确率。

### 前端与端到端测试

- 学生和教师关键页面、状态投影和错误降级。
- 反馈必需会话头与请求 UUID；同一提交的重试保持载荷，刷新恢复未决记录，真实新尝试使用新键，晚响应不跨会话回填。
- 合成身份登录、诊断反馈、请求教师帮助、教师认领/解决/关闭和学生端回显。
- 就绪状态不因演示数据被错误提升为生产 ready。

## 3. 标准运行方式

完整本地门禁：

```bash
scripts/verify.sh
```

该脚本依次运行 Python 静态检查、后端测试、模拟器测试、合成诊断评测、实验包校验、结构化知识校验、V2 证据工作流校验、安全扫描，以及前端 lint、类型、单元、构建和 Playwright 测试。

分层执行：

```bash
cd backend
ruff check app tests
pytest -q
python -m app.cli.run_synthetic_evaluation
python -m app.cli.verify_experiment_packages
python -m app.cli.verify_structured_knowledge
python -m app.cli.verify_v2_evidence_workflow

cd ../simulator
pytest -q

cd ../frontend
npm run lint
npm run type-check
npm run test -- --run
npm run build
npm run test:e2e
```

## 4. 数据库和部署验收

迁移变更必须同时验证空库升级、现有库升级、单一 Head 和模型差异：

```bash
docker compose build
docker compose up -d
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend alembic check
```

历史初始迁移会创建 `vector` 扩展，因此测试和 Compose 数据库镜像必须提供该扩展；这只是迁移兼容条件，不是 RAG 功能验收。

生产前还必须演练：

- PostgreSQL 备份和隔离恢复；
- 无公网、无 AI Key 时的确定性诊断；
- Provider 超时、限流、非法 JSON 和越界证据的降级；
- 服务重启后的 LangGraph Checkpoint 恢复；
- 凭据撤销、班级隔离和审计查询；
- 磁盘、数据库、队列/请求积压和错误率告警。

## 5. 真实硬件验收要求

正式准确性结论至少需要：

1. 明确板卡、传感器、固件、接线、GPIO、供电和环境版本；
2. 带时间戳的原始设备数据和不可变真值标签；
3. 正常、典型故障、复合故障、证据不足和恢复样本；
4. 由教师或硬件负责人确认的根因和最终修复动作；
5. 预先约定的误报率、漏报率、Top-K、诊断时延和教师介入目标；
6. 测试集与知识整理、阈值设定数据隔离；
7. 按实验包版本、硬件版本和规则版本分层报告结果。

未满足以上条件时，只能报告“合成门禁通过”，不得报告“诊断准确率已达到生产要求”。

## 6. 失败处理

任一强制门禁失败时不得通过删除测试、放宽白名单、降低真实性标记或恢复旧 RAG 逻辑绕过。应先判断是代码回归、测试预期过期、缺少外部资料还是环境故障，再修复根因并记录验证命令和结果。

## 7. 第一阶段评测可信化（2026-09-12）

要求、测试和依据见 [评测要求对应表](evaluation-requirements.md)。本轮采用 ClawEval 的精确校验与证据选择原则，不引入其固定任务目录或模型裁判。

- 合成评测版本为 `6-rendered-output-contract`，每条结果记录实际渲染解释；`forbidden_claims.scope` 指明扫描范围，`semantic_review=not_run`。
- high 无有效引用、隐藏输入冲突、白名单外步骤会被校验拒绝；无关联证据的降级结论为 unknown。
- 最终解释摘要/限制由后端生成；缓存和历史重放不绕过当前输出边界。具体兼容行为和未覆盖的推理自由文本见对应表。
- 包内故障样例检查异常类型集合精确一致；包内正常样例不证明完整运行状态，候选成员校验不证明排序正确。
- 原 100 次重复结构样例改为明确的合法/非法样例；不报告真实模型输出合格率。

专项回归：`cd backend && python -m pytest tests/test_evaluation_contract.py tests/test_ai_diagnosis.py tests/test_diagnosis_workflow_security.py`。

## 8. 完整流程评测（第二阶段）

独立 CLI 通过真实路由和诊断图运行合成场景并输出可追溯 JSON；参考答案独立于被测输入。第二阶段最初 16 场景的 13 passed / 3 failed 保留在 [历史失败基线](workflow-evaluation-phase2.md)，不改写原记录。

本轮修复三项缺口并扩展为 **25 个 PostgreSQL 场景，25 passed**，最新报告为 `output/workflow-evaluation/remediation-postgres.json`。原三项 strict xfail 已移除，反馈副作用、重放响应与关联证据篡改必须使门禁失败。负责人摘要、兼容变化及全部结果见 [整改报告](workflow-remediation.md)。

## 9. 反馈可靠性与本轮迁移验收

- 42 项可靠性测试通过：同请求并发、成功回执丢失、已消费反馈补确认、未消费反馈恢复，以及关闭会话边界。
- Checkpoint `put` 的 6 个失败点与 `put_writes` 的 8 个失败点分别在 SQLite/PostgreSQL 验证，共 28 项故障注入；成功后不重复反馈或调用。
- PostgreSQL 已验证空库升级、0026 带历史反馈升级至 0027、单 Head、模型差异检查和重复键拒绝；旧反馈关联保持 NULL。
- 前端 43 项单元测试和 4 项学生页面 Chrome E2E 通过，类型、lint、生产构建通过。E2E 使用 Mock API，不能冒充浏览器与真实后端联合验收。
- 后端全量：330 passed，无 skipped/xfail；40.34 秒，1 项 Starlette/anyio 依赖弃用警告。完整流程 CLI、迁移、前端与后端回归分别计数，不相互替代。

同步 Checkpoint 与补确认解决具体恢复窗口，不代表数据库和 Saver 已有跨存储原子事务；连接/图重建、注入保存错误也不等于进程 kill、断电或生产负载验收。当前尚未部署或推送 GitHub。
