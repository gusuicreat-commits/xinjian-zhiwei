# 芯鉴知微当前实现状态

核对日期：2026-09-28。本文记录工作区的软件版本、能力、限制及执行证据；开发要求见[开发准则](development-guidelines.md)，外部事实与效果待验项见[真实性看板](project-truth-status.md)。代码存在、测试通过和已部署分别判断。

## 当前版本

| 对象 | 当前代码/内容版本 | 核对来源 |
| --- | --- | --- |
| 应用 | `1.0.0` | `VERSION`、应用配置与 `scripts/check_version.py` |
| 数据库迁移 Head | `20260927_0035` | `backend/migrations/versions`；不是运行库版本 |
| 诊断引擎兼容契约 | `2.1.0` | `experiment_packages/loader.py`；与应用版本分开 |
| DHT11 工作区资料包 | `dht11_temperature_humidity@2.0.5` | 包 metadata.yaml；测试草稿 |
| LED 工作区资料包 | `gpio_led_output@2.0.3` | 包 metadata.yaml；测试草稿 |
| ESP32 DHT11 固件 | `0.2.2` | platformio.ini、firmware_config.h、协议样例；已编译，未实物验收 |

资料包哈希清单为 `scripts/package_versions.json`，版本门禁复用装载器算法；运行时另核验数据库固定快照。工作区草稿不等于已导入或发布。

## 已实现的软件能力

代码定位中服务和 AI 路径均相对 `backend/app/`；模块契约维护实现细节。

| 领域 | 当前行为 | 定位/契约 |
| --- | --- | --- |
| 身份与会话 | 正式学生按班级/任务/设备/会话授权；设备凭据只认证设备，演示保留受限兼容；教师可释放指定占用 | `services/data_scope.py`、`experiment_sessions.py`；[API](api-design.md) |
| 设备接入 | 四个遥测入口共享事务准入、额度和流式大小边界，等待后重验设备身份；批次幂等、序号冲突、时间质量、容量及会话归属校验 | `services/device_ingest.py`、`device_protocol.py`；[设备协议](device-protocol.md) |
| 诊断与问题生命周期 | 规则识别异常，故障树限定候选，实际落库证据关联问题；相关新证据改变对应计数/修订，共享判据判断恢复及提示进度 | `diagnosis`、`services/diagnosis_episode.py`；[架构](architecture.md) |
| 新数据检查 | 固定输入与请求身份；恢复原请求；新回执复用证据时读取问题当前处理状态，旧回执不改写，不额外调用模型 | `services/diagnosis_checks.py`；[重新检查规则](development-guidelines.md#recheck) |
| 学生反馈与教师处置 | 等待锁后、工作流恢复和长操作交付时重验当前权限；401/403不包装成503；合法历史回执仍可重放。409不换身份重试；反馈、工单和硬件恢复分开，私密备注按角色投影 | `services/student_feedback.py`、`diagnosis_workflow.py`、`interventions.py` |
| 教学资料与案例 | 新指导保存 concepts/steps 的明确关联快照；故障树提示决定动作。草稿审批/润色采用状态与版本约束，来源唯一、审批同事务；实验包版本化发布并绑定快照 | `experiment_packages/teaching.py`、`knowledge/case_drafting.py`；[包设计](experiment-package-design.md) |
| AI | 默认关闭；候选排序/解释/润色共享外发清洗、预算预留、缓存重验和调用审计，失败降级。`evidence-reasoning-v2.7` 保留分步证据核对并接入完整上下文准备，沿用原 Schema/图、开关和 thinking 设置；新增6项语义条目仍未审阅 | `ai/governance.py`、`context_sanitizer.py`、`reasoning.py`；[AI 设计](ai-diagnosis-design.md) |
| 记忆 | 事实（固定包配置）、经验（受审案例）、工作（当前任务投影）分开；来源版本与用途留痕，召回/恢复/交付重验，停用后阻断旧建议并支持教师影响复核；过期缓存按固定计划清理 | `services/memory.py`、`memory_governance.py`、`memory_restore.py`；[记忆设计](ai-diagnosis-design.md#memory-lifecycle-design) |
| 前端 | 学生和教师各三类任务视图；切页保留对象与待确认请求；教师旧请求隔离、分区错误提示、就绪统计按范围表达；内部代码中文投影，离线审核可演示 | `frontend/src` 的两端 Dashboard、`userLanguage.ts`；[界面规则](development-guidelines.md#ui) |
| 固件与运维 | 64位运行时钟；DHT11前次转换语义；配置持久存储后先保存单批、存储失败暂停、重试预算持久化、确认后仅重试清理。备份恢复核对同一数据库快照的内容与关系约束，模拟器提供实际场景清单 | [固件](../firmware/esp32_dht11/README.md)、[部署](deployment.md)、[模拟器](../simulator/README.md) |

## 软件限制

- 旧逐条遥测没有请求身份，不保证重试不重复；批次回执有幂等语义。
- “仍未解决”继续原证据；重新检查只分析已上传数据，不采样或控制硬件。处理结束、无异常、满足恢复判据和课程完成不是同一状态。
- 固件单批缓存满时暂停采样，不能保证断网期间连续记录。
- AI 金额是估算预检，存在待核对费用，不能声称精确费用硬上限；结构/引用校验不证明自由文本语义或电气安全。
- concepts/steps 是教学参考，不扩充动作或进入 Provider 输入；旧指导不回填。独立 hints 工件不覆盖所有运行提示。
- 已发布包不可变主要由服务层保证；`state_revision` 不是锁，业务库与 Checkpoint 不是跨存储原子事务。生产恢复须配置持久化 Checkpoint。
- 历史字段/表仍保留；主链没有 RAG、Embedding 或自由规划 Agent。pgvector 镜像仅兼容历史迁移。
- DHT11/LED 仍为测试草稿；真实 Provider、硬件、教师材料、课堂效果、远端 CI 和运行环境的验收缺口集中见[真实性看板](project-truth-status.md)。

## 记忆实施边界

[三类记忆与生命周期设计](ai-diagnosis-design.md#memory-lifecycle-design)已统一并实施。新增来源使用、停用事件、影响复核和清理计划四张表；教师端可查看停用来源的关联诊断、当时依据并保存复核，管理员可预览和执行过期解释缓存清理。来源撤回或版本改变后，历史保留，但不能继续作为当前建议交付。

事实记忆目前只投影已有固定配置，不提供独立的实测事实编辑器；经验来自受审资料，工作记忆不自动晋升。没有新增向量库、自由规划 Agent 或额外模型调用。遗忘仅实际清理过期或明确关联停用来源的解释缓存；证据、诊断、Checkpoint、备份和外部副本因保留策略未定而明确阻止删除。停用登记可导出并在隔离恢复库重放，尚无自动调度或生产恢复验收。

## 执行证据

2026-09-28已实施[受控上下文建设方案](context-construction-plan.md)的P0–P3软件部分：完整材料准备、整单元预算选择、来源清单、版本化缓存/重放和独立评测。未增加向量库、公共端点或数据库迁移。最新结果见[上下文实施报告](../output/audits/context-implementation-latest/report.md)，其中区分完整门禁、反例、真实模型/硬件/教师待验收项；下述记忆报告是此前独立证据，不与本次数量相加。 本次完整门禁退出0：后端759项、工作流25条、前端130项、真实PostgreSQL浏览器8条等检查通过；末轮案例排序微调后139项定向回归通过，不能与759项相加。独立上下文11份回归、3份合成软件保留材料通过；P4真实效果仍未验收。

此前证据为[记忆实施验收报告](../output/audits/memory-implementation-latest/report.md)（2026-09-28）：后端732项通过、2项备份测试在全量运行中跳过；前端130项、真实 PostgreSQL 浏览器8条通过。原跳过的2项备份检查随后补测通过；最终页面定向复核1条通过，单独记录在报告中，不与全量结果重复计数。类型检查、构建、Lint、版本门禁及两个故意恢复缺陷的反例检查结果见报告。

上述记忆报告对应当时未提交工作区和源码指纹；其运行库未迁移，未部署、调用真实模型或重编译固件。本次上下文实现另行执行了固件构建，实际范围见新报告。上一次[数据处理修复报告](../output/audits/data-integrity-fix-latest/report.md)保留为独立历史证据，不能与本轮数量累加。

其他范围按独立报告查询：[CoT 实施与 Mock 检查](../output/audits/cot-implementation-latest/report.md)（真实语义与效果比较未执行）、[新旧入口修复](../output/audits/legacy-boundary-remediation-latest/report.md)（含模拟器、固件、迁移、备份与分阶段门禁；原 verify 首轮失败，后续定向重跑通过，不能描述为单次全绿）。更早证据见[历史索引](archive/README.md)，不在本页累计数量。自动报告可能只在本机/CI存在，缺附件不能当作已重新验证。
