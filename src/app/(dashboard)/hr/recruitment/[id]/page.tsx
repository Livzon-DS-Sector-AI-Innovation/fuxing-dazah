import { fetchCandidateById } from '@/lib/api/hr'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'

interface CandidateDetailPageProps {
  params: Promise<{ id: string }>
}

export default async function CandidateDetailPage({ params }: CandidateDetailPageProps) {
  const { id } = await params
  const res = await fetchCandidateById(id)

  return <CandidateDetailClient candidate={res.data} />
}
