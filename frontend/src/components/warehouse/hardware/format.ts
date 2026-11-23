export function formatQty(value: unknown, placeholder = '—'): string {
  if (value === null || value === undefined || value === '') return placeholder
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Math.round(n).toLocaleString('zh-CN')
}
