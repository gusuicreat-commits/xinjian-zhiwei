# 芯鉴知微文档索引

按当前要做的事查文档。长期规则、模块契约、操作方法、当前状态和历史证据分别维护；同一规则只保留一处正文。

## 开始开发或修复

| 文档 | 保留的独立职责 |
| --- | --- |
| [项目简介](../README.md) | 产品用途、能力边界与第一次启动 |
| [开发入口](../AGENTS.md) | 阅读顺序、适用范围与规范来源 |
| [开发准则](development-guidelines.md) | 持续规则的唯一正文；重点入口：[模型内核](development-guidelines.md#model-core)、[业务规则](development-guidelines.md#business-rules)、[数据变更](development-guidelines.md#data-change)、[修复 Bug](development-guidelines.md#fix-bugs)、[规则与入口对应表](development-guidelines.md#rule-map) |

## 定位模块及契约

| 文档 | 回答的问题 |
| --- | --- |
| [系统架构](architecture.md) | 模块如何分工，数据怎样流动？ |
| [AI 诊断设计](ai-diagnosis-design.md) | 固定工作流、受约束推理、校验与降级如何执行？CoT 第一版已接入，真实模型效果尚未验收；[记忆生命周期方案](ai-diagnosis-design.md#memory-lifecycle-design)已接入三类投影、来源追踪与受控清理；完整删除仍受保留策略限制。 |
| [实验包设计](experiment-package-design.md) | 十类工件如何关联、校验、发布并固定为运行快照？ |
| [受控上下文建设方案](context-construction-plan.md) | 如何借鉴RAG思想，分阶段完善现有资料选择、完整打包和评测？含代码依据、验收场景及兼容边界；软件已实施，真实效果待验收。 |
| [API 设计](api-design.md) | 各接口怎样认证、授权、幂等和兼容？字段细节查当前 Schema/OpenAPI。 |
| [数据库设计](database-design.md) | 实体关联、事务和迁移边界在哪里？ |
| [设备协议](device-protocol.md) | 怎样上传批次，处理会话、时间、重试和冲突？ |

## 测试、演示与部署

| 文档 | 保留的独立职责 |
| --- | --- |
| [测试与评测](evaluation.md) | 本地/CI 命令、依赖、各层检查入口 |
| [评测要求对应表](evaluation-requirements.md) | 要求对应哪些检查和反例，以及 ClawEval 来源、覆盖缺口 |
| [测试报告约定](test-reporting.md) | 报告路径、执行状态、附件和退出码怎样解释 |
| [部署说明](deployment.md) | 配置、启动、迁移、Checkpoint、备份与恢复 |
| [演示手册](demo-runbook.md) | 合成账号、模拟设备和页面操作闭环 |
| [模拟器说明](../simulator/README.md) | 场景选择、发送、重试与重放 |
| [ESP32 固件说明](../firmware/esp32_dht11/README.md) | 候选接线、构建、配置、缓存与实物待验项目 |
| [硬件验证计划](hardware-validation-plan.md) | 实物对照试验与独立真值记录；不代表已实测 |
| [真人试用模板](usability-trial.md) | 学生任务、观察和误解记录；不代表已开展试用 |
| [离线审核包模板](../frontend/review-package/审核说明.md) | 构建和组装审核包；源码目录本身不是完整可运行包 |

## 确认当前能力和缺口

- [实现状态](implementation-status.md)：当前版本、代码能力、软件限制及最近执行证据；不累计逐轮修复日志。
- [真实性看板](project-truth-status.md)：硬件、教师、课程、真实模型和运行环境还缺什么证据、由谁确认。

## 查历史依据和来源

| 材料 | 为什么保留 |
| --- | --- |
| [原始模型规范](references/model-spec-2026-09-17.md) | 用户指定规范的原文快照；持续适用边界见开发准则，不直接照搬历史示例 |
| [历史资料索引](archive/README.md) | 独有失败基线、知识来源审计、实施记录与视觉审查 |
| [发行记录](../CHANGELOG.md) | 发行时点的变化，不代表现行架构路线 |
| [前端复杂度评估](../output/reports/frontend-complexity-review-2026-09-21.md) | 方案 B 的选择依据；当前页面以代码和当次页面验证为准 |
| `output/audits/`、`docs/reports/` | 分次执行证据与附件；部分只在本机或 CI 存在，缺附件时不能声称已复验 |
| `交付文件/` 中日期命名的文件 | 历史交付原件；同名“ 2”目录的 HTML 有差异，不能按文件名判断重复 |

规范说明应该怎样做，代码、Schema 和当次执行记录用于核对实现事实；实现有偏差应明确记录，不能降低规则迁就实现。旧报告、外部示例和交付快照不证明当前部署、硬件或教学效果。文档维护与冲突处理统一遵守[开发准则](development-guidelines.md)；新增内容先归入现有职责，只有独立用途才新建文档。
