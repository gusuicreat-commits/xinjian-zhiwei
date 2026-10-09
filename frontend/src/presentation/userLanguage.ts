/** Display-only vocabulary. Never use labels as identifiers or change stored evidence. */
const codes: Record<string, string> = {
  DEVICE_OFFLINE: '设备未按时上报',
  HEARTBEAT_STALE: '未按时收到设备心跳',
  DATA_STALE: '实验数据缺失或更新不及时',
  SENSOR_READ_FAILED: '传感器读取失败',
  DHT11_READ_FAILED: 'DHT11 传感器读取失败',
  GPIO_EXPECTATION_FAILED: 'GPIO 输出与预期不符',
}
export function issueLabel(code: string | null | undefined): string {
  return (code && codes[code]) || '暂未提供通俗说明'
}
/** Translate only standalone, known system tokens, leaving numbers and technical names intact. */
export function readableText(text: string | null | undefined): string {
  return (text || '')
    .replace(/\b[A-Z][A-Z0-9_]*\b/g, (token) => codes[token] || token)
    .replace(/当前推理结果为 unknown/g, '目前还不能确定原因')
    .replace(/本次规则报告：/g, '本次检测发现：')
}
export function logLevel(level: string): string {
  return (
    (
      {
        error: '错误',
        critical: '严重错误',
        warn: '提醒',
        warning: '提醒',
        info: '信息',
        debug: '调试',
      } as Record<string, string>
    )[level.toLowerCase()] || '其他记录'
  )
}
export function logSummary(log: {
  event_code: string | null
  message: string
  is_test_data?: boolean
}): string {
  const known = log.event_code && codes[log.event_code]
  // The message may carry additional qualifiers; always retain it in the original record.
  return known
    ? `${known}${log.is_test_data ? '（测试记录）' : ''}`
    : /[\u4e00-\u9fff]/.test(log.message)
      ? readableText(log.message)
      : '这条设备记录暂未提供中文说明，可展开查看原文。'
}
const checks: Record<string, string> = {
  device_online: '设备上报',
  heartbeat_fresh: '设备心跳',
  data_fresh: '数据更新时间',
  data_periodic: '数据上报周期',
}
export function evidenceText(item: {
  fact: string
  observed_value?: number | null
  details?: Record<string, unknown>[]
}): string {
  const value = item.observed_value ?? '未提供'
  if (item.fact === 'runtime_health_failure') {
    const names = [
      ...new Set(
        (item.details || []).map((detail) => checks[String(detail.check)]).filter(Boolean),
      ),
    ]
    return `${names.length ? names.join('、') : '设备运行检查'}：${value} 项检查未满足要求（不是硬件故障次数）`
  }
  if (item.fact === 'failure_count_in_window')
    return `本次诊断时间范围内累计读取失败 ${value} 次（不代表连续失败）`
  if (item.fact === 'expected_behavior_violation_count') return `与实验预期不符的观测共 ${value} 条`
  return `这项证据暂未提供通俗说明；原始观测值：${value}`
}

export function metricLabel(key: string): string {
  return (
    (
      {
        temperature: '温度',
        humidity: '湿度',
        voltage: '电压',
        current: '电流',
        output_state: '输出状态',
      } as Record<string, string>
    )[key] || key
  )
}

const queryCodes: Record<string, string> = {
  waiting_answer: '等待你的观察答复',
  completed_satisfied: '资料核对完成（不代表故障已解决）',
  finish_unknown: '本次核对已结束，仍有资料缺口',
  stale: '资料已变化，本次核对结果不可再用',
  satisfied: '该项资料已取得',
  unknown: '目前无法判断',
  match: '程序自报 GPIO 与实验要求一致',
  mismatch: '程序自报 GPIO 与实验要求不一致',
  matches_table: '学生自述：与接线表一致',
  differs: '学生自述：与接线表不同',
  unclear: '学生自述：无法确认',
  present: '已找到适用的审核案例（不代表本次根因）',
  checked_empty: '已核对，未找到适用的审核案例',
  not_reported: '本次诊断没有可比较的程序引脚上报',
  no_approved_case: '没有适用的已审核案例',
  no_task_evidence: '本次诊断缺少可用证据',
  requirement_missing: '缺少可比较的实验引脚要求',
  package_not_bound: '本次会话未绑定实验资料包',
  observation_unknown: '实际接线观察仍无法确认',
  question_not_approved: '正式题目待教师确认，本次不提供作答',
  source_stale: '所用资料已变化或停用',
  source_error: '资料暂时无法读取，请稍后重试',
  access_denied: '当前无权查看资料',
  reported_conflict: '程序上报的引脚信息存在冲突，无法比较',
  material_omitted: '资料超过可用范围，未用于本次判断',
  question_version_stale: '题目版本已变化，本题不可再用',
  requirements_unknown: '仍有资料无法确认',
  firmware_gpio_vs_requirement: '程序引脚与实验要求',
  wiring_observation: '实际接线观察（学生自述）',
  approved_reference: '适用的审核案例',
  unconfirmed: '未确认故障原因',
  not_asserted: '实际接线与硬件效果尚未核验',
}
export function queryCodeLabel(code: string): string {
  return queryCodes[code] || '暂缺解释'
}
export function queryQuestionText(id: string): string | null {
  return id === 'synthetic.dht11.wiring_observation'
    ? 'DHT11 的 DATA 线是否按实验接线表接到开发板？'
    : null
}
export const queryOptionLabels: Record<string, string> = {
  matches_table: '按接线表连接',
  differs: '与接线表不同',
  unclear: '无法确认',
}
