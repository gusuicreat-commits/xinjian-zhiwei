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
- 对实际渲染的解释记录短语出现情况，仅供审阅，不以命中或未命中判定语义；
- Episode 重复故障按预期聚合；
- 默认评测不调用真实 AI Provider。

阈值针对提交的确定性合成规则设为严格通过，不应解释为真实世界准确率。

自 2026-09-15 起，合成报告版本为 `7-code-and-semantic-separated`，原顶层 passed 改为 code_checks_passed，原 forbidden_claims 改为无判定的 pattern_scan。semantic_review 逐条记录 Rubric 的 not_run/null；代码通过但语义未审阅时总体 status=incomplete，代码失败时为 failed。CLI 退出码 0 只表示确定性代码检查通过；verify 脚本同样仅承诺代码门禁，不代表语义、硬件或课程通过。消费旧 JSON 字段的调用方须同步更新，历史报告不改写。

### 前端与端到端测试

- 学生和教师关键页面、状态投影和错误降级。
- 反馈必需会话头与请求 UUID；同一提交的重试保持载荷，刷新恢复未决记录，真实新尝试使用新键，晚响应不跨会话回填。
- 浏览器记录丢失后，按有效实验会话纯读找回服务端未决记录；只有明确点击才恢复原请求，较早诊断与原备注同样保留。
- 合成身份登录、诊断反馈、请求教师帮助、教师认领/解决/关闭和学生端回显。
- 就绪状态不因演示数据被错误提升为生产 ready。

## 3. 标准运行方式

完整本地门禁需要专用测试 PostgreSQL、后端虚拟环境、模拟器虚拟环境、已安装的前端依赖和 Playwright 浏览器。在仓库根目录执行：

```bash
export BACKEND_PYTHON=/absolute/path/to/backend/venv/bin/python
export XINJIAN_EVAL_POSTGRES_DSN='postgresql://test_user:test_password@127.0.0.1:5432/test_database'
scripts/verify.sh
```

以上连接串是占位示例，须换成隔离测试库。脚本不会回退到应用的 `DATABASE_URL`；缺少评测 DSN 时写出 `blocked` JSON 并退出 2，不跳过后宣称全量通过。`TEST_DIAGNOSIS_CHECKPOINT_DSN` 未配置时只继承这个明确指定的测试 DSN。

脚本依次运行数据库准备、Python 静态检查、后端测试、模拟器测试、合成诊断、实验包、结构化知识、V2 工作流、25 场景 PostgreSQL 评测、安全扫描，以及前端 lint、类型、单元、构建、Mock API E2E 和浏览器真实联调。报告默认写入 `output/workflow-evaluation/local-postgres.json`，可用 `WORKFLOW_EVALUATION_REPORT` 改路径；历史失败报告不覆盖。

`scripts/prepare_evaluation_postgres.py` 在指定测试库的 `public` 中准备历史迁移所需的 vector 扩展；已有扩展在其他 schema 时明确失败，不自动迁移扩展。此步骤不是启用向量检索。

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
npm run test:e2e:integration  # 需上述测试 DSN 与 BACKEND_PYTHON
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

前轮修复三项缺口并扩展为 **25 个 PostgreSQL 场景，25 passed**，该次报告为 `output/workflow-evaluation/remediation-postgres.json`。原三项 strict xfail 已移除，反馈副作用、重放响应与关联证据篡改必须使门禁失败。负责人摘要、兼容变化及本轮新结果见 [整改报告](workflow-remediation.md)。

## 9. 反馈可靠性与前轮迁移验收

- 42 项可靠性测试通过：同请求并发、成功回执丢失、已消费反馈补确认、未消费反馈恢复，以及关闭会话边界。
- Checkpoint `put` 的 6 个失败点与 `put_writes` 的 8 个失败点分别在 SQLite/PostgreSQL 验证，共 28 项故障注入；成功后不重复反馈或调用。
- PostgreSQL 已验证空库升级、0026 带历史反馈升级至 0027、单 Head、模型差异检查和重复键拒绝；旧反馈关联保持 NULL。
- 前端 43 项单元测试和 4 项学生页面 Chrome E2E 通过，类型、lint、生产构建通过。E2E 使用 Mock API，不能冒充浏览器与真实后端联合验收。
- 后端全量：330 passed，无 skipped/xfail；40.34 秒，1 项 Starlette/anyio 依赖弃用警告。完整流程 CLI、迁移、前端与后端回归分别计数，不相互替代。

同步 Checkpoint 与补确认解决具体恢复窗口，不代表数据库和 Saver 已有跨存储原子事务；连接/图重建、注入保存错误也不等于进程 kill、断电或生产负载验收。当前尚未部署或推送 GitHub。

## 10. 反馈找回、CI 与真实浏览器联调

GitHub CI 已配置 25 场景 PostgreSQL 评测，并使用 `always()` 上传该步 JSON 报告（保留 14 天）。缺环境记录 blocked、未运行记录 not_run/incomplete、断言失败记录 failed，均不能作为通过。上传范围只包含流程 JSON，不包含浏览器 trace、凭据或数据库连接串。配置已更新不等于 GitHub 托管 runner 已执行，本轮只报告本机结果。

新增真实联调使用浏览器 → 实际 FastAPI 路由 → 实际 LangGraph → PostgreSQL 业务表和 Checkpoint。设备数据与身份为合成，AI Provider 使用 Mock；不是硬件或真实模型验收，也不是生产部署。

| 场景 | 独立验证点 |
| --- | --- |
| 登录、上报、首次诊断、反馈及刷新 | 实际数据库有 Evidence；反馈只保存一条；原 UUID 重放后状态、调用记录和 Evidence 不变 |
| 未决反馈、关页、重新登录、找回与确认 | 浏览器 sessionStorage 为空；GET 后数据库不变；点击后沿用原 UUID，反馈/恢复次数仅增加一次 |

入口为 `npm run test:e2e:integration`。测试脚本通过独立 CLI 创建随机 schema，执行真实 Alembic 到 Head，再启动仅监听回环地址的 Uvicorn；没有向生产 API 加故障注入端点。每个 schema 先创建独立版本表并校验业务表归属，避免误用已迁移的 public 表。故障窗口使用测试进程的临时控制文件；退出时清理并断言 schema 已删除。

前端默认端口 15173、后端 18101，可用 `INTEGRATION_FRONTEND_PORT` / `INTEGRATION_BACKEND_PORT` 修改；不复用现有服务。CI 安装并使用 Chromium，本机可设置 `INTEGRATION_CHROME_CHANNEL=chrome` 使用已安装 Chrome。本地浏览器报告为 `frontend/playwright-report/integration/results.json`。后端找回专项另外覆盖旧诊断、原备注、越界、关闭会话、旧 NULL 记录及超过 20 条的分页边界。

当前代码没有新增数据库迁移；Head 仍为 `20260912_0027`。本轮执行数量与结果集中记录在 [整改报告](workflow-remediation.md) 的“反馈找回与持续验收”。

## 自动报告的存放与详略

流程 CLI 默认输出简明 JSON 和同名 Markdown；失败细节单独 gzip 保存。报告不再混入源码变更，详见 [测试报告约定](test-reporting.md)。原始内存检查及退出码不变；需要全部快照时使用 `--details all`。旧报告原地保留。
