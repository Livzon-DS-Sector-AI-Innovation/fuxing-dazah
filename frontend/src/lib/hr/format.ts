// HR 时间展示统一格式（此前各处 toLocaleString 写法有四种，同一时间在不同页面显示不一致）。

import dayjs from 'dayjs'

/** 空值统一显示「—」，其余按 YYYY-MM-DD HH:mm 展示 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  return dayjs(value).format('YYYY-MM-DD HH:mm')
}
