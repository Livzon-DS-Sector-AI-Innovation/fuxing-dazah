import { getAuthHeaders } from '@/lib/auth'
import type { Product } from '@/types/production'

const API_BASE = process.env.API_BASE_URL
  ? `${process.env.API_BASE_URL}/api/v1`
  : 'http://localhost:8000/api/v1'

export async function fetchProducts(): Promise<Product[]> {
  try {
    const headers = await getAuthHeaders()
    const res = await fetch(`${API_BASE}/production/products?page=1&page_size=100`, {
      headers,
      cache: 'no-store',
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      let msg = `获取产品列表失败: ${res.status}`
      try { msg = JSON.parse(body).message || msg } catch { /* not JSON */ }
      throw new Error(msg)
    }
    const json = await res.json()
    return json.data ?? []
  } catch (e) {
    console.error('fetchProducts error:', e)
    throw e
  }
}
