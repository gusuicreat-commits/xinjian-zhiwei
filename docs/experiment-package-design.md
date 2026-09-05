# Experiment Package 与证据治理

最后更新：2026-09-05

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

当前完整包为 `dht11_temperature_humidity@2.0.0` 和
`gpio_led_output@2.0.0`。它们用于证明同一套加载、规则、故障树和证据链可以处理不同实验。

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
