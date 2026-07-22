import { fetchProducts } from '@/lib/api/production'
import { BatchesPage } from '@/components/production'

export const dynamic = 'force-dynamic'

export default async function Page() {
  const products = await fetchProducts()
  return <BatchesPage initialProducts={products} />
}
