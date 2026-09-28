# 芯鉴知微项目真实性看板

核对日期：2026-09-28。范围：DHT11 工作区 `2.0.5` 草稿、LED 工作区 `2.0.3` 草稿；未确认它们已导入或发布到运行库。本页集中记录实物、教学、真实模型与运行环境还缺什么证据。软件版本、功能和最近测试数量统一见[实现状态](implementation-status.md)。

## 当前结论

软件已有诊断、反馈、教师处置、版本化资料包、三类记忆的生命周期管理，以及受控上下文的完整打包/来源审计；最新软件验证见实现状态。**目前仍不能据此确认实物故障、完整 AI 因果支持或课堂效果。** 本轮上下文实施没有开展实物实验、取得教师签署、调用真实Provider、检查业务运行库或远端CI；当前配置检查为AI关闭、Provider未就绪。

状态含义：`verified` 只说明该项限定事实有依据；`pending_hardware` 等待实物确认；`pending_teacher` 等待教师确认（课程判据用 `pending_course_confirmation`）；`issue` 表示已确认且仍存在的缺口。没有依据时确认人、时间和根因保持空或 unknown；来源声明、文件哈希和 Evidence UUID 本身不认证硬件事实。

## 硬件待确认

D 包为 [DHT11 包](../backend/experiment_packages/dht11_temperature_humidity/)，L 包为 [LED 包](../backend/experiment_packages/gpio_led_output/)；以下均为 `pending_hardware`。

| 事项 | 已有配置/已知范围 | 缺什么、由谁确认 |
| --- | --- | --- |
| DHT11 候选接线 | ESP32-DevKitC V4/WROOM-32E、四针裸 DHT11、DATA→GPIO4、3.3V、4.7kΩ上拉；见 D 包 hardware.yaml、[固件说明](../firmware/esp32_dht11/README.md)及 Aosong 原始说明书 | 硬件负责人核对实物引脚与供电，做连续读取和断线对照 |
| 失败阈值 | 窗口累计阈值5是可配置示例，连续失败阈值未知；见 D 包 rules.yaml / truth_status.failure_threshold | 实测成功/失败序列，教师确认可接受误报 |
| 真实故障日志与可区分性 | `DHT11_READ_FAILED→sensor.read_failed` 是当前契约；断线、错GPIO、未供电与器件异常可能同表现，placeholder故障树不足以确认唯一根因 | 固件/硬件负责人保存逐次日志、版本与独立测量，按[历史审计矩阵](archive/experiment-knowledge-audit.md)做单因素对照 |
| 心跳、采样与超时 | 固件配置3秒采样，DHT11最低请求间隔2秒；平台90秒是监测时限，不是实测周期。见 D 包和 firmware_config.h | 测量周期、延迟、断网恢复，教师确认课堂容差 |
| LED GPIO、有效电平与回路 | GPIO2、active_level=1是示例，限流和回流未确认；见 L 包 hardware.yaml / truth_status.final_gpio | 核对板载/外接、器件型号、原理图和实物 |
| LED `level` 来源 | 未知是真实固件的变量、寄存器还是引脚采样；见 truth_status.level_source | 固件负责人提供源码、构建版本和测量位置 |
| LED 发光与响应窗口 | 没有已验证的独立光学输入；电流或HIGH命令不等于发光，比较窗口也待确认；见 truth_status.physical_light | 人工/光学观测与命令时刻关联，确认响应窗口 |
| 固件实物可靠性 | 编译和主机故障模拟已有记录；单批缓存满暂停采样 | 按[硬件验证计划](hardware-validation-plan.md)核验真实闪存、掉电、Wi-Fi/TLS、存储失败、回执和传感器精度 |

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
| AI语义、CoT效果与成本 | `evidence-reasoning-v2.7` 分步核对和完整上下文准备已接入，Mock/代码检查已有证据；新增语义条目未审阅，真实Provider质量、因果支持和实际费用未验收 | 按[评测对应表](evaluation-requirements.md)记录独立语义审阅；在授权环境以冻结输入比较旧/新提示的实际输出与费用。结构正确不代表语义正确。 |
| 记忆真实性与保留策略 | 来源、审核、版本与停用检查已实施；配置事实不代表实物核验，经验不代表当前根因，工作上下文不自动成为长期知识。证据、Checkpoint、备份及外部副本尚无获定保留策略 | 确认各类数据保留期限与删除范围；在选定恢复环境验证最新可信停用登记。缓存清理不能证明所有副本已删除。 |
| 上下文真实效果 | 软件已有整单元选择、来源清单与独立合成评测；真实保留集和人工语义审阅尚未完成 | 按[方案P4材料清单](context-construction-plan.md#p4-已整理的材料清单)补齐两实验来源与实际模型输出；不以合成回归或完整代码门禁推断效果提升 |
| 运行环境与CI | 本地隔离库检查不等于已部署、运行库已迁移或远端CI通过；没有当前生产容量结论 | 对选定环境核对数据库、持久化Checkpoint、备份恢复、容量与CI实际执行记录；参见[部署说明](deployment.md) |

只有出现新证据才更新对应状态，记录来源版本、范围和确认依据。`truth_status` 是审阅注记，不参与阈值计算；参数来自 runtime_expectations、rules 和 expected_behaviors。硬件确认与教师确认互不替代；已修复项移出当前缺口，保留历史失败和验收报告，维护方式遵守[开发准则](development-guidelines.md)。
