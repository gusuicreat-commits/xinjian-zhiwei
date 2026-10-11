# 芯鉴知微项目真实性看板

核对日期：2026-10-11。范围：SHT31 工作区 `1.0.0` 草稿、LED 工作区 `2.0.4` 草稿；未确认它们已导入或发布到运行库。本页集中记录实物、教学、真实模型与运行环境还缺什么证据。软件版本、功能和最近测试数量统一见[实现状态](implementation-status.md)。

本次增量：[默认容量与生成合同修复](../output/audits/ai-capacity-semantic-followup-20261004/report.md)将默认与本机输入配置统一为10000，并以v2.14限制新模型自由理由/摘要/需求；已知合成回归12/12通过，配置差异组6/6保留候选方向，证据不足组6/6保留unknown。前轮4000容量失败记录保留，显式低预算仍受保护。独立教师与课堂验收已有空模板，结论仍未填写；没有完整类型化实读配置生产方，正式资料、P4、硬件和课堂仍需真实材料。AI仍关闭、未部署，Loop仍未接入产品。

## 当前结论

软件已有诊断、反馈、教师处置、版本化资料包、三类记忆的生命周期管理，以及受控上下文的完整打包/来源审计；最新软件验证见实现状态。**目前仍不能据此确认实物故障、完整 AI 因果支持或课堂效果。** 2026-10-03已完成一轮Kimi真实合成API测试，发现排序合同、自由文字及等待体验问题；本机业务AI仍关闭，未部署。当前修复与验收证据见实现状态；真实模型已连通不等于整体质量、实物或课堂通过。

状态含义：`verified` 只说明该项限定事实有依据；`pending_hardware` 等待实物确认；`pending_teacher` 等待教师确认（课程判据用 `pending_course_confirmation`）；`issue` 表示已确认且仍存在的缺口。没有依据时确认人、时间和根因保持空或 unknown；来源声明、文件哈希和 Evidence UUID 本身不认证硬件事实。

## 硬件基线（用户 2026-10-11 决定）

2026-10-11，用户决定作废 2026-09-28 确定的“ESP32-DevKitC V4 + 四针 DHT11 + 板上 Wi-Fi 上传”方案，以同学已写好并在运行的程序为准；数据走电脑端串口桥；DHT11 资料包与旧固件直接从主线删除（最后所在提交 `2876e91`，见[删除索引](archive/README.md)）。

| 项目 | 当前基线 | 依据 |
| --- | --- | --- |
| 开发板 | ESP32-S3-N16R8（用户报告）；esptool 实读 ESP32-S3（QFN56）rev v0.2、内置 8MB PSRAM；USB 为 Espressif `303a:1001` 原生 USB Serial/JTAG | 2026-10-11 本机读取；是否为乐鑫官方 DevKitC-1 未核实 |
| 温湿度传感器 | Sensirion SHT31，I²C，地址 0x44（ADDR 高为 0x45） | 用户提供的源码；Sensirion SHT3x 手册 V7 |
| 接线设计 | 3.3V、共地、SDA→GPIO8、SCL→GPIO9；程序只开 ESP32 内部上拉 | `firmware/esp32s3_sht31/main/main.c`（原样入库） |
| 采样与输出 | 单次测量 0x2400、等 20 ms、每轮 1000 ms（实测约 1.05 秒一行）；只打印串口，不校验 CRC | 同上；2026-10-11 串口实测 |
| 数据通路 | 电脑端 `bridge/` 解析串口行，按设备协议 V1 上传；时间取电脑收到行的时间 | [串口桥说明](../bridge/README.md) |

当前状态：**程序在实物上持续输出合理读数，并已经串口桥接入隔离测试平台**（2026-10-11：40 秒 38 行 → 76 条读数、8 批全部接受，末行数值与串口一致）。这只证明程序运行并返回合理数值，不证明接线已逐项核验、精度、采样周期容差或故障可区分性；包内对应项仍为 `pending_hardware`。执行顺序见 [SHT31 内部实验指南](experiments/sht31-internal-lab.md)。

## 硬件待确认

S 包为 [SHT31 包](../backend/experiment_packages/sht31_temperature_humidity/)，L 包为 [LED 包](../backend/experiment_packages/gpio_led_output/)；以下均为 `pending_hardware`。

| 事项 | 已有配置/已知范围 | 缺什么、由谁确认 |
| --- | --- | --- |
| SHT31 接线（已运行，待逐项核验） | SDA→GPIO8、SCL→GPIO9、3.3V、地址 0x44；模块是否自带上拉未知；见 S 包 hardware.yaml、[程序说明](../firmware/esp32s3_sht31/README.md) | 硬件负责人拍照登记模块型号、引脚与上拉，做断线对照 |
| 失败阈值 | 窗口累计阈值 5 是项目待实测设定，连续失败阈值未知；程序约 1 秒一次，5 次失败约 5 秒内即可累积；见 S 包 rules.yaml | 实测成功/失败序列，教师确认可接受误报 |
| 真实故障日志与可区分性 | `SHT31_READ_FAILED→sensor.read_failed` 是当前契约；程序只输出同一句失败行，断线、地址不符、上拉不足、未供电与器件异常无法区分；程序不校验 CRC，干扰导致的错误数据会当作正常读数 | 按[不可辨识组与试验](hardware-validation-plan.md#不可辨识组与来源沿革)做单因素对照，保存逐次串口与桥日志 |
| 心跳、采样与超时 | 串口桥只在收到新行时附带心跳，每 5 秒或 50 条成批；平台 90 秒是离线判定时限，不是实测周期 | 测量串口周期、上传延迟、平台中断恢复，教师确认课堂容差 |
| LED GPIO、有效电平与回路 | GPIO2、active_level=1是示例，限流和回流未确认；见 L 包 hardware.yaml / truth_status.final_gpio | 核对板载/外接、器件型号、原理图和实物 |
| LED `level` 来源 | 未知是真实固件的变量、寄存器还是引脚采样；见 truth_status.level_source | 固件负责人提供源码、构建版本和测量位置 |
| LED 发光与响应窗口 | 没有已验证的独立光学输入；电流或HIGH命令不等于发光，比较窗口也待确认；见 truth_status.physical_light | 人工/光学观测与命令时刻关联，确认响应窗口 |
| 串口桥与平台中断 | 软件测试覆盖重试、按序排队（上限 20 批）、永久拒绝不堵队列和退出汇总；真机联调只做了正常路径 | 运行中停掉后端约 1 分钟再恢复，核对每个 requestId 只入库一次（指南 T4） |
| 自动恢复所需读数时效 | 当前温湿度 maximum_age_seconds 仍为 null，正常评估保持 unknown；读数时间来自电脑接收时刻，不是设备时钟 | 先导测量后制定内部参数，追加包并用独立数据验收，保留教师课程判据待确认 |

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
| 上下文真实效果 | 软件已有整单元选择、来源清单与独立合成评测；真实保留集和人工语义审阅尚未完成 | 按[P4待验材料清单](evaluation-requirements.md#p4-真实效果待验材料)补齐两实验来源与实际模型输出；不以合成回归或完整代码门禁推断效果提升 |
| 运行环境与CI | 本机业务库已于2026-10-10迁移到当前Head并核对（见[实现状态](implementation-status.md)）；本地检查不等于已部署或远端CI通过；没有当前生产容量结论 | 对选定环境核对数据库、持久化Checkpoint、备份恢复、容量与CI实际执行记录；参见[部署说明](deployment.md) |

只有出现新证据才更新对应状态，记录来源版本、范围和确认依据。`truth_status` 是审阅注记，不参与阈值计算；参数来自 runtime_expectations、rules 和 expected_behaviors。硬件确认与教师确认互不替代；已修复项移出当前缺口，保留历史失败和验收报告，维护方式遵守[开发准则](development-guidelines.md)。

2026-09-28资料包衔接P0–P3补充：来源登记目前主要为项目源码/配置定位，缺少对应的厂商附件、教师材料及实物记录；默认预检显示unverifiable。有限条件匹配不认证真实接线、全部自由文本前提或恢复结果。样包仍为测试草稿，P4概念外发未实施；未导入运行库、部署或完成真实Provider验收。

2026-09-28—29 围绕 DHT11 方案做的资料包来源修复、内部指南、LittleFS 镜像构建与 T0—T4 到货清单，随该方案于 2026-10-11 作废；相关文档最后所在提交为 `2876e91`，找回方式见[删除索引](archive/README.md)。LED 材料仍为旧项目基线来源；默认未提供来源快照的预检仍显示 unverifiable。2026-09-29 补的内部测试初始化 CLI 见[准备说明](experiments/internal-lab-preparation.md)，它不自动审批包、不创建活动会话。
