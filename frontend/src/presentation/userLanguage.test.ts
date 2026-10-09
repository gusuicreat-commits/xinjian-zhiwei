import { describe, expect, it } from 'vitest'
import { evidenceText, issueLabel, logSummary, readableText } from './userLanguage'
describe('user-facing language preserves diagnostic boundaries', () => {
  it('explains saved system tokens without asserting hardware damage', () => {
    const source =
      '本次规则报告：DEVICE_OFFLINE、HEARTBEAT_STALE。当前推理结果为 unknown，尚不能给出有证据支持的原因排序。'
    const result = readableText(source)
    expect(result).toContain('设备未按时上报、未按时收到设备心跳')
    expect(result).toContain('目前还不能确定原因')
    expect(result).toContain('尚不能给出有证据支持的原因排序')
    expect(source).toContain('DEVICE_OFFLINE')
  })
  it('does not replace identifiers, technical names or measurements', () => {
    expect(readableText('id_DEVICE_OFFLINE DHT11 GPIO USB 23.5 °C')).toBe(
      'id_DEVICE_OFFLINE DHT11 GPIO USB 23.5 °C',
    )
    expect(issueLabel('NEW_RULE')).toBe('暂未提供通俗说明')
  })
  it('distinguishes check counts from failures and accumulated from consecutive', () => {
    const item = {
      fact: 'runtime_health_failure',
      observed_value: 1,
      details: [{ check: 'heartbeat_fresh' }],
    }
    const before = JSON.stringify(item)
    expect(evidenceText(item)).toBe('设备心跳：1 项检查未满足要求（不是硬件故障次数）')
    expect(JSON.stringify(item)).toBe(before)
    expect(evidenceText({ fact: 'failure_count_in_window', observed_value: 5 })).toContain(
      '不代表连续失败',
    )
    expect(evidenceText({ fact: 'new_fact', observed_value: 0 })).toContain('原始观测值：0')
  })
  it('marks synthetic logs and does not invent unknown log meaning', () => {
    expect(
      logSummary({ event_code: 'DHT11_READ_FAILED', message: 'synthetic', is_test_data: true }),
    ).toContain('测试记录')
    expect(logSummary({ event_code: 'UNRECOGNIZED', message: 'custom event' })).toContain(
      '暂未提供中文说明',
    )
  })
})

describe('query display vocabulary', () => {
  it('maps complete known codes only and leaves new codes unexplained', async () => {
    const { queryCodeLabel, queryQuestionText } = await import('./userLanguage')
    for (const code of [
      'not_reported',
      'no_approved_case',
      'observation_unknown',
      'question_not_approved',
      'source_stale',
      'reported_conflict',
      'requirement_missing',
      'material_omitted',
    ]) {
      expect(queryCodeLabel(code)).not.toBe('暂缺解释')
    }
    expect(queryCodeLabel('prefix_not_reported')).toBe('暂缺解释')
    expect(queryCodeLabel('new_reason')).toBe('暂缺解释')
    expect(queryQuestionText('unknown')).toBeNull()
    expect(queryQuestionText('synthetic.dht11.wiring_observation')).toContain('DHT11 的 DATA 线')
  })
})
