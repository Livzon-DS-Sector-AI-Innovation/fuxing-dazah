'use client'

import { useEffect, useState, use } from 'react'
import { Typography, Spin, App, Button, Space } from 'antd'
import { ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { LcReportView } from '@/components/quality'
import type { InspectionRecordDetail } from '@/types/quality'
import { fetchInspectionRecord } from '@/actions/quality'

const { Title } = Typography

export default function RecordDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<InspectionRecordDetail | null>(null)

  useEffect(() => {
    fetchInspectionRecord(id)
      .then(setDetail)
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [id, message])

  if (loading) return <Spin size="large" style={{ marginTop: 100 }} />

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()}>返回</Button>
        <Button type="primary" icon={<FileTextOutlined />}
          onClick={() => router.push(`/quality/report?recordId=${id}`)}>
          生成报告单
        </Button>
      </Space>
      {detail && <LcReportView report={detail.report} />}
    </div>
  )
}
