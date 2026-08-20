# 芯鉴知微规则诊断设计（Phase 4）

## 范围

Phase 4 只实现可重复、可审计的确定性诊断，不实现 Phase 5 故障树、RAG 或 AI 推理。当前核心错误类型为：

- `SENSOR_READ_FAILED`：回看窗口中存在同名设备事件码。
- `DEVICE_OFFLINE`：距最后服务端接收心跳达到 YAML 阈值；从未心跳也视为匹配，并在证据中标记 `never_seen`。
- `VALUE_OUT_OF_RANGE`：读数超出调用方提供的通用实验模板指标范围。

## 数据流

`build_diagnosis_context` 按固定顺序读取设备日志、心跳和传感器读数，并合并可选
`ExperimentTemplateContext`。指定 Experiment Definition 时，兼容 Normalizer 还会构造统一
Observation/Event、Expected Behavior 与作用域选择。规则加载器递归读取
`backend/app/diagnosis/rules/`，按 common/interface/component/experiment Scope 选择来源；
旧调用只加载根目录兼容规则。Pydantic 拒绝额外字段、非法事实、非法运算符和重复规则 ID。
匹配器按 `priority` 降序、规则 ID 升序执行，输出命中规则、来源/版本/Scope 和原始证据。

规则集和上下文均规范化为排序 JSON 后计算 SHA-256。相同规则与相同上下文产生完全相同的输入指纹和匹配内容。

## 配置边界

YAML 只声明规则元数据、事实、运算符、阈值和参数；主匹配流程不按错误类型编写条件分支。目前开放事实为 `log_event_count`、`seconds_since_last_seen` 和 `out_of_range_count`，运算符为 `eq/gte/gt/lte/lt`。

具体 ESP32 型号、传感器型号、指标字段和生产阈值尚未确定。指标范围通过通用
`metric_ranges` 或 Expected Behavior 注入，示例值不得解释为生产配置。规则文件变更必须
经过评审和测试；规则集哈希与来源追踪随每条结果保存。重复规则 ID 失败关闭，不做隐式覆盖。

## 已知边界

- Phase 4 暂由诊断运行请求提供实验模板快照；正式实验模型建立后改为服务端按实验加载。
- 当前认证沿用设备令牌，学生/教师权限将在业务模型阶段补齐。
- 当前一次运行保存一条审计结果；输入指纹用于比较确定性，不作为幂等键。
- 不含 `VALUE_STUCK` 等可选规则，它们应在核心三类稳定后按相同机制扩展。
