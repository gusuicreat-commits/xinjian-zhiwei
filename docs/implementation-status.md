# 芯鉴知微当前实现状态

核对日期：2026-09-30。本文记录工作区的软件版本、能力、限制及执行证据；开发要求见[开发准则](development-guidelines.md)，外部事实与效果待验项见[真实性看板](project-truth-status.md)。代码存在、测试通过和已部署分别判断。

## 当前版本

| 对象 | 当前代码/内容版本 | 核对来源 |
| --- | --- | --- |
| 应用 | `1.0.0` | `VERSION`、应用配置与 `scripts/check_version.py` |
| 数据库迁移 Head | `20260930_0036` | `backend/migrations/versions`；不是运行库版本 |
| 诊断引擎兼容契约 | `2.2.0` | `experiment_packages/loader.py`；与应用版本分开 |
| DHT11 工作区资料包 | `dht11_temperature_humidity@2.0.11` | 包 metadata.yaml；测试草稿 |
| LED 工作区资料包 | `gpio_led_output@2.0.4` | 包 metadata.yaml；测试草稿 |
| ESP32 DHT11 固件 | `0.2.5` | 固件/LittleFS已构建，完整软件门禁通过；未实物验收 |

资料包哈希清单为 `scripts/package_versions.json`，版本门禁复用装载器算法；运行时另核验数据库固定快照。工作区草稿不等于已导入或发布。

## 已实现的软件能力

代码定位中服务和 AI 路径均相对 `backend/app/`；模块契约维护实现细节。

| 领域 | 当前行为 | 定位/契约 |
| --- | --- | --- |
| 身份与会话 | PostgreSQL共享登录失败/在途额度，成功不清除其他在途请求；正式学生按班级/任务/设备/会话授权；设备凭据只认证设备，演示保留受限兼容；教师可释放指定占用 | `services/data_scope.py`、`experiment_sessions.py`；[API](api-design.md) |
| 设备接入 | 四个遥测入口共享事务准入、额度和流式大小边界，等待后重验设备身份；批次幂等、序号冲突、时间质量、容量及会话归属校验 | `services/device_ingest.py`、`device_protocol.py`；[设备协议](device-protocol.md) |
| 诊断与问题生命周期 | 规则识别异常，故障树限定候选，实际落库证据关联问题；相关新证据改变对应计数/修订，共享判据判断恢复及提示进度 | `diagnosis`、`services/diagnosis_episode.py`；[架构](architecture.md) |
| 新数据检查 | 固定输入与请求身份；恢复原请求；新回执复用证据时读取问题当前处理状态，旧回执不改写，不额外调用模型 | `services/diagnosis_checks.py`；[重新检查规则](development-guidelines.md#recheck) |
| 学生反馈与教师处置 | 等待锁后、工作流恢复和长操作交付时重验当前权限；401/403不包装成503；合法历史回执仍可重放。409不换身份重试；反馈、工单和硬件恢复分开，私密备注按角色投影 | `services/student_feedback.py`、`diagnosis_workflow.py`、`interventions.py` |
| 教学资料与案例 | 新指导保存 concepts/steps 的明确关联快照；故障树提示决定动作。草稿审批/润色采用状态与版本约束，来源唯一、审批同事务；实验包版本化发布并绑定快照 | `experiment_packages/teaching.py`、`knowledge/case_drafting.py`；[包设计](experiment-package-design.md) |
| AI | 默认关闭；候选排序/解释/润色共享外发清洗、预算预留、缓存重验和调用审计，失败降级。`evidence-reasoning-v2.8` 保留分步证据核对并接入完整上下文准备，沿用原 Schema/图、开关和 thinking 设置；新增6项语义条目仍未审阅 | `ai/governance.py`、`context_sanitizer.py`、`reasoning.py`；[AI 设计](ai-diagnosis-design.md) |
| 记忆 | 事实（固定包配置）、经验（受审案例）、工作（当前任务投影）分开；来源版本与用途留痕，召回/恢复/交付重验，停用后阻断旧建议并支持教师影响复核；过期缓存按固定计划清理 | `services/memory.py`、`memory_governance.py`、`memory_restore.py`；[记忆设计](ai-diagnosis-design.md#memory-lifecycle-design) |
| 前端 | 学生和教师各三类任务视图；切页保留对象与待确认请求；教师旧请求隔离、分区错误提示、就绪统计按范围表达；内部代码中文投影，离线审核可演示 | `frontend/src` 的两端 Dashboard、`userLanguage.ts`；[界面规则](development-guidelines.md#ui) |
| 固件与运维 | 64位运行时钟；DHT11前次转换语义；配置持久存储后先保存单批、存储失败暂停、重试预算持久化、确认后仅重试清理。备份恢复核对同一数据库快照的内容与关系约束，模拟器提供实际场景清单 | [固件](../firmware/esp32_dht11/README.md)、[部署](deployment.md)、[模拟器](../simulator/README.md) |

## 软件限制

- 2026-09-30全项目审计7项缺陷已修复（含MIME相邻边界）：工单锁后授权、旧模板并发、学生明确拒绝恢复、共享登录准入、重复身份409、坏文件422和文档CSP。最终完整门禁退出0：后端929、模拟器32、前端单元136、浏览器18/9/1项，另验Swagger/ReDoc真实渲染。迁移Head0036仅在隔离库验证，业务部署及实物未执行；见[方案、自审与修复报告](../output/audits/software-fix-20260930/report.md)。

- 2026-09-29固件修复交付：DHT11包2.0.11、固件0.2.5，完整软件门禁退出0（后端906、模拟器32、前端单元130、浏览器17/9/1项），新增18个固件回归场景通过；两个镜像构建及LittleFS解包核对通过，操作手册v2已同步。详细源码身份、哈希、日志和实物未执行项见[修复报告](../output/audits/dht11-firmware-fix-20260929/report.md)。
- 2026-09-29施工设计只读核对中，隔离主机反例发现固件0.2.4在慢HTTP重试成功后可能过早再次采样；该问题已在固件0.2.5修复，并补充启动等待、同轮缓存解除后的priming及HTTPS配置保护；本轮软件验收结果见[修复报告](../output/audits/dht11-firmware-fix-20260929/report.md)。真实读数时效参数补齐顺序见[实物施工方案](experiments/dht11-hardware-execution-plan.md)。以下历史软件通过记录不包含这个新增反例。
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

## 资料包与上下文衔接实施

[资料包方案](package-context-evolution-plan.md)的P0–P3已落地：案例限制与有限条件、私有审核源清洗、格式1.1来源登记和1.0兼容、派生副本影响候选、两阶段调用预检、冻结调用身份的旧建议读取保护。数据库仍为0035，无运行库导入或发布。P4概念解释未实施。

最终本机完整门禁退出0：后端869项、前端130项、PostgreSQL流程25条、浏览器17＋8＋1条通过；详细软件检查、首轮失败与补测见[资料包实施报告](../output/audits/package-context-implementation/report.md)，不与以下历史结果累计。

## 执行证据

2026-09-28已实施[受控上下文建设方案](context-construction-plan.md)的P0–P3软件部分：完整材料准备、整单元预算选择、来源清单、版本化缓存/重放和独立评测。未增加向量库、公共端点或数据库迁移。当时结果见[上下文实施报告](../output/audits/context-implementation-latest/report.md)，其中区分完整门禁、反例、真实模型/硬件/教师待验收项；下述记忆报告是此前独立证据，不与本次数量相加。 当时完整门禁退出0：后端759项、工作流25条、前端130项、真实PostgreSQL浏览器8条等检查通过；末轮案例排序微调后139项定向回归通过，不能与759项相加。独立上下文11份回归、3份合成软件保留材料通过；P4真实效果仍未验收。

此前证据为[记忆实施验收报告](../output/audits/memory-implementation-latest/report.md)（2026-09-28）：后端732项通过、2项备份测试在全量运行中跳过；前端130项、真实 PostgreSQL 浏览器8条通过。原跳过的2项备份检查随后补测通过；最终页面定向复核1条通过，单独记录在报告中，不与全量结果重复计数。类型检查、构建、Lint、版本门禁及两个故意恢复缺陷的反例检查结果见报告。

上述记忆报告对应当时未提交工作区和源码指纹；其运行库未迁移，未部署、调用真实模型或重编译固件。此前上下文实现另行执行了固件构建，实际范围见新报告。上一次[数据处理修复报告](../output/audits/data-integrity-fix-latest/report.md)保留为独立历史证据，不能与本轮数量累加。

其他范围按独立报告查询：[CoT 实施与 Mock 检查](../output/audits/cot-implementation-latest/report.md)（真实语义与效果比较未执行）、[新旧入口修复](../output/audits/legacy-boundary-remediation-latest/report.md)（含模拟器、固件、迁移、备份与分阶段门禁；原 verify 首轮失败，后续定向重跑通过，不能描述为单次全绿）。更早证据见[历史索引](archive/README.md)，不在本页累计数量。自动报告可能只在本机/CI存在，缺附件不能当作已重新验证。

## DHT11资料与固件修复（2026-09-28）

DHT11工作区2.0.7、固件0.2.3修正负温度符号及所选手册格式/量程检查，统一3秒项目间隔，接入厂商来源与教学参考绑定。LED工作区内容不变。新反例及本次测试结果以[修复报告](../output/audits/package-repair-20260928/report.md)为准；旧诊断、原始读数和发布快照不回填，未导入或部署运行库。

## DHT11操作资料建设（2026-09-28）

DHT11工作区2.0.8、固件0.2.4：新增[内部实验指南](experiments/dht11-internal-lab.md)、六类排查卡和记录模板，扩充八个知识点与四个教学环节的实际绑定；初始化镜像显式使用LittleFS，固件仍不自动格式化。测试与未完成项见[本轮报告](../output/audits/dht11-content-20260928/report.md)。平台任务初始化入口缺口已列真实性看板；没有导入、发布或部署运行库。

## DHT11软件收尾与准备入口（2026-09-29）

工作区资料包2.0.9、固件0.2.4：移除启动时外部字体请求，补充内部测试实验plan/apply/status CLI、事务审计与重复执行恢复，学生仍通过原接口创建固定包会话。操作见[准备说明](experiments/internal-lab-preparation.md)，最终测试与受阻项见[本轮报告](../output/audits/dht11-readiness-20260929/report.md)。本轮仅在一次性测试环境演练，没有发布到业务库或完成实物验收。

2026-09-29后续：用户交接离线安装的tool-mklittlefs 1.203.210628后，复核压缩包与安装文件一致；使用已有PlatformIO Core 6.1.19完成项目固件与buildfs构建，均退出0。LittleFS镜像为1,441,792字节，匹配0x160000分区；按实际尺寸解包仅含与源码一致的README.txt。随后补跑完整本机软件门禁，退出0：后端906、模拟器32、流程25、前端单元130、模拟浏览器17、真实后端浏览器9、离线审阅1项通过。此前镜像构建阻塞已解除，见[离线工具验收](../output/audits/littlefs-offline-20260929/report.md)。上一轮中止记录仍保留；实物烧录、挂载与掉电验证仍未执行。

2026-09-29内部技术准备：按当前工作区再次定向构建固件和LittleFS镜像并核对分区/解包内容，T0软件就绪已具本机证据；T1—T4目标与[到货执行清单](experiments/dht11-arrival-checklist.md)已明确，均不冒充实物结果。构建尺寸、当次哈希及临时环境限制见[本轮记录](../output/audits/dht11-arrival-prep-20260929/report.md)。

## 共享校验修复（2026-09-30）

按[共享校验方案](shared-validation-repair-plan.md)修复本轮九项缺陷及同规则相邻入口：最终授权、当前建议资格、实验身份、来源清理、测试标记、命令恢复、权限失效页面、安全扫描和就绪探针统一对应校验。当前是未提交工作区，没有部署或改写业务历史。

本轮本地验收分阶段完成：后端1004、模拟器32、PostgreSQL流程25、前端单元153、模拟浏览器19、真实数据库浏览器10、离线页面1项通过；固件、静态检查和独立容器断库恢复通过。完整脚本在新浏览器测试的重复文案定位处退出1，修正为正文定位后，浏览器三组及前端静态检查补跑退出0；不宣称单次全绿。中途失败、原因、最终源码指纹和未验收范围见[修复效果报告](../output/audits/shared-validation-fix-20260930/report.md)，不与历史数量累计。真实Provider语义、实物、部署和课堂效果仍未验证。
