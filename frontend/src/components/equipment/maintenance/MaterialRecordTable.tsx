'use client'

import { useState, useEffect } from 'react'
import { Table, Empty } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { MaterialRecord } from '@/types/equipment'
import { fetchWorkOrderMaterialsClient } from '@/lib/api/equipment-client'

const columns: ColumnsType<MaterialRecord> = [
  {
    title: '备件编码', dataIndex: 'spare_part_code', key: 'spare_part_code', width: 120,
    render: (code: string | undefined) => code || '-',
  },
  {
    title: '备件名称', dataIndex: 'spare_part_name', key: 'spare_part_name', width: 160,
    render: (name: string | undefined) => name || '-',
  },
  {
    title: '数量', dataIndex: 'quantity', key: 'quantity', width: 80,
  },
  {
    title: '单位', dataIndex: 'spare_part_unit', key: 'spare_part_unit', width: 80,
    render: (unit: string | undefined) => unit || '-',
  },
  {
    title: '领用时间', dataIndex: 'created_at', key: 'created_at', width: 160,
    render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
  },
  {
    title: '备注', dataIndex: 'remark', key: 'remark', width: 160,
    render: (remark: string | null) => remark || '-',
  },
]

interface MaterialRecordTableProps {
  workOrderId: string
}

export function MaterialRecordTable({ workOrderId }: MaterialRecordTableProps) {
  const [materials, setMaterials] = useState<MaterialRecord[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const data = await fetchWorkOrderMaterialsClient(workOrderId)
        if (!cancelled) setMaterials(data)
      } catch {
        if (!cancelled) setMaterials([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [workOrderId])

  if (!loading && materials.length === 0) {
    return <Empty description="暂无领料记录" />
  }

  return (
    <Table
      columns={columns} dataSource={materials} rowKey="id" size="small" loading={loading}
      scroll={{ x: 'max-content' }}
      pagination={false}
    />
  )
}
