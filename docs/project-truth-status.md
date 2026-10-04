# 芯鉴知微项目真实性看板

核对日期：2026-10-04。范围：DHT11 工作区 `2.0.11` 草稿、LED 工作区 `2.0.4` 草稿；未确认它们已导入或发布到运行库。本页集中记录实物、教学、真实模型与运行环境还缺什么证据。软件版本、功能和最近测试数量统一见[实现状态](implementation-status.md)。

本次增量：[默认容量与生成合同修复](../output/audits/ai-capacity-semantic-followup-20261004/report.md)将默认与本机输入配置统一为10000，并以v2.14限制新模型自由理由/摘要/需求；已知合成回归12/12通过，配置差异组6/6保留候选方向，证据不足组6/6保留unknown。前轮4000容量失败记录保留，显式低预算仍受保护。独立教师与课堂验收已有空模板，结论仍未填写；没有完整类型化实读配置生产方，正式资料、P4、硬件和课堂仍需真实材料。AI仍关闭、未部署，Loop仍未接入产品。

## 当前结论

软件已有诊断、反馈、教师处置、版本化资料包、三类记忆的生命周期管理，以及受控上下文的完整打包/来源审计；最新软件验证见实现状态。**目前仍不能据此确认实物故障、完整 AI 因果支持或课堂效果。** 2026-10-03已完成一轮Kimi真实合成API测试，发现排序合同、自由文字及等待体验问题；本机业务AI仍关闭，未部署。当前修复与验收证据见实现状态；真实模型已连通不等于整体质量、实物或课堂通过。

状态含义：`verified` 只说明该项限定事实有依据；`pending_hardware` 等待实物确认；`pending_teacher` 等待教师确认（课程判据用 `pending_course_confirmation`）；`issue` 表示已确认且仍存在的缺口。没有依据时确认人、时间和根因保持空或 unknown；来源声明、文件哈希和 Evidence UUID 本身不认证硬件事实。

## 首轮硬件选型（用户已确定）

2026-09-28，用户确认首轮采用以下组合，作为采购及后续联调基线。后续型号变更须明确记录理由、对应资料和软件适配影响，不再自行更换候选。

| 项目 | 已确定的选型或配置 |
| --- | --- |
| 开发板 | Espressif ESP32-DevKitC V4，ESP32-WROOM-32E 模组 |
| 温湿度传感器 | Aosong DHT11，四针裸器件；解码依据为已保存的 V1.3_20170331 手册 |
| 接线设计 | 3.3V供电、共地、DATA→GPIO4，DATA与3.3V间外接4.7kΩ上拉，NC不接 |
| 请求周期 | 项目最小请求间隔与配置周期均为3秒 |

当前状态为**用户报告硬件条件已具备，实物身份、接线与功能待核验**（2026-09-29本轮更新）。用户允许沿用上述选型安排，常见工具已具备；实际型号/批次和烧录、平台电脑在开工时登记。执行顺序见[首轮实物施工方案](experiments/dht11-hardware-execution-plan.md)。已登记内部指南v3中的“尚未采购”是其编写时状态；当前可用条件以本页为准。包内`pending_hardware`及“项目设计候选”仍表示实物适用性未核验，不表示硬件、教师或课程验收已经完成。

## 硬件待确认

D 包为 [DHT11 包](../backend/experiment_packages/dht11_temperature_humidity/)，L 包为 [LED 包](../backend/experiment_packages/gpio_led_output/)；以下均为 `pending_hardware`。

| 事项 | 已有配置/已知范围 | 缺什么、由谁确认 |
| --- | --- | --- |
| DHT11 已确定接线设计（待实测） | ESP32-DevKitC V4/WROOM-32E、四针裸 DHT11、DATA→GPIO4、3.3V、4.7kΩ上拉；见 D 包 hardware.yaml、[固件说明](../firmware/esp32_dht11/README.md)及 Aosong 原始说明书 | 硬件负责人核对实物引脚与供电，做连续读取和断线对照 |
| 失败阈值 | 窗口累计阈值5是可配置示例，连续失败阈值未知；见 D 包 rules.yaml / truth_status.failure_threshold | 实测成功/失败序列，教师确认可接受误报 |
| 真实故障日志与可区分性 | `DHT11_READ_FAILED→sensor.read_failed` 是当前契约；断线、错GPIO、未供电与器件异常可能同表现，placeholder故障树不足以确认唯一根因 | 固件/硬件负责人保存逐次日志、版本与独立测量，按[历史审计矩阵](archive/experiment-knowledge-audit.md)做单因素对照 |
| 心跳、采样与超时 | 固件项目请求间隔与采样周期均为3秒，厂商要求严格大于2秒；平台90秒是监测时限，不是实测周期。见 D 包和 firmware_config.h | 测量周期、延迟、断网恢复，教师确认课堂容差 |
| LED GPIO、有效电平与回路 | GPIO2、active_level=1是示例，限流和回流未确认；见 L 包 hardware.yaml / truth_status.final_gpio | 核对板载/外接、器件型号、原理图和实物 |
| LED `level` 来源 | 未知是真实固件的变量、寄存器还是引脚采样；见 truth_status.level_source | 固件负责人提供源码、构建版本和测量位置 |
| LED 发光与响应窗口 | 没有已验证的独立光学输入；电流或HIGH命令不等于发光，比较窗口也待确认；见 truth_status.physical_light | 人工/光学观测与命令时刻关联，确认响应窗口 |
| 固件实物可靠性 | 历史编译和主机故障模拟已有记录；固件0.2.5已修复慢重试后的采样间隔、启动等待和HTTPS配置保护，软件证据见实现状态；单批缓存满暂停采样 | 按[施工方案S0](experiments/dht11-hardware-execution-plan.md#3-s0先完成软件开工准备)核对本次交付及现场环境，再核验真实闪存、掉电、Wi-Fi/TLS、存储失败及回执 |
| 自动恢复所需读数时效 | 当前温湿度maximum_age_seconds仍为null，正常评估保持unknown；无可信设备时间也不能证明修复后的新证据 | 按[施工方案S3](experiments/dht11-hardware-execution-plan.md#6-s3先测量再补全自动恢复所需参数)先导测量后制定内部参数，追加包并用独立数据验收，保留教师课程判据待确认 |

## 教学待确认

| 事项 | 当前材料 | 完成条件 |
| --- | --- | --- |
| 教师经验（pending_teacher） | 两包 teacherNotes 为空，未取得本人可追溯材料；见 cases.yaml / facts.teacher_status | 教师提供来源、适用条件与审核记录 |
| 学生案例（pending_teacher） | 目前均为合成样例；见 facts.student_case_status | 保存真实课堂原始证据、操作和修复后采样，关联 Evidence 并经教师审核 |
| 验收标准（pending_course_confirmation） | 持续读数、亮灭合格条件、误差和观察时长待确认；见 truth_status.teaching_acceptance | 课程负责人提供指导书版本、页码和判据 |
| 排查动作与升级（pending_teacher） | 故障树仍为 placeholder，提示是待审核建议；见 teaching_actions_and_escalation | 教师确认操作权限、测量方式与介入时机 |
| 真人可用性（pending_teacher） | 自动化页面验证不是学生学习或使用效果证据 | 使用[真人试用模板](usability-trial.md)记录任务完成、误解与求助点，修订后复核 |

## 软件已经表达的事实边界

以下是已核对的软件契约，不能升格为硬件或教师验证；实现和回归入口见相应模块文档。

| 主题 | 当前限定结论与定位 |
| --- | --- |
| 证据、异常、根因 | 读取失败是报告，窗口累计达阈值是规则异常，接线/配置/器件异常仍为候选；证据不足保留 unknown。[AI 设计](ai-diagnosis-design.md)说明约束。 |
| 计数 | `failure_count_in_window` 是累计；`consecutive_failure_count=null`，不推导连续失败，也不混入学生排查次数。定位：matcher.py、test_experiment_trust.py。 |
| LED 三类观测 | 命令、电气电平和实际发光分别表示；旧level不自动升级。同一命令按目标比较，缺关联/窗口为unknown；显式metric不再重复匹配旧level。定位：normalization.py、expected_behavior.py、L包映射及回归。 |
| 正常与恢复 | 正常需心跳、周期、有效字段、预期行为和无异常同时满足；缺参数为unknown。基础离线/过期规则不推断断电或损坏；处理结束与硬件恢复分开。定位：runtime_health.py、base_health_rules.yaml及[重新检查规则](development-guidelines.md#recheck)。 |
| 知识与证据来源 | 测试案例保留test_data、unverified、draft/unknown，不带伪教师署名/时间、不进入已审核匹配；Evidence类型经校验，UUID对应实际测试库记录，真实设备来源仍待验证。定位：两包cases.yaml、KnowledgeCase、package loader、诊断及回归。 |
| 包兼容与教学参考 | engine范围在导入、发布和运行时检查；concepts/steps只对明确关联的新指导保存展示，首次/反馈/AI降级复用快照，旧指导不补造关联。软件接通不代表模型已用参考或教师已认可。见[包设计](experiment-package-design.md)。 |

## 其他未完成验收

| 范围 | 已有内容与缺口 | 所需证据 |
| --- | --- | --- |
| AI语义、CoT效果与成本 | 前轮v2.13对照和本轮v2.14已知合成回归已有开发方逐项审阅；本组候选利用不证明一般准确率、CoT增益或物理根因，费用估算与账单分开。当前调用数与成本见本轮报告 | 按[评测对应表](evaluation-requirements.md)补教师独立保留集、教学范围和因果支持审阅；核实际账单与正式材料容量。结构正确不代表语义正确。 |
| 记忆真实性与保留策略 | 来源、审核、版本与停用检查已实施；配置事实不代表实物核验，经验不代表当前根因，工作上下文不自动成为长期知识。证据、Checkpoint、备份及外部副本尚无获定保留策略 | 确认各类数据保留期限与删除范围；在选定恢复环境验证最新可信停用登记。缓存清理不能证明所有副本已删除。 |
| 上下文真实效果 | 软件已有整单元选择、来源清单与独立合成评测；真实保留集和人工语义审阅尚未完成 | 按[方案P4材料清单](context-construction-plan.md#p4-已整理的材料清单)补齐两实验来源与实际模型输出；不以合成回归或完整代码门禁推断效果提升 |
| 运行环境与CI | 本地隔离库检查不等于已部署、运行库已迁移或远端CI通过；没有当前生产容量结论 | 对选定环境核对数据库、持久化Checkpoint、备份恢复、容量与CI实际执行记录；参见[部署说明](deployment.md) |

只有出现新证据才更新对应状态，记录来源版本、范围和确认依据。`truth_status` 是审阅注记，不参与阈值计算；参数来自 runtime_expectations、rules 和 expected_behaviors。硬件确认与教师确认互不替代；已修复项移出当前缺口，保留历史失败和验收报告，维护方式遵守[开发准则](development-guidelines.md)。

2026-09-28资料包衔接P0–P3补充：来源登记目前主要为项目源码/配置定位，缺少对应的厂商附件、教师材料及实物记录；默认预检显示unverifiable。有限条件匹配不认证真实接线、全部自由文本前提或恢复结果。样包仍为测试草稿，P4概念外发未实施；未导入运行库、部署或完成真实Provider验收。

2026-09-28资料包修复补充：DHT11 2.0.7已关联本地留存的Aosong V1.3和DevKitC指南、锁定依赖与固件0.2.3源码；对应声明按章节定位，实物、教师、课程材料分别保持pending。来源身份检查结果见[本轮报告](../output/audits/package-repair-20260928/report.md)。LED材料仍为旧项目基线来源；默认未提供来源快照的预检仍显示unverifiable，不将其改成审核通过。

2026-09-28操作资料补充：内部指南覆盖离线准备、本地采集、平台前提、六类排查及记录模板，见[指南](experiments/dht11-internal-lab.md)。首次LittleFS镜像构建已提供明确配置，实际烧录/挂载仍待实物。2026-09-29已补内部测试初始化CLI，见[准备说明](experiments/internal-lab-preparation.md)；它不自动审批包、不创建活动会话。seed_demo仍是旧演示入口。实际验收与剩余环境阻塞见[本轮报告](../output/audits/dht11-readiness-20260929/report.md)。

2026-09-29后续：LittleFS工具已由用户离线取得并安装，项目级buildfs与镜像内容复核通过，下载依赖造成的本机构建阻塞解除；完整本机软件门禁随后退出0，见[复核记录](../output/audits/littlefs-offline-20260929/report.md)。本轮没有修改代理配置；原下载路径的具体网络根因未通过切换路径对照确认。镜像生成及软件门禁不替代板上初始化、挂载、断电与断网恢复验证。

2026-09-29内部实验推进：已将[内部技术目标T0—T4与到货清单](experiments/dht11-arrival-checklist.md)作为单人可执行的功能与证据链验收入口。T0本机软件构建已复核；T1—T4均待实物/隔离环境执行，教师、课程、精度及目标部署结论仍按上表独立保留。构建证据见[本轮记录](../output/audits/dht11-arrival-prep-20260929/report.md)。
