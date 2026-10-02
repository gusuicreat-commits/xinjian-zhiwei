# 芯鉴知微文档索引

先看当前用途和状态，再按任务查看契约。审查请记录分支与提交号；历史报告不代表当前代码，GitHub 也不包含本机尚未提交的修复。

## 常用入口

| 目的 | 文档 |
| --- | --- |
| 了解软件 | [项目简介](../README.md) · [系统架构](architecture.md) |
| 确认已实现与未验收事项 | [实现状态](implementation-status.md) · [真实性看板](project-truth-status.md) |
| 开发和修复 | [开发入口](../AGENTS.md) · [开发准则](development-guidelines.md) |
| 运行和演示 | [部署说明](deployment.md) · [演示手册](demo-runbook.md) |
| 测试和解读结果 | [测试与评测](evaluation.md) · [测试报告约定](test-reporting.md) |

## 按模块查阅

- AI 与资料：[AI诊断设计](ai-diagnosis-design.md)、[实验包设计](experiment-package-design.md)、[受控上下文](context-construction-plan.md)、[资料包衔接](package-context-evolution-plan.md)。
- 接口与存储：[API设计](api-design.md)、[数据库设计](database-design.md)、[设备协议](device-protocol.md)。
- 实物准备：[DHT11内部实验指南](experiments/dht11-internal-lab.md)、[施工方案](experiments/dht11-hardware-execution-plan.md)、[到货执行清单](experiments/dht11-arrival-checklist.md)、[内部测试准备](experiments/internal-lab-preparation.md)、[固件说明](../firmware/esp32_dht11/README.md)。
- 验收补充：[评测要求](evaluation-requirements.md)、[硬件验证计划](hardware-validation-plan.md)、[真人试用模板](usability-trial.md)、[模拟器说明](../simulator/README.md)。
- 前端演示：使用[离线审核构建](../frontend/review-package/审核说明.md)；由当前源码生成，不维护独立四页HTML副本。

## 历史与证据

已实施的[共享校验修复](shared-validation-repair-plan.md)和[AI安全修复](agent-security-repair-plan.md)作为设计依据保留；实施状态及验收边界统一查[实现状态](implementation-status.md)。

[历史资料索引](archive/README.md)保存独有的决策与反例；[模型规范原文](references/model-spec-2026-09-17.md)保留规范来源，[发行记录](../CHANGELOG.md)记录历史变化。当前有效规则统一在开发准则中维护。

`output/audits/` 等自动报告通常只在本机或对应 CI 附件中，GitHub 链接缺失不代表测试通过，也不能根据缺失附件补造结果。旧HTML、日期交付包和旧现状报告已退出当前目录，可从Git历史查阅。需要交付时重新构建，标明提交号与日期，生成物不提交到源码仓库。
