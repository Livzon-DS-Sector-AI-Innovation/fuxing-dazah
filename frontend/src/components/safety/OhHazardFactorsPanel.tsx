'use client'

// 危害因素 PPE 映射字典 Panel（OhHazardFactorsPanel）— 只读台账，无 Drawer
// StatCard 统计行（字典条数/已覆盖标准名/未覆盖标准名/已维护 PPE）→ keyword 客户端过滤（后端无筛选参数）
// 顶部 Alert info：本表为人工维护映射字典，AI 差异分析从此取值。
// 数据量小（42 项字典）：page_size=200 全量拉取 + 客户端过滤/分页。

import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Input,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { fetchOhHazardFactors } from '@/lib/api/safety/occupational-health'
import type { OhHazardFactor } from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard } from '@/components/ui-kit'
import {
  HAZARD_FACTOR_OPTIONS,
  UI,
} from './ohConstants'

const MAX_FETCH = 200

export default function OhHazardFactorsPanel() {
  const [keyword, setKeyword] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['oh-hazard-factors'],
    queryFn: () => fetchOhHazardFactors({ page: 1, page_size: MAX_FETCH }),
  })

  const rows = useMemo(() => data ?? [], [data])
  const total = rows.length

  const kpi = useMemo(() => {
    const covered = rows.filter((r) => HAZARD_FACTOR_OPTIONS.includes(r.factor_name)).length
    const withPpe = rows.filter((r) => r.ppe_respiratory).length
    return {
      total,
      covered,
      uncovered: Math.max(HAZARD_FACTOR_OPTIONS.length - covered, 0),
      withPpe,
    }
  }, [rows, total])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return rows
    return rows.filter((r) =>
      (r.factor_name ?? '').toLowerCase().includes(kw) ||
      (r.ppe_respiratory ?? '').toLowerCase().includes(kw)
    )
  }, [rows, keyword])

  const columns: ColumnsType<OhHazardFactor> = useMemo(() => [
    {
      title: '危害因素标准名', dataIndex: 'factor_name', key: 'factor_name', width: 260,
      render: (v: string) => (
        <Tag color="purple" style={{ marginInlineEnd: 0 }}>{v}</Tag>
      ),
    },
    {
      title: '呼吸防护用品', dataIndex: 'ppe_respiratory', key: 'ppe_respiratory',
      render: (v: string) => v
        ? <span style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{v}</span>
        : <span style={{ color: UI.muted, fontSize: 13 }}>未维护</span>,
    },
    {
      title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 130,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-'),
    },
  ], [])

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（字典全量派生） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="字典条数" value={kpi.total ?? '-'} sub="PPE 映射字典" />
        <StatCard label="已覆盖标准名" value={kpi.covered} sub="与 42 项标准字典匹配" />
        <StatCard label="未覆盖标准名" value={kpi.uncovered} sub={`42 项标准缺口 ${kpi.uncovered} 项`} />
        <StatCard label="已维护 PPE" value={kpi.withPpe} sub="呼吸防护用品非空" />
      </div>

      <SectionCard
        title="危害因素 PPE 字典"
        description={`人工维护映射字典（共 ${total} 条），AI 差异分析从此取值`}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="本表为人工维护映射字典，AI 差异分析从此取值"
        />
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="危害因素名称/防护用品" value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 240 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={() => refetch()} size="small" /></Tooltip>
        </div>

        <Table<OhHazardFactor>
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 760 }}
          locale={{ emptyText: <EmptyGuide compact title="暂无危害因素 PPE 字典" description="字典由 Bitable 同步维护，稍后刷新查看" /> }}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </SectionCard>
    </div>
  )
}
