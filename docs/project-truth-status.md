# 芯鉴知微项目真实性看板

更新：2026-09-12。范围：DHT11 / LED 工作区 `2.0.2` 草稿及完整流程整改；未导入或发布到运行数据库，未执行真实硬件实验，未取得教师/课程签署材料。

## 项目负责人可读摘要

| 问题 | 本轮结论 |
| --- | --- |
| 这次发现了什么问题？ | 前轮三项证据/反馈问题已修复。本轮补齐关页后找回，并发现首次诊断入口被隐藏、旧请求晚响应可能覆盖切换后的页面；这些缺口已修正。 |
| 会造成什么现实影响？ | 学生可能无法开始首次诊断，或重新进入后不知道上次反馈是否成功；切换实验后可能显示过时结果。 |
| 现在能不能解决？ | 软件侧已增加按会话找回和明确点击确认，补齐首次入口与旧响应隔离，并接入真实浏览器/后端/数据库联调和持续门禁。最新实际结果见整改报告；代码不能证明实物接线、故障或发光。 |
| 如果不能，需要谁确认？ | 硬件负责人验证板卡、日志、测量来源和阈值；教师提供实验指导书、验收标准、操作边界及真实案例审核。 |
| 下一步最应该做什么？ | 审阅本轮本地结果后安排配套发布并观察一次云端 CI；硬件侧锁定器件和课程材料，完成正常—单因素故障—恢复对照。 |

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
| 表述评测对象与方法 | ✅ verified（范围已纠正） | 扫描实际渲染文字，但只记录出现片段、不判语义；否定/改写反例不再获得关键词裁决，语义仍 not_run |
| high 最低证据门槛 | ✅ verified（代码） | 空引用、unknown/invalid 观测不能支持 high；引用存在仍不证明根因 |
| 解释摘要与操作边界 | ✅ verified（代码） | 摘要/限制由后端生成，步骤选允许动作；真实教学动作仍 pending_teacher |
| 完整推理语义与因果支持 | 🔴 issue（尚未覆盖） | 自由推理文字和占位故障树关联尚无完整语义/因果验收；真实可区分性 pending_hardware |

五问负责人摘要、要求映射、兼容影响和未完成范围见 [评测要求对应表](evaluation-requirements.md)。本次没有升级任何硬件或教师状态。

## 2026-09-12 完整流程评测第二阶段（历史失败基线）

| 关键点 | 当前状态 | 证据与下一步 |
| --- | --- | --- |
| 真实路由至诊断图的合成流程 | ✅ verified（限定场景） | 16 个 PostgreSQL 场景中 13 通过、3 失败，不能宣称整体通过 |
| 候选证据关联 | 🔴 issue：WF-ISSUE-01 | 实际候选可引用心跳占位；应按匹配条件关联，缺依据保留 unknown |
| 反馈重试身份 | 🔴 issue：WF-ISSUE-02 | 同报文重复提交会推进两次；需区分同请求重试与真正的新反馈 |
| 反馈接口会话归属 | 🔴 issue：WF-ISSUE-03 | 同设备其他学生会话反馈返回 201 并结束原诊断；应在写入前拒绝 |
| PostgreSQL 诊断恢复 | ✅ verified（连接/图重建） | 实际诊断图与业务表、原证据/审计保留并继续完成教师审核；不代表进程崩溃或生产验收 |
| 硬件与教师事实 | 🟡 pending_hardware / 🟠 pending_teacher | 本轮只有合成设备、Mock AI、合成教师角色，全部既有待确认状态不变 |

负责人五问摘要、复现记录及整改优先级见 [第二阶段报告](workflow-evaluation-phase2.md)。第一阶段已存为本地提交 `97c4d27`；第二阶段未修改生产流程或事实库。

## 2026-09-12 完整流程整改（当前状态）

| 关键点 | 当前状态 | 限定结论与证据 |
| --- | --- | --- |
| WF-ISSUE-01 候选证据关联 | ✅ verified（软件已修） | 关联实际匹配异常的持久化证据；AI 引用须属于对应候选。匹配不到保留空引用/unknown；不证明根因可区分性 |
| WF-ISSUE-02 反馈重试 | ✅ verified（软件已修） | 同诊断同键同载荷重放；改载荷 409；真实新尝试新键。浏览器未决载荷和按会话的服务端找回配合，明确点击后重试 |
| WF-ISSUE-03 反馈归属 | ✅ verified（软件已修） | 先核对会话—学生—设备—诊断，再写反馈；重放也校验。无归属旧诊断返回 403，不补造历史身份 |
| 反馈并发与保存失败恢复 | ✅ verified（限定故障窗口） | 42 项可靠性测试，含双库 28 个 Checkpoint 保存故障点；已消费只补确认，未消费继续恢复或按会话状态拒绝 |
| 迁移 0027 | ✅ verified（隔离升级） | 空库及带两条历史反馈的 0026 升级、单 Head、模型差异、唯一键检查通过；历史新字段保持 NULL；未部署生产 |
| 完整流程与回归 | ✅ verified（合成） | 前轮 PostgreSQL 25/25、后端 330、前端 43 unit/4 Mock 学生 E2E；本轮扩展和实际执行结果见整改报告，不把历史数量当最新结果 |
| 服务端反馈找回 | ✅ verified（软件） | 仅返回归属有效的当前会话记录；GET 不改变流程；原备注及较早诊断保留，显式点击恢复原请求；从未落库且本地丢失的请求无法找回 |
| 首次诊断与会话切换 | ✅ verified（软件） | 有会话无历史诊断可启动；无会话不允许启动；旧请求响应不能重新加载已离开的会话 |
| 浏览器连接真实后端/数据库 | ✅ verified（合成联调） | 两条真实 HTTP 流程校验落库、重放、关页重登与显式确认；实际 Alembic/Checkpoint，AI 仍是 Mock，不证明硬件和模型效果 |
| CI 完整流程门禁 | 已配置，云端运行待验证 | 配置 PostgreSQL 场景、JSON 报告保留及真实浏览器联调；本轮未推送，不把本地通过称为 GitHub CI 已通过 |
| 学生完整账号认证 | 待后续设计 | 当前仍是设备凭据与已有实验会话，不能把本轮归属修复称为完整学生登录系统 |
| 真实模型语义与硬件因果 | 🟡 pending_hardware / 后续语义评测 | 没有真实 Provider 质量评测、真实故障真值或完整电气安全验证 |
| 教师与课程事实 | 🟠 pending_teacher | 指导书、步骤、验收标准与真实案例仍待确认；没有自动批准知识 |

详细结果与接口兼容见 [完整流程问题整改](workflow-remediation.md)。原失败报告继续保留，当前修复仅升级软件行为行；实验包版本和硬件/教师事实未变。本轮未部署、未推送 GitHub。

## 2026-09-15 PDF 反例整改

| 关键点 | 状态 | 限定结论 |
| --- | --- | --- |
| 否定句误判、改写漏检 | 软件方法已纠正 | 不再用关键词决定语言对错；整体语义未审阅时报告 incomplete，不把代码通过冒充整体通过 |
| 具体限制被模板覆盖 | 软件输出已改进 | 本次异常、冲突与具体待核验项进入摘要/限制；模型提出的信息仍标未确认，持久化和回放保留 |
| Rubric 基本要求 | 已补齐定义 | 每条一事、只写符合条件、≤400 字符/3 句话，只能符合/不符合；没有评分机制 |
| AI 自由推理语义 | 尚未执行 | 四条语义检查均 not_run/null；没有自动裁判，未知事实状态不升级 |

负责人五问与验证结果见 [评测要求对应表](evaluation-requirements.md) 和 [整改报告](workflow-remediation.md)。此前报告保留为历史，不改写成新版成功记录。

### 追加复查（2026-09-15）

| 关键点 | 状态 | 当前依据与边界 |
| --- | --- | --- |
| unknown 被解释层重新引入候选 | ✅ verified | 已修复；空结果及残留旧候选的反例测试通过 |
| 测试案例被混入教师确认资料 | ✅ verified | 投影时排除测试/未确认/空根因，保留测试标识；此检查不提供真实教师签署 |
| 本轮完整软件回归 | ✅ verified | 后端 354、前端 60、模拟器 16、浏览器 9、PG 流程 25 项通过，详见 workflow-remediation.md |
| 自由推理文字与实际硬件结论是否一致 | 🟠 pending_teacher / 🟡 pending_hardware | 独立语义审阅及硬件真值仍未完成；代码通过不能替代 |
