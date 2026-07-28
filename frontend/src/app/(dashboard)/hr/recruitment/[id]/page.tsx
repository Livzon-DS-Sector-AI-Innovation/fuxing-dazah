'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import CandidateDetailClient from '@/components/hr/CandidateDetailClient'

/** 安全的 JSON fetch */
async function safeFetch(url: string, init?: RequestInit): Promise<any> {
  let r: Response
  try { r = await fetch(url, init) }
  catch { throw new Error('无法连接后端服务，请确认后端已启动') }
  const text = await r.text()
  if (!r.ok) {
    let errMsg = `HTTP ${r.status}`
    try { const body = JSON.parse(text); if (body.message) errMsg = body.message }
    catch { errMsg += `: ${text.slice(0, 200)}` }
    throw new Error(errMsg)
  }
  try { return JSON.parse(text) }
  catch { throw new Error(`服务器返回非JSON响应: ${text.slice(0, 200)}`) }
}

export default function CandidateDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [candidate, setCandidate] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    safeFetch(`/api/v1/hr/candidates/${id}`, { credentials: 'include' })
      .then(d => setCandidate(d.data))
      .catch((err: any) => setError(err.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="h-64" />
  if (!candidate) return <div className="text-center text-gray-400 py-20">{error || '候选人不存在或已被删除'}</div>
  return <CandidateDetailClient candidate={candidate} />
}
