'use client'

import { useState, useEffect } from 'react'
import { Button, Space, Select } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { EnergyTypeMeta } from '@/types/energy'
import { getAlertProcessList, getEnabledTypeConfigs } from '@/actions/energy'
import { usePagedList } from '@/lib/energy/usePagedList'
import { AlertProcessTable } from './AlertProcessTable'
import { PageHeading } from '@/components/shared/PageHeading'
import { EnergyPageFrame } from './EnergyPageFrame'
import styles from './EnergyAlerts.module.css'

export function EnergyAlertProcessPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])

  useEffect(() => {
    getEnabledTypeConfigs().then((configs) => setTypeMetadata(configs)).catch(() => {})
  }, [])

  const recordsQuery = usePagedList(['energy', 'alert-process', statusFilter, page, pageSize], () => getAlertProcessList({ status: statusFilter, page, page_size: pageSize }), { errorMessage: '获取预警处理列表失败' })
  const records = recordsQuery.data?.items ?? []
  const total = recordsQuery.data?.total ?? 0
  const loading = recordsQuery.isFetching
  const fetchRecords = () => void recordsQuery.refetch()

  return (
    <EnergyPageFrame>
      <PageHeading title="预警处理" subtitle="跟进待处理告警，及时记录处置结果并保留完整追踪信息。" />

      <div className={styles.filters}>
        <Space>
          <span className={styles.statusSummary}>共 {total} 条预警</span>
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
    </EnergyPageFrame>
  )
}
