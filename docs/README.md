# 芯鉴知微文档索引

先看当前用途和状态，再按任务查看契约。审查请记录分支与提交号；历史报告不代表当前代码，GitHub 也不包含本机尚未提交的修复。

## 常用入口

| 目的 | 文档 |
| --- | --- |
| 理解产品定位与开发背景 | [产品背景与需求（PRD）](product-background-prd.md)：利用设备内部运行证据辅助学生诊断，定义目标、需求与效果验收方向 |
| 了解软件 | [项目简介](../README.md) · [系统架构](architecture.md) |
| 确认已实现与未验收事项 | [实现状态](implementation-status.md) · [真实性看板](project-truth-status.md) |
| 开发和修复 | [开发入口](../AGENTS.md) · [开发准则](development-guidelines.md) |
| 理解反复缺陷与本轮扫描 | [AI辅助开发缺陷复盘](development-retrospective-20261002.md) · [全项目软件扫描方案](software-scan-plan-20261002.md)（已执行，修复进展见[应对方案](software-boundary-repair-plan-20261003.md)；依赖公告风险另列，[本机报告](../output/audits/software-boundary-scan-20261002/report.md)） |
| 运行和演示 | [部署说明](deployment.md) · [演示手册](demo-runbook.md) |
| 测试和解读结果 | [测试与评测](evaluation.md) · [测试报告约定](test-reporting.md) · [真实 API 全面测试方案](real-api-test-plan-20261003.md)（仅设计） |

## 按模块查阅

- AI 与资料：[AI诊断设计](ai-diagnosis-design.md)、[Kimi 2.6 接入与实测](kimi-api-integration.md)、[残余问题根因与修复方案](ai-residual-repair-plan-20261004.md)（[验收报告](../output/audits/ai-residual-repair-20261004/report.md)）、[实验包设计](experiment-package-design.md)、[受控上下文](context-construction-plan.md)、[资料包衔接](package-context-evolution-plan.md)。
- [默认容量与生成合同修复评估](../output/audits/ai-capacity-semantic-followup-20261004/report.md)：10000默认、受控生成、真实回归及教师验收交接。
- [受控查询复用与框架选型方案](pi-controlled-query-plan-20261007.md)（仅设计）与[GitHub复用评估](agent-reuse-selection-20261007.md)：优先现有LangGraph，PydanticAI备选，Pi按需求激活；含权限、预算、恢复和分阶段验收。
- [LangGraph受控查询详细执行方案](langgraph-query-execution-plan-20261007.md)（设计时方案）与[新任务交接文本](langgraph-query-handoff-20261007.md)：细化A/B0隔离实现、答复恢复、共同治理、公平对照与阶段门禁；[真实 Kimi 隔离评测及逐例摘要](controlled-query-evaluation-20261008.md)记录已执行结果。
- 接口与存储：[API设计](api-design.md)、[数据库设计](database-design.md)、[设备协议](device-protocol.md)。
- 实物准备：[DHT11内部实验指南](experiments/dht11-internal-lab.md)、[施工方案](experiments/dht11-hardware-execution-plan.md)、[到货执行清单](experiments/dht11-arrival-checklist.md)、[内部测试准备](experiments/internal-lab-preparation.md)、[固件说明](../firmware/esp32_dht11/README.md)。
- 验收补充：[评测要求](evaluation-requirements.md)、[硬件验证计划](hardware-validation-plan.md)、[真人试用模板](usability-trial.md)、[模拟器说明](../simulator/README.md)。
- 前端演示：使用[离线审核构建](../frontend/review-package/审核说明.md)；由当前源码生成，不维护独立四页HTML副本。

## 历史与证据

已实施的[共享校验修复](shared-validation-repair-plan.md)和[AI安全修复](agent-security-repair-plan.md)作为设计依据保留；实施状态及验收边界统一查[实现状态](implementation-status.md)。

[历史资料索引](archive/README.md)保存独有的决策与反例；[模型规范原文](references/model-spec-2026-09-17.md)保留规范来源，[发行记录](../CHANGELOG.md)记录历史变化。当前有效规则统一在开发准则中维护。

`output/audits/` 等自动报告通常只在本机或对应 CI 附件中，GitHub 链接缺失不代表测试通过，也不能根据缺失附件补造结果。旧HTML、日期交付包和旧现状报告已退出当前目录，可从Git历史查阅。需要交付时重新构建，标明提交号与日期，生成物不提交到源码仓库。
