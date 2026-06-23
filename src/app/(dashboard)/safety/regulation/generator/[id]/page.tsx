'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Spin, Result, Button } from 'antd'
import SopContentEditor from '@/components/safety/SopContentEditor'
import { getRegulation } from '@/actions/safety'
import type { OperationRegulation } from '@/types/safety'

export default function SopDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [regData, setRegData] = useState<{
    regulationId: string
    regulationName: string
    content: string
  } | null>(null)

  const fetchRegulation = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await getRegulation(id)
      if (response.code === 200 && response.data) {
        const data = response.data as OperationRegulation
        setRegData({
          regulationId: data.id,
          regulationName: data.regulation_name || '标准化操规',
          content: data.content || '',
        })
      } else {
        setError(response.message || '未找到该操规记录')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchRegulation()
  }, [fetchRegulation])

  const handleBack = useCallback(() => {
    router.push('/safety/regulation/generator')
  }, [router])

  const handleSaved = useCallback(() => {
    // Content saved; no additional action needed
  }, [])

  /* ── loading ── */
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '80vh' }}>
        <Spin size="large" tip="加载操规内容..." />
      </div>
    )
  }

  /* ── error ── */
  if (error || !regData) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '80vh' }}>
        <Result
          status="error"
          title="加载失败"
          subTitle={error || '未找到该操规记录'}
          extra={[
            <Button key="back" onClick={handleBack}>返回列表</Button>,
            <Button key="retry" type="primary" onClick={fetchRegulation}>重新加载</Button>,
          ]}
        />
      </div>
    )
  }

  /* ── editor ── */
  return (
    <div style={{
      position: 'absolute',
      top: 0, left: 0, right: 0, bottom: 0,
    }}>
      <SopContentEditor
        regulationId={regData.regulationId}
        regulationName={regData.regulationName}
        content={regData.content}
        onBack={handleBack}
        onSaved={handleSaved}
      />
    </div>
  )
}
