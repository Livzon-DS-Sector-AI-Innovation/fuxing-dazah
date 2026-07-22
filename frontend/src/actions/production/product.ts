'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type { CreateProductInput, Product, UpdateProductInput } from '@/types/production'

export async function createProduct(input: CreateProductInput): Promise<ActionResult<Product>> {
  const result = await actionFetch<Product>(`${API_BASE}/production/products`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function updateProduct(
  id: string,
  input: UpdateProductInput,
): Promise<ActionResult<Product>> {
  const result = await actionFetch<Product>(`${API_BASE}/production/products/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function deleteProduct(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE}/production/products/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/production/process')
  return result
}
