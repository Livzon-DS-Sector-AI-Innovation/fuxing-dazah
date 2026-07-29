'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'
import { fetchCandidateById } from '@/actions/hr'

export default function CandidateDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [candidate, setCandidate] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetchCandidateById(id)
      .then(d => setCandidate(d.data))
      .catch((err: any) => setError(err.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="h-64" />
  if (!candidate) return <div className="text-center text-gray-400 py-20">{error || '候选人不存在或已被删除'}</div>
  return <CandidateDetailClient candidate={candidate} />
}
