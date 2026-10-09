# Experiment Package 与证据治理

代码核对日期：2026-09-28。本文维护包结构、运行契约及语义边界；制作、来源登记与审核流程见[资料包内容规则](development-guidelines.md#package-content)，软件/硬件/教学验收状态见[项目真实性看板](project-truth-status.md)。

[资料包与上下文合同](experiment-package-design.md#格式11来源登记与案例条件)的P0–P3已实施：案例条件传递、来源关联与调用预检。P4概念外发未实施，教学原文的边界保持下述约定。

## 目标

芯鉴知微使用“通用诊断引擎 + 版本化实验包”扩展实验。新增实验应主要增加数据和测试，
不能默认增加专用 Python 判断函数。实验包是开发和交付格式；PostgreSQL 中经过审核发布的
不可变版本是运行时真相。

## 包结构

```text
experiment_packages/<experiment_code>/
├── metadata.yaml
├── hardware.yaml
├── diagnosis/
│   ├── rules.yaml
│   └── fault_tree.yaml
├── knowledge/
│   ├── concepts.yaml
│   └── cases.yaml
├── teaching/
│   ├── steps.yaml
│   └── hints.yaml
└── tests/
    ├── normal_cases.yaml
    └── fault_cases.yaml
```

服务端根据这 10 个文件生成 Manifest：每个文件一个 SHA-256，整个包再生成一个
SHA-256。Manifest 不信任客户端传入值，由服务端重新计算。

包只允许数据，不允许 Python 插件、脚本路径或任意表达式。规则和故障树只能使用系统
已注册的事实、比较运算符和字段结构。Pydantic 使用 `extra=forbid`，未知字段直接拒绝。

## 格式1.1、来源登记与案例条件

引擎兼容契约为`2.2.0`。加载器按`metadata.schema_version`分派`1.0/1.1`；1.0使用冻结的模型和序列化规则，旧库存文档直接参与hash校验，不插入1.1默认值。十文件与Manifest算法不变。1.1要求引擎范围覆盖当前引擎；新格式包不能交给只支持1.0的旧程序。

1.1新增`metadata.content_registry`，其`sources/units/value_owners`只登记来源与已有内容的位置。来源有版本、位置、定位、可取得状态和可空hash；单元有固定工件/实体/字段选择器、陈述性质、`source_refs/derived_from/depends_on`，不另存一份摘要。概念/步骤的必要条件归单元登记，案例条件只归`solutionRecord.confirmation_material`，禁止重复填。作者不能在登记内自授审核状态。运行不会读取登记中的URL或任意文件。

选择器只接受后端白名单的工件、实体与字段，检查不存在、重复、循环和越界引用；`value_owners`检查声明的重复结构化值及单位。自然语言数字是否正确仍需审阅。服务器在报告生成`package_version_id + package_hash + unit_id + unit_hash`，不将hash写回被哈希内容。预检未提供可信来源快照时标`unverifiable`；提供时精确比hash，`verified_identity`只表示身份匹配，不表示来源真实或教师批准。

案例限制正文唯一入口是`solutionRecord.confirmation_material.applicability_limits`，非空且最多2000字符。可选`applicability_conditions`使用`version: 1`，`conditions`为非空列表；仅允许`experiment_code/package_version/component_id`和`operator: in`，精确AND匹配，不执行表达式。后两字段须同时声明实验代码。条件来自固定诊断版本和单一明确组件范围，缺失/歧义为unknown。1.0拒绝隐藏该新字段；全局案例通过审批Schema写入，无需数据库迁移。

匹配在top-k前过滤无效/缺少限制及不匹配/unknown条件，保留原审核、测试与实验边界；未声明结构条件为`text_only`，不能冒充已验证。模型案例投影`case-applicability-v1`含完整限制和代码检查结果，与案例整条选取或省略。详细模型、重放合同见[AI设计](ai-diagnosis-design.md)。

全局案例停用只将同ID或明确`derived_from`的改名包副本列为影响候选，不自动撤销固定包；无来源链的历史覆盖保持未知。离线预检命令及退出码见[测试指南](evaluation.md#package-context-preview)，不会导入、发布或连接Provider。

## 校验和发布

导入前依次检查：

1. 10 个必需文件是否完整；
2. 每个文件是否满足严格 Schema；
3. 组件、接口、GPIO、错误类型、原因 ID、证据类型和案例引用是否存在；
4. 正常样例是否不误报、故障样例是否命中预期错误和候选原因；
5. 文件哈希与包哈希是否可重复计算。

发布状态为：

```text
draft → pending → approved → published → superseded/revoked
```

管理员负责状态变更。已导入的 `experiment + version` 不允许覆盖；修改任何内容必须提高
版本号并重新走校验和审核。新版本发布后旧版本标为 superseded，固定该版本的既有会话仍可使用，但它不再是当前版本；revoked 则阻断教学使用，历史事实保留。发布竞争按实验父记录串行处理，不能产生两个当前版本。

状态名 pending 是实验包状态；案例草稿使用 pending_review，不能互换。软件校验通过和管理员状态流转不等于实物或教学验收。

## 运行时绑定

实验任务可绑定 `experiment_version_id`；新会话开始时固定允许使用的包版本。后续工作流使用会话固定版本，任务改版不会偷偷迁移既有会话；客户端不能把任务切换到另一包。历史会话没有固定字段时按现有兼容路径校验，不回填历史来源。`DiagnosisContext`、`DiagnosisState`、`diagnosis_results` 和
`diagnosis_workflow_runs` 都记录实验身份、版本 ID 和包哈希。

未绑定实验包的旧请求继续使用原 Experiment Definition 路径，保证已有功能兼容。新实验
应使用 Experiment Package，不再扩展旧路径。

## 标准证据

`diagnosis_evidence` 为每条证据保存：

- `evidence_type`：标准事件、观测或规则事实类型；
- `source_type + source_ref`：证据来自哪条日志、读数、心跳或规则；
- `raw_payload`：设备原始值；
- `normalized_value`：通用规则和 AI 使用的标准结构；
- `occurred_at`：设备事实发生时间；
- `diagnosis_id + experiment_version_id`：所属诊断和实验版本。

规则输出和故障树原因使用这些证据的 UUID。AI 输出中的 `used_evidence_ids` 必须属于本次
诊断；原因 ID 必须属于故障树候选集；错误类型必须与规则结果一致。不满足任一条件就回退
确定性结果或输出 `unknown`。

## 当前示例与校验入口

当前完整包为 `dht11_temperature_humidity@2.0.11` 和
`gpio_led_output@2.0.4`。DHT11 工作区版本 2.0.11 仍是测试草稿；两包用于证明同一套加载、规则、故障树和证据链可以处理不同实验。

两个包及其案例均为合成测试资料，并明确标记测试数据；没有真实硬件和教师审核时不能作为
正式实验知识发布。`metadata.compatibility.engine` 在导入、发布检查和运行装载时执行版本范围校验。
`knowledge/concepts.yaml` 和 `teaching/steps.yaml` 通过显式 bindings 接入新指导，详见下方教学参考契约；旧记录不补关联。

本地校验入口为 `python -m app.cli.verify_experiment_packages`；导入与发布端点见
[API 契约](api-design.md#experiment-package-接口)。内容制作不在此另列流程，以顶部准则链接为准。

## 证据和测试资料的语义边界

以下是当前包与引擎的契约，不是某次修复完成报告。工作区内容不代表已经导入运行数据库，配置是否可用于真实硬件仍须独立确认。

### 案例与候选

两包案例使用 `sourceType: test_data`、`facts.verification_status: unverified`、`isTestData: true`、`reviewStatus: draft`、`rootCauseStatus: unknown`；清除根因值、教师署名、确认时间，撤销 factsLocked/qualityCheckPassed。沿用现有枚举，不新增 test_data 或 unverified 审核状态。Schema 拒绝 sourceType=test_data 的案例冒充 approved/confirmed。包导入保守继承案例测试标记，调用方不能仅靠省略 is_test_data 把示例包变为正式包。

两个故障树当前标为 placeholder；同一异常症状对各原因等权支持，不再借同一日志重复加权优先认定某根因。它们仍提供待验证候选，不是真实教师诊断经验。

### 失败计数

DHT11 规则使用 `failure_count_in_window`，现保留阈值 5，含义是所选窗口内累计的指定组件失败事件数；阈值仍在 rules.yaml 可配置，待硬件校准。规则证据 details 同时记录累计数及 `consecutive_failure_count: null`。没有经过验证的逐次成功/失败完整序列，因此未实现或启用连续失败阈值，不以累计次数冒充连续失败。

`required_parameters.consecutive_failure_threshold: null` 是待确认占位，不是正在运行的规则。工作流 `failure_count/historical_failures` 表达持久化问题中的异常证据轮次；`attempt_count` 表达未解决排查尝试。它们都不能替代设备采样失败计数。

### LED 证据语义

| 语义 | 实际持久化类型 / 值 | 所需来源声明 | 能说明什么 |
| --- | --- | --- | --- |
| 来源未验证的旧 level | observation.level / 0或1 | 未确认 | status=unknown；不能推出下列三类事实 |
| GPIO_COMMAND_HIGH | observation.gpio_command_level / 1 | measurement_source=command | 设备报告 HIGH 命令，不说明引脚实测或发光 |
| GPIO_ACTUAL_LEVEL_HIGH | observation.gpio_actual_level / 1 | measurement_source=electrical_measurement | 设备报告电气测量；实际测量方法仍 pending_hardware |
| LED_PHYSICALLY_ON | observation.led_physically_on / 1 | measurement_source=optical_observation | 独立光学观测的报告；当前没有已验证的光学硬件来源 |

来源声明本身不是仪表校准或真实性认证。HTTP reading 将 measurement_source、command_id 放在 metadata 中；原始映射测试可以使用顶层字段。缺少或不匹配来源声明的后三类观测为 unknown。标准 Evidence UUID 和 normalized_value.status 一起进入 AI 证据投影；AI 提示明确禁止 level→实际发光、累计→连续的推断。

LED `state_matches_command` 比较相同 component/interface、相同非空 command_id 下的命令与电气观测，要求值为二态、状态有效、时序与响应窗口有效。LOW 与 HIGH 都按当前命令比较，不再固定以 1 为正常。`within_seconds` 当前 null，未确认窗口时比较结果 unknown。没有自动启用实际发光判断。

### 通用运行健康与显式正常

通用规则保存在 `backend/app/diagnosis/base_health_rules.yaml`，由现有规则引擎统一执行；未复制到任何实验包。声明 runtime_expectations 的实验会合并该基础规则，规则版本/hash 包括基础来源。历史未声明该字段的实验沿用兼容规则，不重写历史包。

hardware.yaml 的可选 runtime_expectations 包含：

- `verification_status`：当前 pending_hardware。
- `offline_after_seconds`：当前 90，沿用项目示例策略，不是硬件标准。
- `heartbeat_maximum_age_seconds`：当前 90，同为待验证监测时限，不等于真实发送周期。
- `required_observations`：按 component_id + metric 列出必需观测及可选单位/合法值。
- `maximum_age_seconds`：控制最新样本年龄及观察窗口内相邻样本最大间隔；当前全部 null，等待实际采样周期和容差确认。

DEVICE_OFFLINE 判断上报可达性；HEARTBEAT_STALE 独立判断心跳新鲜度；DATA_STALE 判断已配置时限下的必需数据缺失、过期或周期中断。不从这些异常推断断电、损坏或断线的唯一根因。心跳优先使用持久化心跳的服务端接收时间。

`DiagnosisContext.normal_assessment` 随 context_snapshot 保存并进入诊断核心输出。只有心跳/可达性、必需数据新鲜度与周期、数值有效性、所有配置的 expected_behaviors 和无异常规则命中均满足，才为 normal；违反条件为 abnormal；缺参数、缺证据或只有一组采样无法验证周期时为 unknown。周期至少要有两个不同采样时刻，校验所选窗口中的样本间隔；这是工程完整性判据，未校准为课堂验收。

normal 的 scope 固定为 reported_telemetry_only，并携带 pending_hardware，不代表器件精度、实际发光或整套硬件验收。当前示例读数周期、LED 响应窗口留空，故不会给出完整 normal 结论。

### 接入与校验

legacy 日志归一化支持 sensor_snapshot.component_id/interface_id；仍由已声明组件和规则参数匹配，未凭错误码猜组件。DHT11 的错误事件、temperature/humidity，LED 四类观测均与实际持久化名称对齐。对声明新 runtime_expectations 的包，新增 evidence.runtime_types 校验，阻止声明类型与静态映射输出类型不一致；旧包维持兼容。

包内 facts 样例仍只验证规则结构，零命中样例明确不声称正常。HTTP→持久化→context→Evidence UUID、显式正常、LED 语义隔离和累计计数的回归覆盖在 `backend/tests/test_experiment_trust.py`。这些都是自动化合成数据测试，不能当真实硬件案例。

## 参数来源与版本变更

`required_parameters.truth_status` 逐项记录待硬件、待教师或待课程确认状态、来源定位和所需材料。
案例 facts 的教师/学生案例/课程状态也是审核注记，不能据此自动补出 GPIO、阈值、周期或经验。
LED 旧 level 映射用 `match.metric: null` 与显式 command/electrical/optical 指标分开，避免同一报文重复映射。

工作区内容哈希由加载器按解析后的文档计算；导入后以服务端规范化快照重新计算 hash。
`scripts/check_version.py` 将源码包与明确 Git 基准比较，再核对 `scripts/package_versions.json` 和指定的
当前版本说明。内容有变化必须升版本；只更新 hash 不能绕过基准比较。历史报告保留当时版本，不批量改写。
版本检查不是包发布，也不代表硬件适用性通过；完整包校验仍由 loader 和包内样例执行。

## 教学参考契约

以下为当前可选字段；旧包缺字段仍可读，原始快照及 hash 不改变。

- `teaching/steps.yaml.bindings`：每条包含tree_id、cause_id、component_id、levels、concept_ids、step_ids。
  同树/原因/组件/等级只能有一条绑定；所有引用必须存在，至少引用一个知识点或步骤。
- `steps[].prerequisite_step_ids`：先行实验环节；禁止缺失引用与循环。按声明次序稳定展开，公共依赖仅展示一次。
- 未填写绑定的旧内容保持未关联；当前不按文字猜测用途、不默认展示整包资料。

运行选择只接受持久化问题中的单一component范围，匹配固定包、树、原因和实际提示等级。
接口级/组件不明/多组件歧义保持缺失。实验步骤及其依赖只是参考，不是自动追加的允许动作。
动作仍来自已生成的故障树提示；独立hints.yaml当前仍是被校验存储的工件，不会覆盖故障树提示。
两处既有提示文字不完全相同；当前不通过同步文字改变动作。未来若统一，须独立说明兼容影响。

`GuidanceHistory.hints[].teaching` 保存契约版本、包版本ID/hash、资料状态、测试标记、知识点和步骤全文。
与原指导同事务写入，旧指导读取不回填；学生API与指导API复用同一JSON快照，反馈重试不改写。
可选字段使用已有JSON列，无数据库迁移；旧前端可忽略新增字段。
包撤回时现有教学可用性检查暂停学生建议，保留历史事实。资料加载失败时不生成参考，不扩大动作集合。

参考文字不进入推理/解释/润色Provider投影，不新增模型调用、Prompt字段或AI缓存契约。
学生页面通过原文显示“知识说明”“预期观察（不是实测结果）”，明确测试材料状态；不提供执行完成按钮。
教学参考不改变计数、提示升级、复测流程、恢复判据或教师审核事实。

## 设计参考来源

以下方法仅作设计参考，不替代本项目的软件、硬件和教学验收：

- The Carpentries：[内容组织](https://carpentries.github.io/lesson-development-training/lesson-content.html)、[试教与维护](https://carpentries.github.io/lesson-development-training/instructor/operations.html)用于明确目标、练习和教学反馈。
- Wokwi：[电路结构](https://docs.wokwi.com/diagram-format)、[自动化场景](https://docs.wokwi.com/wokwi-ci/automation-scenarios)用于记录可复现场景；仿真不能证明真实供电、接触和器件状态，也不要求采用其接口。
- Zephyr：[样例规范](https://docs.zephyrproject.org/latest/samples/sample_definition_and_criteria.html)用于写清硬件要求、运行方法及预期输出；可运行样例不能代替异常与恢复测试。

## DHT11 2.0.7内容修订

项目`minimum_interval_ms`与配置周期均为3000ms；厂商V1.3的严格大于2秒限制由原始手册定位解释，不把2000ms当允许的等值边界。`identify`是connect/configure/observe的先行参考，`protocol_evidence`在三个读取失败原因分支的四级提示中可选取；只影响新指导参考快照。来源新增厂商附件与对应固件源码hash，旧基线保留为内容沿革；硬件/教师/课程分别待确认。LED 2.0.4内容未变。

## 内容制作与来源审查

用户于2026-09-21确认的固定制作流程持续生效。先做好一个范围明确的样板，再扩其他实验；完成度按实验问题能否回答判断，不按文件数量判断。工件结构和运行消费查[实验包设计](experiment-package-design.md)。

| 阶段 | 可审查产出与完成条件 |
| --- | --- |
| 1. 定范围 | 范围卡：学生/前置知识、教学目标、板卡器件、接线、程序依赖版本、预期观察、验收与不覆盖项；未知单列 |
| 2. 收来源 | 来源登记：材料支持哪条内容、适用条件与用途 |
| 3. 整理事实 | 每条一个意思，保留来源、条件、单位、确认状态；分开来源陈述、当前配置、实测及待验证建议，冲突未解不择优认定 |
| 4. 写内容 | 正常流程＋异常排查卡，明确下一动作要获得什么信息；没有真实案例不编造 |
| 5. 映射工件 | 审阅后映射十类工件，核对引用、实际消费路径及缺口，形成版本化草稿 |
| 6. 分层验证 | 软件、真实硬件、教学试用分别记录结果及未执行项，失败可返回前面阶段修订 |
| 7. 审核维护 | 按职责确认事实和教学判据，走已有审核发布；新证据修订追加版本，保留原来源与旧结论 |

允许独立工作并行，不必等齐外部材料才写软件草稿或做合成验证，但不能越过缺失的事实确认门槛。2026-09-22用户已授权维护者在缺购置硬件/教师支持时按官方资料选择候选板卡、器件与框架并推进软件自审；候选标`project_design`，实物/课程/教师结论保持pending，不能预填确认人和时间。用户于2026-09-28确认首轮硬件选型，决定统一记录于[真实性看板](project-truth-status.md)；采购选型确认与实物验证状态分开，不因选型确定清除pending。

- **采信来源：**课程目标/判据优先教师和正式指导书；板卡/器件用对应厂商版本的手册、原理图；程序语义用实际源码、依赖和官方示例；实物结论用接线、原始日志、独立测量、操作及恢复新样本。社区材料只能提出待核查线索，通用器件参数不自动成为板级接线或阈值。
- **来源登记：**至少记录位置、版本、页码/章节/代码定位、适用硬件、支持内容与未决问题；保留原附件，包内保存经审阅内容及引用。来源冲突先查型号、版本、条件和测量语义；教师经验有提供者和依据。使用现有字段/审阅材料，不向严格Schema偷加字段。
- **正常流程：**学习目标、前置知识、器材接线、程序配置、步骤、预期观察、结果记录及课程判据；缺判据留缺口，预期不冒充实测。
- **排查卡：**现象/证据、能判断与不能判断的内容、有限候选、允许动作/前提、区分作用、需留记录、新证据验证方式、何时求助。排查顺序不等原因概率；恢复沿用[生命周期判据](development-guidelines.md#business-rules)。正式案例可留空，合成场景明确标测试。
- **验收职责：**维护者验证结构/规则/引用/版本和正常、异常、缺测、旧数据、冲突、恢复；硬件负责人做正常—单因素异常—恢复的独立对照并隔离调参与验收数据；教师确认目标/动作/判据并观察未参与编写者的卡点、误解、求助。同人可兼任，职责与依据分开。AI可整理资料和软件检查，不代实测、教师确认或发布决定。
- **变更管理：**范围卡、来源/事实清单、流程/排查卡、待确认项可集中记录。补有依据内容、改错字/链接不需重定规则；改变流程、采信、事实边界、工件职责或验收/发布门槛，须说明差异、理由、影响、兼容及确认依据，经用户明确确认再实施，当前明确变更指令可作为确认。不得借演示、新对话表述或外部方法静默弱化。

## P4概念解释合同（未实施）

以下保留尚未实施的设计边界，不表示新增能力已落地；当前 concepts/steps 仍不外发。

只允许与当前固定指导的树/原因/组件/等级显式绑定、经审阅的少量概念，进入**解释阶段**。步骤正文继续作为学生参考；引用概念不能成为Evidence UUID、确认案例或新增允许动作。该能力采用独立默认关闭开关，仍受总AI开关控制，不新增一次模型调用、不绕过ai_require_knowledge。

审核复用现有`AuditEvent`，新增专用材料审核动作：操作者须有`knowledge.review.approve`及所列来源的当前读取权限，不能由查看班级或发布包权限推导；确认一份冻结清单，事件绑定版本ID、包hash、单元ID/hash、用途和支持依据。普通包approved/published事件、作者署名和软件预检均不能替代该记录。按包父记录锁顺序串行，等待后重验权限和版本；审核与审计同事务。幂等身份为`版本ID＋操作者＋request_id`，同载荷返回原事件、异载荷409；所有入口持同一父记录锁并使用严格事件Schema。首版撤销该外发资格沿用明确整包revoke；细粒度单元撤回留待独立设计。无此审核记录不外发。

P4的`guidance_ref`由后端从当前指导身份及允许动作定位生成，概念引用ID由包hash和unit_id生成；不要求模型发明身份。内部保存全量身份对应关系，外发只给稳定、不含用户身份的引用；映射属于本次封存输入，重放不得用新动作顺序重新解释旧索引。

| P4合同（拟定） | 完整路径与限制 |
| --- | --- |
| 输入 `teaching_references[]` | 独立于knowledge案例数组，最多3个当前绑定概念；只含本地生成引用ID、已审正文、必要条件、状态和允许动作关联。单元清洗后上限起点1000字符且共享总预算，按bindings原次序去重；超限整条省略。 |
| 输出 `teaching_explanations[]` | 新增可选数组，最多3项；每项`guidance_ref/concept_ids/text`，text起点上限300字符。引用必须属于本次已提供集合，guidance_ref只能指向现有指导/允许动作；步骤、异常、候选及计数合同不变。 |
| 本地校验和展示 | 检查类型、引用、绑定及长度；无效教学项丢弃并保留既有解释/原文。显示在当前指导旁，标“AI辅助理解”，保留来源、条件及资料状态。自由文字正确性需独立语义验收，关键词扫描不充当安全证明。 |
| 审计和兼容 | 输入、输出、缓存、前端类型与渲染同步版本化；概念提供/引用在manifest独立记录，包来源继续由MemoryUse跟踪；不塞入case_ids。旧输出缺数组默认空，不补历史参考或再调用。 |

这些容量是首版工程约束，不是效果最优值，须用预检与独立样本核对。软件接通后只有取得真实、已审内容和模型对照证据，才评估是否启用；当前两包草稿不因此获得正式经验或概念审核资格。
