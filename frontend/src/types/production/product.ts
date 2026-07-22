export interface Product {
  id: string
  product_code: string | null
  product_name: string
  unit: string
  remark: string | null
  created_at: string
  updated_at: string
}

export interface CreateProductInput {
  product_code?: string | null
  product_name: string
  unit?: string
  remark?: string | null
}

export interface UpdateProductInput {
  product_name?: string
  unit?: string
  remark?: string | null
}
