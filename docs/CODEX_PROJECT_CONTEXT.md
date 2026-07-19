# 芯鉴知微项目上下文备忘

本文件由 Codex 根据 `芯鉴知微_项目背景README_Codex版.docx` 阅读整理，用于后续开发时快速对齐项目方向。

## 一句话定义

芯鉴知微是一个面向高校嵌入式与物联网实验课程的智能分析平台。它通过实验板采集运行状态、串口日志和传感器数据，自动识别常见实验异常，为学生生成排查建议，并为教师提供实验进度、高频错误和设备状态看板。

## 核心判断

- 项目不是普通 AI 问答框，也不是简单硬件实验 Demo。
- 核心价值是把嵌入式实验现场转化为可采集、可分析、可反馈、可复用的数据资产。
- 第一版要小而完整：一个 ESP32、一个 DHT11 传感器、一套日志格式、一个后端接口、一个规则诊断、一个学生端异常卡片、一个教师端统计面板。
- AI 不直接替代规则判断。更稳妥的结构是：规则负责判案，AI 负责讲明白。

## 推荐 MVP

主线实验：ESP32 + DHT11 温湿度实验。

第一版必须跑通：

1. ESP32 连接 Wi-Fi。
2. ESP32 读取 DHT11。
3. ESP32 输出统一格式日志。
4. ESP32 将日志和传感器数据上传到后端。
5. 后端保存设备日志和传感器数据。
6. 规则引擎识别至少 3 类异常。
7. 学生端展示设备状态、实时日志、异常卡片和排查建议。
8. 教师端展示在线设备数、异常设备数、高频错误排行。
9. 知识库至少包含 5 个实验模板和对应常见错误。

## 建议覆盖实验

- LED 闪烁：GPIO 输出控制，引脚写错、LED 接反、未烧录等。
- 按键输入：GPIO 输入读取，上拉下拉错误、接线错误、抖动等。
- DHT11 温湿度：DATA 接错、供电异常、库初始化失败等。
- 光敏传感器：ADC 引脚错、数值长期不变等。
- 超声波测距：Trig/Echo 接反、测距超时、距离越界等。

## 系统分层

- 设备层：ESP32/Arduino/STM32、传感器、LED、按键，产生真实数据。
- 采集层：串口日志、传感器数据、设备心跳、错误码。
- 传输层：第一版推荐 HTTP，后续可考虑 MQTT 或 USB 串口转发。
- 后端层：数据接收、存储、实验任务、用户权限、诊断调度。
- 智能诊断层：规则引擎、时序异常检测、故障树、RAG 知识库、AI 生成。
- 应用层：学生端排查建议、教师端实验看板、知识库管理。
- 沉淀层：实验模板、错误案例、历史日志、教师审核知识库。

## 数据与接口草案

核心数据类型：

- 设备运行状态：online、offline、running、finished。
- 传感器数据：temperature、humidity、light、distance。
- 串口日志/错误码：DHT11 read failed、wifi_connected、button_pressed。

推荐日志字段：

- `level`
- `deviceId`
- `studentId`
- `experimentId`
- `message`
- `errorCode`
- `sensorData`
- `timestamp`

核心接口草案：

- `POST /api/device/log`
- `POST /api/device/heartbeat`
- `GET /api/device/status`
- `GET /api/student/experiments`
- `GET /api/student/logs`
- `POST /api/diagnosis/run`
- `GET /api/diagnosis/result`

## AI 模块方向

第一阶段优先：

- RAG 实验知识库。
- 规则诊断。
- AI 结构化建议。
- 故障树可做基础版。
- 分层提示可做简单版。

后续增强：

- 传感器时序异常检测。
- AI 自动沉淀知识库，需教师审核。
- 边缘规则预诊断或 TinyML，当前不建议主攻。

AI 输出建议使用 JSON，包含：

- `errorType`
- `summary`
- `evidence`
- `possibleCauses`
- `steps`
- `hintLevel`
- `needTeacherHelp`

## 开发注意事项

- 不要把 AI Provider 写死，应抽象成 `aiClient` 或 `aiService`。
- 前端不要直接调用大模型，前端只调用后端。
- 诊断结果必须结构化保存，不能只保存自然语言。
- 硬件上传接口字段变化要向后兼容。
- 知识库内容与代码分离，便于教师和团队维护。
- 规则引擎要可配置，不要把所有规则硬编码在一个函数里。
- 所有 TODO 使用统一格式：`TODO[待补充]: 说明缺失信息`。
- 不确定的信息保留占位符，不要编造。

## 最小开发路线

1. 完成 ESP32 + DHT11 数据上传 Demo。
2. 后端完成 `/api/device/log` 和 `/api/device/heartbeat`。
3. 数据库保存 `DeviceLog`、`SensorReading`、`DiagnosisResult`。
4. 手写规则识别 `SENSOR_READ_FAILED`、`DEVICE_OFFLINE`、`VALUE_OUT_OF_RANGE`。
5. 建立 DHT11、LED、按键三个实验的知识库初版。
6. 接入 RAG 检索，把相关知识作为 AI 上下文。
7. AI 输出结构化诊断 JSON。
8. 学生端展示异常卡片和排查步骤。
9. 教师端展示设备在线数、异常数和高频错误。
10. 再加入故障树、分层提示、知识库审核等增强功能。
