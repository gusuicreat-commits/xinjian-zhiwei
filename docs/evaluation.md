# 测试与评测操作指南

本文维护检查依赖与运行命令。验收规则见 [开发准则](development-guidelines.md#validation)，要求与测试入口见 [评测要求对应表](evaluation-requirements.md)，报告格式见 [测试报告约定](test-reporting.md)。

## 1. 每层检查能证明什么

| 层次 | 实际入口 | 证明范围与限制 |
| --- | --- | --- |
| 静态与构建 | Ruff、前端 lint/type-check/build、安全扫描 | 代码与构建约束；安全扫描不等于完整依赖漏洞审计 |
| 后端与模拟器 | `backend/tests/`、`simulator/tests/` | 合成输入、Mock Provider、SQLite/隔离 PostgreSQL 上的软件行为；缺测试 DSN 时部分 PostgreSQL 测试会跳过 |
| 合成诊断 | `app.cli.run_synthetic_evaluation` | 规则、候选、引用、动作和渲染输出的确定性检查；不调用真实 Provider，不作自动语义判定 |
| 实验包与知识 | `verify_experiment_packages`、`verify_structured_knowledge`、`verify_v2_evidence_workflow` | Schema、引用、版本、测试边界和固定流程；包内正常样例不代替完整运行状态验证 |
| PostgreSQL 流程 | `app.cli.run_workflow_evaluation --postgres` | 真实路由、诊断图、业务表和 Checkpoint 的合成流程；连接重建不等于断电或任意进程崩溃验证 |
| 浏览器 Mock API | `npm run test:e2e` | 页面行为；不能证明真实后端联通 |
| 浏览器真实后端 | `npm run test:e2e:integration` | 浏览器 → FastAPI → LangGraph → PostgreSQL；身份与设备数据为合成，Provider 为 Mock |
| 离线审阅包 | `npx playwright test --config playwright.review.config.ts` | 独立构建的前端审阅页面；不连接真实后端 |
| 固件 | `check_firmware_protocol.py`、PlatformIO、`test_firmware_host.py` | 协议样例、实际编译、LittleFS 初始镜像构建、主机 I/O 故障模拟（含慢网络采样间隔、启动等待、HTTP/HTTPS配置矩阵）；不代替 ESP32 闪存、断电、接线和无线网络实测 |
| 版本 | `check_version.py` | 应用版本、资料包内容与版本、指定当前文档版本；不代表软件或资料已发布 |

本项目当前不执行向量召回评测。真实模型语义、硬件因果与教学效果分别需要独立材料和验收，不能从软件通过率推导。

## 2. 完整本机门禁

从仓库根目录运行 [scripts/verify.sh](../scripts/verify.sh)。需要：

- Python 3.10+ 环境，安装 `backend/requirements.lock`、后端和模拟器包以及 pytest、Ruff；Python 3.10 还需要 tomli。脚本统一使用 `BACKEND_PYTHON` 所在目录的 pytest/Ruff，并不使用另一套模拟器虚拟环境。
- Node 满足 `frontend/package.json` 的 engines（当前 `>=22.12.0`），通过 `npm ci` 安装锁定依赖及 Playwright Chromium。
- 专用测试 PostgreSQL，能创建临时 schema，并具备历史迁移所需的 vector 扩展。不能指向正在运行的业务数据库。
- PlatformIO（CI 固定为 6.1.19）、对应固件工具链、`tool-mklittlefs` 与 C++ 编译器；首次构建需取得锁定依赖。

```bash
export BACKEND_PYTHON=/absolute/path/to/venv/bin/python
export FIRMWARE_PIO=/absolute/path/to/pio
export XINJIAN_BACKUP_TEST_CONTAINER=explicit-isolated-postgres-container
export XINJIAN_EVAL_POSTGRES_DSN='postgresql://test_user:test_password@127.0.0.1:5432/test_database'
scripts/verify.sh
```

容器名与连接串是占位示例，必须选择隔离环境。恢复测试将在指定容器内创建并删除一次性数据库；缺少容器配置时完整验证退出2，不把恢复测试跳过当通过。脚本不回退到 `DATABASE_URL`；缺少评测 DSN 时生成 `blocked` 流程报告并退出 2。`TEST_DIAGNOSIS_CHECKPOINT_DSN`、`TEST_AI_QUOTA_POSTGRES_DSN` 未配置时继承这个明确指定的测试 DSN；若分别指定，也必须使用隔离测试库。

脚本先准备测试数据库，再依次执行后端/模拟器、合成及结构化知识、协议、PostgreSQL 流程、版本、安全、固件和前端检查。任何步骤失败即停止；要结合日志判断哪些后续项目未执行。不要把最后一份历史报告误作本次未运行步骤的结果。

数据库准备脚本会在测试库 `public` 中创建 vector 扩展；若扩展已位于其他 schema，则明确失败，不自动迁移。它不是向量检索功能。

流程报告默认是 `output/workflow-evaluation/local-latest.json` 及同名 Markdown，可用 `WORKFLOW_EVALUATION_REPORT` 改名。固定文件名会被新运行覆盖；需保留失败取证时先采用独立输出名。详见 [测试报告约定](test-reporting.md)。

`verify.sh --docker` 在测试后执行 Compose 构建和启动，**会触发后端启动迁移并操作所选 Compose 环境**；它不是纯测试模式。只做软件验收时不要添加该参数。

## 3. 分层定位失败

以下命令在仓库根目录、已激活所需 Python 环境后执行。单独运行一层不能称为完整验收。

```bash
ruff check backend simulator scripts/prepare_evaluation_postgres.py scripts/database_backup.py
PYTHONPATH=backend python -m pytest backend/tests
PYTHONPATH=simulator python -m pytest simulator/tests
PYTHONPATH=backend python -m app.cli.run_synthetic_evaluation
PYTHONPATH=backend python -m app.cli.verify_experiment_packages
PYTHONPATH=backend python -m app.cli.verify_structured_knowledge
PYTHONPATH=backend python -m app.cli.verify_v2_evidence_workflow
PYTHONPATH=backend python scripts/check_firmware_protocol.py
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation \
  --postgres --output output/workflow-evaluation/local-latest.json
python scripts/check_version.py --base-ref HEAD
scripts/security_scan.sh
pio run -d firmware/esp32_dht11
pio run -d firmware/esp32_dht11 -t buildfs
python scripts/test_firmware_host.py
```

```bash
cd frontend
npm ci
npx playwright install chromium
npm run lint
npm run type-check
npm run test -- --run
npm run build
npm run test:e2e
npm run test:e2e:integration
npx playwright test --config playwright.review.config.ts
```

浏览器默认使用锁定 Playwright 对应的 Chromium；专门测试系统 Chrome 时分别设置 `E2E_CHROME_CHANNEL=chrome` / `INTEGRATION_CHROME_CHANNEL=chrome`。页面断言通过但 worker 退出超时，仍属失败。

真实联调必须提供 `BACKEND_PYTHON` 和测试 DSN，创建随机 schema、执行 Alembic、启动回环地址后端；退出时清理并验证 schema 删除。默认前端端口 15173、后端 18101，可用 `INTEGRATION_FRONTEND_PORT` / `INTEGRATION_BACKEND_PORT` 修改；不复用现有服务。Mock API E2E 默认可复用本地 Vite，必要时核对服务确属本次源码。

版本脚本本机默认比较 `HEAD`；检查已提交的一系列改动时应通过 `--base-ref` 或 `VERSION_BASE_REF` 指定其之前的基线，不能用待验收提交自身来证明版本递增。它比较资料包规范化内容哈希和 `scripts/package_versions.json`，并检查 README、真实性看板、实现状态中的指定当前版本表述；不扫描任意历史文字。基线缺失会失败，不应通过刷新哈希绕过版本升级。

## 4. CI 与环境差异

[CI 配置](../.github/workflows/ci.yml) 使用 Linux、Python 3.12、Node 22、pgvector PostgreSQL 16；`APP_ENV=test`。健康测试独立注入 development/test 设置，不依赖本地 `.env`。

- `verify` 作业运行软件检查、真实 PostgreSQL 流程、迁移与 Checkpoint 设置、前端及真实联调。
- `firmware` 作业独立运行协议检查、PlatformIO 编译、LittleFS 镜像构建和主机故障回归。
- CI 版本基线来自 PR base SHA 或 push 前 SHA，checkout 获取完整历史。新仓库或异常基线不能视为已验证。
- 流程报告、浏览器报告按现有配置上传 artifact，保留 14 天；报告存在不等于对应步骤成功。

本机通过、CI 已配置、远端 CI 实际通过是三种不同结论；必须给出对应运行记录。人工语义、真实硬件和课堂验证不在这些 CI 作业中。

## 5. 迁移、部署与真实验收

迁移变更在隔离库验证空库升级、涉及的历史版本升级、历史记录保留、单一 Head 和 `alembic check`。同版本的模型检查不能代替历史升级测试。默认 `verify.sh` 不等于目标环境迁移验收，部署操作见 [部署说明](deployment.md)。

真实上线还需结合目标环境验证备份恢复、持久化 Checkpoint、凭据撤销、班级隔离、无 Key 降级和监控；并按 [硬件验证计划](hardware-validation-plan.md) 记录板卡、固件、接线、原始采样、独立真值和恢复证据。规则调整数据与验收样本应隔离。

## 6. 失败定位

失败先区分实现缺陷、预期过期、环境受阻和材料缺失，再按 [如何修复 Bug](development-guidelines.md#fix-bugs) 处理。对应反例查 [规则入口表](development-guidelines.md#rule-map) 和 [评测要求表](evaluation-requirements.md)。

当前范围和未完成事项查 [实现状态](implementation-status.md) 与 [真实性看板](project-truth-status.md)；历史失败依据从 [评测要求表](evaluation-requirements.md) 的对应编号追溯，不用历史数量补成本次未运行的结果。

## 受控上下文独立评测

执行 `PYTHONPATH=backend "$BACKEND_PYTHON" -m app.cli.run_context_evaluation --output output/context-evaluation/latest.json`。输入 `backend/evaluation/context_inputs.json` 与独立期望 `context_expectations.json` 分离；仅评测器读取期望。当前11个样本均为合成回归，覆盖资格与完整打包，真实语义和独立保留集待验收。服务级关联、来源、缓存、预算、重放及破坏反例运行 `PYTHONPATH=backend "$BACKEND_PYTHON" -m pytest backend/tests/test_context_construction.py backend/tests/test_context_evaluation.py`；跨链路仍执行完整门禁，不能只凭该CLI交付。

<a id="package-context-preview"></a>
## 资料包调用预检

P0–P3提供无数据库写入、无Provider调用的预检，复用运行时资格筛选、投影及推理/解释的实际Prompt builder。仓库根目录执行：

```bash
PYTHONPATH=backend python -m app.cli.preview_package_context --strict \
  --expectations backend/evaluation/package_context_expectations.json
```

默认输入是`backend/evaluation/package_context_inputs.json`，预期独立保存在expectations；严格模式已加入`verify.sh`。报告写`output/package-context-preview/latest.json`及Markdown。`--package`可指定显式包目录，`--inputs`指定合成场景，`--budgets`指定允许的预算JSON，`--trusted-sources`提供显式来源身份快照，`--output`保存独立报告；不按来源登记自动抓文件/URL。

退出0表示分析完成（普通模式可含省略/降级）或严格断言全部通过；解析/执行/断言错误退出1，缺必需材料退出2。结构、来源身份和阶段覆盖分别记录，包含真实阶段ID/省略原因、清洗长度、完整Prompt估算和指纹。来源不可取得为unverifiable；身份比对成功不等于内容语义真实。报告固定标offline_fixture、权限not_evaluated、真实Provider/语义/硬件未运行。

双阶段实际Mock请求与隐私、旧call-stage及并发重放、冻结工作流建议、1.0hash兼容和派生影响在`test_package_context_runtime.py`、`test_r2_provider_data_boundary.py`、`test_current_advice.py`、`test_case_applicability.py`、`test_package_registry.py`、`test_package_context_preview.py`断言。预检报告不代替这些运行服务边界检查。

## 内部测试准备与演练

`test_internal_experiment_cli.py`与`test_internal_experiment_preparation.py`验证显式目标、授权、重复、冲突及回滚；`test_internal_experiment_preparation_postgres.py`验证真实PostgreSQL的并发与锁后复核。`test_internal_experiment_drill.py`从空实验schema经管理员包API、准备CLI和学生/设备API走完整合成流程，设置`XINJIAN_INTERNAL_DRILL_REPORT`可留脱敏成功过程。上述均被后端全量测试收集；缺测试DSN会跳过PostgreSQL层，不能称完成。

真实浏览器联调另含新初始化任务的学生选择、开始、资料展示和结束用例。演练与旧有8项流程分别有实际结果，不能把数据库published、合成记录、AI skipped审计行数当实物验收或真实Provider调用。操作入口见[内部准备说明](experiments/internal-lab-preparation.md)。


### 显式配置容量预检

`preview_package_context --profile /path/to/profile.json`接收完整白名单快照（由`context_preview.snapshot_preview_profile(settings, source="runtime_snapshot")`生成），不接收密钥或整个Settings导出。也可标记`candidate_profile`比较有界候选预算。显式配置与场景预算冲突会失败；应另建无冲突合成场景，不修改既有冻结输入。报告中的来源标签由调用方声明，仍需记录实际服务/版本/生成时间，不能当作已经部署。推理与解释分别报告准入，`prepared`不代表真实Provider已调用。

### 教师与课堂独立验收

使用[本轮交接说明](../output/audits/ai-capacity-semantic-followup-20261004/teacher-acceptance.md)和[空白记录模板](../output/audits/ai-capacity-semantic-followup-20261004/teacher-acceptance-template.json)准备真实验收，逐项判据仍唯一引用`semantic_rubrics.json`。教师先冻结真实来源、课程允许动作及独立预期，再运行待验版本；预期不进入Provider。合成开发回归、教师语义判断、实物恢复和课堂可用性分别记录，缺材料保持null/not_run，不自动签署通过。
