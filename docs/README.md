# 芯鉴知微文档导航

开发先读[AGENTS](../AGENTS.md)与[开发检查清单](development-guidelines.md#rule-map)，确认能力看状态，改模块看契约。本文只导航，历史方案不再作为执行入口。

| 用途 | 当前文档 |
| --- | --- |
| 产品与现状 | [产品背景/PRD](product-background-prd.md) · [架构](architecture.md) · [实现状态](implementation-status.md) · [真实性看板](project-truth-status.md) |
| 诊断与资料 | [AI诊断设计](ai-diagnosis-design.md) · [实验包设计](experiment-package-design.md) · [当前查询来源合同](query-source-contract-plan-20261009.md) |
| 接口与存储 | [API/客户端合同](api-design.md) · [数据库](database-design.md) · [设备协议](device-protocol.md) |
| 开发与评测 | [检查清单](development-guidelines.md) · [缺陷复盘](development-retrospective-20261002.md) · [测试命令](evaluation.md) · [要求/反例/待验材料](evaluation-requirements.md) · [报告约定](test-reporting.md) |
| 真实模型证据 | [Kimi接入与实测](kimi-api-integration.md) · [已结束受控查询评测摘要](controlled-query-evaluation-20261008.md) |
| 运行与使用 | [部署](deployment.md) · [演示](demo-runbook.md) · [真人试用](usability-trial.md) |
| 实物验收 | [硬件验证计划](hardware-validation-plan.md) · [DHT11内部指南](experiments/dht11-internal-lab.md) · [施工计划](experiments/dht11-hardware-execution-plan.md) · [到货清单](experiments/dht11-arrival-checklist.md) · [测试环境准备](experiments/internal-lab-preparation.md) |
| 来源与历史找回 | [用户模型规范原文](references/model-spec-2026-09-17.md) · [上下文参考原文](references/context-systems-article-2026-09-28.md) · [删除索引](archive/README.md) |

[上下文旧链接入口](context-construction-plan.md)仅兼容只读原文快照，不维护方案。实物施工/验证计划仍有待执行事项；P4概念外发仍未实施，合同归实验包设计。

`output/audits/` 是执行附件，通常只在本机或CI存在；缺附件不算通过。历史文件按删除索引从Git找回，历史测试不证明当前源码、部署、模型语义、硬件或课堂验收。
