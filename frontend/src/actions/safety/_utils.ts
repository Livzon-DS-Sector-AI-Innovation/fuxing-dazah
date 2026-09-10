/**
 * Safety module — shared utilities (NOT Server Actions).
 *
 * Next.js requires 'use server' files to ONLY export async functions.
 * Constants, sync helpers, and pure utilities live here instead.
 */

export const API_BASE = process.env.API_BASE_URL
  ? `${process.env.API_BASE_URL}/api/v1`
  : (() => { throw new Error('环境变量 API_BASE_URL 未配置，无法连接后端服务') })()

/** scheduler-config（AI 配置 + 定时任务）API 路径前缀 */
export const SAFETY_SCHEDULER_CONFIG = '/safety/scheduler-config'

/** bitable-config（多维表格配置中心）API 路径前缀 */
export const SAFETY_BITABLE_CONFIG = '/safety/bitable-config'

/**
 * Build a URL query string from a plain params object.
 * Filters out undefined, null, and empty string values.
 */
export function buildQueryString(params: object): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, String(value))
    }
  }
  const qs = searchParams.toString()
  return qs ? `?${qs}` : ''
}

/** base64 → 浏览器下载（与 meter 模块导出基线一致） */
export function downloadBase64Excel(base64: string, filename: string): void {
  const byteChars = atob(base64)
  const byteNums = new Array(byteChars.length)
  for (let i = 0; i < byteChars.length; i++) byteNums[i] = byteChars.charCodeAt(i)
  const blob = new Blob([new Uint8Array(byteNums)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  window.URL.revokeObjectURL(url)
  document.body.removeChild(a)
}
