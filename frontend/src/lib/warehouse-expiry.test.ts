import { describe, expect, it } from 'vitest'
import { expiryTone } from './warehouse-expiry'

const NOW = new Date('2026-09-15T00:00:00+08:00')

describe('expiryTone', () => {
  it('未录入效期返回 none', () => {
    expect(expiryTone(null, NOW)).toBe('none')
    expect(expiryTone(undefined, NOW)).toBe('none')
    expect(expiryTone('', NOW)).toBe('none')
  })

  it('30 天内为临期紧急（danger）', () => {
    expect(expiryTone('2026-09-20', NOW)).toBe('danger')
    expect(expiryTone('2026-10-10', NOW)).toBe('danger')
  })

  it('30-90 天为需关注（warning）', () => {
    expect(expiryTone('2026-10-15', NOW)).toBe('warning')
    expect(expiryTone('2026-12-10', NOW)).toBe('warning')
  })

  it('90 天以上为正常（ok）', () => {
    expect(expiryTone('2026-12-15', NOW)).toBe('ok')
    expect(expiryTone('2027-09-15', NOW)).toBe('ok')
  })

  it('非法日期返回 none', () => {
    expect(expiryTone('not-a-date', NOW)).toBe('none')
  })
})
