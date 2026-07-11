'use client'

import { apiGet } from '@/lib/http-client'
import type {
  TrendResponse,
  TrendQuery,
  AnomalyResponse,
  AnomalyQuery,
  EquipmentListResponse,
} from '@/types/equipment/inspection-analytics'

const BASE = `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/equipment/inspection/analytics`

function qs(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') sp.set(k, v)
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export async function fetchTrend(query: TrendQuery): Promise<TrendResponse> {
  return apiGet<TrendResponse>(`${BASE}/trend${qs({
    equipment_id: query.equipment_id,
    item_ids: query.item_ids.join(','),
    from_date: query.from_date,
    to_date: query.to_date,
  })}`)
}

export async function fetchAnomaly(query: AnomalyQuery = {}): Promise<AnomalyResponse> {
  return apiGet<AnomalyResponse>(`${BASE}/anomaly${qs({
    from_date: query.from_date,
    to_date: query.to_date,
  })}`)
}

export async function fetchEquipmentList(keyword?: string): Promise<EquipmentListResponse> {
  return apiGet<EquipmentListResponse>(`${BASE}/equipment-list${qs({ keyword })}`)
}
