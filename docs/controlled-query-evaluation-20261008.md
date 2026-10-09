# LangGraph 受控查询：隔离评测与真实 Kimi 结果

日期：2026-10-07—08。批次源码指纹：`7c85867bc1f145ad24bb751232dadb43e8f46e9549480f107f262f4876b8d8f8`。本页是可随源码提交的脱敏摘要；本机完整回执、账本和逐组 JSON 保存在 `output/audits/langgraph-query-real-20261007/`，该目录按仓库约定不进入 Git。

## 已完成与边界

受控查询合同、LangGraph B0 图、持久回执、离线/真实评测 CLI 和反例测试已在隔离环境实现。复用现有固定诊断图、Provider 客户端、权限/来源服务、调用治理及 PostgreSQL checkpoint；未接产品 API 或前端，未迁移业务库、部署或开启业务 AI。

本次实际运行 36 个合成情境 × 3 次重复 × A 固定流程/B0 模型受控查询/确定性查询，共 **108 组、324 组臂**，软件合同断言全部通过。真实 `kimi-k2.6` 共 82 次请求，67 次成功、15 次返回 HTTP 429；后者全部发生在开发阶段的短时连续调用。降频后的保留集 60 次调用均成功，但两个阶段发送条件不同，不能合并计算同条件成功率。模型解释因草稿知识不满足审核门禁而没有外发。

兼容探针与动作选择使用受控 JSON，不代表原生 function calling。越界动作的拒绝由离线强制反例验证；真实样本只验证模型在合法动作集合中的响应。全批人工语义、硬件、课堂均未验收，结构通过不代表诊断准确率或教学收益。

## 批次后的共同入口修复

合并前回归又复现了 Provider 已结算、随后操作者撤权或来源失效时调用审计可能缺失的问题；推理入口还可能吞掉撤权并给出确定性结果。现已修复共同调用入口及解释/推理审计：保留已发生的 Provider 用量和内部审计，拒绝交付、缓存及业务投影，并让撤权异常显式传播。新增 SQLite/PostgreSQL 回归覆盖操作者撤权与来源失效。此修复发生在上方真实 Kimi 批次之后，批次源码指纹仍只对应当时实际发送的版本；修复后的源码由本轮软件回归验证：完整后端测试 1280 通过、14 跳过，Ruff 全后端检查通过；未把历史付费结果冒充新源码的真实 API 复测。

## 三种收益分别观察

| 观察 | 真实批次结果 | 解释 |
| --- | ---: | --- |
| A/B0 均可交付 | 72/108 组 | 其余组包含撤权、失效、等待或资源停止，不能强求交付 |
| B0 新增材料记录 | 45/72 组 | 记录增加不等于有效证据或根因确认 |
| 取证需求从未满足变为 present | 36/72 组 | 未知答复仍为 checked_empty，不计收益 |
| B0 与确定性查询材料及终态相同 | 105/108 组 | 另 3 组均为 h21 选择额度为零，B0 停止而确定性路径继续 |
| 同材料规则/AI 末端回放 | 240 组臂 | 57 次真实 AI 推理，183 次确定性回退；最终状态均保留 unknown |

新增查询材料没有被自动映射为候选原因支持边。取证完成不确认根因。模型选动作没有显示额外材料收益，因此当前建议保留固定流程，并优先研究确定性受控查询的真实来源接入；B0 继续隔离保存。

## 费用与续跑

成功响应按 token 和官方未命中价格估算 **¥1.1701715**；15 次 HTTP 429 的保守预留 **¥0.73962**；本批账本累计 **¥1.9097915**，低于单独授权的 ¥10 上限。服务商账单未核对，保守预留不是实际收费。价格依据为 [Kimi 官方计费说明](https://platform.kimi.com/docs/pricing/chat)。

批次跨本地日期，期间临时 Python 环境丢失 `pyvenv.cfg`。按相同锁文件重建并核对全部版本及源码指纹后，从原账本继续；文件丢失原因未确认。完成后再运行同一 CLI，新增 Provider 尝试为 0，108 组结果和 82 条预留不变。

## 逐情境摘要

每个情境重复 3 次。下表“新增满足”是三次重复中从未满足变为 present 的次数；“选择”是 B0 实际模型选择次数。软件检查均通过，人工语义状态仍为 `not_run/null`。

| ID | 情境 | B0 终态（3 次） | 新增满足 | 选择 |
| --- | --- | --- | ---: | ---: |
| d01 | config-found | delivered | 0 | 0 |
| d02 | report-found | delivered | 0 | 0 |
| d03 | config-archive | delivered | 3 | 0 |
| d04 | report-archive | delivered | 3 | 0 |
| d05 | report-question | delivered | 3 | 0 |
| d06 | report-unknown | delivered | 0 | 0 |
| d07 | opposed-reports | awaiting_answer | 0 | 0 |
| d08 | revoked-at-start | unavailable | 0 | 0 |
| d09 | archive-withdrawal | unavailable | 0 | 0 |
| d10 | query-error | failed | 0 | 0 |
| d11 | bad-selector | delivered | 3 | 3 |
| d12 | zero-query-budget | stopped_budget | 0 | 0 |
| h01 | two-independent-dark-reports | delivered | 0 | 0 |
| h02 | observed-illumination | delivered | 0 | 0 |
| h03 | consistent-settings-record | delivered | 0 | 0 |
| h04 | archive-physical-darkness | delivered | 3 | 0 |
| h05 | two-independent-config-records | delivered | 3 | 0 |
| h06 | unknown-then-known-archive | delivered | 3 | 0 |
| h07 | unobserved-then-light-report | delivered | 3 | 0 |
| h08 | uncertain-record-followed-dark-report | delivered | 3 | 0 |
| h09 | two-archives-then-report | delivered | 3 | 3 |
| h10 | physical-observation-not-available | delivered | 0 | 0 |
| h11 | unable-to-observe-after-prior-unknown | delivered | 0 | 0 |
| h12 | no-course-question-for-configuration | delivered | 0 | 0 |
| h13 | conflicting-settings-not-single-mismatch | delivered | 0 | 0 |
| h14 | expired-before-query | unavailable | 0 | 0 |
| h15 | contradictory-independent-sensors | delivered | 0 | 0 |
| h16 | session-input-revision-changed | unavailable | 0 | 0 |
| h17 | actor-changed-after-question | unavailable | 0 | 0 |
| h18 | source-withdrawn-after-terminal | unavailable | 0 | 0 |
| h19 | one-unprojectable-complete-unit | delivered | 0 | 0 |
| h20 | cancelled-before-start | unavailable | 0 | 0 |
| h21 | selection-no-attempt-remaining | stopped_budget | 0 | 0 |
| h22 | instruction-inside-config-record | delivered | 3 | 0 |
| h23 | identity-overwrite-model-output | delivered | 3 | 3 |
| h24 | wrong-task-tail-in-batch | failed | 0 | 0 |

详细实施边界见[执行方案](archive/README.md)，测试命令与恢复限制见[评测指南](evaluation.md#controlled-query)。
