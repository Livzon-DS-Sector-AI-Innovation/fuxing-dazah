/** 采集监控展示格式化 */

import dayjs from 'dayjs'

export function formatMonitorTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = dayjs(iso)
  return d.isValid() ? d.format('MM-DD HH:mm') : '—'
}

export function formatMonitorTimeFull(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = dayjs(iso)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : '—'
}
