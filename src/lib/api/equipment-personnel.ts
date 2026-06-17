import type {
  EquipmentRole, Personnel, PersonnelListResponse, Candidate,
} from '@/types/equipment-personnel'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const data = await response.json()
  return data.data
}

// ── 角色 API ──

export async function fetchRoles(): Promise<EquipmentRole[]> {
  return apiFetch<EquipmentRole[]>(
    `${API_BASE_URL}/api/v1/equipment/personnel/roles?page_size=500`
  )
}

export async function fetchRole(id: string): Promise<EquipmentRole> {
  return apiFetch<EquipmentRole>(
    `${API_BASE_URL}/api/v1/equipment/personnel/roles/${id}`
  )
}

// ── 人员 API ──

async function apiFetchPaginated(url: string, options?: RequestInit) {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return {
    items: (result.data ?? []) as Personnel[],
    total: (result.meta?.total ?? 0) as number,
    page: (result.meta?.page ?? 1) as number,
    page_size: (result.meta?.page_size ?? 20) as number,
  }
}

export async function fetchPersonnelList(params?: {
  role_id?: string[]
  is_active?: boolean
  keyword?: string
  page?: number
  page_size?: number
}): Promise<PersonnelListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.role_id?.length) {
    params.role_id.forEach(rid => searchParams.append('role_id', rid))
  }
  if (params?.is_active !== undefined) {
    searchParams.set('is_active', String(params.is_active))
  }
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  const qs = searchParams.toString()
  return apiFetchPaginated(
    `${API_BASE_URL}/api/v1/equipment/personnel${qs ? `?${qs}` : ''}`
  )
}

export async function fetchPersonnel(id: string): Promise<Personnel> {
  return apiFetch<Personnel>(
    `${API_BASE_URL}/api/v1/equipment/personnel/${id}`
  )
}

export async function fetchCandidates(
  roleCodes: string[],
  categoryId?: string,
): Promise<Candidate[]> {
  const params = new URLSearchParams()
  roleCodes.forEach(rc => params.append('role_codes', rc))
  if (categoryId) params.set('category_id', categoryId)
  return apiFetch<Candidate[]>(
    `${API_BASE_URL}/api/v1/equipment/personnel/candidates?${params.toString()}`
  )
}
