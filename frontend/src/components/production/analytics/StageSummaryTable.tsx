'use client'

import { useMemo, useState } from 'react'
import { Alert, Empty, Select, Space, Switch, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchStageSummaryClient } from '@/lib/api/production-client'
import type { StageSummaryRow } from '@/types/production'
import { RouteSelect, useProductRoutes, useRouteGraph } from './RouteSelect'
import { useDateRangeState } from './useDateRange'

const { Text } = Typography

// 批次号自然排序（识别嵌入的数字段，避免 "2" 排在 "10" 后）
const batchNoCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

function renderValue(v: unknown) {
  if (v == null) return <Text type="secondary">—</Text>
  if (typeof v === 'boolean') return <Text>{v ? '是' : '否'}</Text>
  return <Text>{String(v)}</Text>
}

export function StageSummaryTable({
  productId,
}: {
  productId: string
}) {
  const [routeId, setRouteId] = useState<string | undefined>()
  const [stageName, setStageName] = useState<string | undefined>()
  const [viewAll, setViewAll] = useState(false)
  // 批次首次开始日期范围 ['YYYY-MM-DD', 'YYYY-MM-DD']；null=不限
  const { dateRange, picker } = useDateRangeState()

  const { routes, isLoading: routesLoading } = useProductRoutes(productId)

  // 默认选中该产品下第一条（优先 published）路线，保证矩阵始终按产品作用域展示
  const effectiveRouteId = useMemo(() => {
    if (routeId && routes.some(r => r.id === routeId)) return routeId
    return routes.find(r => r.status === 'published')?.id ?? routes[0]?.id
  }, [routeId, routes])

  const graph = useRouteGraph('summary', effectiveRouteId)

  const stageOptions = useMemo(
    () => [...new Set((graph?.nodes ?? []).map(n => n.stage_name).filter(Boolean) as string[])],
    [graph],
  )

  const { data: summary, isLoading, error } = useQuery({
    queryKey: ['production-stage-summary', { routeId: effectiveRouteId, stageName, viewAll, dateRange }],
    queryFn: () => fetchStageSummaryClient({
      route_id: effectiveRouteId,
      stage_name: stageName,
      view_all: viewAll,
      start_date: dateRange?.[0] ?? undefined,
      end_date: dateRange?.[1] ?? undefined,
    }),
    enabled: !!effectiveRouteId,
  })

  const columns: TableColumnsType<StageSummaryRow> = useMemo(() => {
    const base: TableColumnsType<StageSummaryRow> = [
      {
        title: '批次号',
        dataIndex: 'batch_no',
        fixed: 'left',
        width: 150,
        sorter: (a, b) => batchNoCollator.compare(a.batch_no, b.batch_no),
        render: (v: string) => <Text strong style={{ fontSize: 13 }}>{v}</Text>,
      },
    ]
    const cols = summary?.columns ?? []
    // 工序作一级表头：按节点 id 分组（不同路线同名工序不能合并），
    // 同工序的字段列与计算列归入同一组，组顺序按首现顺序排列（Map 保序）
    const groups = new Map<string, { title: string; children: TableColumnsType<StageSummaryRow> }>()
    for (const c of cols) {
      let group = groups.get(c.node_id)
      if (!group) {
        group = { title: c.node_name, children: [] }
        groups.set(c.node_id, group)
      }
      group.children.push({
        title: c.unit ? `${c.field_label}（${c.unit}）` : c.field_label,
        // 数组形式 dataIndex 才会按路径逐级取值；字符串会被当作整键字面量
        dataIndex: c.kind === 'field' ? ['values', c.col_key] : ['computed', c.col_key],
        width: 130,
        render: (v: unknown) => renderValue(v),
      })
    }
    return [...base, ...[...groups.values()].map(g => ({ title: g.title, children: g.children }))]
  }, [summary])

  // 该产品还没有工艺路线（路线加载完成后再判定，避免加载中闪现空态）
  const noRoute = !routesLoading && routes.length === 0
  const isEmpty = !isLoading && !error && (summary?.columns.length ?? 0) === 0

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <RouteSelect
          placeholder="选择路线"
          style={{ width: 220 }}
          productId={productId}
          value={effectiveRouteId}
          onChange={v => { setRouteId(v); setStageName(undefined) }}
        />
        <Select
          allowClear
          showSearch={{ optionFilterProp: 'label' }}
          placeholder="全部工段"
          style={{ width: 160 }}
          value={stageName}
          onChange={setStageName}
          disabled={!effectiveRouteId || stageOptions.length === 0}
          options={stageOptions.map(s => ({ label: s, value: s }))}
        />
        <Space size={6}>
          <Switch checked={viewAll} onChange={setViewAll} />
          <Text type="secondary">查看全部工序</Text>
        </Space>
        {picker}
      </Space>

      {error && (
        <Alert
          title={error instanceof Error ? error.message : '获取工段汇总数据失败，请稍后重试'}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {noRoute ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="该产品还没有工艺路线"
          style={{ padding: '48px 0' }}
        />
      ) : isEmpty ? (
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
          bordered
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      )}
    </div>
  )
}
