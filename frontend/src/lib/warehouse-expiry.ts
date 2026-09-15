/**
 * 批次效期紧急度：按距今天数分级，用于库存列表着色。
 * red：<30 天（临期紧急）；gold：<90 天（需关注）；undefined/null → 'none'（未录入）。
 */
export type ExpiryTone = 'danger' | 'warning' | 'ok' | 'none'

export function expiryTone(
  expiryDate: string | null | undefined,
  now: Date = new Date(),
): ExpiryTone {
  if (!expiryDate) return 'none'
  const expiry = new Date(expiryDate)
  if (Number.isNaN(expiry.getTime())) return 'none'
  const days = Math.ceil((expiry.getTime() - now.getTime()) / 86_400_000)
  if (days < 30) return 'danger'
  if (days < 90) return 'warning'
  return 'ok'
}

export const EXPIRY_TONE_COLOR: Record<ExpiryTone, string | undefined> = {
  danger: '#cf4444',
  warning: '#dd5b00',
  ok: undefined,
  none: undefined,
}
