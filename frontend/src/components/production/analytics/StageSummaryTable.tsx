'use client'

import { useMemo, useState } from 'react'
import { Alert, Empty, Select, Space, Switch, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchStageSummaryClient } from '@/lib/api/production-client'
import type { StageSummaryRow } from '@/types/production'
import { RouteSelect, useRouteGraph } from './RouteSelect'

const { Text } = Typography

function renderValue(v: unknown) {
  if (v == null) return <Text type="secondary">—</Text>
  if (typeof v === 'boolean') return <Text>{v ? '是' : '否'}</Text>
  return <Text>{String(v)}</Text>
}

export function StageSummaryTable() {
  const [routeId, setRouteId] = useState<string | undefined>()
  const [stageName, setStageName] = useState<string | undefined>()
  const [viewAll, setViewAll] = useState(false)

  const graph = useRouteGraph('summary', routeId)

  const stageOptions = useMemo(
    () => [...new Set((graph?.nodes ?? []).map(n => n.stage_name).filter(Boolean) as string[])],
    [graph],
  )

  const { data: summary, isLoading, error } = useQuery({
    queryKey: ['production-stage-summary', { routeId, stageName, viewAll }],
    queryFn: () => fetchStageSummaryClient({ route_id: routeId, stage_name: stageName, view_all: viewAll }),
  })

  const columns: TableColumnsType<StageSummaryRow> = useMemo(() => {
    const base: TableColumnsType<StageSummaryRow> = [
      {
        title: '批次号',
        dataIndex: 'batch_no',
        fixed: 'left',
        width: 150,
        render: (v: string) => <Text strong style={{ fontSize: 13 }}>{v}</Text>,
      },
    ]
    const rest: TableColumnsType<StageSummaryRow> = (summary?.columns ?? []).map(c => ({
      title: c.unit ? `${c.node_name}.${c.field_label}（${c.unit}）` : `${c.node_name}.${c.field_label}`,
      // 数组形式 dataIndex 才会按路径逐级取值；字符串会被当作整键字面量
      dataIndex: c.kind === 'field' ? ['values', c.col_key] : ['computed', c.col_key],
      width: 130,
      render: (v: unknown) => renderValue(v),
    }))
    return [...base, ...rest]
  }, [summary])

  const isEmpty = !isLoading && !error && (summary?.columns.length ?? 0) === 0

  return (
    <div style={{ background: '#ffffff', borderRadius: 12, border: '1px solid #e5e3df', padding: 24 }}>
      <Space wrap style={{ marginBottom: 16 }}>
        <RouteSelect
          placeholder="全部路线"
          style={{ width: 220 }}
          value={routeId}
          onChange={v => { setRouteId(v); setStageName(undefined) }}
        />
        <Select
          allowClear
          showSearch={{ optionFilterProp: 'label' }}
          placeholder="全部工段"
          style={{ width: 160 }}
          value={stageName}
          onChange={setStageName}
          disabled={!routeId || stageOptions.length === 0}
          options={stageOptions.map(s => ({ label: s, value: s }))}
        />
        <Space size={6}>
          <Switch checked={viewAll} onChange={setViewAll} />
          <Text type="secondary">查看全部批次</Text>
        </Space>
      </Space>

      {error && (
        <Alert
          title={error instanceof Error ? error.message : '获取工段汇总数据失败，请稍后重试'}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {isEmpty ? (
        <Empty
          description="暂无汇总数据"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ padding: '48px 0' }}
        />
      ) : (
        <Table
          columns={columns}
          dataSource={summary?.rows ?? []}
          rowKey="batch_id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      )}
    </div>
  )
}
