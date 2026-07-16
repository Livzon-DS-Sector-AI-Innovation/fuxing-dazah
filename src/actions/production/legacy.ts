'use server'

import { getAuthHeaders } from '@/lib/auth'
import type {
  Batch,
  BatchQueryParams,
  ApiResponse,
} from '@/types/production'

const API_BASE = process.env.API_BASE_URL
  ? `${process.env.API_BASE_URL}/api/v1`
  : 'http://localhost:8000/api/v1'

// ============ Helper Functions ============

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<ApiResponse<T>> {
  const authHeaders = await getAuthHeaders()
  const { headers: optHeaders, ...restOptions } = options || {}
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      ...authHeaders,
      ...optHeaders,
    },
    ...restOptions,
  })
  return response.json()
}

// ============ Batch Actions ============

export async function getBatches(params: BatchQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.product_code) searchParams.set('product_code', params.product_code)
  if (params.batch_no) searchParams.set('batch_no', params.batch_no)

  const queryString = searchParams.toString()
  const endpoint = `/production/batches${queryString ? `?${queryString}` : ''}`
  return fetchApi<Batch[]>(endpoint)
}
