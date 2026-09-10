'use client'

import { useMemo, useState } from 'react'
import { App, Button, Input, Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ThunderboltOutlined, AuditOutlined, FileDoneOutlined, SendOutlined } from '@ant-design/icons'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchURsReports, fetchURsStats } from '@/lib/api/safety/ehs-change'
import {
  deleteURS,
  submitURS,
} from '@/actions/safety'
import type { URSReport } from '@/types/safety'
import { T } from '../shared-styles'
import { URS_STATUS_FILTER, URS_STATUS_UI, RISK_LEVEL_UI } from './ursConstants'
import { URSRegisterDrawer } from './URSRegisterDrawer'
import { URSDetailDrawer } from './URSDetailDrawer'
import { URSRiskAssessmentDrawer } from './URSRiskAssessmentDrawer'
import { URSItemReviewDrawer } from './URSItemReviewDrawer'
import { URSConclusionModal } from './URSConclusionModal'

const CARD_STYLE: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e5e3df',
  borderRadius: 12,
  padding: 20,
}

export function URSPanel() {
  const { message, modal } = App.useApp()

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')

  // 已应用筛选（点击查询/回车时生效）
  const [applied, setApplied] = useState({ category: '', status: '', keyword: '' })

  // 抽屉/弹窗状态
  const [registerOpen, setRegisterOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [assessId, setAssessId] = useState<string | null>(null)
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [conclusionId, setConclusionId] = useState<string | null>(null)

  const queryClient = useQueryClient()

  const refreshUrs = () => {
    queryClient.invalidateQueries({ queryKey: ['urs-reports'] })
    queryClient.invalidateQueries({ queryKey: ['urs-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['urs-stats'],
    queryFn: fetchURsStats,
  })
  const stats = statsQuery.data ?? { total: 0, high_risk: 0, approved: 0 } as { total: number; high_risk: number; approved: number; by_status?: Record<string, number> }

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['urs-reports', { page, pageSize, ...applied }],
    queryFn: () => fetchURsReports({
      page, page_size: pageSize,
      equipment_category: applied.category || undefined,
      status: applied.status || undefined,
      keyword: applied.keyword || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleSubmit = async (id: string) => {
    const res = await submitURS(id)
    if (res.code >= 200 && res.code < 300) {
      message.success('已提交，AI 评估进行中')
      refreshUrs()
    } else {
      message.error(res.message || '提交失败')
    }
  }

  const handleDelete = (record: URSReport) => {
    modal.confirm({
      title: `删除 URS ${record.urs_no}？`,
      content: '删除后不可恢复（软删除）。',
      onOk: async () => {
        const res = await deleteURS(record.id)
        if (res.code >= 200 && res.code < 300) {
          message.success('已删除')
          refreshUrs()
        } else {
          message.error(res.message || '删除失败')
        }
      },
    })
  }

  const columns: ColumnsType<URSReport> = useMemo(
    () => [
      { title: '编号', dataIndex: 'urs_no', width: 150, render: (v) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span> },
      { title: '设备名称', dataIndex: 'equipment_name', width: 180 },
      { title: '类别', dataIndex: 'equipment_category', width: 100 },
      { title: '部门', dataIndex: 'department', width: 120 },
      {
        title: '综合风险', dataIndex: 'overall_risk_level', width: 90,
        render: (v: string) => {
          const ui = RISK_LEVEL_UI[v] ?? { label: '—', pill: undefined }
          return v ? <span style={ui.pill}>{ui.label}</span> : <span style={{ color: '#bbb8b1' }}>—</span>
        },
      },
      {
        title: '状态', dataIndex: 'review_status', width: 100,
        render: (v: string) => {
          const ui = URS_STATUS_UI[v] ?? { label: v, pill: undefined }
          return <span style={ui.pill}>{ui.label}</span>
        },
      },
      {
        title: '结论', width: 90,
        render: (_, r) =>
          r.grade ? (
            <span style={{ fontSize: 12, fontWeight: 600, color: r.conclusion === 'approved' ? T.success : T.error }}>
              {r.score} 分（{r.grade}）
            </span>
          ) : <span style={{ color: '#bbb8b1' }}>—</span>,
      },
      {
        title: '操作', width: 300, fixed: 'right',
        render: (_, r) => (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Button size="small" type="link" style={{ fontSize: 12 }} onClick={() => setDetailId(r.id)}>详情</Button>
            {r.review_status === 'draft' && (
              <>
                <Button size="small" type="primary" icon={<SendOutlined />} style={{ fontSize: 12, background: T.primary, borderColor: T.primary }} onClick={() => handleSubmit(r.id)}>提交</Button>
                <Button size="small" type="link" style={{ fontSize: 12 }} onClick={() => handleDelete(r)}>删除</Button>
              </>
            )}
            {(r.review_status === 'assessing' || r.review_status === 'assessment_confirmed' || r.review_status === 'human_review' || r.review_status === 'adapting' || r.review_status === 'item_review') && (
              <Button size="small" icon={<ThunderboltOutlined />} style={{ fontSize: 12, borderColor: T.primary, color: T.primary }} onClick={() => setAssessId(r.id)}>评估</Button>
            )}
            {r.review_status === 'item_review' && (
              <Button size="small" icon={<AuditOutlined />} style={{ fontSize: 12, background: T.primary, borderColor: T.primary, color: '#fff' }} onClick={() => setReviewId(r.id)}>审核条目</Button>
            )}
            {(r.review_status === 'approved' || r.review_status === 'rejected' || r.review_status === 'appeal') && (
              <Button size="small" icon={<FileDoneOutlined />} style={{ fontSize: 12, borderColor: T.success, color: T.success }} onClick={() => setConclusionId(r.id)}>结论</Button>
            )}
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const kpi = [
    { label: '全部审核', value: stats.total, bg: T.lavender, color: '#5645d4' },
    { label: '评估/审核中', value: (stats.by_status?.assessing ?? 0) + (stats.by_status?.item_review ?? 0), bg: T.sky, color: '#0075de' },
    { label: '高风险设备', value: stats.high_risk, bg: T.rose, color: '#e03131' },
    { label: '已通过', value: stats.approved, bg: T.mint, color: '#1aae39' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {kpi.map((k) => (
          <div key={k.label} style={{ ...CARD_STYLE, padding: 16, background: k.bg }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 13, color: T.steel, marginTop: 2 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* 筛选 + 列表 */}
      <div style={CARD_STYLE}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          <Select placeholder="设备类别" allowClear style={{ width: 140 }} value={category || undefined} onChange={(v) => setCategory(v ?? '')}
            options={[
              { value: '采样系统', label: '采样系统' }, { value: '反应釜', label: '反应釜' },
              { value: '泵', label: '泵' }, { value: '离心机', label: '离心机' },
              { value: '干燥设备', label: '干燥设备' }, { value: '储罐', label: '储罐' },
              { value: '实验室仪器', label: '实验室仪器' }, { value: '其他', label: '其他' },
            ]} />
          <Select placeholder="状态" allowClear style={{ width: 140 }} value={status || undefined} onChange={(v) => setStatus(v ?? '')} options={URS_STATUS_FILTER} />
          <Input placeholder="设备名称关键词" style={{ width: 180 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} onPressEnter={() => { setApplied({ category, status, keyword }); setPage(1) }} />
          <Button onClick={() => { setApplied({ category, status, keyword }); setPage(1) }}>查询</Button>
          <div style={{ flex: 1 }} />
          <Button type="primary" icon={<PlusOutlined />} style={{ background: T.primary, borderColor: T.primary }} onClick={() => setRegisterOpen(true)}>新建 URS</Button>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={isLoading}
          pagination={{
            current: page, pageSize, total,
            showSizeChanger: true,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          onRow={(r) => ({ onClick: () => setDetailId(r.id), style: { cursor: 'pointer' } })}
        />
      </div>

      <URSRegisterDrawer open={registerOpen} onClose={() => setRegisterOpen(false)} onCreated={() => { setRegisterOpen(false); refreshUrs() }} />
      <URSDetailDrawer recordId={detailId} onClose={() => setDetailId(null)} onOpenAssess={(id) => { setDetailId(null); setAssessId(id) }} />
      <URSRiskAssessmentDrawer recordId={assessId} onClose={() => setAssessId(null)} onOpenReview={(id) => { setAssessId(null); setReviewId(id) }} />
      <URSItemReviewDrawer recordId={reviewId} onClose={() => setReviewId(null)} onOpenConclusion={(id) => { setReviewId(null); setConclusionId(id) }} />
      <URSConclusionModal recordId={conclusionId} onClose={() => setConclusionId(null)} onAppeal={(id) => { setConclusionId(null); setAssessId(id) }} />
    </div>
  )
}
