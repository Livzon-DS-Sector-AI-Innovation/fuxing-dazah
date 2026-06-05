'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  DatePicker,
  Typography,
  Space,
  Tag,
  Spin,
  Popconfirm,
  Descriptions,
  Drawer,
  Tabs,
  InputNumber,
  message,
  Tooltip,
  Badge,
  Timeline,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  SendOutlined,
  CheckOutlined,
  CloseOutlined,
  PlayCircleOutlined,
  RocketOutlined,
  LockOutlined,
  MinusCircleOutlined,
  ExclamationCircleOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import {
  getEhsChanges,
  createEhsChange,
  updateEhsChange,
  deleteEhsChange,
  submitEhsChange,
  approveEhsChange,
  rejectEhsChange,
  startImplementationEhsChange,
  commissionEhsChange,
  closeEhsChange,
  cancelEhsChange,
  addRiskAssessment,
  updateActionItem,
  updatePSSRChecklist,
  submitVerification,
} from '@/actions/safety'
import {
  CHANGE_TYPE_OPTIONS,
  CHANGE_GRADE_OPTIONS,
  CHANGE_DURATION_OPTIONS,
  EHS_CHANGE_STATUS_OPTIONS,
  RISK_LEVEL_OPTIONS,
  RISK_ASSESSMENT_METHOD_OPTIONS,
  APPROVAL_DECISION_OPTIONS,
  ACTION_ITEM_STATUS_OPTIONS,
  PSSR_RESULT_OPTIONS,
  EhsChangeStatus,
} from '@/types/safety'
import type {
  EhsChange,
  EhsChangeFormData,
  RiskAssessmentItem,
  ApprovalChainItem,
  ActionItem,
  PSSRChecklistItem,
} from '@/types/safety'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input
const { RangePicker } = DatePicker

// Status tag colors
const statusColorMap: Record<string, string> = {
  draft: 'default',
  under_review: 'processing',
  approved: 'green',
  rejected: 'red',
  in_progress: 'orange',
  commissioned: 'cyan',
  closed: 'default',
}

const statusLabelMap: Record<string, string> = {
  draft: '草稿',
  under_review: '审核中',
  approved: '已批准',
  rejected: '已驳回',
  in_progress: '实施中',
  commissioned: '已投用',
  closed: '已关闭',
}

export default function EhsChangePage() {
  const [changes, setChanges] = useState<EhsChange[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingChange, setEditingChange] = useState<EhsChange | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  // Detail drawer
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedChange, setSelectedChange] = useState<EhsChange | null>(null)

  // Filters
  const [filters, setFilters] = useState({
    status: undefined as string | undefined,
    change_type: undefined as string | undefined,
    change_grade: undefined as string | undefined,
    change_duration: undefined as string | undefined,
    keyword: undefined as string | undefined,
  })

  // Pagination
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0 })

  const loadChanges = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getEhsChanges({
        page: pagination.page,
        page_size: pagination.page_size,
        ...filters,
      })
      setChanges(res.data || [])
      if (res.meta) {
        setPagination((p) => ({ ...p, total: res.meta!.total || 0 }))
      }
    } catch (error) {
      console.error('Failed to load EHS changes:', error)
    } finally {
      setLoading(false)
    }
  }, [pagination.page, pagination.page_size, filters])

  useEffect(() => {
    loadChanges()
  }, [loadChanges])

  // ── Create / Edit ──

  const openCreateModal = () => {
    setEditingChange(null)
    form.resetFields()
    form.setFieldsValue({
      change_grade: 'general',
      change_duration: 'permanent',
    })
    setModalOpen(true)
  }

  const openEditModal = (record: EhsChange) => {
    setEditingChange(record)
    form.setFieldsValue({
      ...record,
      expected_start: record.expected_start ? record.expected_start : undefined,
      expected_completion: record.expected_completion ? record.expected_completion : undefined,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      const data: EhsChangeFormData = {
        ...values,
        expected_start: values.expected_start || undefined,
        expected_completion: values.expected_completion || undefined,
      }

      if (editingChange) {
        await updateEhsChange(editingChange.id, data)
        message.success('变更更新成功')
      } else {
        await createEhsChange(data)
        message.success('变更创建成功')
      }
      setModalOpen(false)
      loadChanges()
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return // form validation
      message.error('操作失败')
    } finally {
      setSaving(false)
    }
  }

  // ── Workflow Actions ──

  const handleSubmit = async (id: string) => {
    const res = await submitEhsChange(id)
    if (res.code === 0) {
      message.success('变更已提交')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '提交失败')
    }
  }

  const handleApprove = async (id: string, decision: string, comments?: string) => {
    const res = await approveEhsChange(id, decision, comments)
    if (res.code === 0) {
      message.success(decision === 'approved' ? '变更已批准' : '变更已驳回')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleReject = async (id: string) => {
    const res = await rejectEhsChange(id, '驳回')
    if (res.code === 0) {
      message.success('变更已驳回')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '驳回失败')
    }
  }

  const handleStartImpl = async (id: string) => {
    const res = await startImplementationEhsChange(id)
    if (res.code === 0) {
      message.success('变更已开始实施')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleCommission = async (id: string) => {
    const res = await commissionEhsChange(id)
    if (res.code === 0) {
      message.success('变更已投用')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleClose = async (id: string) => {
    const res = await closeEhsChange(id)
    if (res.code === 0) {
      message.success('变更已关闭')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '关闭失败')
    }
  }

  const handleCancel = async (id: string) => {
    const res = await cancelEhsChange(id)
    if (res.code === 0) {
      message.success('变更已取消')
      loadChanges()
      if (selectedChange?.id === id) {
        setSelectedChange(res.data || null)
      }
    } else {
      message.error(res.message || '取消失败')
    }
  }

  const handleDelete = async (id: string) => {
    const res = await deleteEhsChange(id)
    if (res.code === 0) {
      message.success('删除成功')
      loadChanges()
    } else {
      message.error(res.message || '删除失败')
    }
  }

  // ── Detail Drawer ──

  const openDetailDrawer = (record: EhsChange) => {
    setSelectedChange(record)
    setDrawerOpen(true)
  }

  const renderActionButtons = (record: EhsChange) => {
    const btns: React.ReactNode[] = []

    if (record.status === EhsChangeStatus.DRAFT) {
      btns.push(
        <Tooltip title="提交审核" key="submit">
          <Popconfirm title="确认提交此变更申请？" onConfirm={() => handleSubmit(record.id)}>
            <Button type="link" size="small" icon={<SendOutlined />}>提交</Button>
          </Popconfirm>
        </Tooltip>
      )
      btns.push(
        <Tooltip title="取消变更" key="cancel">
          <Popconfirm title="确认取消此变更？" onConfirm={() => handleCancel(record.id)}>
            <Button type="link" size="small" danger icon={<MinusCircleOutlined />}>取消</Button>
          </Popconfirm>
        </Tooltip>
      )
    } else if (record.status === EhsChangeStatus.UNDER_REVIEW) {
      btns.push(
        <Tooltip title="批准" key="approve">
          <Popconfirm title="确认批准此变更？" onConfirm={() => handleApprove(record.id, 'approved')}>
            <Button type="link" size="small" style={{ color: 'green' }} icon={<CheckOutlined />}>批准</Button>
          </Popconfirm>
        </Tooltip>
      )
      btns.push(
        <Tooltip title="驳回" key="reject">
          <Popconfirm title="确认驳回此变更？" onConfirm={() => handleReject(record.id)}>
            <Button type="link" size="small" danger icon={<CloseOutlined />}>驳回</Button>
          </Popconfirm>
        </Tooltip>
      )
    } else if (record.status === EhsChangeStatus.APPROVED) {
      btns.push(
        <Tooltip title="开始实施" key="startImpl">
          <Popconfirm title="确认开始实施？" onConfirm={() => handleStartImpl(record.id)}>
            <Button type="link" size="small" icon={<PlayCircleOutlined />}>开始实施</Button>
          </Popconfirm>
        </Tooltip>
      )
    } else if (record.status === EhsChangeStatus.IN_PROGRESS) {
      btns.push(
        <Tooltip title="投用" key="commission">
          <Popconfirm title="确认投用此变更？" onConfirm={() => handleCommission(record.id)}>
            <Button type="link" size="small" icon={<RocketOutlined />}>投用</Button>
          </Popconfirm>
        </Tooltip>
      )
    } else if (record.status === EhsChangeStatus.COMMISSIONED) {
      btns.push(
        <Tooltip title="关闭变更" key="close">
          <Popconfirm title="确认关闭此变更？" onConfirm={() => handleClose(record.id)}>
            <Button type="link" size="small" icon={<LockOutlined />}>关闭</Button>
          </Popconfirm>
        </Tooltip>
      )
    }
    return btns
  }

  // ── Columns ──

  const columns = [
    {
      title: '变更编号',
      dataIndex: 'change_no',
      width: 160,
      render: (no: string, record: EhsChange) => (
        <a onClick={() => openDetailDrawer(record)}>{no}</a>
      ),
    },
    {
      title: '变更标题',
      dataIndex: 'title',
      ellipsis: true,
    },
    {
      title: '变更类型',
      dataIndex: 'change_type',
      width: 120,
      render: (v: string) => {
        const opt = CHANGE_TYPE_OPTIONS.find((o) => o.value === v)
        return <Tag>{opt?.label || v}</Tag>
      },
    },
    {
      title: '变更等级',
      dataIndex: 'change_grade',
      width: 100,
      render: (v: string) => {
        const opt = CHANGE_GRADE_OPTIONS.find((o) => o.value === v)
        return <Tag color={opt?.color}>{opt?.label || v}</Tag>
      },
    },
    {
      title: '变更期限',
      dataIndex: 'change_duration',
      width: 100,
      render: (v: string) => {
        const opt = CHANGE_DURATION_OPTIONS.find((o) => o.value === v)
        return <Tag color={opt?.color}>{opt?.label || v}</Tag>
      },
    },
    {
      title: '申请部门',
      dataIndex: 'department',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => (
        <Tag color={statusColorMap[v] || 'default'}>{statusLabelMap[v] || v}</Tag>
      ),
    },
    {
      title: '申请人',
      dataIndex: 'applicant_name',
      width: 100,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: unknown, record: EhsChange) => (
        <Space size="small" wrap>
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetailDrawer(record)}>
              详情
            </Button>
          </Tooltip>
          {record.status === EhsChangeStatus.DRAFT && (
            <Tooltip title="编辑">
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>
                编辑
              </Button>
            </Tooltip>
          )}
          {renderActionButtons(record)}
          {record.status === EhsChangeStatus.DRAFT && (
            <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  // ==================== Render ====================

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Title level={4} className="mb-1">EHS变更管理</Title>
          <Text type="secondary">基于 T/CCSAS 007-2020 标准，管理工艺技术、设备设施、管理三类变更的全生命周期</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          新建变更
        </Button>
      </div>

      {/* Filters */}
      <Card size="small" variant="borderless" className="shadow-sm">
        <Space wrap>
          <Select
            placeholder="变更类型"
            allowClear
            style={{ width: 140 }}
            options={CHANGE_TYPE_OPTIONS}
            value={filters.change_type}
            onChange={(v) => setFilters((f) => ({ ...f, change_type: v }))}
          />
          <Select
            placeholder="变更等级"
            allowClear
            style={{ width: 120 }}
            options={CHANGE_GRADE_OPTIONS}
            value={filters.change_grade}
            onChange={(v) => setFilters((f) => ({ ...f, change_grade: v }))}
          />
          <Select
            placeholder="变更期限"
            allowClear
            style={{ width: 120 }}
            options={CHANGE_DURATION_OPTIONS}
            value={filters.change_duration}
            onChange={(v) => setFilters((f) => ({ ...f, change_duration: v }))}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 120 }}
            options={EHS_CHANGE_STATUS_OPTIONS}
            value={filters.status}
            onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
          />
          <Input.Search
            placeholder="搜索标题"
            allowClear
            style={{ width: 250 }}
            onSearch={(v) => setFilters((f) => ({ ...f, keyword: v || undefined }))}
          />
        </Space>
      </Card>

      {/* Table */}
      <Card variant="borderless" className="shadow-sm">
        <Table
          columns={columns}
          dataSource={changes}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.page_size,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => setPagination((p) => ({ ...p, page, page_size: pageSize })),
          }}
        />
      </Card>

      {/* Create/Edit Modal */}
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
          <Title level={5} className="mb-3">基本信息</Title>
          <Space size="middle" wrap className="w-full">
            <Form.Item name="change_no" label="变更编号" rules={[{ required: true, message: '请输入变更编号' }]}>
              <Input placeholder="如 MOC-2026-001" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="title" label="变更标题" rules={[{ required: true, message: '请输入变更标题' }]}>
              <Input placeholder="变更标题" style={{ width: 350 }} />
            </Form.Item>
          </Space>
          <Space size="middle" wrap>
            <Form.Item name="change_type" label="变更类型" rules={[{ required: true }]} initialValue="process_tech">
              <Select options={CHANGE_TYPE_OPTIONS} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="change_grade" label="变更等级" initialValue="general">
              <Select options={CHANGE_GRADE_OPTIONS} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="change_duration" label="变更期限" initialValue="permanent">
              <Select options={CHANGE_DURATION_OPTIONS} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="department" label="申请部门">
              <Input placeholder="部门" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="location_unit" label="所在单元/装置">
              <Input placeholder="装置/单元" style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="applicant_name" label="申请人">
            <Input placeholder="申请人姓名" style={{ width: 200 }} />
          </Form.Item>

          <Title level={5} className="mb-3 mt-4">变更详情</Title>
          <Form.Item name="description" label="变更描述（变更前/变更后对比）">
            <TextArea rows={4} placeholder="详细描述变更内容和前后对比" />
          </Form.Item>
          <Form.Item name="technical_basis" label="变更技术依据">
            <TextArea rows={3} placeholder="技术依据、法规要求等" />
          </Form.Item>
          <Form.Item name="expected_effect" label="预期效果">
            <TextArea rows={2} placeholder="预期达到的效果" />
          </Form.Item>

          <Title level={5} className="mb-3 mt-4">计划</Title>
          <Space size="middle" wrap>
            <Form.Item name="expected_start" label="预期开始日期">
              <DatePicker style={{ width: 180 }} />
            </Form.Item>
            <Form.Item name="expected_completion" label="预期完成日期">
              <DatePicker style={{ width: 180 }} />
            </Form.Item>
          </Space>

          <Form.Item name="notes" label="备注">
            <TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Drawer */}
      <Drawer
        title={selectedChange ? `变更详情 - ${selectedChange.change_no}` : '变更详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedChange(null) }}
        width={800}
        extra={
          selectedChange ? (
            <Space>
              {renderActionButtons(selectedChange)}
            </Space>
          ) : null
        }
      >
        {selectedChange && <EhsChangeDetail change={selectedChange} onRefresh={loadChanges} />}
      </Drawer>
    </div>
  )
}


// ==================== Detail Component ====================

function EhsChangeDetail({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  return (
    <Tabs
      defaultActiveKey="basic"
      items={[
        {
          key: 'basic',
          label: '基本信息',
          children: <BasicInfoTab change={change} />,
        },
        {
          key: 'risk',
          label: (
            <span>
              风险评估
              {change.risk_assessments && change.risk_assessments.length > 0 && (
                <Badge count={change.risk_assessments.length} size="small" style={{ marginLeft: 4 }} />
              )}
            </span>
          ),
          children: <RiskAssessmentTab change={change} onRefresh={onRefresh} />,
        },
        {
          key: 'approval',
          label: (
            <span>
              审批链
              {change.approval_chain && change.approval_chain.length > 0 && (
                <Badge count={change.approval_chain.length} size="small" style={{ marginLeft: 4 }} />
              )}
            </span>
          ),
          children: <ApprovalChainTab change={change} />,
        },
        {
          key: 'actions',
          label: (
            <span>
              行动项
              {change.action_items && change.action_items.length > 0 && (
                <Badge count={change.action_items.filter((a) => a.status !== 'completed').length} size="small" style={{ marginLeft: 4 }} />
              )}
            </span>
          ),
          children: <ActionItemsTab change={change} onRefresh={onRefresh} />,
        },
        {
          key: 'pssr',
          label: 'PSSR检查',
          children: <PSSRTab change={change} onRefresh={onRefresh} />,
        },
        {
          key: 'verification',
          label: '验证与关闭',
          children: <VerificationTab change={change} onRefresh={onRefresh} />,
        },
      ]}
    />
  )
}


// ── Tab: Basic Info ──

function BasicInfoTab({ change }: { change: EhsChange }) {
  return (
    <Descriptions column={2} bordered size="small">
      <Descriptions.Item label="变更编号">{change.change_no}</Descriptions.Item>
      <Descriptions.Item label="变更标题">{change.title}</Descriptions.Item>
      <Descriptions.Item label="变更类型">
        <Tag>{CHANGE_TYPE_OPTIONS.find((o) => o.value === change.change_type)?.label}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="变更等级">
        <Tag color={CHANGE_GRADE_OPTIONS.find((o) => o.value === change.change_grade)?.color}>
          {CHANGE_GRADE_OPTIONS.find((o) => o.value === change.change_grade)?.label}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="变更期限">
        <Tag color={CHANGE_DURATION_OPTIONS.find((o) => o.value === change.change_duration)?.color}>
          {CHANGE_DURATION_OPTIONS.find((o) => o.value === change.change_duration)?.label}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="状态">
        <Tag color={statusColorMap[change.status]}>{statusLabelMap[change.status]}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="申请部门">{change.department || '-'}</Descriptions.Item>
      <Descriptions.Item label="所在单元/装置">{change.location_unit || '-'}</Descriptions.Item>
      <Descriptions.Item label="申请人">{change.applicant_name || '-'}</Descriptions.Item>
      <Descriptions.Item label="创建时间">{new Date(change.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
      <Descriptions.Item label="预期开始">{change.expected_start ? new Date(change.expected_start).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
      <Descriptions.Item label="预期完成">{change.expected_completion ? new Date(change.expected_completion).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
      <Descriptions.Item label="实际开始">{change.actual_start ? new Date(change.actual_start).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
      <Descriptions.Item label="实际完成">{change.actual_completion ? new Date(change.actual_completion).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
      <Descriptions.Item label="变更描述" span={2}>
        <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{change.description || '-'}</Paragraph>
      </Descriptions.Item>
      <Descriptions.Item label="技术依据" span={2}>
        <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{change.technical_basis || '-'}</Paragraph>
      </Descriptions.Item>
      <Descriptions.Item label="预期效果" span={2}>
        <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{change.expected_effect || '-'}</Paragraph>
      </Descriptions.Item>
      <Descriptions.Item label="备注" span={2}>{change.notes || '-'}</Descriptions.Item>
    </Descriptions>
  )
}


// ── Tab: Risk Assessment ──

function RiskAssessmentTab({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  const [adding, setAdding] = useState(false)
  const [assessmentForm] = Form.useForm()

  const handleAddAssessment = async () => {
    try {
      const values = await assessmentForm.validateFields()
      const res = await addRiskAssessment(change.id, values)
      if (res.code === 0) {
        message.success('风险评估记录已添加')
        setAdding(false)
        assessmentForm.resetFields()
        onRefresh()
      } else {
        message.error(res.message || '添加失败')
      }
    } catch {
      // form validation
    }
  }

  const assessments = change.risk_assessments || []

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <Text strong>风险评估记录</Text>
        <Button type="dashed" icon={<PlusOutlined />} onClick={() => setAdding(true)}>
          添加评估
        </Button>
      </div>

      {adding && (
        <Card size="small" className="mb-4">
          <Form form={assessmentForm} layout="vertical">
            <Space size="small" wrap>
              <Form.Item name="method" label="评估方法" rules={[{ required: true }]}>
                <Select options={RISK_ASSESSMENT_METHOD_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="risk_level" label="风险等级">
                <Select options={RISK_LEVEL_OPTIONS} style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="assessed_by" label="评估人">
                <Input style={{ width: 120 }} />
              </Form.Item>
            </Space>
            <Form.Item name="description" label="风险描述">
              <TextArea rows={2} />
            </Form.Item>
            <Form.Item name="control_measures" label="控制措施">
              <TextArea rows={2} />
            </Form.Item>
            <Space>
              <Button type="primary" onClick={handleAddAssessment}>保存</Button>
              <Button onClick={() => setAdding(false)}>取消</Button>
            </Space>
          </Form>
        </Card>
      )}

      {assessments.length === 0 ? (
        <Text type="secondary">暂无风险评估记录</Text>
      ) : (
        assessments.map((item, idx) => (
          <Card key={idx} size="small" className="mb-2" title={`评估 #${idx + 1} - ${item.method || '未知方法'}`}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="风险等级">
                <Tag color={RISK_LEVEL_OPTIONS.find((o) => o.value === item.risk_level)?.color}>
                  {RISK_LEVEL_OPTIONS.find((o) => o.value === item.risk_level)?.label || item.risk_level || '-'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="评估人">{item.assessed_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="风险描述" span={2}>{item.description || '-'}</Descriptions.Item>
              <Descriptions.Item label="控制措施" span={2}>{item.control_measures || '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        ))
      )}
    </div>
  )
}


// ── Tab: Approval Chain ──

function ApprovalChainTab({ change }: { change: EhsChange }) {
  const chain = change.approval_chain || []

  if (chain.length === 0) {
    return <Text type="secondary">暂无审批记录</Text>
  }

  return (
    <Timeline
      items={chain.map((item, idx) => {
        const decisionOpt = APPROVAL_DECISION_OPTIONS.find((o) => o.value === item.decision)
        return {
          key: idx,
          color: item.decision === 'approved' ? 'green' : item.decision === 'rejected' ? 'red' : 'gray',
          children: (
            <div>
              <div className="flex items-center gap-2">
                <Text strong>第{item.level}级审批</Text>
                <Tag color={decisionOpt?.color}>{decisionOpt?.label || item.decision}</Tag>
                <Text type="secondary">- {item.approver_role}</Text>
              </div>
              {item.approver && <Text type="secondary">审批人: {item.approver}</Text>}
              {item.comments && <Paragraph type="secondary" className="mt-1">{item.comments}</Paragraph>}
              {item.decided_at && (
                <div><Text type="secondary" className="text-xs">{new Date(item.decided_at).toLocaleString('zh-CN')}</Text></div>
              )}
            </div>
          ),
        }
      })}
    />
  )
}


// ── Tab: Action Items ──

function ActionItemsTab({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  const items = change.action_items || []

  const handleToggleStatus = async (index: number, currentStatus: string) => {
    const nextStatus = currentStatus === 'completed' ? 'pending' : currentStatus === 'in_progress' ? 'completed' : 'in_progress'
    const res = await updateActionItem(change.id, index, nextStatus)
    if (res.code === 0) {
      message.success('行动项状态已更新')
      if (res.data) {
        // Trigger refresh by reloading
      }
      onRefresh()
    } else {
      message.error(res.message || '更新失败')
    }
  }

  if (items.length === 0) {
    return <Text type="secondary">暂无行动项</Text>
  }

  return (
    <div>
      {items.map((item, idx) => {
        const statusOpt = ACTION_ITEM_STATUS_OPTIONS.find((o) => o.value === item.status)
        return (
          <Card key={idx} size="small" className="mb-2">
            <div className="flex items-center justify-between">
              <div>
                <Text strong>{item.task}</Text>
                <div>
                  <Text type="secondary">责任人: {item.owner || '-'}</Text>
                  {item.due_date && <Text type="secondary" className="ml-2">截止: {item.due_date}</Text>}
                </div>
              </div>
              <Space>
                <Tag>{statusOpt?.label || item.status}</Tag>
                <Button
                  size="small"
                  onClick={() => handleToggleStatus(idx, item.status || 'pending')}
                >
                  {item.status === 'completed' ? '重开' : item.status === 'in_progress' ? '完成' : '开始'}
                </Button>
              </Space>
            </div>
          </Card>
        )
      })}
    </div>
  )
}


// ── Tab: PSSR ──

function PSSRTab({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  const items = change.pssr_checklist || []

  const handleToggleResult = async (index: number, currentResult: string) => {
    const nextResult = currentResult === 'pass' ? 'fail' : currentResult === 'fail' ? 'na' : 'pass'
    const updated = items.map((item, idx) =>
      idx === index ? { ...item, result: nextResult } : item
    )
    const res = await updatePSSRChecklist(change.id, updated)
    if (res.code === 0) {
      message.success('PSSR检查结果已更新')
      onRefresh()
    } else {
      message.error(res.message || '更新失败')
    }
  }

  if (items.length === 0) {
    return <Text type="secondary">暂无PSSR检查清单</Text>
  }

  return (
    <div>
      {items.map((item, idx) => {
        const resultOpt = PSSR_RESULT_OPTIONS.find((o) => o.value === item.result)
        return (
          <Card key={idx} size="small" className="mb-2">
            <div className="flex items-center justify-between">
              <div>
                <Text>{item.item}</Text>
                {item.remarks && <div><Text type="secondary" className="text-xs">{item.remarks}</Text></div>}
              </div>
              <Space>
                <Tag color={resultOpt?.color || 'default'}>{resultOpt?.label || item.result}</Tag>
                <Button size="small" onClick={() => handleToggleResult(idx, item.result || 'na')}>
                  切换
                </Button>
              </Space>
            </div>
          </Card>
        )
      })}
    </div>
  )
}


// ── Tab: Verification & Closure ──

function VerificationTab({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const verification = change.verification
  const closure = change.closure

  const handleSaveVerification = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const res = await submitVerification(change.id, values)
      if (res.code === 0) {
        message.success('验证数据已保存')
        onRefresh()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      // validation error
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Verification */}
      <Card title="变更验证" size="small">
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            expected_effect_achieved: verification?.expected_effect_achieved,
            comments: verification?.comments,
            psi_updated: verification?.psi_updated,
            documents_updated: verification?.documents_updated,
            accepted_by: verification?.accepted_by,
          }}
        >
          <Space size="middle" wrap>
            <Form.Item name="expected_effect_achieved" label="预期效果达成">
              <Select
                style={{ width: 120 }}
                options={[
                  { value: true, label: '是' },
                  { value: false, label: '否' },
                ]}
              />
            </Form.Item>
            <Form.Item name="psi_updated" label="PSI已更新">
              <Select
                style={{ width: 120 }}
                options={[
                  { value: true, label: '是' },
                  { value: false, label: '否' },
                ]}
              />
            </Form.Item>
            <Form.Item name="documents_updated" label="文件已更新">
              <Select
                style={{ width: 120 }}
                options={[
                  { value: true, label: '是' },
                  { value: false, label: '否' },
                ]}
              />
            </Form.Item>
            <Form.Item name="accepted_by" label="验收人">
              <Input style={{ width: 150 }} />
            </Form.Item>
          </Space>
          <Form.Item name="comments" label="验证意见">
            <TextArea rows={3} />
          </Form.Item>
          <Button type="primary" onClick={handleSaveVerification} loading={saving}>
            保存验证数据
          </Button>
        </Form>
      </Card>

      {/* Closure */}
      <Card title="变更关闭" size="small">
        {closure ? (
          <Descriptions column={2} size="small">
            <Descriptions.Item label="关闭人">{closure.closed_by || '-'}</Descriptions.Item>
            <Descriptions.Item label="关闭日期">
              {closure.closed_date ? new Date(closure.closed_date).toLocaleString('zh-CN') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="临时变更到期">
              {closure.temp_expiry_date || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="恢复原状日期">
              {closure.restored_date || '-'}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Text type="secondary">变更尚未关闭</Text>
        )}
      </Card>
    </div>
  )
}
