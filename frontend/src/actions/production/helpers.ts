import { getAuthHeaders } from '@/lib/auth'

export type ActionResult<T = unknown> =
  | { success: true; data: T | null }
  | { success: false; error: string }

export const API_BASE = process.env.API_BASE_URL
  ? `${process.env.API_BASE_URL}/api/v1`
  : 'http://localhost:8000/api/v1'

export async function actionFetch<T = unknown>(
  url: string,
  options?: RequestInit,
): Promise<ActionResult<T>> {
  try {
    const authHeaders = await getAuthHeaders()
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options?.headers,
      },
    })
    if (!response.ok) {
      const errorBody = await response.text().catch(() => '')
      let errorMessage = `请求失败: ${response.status}`
      try {
        const errorJson = JSON.parse(errorBody)
        if (errorJson.message) {
          errorMessage = errorJson.message
          if (errorJson.detail) errorMessage += `: ${errorJson.detail}`
        }
      } catch {
        /* ignore */
      }
      return { success: false, error: errorMessage }
    }
    const json = await response.json().catch(() => null)
    return { success: true, data: (json?.data ?? null) as T | null }
  } catch (e) {
    return { success: false, error: e instanceof Error ? e.message : '网络错误' }
  }
}
