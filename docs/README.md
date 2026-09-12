# 芯鉴知微文档索引

本目录保存能够指导开发或验收的核心文档，并保留明确标注的失败基线，以便核对后续修复。历史决策也可通过 Git 提交记录追溯。

## 负责人入口

- [项目真实性看板](project-truth-status.md)：当前已确认、待硬件、待教师和未整改问题，以及五问可读摘要。
- [完整流程问题整改](workflow-remediation.md)：本轮反馈归属、重试与恢复、候选证据关联，含接口/数据库兼容变化和最新验证记录。
- [实验知识审计](experiment-knowledge-audit.md)：带版本和日期的来源、事实清单与故障－证据矩阵。
- [硬件验证计划](hardware-validation-plan.md)：下一步真实试验与归档方式。

## 阅读顺序

1. [开发准则](development-guidelines.md)：后续开发必须遵守的边界、流程和完成标准。
2. [系统架构](architecture.md)：系统边界、模块关系和运行时主链。
3. [AI 诊断设计](ai-diagnosis-design.md)：证据驱动诊断、LangGraph 状态流转及 AI 约束。
4. [Experiment Package 设计](experiment-package-design.md)：实验包结构、发布和证据治理。
5. [实现状态](implementation-status.md)：当前真实能力、限制和待办事项。

## 接口与数据

- [API 设计](api-design.md)：接口分组、认证、幂等和兼容约定。精确请求/响应以运行时 OpenAPI 为准。
- [数据库设计](database-design.md)：持久化边界、主要实体和迁移规则。
- [设备协议](device-protocol.md)：设备上报协议、认证、时间和幂等语义。

## 交付与验收

- [部署说明](deployment.md)：开发、试运行和生产部署要求。
- [评测要求对应表](evaluation-requirements.md)：评测与整改要求、反例测试、证明范围与未覆盖项。
- [完整流程评测历史基线](workflow-evaluation-phase2.md)：保留第二阶段三个问题的原始失败证据，最新状态见整改报告。
- [测试与评测](evaluation.md)：自动化门禁、合成数据边界和真实验收要求。
- [演示手册](demo-runbook.md)：合成演示、页面闭环和安全重置。

## 文档权威性

当资料冲突时，按以下顺序处理：

1. 已执行的数据库迁移、当前代码和自动化测试；
2. `development-guidelines.md` 中明确的强制约束；
3. 本目录其他核心文档；
4. Git 历史中的旧文档、PDF 背景资料和阶段性讨论。

背景资料用于解释决策来源，不能覆盖已经落地的安全边界，也不能作为真实硬件参数、正式知识或生产配置的证据。
