# Experiment Package 与证据治理

最后更新：2026-09-09

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
版本号并重新走校验和审核。新版本发布后，旧版本可以用于历史重放，但不会再成为当前版本。

## 运行时绑定

实验任务可绑定 `experiment_version_id`。工作流启动时优先使用任务绑定版本；客户端不能
把任务切换到另一个实验包。`DiagnosisContext`、`DiagnosisState`、`diagnosis_results` 和
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

## 当前示例与新增实验步骤

当前完整包为 `dht11_temperature_humidity@2.0.2` 和
`gpio_led_output@2.0.2`。它们用于证明同一套加载、规则、故障树和证据链可以处理不同实验。

两个包及其案例均为合成测试资料，并明确标记测试数据；没有真实硬件和教师审核时不能作为
正式实验知识发布。`metadata.compatibility.engine` 当前只保存声明，尚未执行语义版本校验。
`knowledge/concepts.yaml` 和 `teaching/steps.yaml` 已被校验与存储，但尚未在所有教学路径中
完整消费。

新增实验时：复制包结构，填写硬件与证据映射，编写规则和故障树，补齐教师审核知识和
四级提示，至少提供一个正常样例和一个故障样例，运行
`python -m app.cli.verify_experiment_packages`，再通过 API 导入和发布。

## 未来 RAG

RAG 不是 Experiment Package 的必需能力。知识规模扩大后，可以只对已审核、已发布的案例
建立可重建向量索引；规则、故障树、证据表、版本绑定和发布流程保持不变。向量召回只能
补充参考，不能成为硬件故障事实源。

## 信息可信化整改（2026-09-09）

当前工作区示例包版本为 2.0.1、状态 draft；没有修改数据库中已发布的 2.0.0 快照，也没有执行导入/发布。所有配置仍待硬件确认。

### 案例与候选

两包案例使用 `sourceType: test_data`、`facts.verification_status: unverified`、`isTestData: true`、`reviewStatus: draft`、`rootCauseStatus: unknown`；清除根因值、教师署名、确认时间，撤销 factsLocked/qualityCheckPassed。沿用现有枚举，不新增 test_data 或 unverified 审核状态。Schema 拒绝 sourceType=test_data 的案例冒充 approved/confirmed。包导入保守继承案例测试标记，调用方不能仅靠省略 is_test_data 把示例包变为正式包。

两个故障树改为 placeholder；同一异常症状对各原因等权支持，不再借同一日志重复加权优先认定某根因。它们仍提供待验证候选，不是真实教师诊断经验。

### 失败计数

DHT11 规则使用 `failure_count_in_window`，现保留阈值 5，含义是所选窗口内累计的指定组件失败事件数；阈值仍在 rules.yaml 可配置，待硬件校准。规则证据 details 同时记录累计数及 `consecutive_failure_count: null`。没有经过验证的逐次成功/失败完整序列，因此未实现或启用连续失败阈值，不以累计次数冒充连续失败。

`required_parameters.consecutive_failure_threshold: null` 是待确认占位，不是正在运行的规则。工作流 `failure_count/historical_failures` 仍是指导/反馈历史，不改名、不挪作设备采样计数。

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

hardware.yaml 新增可选 runtime_expectations：

- `verification_status`：当前 pending_hardware。
- `offline_after_seconds`：当前 90，沿用项目示例策略，不是硬件标准。
- `heartbeat_maximum_age_seconds`：当前 90，同为待验证监测时限，不等于真实发送周期。
- `required_observations`：按 component_id + metric 列出必需观测及可选单位/合法值。
- `maximum_age_seconds`：控制最新样本年龄及观察窗口内相邻样本最大间隔；当前全部 null，等待实际采样周期和容差确认。

DEVICE_OFFLINE 判断上报可达性；HEARTBEAT_STALE 独立判断心跳新鲜度；DATA_STALE 判断已配置时限下的必需数据缺失、过期或周期中断。不从这些异常推断断电、损坏或断线的唯一根因。心跳优先使用持久化心跳的服务端接收时间。

`DiagnosisContext.normal_assessment` 随 context_snapshot 保存并进入诊断核心输出。只有心跳/可达性、必需数据新鲜度与周期、数值有效性、所有配置的 expected_behaviors 和无异常规则命中均满足，才为 normal；违反条件为 abnormal；缺参数、缺证据或只有一组采样无法验证周期时为 unknown。周期至少要有两个不同采样时刻，校验所选窗口中的样本间隔；这是工程完整性判据，未校准为课堂验收。

normal 的 scope 固定为 reported_telemetry_only，并携带 pending_hardware，不代表器件精度、实际发光或整套硬件验收。当前示例读数周期、LED 响应窗口留空，故不会给出完整 normal 结论。

### 接入与校验

legacy 日志归一化现在支持 sensor_snapshot.component_id/interface_id；仍由已声明组件和规则参数匹配，未凭错误码猜组件。DHT11 的错误事件、temperature/humidity，LED 四类观测均与实际持久化名称对齐。对声明新 runtime_expectations 的包，新增 evidence.runtime_types 校验，阻止声明类型与静态映射输出类型不一致；旧包维持兼容。

包内 facts 样例仍只验证规则结构，零命中样例明确不声称正常。HTTP→持久化→context→Evidence UUID、显式正常、LED 语义隔离和累计计数的回归覆盖在 `backend/tests/test_experiment_trust.py`。这些都是自动化合成数据测试，不能当真实硬件案例。

## 项目真实性治理补充（工作区 2.0.2）

本轮在 2.0.1 整改基础上补齐逐项 `required_parameters.truth_status`，每项记录状态、项目来源定位与确认所需材料。区分 pending_hardware、pending_teacher、pending_course_confirmation；案例 facts 同步记录 teacher_status/student_case_status/course_status。它们是审核注记，现有引擎不据此自动生成或修改 GPIO、阈值、周期、教师经验或真实案例。

LED 旧 level 原始映射增加 `match.metric: null`，只处理没有显式新 metric 的旧报文；带 pin=2 的新命令/电气/光学观测不会再触发多映射冲突。GPIO_COMMAND 与 GPIO_ACTUAL_LEVEL 是语义类别，其值为 1 时分别对应上文的 HIGH 状态；都不等于 LED_PHYSICALLY_ON。

源码包版本更新为 2.0.2，未导入或发布；之前 2.0.1 的设计说明和验证记录保留为历史。负责人摘要、待确认清单和范围外已知问题集中维护于 [项目真实性看板](project-truth-status.md)。
