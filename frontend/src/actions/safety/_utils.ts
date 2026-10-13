/**
 * Safety module — shared utilities (NOT Server Actions).
 *
 * Next.js requires 'use server' files to ONLY export async functions.
 * Constants, sync helpers, and pure utilities live here instead.
 */

// 本模块会被客户端 chunk 求值（client 组件经 actions barrel 依赖到它），
// 浏览器端只有 NEXT_PUBLIC_* 会被内联，因此不能在模块顶层抛错：
// 服务端走 API_BASE_URL；浏览器端回退 NEXT_PUBLIC_API_BASE_URL（构建期内联）；
// 两者皆缺时退化为同源相对路径（dev 下经 next.config 的 /api rewrite 仍可达后端）。
export const API_BASE = `${process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? ''}/api/v1`

if (!process.env.API_BASE_URL && !process.env.NEXT_PUBLIC_API_BASE_URL) {
  // eslint-disable-next-line no-console
  console.error('环境变量 API_BASE_URL / NEXT_PUBLIC_API_BASE_URL 均未配置，后端请求将退化为同源相对路径')
}

/** scheduler-config（AI 配置 + 定时任务）API 路径前缀 */
export const SAFETY_SCHEDULER_CONFIG = '/safety/scheduler-config'

/** bitable-config（多维表格配置中心）API 路径前缀 */
export const SAFETY_BITABLE_CONFIG = '/safety/bitable-config'

/** app-config（应用配置中心，env→DB 迁移）API 路径前缀 */
export const SAFETY_APP_CONFIG = '/safety/app-config'

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
