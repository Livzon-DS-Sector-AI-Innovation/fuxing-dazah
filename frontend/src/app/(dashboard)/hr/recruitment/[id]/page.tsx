'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'
import { fetchCandidateById } from '@/actions/hr'
import { Alert } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

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
  return (
    <PermissionGuard
      permission="hr:recruitment:read"
      fallback={<Alert type="warning" showIcon message="您没有招聘管理的查看权限，请联系管理员赋权。" />}
    >
      <CandidateDetailClient candidate={candidate} />
    </PermissionGuard>
  )
}
