# 芯鉴知微开发检查清单

规则归本文，能力/待验见[实现状态](implementation-status.md)/[真实性看板](project-truth-status.md)。设计读[PRD](product-background-prd.md)，执行点非已通过证明。

## 1. 开发、修复与交付

<a id="defect-prevention"></a>
<a id="data-change"></a>
- [ ] 核源码/配置/授权，跨架构记决策并同步契约/实现/反例 → 仅人工审查；[开发流程](../AGENTS.md#开发流程)。
- [ ] 明确归属/版本/入口/副作用，验等待/撤权/提交/丢响应顺序及限额/回收 → §9；独立预期不由被测实现生成，拒绝配合法对照，必要时隔离破坏保护验反例。

<a id="fix-bugs"></a>
### 修复 Bug

- [ ] 复现→定位→方案→修改→测试（根因/相邻入口/兼容/回退/合法对照） → §9测试，过程仅人工审查。实质缺陷先固化失败回归，环境报错不算基线；不删/跳过/放宽断言凑通过，纠正测试须独立依据。
- [ ] 低影响改动相称检查，通过后仅遇新改动/失败/疑点再扩测 → 仅人工审查。

<a id="validation"></a>
### 验证与交付

- [ ] 验收独立复跑真实链路、绑定源码/配置/数据；软件/CI/迁移/部署/Provider/硬件/课堂分报，Mock/编译不证实物、未执行非通过 → 仅人工审查；[命令](evaluation.md)、[报告](test-reporting.md)。
- [ ] 迁移只追加，保留历史/NULL，验空历史库升级、唯一Head/模型/恢复，拒有损降级；字段来源/默认/兼容、索引/分页见[数据库设计](database-design.md) → §9 OPERATIONS。
- [ ] 包改内容升版本/核hash，同步当前说明、不改历史 → `scripts/check_version.py`、`test_development_gates.py`。

<a id="model-core"></a>
## 2. 模型规范内核

来源为[2026-09-17原文](references/model-spec-2026-09-17.md)。内核约束产品模型，开发代理仍可在授权内研究/测试。

> 规则决定异常，故障树限定候选，数据库保存证据，模型辅助排序与解释，验证器决定输出能否采用，教师确认正式知识。

1. **证据先于结论。** 上报、规则异常、候选、确认根因分开；引用须为本次实际落库UUID且关联候选。合法ID不证明因果，命令不证明硬件效果，无报错不证明正常，预训练知识不算本次事实 → 证据映射、`knowledge/validation.py`；§9 EVIDENCE/SEM。
2. **保留不确定性。** 不足或不可区分时保留`unknown`、冲突及待核验；`high/medium/low/unknown`是支持等级，分数、排序、检查优先级不是概率或根因确认 → `ai/output_contract.py`；§9 AI/ISSUE，因果仅人工审查。
3. **代码限定职责。** 规则定`error_type`，树定`cause_id`；AI只在已有候选、证据、动作内排序解释，不决定计数、状态、介入、工具执行或发布。固定、可测试Schema与LangGraph分支，当前无RAG、向量检索、多智能体或自由规划 → `ai/diagnosis_graph.py`、`diagnosis/workflow_schemas.py`；§9 AI/RECHECK。
4. **独立校验。** 后端核错误类型、候选、关联证据、知识审核/版本和动作白名单；摘要/限制取已验证状态，自由文字不成事实。结构集合通过不证明完整语义或电气安全 → `knowledge/validation.py`、`ai/output_contract.py`；语义/安全仅人工审查。
5. **AI可移除。** 默认关闭；关闭、拒绝、外发失败、超时、限流、预算或不合规均保留确定性诊断、反馈、求助并记原因；撤权拒绝受限交付 → `ai/governance.py`、`reasoning.py`；§9 AI。
6. **可追溯。** 测试性质保守传播；知识来源核验审核，诊断保留包/模型/Prompt/Schema/验证器/工作流版本及审计。切模型、缓存、回滚不改历史；生产用受控持久checkpoint，内存不作保障 → §9 PROVENANCE/MEMORY/OPS。
7. **需求决定复杂度。** 先完善约束、样例、真实教师资料，以独立评测决定选型/微调/队列/模型服务。保留FastAPI/PostgreSQL、固定LangGraph、Vue/TypeScript及轻量Provider客户端；不叠复杂LangChain、不为统一规则拆微服务，不扩自主硬件控制、自动评分、多学校管理 → 仅人工审查；[架构](architecture.md)。

原文推荐/价格/政策/配置接入时核实，示意Schema/路由/action/性能/灰度/清单非契约；占位ID禁用，在线＋读取失败不确认GPIO；原引用不证明重核。改边界先记决策，不以偏离辩护 → 仅人工审查及§9反例。

<a id="business-rules"></a>
<a id="20-业务逻辑与开发规则用户确认的持续开发依据"></a>
## 3. 业务不变量

- [ ] 操作者、持久化历史归属、当前授权分别核对；设备凭据只认证设备，测试兼容明示；教师限当前授课范围，各角色能力不互推，未知归属受限且不展示 → AUTH/SESSION。等待锁、恢复、长调用发送及交付前重验，401/403不伪装503；退出撤销当前服务端登录。
- [ ] 会话固定已发布包、设备独占；换人/转班不转移历史，迟到记录归原采集者。释放只取消指定会话，不关问题/工单/课程或后继会话；结束仅允许受权确认原操作 → SESSION/LAB-PREP；小组主体/成员有效期/个人反馈仅人工审查。
- [ ] 原始与规范值、发生/接收时间及时间可信度分开；缺/空单位不补造，数字有限，命令/电气/光学分开；同源重传不造新观察，测试来源不能洗正式 → EVIDENCE/PROVENANCE；完整协议见[设备协议](device-protocol.md)。
- [ ] 会话、诊断、问题episode、工单不同；多问题各有范围、证据修订、反馈/指导/预算，A新证据或恢复不改变B。采样失败、异常轮次、未解决反馈、提示、自述执行次数分开，累计不当连续，点击不证明执行 → ISSUE/LIFECYCLE/COUNTERS。
- [ ] 解决注明来源，新异常阻止旧解决；恢复须同范围/语义、独立且时间可信的新采样满足完整判据。无数据/离窗/重传/其他组件正常不证明恢复，关单/结束不等恢复；新时期异常新问题，迟到旧记录补历史 → ISSUE。

<a id="recheck"></a>
- [ ] 未解决沿旧证据，重查分析已上传输入；读取/刷新/切页/回执不新增诊断/反馈/调用/计数。同ID同载荷恢复、异载荷409，未知先确认不换ID；短事务冻结，Provider不持业务锁，提交后沿原ID协调 → RECHECK/COMMAND；细节见[API](api-design.md#检查与恢复约束)。
- [ ] 指导给已知/缺口/下一动作/区分作用/新证据验证，动作带批准前提/安全限制、确定性升级，缺动作转教师；活动问题最多一工单、责任人当前授权、私密不旁路 → INTERVENTION/KNOWLEDGE。
- [ ] 事实→草稿→核验→审核→发布；根因须确认材料，候选外原因留证提新包。审批同事务唯一来源，润色不改事实/返回重验；发布不可覆盖，替代不换旧会话，撤回阻断教学/缓存而保留采集历史 → KNOWLEDGE/PACKAGE/MEMORY。
- [ ] 三类记忆分开；观测/反馈/模型总结不晋升事实。账本固定使用时版本/hash，来源停用同事务、恢复交付重验，复核不改原诊断，影响关联不证明误诊/送达 → MEMORY/ADVICE；未定保留期不删数据。
- [ ] 历史未知留NULL、不猜归属/合并案例；统计有时间/分母/单位，测试不混正式；归档/停用/删除分开、兼容删前核迁移/回退，`state_revision`非锁 → OPERATIONS；保留期/容量/SLO/课程阈值仅人工审查。

<a id="ai-boundary"></a>
## 4. AI外发与费用

- [ ] 三入口白名单清洗完整受权源秘密、动态键/值、短秘密/嵌套；必需身份冲突取消增强，不伪造ID/改数字，数据命令无指令权、私密不外发 → AI/CTX，完整见[AI设计](ai-diagnosis-design.md#调用恢复合同)。
- [ ] 逻辑操作/物理尝试分开，发送前存身份/版本/额度，成功重放、未知不重发/退款；期限/字节/退避/金额有界，尝试记账不重复扣，估算不当硬上限 → AI；[调用合同](ai-diagnosis-design.md#调用恢复合同)。
- [ ] 返回/缓存/恢复重验当前授权、来源、版本、测试范围；过时丢弃仍记费用，审计失败不能吞撤权。Schema与业务一致，两阶段共享原因许可，unknown/空排序不补原因，先判冲突再限引用 → AI/SEM/STAGE。

<a id="package-content"></a>
## 5. 实验包

- [ ] 七步制作，事实/选型/实测/课程确认分开，缺材料仅测试草稿 → PACKAGE；[内容制作合同](experiment-package-design.md#内容制作与来源审查)，真实资料/责任与重大流程变更仅人工审查。
- [ ] 十工件验Schema/引用/单位/ID/hash/兼容，差异用数据、运行固定发布快照；案例连条件整条选择，源身份非真实性；concepts/steps明确绑定、不扩动作/计数/外发，旧指导不回填 → PACKAGE/PKC/CTX；P4仍待实施。

<a id="ui"></a>
## 6. 界面

- [ ] 对象/快照不混，导航只读、隔离迟到响应；401登录/403清无权/409核状态，未知保留原ID → COMMAND/UI；[客户端合同](api-design.md#客户端展示与请求隔离)。
- [ ] 测试/过期/未知/冲突/缺证据/待确认直接可见，采样/读取时间、原始/规则/AI/教师分清，中文不改业务含义 → UI；布局/术语仅人工审查。

<a id="ai-quality"></a>
<a id="21-ai-开发与质检准则claweval-适配2026-09-27"></a>
<a id="rubrics"></a>
## 7. 测试与AI质检

- [ ] 派生数据用`tests/pipeline.py`，手工构造棘轮仅降、刻意异常注明原因、独立断言由测试维护 → TEST。
- [ ] 精确字段/参数/中间值/数字格/副作用独立断言，答案只给评测器；语义人工审查、关键词不替代、不与模型裁判混同方法 → [评测表](evaluation-requirements.md)。
- [ ] Rubric稳定ID/条件/材料双向映射，一条一事、符合侧、≤400字符及≤3句，仅符合/不符合，无评分/评级/抵消；未审`null/not_run`，缺材料/不适用记原因，未审完不称通过 → [semantic_rubrics.json](../backend/evaluation/semantic_rubrics.json)、`test_evaluation_contract.py`；语义仅人工审查，候选支持等级保留。
- [ ] 核触发及对应轮次/全程/审计/DOM，后轮不抹失败；AI改动核CoT、图/恢复、整单元/两阶段manifest、案例条件、记忆/停用、包参考、输出/费用，配置预检不以Mock替代 → §9；[取证与独立对照](evaluation-requirements.md#取证与独立效果对照)，效果仅人工审查。

<a id="doc-maintenance"></a>
## 8. 文档维护

- [ ] 规则归本文、细节归设计、状态归看板、命令归手册、结果归`output/audits/`；不逐轮加方案或改历史；删除先归位事实、修链接/锚点、记最后提交 → 仅人工审查、[删除索引](archive/README.md)。文档检查不算行为验收，秘密/完整错误体不入Git/日志，扫描见OPS。

<a id="rule-map"></a>
## 9. 规则—执行位置—入口—反例

路径基准：后端`backend/app/`（服务短名在`services/`），测试`backend/tests/`，前端`frontend/src/`；通配符为测试组。

|规则|共享执行点|入口与独立反例/门禁|
|---|---|---|
|TEST/XJ-009|`tests/pipeline.py`|摄入→保存；`test_fixture_provenance.py`；手工白名单仅降|
|ERROR/XJ-010|`core/errors.py`、`api/errors.py`|分类/兼容/吞异常；`test_error_handling_gate.py`，捕获白名单仅降|
|AUTH/XJ-008|`api/access_policy.py`|全路由/隐藏别名/设备422；`test_access_policy.py`|
|AUTH|`auth.py`、`data_scope.py`、`api/dependencies.py`|全入口/反馈/恢复锁后撤权；`test_shared_authorization*`、`test_feedback_authorization_wait.py`|
|AUTH/登录退出|`auth.py`、`login_limits.py`|共享在途额度/原token撤销；`test_session_security_repair.py`|
|ADVICE/R2、IDENTITY/R3|`current_advice.py`、`knowledge/applicability.py`|冻结绑定/教师编辑/未知实验；`test_shared_advice_regression.py`|
|SOURCE/R4|`source_lifecycle.py`|引用/清理共锁、拒绝/合法对照；`test_shared_source*`|
|PROVENANCE/R5|`provenance.py`|派生/导出/审计任一测试源传播；`test_provenance_contract.py`|
|COMMAND/R6|`api/commandOutcome.ts`、`resilience.ts`|各操作409/超时后403/回执；同名单测及store/浏览器|
|OPS/R7、R8|`scripts/security_scan.py`、`api/v1/routes/health.py`|无秘密回显/失败非通过/ready；`test_security_scan_contract.py`、`test_readiness.py`|
|OPS/配置与旧入口|`core/config.py`、`api/http_boundary.py`、`experiment_templates.py`、`main.py`|持久checkpoint/500/旧发布/重复身份/docs头；`test_runtime_boundary_repair.py`、`test_audit_remediation.py`|
|SESSION|`experiment_sessions.py`|开始/结束/释放/回执，后继保护；`test_session_release.py`|
|EVIDENCE|`device_protocol.py`、`device_ingest.py`|四入口/半批/整数/重传/流量；`test_ingestion*`|
|ISSUE/LIFECYCLE/COUNTERS|`diagnosis_episode.py`、`recovery_evidence.py`、`guidance.py`|新旧诊断/反馈/恢复；多问题/旧证据/解决竞争；`test_episode_*`|
|RECHECK|`diagnosis_checks.py`、`diagnosis_workflow.py`|冻结/同异ID/丢回执/快照；`test_diagnosis_checks*`、`test_check_handling_snapshot.py`|
|INTERVENTION|`interventions.py`|工单全入口逐对象投影；`test_intervention_scope_r2.py`|
|KNOWLEDGE|`knowledge/case_drafting.py`|案例全入口/版本/撤权/唯一源；`test_knowledge_case*`|
|MEMORY|`memory.py`、`memory_governance.py`、`memory_restore.py`|停用/复核/清理/恢复/源同步；`test_memory_*`|
|PACKAGE|`experiment_packages/loader.py`、`teaching.py`、`experiment_packages.py`|导入/发布/运行/撤回/指导；`test_business_package_boundary.py`|
|PKC|`knowledge/applicability.py`、`projection.py`、`experiment_packages/registry.py`|条件/top-k/来源/1.0hash/当前建议；`test_package_context*`、`test_case_applicability.py`|
|CTX/STAGE|`ai/context_builder.py`、`context_status.py`、`experiment_packages/context_preview.py`|整单元/51条/秘密/实际预算；`test_context*`、`test_stage_context_admission.py`|
|AI/SEM|`ai/reasoning.py`、`output_contract.py`、`current_advice.py`|两阶段许可/支持上限/unknown/旧别名/合法动作；`test_explanation_handoff.py`、`test_residual_semantic_contract.py`|
|AI/治理外发|`ai/governance.py`、`clients.py`、`context_sanitizer.py`|三入口/未知发送/费用/等锁撤权及超时；`test_ai_operation*`、`test_ai_dispatch*`、`test_r2_provider_data_boundary.py`|
|AI/拒绝审计|`ai/governance.py::audit_delivery_denial`|Provider后0/1审计、回滚失败不吞撤权；`test_knowledge_case_drafting.py`|
|QUERY/XJ-003..005|`query_sources.py`、`query_tasks.py`|8KiB/幂等/503非stale/409/结束403/GET无写；`test_query_*`|
|UI|两端store、诊断/查询组件、`userLanguage.ts`、图表/样式、`review/state`|对象/迟到/原ID/私密/中文、卸载/五路由三宽度/离线；组件/store、`frontend/tests/e2e/`及`integration/`测试，截图人工审查|
|LAB-PREP|`internal_experiment_preparation.py`、`cli/prepare_internal_experiment.py`|plan/apply/status/发布测试包/重复冲突；`test_internal_experiment*`|
|OPERATIONS/历史版本|迁移、`cli/audit_historical_integrity.py`、`scripts/check_version.py`|NULL/升级/唯一Head/模型/版本/统计；`test_migration_r2.py`、`test_development_gates.py`|
|OPERATIONS/固件备份模拟器|`firmware/esp32_dht11`、`scripts/database_backup.py`、`simulator`|同快照/关系、单批/慢重试/64位/TLS、首发清单/时限；备份、固件主机/构建、模拟器测试|
