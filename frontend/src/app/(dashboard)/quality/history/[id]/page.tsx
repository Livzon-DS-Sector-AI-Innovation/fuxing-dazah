'use client'

import { useEffect, useState, use } from 'react'
import { Spin, App, Button, Space, Card, Descriptions, Table, Typography, Tag } from 'antd'
import { ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { LcReportView } from '@/components/quality'
import type { InspectionRecordDetail } from '@/types/quality'
import { fetchInspectionRecord } from '@/actions/quality'

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
      {detail && detail.source === 'calc_form' && detail.raw_data && (
        <Card size="small" title={<span>在线计算表提交快照 <Tag color="blue">calc_form</Tag></span>} style={{ marginBottom: 16 }}>
          <Descriptions size="small" column={3} style={{ marginBottom: 8 }}>
            <Descriptions.Item label="表号">{String((detail.raw_data as Record<string, unknown>).table_no ?? '-')}</Descriptions.Item>
            <Descriptions.Item label="检验日期">{String((detail.raw_data as Record<string, unknown>).record_date ?? '-')}</Descriptions.Item>
            <Descriptions.Item label="批号">{detail.batch_number}</Descriptions.Item>
          </Descriptions>
          {Boolean(detail.raw_data.computed) && typeof detail.raw_data.computed === 'object' && (
            <Table
              rowKey="std_name" size="small" pagination={false}
              dataSource={(detail.raw_data.computed as { items?: { label: string; value: number | null; nd?: boolean; detail?: string }[] }).items ?? []}
              columns={[
                { title: '项目', dataIndex: 'label', width: 180 },
                { title: '计算结果', dataIndex: 'value', width: 120, render: (v: number | null, r: { nd?: boolean }) => v != null ? <Typography.Text strong>{v.toFixed(4)}{r.nd ? '（未检出）' : ''}</Typography.Text> : '-' },
                { title: '明细', dataIndex: 'detail', ellipsis: true },
              ]}
            />
          )}
        </Card>
      )}
      {detail && <LcReportView report={detail.report} />}
    </div>
  )
}
