'use client'

/**
 * 相关方准入条件审核（列表 + KPI + 详情抽屉 + AI 审核 Tab）
 * 数据源：Bitable 镜像表（飞书同步）+ 平台 AI 三维度审核（协议/执照/保险）。
 * 视觉：DESIGN 统计卡 + 台账风格（同 EhsChangeApplyPage）。
 */
import { useMemo, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  EyeOutlined,
  FileTextOutlined,
  LinkOutlined,
  ReloadOutlined,
  RocketOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchContractorAdmissions, fetchContractorAdmissionStats } from '@/lib/api/safety/contractor-admission'
import {
  getContractorAdmissionDetail,
  runAdmissionReview,
} from '@/actions/safety'
import type {
  ContractorAdmission,
  ContractorAdmissionListItem,
  ContractorAdmissionStats,
} from '@/types/safety'
import { T } from '../shared-styles'
import { CARD_STYLE, KpiCard } from '../ehsChange/shared'
import { fileProxyUrl } from '../file-url'
import {
  ADMISSION_CONCLUSION_UI,
  AI_REVIEW_STATUS_UI,
  AI_REVIEW_STATUS_FILTER,
  DEFECT_CATEGORY_UI,
  RELATED_PARTY_TYPE_UI,
  RELATED_PARTY_TYPE_FILTER,
  SUBMIT_STATUS_UI,
  SUBMIT_STATUS_FILTER,
  TRAINING_STATUS_UI,
} from './contractorAdmissionConstants'

const { Title, Text } = Typography

function fmtDate(v?: string | null): string {
  if (!v) return ''
  return new Date(v).toLocaleDateString('zh-CN')
}

function Pill({ ui, value }: { ui?: { label: string; pill: React.CSSProperties }; value?: string | null }) {
  if (!value || !ui) return <span style={{ fontSize: 12, color: T.muted }}>—</span>
  return <span style={ui.pill}>{ui.label}</span>
}

function PillInline({ ui, value }: { ui?: React.CSSProperties; value?: string | null }) {
  if (!value || !ui) return <span style={{ fontSize: 12, color: T.muted }}>—</span>
  return <span style={ui}>{value}</span>
}

// ── 详情字段区（同 EhsChangeDetail 的 FieldLabel/FieldTile 视觉）──
function FieldLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>{children}</div>
}

function FieldTile({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: T.charcoal, minHeight: 38, wordBreak: 'break-all' }}>
      {children ?? <span style={{ color: T.muted }}>—</span>}
    </div>
  )
}

function TextBlock({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, lineHeight: 1.7, color: T.charcoal, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {children ?? <span style={{ color: T.muted }}>—</span>}
    </div>
  )
}

// 详情抽屉附件分组（与后端 6 个附件 JSON 字段一一对应）
const ATTACHMENT_GROUPS: { key: keyof ContractorAdmission; label: string }[] = [
  { key: 'safety_agreement_files', label: '安全管理协议' },
  { key: 'business_license_files', label: '企业营业执照' },
  { key: 'insurance_files', label: '现场作业保险凭证' },
  { key: 'assessment_rules_files', label: '承包商考核细则' },
  { key: 'employee_cert_files', label: '员工证明盖章文件' },
  { key: 'on_site_leader_stamp_files', label: '现场负责人盖章文件' },
]

// AI 审核维度（与 ai_review_result 键一致；当前仅审核安全管理协议，
// 营业执照/保险维度预留待开发，result 中为 null 时不渲染）
const REVIEW_DIMENSIONS: { key: 'agreement' | 'license' | 'insurance'; label: string }[] = [
  { key: 'agreement', label: '安全管理协议' },
  { key: 'license', label: '企业营业执照' },
  { key: 'insurance', label: '现场作业保险凭证' },
]

const EMPTY_ADMISSION_STATS: ContractorAdmissionStats = {
  total: 0,
  by_ai_review_status: {},
  by_related_party_type: {},
  by_submit_status: {},
}

export function ContractorAdmissionPage() {
  const { message } = App.useApp()
  const [filters, setFilters] = useState<{
    related_party_type?: string
    submit_status?: string
    ai_review_status?: string
    keyword?: string
  }>({})
  const [pagination, setPagination] = useState({ page: 1, page_size: 20 })

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selected, setSelected] = useState<ContractorAdmission | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  const queryClient = useQueryClient()

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['contractor-admission-stats'],
    queryFn: fetchContractorAdmissionStats,
  })
  const stats = statsQuery.data ?? EMPTY_ADMISSION_STATS

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['contractor-admissions', { page: pagination.page, pageSize: pagination.page_size, filters }],
    queryFn: () => fetchContractorAdmissions({
      page: pagination.page,
      page_size: pagination.page_size,
      sort_by: 'entry_date',
      sort_order: 'desc',
      ...filters,
    }),
  })
  const admissions = listData?.items ?? []
  const total = listData?.total ?? 0

  const setFilter = (patch: Record<string, string | undefined>) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, ...patch }))
  }

  // ── KPI 卡带（AI 审核状态维度，点击联动筛选）──
  const kpiCards = useMemo(
    () => [
      {
        label: '总数',
        value: stats.total,
        active: !filters.ai_review_status,
        onClick: () => setFilter({ ai_review_status: undefined }),
      },
      {
        label: '待审核',
        value: stats.by_ai_review_status['none'] ?? 0,
        color: T.warning,
        active: filters.ai_review_status === 'none',
        onClick: () => setFilter({ ai_review_status: 'none' }),
      },
      {
        label: '通过',
        value: stats.by_ai_review_status['completed'] ?? 0,
        color: T.success,
        active: filters.ai_review_status === 'completed',
        onClick: () => setFilter({ ai_review_status: 'completed' }),
      },
      {
        label: '不通过',
        value: stats.by_ai_review_status['failed'] ?? 0,
        color: T.error,
        active: filters.ai_review_status === 'failed',
        onClick: () => setFilter({ ai_review_status: 'failed' }),
      },
    ],
    [stats, filters],
  )

  // ── 操作 ──
  const afterAction = (id: string, data?: ContractorAdmission | null) => {
    queryClient.invalidateQueries({ queryKey: ['contractor-admissions'] })
    queryClient.invalidateQueries({ queryKey: ['contractor-admission-stats'] })
    if (selected?.id === id && data) setSelected(data)
  }

  const openDetail = async (record: ContractorAdmissionListItem) => {
    setDrawerOpen(true)
    setSelected(null)
    setDetailLoading(true)
    try {
      const res = await getContractorAdmissionDetail(record.id)
      if (res.code === 200 && res.data) {
        setSelected(res.data)
      } else {
        message.error(res.message || '加载详情失败')
      }
    } catch (e) {
      console.error('Failed to load contractor admission detail:', e)
      message.error('加载详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const handleReview = async (id: string) => {
    setReviewing(true)
    try {
      const res = await runAdmissionReview(id)
      if (res.code === 200 && res.data) {
        if (res.data.ai_review_status === 'failed') {
          message.warning(`AI 审核失败：${res.data.ai_error_message || '未知原因'}`)
        } else if (res.data.ai_review_status === 'processing') {
          message.info('AI 审核已触发，正在后台执行')
        } else {
          message.success('AI 审核完成')
        }
        afterAction(id, res.data)
      } else {
        message.error(res.message || 'AI 审核触发失败')
      }
    } finally {
      setReviewing(false)
    }
  }

  const cellText: React.CSSProperties = { fontSize: 12, color: T.slate }
  const cellEmpty: React.CSSProperties = { fontSize: 12, color: T.muted }

  const columns = [
    {
      title: '作业单位名称',
      dataIndex: 'company_name',
      width: 200,
      ellipsis: true,
      render: (v: string | null, record: ContractorAdmissionListItem) => (
        <a
          onClick={() => openDetail(record)}
          style={{ color: '#0075de', textDecoration: 'none', fontSize: 13 }}
          onMouseEnter={(e) => { e.currentTarget.style.textDecoration = 'underline' }}
          onMouseLeave={(e) => { e.currentTarget.style.textDecoration = 'none' }}
        >
          {v || '—'}
        </a>
      ),
    },
    {
      title: '相关方类型',
      dataIndex: 'related_party_type',
      width: 120,
      render: (v: string | null) => <Pill ui={RELATED_PARTY_TYPE_UI[v ?? '']} value={v} />,
    },
    {
      title: '对接人员',
      dataIndex: 'liaison_user_name',
      width: 100,
      render: (v: string | null) => (v ? <span style={cellText}>{v}</span> : <span style={cellEmpty}>—</span>),
    },
    {
      title: '入厂日期',
      dataIndex: 'entry_date',
      width: 110,
      render: (v: string | null) => (v ? <span style={cellText}>{fmtDate(v)}</span> : <span style={cellEmpty}>—</span>),
    },
    {
      title: '提交状态',
      dataIndex: 'submit_status',
      width: 96,
      render: (v: string | null) => <Pill ui={SUBMIT_STATUS_UI[v ?? '']} value={v} />,
    },
    {
      title: '培训状态',
      dataIndex: 'training_status',
      width: 110,
      render: (v: string | null) => <Pill ui={TRAINING_STATUS_UI[v ?? '']} value={v} />,
    },
    {
      title: 'AI审核状态',
      dataIndex: 'ai_review_status',
      width: 96,
      render: (v: string | undefined) => <Pill ui={AI_REVIEW_STATUS_UI[v ?? '']} value={v} />,
    },
    {
      title: 'AI审核结论',
      dataIndex: 'ai_overall_conclusion',
      width: 120,
      render: (v: string | null) => <PillInline ui={ADMISSION_CONCLUSION_UI[v ?? '']} value={v} />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => <span style={cellText}>{fmtDate(v)}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, record: ContractorAdmissionListItem) => (
        <Space size="small" wrap>
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(record)}>详情</Button>
          </Tooltip>
          {record.ai_review_status !== 'completed' && record.ai_review_status !== 'processing' && (
            <Tooltip title="手动触发 AI 审核（安全管理协议）">
              <Popconfirm
                title="确认对此条准入记录执行 AI 审核？"
                onConfirm={() => handleReview(record.id)}
              >
                <Button type="link" size="small" icon={<RocketOutlined />} loading={reviewing}>AI审核</Button>
              </Popconfirm>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  // ── 详情抽屉内容 ──
  const renderBasicFields = (a: ContractorAdmission) => [
    { label: '相关方类型', node: <Pill ui={RELATED_PARTY_TYPE_UI[a.related_party_type ?? '']} value={a.related_party_type} /> },
    { label: '承包商负责人', value: a.contact_person },
    { label: '负责人联系电话', value: a.contact_phone },
    { label: '对接人员', value: a.liaison_user_name },
    { label: '入厂日期', value: fmtDate(a.entry_date) },
    { label: '开始日期', value: fmtDate(a.start_date) },
    { label: '结束日期', value: fmtDate(a.end_date) },
    { label: '材料失效日期', value: fmtDate(a.material_expiry_date) },
    { label: '实际提交日期', value: fmtDate(a.actual_submit_date) },
    { label: '实际完成日期', value: fmtDate(a.actual_complete_date) },
    { label: '提交状态', node: <Pill ui={SUBMIT_STATUS_UI[a.submit_status ?? '']} value={a.submit_status} /> },
    { label: '培训状态', node: <Pill ui={TRAINING_STATUS_UI[a.training_status ?? '']} value={a.training_status} /> },
  ]

  const renderAttachments = (a: ContractorAdmission) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {ATTACHMENT_GROUPS.map((g) => {
        const files = a[g.key]
        const list = Array.isArray(files) ? files : []
        return (
          <div key={g.key}>
            <FieldLabel>{g.label}</FieldLabel>
            {list.length === 0 ? (
              <FieldTile><span style={{ color: T.muted }}>无附件</span></FieldTile>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {list.map((f, i) => {
                  const name = f.name || f.original_name || `附件 ${i + 1}`
                  const url = f.path ? fileProxyUrl(f.path) : ''
                  return url ? (
                    <a key={i} href={url} target="_blank" rel="noreferrer"
                      style={{ fontSize: 13, color: '#0075de', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <LinkOutlined />{name}
                    </a>
                  ) : (
                    <span key={i} style={cellText}>{name}</span>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )

  const renderAiReview = (a: ContractorAdmission) => {
    const r = a.ai_review_result
    const canReview = a.source === 'bitable' && a.ai_review_status !== 'completed' && a.ai_review_status !== 'processing'
    const hasResult = !!r && (r.overall_conclusion || r.overall_report || REVIEW_DIMENSIONS.some((d) => r[d.key]?.conclusion || r[d.key]?.report))

    if (!hasResult) {
      return (
        <div>
          {a.ai_review_status === 'failed' ? (
            <>
              <Text style={{ color: T.error }}>AI 审核失败，可点击重新审核。</Text>
              {a.ai_error_message && (
                <div style={{ marginTop: 10 }}>
                  <FieldLabel>失败原因</FieldLabel>
                  <TextBlock>{a.ai_error_message}</TextBlock>
                </div>
              )}
            </>
          ) : (
            <Text style={{ color: T.steel }}>
              暂无 AI 审核结果。由平台调用 AI 审核安全管理协议（营业执照/保险凭证维度待开发）并回填飞书多维表格。
            </Text>
          )}
          {canReview && (
            <div style={{ marginTop: 12 }}>
              <Button type="primary" icon={<RocketOutlined />} loading={reviewing} onClick={() => handleReview(a.id)}>
                触发AI审核
              </Button>
            </div>
          )}
        </div>
      )
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {canReview && (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" ghost icon={<RocketOutlined />} loading={reviewing} onClick={() => handleReview(a.id)}>
              重新审核
            </Button>
          </div>
        )}
        {/* 总体结论 */}
        <div>
          <FieldLabel>总体结论</FieldLabel>
          <div style={{ marginBottom: 8 }}>
            {r?.overall_conclusion
              ? <span style={ADMISSION_CONCLUSION_UI[r.overall_conclusion]}>{r.overall_conclusion}</span>
              : <Tag>未审核</Tag>}
          </div>
          {r?.overall_report && <TextBlock>{r.overall_report}</TextBlock>}
        </div>
        {/* 三维度报告 */}
        {REVIEW_DIMENSIONS.map((d) => {
          const dim = r?.[d.key]
          if (!dim || (!dim.conclusion && !dim.report)) return null
          return (
            <div key={d.key}>
              <FieldLabel>{d.label}</FieldLabel>
              <div style={{ marginBottom: 8 }}>
                {dim.conclusion
                  ? <span style={ADMISSION_CONCLUSION_UI[dim.conclusion]}>{dim.conclusion}</span>
                  : <Tag>未审核</Tag>}
              </div>
              {dim.report && <TextBlock>{dim.report}</TextBlock>}
              {dim.defects && dim.defects.length > 0 && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {dim.defects.map((df, i) => (
                    <div key={i} style={{ fontSize: 12, color: T.charcoal, display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                      <span style={{ color: T.error }}>•</span>
                      <span>{df}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        {/* 不符合项分类 */}
        {r?.defect_categories && r.defect_categories.length > 0 && (
          <div>
            <FieldLabel>不符合项分类</FieldLabel>
            <Space size={[4, 4]} wrap>
              {r.defect_categories.map((c) => (
                <span key={c} style={DEFECT_CATEGORY_UI[c]?.pill ?? DEFECT_CATEGORY_UI.A基础信息类.pill}>{DEFECT_CATEGORY_UI[c]?.label ?? c}</span>
              ))}
            </Space>
          </div>
        )}
        {/* 审核依据（法规） */}
        {r?.regulations && r.regulations.length > 0 && (
          <div>
            <FieldLabel>审核依据（法规）</FieldLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {r.regulations.map((reg, i) => (
                <div key={i} style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: T.charcoal }}>
                  <span style={{ fontWeight: 600 }}>{reg.doc_title || '未知法规'}</span>
                  {reg.article_ref && <span style={{ color: T.steel }}> — {reg.article_ref}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
        {a.ai_reviewed_at && (
          <Text style={{ fontSize: 12, color: T.steel }}>最近审核时间：{new Date(a.ai_reviewed_at).toLocaleString('zh-CN')}</Text>
        )}
      </div>
    )
  }

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 22, fontWeight: 600, color: T.ink }}>
            相关方准入审核
          </Title>
          <Text style={{ fontSize: 13, color: T.slate }}>
            飞书多维表格同步 · AI 审核（安全管理协议，营业执照/保险凭证维度待开发）
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => {
          queryClient.invalidateQueries({ queryKey: ['contractor-admissions'] })
          queryClient.invalidateQueries({ queryKey: ['contractor-admission-stats'] })
        }}>刷新</Button>
      </div>

      {/* KPI 卡带 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {kpiCards.map((k) => (
          <KpiCard key={k.label} label={k.label} value={k.value} active={k.active} color={k.color} onClick={k.onClick} />
        ))}
      </div>

      {/* 表格卡（筛选栏并入卡头） */}
      <div style={{ ...CARD_STYLE, padding: '4px 16px 12px' }}>
        <div style={{ margin: '0 -16px', padding: '8px 16px 12px', borderBottom: `1px solid ${T.hairlineSoft}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <Space wrap>
            <Select placeholder="全部类型" allowClear size="small" style={{ width: 140 }} options={RELATED_PARTY_TYPE_FILTER} value={filters.related_party_type}
              onChange={(v) => setFilter({ related_party_type: v })} />
            <Select placeholder="全部提交状态" allowClear size="small" style={{ width: 130 }} options={SUBMIT_STATUS_FILTER} value={filters.submit_status}
              onChange={(v) => setFilter({ submit_status: v })} />
            <Select placeholder="全部审核状态" allowClear size="small" style={{ width: 130 }} options={AI_REVIEW_STATUS_FILTER} value={filters.ai_review_status}
              onChange={(v) => setFilter({ ai_review_status: v })} />
            <Input.Search placeholder="搜索单位名称/负责人" allowClear size="small" style={{ width: 220 }}
              defaultValue={filters.keyword}
              onSearch={(v) => setFilter({ keyword: v || undefined })} />
          </Space>
          <span style={{ fontSize: 12, color: T.steel }}>共 {total} 条</span>
        </div>
        <Table
          columns={columns}
          dataSource={admissions}
          rowKey="id"
          loading={isLoading}
          size="small"
          style={{ marginTop: 8 }}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => setPagination((p) => ({ ...p, page, page_size: pageSize })),
          }}
        />
      </div>

      {/* 详情 Drawer */}
      <Drawer
        title={selected ? `准入详情 - ${selected.company_name || selected.admission_no || '未命名'}` : '准入详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelected(null) }}
        width={820}
        loading={detailLoading}
      >
        {selected && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {/* 元信息 */}
            <div style={{ padding: '4px 0 16px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <Pill ui={RELATED_PARTY_TYPE_UI[selected.related_party_type ?? '']} value={selected.related_party_type} />
              <span style={{ fontSize: 12, color: T.steel }}>
                来源：{selected.source === 'bitable' ? '飞书' : '平台'}
              </span>
              <Pill ui={AI_REVIEW_STATUS_UI[selected.ai_review_status ?? '']} value={selected.ai_review_status} />
              {selected.feishu_url && (
                <a href={selected.feishu_url} target="_blank" rel="noreferrer" style={{ color: '#0075de', fontSize: 13 }}>
                  查看飞书原文 ↗
                </a>
              )}
            </div>

            <Tabs
              defaultActiveKey="basic"
              items={[
                {
                  key: 'basic',
                  label: (
                    <span><FileTextOutlined style={{ marginRight: 6 }} />基本信息</span>
                  ),
                  children: (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                      <div>
                        <FieldLabel>作业单位名称</FieldLabel>
                        <FieldTile>{selected.company_name}</FieldTile>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px 16px' }}>
                        {renderBasicFields(selected).map((f) => (
                          <div key={f.label}>
                            <FieldLabel>{f.label}</FieldLabel>
                            <FieldTile>{f.node ?? f.value}</FieldTile>
                          </div>
                        ))}
                      </div>
                      <div>
                        <FieldLabel>备注</FieldLabel>
                        <TextBlock>{selected.notes}</TextBlock>
                      </div>
                      <div>
                        <FieldLabel>准入材料附件</FieldLabel>
                        {renderAttachments(selected)}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'ai',
                  label: (
                    <span><RobotOutlined style={{ marginRight: 6 }} />AI审核</span>
                  ),
                  children: renderAiReview(selected),
                },
              ]}
            />
          </div>
        )}
      </Drawer>
    </div>
  )
}
