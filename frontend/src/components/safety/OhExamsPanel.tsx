'use client'

// 体检记录 Panel（OhExamsPanel）— 对标 MsdsPanel
// KPI（4 卡）→ 筛选（类型/结论/解析状态/部门/keyword）→ Table
// 高危结论行底色 OH_HIGH_RISK_ROW_BG（OH_HIGH_RISK_CONCLUSIONS 判定，旧交互语义保留项）；
// failed 解析状态行内附「重试」；报告附件下载复用 /api/v1/safety/files/{path}。
// 跨 Tab 联动：接收 initialKeyword（人员台账跳转预筛），消费后回调 onConsumedKeyword。

import { useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  Empty,
  Input,
  Popconfirm,
  Select,
  Table,
  Tooltip,
} from 'antd'
import { DownloadOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchOhExams, fetchOhExamStats } from '@/lib/api/safety/occupational-health'
import { parseOhExam } from '@/actions/safety'
import type { OhHealthExam } from '@/types/safety'
import {
  CARD_STYLE,
  OH_AI_CONCLUSION_FILTER,
  OH_AI_CONCLUSION_UI,
  OH_EXAM_TYPE_FILTER,
  OH_EXAM_TYPE_UI,
  OH_HIGH_RISK_CONCLUSIONS,
  OH_HIGH_RISK_ROW_BG,
  OH_PARSE_STATUS_FILTER,
  OH_PARSE_STATUS_UI,
  T,
  UI,
} from './ohConstants'
import { linkPrimary } from './shared-styles'
import OhExamDrawer from './OhExamDrawer'

function KpiCard({ label, value, caption, bg, valueColor }: {
  label: string; value: string; caption?: string; bg?: string; valueColor?: string
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

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function getEffectiveConclusion(exam: OhHealthExam): string | undefined {
  return exam.override_conclusion ?? exam.ai_conclusion
}

interface OhExamsPanelProps {
  initialKeyword?: string
  onConsumedKeyword?: () => void
}

export default function OhExamsPanel({ initialKeyword, onConsumedKeyword }: OhExamsPanelProps) {
  const { message } = App.useApp()

  const [keyword, setKeyword] = useState('')
  const [examType, setExamType] = useState<string | undefined>()
  const [aiConclusion, setAiConclusion] = useState<string | undefined>()
  const [parseStatus, setParseStatus] = useState<string | undefined>()
  const [department, setDepartment] = useState('')

  // 已应用筛选（下拉选中即查，文本框回车/刷新时查）
  const [applied, setApplied] = useState<{ keyword: string; examType?: string; aiConclusion?: string; parseStatus?: string; department: string }>({ keyword: '', department: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [detailExam, setDetailExam] = useState<OhHealthExam | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const consumedKeywordRef = useRef('')

  const queryClient = useQueryClient()

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['oh-exams-stats'],
    queryFn: fetchOhExamStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['oh-exams', { page, pageSize, examType: applied.examType, aiConclusion: applied.aiConclusion, parseStatus: applied.parseStatus, department: applied.department, keyword: applied.keyword }],
    queryFn: () => fetchOhExams({
      page, page_size: pageSize,
      exam_type: applied.examType || undefined,
      ai_conclusion: applied.aiConclusion || undefined,
      ai_parse_status: applied.parseStatus || undefined,
      department: applied.department.trim() || undefined,
      keyword: applied.keyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  // 跨 Tab 联动：人员台账 → 体检记录预筛
  useEffect(() => {
    if (initialKeyword && initialKeyword !== consumedKeywordRef.current) {
      consumedKeywordRef.current = initialKeyword
      setKeyword(initialKeyword)
      setApplied({ keyword: initialKeyword, examType, aiConclusion, parseStatus, department })
      setPage(1)
      onConsumedKeyword?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialKeyword])

  const handleSearch = () => {
    setApplied({ keyword, examType, aiConclusion, parseStatus, department })
    setPage(1)
  }

  const handleRetryParse = async (exam: OhHealthExam) => {
    const res = await parseOhExam(exam.id)
    if (res.code === 200) {
      message.success('已触发重新解析')
      queryClient.invalidateQueries({ queryKey: ['oh-exams'] })
    } else {
      message.error(res.message || '解析失败')
    }
  }

  const renderHazardTags = (factors: string[] | undefined) => {
    if (!factors || factors.length === 0) return <span style={{ color: UI.muted }}>-</span>
    const shown = factors.slice(0, 2)
    const rest = factors.slice(2)
    return (
      <span>
        {shown.map((h) => (
          <span key={h} style={{ fontSize: 12, padding: '1px 8px', borderRadius: 4, color: '#391c57', background: T.lavender, fontWeight: 500, marginRight: 4 }}>{h}</span>
        ))}
        {rest.length > 0 && (
          <Tooltip title={rest.join('、')}>
            <span style={{ fontSize: 12, color: UI.steel, cursor: 'pointer' }}>+{rest.length}</span>
          </Tooltip>
        )}
      </span>
    )
  }

  const columns: ColumnsType<OhHealthExam> = [
    {
      title: '体检号', dataIndex: 'exam_no', key: 'exam_no', width: 150,
      render: (text: string, record: OhHealthExam) => (
        <a onClick={() => { setDetailExam(record); setDetailOpen(true) }}
           style={{ ...linkPrimary, cursor: 'pointer', fontWeight: 600 }}>
          {text || '(未填写)'}
        </a>
      ),
    },
    { title: '姓名', dataIndex: 'employee_name', key: 'employee_name', width: 100, render: (v: string) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 130, ellipsis: true, render: (v: string) => v || '-' },
    { title: '体检类型', dataIndex: 'exam_type', key: 'exam_type', width: 100, render: (v: string) => <Pill status={v} map={OH_EXAM_TYPE_UI} /> },
    { title: '体检日期', dataIndex: 'exam_date', key: 'exam_date', width: 110, render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-') },
    {
      title: '接害工龄', dataIndex: 'hazard_exposure_years', key: 'hazard_exposure_years', width: 90,
      render: (v: number) => (v === undefined || v === null ? '-' : `${v} 年`),
    },
    {
      title: '危害因素', dataIndex: 'hazard_factors', key: 'hazard_factors', width: 180,
      render: (v: string[] | undefined) => renderHazardTags(v),
    },
    {
      title: 'AI 结论', key: 'conclusion', width: 100,
      render: (_: unknown, record: OhHealthExam) => <Pill status={getEffectiveConclusion(record)} map={OH_AI_CONCLUSION_UI} />,
    },
    {
      title: '解析状态', dataIndex: 'ai_parse_status', key: 'parse_status', width: 110,
      render: (v: string, record: OhHealthExam) => (
        <span>
          <Pill status={v} map={OH_PARSE_STATUS_UI} />
          {v === 'failed' && (
            <Popconfirm
              title="重新解析"
              description="重新调用 AI 解析该体检报告"
              okText="重新解析" cancelText="取消"
              onConfirm={() => handleRetryParse(record)}
            >
              <span style={{ ...linkPrimary, cursor: 'pointer', marginLeft: 6, fontSize: 12 }}>重试</span>
            </Popconfirm>
          )}
        </span>
      ),
    },
    {
      title: '报告附件', key: 'attachment', width: 90,
      render: (_: unknown, record: OhHealthExam) => {
        const path = record.attachment_paths?.[0] ?? record.attachments?.[0]?.path
        if (!path) return <span style={{ color: UI.muted, fontSize: 12 }}>无</span>
        return (
          <Button size="small" type="text" icon={<DownloadOutlined />}
            onClick={() => window.open(`/api/v1/safety/files/${encodeURIComponent(path)}`, '_blank')}
            style={{ color: T.primary }}>下载</Button>
        )
      },
    },
  ]

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="体检总数" value={String(stats?.total ?? '-')} bg={T.lavender} valueColor={T.primary} caption="全部体检记录" />
        <KpiCard label="异常指标人数" value={String(stats?.abnormal ?? '-')} bg={T.peach} valueColor={T.warning} caption="结论为异常/疑似职业病等" />
        <KpiCard label="职业禁忌证" value={String(stats?.contraindicated ?? '-')} bg={T.rose} valueColor={T.error} caption="禁忌证结论记录" />
        <KpiCard label="待 AI 解析" value={String(stats?.pending_parse ?? '-')} bg={T.sky} valueColor="#005bab" caption="pending 状态" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="体检号/姓名" value={keyword}
            onChange={(e) => setKeyword(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 170 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Select
            value={examType}
            onChange={(v) => { setExamType(v); setApplied({ keyword, examType: v, aiConclusion, parseStatus, department }); setPage(1) }}
            options={OH_EXAM_TYPE_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Select
            value={aiConclusion}
            onChange={(v) => { setAiConclusion(v); setApplied({ keyword, examType, aiConclusion: v, parseStatus, department }); setPage(1) }}
            options={OH_AI_CONCLUSION_FILTER}
            style={{ width: 140 }} allowClear
          />
          <Select
            value={parseStatus}
            onChange={(v) => { setParseStatus(v); setApplied({ keyword, examType, aiConclusion, parseStatus: v, department }); setPage(1) }}
            options={OH_PARSE_STATUS_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Input allowClear placeholder="部门" value={department}
            onChange={(e) => setDepartment(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 140 }} />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
        </div>

        <Table<OhHealthExam>
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 1280 }}
          locale={{ emptyText: <Empty description="暂无体检记录" /> }}
          onRow={(record) => {
            const conclusion = getEffectiveConclusion(record)
            if (conclusion && OH_HIGH_RISK_CONCLUSIONS.includes(conclusion)) {
              return { style: { background: OH_HIGH_RISK_ROW_BG } }
            }
            return {}
          }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </div>

      <OhExamDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        exam={detailExam}
        onRefresh={() => queryClient.invalidateQueries({ queryKey: ['oh-exams'] })}
      />
    </div>
  )
}
