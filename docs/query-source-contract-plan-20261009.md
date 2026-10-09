# 受控查询：真实资料来源合同方案

日期：2026-10-09。状态：**待用户审阅的设计**，未实现。前置结论见[受控查询评测摘要](controlled-query-evaluation-20261008.md)：B0 模型选动作没有显示额外收益，下一步采用**确定性受控查询**，先补真实资料来源，再做最小产品接入。持续规则仍只维护在[开发准则](development-guidelines.md)，本文只定义查询来源的合同与落点。

## 1. 要解决的问题

`query-task-v3`（`backend/app/evaluation/query_contract.py`）定义了 3 个工具（`query_evidence`、`query_package_requirement`、`query_approved_cases`）和 3 类需求（`configuration`、`led_report`、`independent_led_observation`），但：

- 工具背后全是**合成适配器**，`EvidenceRef.is_test_data` 固定为 `True`；
- `saved_configuration_comparison` 在产品里**没有生产方**（真实性看板也记录“没有完整类型化实读配置生产方”）；
- 追问目录 `QUESTIONS` 明确标注为合成，未经教师或课程确认；
- 授权/来源复核是可注入的合成标记，生产身份与来源服务尚未接入这条路径。

本方案回答：**学生当前任务允许查哪些真实资料、各自代表什么、何时必须停止交付**。只覆盖 DHT11 `SENSOR_READ_FAILED` 一个场景；LED 沿用同一合同，待其真实来源（电气/光学观测）存在后再加。

## 2. 设计原则

1. **只读已有业务事实，不新造事实。** 每个来源对应一个现有的生产方和模型；没有生产方的需求标 `not_available`，不由模型或文本推断补齐。
2. **复用现有守卫，不另写一套。** 身份用 `authorize_student_actor`，包与案例来源用 `memory.current_source` / `approved_case`，案例适用性用 `evaluate_case_applicability`，外发与费用仍只走 `GovernedAIInvocation`。
3. **取证不确认根因。** 查询结果只进入指导的“已知/缺失”部分，**首版不改变故障树候选排序或支持边**；任何把材料映射为候选支持的规则需教师确认并版本化。
4. **确定性策略。** 动作顺序由合同决定（先查存档，后问一道许可问题），产品路径不调用模型选动作；业务 AI 保持默认关闭。
5. **失败分清楚。** `denied`（无权）、`error`（工具故障）、`checked_empty`（查了没有）、`not_available`（没有生产方）互不冒充。

## 3. 来源目录（DHT11 首版）

| ID | 来源 | 生产方 / 存储 | 代表什么 | 不代表什么 |
| --- | --- | --- | --- | --- |
| S1 `task_evidence` | 本次诊断已冻结的证据 | `diagnosis.py` → `DiagnosisEvidence`（按 `diagnosis_id`） | 规则使用的上报与规则事实 | 硬件状态、根因 |
| S2 `firmware_reported_config` | 失败日志中固件自报的配置 | 固件 0.2.5 在每条 `DHT11_READ_FAILED` 日志写 `sensor_snapshot.gpio`（`firmware/esp32_dht11/src/main.cpp`）；诊断时随事件证据冻结进 `DiagnosisEvidence.raw_payload` | 当次运行的固件编译常量 `XJ_DHT11_DATA_GPIO` | 实际接线、引脚电气状态 |
| S3 `package_requirement` | 会话固定包的接口要求 | `ExperimentVersion` → `hardware.yaml` `interfaces[].pins`（如 `dht11_gpio.data=4`） | 本实验**要求**的配置 | 学生实际配置 |
| S4 `approved_case` | 通过审核且适用的案例 | `KnowledgeCase` / 包内案例，经 `approved_case` + `evaluate_case_applicability` | 可复用的已审核经验 | 本次根因 |
| S5 `student_answer` | 对一道许可问题的答复 | 新增答复回执（见 §6），问题来自版本化问题目录 | 学生自述的观察 | 已核验的物理事实 |

明确**不是**来源：模型预训练知识；其他会话、其他学生或归属不明的数据；未发布/草稿包和案例；日志或答复文本中的指令；任意 URL、路径、SQL 或模型给出的 ID。

### 3.1 S2 的取证范围

只读取**本次诊断已冻结**的失败事件证据：`DiagnosisEvidence` 中 `source_type="device_log"`、`evidence_type` 为该失败事件的行。归一化时这些行的 `source_ref` 即 `DeviceLog.id`，`raw_payload` 是日志载荷的冻结副本（含 `sensor_snapshot`，见 `diagnosis/normalization.py`、`services/diagnosis.py`），因此 GPIO 只读该冻结副本，不按时间窗另查，避免越出诊断快照。只采用 `source_type="device_log"`、载荷 `event_code="DHT11_READ_FAILED"` 且 `evidence_type` 等于固定包 `evidence_mapping` 映射类型（当前 `sensor.read_failed`）的行；`sensor_snapshot.gpio` 缺失或不是整数时，该行不计入比较。

同一诊断内若多条日志自报的 GPIO 不同（例如中途重烧固件），状态为 `conflicting`，同时保留各条的 `firmware_version` 和 `boot_id`。这两项在批次信封上，不在冻结载荷里：`boot_id` 按 `source_ref` 读取**同一条** `DeviceLog`，`firmware_version` 取同一 `ingestion_request_id` 的心跳记录（同批多值不一致或缺失则为 null）。这些元数据只用于说明，不参与 GPIO 判定；其变化使已采用结果失效（stale）。

### 3.2 当前各来源的真实可用性

| 来源 | 今天能否产出真实材料 | 说明 |
| --- | --- | --- |
| S1 | 能（模拟器/实物上报后） | 已有生产方 |
| S2 | 能（固件 0.2.5 已写入；实物待联调） | 软件可用模拟器构造相同载荷验证 |
| S3 | 能 | 包为测试草稿，结果保持 `is_test_data` |
| S4 | **没有合格案例** | DHT11 唯一案例为 `draft`、`unknown` 根因、测试数据；查询应返回 `checked_empty`（原因 `no_approved_case`），不是错误 |
| S5 | **没有已确认问题** | 问题目录需教师/课程确认；开发期用标注为合成的目录，不能进入正式会话 |

## 4. 需求定义（DHT11 `SENSOR_READ_FAILED`）

| 需求 | 判定 | 满足条件 | 来源与顺序 |
| --- | --- | --- | --- |
| R1 `firmware_gpio_vs_requirement` | `match` / `mismatch` / `unknown` | S2 至少一条自报值，且 S3 有对应接口要求；两者都有才比较 | S1→S2→S3，均为存档查询，无追问 |
| R2 `wiring_observation` | `matches_table` / `differs` / `unclear` | S5 答复为可解析的枚举值；`unclear` 关闭本题但保留缺口 `observation_unknown` | 仅在 R1 已查完后，问一道许可问题 |
| R3 `approved_reference` | `present` / `checked_empty` | S4 返回至少一条适用、已审核案例 | S4 存档查询 |

语义约束沿用 `query-task-v3`：`mismatch` 是比较已完成，不是材料冲突；`unclear` 是答复已收到，不是需求已满足；同源同修订换 ID 不算新进展；`completed_satisfied` 只表示取证完成。R1 为 `mismatch` 时，指导可以陈述“固件自报 GPIO 与实验要求不一致”，但仍须说明这不证明接线状态，也不确认根因。

R2 的问题文本、选项和适用条件属于教学内容，必须进入资料包（`teaching/`）并带 `pending_teacher` 状态；本方案只定义其结构（问题 ID、版本、枚举选项、适用需求），不定稿措辞。

## 5. 来源接口（服务层）

拟新增 `backend/app/services/query_sources.py`，每个来源实现同一协议；评测中的合成适配器改为实现该协议，使评测与产品走同一合同。

```text
query(db, scope, requirement) -> SourceResult
    status: present | checked_empty | conflicting | not_available | denied | error
    units:  完整单元列表（按 8 KiB UTF-8 预算整单元入选，超量计入 omitted_count）
    manifest: [{source_kind, source_id, source_revision, unit_sha256, is_test_data}]
revalidate(db, scope, manifest) -> ok | stale | denied
```

- `scope` 由服务器从已授权的 `ExperimentSession` / `DiagnosisResult` 构造，不接受调用方传入用户、课程或版本。
- `source_id` 取稳定业务主键：S1、S2 均为 `DiagnosisEvidence.id`（S2 另记其 `source_ref` 即 `DeviceLog.id`），S3 `ExperimentVersion.id + interface_id`，S4 案例 ID + 版本，S5 答复回执 ID。
- `is_test_data` 按 `derive_test_flag` 保守传播：任一来源或包为测试数据，结果即为测试数据。
- `denied` 不返回任何对象是否存在的信息。

## 6. 授权、撤权与版本变化

### 6.1 复核点

| 时点 | 复核内容 | 失败处理 |
| --- | --- | --- |
| 任务启动 | `authorize_student_actor`（账号、会话 active、设备、班级、任务），诊断属于该会话 | 401/403，不创建任务 |
| 每次查询前、查询返回后采用前 | 同上 + 该来源 `revalidate` | 撤权：终态 `revoked`，丢弃本批；来源失效：终态 `stale` |
| 提问登记、答复提交事务内 | 同上；问题版本与会话固定包一致 | 拒绝写入回执，不消费问题额度 |
| 终态写入与交付投影前 | 全部 manifest 重新 `revalidate`；`diagnosis_sources_available` | 不交付受限内容，返回确定性结果并记录原因 |
| 读取旧结果、缓存回放 | 同交付前 | 同上，不因已保存而展示 |

### 6.2 停止交付的条件

- **身份或范围变化**：账号停用、会话结束/取消、学生不再属于该班级或任务。会话结束后只允许确认原回执，不开始新查询。
- **包版本变化**：会话固定包被撤回或登记停用（`MemoryEvent`），S3 与依赖它的 R1 判为 `stale`。普通替代版本不影响已固定版本的会话。
- **案例变化**：S4 案例撤回、审核状态或内容哈希变化，该引用失效；其余需求不受影响。
- **证据变化**：诊断冻结后新到的数据属于下一次检查，不进入本任务；本任务引用的证据行不可用时判 `stale`。

### 6.3 存储位置

10-08 专项留下的缺口是“授权与查询回执分属不同存储时，撤权与提交的原子顺序未验证”。产品路径的建议是：**任务、问题、答复回执与业务数据放在同一业务 PostgreSQL 库**，采用与授权复核在同一事务内完成；LangGraph checkpoint 仍可独立，按现有规则以业务回执为准协调。这需要一个新迁移，放在下一步“最小产品接入”中实施并单独审阅。

## 7. 资源上限

沿用评测 profile，不另设：查询 4 次、问题 1 个、单次投影 8 KiB、活跃执行 120 秒。确定性路径不调用模型选动作，因此“选择 3 次”不适用；末端推理/解释仍受现有治理与全任务 5 次上限约束，AI 关闭时直接走确定性结果。

## 8. 测试材料（实现时先写，预期独立于实现）

| 组 | 反例 | 期望 |
| --- | --- | --- |
| S2/R1 | 自报 GPIO=4 且要求为 4 | R1 `match`；指导不称接线正确 |
| S2/R1 | 自报 GPIO=5 | R1 `mismatch`；根因仍 unconfirmed |
| S2/R1 | 本诊断无失败日志，或日志无 `sensor_snapshot.gpio` | R1 `unknown`，原因 `not_reported` |
| S2/R1 | 同诊断两条日志自报 4 和 5 | `conflicting`，保留两条的固件版本与 boot_id |
| S2 | 日志 `message` 中含指令文本 | 仅作数据，不改变动作集合 |
| S4/R3 | 只有 draft/测试案例 | `checked_empty`（`no_approved_case`），不是 `error` |
| S5/R2 | 问题目录未确认、正式会话 | 不生成提问动作，R2 保持缺口，终态 `finish_unknown` |
| S5/R2 | 答复 `unclear` | 本题关闭，缺口 `observation_unknown`，不再追问 |
| 范围 | 测试设备数据进入正式会话 | 拒绝，结果保持测试性质 |
| 撤权 | 查询返回后、答复提交时、交付前分别撤销学生权限 | 不采用、不写回执、不交付；不泄露对象存在性 |
| 版本 | 任务进行中包被登记停用 | R1 `stale`，不交付依赖 S3 的结论 |
| 会话 | 任务等待答复时会话结束 | 不接受新答复；原回执可确认 |
| 投影 | 单条单元超过 8 KiB | 整条省略并计数，不截断 |

## 9. 不在本步范围

- 产品 API、前端页面、数据库迁移（属于下一步最小产品接入）；
- 固件或设备协议改动（S2 已有生产方，首版不需要）；
- 把查询材料映射为故障树候选支持（需教师确认）；
- LED 场景、真实 Kimi 复测、部署、开启业务 AI。

## 10. 需要确认的事项

1. **R2 追问的内容来源**：开发期先用标注为合成的问题目录推进软件，正式问题文本与选项待教师确认后进入资料包。是否同意这样分开推进？
2. **S2 的语义边界**：固件自报 GPIO 只证明“程序设置”，不证明接线。是否同意首版只在指导中陈述比较结果，不影响候选排序？
3. **回执存储**：同意在下一步把查询回执放入业务库（新迁移），以消除跨存储撤权顺序问题？

确认后进入实现：先按 §8 写反例测试，再实现 `query_sources.py` 与评测适配器的替换，最后接入单场景产品路径。
