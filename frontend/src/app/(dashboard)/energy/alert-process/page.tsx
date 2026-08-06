'use client'

import { useState, useEffect, useCallback } from 'react'
import { Button, Space, App, Select } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { AlertRecord, EnergyTypeMeta } from '@/types/energy'
import { getAlertProcessList, getEnabledTypeConfigs } from '@/actions/energy'
import { AlertProcessTable } from '@/components/energy'

export default function AlertProcessPage() {
  const { message } = App.useApp()

  const [records, setRecords] = useState<AlertRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)

  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])

  useEffect(() => {
    getEnabledTypeConfigs().then(configs => {
      setTypeMetadata(configs.map(c => ({
        type_code: c.type_code,
        display_name: c.display_name,
        unit: c.unit,
        color: c.color,
        icon: c.icon,
      })))
    }).catch(() => {})
  }, [])

  const fetchRecords = useCallback(async (p = page, ps = pageSize) => {
    setLoading(true)
    try {
      const result = await getAlertProcessList({
        status: statusFilter,
        page: p,
        page_size: ps,
      })
      setRecords(result.items)
      setTotal(result.total)
    } catch {
      message.error('获取预警处理列表失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter])

  useEffect(() => {
    fetchRecords()
  }, [fetchRecords])

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.3, margin: '0 0 20px' }}>
        预警处理
      </h1>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Select
            placeholder="筛选状态"
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1) }}
            allowClear
            style={{ width: 140 }}
            options={[
              { label: '待处理', value: 'pending' },
              { label: '已驳回', value: 'rejected' },
            ]}
          />
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchRecords()}>
            刷新
          </Button>
        </Space>
      </div>

      <AlertProcessTable
        data={records}
        loading={loading}
        total={total}
        page={page}
        pageSize={pageSize}
        onPageChange={(p, ps) => { setPage(p); setPageSize(ps) }}
        onRefresh={() => fetchRecords()}
        typeMetadata={typeMetadata}
      />
    </div>
  )
}
