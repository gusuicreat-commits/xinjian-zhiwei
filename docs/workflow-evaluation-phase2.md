# 第二阶段：完整流程评测与问题清单

> 历史失败基线：本页保留第二阶段原始输入、失败结果和当时的整改建议，不代表当前代码仍有相同缺陷。后续修复、兼容变化和最新验收记录见 [完整流程问题整改](workflow-remediation.md)。

日期：2026-09-12。第一阶段基线提交：`97c4d27`。本阶段只新增隔离评测、反例和报告，没有修改生产诊断流程、接口、数据库模型或实验包。

## 项目负责人可读摘要

| 问题 | 本轮结论 |
| --- | --- |
| 发现了什么？ | 流程能够跑通，但发现三处缺口：候选原因借用心跳证据、重复反馈导致重复推进、另一学生的会话可以提交原学生的反馈。 |
| 现实影响是什么？ | 有 UUID 的建议仍可能缺乏相关依据；网络重试可能被算作新尝试并重复调用 AI；原学生的实验状态可能被他人改变。 |
| 现在能解决吗？ | 都属于软件问题，可在后续小范围整改；本次已保留可复现输入和失败检查，没有修改预期把它们变绿。 |
| 还需要硬件或教师吗？ | 修复这三项软件缺口不依赖硬件。真实日志、故障可区分性和灯亮需要硬件；教学动作与案例需要教师，状态均未升级。 |
| 下一步最应该做什么？ | 先修反馈会话归属，再明确反馈请求幂等身份，最后修正候选证据映射；逐项重跑本报告场景。 |

## 实际结果

| 检查 | 结果及解释 |
| --- | --- |
| PostgreSQL 完整流程评测 | 16 场景：13 passed、3 failed；整体 **failed**，CLI 退出码 1 |
| SQLite 完整流程评测 | 16 场景：12 passed、3 failed、1 not_run；恢复场景未在内存库冒充通过 |
| 后端全量回归（配置两个隔离 PostgreSQL DSN） | 251 passed、3 xfailed，无跳过，1 项依赖库弃用警告 |
| 实验包校验 | DHT11、LED 均 2.0.2，各 10 项通过，文件包 hash 与第一阶段一致 |
| V2 证据工作流 CLI、Ruff、差异检查 | 通过 |

三个 `xfail(strict=True)` 分别关联下文三个问题，用于防止既有缺陷淹没新增回归。**它们是已知未通过项，不能计入通过数量。** 对应 CLI 不识别或豁免 xfail，仍逐项输出 failed、整体失败并返回非零状态。修复时严格 XPASS 会要求同步移除问题标记。

本轮报告：`output/workflow-evaluation/phase2-postgres.json`，约 1 MB，仅含合成数据。报告记录代码文件与输入/预期 SHA-256、基线 Git 提交和工作区是否有改动，不能仅用 HEAD 代表未提交的评测实现。该输出为本地生成物，完整命令见下文；可重新生成，不自动上传 GitHub。

## 本轮覆盖

评测通过生产 HTTP 路由执行：设备 ingest → 归一化及 Evidence 落库 → 真实 LangGraph → 规则 → 故障树 → 知识约束 → Mock AI → 解释 → 学生反馈 → 教师审核。数据库、账号、设备和教师角色均由隔离夹具建立。

| 场景 ID | 判据 | 本轮结果 |
| --- | --- | --- |
| dht-missing | 有心跳无读数，正常评估必须 unknown | passed |
| led-legacy / led-command | level 或命令不能生成物理发光证据；正常评估 unknown | passed |
| dht-ambiguous | 当 Mock 返回 unknown 时，系统保留 unknown、无排序并转教师，不强迫补根因 | passed；不表示模型自行识别了真实不可区分故障 |
| dht-valid | 合法 Mock 输出贯穿推理、解释和审计 | passed；不证明排序的因果质量 |
| dht-foreign_evidence | 非本次 UUID 被拒绝并降级，审计为失败 | passed |
| dht-invalid_json / dht-timeout | 非法 JSON / 合成超时异常得到降级 | passed；未模拟真实网络延迟 |
| dht-candidate-linkage | DHT11 候选引用应关联触发异常的证据，不能拿心跳占位 | failed，WF-ISSUE-01 |
| feedback-roundtrip | 未解决继续原流程，解决后结束，读取不重复调用 | passed |
| duplicate-feedback | 将连续相同 HTTP 提交作为重试场景，不应新增反馈/恢复/调用 | failed，WF-ISSUE-02；现接口缺少区分重试与新反馈的身份 |
| teacher-roundtrip | 求助→合成教师审核→重复审核返回 409 且无副作用 | passed |
| foreign-session-read | 其他学生会话读取原流程返回 404 且无副作用 | passed |
| foreign-session-feedback | 其他学生会话提交反馈应在写入前拒绝 | failed，WF-ISSUE-03 |
| foreign-package-version | 与作业锁定包不同的版本返回 403 | passed |
| postgres-restart | 关闭连接重建真实图，恢复后继续反馈与教师审核 | passed |

每个快照还检查包 hash 和归属、证据 UUID 与原始上报来源、节点前缀、候选成员资格、推理证据引用、解释动作、异常不被 AI 改写、审计阶段唯一、无自动 approved KnowledgeCase。引用合法和类型相关均不证明硬件因果成立。

## 三个必须整改的问题

### WF-ISSUE-03：反馈接口缺少请求者会话校验（优先）

复现：为同一合成设备建立另一学生的有效会话，使用其 `X-Experiment-Session-ID` 向原学生诊断提交 resolved。实际返回 **201**、新增反馈，原流程从 waiting_feedback 变为 completed；预期是在写入前拒绝并保持所有记录不变。

定位：[反馈路由](../backend/app/api/v1/routes/student.py)仅先验证 diagnosis.device_id，随后就保存反馈；[恢复服务](../backend/app/services/diagnosis_workflow.py)检查设备与记录内部归属，未比较本次请求者的实验会话。这与读取接口已有的会话边界不一致。

后续整改应在保存任何反馈、Episode 或草稿之前核对会话—学生—设备—诊断关系；拒绝路径必须零副作用。不能只在流程恢复后补校验。此复现不声称证明攻击者无需设备凭据，也不覆盖其他全部权限边界。

### WF-ISSUE-02：反馈不能区别请求重试与新一轮尝试

复现：连续两次发送相同 unresolved 报文。第二次新增一个反馈 UUID，resume_count 从 1 到 2，Mock 总调用从 4 到 6。

定位：[save_student_feedback](../backend/app/services/student_dashboard.py)每次创建新记录；当前反馈 Schema 只有 action/note，没有能识别同一次逻辑提交的键。因此问题是**重试契约缺失**，不能把所有相同文本都当重复操作。

后续应设计稳定的提交标识与数据库唯一约束：相同键同载荷重放原响应，相同键不同载荷冲突，不同键允许真实新尝试。拒绝或重放不得新增调用、Episode 变更或知识草稿。该项可能涉及小范围 Schema/迁移，需要与权限修复一起审阅；本轮未直接添加。

### WF-ISSUE-01：候选原因借用了无关证据

复现：一次心跳加五次 DHT11 读取失败，候选原因 evidence_refs 指向真实的 `device_heartbeat` UUID。异常规则的失败证据 UUID 另有落库，不能用心跳填补关联缺口。

定位：[fault_tree_analyzer](../backend/app/ai/diagnosis_graph.py)解析旧 log_id/reading_id，未匹配时使用第一条注册证据。第一阶段收紧了 AI 推理降级，但这一更上游的映射仍可产生看似合法的引用。

后续应根据故障树实际匹配条件关联规则事实及原始事件；匹配不到时保留空引用/unknown。不得固定换成“第一条失败日志”。就算关联到失败日志，也不能因此断言 DATA 断开或器件损坏。

## 评测实现与隔离

- [workflow_inputs.json](../backend/evaluation/workflow_inputs.json)：合成上报、Mock 模式与操作序列。
- [workflow_expectations.json](../backend/evaluation/workflow_expectations.json)：独立人工写定的异常集合、状态序列及要求；仅评测器读取，未交给被测图或 Mock。
- [workflow_environment.py](../backend/app/evaluation/workflow_environment.py)：建立隔离 SQLite 或随机 PostgreSQL schema，使用现有包导入/状态转换建立测试版本，结束删除自己建立的 schema。此处 approved/published 是合成数据库的工作流测试，不是正式知识认证。
- [workflow_runner.py](../backend/app/evaluation/workflow_runner.py)：通过真实路由驱动，保存实际输入/响应、过程快照、证据来源、AI 审计及预期对比。
- [test_workflow_evaluation.py](../backend/tests/test_workflow_evaluation.py)：流程检查及篡改反例，验证替换 UUID、增加异常、越界动作、换包 hash、自动批准知识都会导致检查失败。

使用新建 FastAPI 测试应用挂载生产路由；不会启动生产 lifespan。真实业务函数及诊断图不被替换，只替换两个 AI client 工厂。报告不导出登录密码、设备 token、Authorization 或登录 access_token。Mock 输出只代表特定合成行为，不代表真实模型能力。

PostgreSQL 验证包含真实业务表和实际诊断图，连接关闭后重新建立业务连接和 PostgresSaver，验证证据、审计、状态与下一步继续执行。**这是连接重建/图重建恢复试验，不是进程 kill、整机重启、网络分区或并发负载验收。** 使用 ORM 建表，未代替 Alembic 升级验收；没有访问生产库。

## 重跑与门禁

从仓库根目录运行（Python 3.10+；本轮为 `/tmp/xinjian-trust-venv/bin/python`）：

```bash
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation \
  --output output/workflow-evaluation/phase2-sqlite.json
```

需要隔离的 PostgreSQL 测试库时，设置 `XINJIAN_EVAL_POSTGRES_DSN` 后执行：

```bash
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation --postgres \
  --output output/workflow-evaluation/phase2-postgres.json
pytest backend/tests -o addopts='' -q -ra
```

不要将 DSN 指向生产库。评测只创建/删除随机 `workflow_eval_*` schema，不重置整个数据库。只有明确传入 `--postgres` 才读取该环境变量；未配置时记录 blocked，退出 2。无 PostgreSQL 时恢复场景 not_run，不计为通过；场景执行异常记录 error，不导出可能含凭据的异常正文。

CLI 退出码：0 全部通过，1 有失败/执行错误，2 环境阻塞/未执行项。当前入口是独立 CLI，尚未自动接入 GitHub CI；既有 CI 或 pytest 为绿不能替代本阶段的失败报告。

后续完成三个修复后，须移除相应 strict xfail 并重跑该 CLI，只有报告全部通过才能完成本阶段软件契约验收。硬件、教师、真实 AI 语义质量、前端浏览器、负载与进程崩溃验证继续分开报告。
