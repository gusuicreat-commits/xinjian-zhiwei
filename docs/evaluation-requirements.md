# 评测要求、测试与依据对应表

本文维护要求编号、来源与测试入口，不记录本次是否通过。持续规则见 [开发准则](development-guidelines.md#ai-quality)，运行方式见 [测试与评测](evaluation.md)，执行结果按 [报告约定](test-reporting.md) 保存。

## 来源与适配原则

参考用户提供的《ClawEval质检标准.pdf》4 页，导出标记为 2026-09-02 10:54，SHA-256：
`2802cc63c54110d2fbd1b079a4dcd7864377d6c8294fafdc7486431b26929520`。
PDF 是评测设计参考，不是器件参数或正式 KnowledgeCase 来源，原文件未复制入仓库。2026-09-27 核对过 4 页原文及渲染；第 4 页安全场景右侧裁切、外链规范未核验，不补造内容或声称全部采纳。

采用：精确事项用代码；检查实际输出；要求逐项可追溯；正确样例与错误反例并存；区分结果和过程材料。
不照搬：外部固定路径、默认 ±15% 容差、禁止评测器读取参考答案、为凑数量重复测试。
文档中数值 rubric 与精确校验、混合测试示例存在不一致，项目统一以代码检查可确定事项。

### Rubric 的必守约束

二元、原子、长度、符合侧写法与关键词边界统一维护在 [AI 质检规则](development-guidelines.md#ai-quality)。

条目唯一维护在 [semantic_rubrics.json](../backend/evaluation/semantic_rubrics.json)，每条声明所需输入与实际输出材料。格式校验不证明语义质量，人工审阅仍需独立依据；真实模型语义评测与模型裁判尚未完成。

### ClawEval 逐页适配映射

下表全部对应 [AI 质检规则](development-guidelines.md#ai-quality)；“纳入”不表示测试已经实现或执行，具体覆盖见后续编号表。

| PDF 位置 | 强调内容 | 本项目归属与适配 |
| --- | --- | --- |
| 第 1 页“核心宪法”1；第 4 页六.6 | 继承历史题目的适用检查角度 | 保留适用边界和反例，未采用项说明原因；不机械增加数量或访问外部任务路径 |
| 第 1 页“核心宪法”2–3 | 检查实际产物、必须发生的调用及参数 | 分别检查结果和过程，不以模型自述或预期文本替代 |
| 第 1 页一.1–2 | 判定二元，只写符合侧 | 严重错误采用门禁，不引入综合分数 |
| 第 1 页一.3–4 | 一条一事，≤400 字符且≤3 句 | 跨轮一致性项保留当场纠正与后续沿用两个时点材料 |
| 第 1 页一.5；第 2 页二.6 | Rubric 不列关键词，精确常量独立维护 | 精确实体/枚举由代码判断，自由语义不用关键词裁决 |
| 第 1–2 页二.1–3 | 精确检查与语义判断分工，同方法不混用 | 项目使用独立代码检查与人工语义审阅，未引入 LLM judge |
| 第 2 页二.4–5、三.2；第 4 页六.7 | 参数来源、公式、理论值、容差、中间数和逐格数字检查 | 用独立依据编码检查，不照搬 ±15%/±5% 或数值 Rubric |
| 第 2 页三.1；第 4 页六.5 | 隐性与条件要求逐项覆盖 | 限已声明业务和测试场景，不猜测真实用户心理 |
| 第 2 页三.3；第 4 页六.8 | 调用发生与每个参数约束独立测试 | 检查后端固定流程及真实请求，不给模型新增工具权限 |
| 第 2 页三.4 | 文件存在、解析、字段、计数和关键值分别检查 | 有文件产物时适用，不为无文件任务虚构产物 |
| 第 2–3 页五.1–2 | 按问题选择全程、最终、首轮、完整对话材料 | 使用项目现有材料与日志结构，不复制外部固定模板 |
| 第 3 页五.3–4 | 条件触发保护须看到用户输入 | 未触发标不适用并说明原因，不计为已验证；缺材料不自动通过 |
| 第 3 页五.5–6；第 4 页五.8–9、六.4 | 条目定义/引用对应、集中维护、避免重复 | 沿用项目 ID 与测试结构，不强改成 `RUBRIC_*` 文件布局 |
| 第 4 页五.7 | 禁止读取外部参考答案 | 参考答案仅给评测器，被测系统不可接触；保留独立、可复现预期 |
| 第 4 页六.1 | 纯对话安全，严重违规不可抵消 | 可见 A–H 纳入适用规则，裁切场景与外链不补造 |
| 第 4 页六.2–3 | 导入、测试收集无错误 | 运行实际受影响入口，收集成功不冒充测试通过 |

原文存在几处内部口径差异，本项目按确定性、可复核和已有授权边界处理：

1. 第 1 页要求确定数字用代码，第 2 页又允许/要求逐格数值 Rubric；统一采用独立代码校验，格式不固定不改变精确事项的性质。
2. 第 2 页禁止同测试混用精确断言与模型裁判，第 3 页五.4 示例却同时调用；拆成独立检查，可共享夹具和完整触发材料。
3. 第 4 页以安全“清零分数”描述严重错误；项目使用不可抵消的验收门禁，遵循原文二元原则，不新增评分体系。
4. 原文条件未发生可自动通过；项目区分不适用、未覆盖该场景和缺材料，避免把没有发生的行为当已验收。

CoT 实现边界见 [AI 设计](ai-diagnosis-design.md)，软件与语义检查分别登记在下方 COT 表。

## 要求映射

“代码已覆盖”只指表中限定的行为。测试均为合成输入或测试数据库记录；不得推导真实硬件准确率。

| 编号 | 单项要求 | 检查材料和方式 | 测试入口 | 状态与依据 |
| --- | --- | --- | --- | --- |
| EVAL-01 | 扫描实际渲染文字，但不以子串判定语义 | 命中仅为线索；否定和改写均保持语义未审阅；精确规则错误仍使代码检查失败 | `test_evaluation_contract.py::test_pattern_scan_reads_rendered_output_without_judging_meaning`、`test_negative_and_paraphrased_claims_cannot_get_a_keyword_verdict`、`test_exact_rule_error_still_fails_code_checks` | 9 月 15 日纠正；SEM-01/02 语义检查未执行 |
| EVAL-02 | high 必须有有效白名单证据引用 | 空引用、unknown 观测的反例与有引用的正例 | 同文件 `test_high_support_*` | 代码已覆盖；仅最低结构门槛，不证明因果 |
| EVAL-03 | 模型不能隐藏输入证据冲突 | 输入 conflict 与输出 conflict 比较 | 同文件 `test_model_cannot_hide_input_conflict` | 代码已覆盖；项目证据冲突约束 |
| EVAL-04 | 降级不能借用无关证据制造支持 | 候选无关联引用时返回 unknown；保留允许的下一动作 | 同文件 `test_fallback_*` | 代码已覆盖；AI 不可用也遵守证据原则 |
| EVAL-05 | 推理后独立校验也检查 high 引用 | 检查独立 knowledge validation 的结果 | 同文件 `test_post_reasoning_guard_independently_rejects_high_without_evidence` | 代码已覆盖；独立防线 |
| EVAL-06 | 解释步骤只能选择允许动作 | 逐字白名单校验；显式空名单不借用其他来源 | 同文件 `test_explanation_*`、`test_empty_workflow_actions_do_not_fall_back_to_other_hints` | 代码已覆盖；动作来源仍须教师审核 |
| EVAL-07 | 摘要说明本次异常，具体待核验项不升格为事实 | 规则类型、unknown/冲突状态、引用的缺失证据需求；解释模型单独新增的“已确认”限制不作为事实采纳 | 同文件 `test_model_prose_cannot_replace_server_owned_fact_summary`、`test_specific_pending_information_is_preserved_without_becoming_confirmed`；`test_ai_diagnosis.py::test_specific_pending_information_survives_persistence_and_replay` | 9 月 15 日纠正信息损失；推理提出的需求保留“未确认”标签 |
| EVAL-08 | 输出边界在返回和审计之前执行 | Provider Mock → 服务 → 测试数据库审计与返回值 | `test_ai_diagnosis.py::test_provider_boundary_is_applied_before_response_and_audit` | 代码已覆盖；不是完整 UI/课堂验收 |
| EVAL-09 | 历史审计不能冒充当前验证建议 | 缺当前输出契约的旧记录保留原文，但不返回为有效 AI 建议 | 同文件 `test_old_audit_prose_is_not_served_as_current_validated_output` | 代码已覆盖；无历史数据库批量改写 |
| EVAL-10 | 缓存命中不能绕过动作校验 | 篡改测试缓存的步骤后重读；应重建缓存 | 同文件 `test_invalid_cached_steps_are_revalidated_and_replaced` | 代码已覆盖；已有缓存/调用幂等测试继续保留 |
| EVAL-11 | 包内故障样例不能容忍额外异常类型 | 同一输入增加另一异常规则，包测试必须失败 | `test_evaluation_contract.py::test_package_fault_sample_rejects_an_additional_error_type` | 代码已覆盖；不等于实际故障树排序验收 |
| EVAL-12 | Schema 合法与非法分别覆盖 | 合法样例、越界提示等级、错误字段类型、非法枚举 | `test_diagnosis_workflow_security.py::test_valid_synthetic_output_satisfies_schema_and_allowlists`、`test_invalid_output_shapes_are_rejected` | 代码已覆盖；不再将重复 100 条样例称为 99% 模型合格率 |
| TRUST-01 | 窗口失败不能当连续失败 | 成功/失败交替序列的规则计数 | `test_experiment_trust.py::test_window_failure_count_does_not_claim_consecutive_failures` | 继承现有覆盖；阈值 pending_hardware |
| TRUST-02 | GPIO 命令、实际电平、物理发光独立 | 原始报文、归一化结果与落库类型 | 同文件 `test_led_legacy_level_never_establishes_command_actual_or_light`、`test_led_evidence_persists_distinct_types_and_real_uuids` | 继承现有覆盖；真实来源 pending_hardware |
| TRUST-03 | 没命中异常不自动代表正常 | 心跳、周期、字段有效性及缺数据反例 | 同文件 `test_normal_requires_heartbeat_periodic_valid_data_and_no_rule_hits`、`test_single_sample_and_unconfigured_period_are_not_periodic_success` | 继承现有覆盖；课程标准 pending_teacher |
| TRUST-04 | Evidence 属于当前包版本并已落库 | HTTP 上报到测试数据库的证据类型与 UUID | 同文件 `test_http_ingest_to_package_evidence_uses_same_semantics` | 继承现有覆盖；不证明来源描述真实 |
| TRUST-05 | 学生解决反馈不直接发布知识 | 案例草稿、事实字段和审核状态 | `test_knowledge_case_drafting.py`、`test_structured_knowledge.py`；`verify_v2_evidence_workflow` 合成 CLI | 继承现有覆盖；真实案例 pending_teacher |

以上测试文件位于 [backend/tests](../backend/tests/)。运行方法见 [测试与评测](evaluation.md)。
此表是人工维护的要求映射，不宣称已建立自动覆盖率计算器。

解释的 `explanation-boundary-v2` 契约、历史审计和缓存兼容规则统一见 [AI 设计](ai-diagnosis-design.md)，由 EVAL-02/04/05/06/07/09/10 检查。

## 覆盖边界

- 自由 `reason/summary` 与教师编辑文本须独立语义审阅；模板保护、关键词扫描、Rubric 格式通过都不能替代。报告状态见 [测试报告约定](test-reporting.md)。
- UUID、status 和候选关联合法不证明真实故障可区分。包内 normal 样例只验证包内规则未命中，候选样例只检查树内成员资格；完整正常运行、排序和硬件因果分别验证。
- 尚未引入 LLM judge、真实模型基准或自动教学评分。合成多轮材料不证明模型质量；Prompt 禁令不替代提示注入、权限、草稿和只读反例。

## 维护要求

修改规则时同步受影响的编号、入口、反例和依据；预期独立性、未执行/不适用状态及语义审阅按 [开发准则](development-guidelines.md#ai-quality) 执行。

## 完整流程要求

原失败依据见 [第二阶段历史报告](archive/workflow-evaluation-phase2.md)，该阶段修复证据见 [整改报告](archive/workflow-remediation.md)。下表保留要求编号及既有覆盖范围；是否当前通过必须重新执行，不能从历史 passed 或测试数量推导。流程要求对应 `backend/evaluation/workflow_expectations.json` 和 `assess_case` 返回的单项 checks；可靠性边界另由专项测试验证。

| 编号 | 要求与入口 | 既有覆盖及边界 |
| --- | --- | --- |
| FLOW-01 | 设备 HTTP 上报至实际落库 UUID、归属、包 hash 和节点轨迹；每个场景快照检查 | 已覆盖；不证明证据支持具体根因 |
| FLOW-02 | 缺数据及 LED 缺光学观测保留 unknown；dht-missing、led-legacy、led-command | 已有场景覆盖 |
| FLOW-03 | 合法/未知/非法 UUID/非法 JSON/超时 Mock 经真实推理与解释路径；dht-* | 已有对应软件约束检查；无真实模型质量结论 |
| FLOW-04 | 未解决继续、解决结束、教师处理及重复审核无副作用 | 已有场景覆盖 |
| FLOW-05 | 跨学生读取、跨包版本请求拒绝；拒绝不改变原流程 | 已有场景覆盖 |
| FLOW-06 | 跨学生提交及重放反馈在所有写入前拒绝；foreign-session-feedback、foreign-session-feedback-replay | 已有场景覆盖；WF-ISSUE-03 已整改，缺失会话另按 422 拒绝 |
| FLOW-07 | 同键同载荷重放无重复副作用；duplicate-feedback | 已有场景覆盖；WF-ISSUE-02 已整改，不按文本永久去重 |
| FLOW-08 | 候选关联到触发异常的证据，不能借用心跳；dht-candidate-linkage | 已有场景覆盖；WF-ISSUE-01 已整改，仍不证明真实根因 |
| FLOW-09 | 真实诊断图在 PostgreSQL 连接/图重建后继续反馈及教师处理 | 已有场景覆盖；无进程 kill/断电验收 |
| FLOW-10 | 不因学生 resolved 或测试教师审核自动批准正式知识；快照检查 | 已有场景覆盖；真实案例仍 pending_teacher |
| FLOW-11 | 相同键不同 action/note 冲突，新尝试新键正常推进；feedback-conflict-*、feedback-new-attempt | 已有场景覆盖；冲突 409，无新增副作用 |
| FLOW-12 | 反馈缺会话/缺键/非法 UUID 拒绝；feedback-missing-*、feedback-invalid-request-id | 已有场景覆盖；422，未写入 |
| FLOW-13 | AI 不得引用同诊断中与该候选无关的证据；dht-unrelated-evidence 及 `test_candidate_evidence_mapping.py` | 已有场景覆盖；Provider 与独立 guard 双重检查 |
| FLOW-14 | PostgreSQL 重建后同键重放不再推进；postgres-restart-replay | 已有场景覆盖；仅连接与图重建范围 |
| FLOW-15 | 并发、丢回执、Checkpoint 保存故障后原请求恢复/补确认；`test_feedback_reliability.py` | SQLite/PostgreSQL 保存故障注入；历史执行数量见整改报告，不宣称任意崩溃原子性 |
| FLOW-16 | 关闭会话只允许已消费反馈补确认，未消费不能继续执行；同可靠性文件 | 已覆盖已消费与未消费边界；不是解除会话限制 |
| FLOW-17 | 前端未决键不跨会话/诊断；重试同载荷，成功后真实新尝试新键 | 前端单元及学生 Mock E2E；本地未决记录与服务端找回分别验证，不承诺关页保存所有本地状态 |
| FLOW-18 | 迁移不伪造历史反馈归属且新键受唯一约束保护 | 0026 → 0027 历史升级、空库、单 Head、模型差异及重复键拒绝；当前其他迁移另验 |

补充边界：明确 unknown（包括残留候选）和空推理结果不能由解释层恢复候选；测试资料和未确认根因不得投影成教师确认案例。入口为 `test_evaluation_contract.py`、`test_ai_reasoning_v2.py`；历史依据见 [整改报告](archive/workflow-remediation.md)。


## 开发门禁对应表

这三项来自实际失败反例，不能只验证检查脚本能够成功退出。下表登记现行实现和正反例；本次文档核对不重新宣称远端 CI 或全部代码通过。

| 编号 | 要求 | 唯一入口与反例 | 检查边界 |
| --- | --- | --- | --- |
| GATE-ENV-01 | 健康接口如实返回配置环境，测试不依赖开发环境默认值 | `backend/tests/test_health.py::test_health_check_returns_structured_status` 独立构造 development/test Settings；CI 明确 `APP_ENV=test` | 测试不读本机 `.env` 决定预期，不把接口改成固定 development 来消除失败 |
| GATE-PROTOCOL-01 | 固件协议检查同时检查信封和实际记录内容 | `scripts/check_firmware_protocol.py` 复用 `services/device_protocol.py`；`test_development_gates.py::test_firmware_gate_validates_actual_records` 包含缺值、错误类型、NaN/Inf、空批次、版本/容量及无 NTP 合法例 | 验证提交的协议样例，不等于已捕获真实 ESP32 的全部报文 |
| GATE-VERSION-01 | 包内容修改须提高版本；当前说明与实际版本一致，历史记录保留 | `scripts/check_version.py`、`scripts/package_versions.json`；`test_development_gates.py` 包含未升版本、只刷新哈希、过期当前文档和合法升级/历史保留 | 比较显式 Git 基线；仅检查脚本列明的当前文档表述，不承诺自动理解所有文档 |

版本基线的本机/CI 设置、完整门禁的实际步骤及缺环境处理见 [测试与评测](evaluation.md)。修改协议字段或检查规则时必须核对运行时消费入口和这些反例；修改当前版本文档时应运行版本门禁，而不是改写历史报告来凑一致。

## CoT 检查对应表

提示策略与当前版本见 [AI 设计](ai-diagnosis-design.md)；历史软件证据见 [实施报告](../output/audits/cot-implementation-latest/report.md)（本机产物，可能不随检出提供）。

| 编号 | 确切检查与入口 | 范围 |
| --- | --- | --- |
| COT-CODE-01 | `test_r2_provider_data_boundary.py::test_evidence_review_uses_one_governed_call` | 实际服务使用一次 Mock 调用，unknown 空候选落库；不证明模型自然会返回 unknown |
| COT-CODE-02 | 同文件 `test_evidence_review_request_and_audit_keep_versioned_contract` | 实际请求的版本、外发字段、Schema 和审计哈希 |
| COT-CODE-03 | 同文件 `test_evidence_review_cannot_bypass_action_assertions` | 白名单外动作经代码拒绝并降级 |
| COT-CODE-04 | 同文件 `test_old_reasoning_replay_is_not_relabelled_or_called_again` | 旧记录重验，不重发请求、不改历史版本 |
| COT-SEM-01 至 06 | `semantic_rubrics.json`；`runner.run_evaluation` 的 semantic_review | 理由依据、未知、冲突、建议状态、一致性、表达；全部保留 not_run/null |

COT-SEM-02 检查证据不足时是否保留未知，SEM-01 检查是否把候选冒充已确认根因，二者不重复计数。缺实际推理/对话/学生输出材料时不得通过；真实模型比较仍需单独执行。

<a id="context-checks"></a>
## CTX：受控上下文实施对应表

共同依据：[方案B1–B9与CTX验收矩阵](context-construction-plan.md)。下列代码检查不能判定自由文字语义；执行结果见当次报告。`test_context_construction.py` 简称packing，`test_context_evaluation.py` 简称evaluation。

| 编号 | 实际入口与断言 | 边界 |
| --- | --- | --- |
| CTX-01 | packing `test_safe_case_keeps_units_negation_and_identity`、`test_explanation_actual_requests_manifest_cache_and_retry`；F01/F11 | 比较实际请求、版本和指纹 |
| CTX-02 | F02–F05逐项资格反例；evaluation `test_invalid_source_gate_mutation_is_detected`；`test_memory_lifecycle.py::test_each_experience_gate_is_enforced` | 四项资格分别阻断 |
| CTX-03 | F06/F07/F10；`test_experiment_packages.py::test_package_versions_are_immutable_and_runtime_is_database_backed`；`test_memory_lifecycle.py::test_teacher_cannot_review_or_discover_another_class` | 实验、固定版本、测试/正式与班级范围；不存在通用型号字段，因此未实现或宣称通用型号匹配 |
| CTX-04 | packing `test_long_case_is_whole_or_omitted_never_cut_json`、`test_safe_case_keeps_units_negation_and_identity`；F08 | JSON、否定、单位及条件整体保留/省略 |
| CTX-05 | packing `test_required_51st_evidence_cannot_silently_disappear`、`test_graph_reads_full_temporary_registry_without_growing_checkpoint` | 上游临时读取全量；外发超限拒绝，Checkpoint不扩张 |
| CTX-06 | packing `test_required_oversize_explanation_has_zero_attempts`、`test_pure_packing_does_not_mutate_input_or_include_private_schema` | 可选材料先退出；必需超限0次调用 |
| CTX-07 | packing `test_dedupe_is_request_local_and_versions_stay_distinct`、`test_distinct_observations_are_not_text_deduplicated` | 单次同源去重，不永久排除已读依据 |
| CTX-08 | packing实际请求/缓存测试；`test_memory_lifecycle.py::test_recorded_call_sources_remain_the_pre_call_snapshot` | matched/provided/derived及提前快照；有效引用沿原cited逻辑 |
| CTX-09 | `test_memory_lifecycle.py` 的withdraw、late_version、cache_invalidation；`test_memory_postgres.py::test_source_delivery_waits_for_withdrawal_then_rechecks`；原工作流恢复测试 | 停用、撤权、在途变化、缓存与恢复不跳过重验 |
| CTX-10 | packing实际请求/缓存测试的策略变更分支；`test_r2_provider_data_boundary.py::test_old_reasoning_replay_is_not_relabelled_or_called_again`；原解释幂等测试 | 新策略改变缓存；旧阶段无额外调用/计费、无补写 |
| CTX-11 | packing秘密来源、脱敏增长、四种身份冲突；`test_r2_provider_data_boundary.py` 两阶段真实请求边界 | 不新增外发字段与允许动作；提示注入仍为数据 |
| CTX-12 | 原规则/工作流/业务只读测试；`test_memory_lifecycle.py::test_three_memories_do_not_promote_observations_or_write_on_read` | 规则、动作、计数、升级与读写职责不变 |
| CTX-13 | evaluation 的期望隔离、归因与缺材料测试；F01–F11 | 独立期望只给评测器；不存在全库推测 |
| CTX-14 | packing实际请求指纹、重试同Prompt、私有Schema、旧JSON损坏；旧推理无manifest重放 | 指纹可重算；旧未知不回填 |
| CTX-15 | F01/F11；原 `test_r2_provider_data_boundary.py::test_full_workflow_remains_usable_without_ai`；既有DHT/LED证据语义测试 | 代码不将案例升级本次实测；自由表达按SEM/COT人工审阅，当前not_run |

当前11份上下文评测材料均为合成回归集。没有独立真实保留集或人工审核产物，不能把这组软件检查写成真实诊断效果通过。
