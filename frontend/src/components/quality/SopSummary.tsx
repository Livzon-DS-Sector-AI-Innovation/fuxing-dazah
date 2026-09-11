'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card, Table, Tag, Select, App, Typography, Space, Input } from 'antd'
import { FileSearchOutlined, FormOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import type { SopSummaryItem, SopSummaryBatch } from '@/types/quality'
import { fetchTaskSopSummary } from '@/actions/quality'

const { Text } = Typography

export default function SopSummary() {
  const router = useRouter()
  const { message } = App.useApp()
  const [items, setItems] = useState<SopSummaryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [productSearch, setProductSearch] = useState('')
  const [selected, setSelected] = useState<string | undefined>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchTaskSopSummary(productSearch || undefined)
      setItems(data)
      if (!selected || !data.some((i) => keyOf(i) === selected)) {
        setSelected(data[0] ? keyOf(data[0]) : undefined)
      }
    } catch (err: any) {
      message.error(err.message || '加载按 SOP 汇总失败')
    } finally {
      setLoading(false)
    }
  }, [productSearch, message, selected])

  useEffect(() => { load() }, [load])

  const keyOf = (i: SopSummaryItem) => `${i.sop_no || '无SOP号'}__${i.item_name}`
  const current = items.find((i) => keyOf(i) === selected)

  const columns = [
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 130 },
    { title: '生产日期', dataIndex: 'production_date', key: 'production_date', width: 110, render: (v: string | null) => v || '-' },
    { title: '效期', dataIndex: 'expiry_date', key: 'expiry_date', width: 110, render: (v: string | null) => v || '-' },
    {
      title: '结果', key: 'result', width: 140,
      render: (_: any, b: SopSummaryBatch) => b.result_value != null ? b.result_value : (b.result_text || '-'),
    },
    {
      title: '判定', dataIndex: 'is_pass', key: 'is_pass', width: 80,
      render: (v: boolean) => v ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>,
    },
    {
      title: '来源', dataIndex: 'source', key: 'source', width: 80,
      render: (v: SopSummaryBatch['source']) => v === 'parse' ? <Tag color="blue">解析</Tag> : <Tag>手工</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, b: SopSummaryBatch) => (
        <a onClick={() => router.push(`/quality/task/${b.task_id}`)}><FormOutlined /> 查看任务</a>
      ),
    },
  ]

  return (
    <Card size="small" title={<><FileSearchOutlined /> 按 SOP 汇总（以 SOP 为索引，看各项目跨批次结果）</>}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="按产品名过滤"
          allowClear
          value={productSearch}
          onChange={(e) => setProductSearch(e.target.value)}
          onSearch={() => load()}
          style={{ width: 220 }}
        />
        <Select
          showSearch
          optionFilterProp="label"
          style={{ width: 320 }}
          placeholder="选择 SOP 项目"
          value={selected}
          onChange={setSelected}
          options={items.map((i) => ({
            label: `${i.sop_no || '无SOP号'} ${i.item_name}`,
            value: keyOf(i),
          }))}
        />
        {current && (
          <Text type="secondary">
            标准：{current.standard_text || '-'}（{current.operator || ''} {current.limit_min ?? ''}{current.limit_max ?? ''}）；共 {current.batches.length} 批
          </Text>
        )}
      </Space>

      <Table
        rowKey={(r) => `${r.task_id}_${r.batch_number}`}
        size="small"
        loading={loading}
        columns={columns}
        dataSource={current?.batches || []}
        pagination={false}
      />
    </Card>
  )
}
