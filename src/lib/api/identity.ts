'use client'

import { apiGet } from '@/lib/http-client'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export interface IdentityPersonnel {
  id: string
  name: string
  employee_no: string | null
  department: string | null
  avatar_url: string | null
}

// ponytail: shared helper, same pattern as qs() in production-client — extract if used in 3+ files
function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
  }
  return sp.toString()
}

export async function fetchIdentityPersonnel(params?: {
  keyword?: string
  offset?: number
  limit?: number
}): Promise<{ items: IdentityPersonnel[]; total: number }> {
  const s = qs({
    keyword: params?.keyword ?? null,
    offset: params?.offset ?? 0,
    limit: params?.limit ?? 9999,
  })
  return apiGet(`${API_BASE}/api/v1/identity/personnel?${s}`)
}
