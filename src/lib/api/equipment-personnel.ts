import type {
  EquipmentRole, Personnel, PersonnelListResponse, Candidate,
} from '@/types/equipment-personnel'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

// ── 角色 API ──

export async function fetchRoles(): Promise<EquipmentRole[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/personnel/roles?page_size=500`)
}

export async function fetchRole(id: string): Promise<EquipmentRole> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/personnel/roles/${id}`)
}

// ── 人员 API ──

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
  if (params?.is_active !== undefined) searchParams.set('is_active', String(params.is_active))
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  const qs = searchParams.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/personnel${qs ? `?${qs}` : ''}`)
}

export async function fetchPersonnel(id: string): Promise<Personnel> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/personnel/${id}`)
}

export async function fetchCandidates(
  roleCodes: string[],
  categoryId?: string,
): Promise<Candidate[]> {
  const params = new URLSearchParams()
  roleCodes.forEach(rc => params.append('role_codes', rc))
  if (categoryId) params.set('category_id', categoryId)
  return apiGet(`${API_BASE_URL}/api/v1/equipment/personnel/candidates?${params.toString()}`)
}
