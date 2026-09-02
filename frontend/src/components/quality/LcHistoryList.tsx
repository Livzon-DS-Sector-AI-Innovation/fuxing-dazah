'use client'

import { useState, useEffect, useCallback } from 'react'
import { Table, Tag, Input, Space, Button, App, Typography } from 'antd'
import { SearchOutlined, DeleteOutlined, EyeOutlined, ExperimentOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import type { InspectionRecordListItem } from '@/types/quality'
import { fetchInspectionRecords, deleteInspectionRecord } from '@/actions/quality'

const { Text } = Typography

export default function LcHistoryList() {
  const router = useRouter()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<InspectionRecordListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [productSearch, setProductSearch] = useState('')
  const [batchSearch, setBatchSearch] = useState('')

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await fetchInspectionRecords(
        productSearch || undefined,
        batchSearch || undefined,
        p,
      )
      setData(res.data)
      setTotal(res.meta.total)
    } catch {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }, [productSearch, batchSearch, message])

  useEffect(() => { load(page) }, [page, load])

  const handleDelete = async (id: string) => {
    try {
      await deleteInspectionRecord(id)
      message.success('已删除')
      load(page)
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', width: 180 },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 120 },
    { title: '标准', dataIndex: 'standard_type', key: 'standard_type', width: 70,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    {
      title: '判定', dataIndex: 'all_pass', key: 'all_pass', width: 80,
      render: (v: boolean) => v
        ? <Tag color="success">合格</Tag>
        : <Tag color="error">不合格</Tag>,
    },
    {
      render: (v: boolean) => v ? <Tag color="warning">OOT</Tag> : null,
    },
    { title: '文件名', dataIndex: 'excel_filename', key: 'excel_filename', ellipsis: true },
    {
      title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: any, r: InspectionRecordListItem) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />}
            onClick={() => router.push(`/quality/history/${r.id}`)}>
            详情
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDelete(r.id)} />
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="产品名称" allowClear value={productSearch}
          onChange={e => setProductSearch(e.target.value)}
          onPressEnter={() => { setPage(1); load(1) }}
          style={{ width: 150 }} prefix={<SearchOutlined />} />
        <Input placeholder="批号" allowClear value={batchSearch}
          onChange={e => setBatchSearch(e.target.value)}
          onPressEnter={() => { setPage(1); load(1) }}
          style={{ width: 150 }} prefix={<ExperimentOutlined />} />
        <Button type="primary" onClick={() => { setPage(1); load(1) }}>搜索</Button>
      </Space>

      <Table
        columns={columns}
        dataSource={data.map(r => ({ ...r, key: r.id }))}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small"
      />
    </div>
  )
}
