/** 采集监控展示格式化 */

import dayjs, { type Dayjs } from 'dayjs'

type MonitorTimeValue = string | number | null | undefined

/**
 * ragplus 契约③ 的 last_success_at 实际返回 Unix 秒级时间戳（number）。
 * dayjs(number) 会按毫秒解析，直接展示会落到 1970 年；这里统一兼容
 * 秒/毫秒时间戳与 ISO 字符串，并把缺失值/1970 占位值显示为「—」。
 */
function parseMonitorTime(value: MonitorTimeValue): Dayjs | null {
  if (value == null || value === '') return null

  const numeric =
    typeof value === 'number'
      ? value
      : /^\d+$/.test(value.trim())
        ? Number(value)
        : null

  if (numeric != null) {
    if (!Number.isFinite(numeric) || numeric <= 0) return null
    // 10 位秒级时间戳转毫秒；13 位毫秒时间戳直接使用
    const parsed = dayjs(numeric < 1e12 ? numeric * 1000 : numeric)
    return parsed.isValid() && parsed.year() > 1970 ? parsed : null
  }

  const parsed = dayjs(value)
  return parsed.isValid() && parsed.year() > 1970 ? parsed : null
}

export function formatMonitorTime(iso: MonitorTimeValue): string {
  const d = parseMonitorTime(iso)
  return d ? d.format('MM-DD HH:mm') : '—'
}

export function formatMonitorTimeFull(iso: MonitorTimeValue): string {
  const d = parseMonitorTime(iso)
  return d ? d.format('YYYY-MM-DD HH:mm') : '—'
}
