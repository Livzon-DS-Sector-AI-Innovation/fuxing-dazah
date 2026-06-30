/**
 * Safety module — shared utilities (NOT Server Actions).
 *
 * Next.js requires 'use server' files to ONLY export async functions.
 * Constants, sync helpers, and pure utilities live here instead.
 */

export const API_BASE = process.env.API_BASE_URL
  ? `${process.env.API_BASE_URL}/api/v1`
  : (() => { throw new Error('环境变量 API_BASE_URL 未配置，无法连接后端服务') })()

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
