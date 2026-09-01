'use client'

import { useState } from 'react'
import { Card, Button, Select, Space, Typography, App, Descriptions } from 'antd'
import { FileTextOutlined, DownloadOutlined } from '@ant-design/icons'
import type { InspectionRecordListItem } from '@/types/quality'
import { generateReport } from '@/actions/quality'

const { Text, Title } = Typography

interface Props {
  record: InspectionRecordListItem
  templates: { value: string; label: string }[]
}

export default function ReportGenerator({ record, templates }: Props) {
  const { message } = App.useApp()
  const [template, setTemplate] = useState(templates[0]?.value || '万古霉素/3205.docx')
  const [generating, setGenerating] = useState(false)

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await generateReport(record.id, template)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const disposition = res.headers.get('Content-Disposition') || ''
      const match = disposition.match(/filename=(.+)/)
      a.download = match ? match[1] : `COA-${record.batch_number}.docx`
      a.click()
      URL.revokeObjectURL(url)
      message.success('报告单已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <Card size="small" title={<><FileTextOutlined /> 生成 COA 报告单</>}>
      <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="产品">{record.product_name}</Descriptions.Item>
        <Descriptions.Item label="批号">{record.batch_number}</Descriptions.Item>
        <Descriptions.Item label="模板">
          <Select
            value={template}
            onChange={setTemplate}
            options={templates}
            style={{ width: 220 }}
            size="small"
          />
        </Descriptions.Item>
        <Descriptions.Item label="操作">
          <Button type="primary" icon={<DownloadOutlined />}
            loading={generating} onClick={handleGenerate}>
            生成并下载
          </Button>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}
