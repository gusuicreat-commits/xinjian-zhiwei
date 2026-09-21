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
