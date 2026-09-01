'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Table, Tag, Input, Space, App, Button } from 'antd'
import { FileTextOutlined, DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ReportRecord } from '@/types/quality'
import { fetchReportRecords } from '@/actions/quality'

const { Title, Paragraph } = Typography

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export default function ReportPage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ReportRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await fetchReportRecords(search || undefined, undefined, p)
      setData(res.data)
      setTotal(res.meta.total)
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }, [search, message])

  useEffect(() => { load(page) }, [page, load])

  const handleDownload = (reportId: string) => {
    window.open(`${API_BASE_URL}/api/v1/quality/report/records/${reportId}/download`, '_blank')
  }

  const columns = [
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 150 },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 120 },
    { title: '模板', dataIndex: 'template_path', key: 'template_path', ellipsis: true },
    { title: '文件大小', dataIndex: 'file_size', key: 'file_size', width: 100,
      render: (v: number) => v ? `${(v / 1024).toFixed(1)} KB` : '-' },
    { title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '操作', key: 'actions', width: 100,
      render: (_: any, r: ReportRecord) => (
        <Button size="small" icon={<DownloadOutlined />}
          onClick={() => handleDownload(r.id)} disabled={!r.file_path}>
          下载
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Title level={3}><FileTextOutlined /> COA 报告单</Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        管理已生成的检验报告单（COA），支持下载历史报告。
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="搜索产品名称" allowClear value={search}
          onChange={e => setSearch(e.target.value)}
          onPressEnter={() => { setPage(1); load(1) }}
          style={{ width: 200 }} prefix={<SearchOutlined />} />
        <Button type="primary" onClick={() => { setPage(1); load(1) }}>搜索</Button>
      </Space>

      <Table columns={columns}
        dataSource={data.map(r => ({ ...r, key: r.id }))}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small" />
    </div>
  )
}
