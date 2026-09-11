# DHT11 / LED 实验知识审计与事实清单

审计日期：2026-09-08。对象：芯鉴知微 V2，仓库 HEAD `7efbaf47c375cc6c64df0f844bc5878ba641a960`。
范围：仓库源文件、设计文档、实现静态核查、内存合成探查及厂商一手资料；未连接真实硬件、未查询运行数据库中的发布/审核记录、未访问真实课堂记录。本报告不是硬件验收、教师签字或正式 KnowledgeCase。

> 2026-09-09 更新：本文记录 2.0.0 审计时点。已确认的软件/内容问题现已按 [实验包设计的可信化整改](experiment-package-design.md) 修正，并在真实性治理轮更新为工作区 2.0.2 草稿；下文原审计发现与旧 hash 保留为历史依据，不代表整改后的当前状态。硬件与教师待确认项未升级为已验证。

## 项目负责人可读摘要（原始审计）

- **发现了什么：** 示例资料混入确认性表述，累计失败被写成连续失败，GPIO 上报值被用于描述灯亮。
- **现实影响：** 可能错误判断故障、误导学生排查，并高估当前实验验证程度。
- **能否解决：** 软件表达与证据边界可以整改；当前进展见 [真实性看板](project-truth-status.md)，下文保留审计时点原貌。
- **需要谁确认：** 硬件负责人提供实物与测量记录，教师确认课程标准和案例。
- **下一步：** 先核对器件和指导书，再实施可追溯的对照试验，不凭经验填满未知项。

## 1. 结论与边界

当前 V2 的职责划分保持不变：FastAPI/PostgreSQL/Vue 3；DiagnosisState + LangGraph；规则识别异常；故障树限定候选；结构化知识供给；AI 仅排序候选并引用本次真实落库 Evidence UUID；知识经人工审核后发布。无 RAG、Embedding、自由规划或多智能体扩展。

两个 `2.0.0` 实验包均为工程示例。真实存在的 UUID 证明记录可追溯，不证明记录来自真实硬件，也不证明上报内容等于物理事实。当前失败日志不足以确认 DHT11 根因；LED 上报电平不能证明实际发光。

**本阶段仅建立审计文档和验证计划。下列修改全部是待确认建议，没有改动任何实验包、KnowledgeCase、规则或代码。**

## 2. 来源登记与审计对象

以下仓库路径相对仓库根目录；D 包缩写指 `backend/experiment_packages/dht11_temperature_humidity/`，L 包指 `backend/experiment_packages/gpio_led_output/`。事实表中的路径与字段组合为可定位的 source_ref，不表示外部权威背书。

| 来源 ID | 实际检查对象 | 能证明什么 |
| --- | --- | --- |
| R1 | [architecture.md](architecture.md)、[implementation-status.md](implementation-status.md)、[experiment-package-design.md](experiment-package-design.md)、[ai-diagnosis-design.md](ai-diagnosis-design.md)、[development-guidelines.md](development-guidelines.md) | 项目设计、已声明限制；文档中旧测试结果不是本次实测 |
| R2 | D 包全部十个 YAML | DHT11 当前工程配置、样例规则、案例、提示及测试 |
| R3 | L 包全部十个 YAML | LED 当前工程配置、样例规则、案例、提示及测试 |
| R4 | `backend/knowledge/cases/{dht11,led,button,photosensor,ultrasonic}.yaml`；`knowledge/templates/README.md`、`knowledge/rules/README.md` | 五个旧兼容案例均 pending；模板/规则目录仅有说明，无教师原始附件 |
| R5 | `backend/app/diagnosis/{normalization,expected_behavior,matcher}.py`；`backend/app/services/diagnosis.py` | 输入归一化、统计口径、规则选取及实际 Evidence 持久化类型 |
| R6 | `backend/app/experiment_packages/{schemas,loader}.py`；`backend/app/services/experiment_packages.py`；`backend/app/knowledge/matcher.py`；`backend/app/schemas/knowledge_case.py` | 严格 Schema、包校验、测试门槛、案例准入条件 |
| R7 | [device-protocol.md](device-protocol.md)；`backend/app/schemas/device.py`、`backend/app/services/device_ingest.py`、`backend/app/core/config.py` | 通用设备协议、有限数值校验、在线状态与接入限制 |
| R8 | `backend/app/diagnosis/rules/core_rules.yaml`；`backend/app/diagnosis/rules/experiments/gpio_led.yaml`；旧 `backend/app/experiments/definitions/gpio_led_output.yaml`；`backend/app/diagnosis/fault_trees/` | 旧兼容规则/故障树存在，不能默认算作已绑定包的生效配置 |
| R9 | `backend/app/ai/diagnosis_graph.py`；`backend/app/services/diagnosis_episode.py` | failure_count / historical_failures 属于诊断指导历史，不等于固件连续采样失败数 |

外部来源均于 2026-09-08 访问。只摘记必要事实，不把整份厂商手册复制进项目，也不导入正式案例。尚未归档厂商 PDF 二进制与 SHA-256；下次选定实际器件后应按授权条件归档对应版本及访问记录。

| 来源 ID | 一手来源、版本和定位 | 适用范围与限制 |
| --- | --- | --- |
| S1 | [奥松 DHT11 产品手册](https://www.aosong.com/userfiles/files/media/DHT11-V1_3%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E8%AF%A6%E7%BB%86%E7%89%88%EF%BC%89.pdf)，V1.3_20170331；印刷页 1–6（PDF 页 2–7） | 原厂该版本器件；不能默认等于采购模块、其他修订版或三针转接板 |
| S2 | [Espressif ESP-IDF v5.3.2 / ESP32 GPIO 文档](https://docs.espressif.com/projects/esp-idf/en/v5.3.2/esp32/api-reference/peripherals/gpio.html)，GPIO Summary、gpio_set_direction / gpio_set_level / gpio_get_level | 经典 ESP32 与指定 SDK 文档；不是全系列 ESP32、不是本项目固件版本声明 |
| S3 | [Kingbright WP7113ID 数据表](https://www.kingbrightusa.com/images/catalog/SPEC/WP7113ID.pdf)，V.14A，页 1–3 | 仅用作有明确型号的 LED 资料范例，**不是本项目已选 LED**；其电压、电流和光学数值不得移植至当前包 |

未发现两个包的来源字段指向实际课程指导书、教师签署记录、厂商版本化手册或硬件 run 记录。仓库还有项目介绍 PDF、旧项目现状 DOCX 等交付物，本次未将这些宣传/进展材料当作器件事实来源；未逐份审阅未跟踪交付物及压缩包。

## 3. 当前资料分类审计

| 分类 | DHT11 | LED | 处理 |
| --- | --- | --- | --- |
| 已有明确项目来源 | 十工件、版本、GPIO4、阈值 5、三个 cause_id；可在 R2/R5 定位 | 十工件、GPIO2、active_level=1、三个 cause_id；可在 R3/R5 定位 | 仅确认“仓库如此定义”，不能升格为硬件事实 |
| 当前项目示例数据 | cases 中 isTestData=true；故障 facts=20、正常 facts=0 | cases 中 isTestData=true；预期违背计数 1/0 | 继续仅供合成校验 |
| 开发阶段假设 | esp32-devkit 泛称、GPIO4、input_pullup、2000ms；失败越多越支持接线；提示升级阈值 | esp32-devkit 泛称、GPIO2、高电平有效；电平不符支持极性/器件故障；固定期望 HIGH | 标明待证实，不据此确定根因 |
| 待硬件确认 | 器件修订、裸器件/模块、供电、地、上拉、方向切换、采样/超时、错误码与真实性 | 板载/外接、原理图、引脚、限流回路、有效电平、level 的测量来源、光学观测 | pending_hardware |
| 待课程/教师确认 | 实验目标、允许环境范围、合格连续读数定义、提示顺序、仪表操作与器件替换条件 | 亮灭时序、验收“看到灯亮”还是电平、可用仪器、排查步骤与评分标准 | pending_course_confirmation |
| 不可视为真实教师经验 | confirmedBy=teacher-team、confirmedAt=2026-09-04、teacherNotes、rootCauseStatus=confirmed | 同左 | 全为测试夹具；无签署证据，不能沿用到正式案例 |

`metadata.yaml` 自身没有 isTestData 字段，包内案例有 isTestData=true；数据库 ExperimentVersion 另有 is_test_data，由导入链路记录。不能仅凭 metadata 的 draft 或案例的 approved 推断线上发布状态。当前未审计数据库。

### 3.1 需要优先处理的真实性与可观测性问题

1. **案例审核占位。** 两包各一个案例同时写有 approved、confirmed、factsLocked、qualityCheckPassed 和 teacher_confirmed_case，但 isTestData=true。四重门槛能验证字段状态，不能验证教师是否真的做过实验。正式版本不得简单把 isTestData 改为 false；需从真实独立记录重建事实和确认链。
2. **DHT11 规则不等于连续失败。** `event_type_count >= 5` 统计窗口内指定组件的失败事件；不检查成功是否打断、不要求在线、不要求温湿度缺失。默认上下文回看 3600 秒（调用可变）；累计失败与固件连续失败、诊断历史失败是三个口径。5 次、权重和升级时间均无硬件/课程依据。
3. **同证据强行排序。** DHT11 接线原因额外取得失败事件权重 60，与触发规则重复依赖同一症状；LED 软件原因也重复使用预期违背。优先检查顺序不等于根因支持强度。故障树 score 不具统计概率意义。
4. **候选空间缺项。** DHT11 没有独立“传感器未供电”cause_id；“数据线接错/接触不良”不能精确表达所有供电故障。两个包都没有 DEVICE_OFFLINE 规则；`diagnose()` 绑定包时使用包规则文档，不自动合并 core_rules。设备页面可显示离线，不代表该包能给出离线异常诊断。超时不说明断电还是网络中断。
5. **LED 证据语义越界。** hardware 宣告 `led.output_level`；实际观测持久化统一命名 `observation.level`。`level=1` 的内容由固件决定，当前无实现证明它来自 pad 输入回读，更无电流/光敏证据。案例的“LED 状态没有变化”和 normalState 的“led: 点亮”不是电平日志能够推出的事实。
6. **LED 没有动作时序关联。** `state_equals` 使用当前列表最后一个匹配观测，固定 expected=1，没有 command_id/目标状态/响应窗口约束；正常灭灯 level=0 也可能被判违背，缺观测则 unknown，规则违背计数为 0。不能把未命中规则当作实验正常。
7. **DHT11 预期行为未闭合。** `interface_communicates` 仅识别 communication_success / communication_failure；包映射的 sensor.read_failed 和温湿度 observation 不自动变成这两类事件，故 dht11_communicates 可一直 unknown。
8. **真实接入与 raw 示例路径不同。** DB 上下文使用 normalize_legacy_context，再重命名 device_error_code；不会自动运行 hardware.normalization 的完整原始映射。legacy 日志 component 只取 raw_payload 顶层 component_id/component；标准日志 Schema 没有这两个顶层字段，sensor_snapshot 中的值不会自动提升。DHT11 规则还要求 component_id=dht11，因此标准上报可能有错误码却不命中规则。需真实 ingest→DB→context 契约测试确认；不能拿 raw adapter 测试代替。LED 应核对 sensor_type 如何落到 status_led，再核对 metric_key=level，不能假设 `{pin:2,level:1}` 是当前 ingest 的合法完整报文。
9. **资料内部循环引用。** concepts.references 指向 hardware/steps，cases.sourceRef 指向自身文件，只证明项目出处，不是原厂或真实案例来源。
10. **硬件回路未完整描述。** DHT11 connections 仅 DATA→GPIO4，缺 VDD/GND/上拉回路；LED 仅 ANODE→GPIO2，缺电阻、阴极回路、供电/地和板级图。DHT11 仅 input_pullup 不能描述完整双向通信。不要照此当成可直接施工接线图。
11. **版本资料差异。** S1 写读取间隔 >2 秒，而包固定 2000ms、概念写“至少 2 秒”；不能直接等同。必须锁定实际修订与驱动库后选择有余量的周期。此处不填入未经确认的正式替代值。
12. **包测试覆盖有限。** 当前每包一个正常、一个故障样本只注入 facts。loader 检查规则条件及期望原因是否为树中的子集，不验证真实故障对应原因、真实排序或遥测全链路。0 次失败也可能是没有收到任何数据。

## 4. 事实记录约定

source_type 仅用：official_documentation、datasheet、course_material、teacher_confirmed、project_design、hardware_test、real_case。
verification_status 仅用：verified_source、pending_course_confirmation、pending_hardware、hardware_verified、teacher_confirmed。

verified_source 表示核对到了指定来源，不表示本项目硬件适用性已验证。category 区分 manufacturer_fact / project_configuration / implementation_fact / diagnostic_limit / teaching_requirement / evidence_contract。一条记录只表达一个层级的事实。待确认的项目选择使用 project_design；没有拿到课程材料，不能虚写 course_material；目前没有 hardware_test、real_case、teacher_confirmed 来源记录，也没有 hardware_verified / teacher_confirmed 状态。

两类待确认均存在时，表中选当前主阻塞状态，另一门槛写 notes；不得因单个 status 就跳过其他门槛。此审计字典与 KnowledgeCase.sourceType、Evidence.source_type 是不同用途，不能直接把新字段注入现有严格 Schema。

## 5. DHT11 知识事实清单

本表每行 experiment_type 固定为 `dht11_temperature_humidity`（这是每行记录的一部分）。

| knowledge_id | experiment_type | category | statement | source_type | source_ref | verification_status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D-F01 | dht11_temperature_humidity | manufacturer_fact | S1 四针器件定义 VDD、DATA、NC、GND；VDD 3.3–5.5V | datasheet | S1 印刷 p1，引脚说明 | verified_source | 不作为采购模块接线图；适用性待硬件核对 |
| D-F02 | dht11_temperature_humidity | manufacturer_fact | S1 的 DATA 是单线双向接口，主机发起后释放总线等候响应 | datasheet | S1 p3、p5 | verified_source | 不等于固定 input_pullup 模式 |
| D-F03 | dht11_temperature_humidity | manufacturer_fact | S1 典型短线电路建议 4.7kΩ 上拉 | datasheet | S1 p3，典型电路 | verified_source | 是带条件建议，模块是否内置、上拉电压须实查 |
| D-F04 | dht11_temperature_humidity | manufacturer_fact | S1 采样周期及读取间隔要求大于 2 秒 | datasheet | S1 p2 表3、p3 说明3 | verified_source | 不为 2000ms 的严格边界背书 |
| D-F05 | dht11_temperature_humidity | manufacturer_fact | S1 上电后有 1 秒稳定等待；起始低脉冲为 18–30ms | datasheet | S1 p5、p6 表4 | verified_source | 需对实际库和器件修订核验，不新增固件常量 |
| D-F06 | dht11_temperature_humidity | manufacturer_fact | S1 帧含 40 位；有温湿度数据与校验字段 | datasheet | S1 p3–4 | verified_source | 校验失败只是通信观测，不能唯一定位断线 |
| D-C01 | dht11_temperature_humidity | project_configuration | 当前包选 esp32-devkit、DHT11、DATA=GPIO4 | project_design | R2 hardware.hardware/interfaces/connections | pending_hardware | 还需课程接线图；没有 GPIO4 通用标准 |
| D-C02 | dht11_temperature_humidity | project_configuration | 当前包设 input_pullup、minimum_interval_ms=2000 | project_design | R2 hardware.interfaces/required_parameters | pending_hardware | 需明确 idle 配置与通信时方向切换；见 D-F04 |
| D-C03 | dht11_temperature_humidity | project_configuration | 当前缺供电节点、公共地、裸器件/模块和上拉具体配置 | project_design | R2 hardware.connections | pending_hardware | 补 BOM、照片、原理图后才能确认电气兼容 |
| D-I01 | dht11_temperature_humidity | implementation_fact | 当前规则只要求窗口内 dht11 的 sensor.read_failed 数≥5 | project_design | R2 rules；R5 matcher._event_type_count | verified_source | 不是连续失败，不验证无读数或在线 |
| D-I02 | dht11_temperature_humidity | evidence_contract | DHT11_READ_FAILED 映射为 sensor.read_failed，但组件归属须正确传递 | project_design | R2 hardware；R5 build_diagnosis_context/normalize_legacy_context | pending_hardware | 已确认代码路径差异；真实固件报文尚未验证 |
| D-I03 | dht11_temperature_humidity | implementation_fact | 温湿度观测按 observation.temperature / observation.humidity 落库 | project_design | R5 save_diagnosis_result | verified_source | 有效数值上报不等于测量精度；失败不得伪造 0 |
| D-I04 | dht11_temperature_humidity | diagnostic_limit | DATA 断开、引脚错误、未供电、器件异常可形成相同失败日志，当前不能唯一分辨 | project_design | R2 fault_tree；R5；本报告矩阵 | pending_hardware | 是待测可辨识性假设；根因 unknown / need_verification |
| D-T01 | dht11_temperature_humidity | teaching_requirement | 失败次数 5、正常观察时长、允许误差与提示升级门槛尚无课程确认 | project_design | R2 rules/fault_tree/steps | pending_course_confirmation | 阈值随后还需硬件校准；不套用房间温湿度经验值 |
| D-T02 | dht11_temperature_humidity | teaching_requirement | 当前“测电压、最小程序、同型号对照”步骤待课程审核 | project_design | R2 teaching/hints；fault_tree.hints | pending_course_confirmation | 明确操作者、仪表和更换条件 |
| D-K01 | dht11_temperature_humidity | diagnostic_limit | 包内 confirmed.v2 案例是测试夹具，不是已证实接线故障 | project_design | R2 knowledge/cases.yaml | verified_source | teacher-team 与确认时间不能作为真实签署证据 |

S1 的量程、精度存在指定温度/电压等条件。本次不把这些数值转成项目规则；实际型号确认后按同版本表格建立独立参数记录，避免混用其他 DHT11 修订。

## 6. LED 知识事实清单

本表每行 experiment_type 固定为 `gpio_led_output`（这是每行记录的一部分）。

| knowledge_id | experiment_type | category | statement | source_type | source_ref | verification_status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| L-F01 | gpio_led_output | manufacturer_fact | 经典 ESP32 支持配置 GPIO 为数字输出，但存在引脚限制 | official_documentation | S2 GPIO Summary / gpio_set_direction | verified_source | 不代表任意 ESP32 系列任意引脚都能输出 |
| L-F02 | gpio_led_output | manufacturer_fact | gpio_set_level 的 0/1 表示设置低/高输出电平 | official_documentation | S2 gpio_set_level | verified_source | API 语义不是独立光学反馈 |
| L-F03 | gpio_led_output | manufacturer_fact | gpio_get_level 读取输入；未使能输入功能时该文档注明返回 0 | official_documentation | S2 gpio_get_level | verified_source | 读回 0 不能脱离 GPIO 模式解释 |
| L-F04 | gpio_led_output | manufacturer_fact | 经典 ESP32 GPIO2 属于 strapping pin | official_documentation | S2 GPIO Summary | verified_source | 本板上复位/下载时的负载需验证，不能泛化其他板卡 |
| L-F05 | gpio_led_output | manufacturer_fact | S3 区分正向电流、正向电压与光学强度，并给出带条件参数 | datasheet | S3 p1–3 | verified_source | 仅该型号范例；当前 LED 型号未知，不采用其数值 |
| L-C01 | gpio_led_output | project_configuration | 当前包用 GPIO2、output、active_level=1 | project_design | R3 hardware.interfaces/required_parameters | pending_hardware | 当前不是 GPIO12；板载/外接与课程要求待确认 |
| L-C02 | gpio_led_output | project_configuration | 当前仅声明 ANODE→GPIO2，完整限流与回流路径未定义 | project_design | R3 hardware.connections | pending_hardware | 不可直接按此接线；缺实际 LED、电阻型号和值 |
| L-C03 | gpio_led_output | project_configuration | 高电平是否点亮取决于本板电路，当前 active_level=1 待确认 | project_design | R3 hardware；teaching/steps | pending_hardware | 需原理图及 HIGH/LOW 双态观测 |
| L-E01 | gpio_led_output | evidence_contract | level 的来源尚未明确为命令变量、输出寄存器还是 pad 输入 | project_design | R3 hardware.normalization；R5 | pending_hardware | 固件版本与采集位置必须一起记录 |
| L-E02 | gpio_led_output | implementation_fact | 当前持久化类型是 observation.level，而案例声明 led.output_level | project_design | R5 save_diagnosis_result；R3 cases/hardware | verified_source | 静态声明通过不表示真实 UUID 类型已对齐 |
| L-E03 | gpio_led_output | diagnostic_limit | 当前包没有光敏或电流观测，因此 level/log 不能证明 LED 真实发光 | project_design | R3 hardware；R5 | verified_source | 即使以后测到电流，实际发光仍应另有光学/人工证据 |
| L-I01 | gpio_led_output | implementation_fact | state_equals 固定比较最后一条匹配 level 与 1 | project_design | R3 steps；R5 compare_expected_behavior | verified_source | 没有绑定这次亮灯命令；缺值 unknown |
| L-I02 | gpio_led_output | diagnostic_limit | 极性反接、回路开路、LED 器件故障可在 level=1 时表现相同 | project_design | R3 fault_tree；本报告矩阵 | pending_hardware | 当前根因 unknown / need_verification |
| L-T01 | gpio_led_output | teaching_requirement | 亮灭周期、允许响应延迟、目视判据与实验合格条件待课程确认 | project_design | R3 teaching/steps | pending_course_confirmation | 不能把 expected=1 直接当作整个亮灭实验验收 |
| L-T02 | gpio_led_output | teaching_requirement | 极性核对、断电测量、对照更换的操作权限和步骤待教师确认 | project_design | R3 hints/fault_tree | pending_course_confirmation | 未取得实际器件手册前不规定电阻或电流 |
| L-K01 | gpio_led_output | diagnostic_limit | approved/confirmed 案例没有真实“灯不亮”观测或教师签署附件 | project_design | R3 knowledge/cases.yaml | verified_source | 保持 test_only，不进入正式经验 |

## 7. 当前证据能力与缺口

| 要比较的证据 | 当前真实语义 | 不应推断 |
| --- | --- | --- |
| device_online | last_seen_at 与服务端时限形成的可达状态；配置默认 90s | 不证明 DHT11 有电、不证明板卡程序正常；超时不能唯一定位断电 |
| sensor_read_failed | 指定错误码归一化后的失败事件；组件匹配是前提 | 不证明 DATA 断开或传感器损坏 |
| temperature / humidity | 有时间、来源的数值观测；可能为旧值，需看采样时间 | 无读数不是 0；正常值不是无故障；值不变不是器件卡死 |
| failed_count | 当前无已确认的固件同名独立采样事实契约 | 不可用指导 failure_count/historical_failures 替代；累计事件数不等于连续失败 |
| log event | 固件报告的事件，持久化可追溯；细分 timeout/checksum 尚未落实 | 日志文案不等于外部仪器观测 |
| observation.level | 上报数值；GPIO 物理采样来源未确认 | 不证明实际 HIGH，更不能证明实际发光 |
| rule.* UUID | 规则对既有证据的派生统计 | 不是第二份独立物理证据，不可重复加权当作互相印证 |
| resolved / 教师反馈 | 人工报告与审核动作 | 单次“解决了”不自动证明唯一根因；仍需真实修复记录 |

### 7.1 DHT11 故障－证据矩阵

以下是**预期表现假设，不是硬件测试结果**。在线指 ESP32 仍能上报；缺读数也可能留有旧值。计数增长以固件确实逐次记录失败且接入组件映射正确为条件。每行根因可辨识结论均不得超出证据。

| 故障原因 / 候选覆盖 | device_online | sensor_read_failed / log event | temperature / humidity | failed_count | 当前系统是否能区分 | 还缺什么证据 | 后续如何验证 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DATA 断开；wiring.data_pin_mismatch 近似覆盖 | 可仍在线 | 可相同失败/超时 | 缺新值或旧值 | 若正确记录则增长 | unknown / need_verification；与下三项可完全相同 | 实际接线、两端波形、供电、驱动 GPIO | D-01，断电断开 DATA，其他不变；恢复对照 |
| 程序 GPIO 错误；software.gpio_mismatch | 可仍在线 | 可相同失败/超时 | 同上 | 同上 | unknown / need_verification | 固件构建哈希、实际引脚配置、物理线、目标脚波形 | D-02，仅改变经审核的配置，对照恢复 |
| 传感器未供电；无独立 cause_id | 可仍在线 | 可相同失败/超时 | 同上 | 同上 | unknown / need_verification；当前候选空间不完整 | VDD-GND 实测、上拉电源、反向供电检查 | D-03，教师确认隔离方法后单因素验证 |
| 传感器本体异常；hardware.sensor_failure | 可仍在线 | 可失败，也可能异常值 | 缺失、异常或表面正常均可能 | 不保证增长 | unknown / need_verification；不能靠“排查未解决”确认损坏 | 已知正常器件 A/B/A 对照、同接线同固件、原始波形 | D-04；无已知故障件则记录未执行，不制造损坏 |
| ESP32 停止上报/离线；包无该规则 | 超时后离线 | 无新事件；历史失败可能仍在窗口 | 无新值；历史值可能仍显示 | 服务端计数不必增长 | 可观察不可达，根因 unknown / need_verification；包内不会自动 DEVICE_OFFLINE | 串口、电源实测、网络日志、bootId | C-01/C-02 对比网络中断和断电 |
| 读取时序/库类型不符；software.gpio_mismatch 部分覆盖 | 可在线 | 可能失败，具体码待测 | 缺新值或偶发成功 | 依采样与日志策略 | unknown / need_verification | 库版本、实际周期、启动等待、超时/校验阶段 | D-05；按型号允许条件做受控配置对照 |
| 接触不良/间歇失败；wiring 类 | 可在线 | 成功失败交替 | 可有有效新值 | 累计数增长、连续数应被成功打断 | 规则仍可触发，不能推出持续断线；unknown / need_verification | 完整逐次成功/失败序列、接触记录 | D-06，受控可恢复断接，记录每次操作时刻 |

**不可辨识组 D-A：** DATA 断开、错误 GPIO、未供电和部分器件异常，可以具有完全相同的在线状态、失败次数、失败码及温湿度缺失。增加相同失败日志数量不会解除不可辨识性。矩阵中的“可能”需实测验证，不代表每一型号必然产生同样错误。

**不可辨识组 D-B：** 网络隔离、ESP32 断电、固件停止上传可能产生同样“无新遥测”。设备不可达应优先恢复可观测性，不能借历史 DHT11 失败认定当前传感器损坏。

### 7.2 LED 故障－证据矩阵

下表假设上报 level 来自程序目标变量的情况；若实际是寄存器或 pad 读回，必须重新实验，不可照搬。当前没有独立电流/发光传感器。

| 故障原因 / 候选覆盖 | device_online / log event | 命令及 level 可能值 | 真实发光事实 | 当前系统是否能区分 | 还缺什么证据 | 后续如何验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 程序未配置输出；software.output_configuration | 可在线，可能有执行日志 | 命令 HIGH、level=1 仍可能 | 未观测 | unknown / need_verification；规则可能不报错 | mode、API 返回值、pad 电压及时间关联 | L-02，对照正确模式 |
| 程序 GPIO 与实际线不符；software 类 | 可在线 | 目标脚 HIGH、上报 1 | 未观测 | unknown / need_verification | 编译配置、接线、两个脚各自测量 | L-03，仅改变配置，不接未知引脚 |
| 有效电平理解反了；software 类 | 可在线 | HIGH、1 | 可能不亮，当前不能证明 | unknown / need_verification | 板级原理图与 HIGH/LOW 各自光学结果 | L-04，双态观测 |
| 极性反接；wiring.led_polarity | 可在线，执行日志相同 | HIGH、1 | 未观测 | unknown / need_verification；可与开路/坏件相同 | 极性图、断电核对、经审核的电流/光学观测 | L-05；反向额定未确认时只做断电检查 |
| 电阻/回流线开路；wiring 类 | 可在线，执行日志相同 | HIGH、1 | 未观测 | unknown / need_verification | 完整回路、电阻/通断测量、光学记录 | L-06，断电打开已确认支路并恢复 |
| LED 器件异常；hardware.led_failure | 可在线，执行日志相同 | HIGH、1 | 未观测 | unknown / need_verification | 正常器件对照、回路与光学证据 | L-07；无故障件不声称执行 |
| GPIO 物理未达到目标电平；software 类不能覆盖所有物理原因 | 可在线 | 命令 HIGH；pad 可能低，变量仍为 1 | 未观测 | unknown / need_verification；只可确认实测不符 | 输入使能、独立电压、负载、供电、测量方法 | L-02/L-08；不要用短路制造故障 |
| 正常灭灯阶段 | 可在线 | LOW、0 | 应由独立观测确认 | 当前固定期望 1 可误报；根因 unknown / need_verification | command_id、当前目标值、相位、有效时间窗 | L-01，完整亮灭序列 |
| ESP32 离线 | 超时后离线，无新日志 | 历史值或缺值 | 未观测，灯可能保持或灭 | 只知不可达；unknown / need_verification | 本地电源/串口与同期光学记录 | C-01/C-02 |
| 未上报 level / 上报旧值 | 可仍在线 | 缺值或过时 1 | 未观测 | 缺值 unknown 不触发该规则；旧值可假满足 | 采样时间、命令关联、采集来源、缺测超时 | L-08 |

**不可辨识组 L-A：** 程序记录 HIGH/level=1 时，极性异常、开路、器件异常和配置错误可能保持相同服务器证据。系统至多知道“设备报告了命令/状态”，当前甚至没有确认该字段真的反映引脚电压。命令执行记录、pad 电压、回路电流、LED 发光必须分开记录，不能相互替代。

## 8. 按工件的修改建议（待用户确认后执行）

“保留”仅指其作为项目结构/标识成立，不代表正式硬件验收。PH=pending_hardware；PC=pending_course_confirmation。状态暂在本审计侧表维护，不直接增加 YAML 未知字段。

| 工件 | 现在可确认并保留 | DHT11 待处理 | LED 待处理 | 真实验证后补充 |
| --- | --- | --- | --- | --- |
| metadata.yaml | schema_version、code、locale、当前 version、draft 及组织标识的工程用途 | author=项目教师组需真实责任人确认（PC）；平台适用（PH） | 同左 | BOM/课程版本关联、实际审核人和发布记录；engine 字段只是声明 |
| hardware.yaml | 组件/接口 ID、映射结构 | GPIO4、mode、2000ms（PH）；补完整回路；DB 组件映射缺口 | GPIO2、有效电平（PH）；补 LED/电阻/回流；明确 level 来源和证据类型 | 对应实物手册、连接图、固件哈希、实际电压/时序、契约样本 |
| diagnosis/rules.yaml | rule_id、error_type 的工程契约 | 将“连续”与累计统计分清；5 次（PC+PH）；在线/缺测覆盖建议 | 输出状态措辞限定为已观测量；解决灭灯阶段与缺测不报警语义 | 根据真实正常/故障分布制定窗口/阈值与误报验收 |
| diagnosis/fault_tree.yaml | 候选 ID 可保留作草稿；不是已确认根因 | 供电候选缺项；同症状加权不能证明接线更可能；升级阈值 PC | 不能用 level 不符证明极性/坏件；增加必要独立证据要求 | 可辨识条件、unknown 条件、人工证据与允许动作；是否新增候选需另审 |
| knowledge/concepts.yaml | 概念标识、基本主题 | 外部 S1 引用与适用修订；>2s 和静态 mode 问题 | 关联 S2 与实际 LED 手册，区分电平/发光 | knowledge_id→来源版本/章节→课程/硬件证据关联 |
| knowledge/cases.yaml | isTestData=true 的示例性质 | 当前所有教师确认、根因字段不得继承到正式案例 | 同左；删除正式候选材料中无观测支撑的“灯未变化”断言 | 独立 run、真实 Evidence UUID、明确根因状态、实际修复及签署记录 |
| teaching/steps.yaml | connect/configure/observe 步骤结构 | 接线、周期（PH）；目标和成功判据（PC）；通讯预期事件不闭合 | GPIO2/高有效（PH）；亮灭相位/光学判据（PC）；固定 HIGH 不等于亮灭实验 | 每步输入、观测手段、成功/未知条件和下一验证动作 |
| teaching/hints.yaml | 四级结构、cause_id 引用 | 引脚具体值（PH）；测量与更换操作（PC） | 同左；不把命令日志写成光学证据 | 与 fault_tree.hints 统一措辞并验证实际消费路径 |
| tests/normal_cases.yaml | 保留现有合成引擎样例 | 增加有效温湿度/失败为零/无数据的区分 | 加正常 HIGH/LOW 两相、无光学证据不得判灯亮 | 新增版本绑定的真实采集回放，与合成测试明确分离 |
| tests/fault_cases.yaml | 保留现有错误类型结构校验 | 同表现多故障、间歇成功、缺组件、断网、恢复 | HIGH 不发光、反相、缺值、旧值、Evidence 类型契约 | 真实真值与盲测；不把注入 facts 的通过率当根因准确率 |

现有包 test Schema 仅支持 facts 和 error_type/candidate_causes，不能直接承载波形、expected_unknown、完整协议和时序回放。后续先使用现有后端测试能力覆盖契约；若确需扩展 Schema，单独提出最小变更，不在此阶段实现。已发布包不能覆盖，应以新版本导入审核；本报告不预定版本号。

## 9. 两类必须等待的输入

### 必须等待真实硬件

- 板卡厂商/型号/修订、模块芯片、完整 BOM 与接线图；确认 DHT11 模块是否带上拉、LED 是否板载。
- 实际供电、逻辑电平兼容、DHT11 时序、GPIO 方向切换、LED 限流及有效电平；不填统一 GPIO、电压或电阻“标准值”。
- 固件/驱动/SDK 版本、真实错误码与采样日志、失败计数定义、level 的物理含义。
- 每种单因素故障、同症状不可辨识组、恢复过程、仪器/照片/串口与服务端证据的时间关联。
- 真正的故障件对照和修复记录；未执行的测试保持 pending_hardware。

### 必须等待教师/课程

- 课程名称、实验指导书版次/页码、可引用权限、实验目标与接线要求。
- 连续读数/亮灭的成功判据、允许误差和延迟、测试窗口、提示升级和评分规则。
- 允许学生执行的测量、故障注入、拆装和更换步骤；需要教师操作的边界。
- 每个正式案例的真实审核人、时间、根因依据和实际解决动作。占位姓名、网上教程和 AI 文案均不能代替确认。

## 10. 本次验证记录

- 两包只读 CLI `backend/.venv/bin/python -m app.cli.verify_experiment_packages`（从 backend 执行）：各 9 项通过。
- DHT11 包 hash：`9d6e04e3e1893e54138bf7ff925e4e4b8801f3276c16ba8f046362d53329ca55`。
- LED 包 hash：`d31ab869d3fbecb4cab07f660b071f08f8fd29e72840ace023b17b45094d9281`。
- 内存合成探查：5 条 DHT11 失败事件加一条温度观测，仍命中 SENSOR_READ_FAILED，interface_communicates 为 unknown；清空观测/事件且 last_seen_at=None 后两包均无错误命中。
- 内存合成探查：LED level=1 得 satisfied；无观测得 unknown。sensor_snapshot 内 component_id 不会被 legacy normalizer 提取到事件 component_id。
- 探查没有落库、没有生成可供 AI 引用的真实 Evidence UUID、没有调用 AI。数据库完整链路待下一阶段。
- 当前 backend/.venv 是 Python 3.9；直接导入完整 diagnosis 服务遇到 `TypeError`（不支持该模块的联合类型表达式）。改用独立纯函数完成上述有限探查；没有修环境，也没有声称端到端测试通过。项目要求 Python 3.10+，下一阶段先选受支持环境。

下一阶段详见 [hardware-validation-plan.md](hardware-validation-plan.md)。本轮在调查和设计完成后停止，等待用户确认才修改实验包。
