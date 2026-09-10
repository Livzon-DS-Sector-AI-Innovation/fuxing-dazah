'use client'

/**
 * EHS 变更审批台账（申请页）
 * 突出审批信息：变更分类/时效/等级/部门/当前处理人/审批节点 + AI 审核。
 * 视觉：DESIGN 统计卡 + 台账风格。
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  App,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tooltip,
  Typography,
} from 'antd'
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  LockOutlined,
  MinusCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  RocketOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchEhsChanges, fetchEhsChangeStats } from '@/lib/api/safety/ehs-change'
import {
  approveEhsChange,
  cancelEhsChange,
  closeEhsChange,
  commissionEhsChange,
  createEhsChange,
  deleteEhsChange,
  rejectEhsChange,
  startImplementationEhsChange,
  submitEhsChange,
  updateEhsChange,
} from '@/actions/safety'
import {
  CHANGE_DURATION_OPTIONS,
  CHANGE_TYPE_OPTIONS,
  EhsChangeStatus,
} from '@/types/safety'
import type { EhsChange, EhsChangeFormData } from '@/types/safety'
import { T, monoFont } from '../shared-styles'
import {
  AI_CONCLUSION_FILTER,
  CHANGE_DURATION_LABEL,
  CHANGE_TYPE_LABEL,
  STATUS_FILTER,
  STATUS_UI,
  getAiConclusion,
} from './ehsChangeConstants'
import { CARD_STYLE, EhsChangeDetail, GradePill, KpiCard, StatusPill, AiConclusionPill } from './shared'

const { Title, Text } = Typography
const { TextArea } = Input

const EMPTY_APPLY_STATS = { total: 0, status: {}, ai: { 审核通过: 0, 需补充完善: 0, 审核不通过: 0 } } as { total: number; status: Record<string, number>; ai: Record<string, number> }

export function EhsChangeApplyPage() {
  const routerSearch = useSearchParams()
  const { message } = App.useApp()

  const [filters, setFilters] = useState({
    status: undefined as string | undefined,
    change_type: undefined as string | undefined,
    change_grade: undefined as string | undefined,
    change_duration: undefined as string | undefined,
    keyword: (routerSearch.get('keyword') as string | undefined) ?? undefined,
    ai_review_conclusion: undefined as string | undefined,
  })
  const [pagination, setPagination] = useState({ page: 1, page_size: 20 })

  // Detail drawer / create-edit modal
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedChange, setSelectedChange] = useState<EhsChange | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingChange, setEditingChange] = useState<EhsChange | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const queryClient = useQueryClient()

  const { ai_review_conclusion, ...serverFilters } = filters

  const refreshApply = () => {
    queryClient.invalidateQueries({ queryKey: ['ehs-changes'] })
    queryClient.invalidateQueries({ queryKey: ['ehs-change-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['ehs-change-stats', 'approval'],
    queryFn: () => fetchEhsChangeStats('approval'),
  })
  const stats = statsQuery.data ?? EMPTY_APPLY_STATS

  // 列表 query（服务端筛选）
  const { data: listData, isLoading } = useQuery({
    queryKey: ['ehs-changes', { page: pagination.page, pageSize: pagination.page_size, serverFilters, feishuTableId: 'approval' }],
    queryFn: () => fetchEhsChanges({
      page: pagination.page,
      page_size: pagination.page_size,
      feishu_table_id: 'approval',
      sort_by: 'change_no',
      sort_order: 'desc',
      ...serverFilters,
    }),
  })

  // ai_review_conclusion 客户端过滤（保持原行为）
  const changes = useMemo(() => {
    const items = listData?.items ?? []
    if (ai_review_conclusion) {
      return items.filter((c) => getAiConclusion(c) === ai_review_conclusion)
    }
    return items
  }, [listData?.items, ai_review_conclusion])

  const total = listData?.total ?? 0

  // 关联追溯：acceptance 页带 keyword 跳转进来 → 自动搜索
  const setKeywordFilter = (kw: string) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, keyword: kw || undefined }))
  }

  const setFilter = (patch: Record<string, string | undefined>) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, ...patch }))
  }

  // ── KPI 卡带（点击联动筛选）──
  const kpiCards = useMemo(
    () => [
      {
        label: '全部变更',
        value: stats.total,
        active: !filters.status && !filters.ai_review_conclusion,
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: undefined }),
      },
      {
        label: '审批中',
        value: stats.status.under_review ?? 0,
        color: T.warning,
        active: filters.status === 'under_review',
        onClick: () => setFilter({ status: 'under_review', ai_review_conclusion: undefined }),
      },
      {
        label: '已通过',
        value: stats.status.approved ?? 0,
        color: T.success,
        active: filters.status === 'approved',
        onClick: () => setFilter({ status: 'approved', ai_review_conclusion: undefined }),
      },
      {
        label: '需补充完善',
        value: stats.ai['需补充完善'] ?? 0,
        color: T.warning,
        active: filters.ai_review_conclusion === '需补充完善',
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: '需补充完善' }),
      },
      {
        label: '审核不通过',
        value: stats.ai['审核不通过'] ?? 0,
        color: T.error,
        active: filters.ai_review_conclusion === '审核不通过',
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: '审核不通过' }),
      },
      {
        label: '已拒绝',
        value: stats.status.rejected ?? 0,
        color: T.error,
        active: filters.status === 'rejected',
        onClick: () => setFilter({ status: 'rejected', ai_review_conclusion: undefined }),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stats, filters],
  )

  // ── 工作流操作 ──
  const afterAction = (id: string, data?: EhsChange | null) => {
    refreshApply()
    if (selectedChange?.id === id && data) setSelectedChange(data)
  }
  const handleSubmit = async (id: string) => {
    const res = await submitEhsChange(id)
    res.code === 200 ? message.success('变更已提交') : message.error(res.message || '提交失败')
    afterAction(id, res.data)
  }
  const handleApprove = async (id: string) => {
    const res = await approveEhsChange(id, 'approved')
    res.code === 200 ? message.success('变更已批准') : message.error(res.message || '操作失败')
    afterAction(id, res.data)
  }
  const handleReject = async (id: string) => {
    const res = await rejectEhsChange(id, '驳回')
    res.code === 200 ? message.success('变更已驳回') : message.error(res.message || '驳回失败')
    afterAction(id, res.data)
  }
  const handleStartImpl = async (id: string) => {
    const res = await startImplementationEhsChange(id)
    res.code === 200 ? message.success('变更已开始实施') : message.error(res.message || '操作失败')
    afterAction(id, res.data)
  }
  const handleCommission = async (id: string) => {
    const res = await commissionEhsChange(id)
    res.code === 200 ? message.success('变更已投用') : message.error(res.message || '操作失败')
    afterAction(id, res.data)
  }
  const handleClose = async (id: string) => {
    const res = await closeEhsChange(id)
    res.code === 200 ? message.success('变更已关闭') : message.error(res.message || '关闭失败')
    afterAction(id, res.data)
  }
  const handleCancel = async (id: string) => {
    const res = await cancelEhsChange(id)
    res.code === 200 ? message.success('变更已取消') : message.error(res.message || '取消失败')
    afterAction(id, res.data)
  }
  const handleDelete = async (id: string) => {
    const res = await deleteEhsChange(id)
    if (res.code === 200) {
      message.success('删除成功')
      refreshApply()
    } else {
      message.error(res.message || '删除失败')
    }
  }

  const renderActionButtons = (record: EhsChange) => {
    if (record.source === 'bitable') return []
    const btns: React.ReactNode[] = []
    if (record.status === EhsChangeStatus.DRAFT) {
      btns.push(
        <Tooltip title="提交审核" key="submit">
          <Popconfirm title="确认提交此变更申请？" onConfirm={() => handleSubmit(record.id)}>
            <Button type="link" size="small" icon={<SendOutlined />} style={{ color: '#0075de' }}>提交</Button>
          </Popconfirm>
        </Tooltip>,
        <Tooltip title="取消变更" key="cancel">
          <Popconfirm title="确认取消此变更？" onConfirm={() => handleCancel(record.id)}>
            <Button type="link" size="small" danger icon={<MinusCircleOutlined />}>取消</Button>
          </Popconfirm>
        </Tooltip>,
      )
    } else if (record.status === EhsChangeStatus.UNDER_REVIEW) {
      btns.push(
        <Tooltip title="批准" key="approve">
          <Popconfirm title="确认批准此变更？" onConfirm={() => handleApprove(record.id)}>
            <Button type="link" size="small" style={{ color: '#1aae39' }} icon={<CheckOutlined />}>批准</Button>
          </Popconfirm>
        </Tooltip>,
        <Tooltip title="驳回" key="reject">
          <Popconfirm title="确认驳回此变更？" onConfirm={() => handleReject(record.id)}>
            <Button type="link" size="small" danger icon={<CloseOutlined />}>驳回</Button>
          </Popconfirm>
        </Tooltip>,
      )
    } else if (record.status === EhsChangeStatus.APPROVED) {
      btns.push(
        <Tooltip title="开始实施" key="startImpl">
          <Popconfirm title="确认开始实施？" onConfirm={() => handleStartImpl(record.id)}>
            <Button type="link" size="small" icon={<PlayCircleOutlined />}>开始实施</Button>
          </Popconfirm>
        </Tooltip>,
      )
    } else if (record.status === EhsChangeStatus.IN_PROGRESS) {
      btns.push(
        <Tooltip title="投用" key="commission">
          <Popconfirm title="确认投用此变更？" onConfirm={() => handleCommission(record.id)}>
            <Button type="link" size="small" icon={<RocketOutlined />}>投用</Button>
          </Popconfirm>
        </Tooltip>,
      )
    } else if (record.status === EhsChangeStatus.COMMISSIONED) {
      btns.push(
        <Tooltip title="关闭变更" key="close">
          <Popconfirm title="确认关闭此变更？" onConfirm={() => handleClose(record.id)}>
            <Button type="link" size="small" icon={<LockOutlined />}>关闭</Button>
          </Popconfirm>
        </Tooltip>,
      )
    }
    return btns
  }

  const cellText: React.CSSProperties = { fontSize: 12, color: T.slate }
  const cellEmpty: React.CSSProperties = { fontSize: 12, color: T.muted }

  const columns = [
    { title: '变更编号', dataIndex: 'change_no', width: 140,
      render: (_: string, record: EhsChange) => (
        <a
          onClick={() => { setSelectedChange(record); setDrawerOpen(true) }}
          style={{ color: '#0075de', textDecoration: 'none' }}
          onMouseEnter={(e) => { e.currentTarget.style.textDecoration = 'underline' }}
          onMouseLeave={(e) => { e.currentTarget.style.textDecoration = 'none' }}
        >
          <span style={monoFont}>{record.bt_change_no || record.change_no}</span>
        </a>
      ),
    },
    {
      title: '变更名称',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string) => (v ? <span style={{ fontSize: 13, color: T.charcoal }}>{v}</span> : <span style={cellEmpty}>—</span>),
    },
    {
      title: '变更分类',
      dataIndex: 'change_type',
      width: 104,
      render: (v: string | null) => (v ? <span style={cellText}>{CHANGE_TYPE_LABEL[v] || v}</span> : <span style={cellEmpty}>—</span>),
    },
    { title: '变更等级', dataIndex: 'change_grade', width: 88, render: (_: string, r: EhsChange) => <GradePill grade={r.change_grade} /> },
    {
      title: '变更时效',
      dataIndex: 'change_duration',
      width: 80,
      render: (v: string | null) => (v ? <span style={cellText}>{CHANGE_DURATION_LABEL[v] || v}</span> : <span style={cellEmpty}>—</span>),
    },
    { title: '申请部门', dataIndex: 'department', width: 108, ellipsis: true, render: (v: string) => (v ? <span style={cellText}>{v}</span> : <span style={cellEmpty}>—</span>) },
    { title: 'AI审核', dataIndex: 'ai_review_status', width: 88, render: (_: string, r: EhsChange) => <AiConclusionPill change={r} /> },
    { title: '状态', dataIndex: 'status', width: 78, render: (v: string) => <StatusPill status={v} /> },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      fixed: 'right' as const,
      render: (_: unknown, record: EhsChange) => (
        <Space size="small" wrap>
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setSelectedChange(record); setDrawerOpen(true) }}>详情</Button>
          </Tooltip>
          {record.source !== 'bitable' && record.status === EhsChangeStatus.DRAFT && (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>编辑</Button>
          )}
          {record.source !== 'bitable' && renderActionButtons(record)}
          {record.source !== 'bitable' && record.status === EhsChangeStatus.DRAFT && (
            <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  // ── 新建/编辑 ──
  const openCreateModal = () => {
    setEditingChange(null)
    form.resetFields()
    form.setFieldsValue({ change_grade: 'general', change_duration: 'permanent' })
    setModalOpen(true)
  }
  const openEditModal = (record: EhsChange) => {
    setEditingChange(record)
    form.setFieldsValue({
      change_no: record.change_no,
      title: record.title,
      change_type: record.change_type || 'process_tech',
      change_grade: record.change_grade || 'general',
      change_duration: record.change_duration || 'permanent',
      department: record.department,
      applicant_name: record.applicant_name,
      description: record.description,
      expected_effect: record.expected_effect,
      expected_start: record.expected_start || undefined,
      documents_text: record.documents_to_update?.map((d) => d.name).join('；'),
      bt_plan_content: record.bt_plan_content,
      bt_risk_measures: record.bt_risk_measures,
    })
    setModalOpen(true)
  }
  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const { documents_text, ...rest } = values
      const data: EhsChangeFormData = {
        ...rest,
        documents_to_update: documents_text ? [{ name: documents_text }] : undefined,
        expected_start: rest.expected_start || undefined,
      }
      if (editingChange) {
        await updateEhsChange(editingChange.id, data)
        message.success('变更更新成功')
      } else {
        await createEhsChange(data)
        message.success('变更创建成功')
      }
      setModalOpen(false)
      refreshApply()
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return
      message.error('操作失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 22, fontWeight: 600, color: T.ink }}>
            EHS变更审批
          </Title>
          <Text style={{ fontSize: 13, color: T.slate }}>
            基于 T/CCSAS 007-2020 · 工艺技术/设备设施/管理三类变更全生命周期
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['ehs-changes'] })
            queryClient.invalidateQueries({ queryKey: ['ehs-change-stats'] })
          }}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>新建变更</Button>
        </Space>
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
            <Select placeholder="全部分类" allowClear size="small" style={{ width: 140 }} options={CHANGE_TYPE_OPTIONS} value={filters.change_type}
              onChange={(v) => setFilter({ change_type: v })} />
            <Select placeholder="全部时效" allowClear size="small" style={{ width: 120 }} options={CHANGE_DURATION_OPTIONS} value={filters.change_duration}
              onChange={(v) => setFilter({ change_duration: v })} />
            <Select placeholder="全部结论" allowClear size="small" style={{ width: 140 }} options={AI_CONCLUSION_FILTER} value={filters.ai_review_conclusion}
              onChange={(v) => setFilter({ ai_review_conclusion: v })} />
            <Select placeholder="全部状态" allowClear size="small" style={{ width: 120 }} options={STATUS_FILTER} value={filters.status}
              onChange={(v) => setFilter({ status: v })} />
            <Input.Search placeholder="搜索标题/编号" allowClear size="small" style={{ width: 220 }}
              defaultValue={filters.keyword}
              onSearch={(v) => setKeywordFilter(v)} />
          </Space>
          <span style={{ fontSize: 12, color: T.steel }}>共 {total} 条</span>
        </div>
        <Table
          columns={columns}
          dataSource={changes}
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

      {/* 新建/编辑 Modal */}
      <Modal
        title={editingChange ? '编辑EHS变更' : '新建EHS变更'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        width={800}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Title level={5} style={{ marginTop: 0 }}>基本信息</Title>
          <Space size="middle" wrap style={{ width: '100%' }}>
            <Form.Item name="change_no" label="变更编号" rules={[{ required: true, message: '请输入变更编号' }]}>
              <Input placeholder="如 MOC-2026-001" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="title" label="变更名称" rules={[{ required: true, message: '请输入变更名称' }]}>
              <Input placeholder="变更名称" style={{ width: 350 }} />
            </Form.Item>
          </Space>
          <Space size="middle" wrap>
            <Form.Item name="change_type" label="变更分类" rules={[{ required: true }]} initialValue="process_tech">
              <Select options={CHANGE_TYPE_OPTIONS} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="change_grade" label="变更等级" initialValue="general">
              <Select options={[{ value: 'general', label: '一般变更' }, { value: 'major', label: '重大变更' }]} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="change_duration" label="变更期限" initialValue="permanent">
              <Select options={CHANGE_DURATION_OPTIONS} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="department" label="申请部门"><Input placeholder="部门" style={{ width: 140 }} /></Form.Item>
          </Space>
          <Form.Item name="applicant_name" label="申请人"><Input placeholder="申请人姓名" style={{ width: 200 }} /></Form.Item>

          <Title level={5}>变更内容</Title>
          <Form.Item name="description" label="申请变更原因">
            <TextArea rows={4} placeholder="变更原因、需解决的问题或安全风险" />
          </Form.Item>
          <Form.Item name="bt_plan_content" label="变更计划内容">
            <TextArea rows={3} placeholder="实施步骤、时间安排、责任人" />
          </Form.Item>
          <Form.Item name="expected_effect" label="预计效果"><TextArea rows={2} placeholder="预期达到的效果" /></Form.Item>
          <Form.Item name="documents_text" label="需更新的文件资料">
            <Input placeholder="如：操作SOP、P&ID图等（多个用；分隔）" />
          </Form.Item>
          <Form.Item name="bt_risk_measures" label="变更风险评估及建议措施">
            <TextArea rows={3} placeholder="合规/工艺/设备设施/管理风险及控制措施" />
          </Form.Item>

          <Form.Item name="expected_start" label="预计实施日期"><DatePicker style={{ width: 180 }} /></Form.Item>
        </Form>
      </Modal>

      {/* 详情 Drawer */}
      <Drawer
        title={selectedChange ? `变更详情 - ${selectedChange.bt_change_no || selectedChange.change_no}` : '变更详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedChange(null) }}
        width={820}
        extra={selectedChange ? <Space>{renderActionButtons(selectedChange)}</Space> : null}
      >
        {selectedChange && (
          <EhsChangeDetail change={selectedChange} onRefresh={() => afterAction(selectedChange.id)} table="approval" />
        )}
      </Drawer>
    </div>
  )
}
