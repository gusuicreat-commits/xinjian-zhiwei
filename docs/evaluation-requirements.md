# 评测要求、测试与依据对应表

更新：2026-09-15。范围：ClawEval 适配、完整流程评测及 PDF 反例整改；不包含真实模型、硬件或课堂效果验收。

## 项目负责人可读摘要

| 问题 | 结论 |
| --- | --- |
| 这次发现了什么问题？ | PDF 复查发现关键词会误判否定句、漏掉改写；固定模板丢掉具体限制；Rubric 的二元要求记录不完整。 |
| 会造成什么现实影响？ | 正确提醒被拦、错误声明漏检，学生只能看到泛泛的限制；代码通过容易被误解为语言质量通过。 |
| 现在能不能解决？ | 已把关键词扫描改为无判定的线索，代码结果与未执行语义审阅分开；摘要增加本次异常，保留具体待核验项并标明未确认；补齐二元 Rubric 清单。完整语义审阅没有假装完成。 |
| 如果不能，需要谁确认？ | UUID 存在不等于因果成立；真实故障、测量来源和阈值仍待硬件确认，教学动作和效果仍待教师确认。 |
| 下一步最应该做什么？ | 审阅反例回归结果，再用独立输入/输出材料逐条人工核对语义 Rubric；模型裁判仍需另行批准，真实硬件与课程事实另行验证。 |

## 来源与适配原则

参考用户提供的《ClawEval质检标准.pdf》4 页，导出标记为 2026-09-02 10:54，SHA-256：
`2802cc63c54110d2fbd1b079a4dcd7864377d6c8294fafdc7486431b26929520`。
PDF 是评测设计参考，不是器件参数或正式 KnowledgeCase 来源。原 PDF 未复制入仓库。

采用：精确事项用代码；检查实际输出；要求逐项可追溯；正确样例与错误反例并存；区分结果和过程材料。
不照搬：外部固定路径、默认 ±15% 容差、禁止评测器读取参考答案、为凑数量重复测试。
文档中数值 rubric 与精确校验、混合测试示例存在不一致，项目统一以代码检查可确定事项。
第 4 页部分安全场景裁切，外链安全规范未包含在文件中，不宣称已实施该规范的全部内容。

### Rubric 的必守约束（补齐原文第 1 页）

- 每条实际判断仅允许“符合”或“不符合”；禁止打分、评级和分数阈值。
- 文本只描述“符合”的条件，不写 PASS/FAIL 两侧对照。
- 每条只检查一件事；独立要求必须拆开。
- 每条不超过 400 字符、3 句话。
- Rubric 不列关键词清单；精确字段/ID/枚举等用独立代码检查，语义不能用关键词替代。
- 未审阅时 judgement=null、status=not_run，不是第三种判定，也不能算“符合”。不合并成总分，不让一项符合抵消另一项不符合。

第一版可审阅条目在 `backend/evaluation/semantic_rubrics.json`：根因是否仍为候选、硬件验证陈述是否有依据、缺失证据限制、下一步检查对象。每条指定所需输入与实际输出材料；本轮没有执行真实模型语义评测或引入模型裁判。条目格式校验不证明条目的语义质量，人工审阅仍需独立依据。

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

## 第一阶段运行行为与兼容

- LangGraph 节点和边不变；仅证据投影附带观测 status，供现有校验使用。
- 解释的 `summary`、`limitations` 仍由后端组织，但根据本次规则、unknown/冲突状态及具体待核验项生成；推理提出的缺失证据需求用引号和“未确认”标注，不能当硬件事实。解释模型自由新增的文字不直接升级为事实。
- `steps` 只接受现有工作流允许动作；未包化调用只能使用已传入的持久化 guidance hints。不从任意知识正文扩充白名单。
- 推理无可关联证据时降级为 unknown，并保留已允许的下一验证动作；模型和推理后校验都拒绝无有效引用的 high。
- 当前输出契约 `explanation-boundary-v2` 保存在现有 AI 审计 JSON 中，无数据库迁移。v1 历史记录不改写；缺当前契约时保持既有 rules_only 降级行为，配套发布时应了解这项兼容边界。
- 缓存指纹纳入实际 Prompt 哈希，缓存读取重新校验。不同输入不再仅因摘要指纹相似就共享建议；可能减少缓存命中。
- 缺当前契约的历史解释只保留审计，不作为当前有效建议展示；返回 rules_only 提示，不再次计费调用模型。历史诊断和已发布包不被重写。

## 明确未完成的范围

1. 字符串扫描只记录实际出现的片段，不给语义判定，也不决定整体通过。新报告以 code_checks_passed 描述代码结果；语义未审阅时总体 status=incomplete，即使关键词没有命中。
2. AI 推理的自由 reason/summary 等字段仍未接受完整语义评价。模板保护针对最终解释摘要和限制，不宣称覆盖所有自然语言字段或教师编辑文本。
3. 有效 UUID、status 和故障树关联不等于“该证据能区分这个根因”。候选关联质量、占位故障树和真实故障可区分性仍须验证。
4. 包内 normal 样例仍只验证包内规则未命中；候选样例只检查树内成员资格。完整正常运行和候选排序由独立测试覆盖，包校验不能代替它们。
5. 未引入 LLM judge、真实模型基准或自动教学评分；完整流程评测已能导出合成多轮材料，但不证明真实模型语义质量。未改实验包 Schema、版本或事实状态。
6. 原有提示注入、权限、草稿和只读测试仍保留；不能把 Prompt 中写了“不执行”当作完整的对抗验收。

## 维护要求

每次修改应更新受影响的编号、反例和依据。不适用项写明原因；未执行、环境错误、缺少实测/课程资料不能记为通过。
测试预期应来自独立需求或经审核参考材料，不能调用同一被测算法生成答案。语义问题另列人工评价，未来引入模型辅助须单独审核。

## 完整流程与整改要求（2026-09-12）

原失败依据见 [第二阶段历史报告](workflow-evaluation-phase2.md)，最新实现与结果见 [整改报告](workflow-remediation.md)。流程要求直接对应 `workflow_expectations.json` 和 `assess_case` 返回的单项 checks；可靠性边界另由专项测试验证。

| 编号 | 要求与入口 | 当前结果 |
| --- | --- | --- |
| FLOW-01 | 设备 HTTP 上报至实际落库 UUID、归属、包 hash 和节点轨迹；每个场景快照检查 | 已覆盖；不证明证据支持具体根因 |
| FLOW-02 | 缺数据及 LED 缺光学观测保留 unknown；dht-missing、led-legacy、led-command | passed |
| FLOW-03 | 合法/未知/非法 UUID/非法 JSON/超时 Mock 经真实推理与解释路径；dht-* | 对应软件约束 passed；无真实模型质量结论 |
| FLOW-04 | 未解决继续、解决结束、教师处理及重复审核无副作用 | passed |
| FLOW-05 | 跨学生读取、跨包版本请求拒绝；拒绝不改变原流程 | passed |
| FLOW-06 | 跨学生提交及重放反馈在所有写入前拒绝；foreign-session-feedback、foreign-session-feedback-replay | passed；WF-ISSUE-03 已整改，缺失会话另按 422 拒绝 |
| FLOW-07 | 同键同载荷重放无重复副作用；duplicate-feedback | passed；WF-ISSUE-02 已整改，不按文本永久去重 |
| FLOW-08 | 候选关联到触发异常的证据，不能借用心跳；dht-candidate-linkage | passed；WF-ISSUE-01 已整改，仍不证明真实根因 |
| FLOW-09 | 真实诊断图在 PostgreSQL 连接/图重建后继续反馈及教师处理 | passed；无进程 kill/断电验收 |
| FLOW-10 | 不因学生 resolved 或测试教师审核自动批准正式知识；快照检查 | passed；真实案例仍 pending_teacher |
| FLOW-11 | 相同键不同 action/note 冲突，新尝试新键正常推进；feedback-conflict-*、feedback-new-attempt | passed；冲突 409，无新增副作用 |
| FLOW-12 | 反馈缺会话/缺键/非法 UUID 拒绝；feedback-missing-*、feedback-invalid-request-id | passed；422，未写入 |
| FLOW-13 | AI 不得引用同诊断中与该候选无关的证据；dht-unrelated-evidence 及 `test_candidate_evidence_mapping.py` | passed；Provider 与独立 guard 双重检查 |
| FLOW-14 | PostgreSQL 重建后同键重放不再推进；postgres-restart-replay | passed；仅连接与图重建范围 |
| FLOW-15 | 并发、丢回执、Checkpoint 保存故障后原请求恢复/补确认；`test_feedback_reliability.py` | 42/42 passed；28 项双库保存故障注入，不宣称任意崩溃原子性 |
| FLOW-16 | 关闭会话只允许已消费反馈补确认，未消费不能继续执行；同可靠性文件 | 已覆盖已消费与未消费边界；不是解除会话限制 |
| FLOW-17 | 前端未决键不跨会话/诊断；重试同载荷，成功后真实新尝试新键 | 前端 43 项 unit / 4 项学生 E2E 通过；关闭标签页不承诺保留 |
| FLOW-18 | 迁移不伪造历史反馈归属且新键受唯一约束保护 | 空库/带两条历史反馈的 0026 升级、单 Head、模型差异及重复键拒绝通过 |

原三个 strict xfail 已移除；25 个 PostgreSQL 场景全部通过，后端全量 330 passed、无 skipped/xfail。反馈 Schema 与迁移 0027 是兼容变化，见整改报告；LangGraph 节点、边与实验包版本机制保持不变。证据引用合法和关联匹配异常都不能代替硬件因果验证。

2026-09-15 追加反例覆盖：明确 unknown（包括残留候选）和空推理结果不能由解释层恢复候选；测试资料和未确认根因不得投影成教师确认案例。对应测试：`test_evaluation_contract.py` 和 `test_ai_reasoning_v2.py`；完整回归结果见 `workflow-remediation.md` 追加复查部分。
