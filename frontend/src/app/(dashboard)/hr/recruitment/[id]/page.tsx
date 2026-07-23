'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'

export default function CandidateDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [candidate, setCandidate] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/v1/hr/candidates/${id}`, { credentials: 'include' })
      .then(r => r.json()).then(d => setCandidate(d.data)).catch(() => setCandidate(null))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="h-64" />
  if (!candidate) return <div className="text-center text-gray-400 py-20">候选人不存在或已被删除</div>
  return <CandidateDetailClient candidate={candidate} />
}
