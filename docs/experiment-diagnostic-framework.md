# 可迁移实验诊断框架

## 1. 目标与边界

诊断系统分成稳定的通用内核与可插拔实验配置层。增加实验时，默认只新增或审核：

- Experiment Definition；
- 硬件、组件和接口描述；
- Expected Behavior；
- YAML 规则与故障树；
- Knowledge Scope；
- 明确标记的测试 Fixture。

不得因为实验名称、传感器型号或某个 GPIO 不同而修改核心规则执行器、证据评分、
`DiagnosisResult`、FastAPI 诊断流程或 LangGraph 编排。只有出现一种现有抽象确实无法表达的
新接口类别、原始协议或通用事实时，才评审扩展内核。

本阶段没有合并或修改独立的 `knowledge-ingestion-pipeline/`，没有新增完整 RAG，也没有重写
已存在的 LangGraph/LangChain 工作流。

## 2. 最终数据流

```text
实验专属原始数据                       Experiment Definition
       │                                      │
       ▼                                      ├─ Hardware / Component / Interface
Event / Observation Normalizer                ├─ Expected Behavior
       │                                      ├─ Rule / Fault Tree Source
       ├─ Observation / Event                  └─ Knowledge Scope
       └─ Unknown + 原始载荷                         │
                       └──────────┬───────────────┘
                                  ▼
                         DiagnosisContext
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
           Scoped Rules    Scoped Fault Trees   Evidence / Level 1–4
                 └────────────────┼────────────────┘
                                  ▼
                         DiagnosisResult
                                  │
                         Teacher Intervention
                                  │
                  Knowledge Scope ──► 受控检索边界
```

旧 PostgreSQL 日志、心跳和读数由兼容 Adapter 转成同一 Observation/Event，同时继续保存在
Context 中用于旧 API 与证据追溯。统一结构是核心的新输入边界，Normalizer 只改变表示，
不推断根因。

## 3. Experiment Definition

正式 Schema 位于 `backend/app/experiments/schemas.py`，加载器位于
`backend/app/experiments/loader.py`。定义必须通过严格 Pydantic 校验；额外字段、非法稳定 ID、
重复组件/接口/行为 ID、失效组件或接口引用都会显式失败。相同 `experiment.id + version` 不得
重复。若一个 ID 有多个版本，调用方必须指定版本，加载器不会静默选择。

定义包含：

- `experiment`：稳定 ID、展示名、版本；
- `hardware`：硬件家族、板卡型号、最小组件集合；
- `interfaces`：GPIO、I2C、SPI、UART、ADC 或 network；
- `required_parameters`：实验必需但不进入核心字段的参数；
- `expected_behaviors`：应出现的状态、范围或事件；
- `diagnostics`：允许加载的规则和故障树来源；
- `normalization`：原始字段到 Observation/Event 的映射；
- `knowledge_scope`：以后检索知识的结构化边界。

配置文件随内容计算 SHA-256。诊断记录持久化实验 ID、版本和定义哈希，历史诊断不会只依赖
易变的展示名。

## 4. 通用硬件与接口抽象

第一版只建立迁移所需的最小模型：

- Device：设备 ID、硬件家族、型号、固件版本和扩展元数据；
- Component：稳定 ID、类别、可选型号、是否必需和扩展元数据；
- Interface：稳定 ID、接口类型、所连接组件、引脚和参数；
- Observation：组件/接口上的指标、值、状态、时间、来源和原始载荷；
- Event：标准事件类型、组件/接口、状态、时间、来源和原始载荷；
- ExpectedBehavior：设备在线、组件存在、接口通信、指标范围、状态相等或事件出现；
- Evidence / Fault / TroubleshootingAction：分别由规则命中、故障树候选和排查历史承载。

具体 SHT31、LED 或某一 GPIO 只出现在实验配置，不进入诊断执行器分支。

## 5. DiagnosisContext

升级后的 Context 明确分开三类状态：

1. 输入事实：设备、组件、接口、Observation、Event、Expected Behavior，以及可追溯的旧日志、
   心跳、读数和 Unknown 原始数据；
2. 推理状态：`inference_state.rule_hits/evidence/suspected_faults`；
3. 教学状态：排查历史、当前提示 Level 和教师介入状态。

原字段均保留默认值，旧 Context 快照仍能反序列化。LangGraph 中真正需要累积的
`errors/node_trace/node_metrics` 继续使用 reducer，未把无限增长的硬件原始字段塞进图状态。

## 6. Normalizer

`backend/app/diagnosis/normalization.py` 提供：

- `mapping` Adapter：通过实验定义映射不同原始字典；
- Adapter Registry：确有新协议时可注册受测试的 Adapter；
- legacy Adapter：把现有 PostgreSQL 日志、心跳和读数投影到统一结构；
- Unknown 保留：无法匹配的数据进入 `unknown_raw_data`，同时生成 `type=unknown` Event，
  原始载荷不会丢失。

Normalizer 不做根因判断。例如 `wifi_connected=false` 只映射为
`communication_failure`；它不会断言是密码、信号或服务端故障。

## 7. Expected Behavior

Expected Behavior 是实验标准，不是复杂 DSL。当前支持：

- 设备应在指定窗口内在线；
- 必需组件应产生事实；
- 接口应能通信；
- 指标应处于范围内；
- 状态应等于期望值；
- 指定事件应出现。

比较器输出 `satisfied / violated / unknown` 和证据引用。规则通过
`expected_behavior_violation_count` 消费差异，因此增加实验行为不会向匹配器增加按实验命名的
条件分支。

## 8. Rule Scope 与冲突处理

规则文件可位于 `rules/common/`、`rules/interfaces/`、`rules/components/`、
`rules/experiments/`，也保留根目录旧规则兼容入口。每个文档声明：

- `source_id`：稳定来源；
- `version`：来源版本；
- `scope.kind`：common/interface/component/experiment；
- `scope.keys`：允许的接口、组件或实验 ID。

实验定义列出允许的 `rule_sources`。加载时同时检查来源存在且 Scope 与当前 Context 匹配；
缺失或越权来源会失败关闭。重复规则 ID 被拒绝，不做隐式覆盖。不同规则的执行顺序保持
`priority` 降序、规则 ID 升序。命中结果保存来源、来源版本、Scope 和原始证据。

无 Experiment Definition 的旧 API 只加载根目录兼容规则，避免新实验规则污染旧诊断。

## 9. Fault Tree Scope

故障树使用与规则相同的来源、版本、Scope 和失败关闭策略。核心评分算法、原因排序、连续失败
计数和 Level 1–4 升级没有按实验分叉。故障树来源与 Scope 保存到 Guidance 审计记录。

旧三棵占位树仍在根目录并由旧入口加载；新实验只加载定义中选择的相关树。

## 10. Knowledge Scope

Knowledge Scope 位于实验定义和 DiagnosisContext，并持久化到 DiagnosisResult，可描述：

- 实验 ID/版本（由诊断记录本身提供）；
- 硬件家族与板卡型号；
- 组件；
- 接口；
- 文档类型；
- 知识版本。

它是未来 RAG 的过滤契约，不代表当前已经完成正式知识接入。独立知识摄取项目继续保持独立。

## 11. 规则、故障树和数据库的存放选择

- Experiment Definition、规则、故障树：版本化 YAML，便于审阅、测试和随代码发布；
- 已有课堂实验模板和诊断制品：继续使用现有版本化数据库表，不重复建表；
- 每次诊断所用实验身份、定义哈希和 Knowledge Scope：保存在 `diagnosis_results`；
- 设备扩展事实与 Context 快照：继续使用 JSON，避免为未验证硬件建立大量表。

迁移 `20260818_0021` 只新增可空字段与索引，旧记录合法且无需回填虚构实验身份。

## 12. 如何增加一个新实验

1. 在 `backend/app/experiments/definitions/` 新建定义，分配稳定 ID 和明确版本。
2. 描述硬件家族、板卡、组件、接口及必要参数。
3. 定义最小 Expected Behavior。
4. 优先选择 `common` 或 `interfaces` 中已有规则来源。
5. 只有现有规则无法表达实验差异时，新增实验作用域 YAML 规则。
6. 优先选择可复用故障树；必要时新增组件级或实验级树。
7. 指定 Knowledge Scope，但不要伪造不存在的正式知识。
8. 添加明确标记的迁移 Fixture，覆盖正常、失败和 Unknown 数据。
9. 运行后端测试、Ruff、前端回归、Alembic 与 Compose 验证。

正常接入不得修改：

- `evaluate_rules` 和 `evaluate_fault_tree`；
- 证据评分与原因排序；
- `DiagnosisResult` 核心输出形状；
- FastAPI 诊断路由结构；
- LangGraph 节点图；
- 学生端或教师端诊断页面。

## 13. 当前迁移性 Fixture

三个 YAML 均为架构测试资料，不是真实课程或硬件结论：

- `gpio_led_output`：GPIO Observation 与状态期望，选择 GPIO/LED 实验规则和树；
- `sht31_i2c_temperature`：I2C timeout 映射为通信失败；
- `wifi_data_upload`：Wi-Fi 连接状态映射为网络通信事件。

I2C 与 Wi-Fi 复用 `interfaces.communication` 规则和故障树；GPIO 专属规则不会进入另两个
实验。三者都由相同诊断执行器输出统一 DiagnosisResult。
