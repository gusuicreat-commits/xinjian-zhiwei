# 芯鉴知微项目真实性看板

文档核对：2026-09-27。范围：DHT11 工作区 `2.0.5` 草稿、LED 工作区 `2.0.3` 草稿及当前软件边界。工作区内容不代表已导入或发布；本次未检查或迁移运行数据库，未执行真实硬件实验，未取得教师/课程签署材料。

## 项目负责人可读摘要

| 问题 | 当前结论 |
| --- | --- |
| 最近修复了什么？ | 本轮完成新旧入口一致性的10项修复：教师状态隔离、恢复证据、提示进度、遥测准入、就绪统计、分区错误、离线演示、64位时钟、快照备份及模拟器清单。 |
| 解决了什么现实风险？ | 防止旧账号请求回写、把无关数据当恢复、提示进度归零、旧入口绕过限额、演示假成功及备份核验遗漏。 |
| 软件验证到哪里？ | 本轮本地门禁按阶段执行并复测失败项，覆盖后端、前端、真实PG并发/迁移/恢复、浏览器和固件编译；明细与未验证范围见下方报告。远端CI与部署未验收。 |
| 还不能确认什么？ | 实物故障、闪存掉电、Wi-Fi/TLS、教师资料、完整AI语义/因果支持及真人课堂效果。 |
| 下一步怎么推进？ | 按缺口分别采集硬件、教师与课堂证据；选择具体实施任务时对照开发准则，不把历史软件通过当成现实效果证明。 |

软件版本和能力统一见[实现状态](implementation-status.md)。最近软件执行证据为[新旧入口修复报告](../output/audits/legacy-boundary-remediation-latest/report.md)；更早失败及整改见[历史索引](archive/README.md)。历史运行库版本、记录数量不在本页冒充实时状态。

## 状态含义与使用边界

- ✅ **verified**：该行限定的来源事实或代码行为已核对；代码测试通过不等于硬件验证通过。
- 🟡 **pending_hardware**：必须由实物、仪器、固件记录或受控硬件试验确认。
- 🟠 **pending_teacher**：必须教师确认；`pending_course_confirmation` 是其中需要课程/指导书依据的子类。
- 🔴 **issue**：已确认的软件/设计缺口仍存在，不能当已实现能力。已修复项注明对应证据，不和旧失败基线混为当前缺口。

同一主题拆分“软件是否正确表达”和“实物事实是否已知”，不把它们合并成一个绿色状态。无实测、无签署时，确认人/确认时间/根因保持空或 unknown。来源声明、文件 hash、Evidence UUID 都不是硬件事实真实性的自动认证。

## 当前关键知识与能力

表中 D 包是 [DHT11 包](../backend/experiment_packages/dht11_temperature_humidity/)，L 包是 [LED 包](../backend/experiment_packages/gpio_led_output/)。来源只证明对应行的限定结论。

| 关键点 | 当前状态 | 已知事实与证据边界 | 依据/定位 | 下一步与确认责任 |
| --- | --- | --- | --- | --- |
| DHT11 工程候选接线 | 🟡 pending_hardware | 已固定 ESP32-DevKitC V4/WROOM-32E、四针裸 DHT11、DATA→GPIO4、3.3V、4.7kΩ 上拉；仍未做实物核验 | D 包 hardware.yaml；firmware/esp32_dht11/README.md；Aosong 原始说明书 | 购件后按实物引脚图、连续读取和断线对照复核 |
| DHT11 累计/连续计数口径 | ✅ verified（代码） | 规则统计 failure_count_in_window；consecutive_failure_count 为 null，不推导连续失败 | matcher.py；D 包 rules.yaml；test_experiment_trust.py | 维持回归覆盖；不将指导历史失败数混入采样计数 |
| DHT11 合理失败阈值 | 🟡 pending_hardware | 累计阈值 5 是可配置示例；连续阈值未知 | D 包 rules.yaml；truth_status.failure_threshold | 实测成功/失败序列后校准，教师同时确认可接受误报 |
| DHT11 真实错误日志 | 🟡 pending_hardware | DHT11_READ_FAILED→sensor.read_failed 是当前数据契约，不是所有实物故障必然输出 | D 包 hardware.yaml / truth_status.fault_log_behavior | 固件/硬件负责人保留逐次真实日志和版本 |
| DHT11 故障可区分性 | 🟡 pending_hardware | 断线、错 GPIO、未供电与器件异常可能同表现；当前不足以确认唯一根因 | [审计矩阵](archive/experiment-knowledge-audit.md)；D 包 placeholder 故障树 | 做对照；相同证据保留 unknown / need_verification |
| LED 最终 GPIO/有效电平/完整回路 | 🟡 pending_hardware | GPIO2、active_level=1 是示例；尚无确认的限流与回流配置 | L 包 hardware.yaml / truth_status.final_gpio | 核对板载/外接、器件型号、原理图和实物 |
| LED 三类证据语义 | ✅ verified（代码/契约） | GPIO_COMMAND、GPIO_ACTUAL_LEVEL、LED_PHYSICALLY_ON 独立；旧 level=1 不会自动转换为电气/光学证据 | normalization.py；L 包 concepts.yaml；回归测试 | 保留来源与命令关联，不用命令替代实测 |
| LED level 的真实来源 | 🟡 pending_hardware | 当前不知道真实固件上报的是变量、寄存器还是引脚采样 | L 包 truth_status.level_source | 固件负责人提供源码、构建版本及测量位置 |
| LED 实际发光 | 🟡 pending_hardware | 没有已验证的独立光学输入；有电流或 HIGH 命令也不自动等于发光 | L 包 truth_status.physical_light | 人工/光学观察与命令时刻关联；没有记录就保持 unknown |
| LED 命令比较与旧 LOW 误报 | ✅ verified（代码） | 按同一命令的目标值比较；不再固定要求 HIGH；缺命令关联/响应窗口为 unknown | expected_behavior.py；test_experiment_trust.py | 实际响应窗口仍须硬件确认 |
| LED 原始映射重叠 | ✅ verified（已修） | 显式 metric 报文携带 pin=2 时不再同时命中旧 level 映射 | L 包 hardware.yaml；三类报文回归测试 | 保留边界测试，不把修复称为实物接入验收 |
| 教师测试案例标记 | ✅ verified（代码/内容） | test_data、unverified、draft/unknown；无 teacher-team 署名或确认时间；不进入已审核知识匹配 | 两包 cases.yaml；KnowledgeCase Schema；回归测试 | 不能只去掉测试标记来发布正式案例 |
| 真实教师经验 | 🟠 pending_teacher | 未取得教师本人可追溯材料；teacherNotes 为空 | 两包 cases.yaml / facts.teacher_status | 教师提供依据、适用条件和审核记录 |
| 真实学生案例 | 🟠 pending_teacher | 当前都是合成例子，未取得真实课堂原始证据与修复记录 | 两包 facts.student_case_status | 课堂记录与 Evidence 关联、教师审核；另需真实硬件来源 |
| 教学验收标准 | 🟠 pending_teacher（pending_course_confirmation） | 持续读数、亮灭合格条件、允许误差/观察时长待确认 | 两包 truth_status.teaching_acceptance | 课程负责人提供指导书版本/页码和判据 |
| 提示步骤与升级门槛 | 🟠 pending_teacher | 当前是待审核排查建议，不是真实教师经验；故障树为 placeholder | 两包 truth_status.teaching_actions_and_escalation | 教师确认操作权限、测量方式和介入时机 |
| Evidence 名称与 UUID | ✅ verified（代码） | 包声明对齐持久化类型；UUID 属于实际测试数据库记录；有类型校验与 HTTP→DB 回归 | package loader；diagnosis.py；test_experiment_trust.py | 真实设备的来源与时序还需硬件验证 |
| 显式正常状态 | ✅ verified（代码） | 需要心跳、周期、有效字段、预期行为与无异常同时满足；缺参数或证据为 unknown | runtime_health.py；matcher.py；回归测试 | normal 仅指已配置的上报监测条件，不是硬件健康认证 |
| 心跳/采样周期和超时 | 🟡 pending_hardware | 固件配置 3 秒采样，DHT11 最低请求间隔 2 秒；平台 90 秒仍是监测时限，不是实测心跳结论 | D 包 hardware.yaml；firmware/esp32_dht11/include/firmware_config.h；Aosong 原始说明书 | 实测周期、延迟、断网恢复，教师确认课堂容差 |
| 通用异常边界 | ✅ verified（代码） | DEVICE_OFFLINE、HEARTBEAT_STALE、DATA_STALE 集中在基础层；包仅提供运行预期 | base_health_rules.yaml；loader.py；回归测试 | 不能把不可达直接解释成断电或器件损坏 |
| engine 兼容声明执行 | ✅ verified（代码） | 导入、发布校验和运行装载执行版本范围检查；无效或不兼容范围被拒绝 | `test_business_package_boundary.py`；历史业务规则实施报告 | 此检查不证明硬件/课程适用或所有教学工件已消费 |
| concepts/steps 教学参考 | ✅ verified（限定软件路径） | 新指导按明确关联保存并展示；首次/反馈/AI降级复用快照；旧记录不补造关联，未关联资料不自动成为建议 | [实现状态](implementation-status.md)；[验收报告](../output/audits/teaching-materials-latest.md) | 真实教学内容待教师审核；不声称模型已使用参考或已验证课堂效果 |

重新检查新增的软件边界见 [开发准则20.22](development-guidelines.md#2022-重新检查固定输入与原请求恢复br-recheck2026-09-20)
及 [重新检查验收记录](../output/audits/diagnosis-checks-latest.md)。分析的是已上传记录，不等于控制硬件复测；
处理已结束、未检测到异常和满足配置恢复判据分别展示，不上升为真实硬件验收。

## 证据、异常、根因分层

| 层 | DHT11 示例 | LED 示例 | 能否自动升格？ |
| --- | --- | --- | --- |
| 证据 | 设备报告读取失败，归一化为 sensor.read_failed | 设备报告 GPIO_COMMAND=HIGH，或独立电气/光学观测 | 只陈述报告了什么及来源，不直接给根因 |
| 异常 | 规则判断窗口累计达到阈值，输出 SENSOR_READ_FAILED | 同命令下电气观测与目标不符，输出 GPIO_EXPECTATION_FAILED | 由规则判定；异常不是断线/损坏的证明 |
| 候选根因 | DATA 接线、GPIO 配置、器件异常等候选 | 配置、回路、器件异常等候选 | 证据不足时 unknown；排序不是确认，必须独立验证 |

## 仍未完成的整体验收

| 范围 | 当前边界 | 完成所需证据 |
| --- | --- | --- |
| 自由推理文字与因果支持 | 结构、引用与动作约束已有软件检查；没有完成整体语义与硬件因果验收 | 独立语义审阅、可追溯硬件真值和反例；按[评测对应表](evaluation-requirements.md)记录not_run/incomplete |
| 真实Provider质量与成本 | Mock和确定性降级不能证明真实模型质量；预算金额仍有估算与待核对费用 | 在授权环境记录真实调用、输入投影、输出判定与实际费用 |
| 固件与真实设备 | 编译和主机故障模拟通过不等于ESP32实物通过；单批缓存满会暂停采样 | [硬件验证计划](hardware-validation-plan.md)中的采样、断线、断网、掉电、存储失败与恢复记录 |
| 课程与学生体验 | 合成教师角色和浏览器联调不能提供教师签署或学习效果结论 | 指导书、正式审核记录及[真人试用](usability-trial.md) |
| 运行环境与持续集成 | 本轮仅在独立测试容器验证，未部署、未迁移运行库、未触发远端CI | 对具体环境独立检查；数据库、Checkpoint、备份恢复与CI实际执行证据 |

## 更新规则

只更新有新证据的行，记录日期、来源版本、适用范围、确认依据和下一步。`truth_status`是审阅注记，不参与阈值计算或自动补全；运行参数仍来自runtime_expectations、rules和expected_behaviors。

没有实际硬件记录或教师签署，不得凭经验将待确认项改为verified，不填入虚构姓名、时间或学生案例。教师确认与硬件验证互不替代。已修复问题从当前缺口移出，但原始失败与验收记录保留在历史区。
