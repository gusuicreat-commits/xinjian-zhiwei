# 芯鉴知微项目真实性看板

更新：2026-09-09。范围：DHT11 / LED 工作区 `2.0.2` 草稿；未导入或发布到运行数据库，未执行真实硬件实验，未取得教师/课程签署材料。

## 项目负责人可读摘要

| 问题 | 本轮结论 |
| --- | --- |
| 这次发现了什么问题？ | 前轮已修正累计失败、灯亮误判和测试案例冒充确认的表述；这轮发现待教师确认项仍不够具体，另有 LED 报文同时携带引脚和观测类型时被重复匹配的问题。 |
| 会造成什么现实影响？ | 团队可能把演示参数或测试经验当作课堂依据；一部分格式正确的 LED 原始报文可能被拒绝。此前仅凭日志判断灯亮或根因，也会误导学生排查。 |
| 现在能不能解决？ | 状态标记、报文匹配和软件判断边界可以修，已完成。仅靠代码不能证明真实接线、器件故障或灯是否发光。 |
| 如果不能，需要谁确认？ | 硬件负责人验证板卡、日志、测量来源和阈值；教师提供实验指导书、验收标准、操作边界及真实案例审核。 |
| 下一步最应该做什么？ | 先锁定板卡/器件清单和课程指导书，再完成一组正常基线及单因素故障—恢复对照；保留原始日志、接线照片和独立观测。 |

## 状态含义与使用边界

- ✅ **verified**：该行限定的来源事实或代码行为已核对；代码测试通过不等于硬件验证通过。
- 🟡 **pending_hardware**：必须由实物、仪器、固件记录或受控硬件试验确认。
- 🟠 **pending_teacher**：必须教师确认；`pending_course_confirmation` 是其中需要课程/指导书依据的子类。
- 🔴 **issue**：已确认的软件/设计缺口仍存在，不能当已实现能力。本轮修复项不继续标红，其修复记录单独保留。

同一主题拆分“软件是否正确表达”和“实物事实是否已知”，不把它们合并成一个绿色状态。无实测、无签署时，确认人/确认时间/根因保持空或 unknown。来源声明、文件 hash、Evidence UUID 都不是硬件事实真实性的自动认证。

## 当前关键知识与能力

表中 D 包是 [DHT11 包](../backend/experiment_packages/dht11_temperature_humidity/)，L 包是 [LED 包](../backend/experiment_packages/gpio_led_output/)。来源只证明对应行的限定结论。

| 关键点 | 当前状态 | 已知事实与证据边界 | 依据/定位 | 下一步与确认责任 |
| --- | --- | --- | --- | --- |
| DHT11 最终 GPIO | 🟡 pending_hardware | GPIO4 仍为显式标注的项目示例，不是通用标准 | D 包 hardware.yaml / truth_status.final_gpio | 硬件负责人核实板卡、原理图、接线；教师复核课程 |
| DHT11 累计/连续计数口径 | ✅ verified（代码） | 规则统计 failure_count_in_window；consecutive_failure_count 为 null，不推导连续失败 | matcher.py；D 包 rules.yaml；test_experiment_trust.py | 维持回归覆盖；不将指导历史失败数混入采样计数 |
| DHT11 合理失败阈值 | 🟡 pending_hardware | 累计阈值 5 是可配置示例；连续阈值未知 | D 包 rules.yaml；truth_status.failure_threshold | 实测成功/失败序列后校准，教师同时确认可接受误报 |
| DHT11 真实错误日志 | 🟡 pending_hardware | DHT11_READ_FAILED→sensor.read_failed 是当前数据契约，不是所有实物故障必然输出 | D 包 hardware.yaml / truth_status.fault_log_behavior | 固件/硬件负责人保留逐次真实日志和版本 |
| DHT11 故障可区分性 | 🟡 pending_hardware | 断线、错 GPIO、未供电与器件异常可能同表现；当前不足以确认唯一根因 | [审计矩阵](experiment-knowledge-audit.md)；D 包 placeholder 故障树 | 做对照；相同证据保留 unknown / need_verification |
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
| 心跳/采样周期和超时 | 🟡 pending_hardware | 90 秒为示例监测时限，不是心跳发送周期；读数最大间隔和 LED 响应窗口留空 | 两包 runtime_expectations / truth_status | 实测周期与延迟，教师确认容差；不自动填默认值 |
| 通用异常边界 | ✅ verified（代码） | DEVICE_OFFLINE、HEARTBEAT_STALE、DATA_STALE 集中在基础层；包仅提供运行预期 | base_health_rules.yaml；loader.py；回归测试 | 不能把不可达直接解释成断电或器件损坏 |
| engine 兼容声明执行 | 🔴 issue（既有范围外缺口） | compatibility.engine 当前仅保存声明，没有语义版本兼容检查 | [实现状态](implementation-status.md)既有限制 | 后续独立评审；本轮不扩展发布架构，不宣称兼容性已验证 |
| concepts/steps 全路径消费 | 🔴 issue（既有范围外缺口） | 内容被校验与存储不等于所有教学路径都已使用 | [实现状态](implementation-status.md)既有限制 | 后续逐路径验收；不得用工件存在冒充功能已生效 |

## 证据、异常、根因分层

| 层 | DHT11 示例 | LED 示例 | 能否自动升格？ |
| --- | --- | --- | --- |
| 证据 | 设备报告读取失败，归一化为 sensor.read_failed | 设备报告 GPIO_COMMAND=HIGH，或独立电气/光学观测 | 只陈述报告了什么及来源，不直接给根因 |
| 异常 | 规则判断窗口累计达到阈值，输出 SENSOR_READ_FAILED | 同命令下电气观测与目标不符，输出 GPIO_EXPECTATION_FAILED | 由规则判定；异常不是断线/损坏的证明 |
| 候选根因 | DATA 接线、GPIO 配置、器件异常等候选 | 配置、回路、器件异常等候选 | 证据不足时 unknown；排序不是确认，必须独立验证 |

## 本轮变更与验证

- 保留上一轮已经完成的代码修正，不改 LangGraph 主流程、AI 受约束原则、包发布机制或 PostgreSQL Evidence 主设计。
- 工作区包升为 2.0.2 草稿；新增逐项 truth_status 和案例的教师/课程待确认状态；修正 LED 原始映射重叠。
- truth_status 放在现有 required_parameters 扩展字典中，**只做审阅注记，不参与阈值计算、不触发自动补全**。真实运行参数仍以 runtime_expectations / rules / expected_behaviors 为准。
- [开发准则](development-guidelines.md)增加持续维护本看板和五问负责人摘要的要求。
- 本轮验证：两包各 10 项校验通过；后端全量 203 通过、1 跳过（可选 PostgreSQL Checkpoint 测试未配置连接）；Ruff 与差异检查通过。完整命令、hash 和警告见 [实现状态](implementation-status.md)“项目真实性治理”记录。测试通过只升级代码行为行，不升级任何硬件/教师行。

## 更新规则

每次审计或整改只更新有新证据的行：记录日期、来源版本、适用范围、确认依据和下一步；修复问题写明回归证据。没有实际硬件记录或教师签署，禁止 AI、脚本或开发者凭经验将待确认项改为 verified，禁止填入虚构姓名/时间/学生案例。教师确认与硬件验证互不替代。

## 2026-09-12 评测可信化第一阶段

| 关键点 | 当前状态 | 限定结论与下一步 |
| --- | --- | --- |
| 禁止表述评测对象 | ✅ verified（代码） | 已扫描渲染解释，并用故意注入错误的样例验证门禁会失败；仍不是语义评价 |
| high 最低证据门槛 | ✅ verified（代码） | 空引用、unknown/invalid 观测不能支持 high；引用存在仍不证明根因 |
| 解释摘要与操作边界 | ✅ verified（代码） | 摘要/限制由后端生成，步骤选允许动作；真实教学动作仍 pending_teacher |
| 完整推理语义与因果支持 | 🔴 issue（尚未覆盖） | 自由推理文字和占位故障树关联尚无完整语义/因果验收；真实可区分性 pending_hardware |

五问负责人摘要、要求映射、兼容影响和未完成范围见 [评测要求对应表](evaluation-requirements.md)。本次没有升级任何硬件或教师状态。
