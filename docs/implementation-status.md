# 芯鉴知微当前实现状态

核对日期：2026-09-27。本文描述当前工作区的软件能力与缺口；强制约束见[开发准则](development-guidelines.md)，实物与教学待确认项见[真实性看板](project-truth-status.md)。代码已经存在、测试曾经通过、已经部署是三件不同的事。

## 当前版本与证据

| 对象 | 当前代码/内容版本 | 核对来源 |
| --- | --- | --- |
| 应用 | `1.0.0` | 根 `VERSION` 与应用配置；`scripts/check_version.py` |
| 数据库迁移 Head | `20260927_0034` | migrations/versions 中的 revision/down_revision；不是运行库版本 |
| 诊断引擎兼容契约 | `2.1.0` | experiment_packages/loader.py；与应用发行版本分开 |
| DHT11 工作区资料包 | `dht11_temperature_humidity@2.0.5` | metadata.yaml；测试草稿 |
| LED 工作区资料包 | `gpio_led_output@2.0.3` | metadata.yaml；测试草稿 |
| ESP32 DHT11 固件 | `0.2.2` | platformio.ini、firmware_config.h、协议样例；已编译，未实物验收 |

版本号不是硬件真实性或教学有效性的证明。资料包内容哈希清单维护于 `scripts/package_versions.json`，由版本门禁复用装载器的哈希算法核对；运行时服务另外核验固定数据库快照。工作区草稿没有因文档整理被导入或发布。

## 已实现的软件能力

| 领域 | 当前行为 | 主要定位/验收入口 |
| --- | --- | --- |
| 身份与实验会话 | 正式学生账号准入，按班级/任务/设备/会话授权；设备凭据只认证设备，测试演示保留受限兼容；教师可管理释放指定占用 | services/data_scope.py、experiment_sessions.py；business_identity、session_release 测试 |
| 设备接入 | 批次幂等、序号冲突、时间质量、整数容量；同设备事务内准入与限额、等待后重验设备身份；原始记录保留会话归属 | services/device_ingest.py、device_protocol.py；[设备协议](device-protocol.md) |
| 诊断与多问题 | 确定性规则判断异常，故障树限定候选，真实落库证据按问题范围关联；相关新证据才改变对应问题计数/修订 | diagnosis、diagnosis_episode；[架构](architecture.md) |
| 新数据检查 | 显式检查命令保存固定输入及请求身份，恢复原请求；与继续旧指导分开，刷新读取不触发新诊断 | services/diagnosis_checks.py；diagnosis_checks/PostgreSQL/浏览器测试 |
| 学生反馈与教师处置 | 重试保持原请求，409不自动换身份；反馈、工单与硬件恢复分别记录，私密备注按角色投影 | student_feedback、interventions；反馈可靠性及真实PG联调 |
| 教学资料 | 新指导按包版本、树/原因/组件/等级保存concepts与steps参考快照；故障树提示控制允许动作；旧指导不回填 | experiment_packages/teaching.py、teaching_materials.py、TeachingReferencePanel |
| 案例与实验包 | 草稿审核/润色有状态和版本并发约束；来源唯一、审批事务；版本化包校验、发布/撤回与固定快照 | case_drafting、experiment_packages；[包设计](experiment-package-design.md) |
| AI | 默认关闭；有限候选排序/解释/表达润色；外发清洗、预算预留、缓存重验、实际调用审计与确定性降级 | ai/governance.py、context_sanitizer.py；[AI设计](ai-diagnosis-design.md) |
| 前端 | 学生当前实验/数据记录/实验参考，教师课堂处置/课堂概览/资料审核；对象与待确认请求跨切页保留，内部代码有中文投影 | StudentDashboardView、TeacherDashboardView、userLanguage.ts |
| 固件 | DHT11读取与前次转换语义；已配置时离线先保留单批，存储失败暂停，重试预算持久化，确认后仅重试清理 | [固件说明](../firmware/esp32_dht11/README.md)；ESP32编译与主机故障测试 |

## 已知限制和未完成事项

- 完整资料包只有DHT11和LED测试草稿；故障树候选和课程动作仍需硬件与教师确认。示例配置不等于实测结论。
- 四个遥测写入入口现共享设备准入、限额与流式大小边界。批次仍有回执幂等；旧逐条接口没有请求身份，不能承诺重试不产生重复记录。
- “仍未解决”继续原证据，不自动采样；“重新检查”分析服务器已收到的数据，不控制硬件。故障已关闭、未检测到异常、硬件恢复和课程完成分别判断。
- 单批离线缓存满时暂停采样，不能保证断网期间连续记录。真实闪存、掉电、Wi-Fi/TLS、实际回执与传感器精度仍待实物验证。
- AI预算金额为估算预检，未知费用需核对；不能声称精确费用硬上限。严格结构/引用校验也不是完整语义或电气安全证明。
- concepts/steps作为学生教学参考，不自动扩大动作白名单或进入Provider输入；独立hints工件不能被描述为覆盖所有运行提示。
- 已发布包不可变主要由服务层保证；`state_revision`不是并发锁，业务表与Checkpoint也不是跨存储原子事务。生产恢复须使用明确配置的持久化Checkpoint。
- 历史兼容表/字段仍保留；当前主链没有RAG、Embedding或自由规划Agent。pgvector镜像用于兼容历史迁移，不是已启用向量检索。
- 目标运行库版本、生产配置、远端CI、真实Provider、教师材料及真人课堂效果，本次软件修复没有验收。

## 新旧入口修复（2026-09-27）

本轮实现教师请求隔离与分区错误、共享恢复证据及问题提示进度、旧遥测准入、就绪统计语义、离线演示闭环、64位固件时钟、快照备份核验和模拟器清单。自动化证据统一记录于 `output/audits/legacy-boundary-remediation-latest/`，以最终report.md列出的分阶段日志为准；没有推送、部署或升级运行库。此次确定性升级节点的改动只处理问题计数，未改AI提示、Provider、CoT或外发策略。

## 最近一次完整软件门禁记录

2026-09-27新旧入口修复的本地验收按阶段完成：后端670项全量通过，最终计数边界另做35项定向复测（含1项新增）；模拟器32、前端123、页面浏览器17、真实PG浏览器联调6、离线审核浏览器1、PG工作流25。ESP32编译、10组主机测试、隔离迁移和备份恢复通过。

`verify.sh`首轮在联调测试的旧迁移号断言处退出1；修正为0034后单独重跑全部6条联调及离线审核，均退出0。不能将原始verify日志描述为单次退出0。源码与各阶段证据见[本轮报告](../output/audits/legacy-boundary-remediation-latest/report.md)。七项修复的旧验收保留在[此前报告](../output/audits/software-remediation-latest/report.md)，不与本轮数量相加。

更早的日期、包哈希、失败及通过结果见[历史实现日志](archive/implementation-history-through-2026-09-27.md)与[历史资料索引](archive/README.md)。自动报告可能只在本机或CI附件存在；缺附件时不能凭文档数量声称重新通过。
