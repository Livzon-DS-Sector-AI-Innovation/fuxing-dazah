'use server'

import { getAuthHeaders } from '@/lib/auth'
import { logApiError } from '@/lib/hr/logger'
import { API_BASE } from './_utils'

interface HrRequestInit extends RequestInit {
  /** HTTP 失败且后端未返回 message/detail 时使用的中文报错 */
  errorMessage?: string
}

/** 从错误响应体中提取后端 message / detail（仅接受字符串） */
async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const err = await response.json()
    if (typeof err?.message === 'string' && err.message) return err.message
    if (typeof err?.detail === 'string' && err.detail) return err.detail
    if (Array.isArray(err?.detail) && err.detail.length > 0) {
      return err.detail.map((e: any) => `${e.loc?.join('.') || ''}: ${e.msg}`).join('; ')
    }
  } catch { /* 非 JSON 响应体 */ }
  return ''
}

/**
 * HR 模块服务端请求封装（参照 safety/_helpers.ts fetchApi 模式）：
 * 自动拼接 API_BASE、附带认证头；body 为 FormData 时去掉 Content-Type
 * 让 fetch 自动带 boundary。失败时抛出带中文文案的 Error，
 * 成功时返回解析后的 JSON（通常为 { code, message, data, meta? } 信封）。
 */
export async function fetchHrApi<T = any>(
  endpoint: string,
  options?: HrRequestInit
): Promise<T> {
  let response: Response
  try {
    const authHeaders = await getAuthHeaders()
    const { headers: optHeaders, errorMessage: _errorMessage, ...restOptions } = options || {}
    const headers: Record<string, string> = { ...authHeaders, ...(optHeaders as Record<string, string> | undefined) }
    if (restOptions.body instanceof FormData) {
      delete headers['Content-Type']
    }
    response = await fetch(`${API_BASE}${endpoint}`, {
      ...restOptions,
      headers,
      cache: 'no-store',
      next: { revalidate: 0 },
    })
  } catch {
    throw new Error('网络请求失败，无法连接到后端服务')
  }

  if (!response.ok) {
    const serverMessage = await extractErrorMessage(response)
    throw new Error(serverMessage || options?.errorMessage || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * HR 模块服务端文本请求封装：用于后端返回 HTML 等纯文本的接口
 * （如证明/Offer 预览）。失败时抛出带中文文案的 Error。
 */
export async function fetchHrText(
  endpoint: string,
  options?: HrRequestInit
): Promise<string> {
  let response: Response
  try {
    const authHeaders = await getAuthHeaders()
    const { headers: optHeaders, errorMessage: _errorMessage, ...restOptions } = options || {}
    const headers: Record<string, string> = { ...authHeaders, ...(optHeaders as Record<string, string> | undefined) }
    if (restOptions.body instanceof FormData) {
      delete headers['Content-Type']
    }
    response = await fetch(`${API_BASE}${endpoint}`, {
      ...restOptions,
      headers,
      cache: 'no-store',
      next: { revalidate: 0 },
    })
  } catch {
    throw new Error('网络请求失败，无法连接到后端服务')
  }

  if (!response.ok) {
    const serverMessage = await extractErrorMessage(response)
    throw new Error(serverMessage || options?.errorMessage || `HTTP ${response.status}`)
  }

  return response.text()
}

/**
 * HR 模块服务端文件下载封装（原 lib/hr/api.ts downloadDocumentBlob 的服务端版）。
 * 返回 base64 内容与响应头 content-disposition 解析出的文件名（无则 null，由调用方给默认名），
 * 客户端再用 downloadBase64File 落地。失败时抛出带中文文案的 Error（含 401/403 特判）。
 */
export async function fetchHrDownload(
  endpoint: string,
  options?: HrRequestInit
): Promise<{ base64: string; filename: string | null }> {
  const url = `${API_BASE}${endpoint}`
  let response: Response
  try {
    const authHeaders = await getAuthHeaders()
    const { headers: optHeaders, errorMessage: _errorMessage, ...restOptions } = options || {}
    const headers: Record<string, string> = { ...authHeaders, ...(optHeaders as Record<string, string> | undefined) }
    if (restOptions.body instanceof FormData) {
      delete headers['Content-Type']
    }
    response = await fetch(url, {
      cache: 'no-store',
      ...restOptions,
      headers,
    })
  } catch {
    throw new Error('网络请求失败，无法连接到后端服务')
  }

  if (!response.ok) {
    let msg = options?.errorMessage || '下载失败'
    let bodyText = ''
    try {
      bodyText = await response.text()
      const d = JSON.parse(bodyText)
      if (typeof d?.message === 'string' && d.message) msg = d.message
      else if (typeof d?.detail === 'string' && d.detail) msg = d.detail
      else if (Array.isArray(d?.detail) && d.detail.length > 0) {
        msg = d.detail.map((e: any) => `${e.loc?.join('.') || ''}: ${e.msg}`).join('; ')
      }
    } catch { /* 非 JSON，用 bodyText 作为日志 */ }
    if (response.status === 401) msg = '请先登录'
    if (response.status === 403) msg = '没有下载权限，请联系管理员配置'
    logApiError(options?.method || 'GET', url, response.status, bodyText || msg)
    throw new Error(msg)
  }

  const buffer = Buffer.from(await response.arrayBuffer())
  const disposition = response.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  const filename = filenameMatch ? decodeURIComponent(filenameMatch[1]) : null
  return { base64: buffer.toString('base64'), filename }
}
