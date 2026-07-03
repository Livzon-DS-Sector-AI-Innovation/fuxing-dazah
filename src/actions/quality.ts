'use server'

import { revalidatePath } from 'next/cache'
import { getServerToken, getImpersonateToken } from '@/lib/auth'
import type { UploadLcResponse } from '@/types/quality'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

/**
 * 上传液相计算表 Excel 并获取解析结果。
 * 使用 FormData 传输文件，不能设 Content-Type（让浏览器自动处理 boundary）。
 */
export async function uploadLcExcel(formData: FormData): Promise<UploadLcResponse> {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()

  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`

  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || (err as any).message || '上传解析失败')
  }

  revalidatePath('/quality')
  return res.json()
}
