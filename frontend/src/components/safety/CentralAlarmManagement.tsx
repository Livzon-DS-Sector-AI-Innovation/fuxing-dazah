'use client'

import { useState } from 'react'
import {
  App, Button, DatePicker, Drawer, Empty, Input, Modal, Select, Space, Table, Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  EyeOutlined, FileTextOutlined, ReloadOutlined, SyncOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchCentralAlarmRecords, fetchCentralAlarmStats } from '@/lib/api/safety/central-alarm'
import {
  generateCentralAlarmDailyReport,
  syncCentralAlarmData,
} from '@/actions/safety'
import type {
  CentralAlarmRecord,
  CentralAlarmReportResponse,
  CentralAlarmStats,
} from '@/types/safety'

import { T } from './shared-styles'
import { AI_DIMENSION_CONFIG, AI_PATTERN_CONFIG, dynamicTagStyle, PUSH_RESULT } from './centralAlarmConstants'

const CARD_STYLE: React.CSSProperties = {
  background: T.canvas,
  border: `1px solid ${T.hairline}`,
  borderRadius: 12,
}

function KpiCard({ label, value, caption, color }: {
  label: string; value: React.ReactNode; caption?: React.ReactNode; color?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: T.muted }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: color ?? T.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: T.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

function PatternTag({ pattern }: { pattern?: string | null }) {
  const cfg = pattern ? AI_PATTERN_CONFIG[pattern] : undefined
  if (!cfg) return <span style={{ fontSize: 12, color: T.muted }}>—</span>
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600,
      padding: '2px 10px', borderRadius: 9999, background: cfg.bg, color: cfg.text,
      whiteSpace: 'nowrap', width: 'fit-content',
    }}>
      {cfg.icon}{cfg.label}
    </span>
  )
}

function DimensionTag({ dimension }: { dimension?: string | null }) {
  const cfg = dimension ? AI_DIMENSION_CONFIG[dimension] : undefined
  if (!cfg) return <span style={{ fontSize: 12, color: T.muted }}>—</span>
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600,
      padding: '2px 10px', borderRadius: 9999, background: cfg.bg, color: cfg.text,
      whiteSpace: 'nowrap', width: 'fit-content',
    }}>
      {cfg.icon}{cfg.label}
    </span>
  )
}

export default function CentralAlarmManagement({ initialStats }: { initialStats: CentralAlarmStats | null }) {
  const { message } = App.useApp()

  // 筛选（输入态）
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null]>([null, null])
  const [workshop, setWorkshop] = useState<string | undefined>()
  const [post, setPost] = useState<string | undefined>()
  const [aiAlarmType, setAiAlarmType] = useState<string | undefined>()
  const [aiPattern, setAiPattern] = useState<string | undefined>()
  const [keyword, setKeyword] = useState<string>('')

  // 已应用筛选（点击查询后生效，保持手动查询交互）
  const [applied, setApplied] = useState<{
    range: [Dayjs | null, Dayjs | null] | null
    workshop?: string
    post?: string
    aiAlarmType?: string
    aiPattern?: string
    keyword: string
  }>({ range: [null, null], keyword: '' })

  // 数据
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [syncing, setSyncing] = useState(false)
  const [generating, setGenerating] = useState(false)

  // 弹窗
  const [reportModal, setReportModal] = useState<CentralAlarmReportResponse | null>(null)
  const [detail, setDetail] = useState<CentralAlarmRecord | null>(null)

  const queryClient = useQueryClient()

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['central-alarms'] })
    queryClient.invalidateQueries({ queryKey: ['central-alarm-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['central-alarm-stats'],
    queryFn: fetchCentralAlarmStats,
    initialData: initialStats ?? undefined,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['central-alarms', {
      page, pageSize,
      dateFrom: applied.range?.[0] ? applied.range[0].format('YYYY-MM-DD') : undefined,
      dateTo: applied.range?.[1] ? applied.range[1].format('YYYY-MM-DD') : undefined,
      workshop: applied.workshop, post: applied.post,
      aiAlarmType: applied.aiAlarmType, aiPattern: applied.aiPattern,
      keyword: applied.keyword,
    }],
    queryFn: () => fetchCentralAlarmRecords({
      page, page_size: pageSize,
      date_from: applied.range?.[0] ? applied.range[0].format('YYYY-MM-DD') : undefined,
      date_to: applied.range?.[1] ? applied.range[1].format('YYYY-MM-DD') : undefined,
      workshop: applied.workshop, post: applied.post,
      ai_alarm_type: applied.aiAlarmType, ai_pattern: applied.aiPattern,
      keyword: applied.keyword || undefined,
    }),
  })

  const records = listData?.items ?? []
  const total = listData?.total ?? 0

  const onFilter = () => {
    setApplied({ range, workshop, post, aiAlarmType, aiPattern, keyword })
    setPage(1)
  }
  const onReset = () => {
    setRange([null, null]); setWorkshop(undefined); setPost(undefined)
    setAiAlarmType(undefined); setAiPattern(undefined); setKeyword('')
    setApplied({ range: [null, null], keyword: '' })
    setPage(1)
  }

  const onSync = async () => {
    setSyncing(true)
    try {
      const res = await syncCentralAlarmData()
      if (res.code === 200) {
        message.success(res.message || '同步完成')
        refresh()
      } else {
        message.error(res.message || '同步失败')
      }
    } catch {
      message.error('同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const onGenerate = async () => {
    setGenerating(true)
    try {
      const res = await generateCentralAlarmDailyReport()
      if (res.code === 200) {
        setReportModal(res.data ?? null)
        refresh()
      } else {
        message.error(res.message || '日报生成失败')
      }
    } catch {
      message.error('日报生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const columns: ColumnsType<CentralAlarmRecord> = [
    { title: '日期', dataIndex: 'alarm_date', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '—' },
    { title: '车间', dataIndex: 'workshop', width: 90, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '—' },
    { title: '产线', dataIndex: 'line', width: 100, render: (v: string) => v || '—' },
    { title: '岗位', dataIndex: 'post', width: 110, render: (v: string) => {
      const s = dynamicTagStyle(v)
      return v ? <Tag style={{ background: s.bg, color: s.text }}>{v}</Tag> : '—'
    } },
    { title: '报警情况说明', dataIndex: 'alarm_description', ellipsis: true, render: (v: string) => v || '—' },
    { title: '报警类型', dataIndex: 'ai_alarm_type', width: 100, render: (v: string) => v ? <Tag color="purple">{v}</Tag> : '—' },
    { title: '异常模式', dataIndex: 'ai_pattern', width: 100, render: (v: string) => <PatternTag pattern={v} /> },
    { title: 'AI 维度', dataIndex: 'ai_dimension', width: 110, render: (v: string) => <DimensionTag dimension={v} /> },
    { title: '操作', width: 70, fixed: 'right', render: (_: unknown, r) => (
      <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setDetail(r)}>详情</Button>
    )},
  ]

  const workshopOptions = Object.keys(stats?.workshop_distribution ?? {}).map((k) => ({ value: k, label: k }))
  const postOptions = Object.keys(stats?.post_distribution ?? {}).map((k) => ({ value: k, label: k }))
  const typeOptions = Object.keys(stats?.alarm_type_distribution ?? {}).map((k) => ({ value: k, label: k }))
  const patternOptions = Object.keys(AI_PATTERN_CONFIG).map((k) => ({ value: k, label: AI_PATTERN_CONFIG[k].label }))

  return (
    <div style={{ padding: 20, background: T.canvas }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: T.ink }}>中控报警分析</h2>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>刷新</Button>
          <Button icon={<SyncOutlined />} loading={syncing} onClick={onSync}>同步飞书</Button>
          <Button type="primary" icon={<FileTextOutlined />} loading={generating} onClick={onGenerate}>生成日报</Button>
        </Space>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <KpiCard label="今日报警" value={stats?.today_total ?? 0} caption="北京时区今日" color={T.error} />
        <KpiCard label="本周报警" value={stats?.week_total ?? 0} caption="自然周 周一~周日" />
        <KpiCard label="累计报警" value={stats?.total_count ?? 0} caption="全量非软删" />
        <KpiCard label="本周已AI分析" value={stats?.week_ai_analyzed_count ?? 0} caption="已回写 AI 字段" />
      </div>

      <div style={{ ...CARD_STYLE, padding: 16, marginBottom: 16 }}>
        <Space wrap>
          <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs | null, Dayjs | null])} allowClear />
          <Select allowClear placeholder="车间" style={{ width: 130 }} value={workshop} onChange={setWorkshop} options={workshopOptions} />
          <Select allowClear placeholder="岗位" style={{ width: 130 }} value={post} onChange={setPost} options={postOptions} />
          <Select allowClear placeholder="报警类型" style={{ width: 130 }} value={aiAlarmType} onChange={setAiAlarmType} options={typeOptions} />
          <Select allowClear placeholder="异常模式" style={{ width: 130 }} value={aiPattern} onChange={setAiPattern} options={patternOptions} />
          <Input.Search placeholder="报警说明/特殊说明关键词" style={{ width: 220 }} allowClear value={keyword}
            onChange={(e) => setKeyword(e.target.value)} onSearch={onFilter} />
          <Button type="primary" onClick={onFilter}>查询</Button>
          <Button onClick={onReset}>重置</Button>
        </Space>
      </div>

      <Table<CentralAlarmRecord>
        rowKey="id"
        columns={columns}
        dataSource={records}
        loading={isLoading}
        scroll={{ x: 1100 }}
        locale={{ emptyText: <Empty description="暂无中控报警记录" /> }}
        pagination={{
          current: page, pageSize, total, showSizeChanger: true, showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
      />

      {reportModal && (
        <Modal
          title={`中控报警日报 · ${reportModal.target_date}`}
          open={!!reportModal}
          onCancel={() => setReportModal(null)}
          footer={null}
          width={720}
        >
          <div style={{ fontSize: 12, color: T.steel, marginBottom: 8 }}>
            涉及 {reportModal.total} 条 · AI 分析 {reportModal.analyzed} 条 ·
            {reportModal.push_results?.map((p, i) => (
              <Tag key={i} color={PUSH_RESULT[p.success ? 'success' : p.skipped ? 'skipped' : 'failed'].color} style={{ marginLeft: 6 }}>
                {PUSH_RESULT[p.success ? 'success' : p.skipped ? 'skipped' : 'failed'].label}
              </Tag>
            ))}
          </div>
          <pre style={{ whiteSpace: 'pre-wrap', background: T.canvas, padding: 16, borderRadius: 8, fontSize: 13, lineHeight: 1.7, maxHeight: 480, overflow: 'auto' }}>
            {reportModal.markdown_report}
          </pre>
        </Modal>
      )}

      <Drawer open={!!detail} onClose={() => setDetail(null)} title="中控报警详情" width={480}>
        {detail && (
          <div style={{ fontSize: 13 }}>
            <DetailRow label="日期" value={detail.alarm_date ? dayjs(detail.alarm_date).format('YYYY-MM-DD HH:mm') : '—'} />
            <DetailRow label="车间/产线" value={`${detail.workshop ?? '—'} / ${detail.line ?? '—'}`} />
            <DetailRow label="岗位" value={detail.post ?? '—'} />
            <DetailRow label="报警情况说明" value={detail.alarm_description ?? '—'} />
            <DetailRow label="特殊情况说明" value={detail.special_note ?? '—'} />
            <DetailRow label="报警类型(AI)" value={detail.ai_alarm_type ?? '—'} />
            <DetailRow label="设备(AI)" value={detail.ai_equipment ?? '—'} />
            <div style={{ marginBottom: 12 }}><span style={LABEL}>异常模式(AI)</span>&nbsp;<PatternTag pattern={detail.ai_pattern} /></div>
            <div style={{ marginBottom: 12 }}><span style={LABEL}>AI 维度</span>&nbsp;<DimensionTag dimension={detail.ai_dimension} /></div>
            <DetailRow label="AI 原因分析" value={detail.ai_reason_analysis ?? '待 AI 分析'} />
            <DetailRow label="AI 整改方向" value={detail.ai_rectification_direction ?? '待 AI 分析'} />
            <DetailRow label="同步时间" value={detail.synced_at ? dayjs(detail.synced_at).format('YYYY-MM-DD HH:mm') : '—'} />
          </div>
        )}
      </Drawer>
    </div>
  )
}

const LABEL: React.CSSProperties = { fontWeight: 600, color: T.muted, display: 'inline-block', width: 110, verticalAlign: 'top' }

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12, lineHeight: 1.6 }}>
      <span style={LABEL}>{label}</span>
      <span style={{ color: T.ink }}>{value}</span>
    </div>
  )
}
