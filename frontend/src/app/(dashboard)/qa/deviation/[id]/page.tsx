import { DeviationDetailPage } from '@/components/qa'

export const dynamic = 'force-dynamic'

export default async function QaDeviationDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <DeviationDetailPage id={id} />
}
