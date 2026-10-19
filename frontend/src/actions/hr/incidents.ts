'use server'

import type { IncidentRecord } from '@/types/hr'
import { fetchHrApi } from './_helpers'

export async function fetchIncidents(type?: string, year?: number): Promise<{ data: IncidentRecord[] }> {
  const params = new URLSearchParams()
  if (type) params.set('incident_type', type)
  if (year) params.set('year', String(year))
  const qs = params.toString() ? `?${params}` : ''
  return fetchHrApi(`/hr/incidents${qs}`, { errorMessage: '获取台账失败' })
}

export async function createIncident(input: Partial<IncidentRecord>): Promise<{ message: string; data: { id: string } }> {
  return fetchHrApi('/hr/incidents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    errorMessage: '新增失败',
  })
}

export async function updateIncident(id: string, input: Partial<IncidentRecord>): Promise<{ message: string }> {
  return fetchHrApi(`/hr/incidents/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    errorMessage: '更新失败',
  })
}

export async function deleteIncident(id: string): Promise<{ message: string }> {
  return fetchHrApi(`/hr/incidents/${id}`, { method: 'DELETE', errorMessage: '删除失败' })
}
