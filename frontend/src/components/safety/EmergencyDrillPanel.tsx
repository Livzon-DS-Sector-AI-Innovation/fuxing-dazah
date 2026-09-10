'use client'

import { useCallback, useMemo, useState } from 'react'
import {
  App,
  Button,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tooltip,
} from 'antd'
import {
  ReloadOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  AlertOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchDrillRecords, fetchDrillStats } from '@/lib/api/safety/emergency-drill'
import {
  generateDrillPlan,
  createHazardsFromIssues,
} from '@/actions/safety'
import type { DrillRecord } from '@/types/safety'
import DrillDetailDrawer from './DrillDetailDrawer'
import DrillDocumentModal from './DrillDocumentModal'
import {
  CARD_STYLE,
  DRILL_TYPE_FILTER,
  DRILL_TYPE_UI,
  REVIEW_STATUS_FILTER,
  REVIEW_STATUS_UI,
  STAGE_FILTER,
  STAGE_UI,
  T,
  UI,
} from './emergencyDrillConstants'

// ── KPI 卡 ──

function KpiCard({
  label,
  value,
  bg,
  valueColor,
  caption,
}: {
  label: string
  value: string
  bg?: string
  valueColor?: string
  caption?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: valueColor ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

// ── 主面板 ──

export default function EmergencyDrillPanel() {
  const { message } = App.useApp()

  const [stage, setStage] = useState('')
  const [drillType, setDrillType] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')

  // 已应用筛选（点击查询/回车时生效）
  const [applied, setApplied] = useState<{ stage: string; drillType: string; department: string; status: string; keyword: string }>({ stage: '', drillType: '', department: '', status: '', keyword: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [detailRecord, setDetailRecord] = useState<DrillRecord | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const [docModalOpen, setDocModalOpen] = useState(false)
  const [docRecordId, setDocRecordId] = useState('')
  const [docGenerating, setDocGenerating] = useState<string | null>(null)  // 正在生成方案的记录 ID

  const queryClient = useQueryClient()

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['drill-stats'],
    queryFn: fetchDrillStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['drills', { page, pageSize, stage: applied.stage, drillType: applied.drillType, department: applied.department, status: applied.status, keyword: applied.keyword }],
    queryFn: () => fetchDrillRecords({
      page, page_size: pageSize,
      stage: applied.stage || undefined,
      drill_type: applied.drillType || undefined,
      department: applied.department || undefined,
      status: applied.status || undefined,
      keyword: applied.keyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleSearch = () => {
    setApplied({ stage, drillType, department, status, keyword })
    setPage(1)
  }

  const handleGeneratePlan = useCallback(async (recordId: string) => {
    setDocGenerating(recordId)
    try {
      const res = await generateDrillPlan(recordId)
      if (res.code === 200 && res.data) {
        message.success('演练方案生成成功')
        setDocRecordId(recordId)
        setDocModalOpen(true)
      } else {
        message.error(res.message || '生成失败')
      }
    } catch { message.error('AI 方案生成失败') }
    finally { setDocGenerating(null) }
  }, [message])

  const handleCreateHazards = useCallback(async (recordId: string) => {
    try {
      const res = await createHazardsFromIssues(recordId)
      if (res.code === 200) {
        message.success(res.message || '隐患创建成功')
        queryClient.invalidateQueries({ queryKey: ['drills'] })
      } else { message.error(res.message || '创建失败') }
    } catch { message.error('隐患创建失败') }
  }, [message, queryClient])

  const columns: ColumnsType<DrillRecord> = useMemo(() => [
    {
      title: '演练内容', dataIndex: 'drill_content', key: 'drill_content',
      ellipsis: true, width: 280,
      render: (text: string, record: DrillRecord) => (
        <a onClick={() => { setDetailRecord(record); setDetailOpen(true) }}
           style={{ cursor: 'pointer', fontWeight: 500, color: UI.ink }}>
          {text || '(未填写)'}
        </a>
      ),
    },
    {
      title: '类型', dataIndex: 'drill_type', key: 'drill_type', width: 110,
      render: (t: string) => {
        const ui = DRILL_TYPE_UI[t]
        if (!ui) return t || '-'
        return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.text, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
      },
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
    {
      title: '环节', key: 'stage', width: 80,
      render: (_: unknown, record: DrillRecord) => {
        let s = 'plan'
        if (record.status) s = 'review'
        else if (record.execution_time) s = 'execution'
        const ui = STAGE_UI[s]
        return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
      },
    },
    {
      title: '复核', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const ui = REVIEW_STATUS_UI[s]
        if (!ui) return '-'
        return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
      },
    },
    {
      title: '实施时间', dataIndex: 'execution_time', key: 'execution_time', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    { title: '组织人', dataIndex: 'organizer', key: 'organizer', width: 100, ellipsis: true },
    {
      title: '操作', key: 'actions', width: 180, fixed: 'right',
      render: (_: unknown, record: DrillRecord) => (
        <Space size={4}>
          <Tooltip title="AI 生成演练方案">
            <Button type="primary" size="small" icon={<ThunderboltOutlined />}
              loading={docGenerating === record.id} onClick={() => handleGeneratePlan(record.id)}
              style={{ background: T.primary, borderColor: T.primary, fontSize: 12 }}>
              AI方案
            </Button>
          </Tooltip>
          {record.issues && !record.status && (
            <Tooltip title="问题 → 隐患记录">
              <Button size="small" icon={<AlertOutlined />}
                onClick={() => handleCreateHazards(record.id)}
                style={{ fontSize: 12, color: T.warning, borderColor: T.warning }}>
                转隐患
              </Button>
            </Tooltip>
          )}
          <Button size="small" type="text" icon={<FileTextOutlined />}
            onClick={() => { setDetailRecord(record); setDetailOpen(true) }} />
        </Space>
      ),
    },
  ], [docGenerating, handleGeneratePlan, handleCreateHazards])

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="演练总数" value={String(stats?.total ?? '-')} bg={T.lavender} valueColor={T.primary} caption="全部记录" />
        <KpiCard label="已执行" value={String(stats?.executed ?? '-')} bg={T.mint} valueColor={T.success} caption="实施阶段" />
        <KpiCard label="已完成" value={String(stats?.completed ?? '-')} bg={T.sky} valueColor="#005bab" caption="复核通过" />
        <KpiCard label="待处理" value={String(stats?.pending ?? '-')} bg={T.peach} valueColor={T.warning} caption="未完成复核" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Select value={stage} onChange={(v) => setStage(v)} options={STAGE_FILTER}
            style={{ width: 120 }} placeholder="环节" allowClear />
          <Select value={drillType} onChange={(v) => setDrillType(v)} options={DRILL_TYPE_FILTER}
            style={{ width: 140 }} placeholder="演练类型" allowClear />
          <Select value={department} onChange={(v) => setDepartment(v)}
            options={stats ? [{value: '', label: '全部部门'}, ...Object.keys(stats.by_department).map(k => ({value: k, label: k}))] : []}
            style={{ width: 140 }} placeholder="部门" allowClear showSearch
            filterOption={(input, option) => (option?.label as string)?.includes(input)} />
          <Select value={status} onChange={(v) => setStatus(v)} options={REVIEW_STATUS_FILTER}
            style={{ width: 120 }} placeholder="复核状态" allowClear />
          <Input.Search value={keyword} onChange={(e) => setKeyword(e.target.value)}
            onSearch={handleSearch} placeholder="搜索演练内容" style={{ width: 220 }} allowClear />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
        </div>

        <Table<DrillRecord>
          columns={columns} dataSource={rows} rowKey="id"
          loading={isLoading} scroll={{ x: 1150 }}
          locale={{ emptyText: <Empty description="暂无演练记录" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          size="middle"
        />
      </div>

      <DrillDetailDrawer open={detailOpen} record={detailRecord}
        onClose={() => setDetailOpen(false)}
        onRefresh={() => queryClient.invalidateQueries({ queryKey: ['drills'] })} />

      <DrillDocumentModal open={docModalOpen} recordId={docRecordId}
        onClose={() => setDocModalOpen(false)} />
    </div>
  )
}
