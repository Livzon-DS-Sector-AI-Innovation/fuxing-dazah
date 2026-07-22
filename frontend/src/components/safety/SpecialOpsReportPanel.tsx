'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Space, Input, Select, DatePicker, Tag, Card,
  Typography, Drawer, App, Tooltip, Modal,
  Form, Row, Col, Switch,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined, PlusOutlined,
  SafetyCertificateOutlined,
  EnvironmentOutlined, ClockCircleOutlined,
  SendOutlined, CheckCircleOutlined, CloseCircleOutlined,
  EditOutlined, DeleteOutlined, EyeOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getSpecialOperationReports,
  createSpecialOperationReport,
  updateSpecialOperationReport,
  deleteSpecialOperationReport,
  submitSpecialOperationReport,
  approveSpecialOperationReport,
  rejectSpecialOperationReport,
  setSpecialOperationReportCritical,
} from '@/actions/safety'
import type { SpecialOperationReport, SpecialOperationReportFormData } from '@/types/safety'

import {
  T, OP_TYPE_CONFIG, OP_LEVEL_LABELS, OP_LEVEL_OPTIONS,
  STATUS_CONFIG, STATUS_OPTIONS,
} from './specialOpsConstants'

const { Text } = Typography
const { TextArea } = Input

// ═══════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════

export default function SpecialOpsReportPanel() {
  const { message } = App.useApp()
  const [form] = Form.useForm()

  // ── Data State ──
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<SpecialOperationReport[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // ── Filters ──
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [opType, setOpType] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // ── Report drawer (create/edit) ──
  const [reportDrawerOpen, setReportDrawerOpen] = useState(false)
  const [editingReport, setEditingReport] = useState<SpecialOperationReport | null>(null)
  const [reportSubmitting, setReportSubmitting] = useState(false)

  // ── Reject modal ──
  const [rejectVisible, setRejectVisible] = useState(false)
  const [rejectId, setRejectId] = useState('')
  const [rejectReason, setRejectReason] = useState('')

  // ── Init form when editing ──
  useEffect(() => {
    if (editingReport && reportDrawerOpen) {
      form.setFieldsValue({
        ...editingReport,
        planned_start_time: editingReport.planned_start_time ? dayjs(editingReport.planned_start_time) : undefined,
        planned_end_time: editingReport.planned_end_time ? dayjs(editingReport.planned_end_time) : undefined,
      })
    }
  }, [editingReport, reportDrawerOpen, form])

  // ── Fetch ──
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getSpecialOperationReports({
        page, page_size: pageSize,
        status: statusFilter || undefined,
        operation_type: opType,
        keyword: keyword || undefined,
      })
      setData(res.data || [])
      setTotal(res.meta?.total || 0)
    } catch {
      message.error('获取数据失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter, opType, keyword])

  useEffect(() => { fetchData() }, [fetchData])

  // ── Open report drawer ──
  const handleCreateReport = () => {
    setEditingReport(null)
    form.resetFields()
    setReportDrawerOpen(true)
  }

  const handleEditReport = (record: SpecialOperationReport) => {
    setEditingReport(record)
    setReportDrawerOpen(true)
  }

  // ── Submit report (create or update) ──
  const handleReportSubmit = async () => {
    try {
      const values = await form.validateFields()
      setReportSubmitting(true)
      const formatted = {
        ...values,
        planned_start_time: values.planned_start_time?.toISOString?.(),
        planned_end_time: values.planned_end_time?.toISOString?.(),
      }
      if (editingReport) {
        const r = await updateSpecialOperationReport(editingReport.id, formatted)
        if (r.code === 200) {
          message.success('已更新')
          setReportDrawerOpen(false)
          fetchData()
        } else {
          message.error(r.message || '更新失败')
        }
      } else {
        const r = await createSpecialOperationReport(formatted as SpecialOperationReportFormData)
        if (r.code === 200) {
          message.success('已创建')
          setReportDrawerOpen(false)
          form.resetFields()
          fetchData()
        } else {
          message.error(r.message || '创建失败')
        }
      }
    } catch {
      // form validation error
    } finally {
      setReportSubmitting(false)
    }
  }

  // ── Delete ──
  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除', content: '确定要删除该报备吗？',
      onOk: async () => {
        const r = await deleteSpecialOperationReport(id)
        if (r.code === 200) { message.success('已删除'); fetchData() }
        else { message.error(r.message || '删除失败') }
      },
    })
  }

  // ── Workflow actions ──
  const handleFlowSubmit = async (id: string) => {
    const r = await submitSpecialOperationReport(id)
    if (r.code === 200) {
      const item = r.data as SpecialOperationReport
      if (item.is_critical) {
        message.success(`已提交 · AI判定为关键作业${item.is_critical_reason ? `（${item.is_critical_reason}）` : ''}`)
      } else {
        message.success(`已提交${item.is_critical_reason ? ` · ${item.is_critical_reason}` : ''}`)
      }
      fetchData()
    }
    else { message.error(r.message || '提交失败') }
  }

  const handleApprove = async (id: string) => {
    const r = await approveSpecialOperationReport(id)
    if (r.code === 200) { message.success('已审批'); fetchData() }
    else { message.error(r.message || '审批失败') }
  }

  const handleOpenReject = (id: string) => { setRejectId(id); setRejectReason(''); setRejectVisible(true) }

  const handleReject = async () => {
    if (!rejectReason.trim()) { message.error('请填写驳回原因'); return }
    const r = await rejectSpecialOperationReport(rejectId, rejectReason)
    if (r.code === 200) { message.success('已驳回'); setRejectVisible(false); fetchData() }
    else { message.error(r.message || '驳回失败') }
  }

  const handleToggleCritical = async (id: string, checked: boolean) => {
    const r = await setSpecialOperationReportCritical(id, checked)
    if (r.code === 200) { message.success(checked ? '已标记为关键作业' : '已取消关键作业标记'); fetchData() }
    else { message.error(r.message || '操作失败') }
  }

  // ── Shared card style ──
  const cardStyle: React.CSSProperties = {
    borderRadius: 12,
    border: `1px solid ${T.hairline}`,
    backgroundColor: T.canvas,
  }

  // ── Columns (per field spec: 编号 | 类型 | 地点 | 内容 | 状态 | 时间 | 关键 | 操作) ──
  const columns: ColumnsType<SpecialOperationReport> = [
    {
      title: '编号', dataIndex: 'report_no', key: 'report_no', width: 130,
      render: (v) => (
        <Text style={{ fontWeight: 500, color: T.charcoal, fontFamily: 'monospace', fontSize: 13 }}>{v}</Text>
      ),
    },
    {
      title: '类型', dataIndex: 'operation_type', key: 'op_type', width: 100,
      render: (v: string) => {
        const cfg = OP_TYPE_CONFIG[v]
        return <Tag style={{ color: cfg?.color, backgroundColor: cfg?.bg, border: 'none', borderRadius: 6, fontWeight: 600, fontSize: 12 }}>{cfg?.label || v}</Tag>
      },
    },
    {
      title: '地点', dataIndex: 'location', key: 'location', width: 120, ellipsis: true,
      render: (v) => (
        <Space size={4}>
          <EnvironmentOutlined style={{ color: T.muted, fontSize: 11 }} />
          <Text style={{ color: T.steel, fontSize: 13 }}>{v || '-'}</Text>
        </Space>
      ),
    },
    {
      title: '内容', dataIndex: 'work_description', key: 'desc', width: 160, ellipsis: true,
      render: (v) => <Tooltip title={v}><Text style={{ fontSize: 13 }}>{v || '-'}</Text></Tooltip>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 85,
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] || { color: T.steel, bg: T.surface, label: s }
        return <Tag style={{ color: cfg.color, backgroundColor: cfg.bg, border: 'none', borderRadius: 6, fontWeight: 600, fontSize: 12 }}>{cfg.label}</Tag>
      },
    },
    {
      title: '时间', dataIndex: 'created_at', key: 'created_at', width: 105,
      render: (v: string, r) => (
        <Tooltip title={`创建: ${v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'}${r.approved_at ? `\n审批: ${dayjs(r.approved_at).format('YYYY-MM-DD HH:mm')}` : ''}`}>
          <Space size={4}>
            <ClockCircleOutlined style={{ color: T.muted, fontSize: 11 }} />
            <Text style={{ color: T.steel, fontSize: 12 }}>{v ? dayjs(v).format('MM-DD HH:mm') : '-'}</Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '关键', dataIndex: 'is_critical', key: 'critical', width: 65,
      render: (v: boolean) => v
        ? <Tag style={{ color: T.error, backgroundColor: T.rose, border: 'none', borderRadius: 6, fontWeight: 600, fontSize: 11 }}>关键</Tag>
        : <Text style={{ color: T.muted, fontSize: 13 }}>-</Text>,
    },
    {
      title: '操作', key: 'action', width: 250, fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          {/* Draft: submit, edit, delete */}
          {record.status === 'draft' && (
            <>
              <Button type="link" size="small" icon={<SendOutlined />}
                style={{ color: T.primary, padding: '0 4px' }}
                onClick={() => handleFlowSubmit(record.id)}
              >提交</Button>
              <Button type="link" size="small" icon={<EditOutlined />}
                style={{ color: '#0075de', padding: '0 4px' }}
                onClick={() => handleEditReport(record)}
              >编辑</Button>
            </>
          )}
          {/* Submitted: approve, reject, edit */}
          {record.status === 'submitted' && (
            <>
              <Button type="link" size="small" icon={<CheckCircleOutlined />}
                style={{ color: T.success, padding: '0 4px' }}
                onClick={() => handleApprove(record.id)}
              >审批</Button>
              <Button type="link" size="small" icon={<CloseCircleOutlined />}
                style={{ color: T.error, padding: '0 4px' }}
                onClick={() => handleOpenReject(record.id)}
              >驳回</Button>
            </>
          )}
          {/* Approved: view only */}
          {record.status === 'approved' && (
            <Button type="link" size="small" icon={<EyeOutlined />}
              style={{ color: T.steel, padding: '0 4px' }}
              onClick={() => handleEditReport(record)}
            >查看</Button>
          )}
          {/* Rejected: edit, delete */}
          {record.status === 'rejected' && (
            <>
              <Button type="link" size="small" icon={<EditOutlined />}
                style={{ color: '#0075de', padding: '0 4px' }}
                onClick={() => handleEditReport(record)}
              >编辑</Button>
            </>
          )}
          {/* Delete for non-approved */}
          {record.status !== 'approved' && (
            <Button type="link" size="small" danger icon={<DeleteOutlined />}
              style={{ padding: '0 4px' }}
              onClick={() => handleDelete(record.id)}
            >删除</Button>
          )}
          {/* Critical toggle */}
          <Tooltip title="关键作业">
            <Switch
              size="small"
              checked={record.is_critical}
              onChange={(v) => handleToggleCritical(record.id, v)}
              style={{ marginLeft: 4 }}
            />
          </Tooltip>
        </Space>
      ),
    },
  ]

  // ── Report form content (per field spec: only ✅ business fields) ──
  const reportFormContent = (
    <Form form={form} layout="vertical">
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="report_no" label="报备编号" rules={[{ required: true, message: '请输入报备编号' }]}>
            <Input placeholder="报备编号" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="operation_type" label="作业类型" rules={[{ required: true, message: '请选择作业类型' }]}>
            <Select
              options={Object.entries(OP_TYPE_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
              placeholder="选择作业类型"
              style={{ borderRadius: 8 }}
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="operation_level" label="作业级别" initialValue="grade2">
            <Select options={OP_LEVEL_OPTIONS} style={{ borderRadius: 8 }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="department" label="报备部门">
            <Input placeholder="部门" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="location" label="作业地点">
            <Input placeholder="地点" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="applicant_name" label="报备申请人">
            <Input placeholder="报备申请人" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="planned_start_time" label="计划开始时间">
            <DatePicker showTime style={{ width: '100%', borderRadius: 8 }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="planned_end_time" label="计划结束时间">
            <DatePicker showTime style={{ width: '100%', borderRadius: 8 }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="work_description" label="作业内容描述">
        <TextArea rows={3} placeholder="作业内容描述" style={{ borderRadius: 8 }} />
      </Form.Item>
      <Form.Item name="notes" label="备注">
        <TextArea rows={2} placeholder="备注" style={{ borderRadius: 8 }} />
      </Form.Item>
    </Form>
  )

  // ── Render ──
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingBottom: 24 }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <Text strong style={{ fontSize: 18, color: T.ink }}>特殊作业报备</Text>
          <div style={{ color: T.slate, fontSize: 13, marginTop: 2 }}>
            GB 30871-2022 · 8类特殊作业报备审批 · 审批通过自动汇入台账
          </div>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreateReport}
          style={{ borderRadius: 8, height: 40, fontWeight: 500 }}
        >
          新建报备
        </Button>
      </div>

      {/* ── Filter Bar ── */}
      <Card
        variant="borderless"
        style={cardStyle}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Space wrap size="middle">
          <Select
            placeholder="状态" allowClear
            style={{ width: 110, borderRadius: 8 }}
            value={statusFilter || undefined}
            onChange={(v) => setStatusFilter(v || '')}
            options={STATUS_OPTIONS}
          />
          <Select
            placeholder="作业类型" allowClear
            style={{ width: 130, borderRadius: 8 }}
            value={opType} onChange={setOpType}
            options={Object.entries(OP_TYPE_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
          />
          <Input
            placeholder="搜索编号/地点/内容"
            prefix={<SearchOutlined style={{ color: T.muted }} />}
            style={{ width: 200, borderRadius: 8 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => { setPage(1); fetchData() }}
            allowClear
          />
          <Button
            icon={<SearchOutlined />}
            onClick={() => { setPage(1); fetchData() }}
            style={{ borderRadius: 8 }}
          >
            查询
          </Button>
        </Space>
      </Card>

      {/* ── Table Card ── */}
      <Card
        variant="borderless"
        style={cardStyle}
        styles={{ body: { padding: 0 } }}
      >
        <Table<SpecialOperationReport>
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1200 }}
          size="middle"
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => <Text style={{ color: T.steel }}>共 {t} 条</Text>,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </Card>

      {/* ── Report Drawer (create/edit) ── */}
      <Drawer
        title={
          <Space>
            <SafetyCertificateOutlined style={{ color: T.primary }} />
            <span>{editingReport ? (editingReport.status === 'approved' ? '查看报备' : '编辑报备') : '新建报备'}</span>
          </Space>
        }
        placement="right"
        size="large"
        open={reportDrawerOpen}
        onClose={() => { setReportDrawerOpen(false); setEditingReport(null) }}
        extra={
          editingReport?.status !== 'approved' ? (
            <Space>
              <Button
                onClick={() => { setReportDrawerOpen(false); setEditingReport(null) }}
                style={{ borderRadius: 8 }}
              >
                取消
              </Button>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                loading={reportSubmitting}
                onClick={handleReportSubmit}
                style={{ borderRadius: 8 }}
              >
                {editingReport ? '更新' : '创建'}
              </Button>
            </Space>
          ) : (
            <Button
              onClick={() => { setReportDrawerOpen(false); setEditingReport(null) }}
              style={{ borderRadius: 8 }}
            >
              关闭
            </Button>
          )
        }
      >
        {reportFormContent}
      </Drawer>

      {/* ── Reject Modal ── */}
      <Modal
        title="驳回原因"
        open={rejectVisible}
        onOk={handleReject}
        onCancel={() => setRejectVisible(false)}
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{
          style: { borderRadius: 8, backgroundColor: T.error, borderColor: T.error },
        }}
        cancelButtonProps={{ style: { borderRadius: 8 } }}
      >
        <TextArea
          rows={4}
          placeholder="请输入驳回原因"
          value={rejectReason}
          onChange={e => setRejectReason(e.target.value)}
          style={{ borderRadius: 8 }}
        />
      </Modal>
    </div>
  )
}
