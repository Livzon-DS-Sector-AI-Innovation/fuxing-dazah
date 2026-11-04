import { describe, expect, it } from 'vitest'

import { formatMonitorTime, formatMonitorTimeFull } from './format'

describe('采集监控时间格式化', () => {
  it('ragplus 返回的 Unix 秒级时间戳按毫秒解析，不再落到 1970 年', () => {
    expect(formatMonitorTimeFull(1792402920)).toBe('2026-10-19 17:42')
    expect(formatMonitorTime(1792402920)).toBe('10-19 17:42')
  })

  it('兼容毫秒时间戳与 ISO 字符串', () => {
    expect(formatMonitorTimeFull(1792402920000)).toBe('2026-10-19 17:42')
    expect(formatMonitorTimeFull('2026-10-15T06:10:00Z')).toBe('2026-10-15 14:10')
  })

  it('缺失值与 1970 占位时间显示为 —', () => {
    expect(formatMonitorTimeFull(null)).toBe('—')
    expect(formatMonitorTimeFull(undefined)).toBe('—')
    expect(formatMonitorTimeFull(0)).toBe('—')
    expect(formatMonitorTimeFull('1970-01-22T01:53:00Z')).toBe('—')
  })
})
