'use client'

import { useEffect, useState, useCallback } from 'react'
import {
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
  Tooltip,
  Card,
  message,
  Row,
  Col,
  Divider,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  VerifiedOutlined,
  WarningOutlined,
  ExperimentOutlined,
  HeartOutlined,
  ExclamationCircleOutlined,
  FileAddOutlined,
} from '@ant-design/icons'
import {
  getOhHazardMonitors,
  getOhHazardMonitor,
  createOhHazardMonitor,
  updateOhHazardMonitor,
  deleteOhHazardMonitor,
  startMonitor,
  completeMonitor,
  verifyMonitor,
  addDetectionResult,
  updateDetectionResult,
  deleteDetectionResult,
  addMonitorAbnormality,
  updateMonitorAbnormalityStatus,
  getOhHealthExams,
  getOhHealthExam,
  createOhHealthExam,
  updateOhHealthExam,
  deleteOhHealthExam,
  startExam,
  completeExam,
  archiveExam,
  addExamItem,
  updateExamItem,
  deleteExamItem,
  setExamConclusion,
  addExamAbnormality,
  updateExamAbnormalityStatus,
} from '@/actions/safety'
import {
  MonitorStatus,
  MONITOR_STATUS_OPTIONS,
  DetectionType,
  DETECTION_TYPE_OPTIONS,
  HazardFactorCategory,
  HAZARD_FACTOR_CATEGORY_OPTIONS,
  OELComplianceStatus,
  OEL_COMPLIANCE_STATUS_OPTIONS,
  ExamStatus,
  EXAM_STATUS_OPTIONS,
  ExamType,
  EXAM_TYPE_OPTIONS,
  ExamConclusion,
  EXAM_CONCLUSION_OPTIONS,
  AbnormalityStatus,
  ABNORMALITY_STATUS_OPTIONS,
  type OhHazardMonitor,
  type OhHealthExam,
  type DetectionResultItem,
  type ExamResultItem,
  type AbnormalityRecord,
} from '@/types/safety'

const { Title, Text } = Typography
const { TextArea } = Input

/* ============================== Helpers ============================== */

const monitorStatusColorMap: Record<string, string> = {
  draft: 'default',
  in_progress: 'processing',
  completed: 'green',
  verified: 'cyan',
}
const monitorStatusLabelMap: Record<string, string> = {
  draft: '草稿',
  in_progress: '检测中',
  completed: '已完成',
  verified: '已验证',
}

const examStatusColorMap: Record<string, string> = {
  scheduled: 'default',
  in_progress: 'processing',
  completed: 'green',
  archived: 'default',
}
const examStatusLabelMap: Record<string, string> = {
  scheduled: '已安排',
  in_progress: '体检中',
  completed: '已完成',
  archived: '已归档',
}

const conclusionColorMap: Record<string, string> = {
  normal: 'green',
  abnormal_other: 'orange',
  suspected_od: 'red',
  od_diagnosed: 'red',
  contraindicated: 'red',
  re_examination: 'blue',
}

export default function OccupationalHealthPage() {
  /* ======================== Monitor State ======================== */
  const [monitors, setMonitors] = useState<OhHazardMonitor[]>([])
  const [monitorLoading, setMonitorLoading] = useState(true)
  const [monitorModalOpen, setMonitorModalOpen] = useState(false)
  const [editingMonitor, setEditingMonitor] = useState<OhHazardMonitor | null>(null)
  const [monitorSaving, setMonitorSaving] = useState(false)
  const [monitorForm] = Form.useForm()
  const [monitorDrawerOpen, setMonitorDrawerOpen] = useState(false)
  const [selectedMonitor, setSelectedMonitor] = useState<OhHazardMonitor | null>(null)
  const [monitorFilters, setMonitorFilters] = useState({
    status: undefined as string | undefined,
    detection_type: undefined as string | undefined,
    workplace: undefined as string | undefined,
    keyword: undefined as string | undefined,
  })
  const [monitorPagination, setMonitorPagination] = useState({ page: 1, page_size: 20, total: 0 })

  /* ======================== Exam State ======================== */
  const [exams, setExams] = useState<OhHealthExam[]>([])
  const [examLoading, setExamLoading] = useState(true)
  const [examModalOpen, setExamModalOpen] = useState(false)
  const [editingExam, setEditingExam] = useState<OhHealthExam | null>(null)
  const [examSaving, setExamSaving] = useState(false)
  const [examForm] = Form.useForm()
  const [examDrawerOpen, setExamDrawerOpen] = useState(false)
  const [selectedExam, setSelectedExam] = useState<OhHealthExam | null>(null)
  const [examFilters, setExamFilters] = useState({
    status: undefined as string | undefined,
    exam_type: undefined as string | undefined,
    department: undefined as string | undefined,
    keyword: undefined as string | undefined,
  })
  const [exampagination, setExamPagination] = useState({ page: 1, page_size: 20, total: 0 })

  /* ===================== Monitor Data Loading ===================== */
  const loadMonitors = useCallback(async () => {
    setMonitorLoading(true)
    try {
      const res = await getOhHazardMonitors({
        page: monitorPagination.page,
        page_size: monitorPagination.page_size,
        ...monitorFilters,
      })
      setMonitors(res.data || [])
      if (res.meta) {
        setMonitorPagination((p) => ({ ...p, total: res.meta!.total || 0 }))
      }
    } catch (error) {
      console.error('Failed to load monitors:', error)
    } finally {
      setMonitorLoading(false)
    }
  }, [monitorPagination.page, monitorPagination.page_size, monitorFilters])

  useEffect(() => { loadMonitors() }, [loadMonitors])

  /* ===================== Exam Data Loading ===================== */
  const loadExams = useCallback(async () => {
    setExamLoading(true)
    try {
      const res = await getOhHealthExams({
        page: exampagination.page,
        page_size: exampagination.page_size,
        ...examFilters,
      })
      setExams(res.data || [])
      if (res.meta) {
        setExamPagination((p) => ({ ...p, total: res.meta!.total || 0 }))
      }
    } catch (error) {
      console.error('Failed to load exams:', error)
    } finally {
      setExamLoading(false)
    }
  }, [exampagination.page, exampagination.page_size, examFilters])

  useEffect(() => { loadExams() }, [loadExams])

  /* ===================== Monitor Modal ===================== */
  const openMonitorCreateModal = () => {
    setEditingMonitor(null)
    monitorForm.resetFields()
    setMonitorModalOpen(true)
  }

  const openMonitorEditModal = (record: OhHazardMonitor) => {
    setEditingMonitor(record)
    monitorForm.setFieldsValue({
      monitor_no: record.monitor_no,
      workplace: record.workplace,
      location: record.location,
      equipment_info: record.equipment_info,
      detection_type: record.detection_type,
      detection_agency: record.detection_agency,
      inspector_name: record.inspector_name,
      notes: record.notes,
    })
    setMonitorModalOpen(true)
  }

  const handleMonitorSave = async () => {
    try {
      const values = await monitorForm.validateFields()
      setMonitorSaving(true)
      let res
      if (editingMonitor) {
        res = await updateOhHazardMonitor(editingMonitor.id, values)
      } else {
        res = await createOhHazardMonitor(values)
      }
      if (res.code === 0) {
        message.success(editingMonitor ? '监测记录已更新' : '监测记录已创建')
        setMonitorModalOpen(false)
        loadMonitors()
      } else {
        message.error(res.message || '操作失败')
      }
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'errorFields' in error) {
        // form validation error, silently ignore
      } else {
        message.error('操作失败')
      }
    } finally {
      setMonitorSaving(false)
    }
  }

  /* ===================== Monitor Workflow ===================== */
  const handleStartMonitor = async (id: string) => {
    const res = await startMonitor(id)
    if (res.code === 0) {
      message.success('已开始监测')
      loadMonitors()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleCompleteMonitor = async (id: string) => {
    const res = await completeMonitor(id)
    if (res.code === 0) {
      message.success('监测已完成，已自动计算OEL合规状态')
      loadMonitors()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleVerifyMonitor = async (id: string) => {
    const res = await verifyMonitor(id, {})
    if (res.code === 0) {
      message.success('监测已验证')
      loadMonitors()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleDeleteMonitor = async (id: string) => {
    const res = await deleteOhHazardMonitor(id)
    if (res.code === 0) {
      message.success('已删除')
      loadMonitors()
    } else {
      message.error(res.message || '删除失败')
    }
  }

  /* ===================== Monitor Detail Drawer ===================== */
  const openMonitorDetail = async (record: OhHazardMonitor) => {
    const res = await getOhHazardMonitor(record.id)
    if (res.code === 0 && res.data) {
      setSelectedMonitor(res.data)
    } else {
      setSelectedMonitor(record)
    }
    setMonitorDrawerOpen(true)
  }

  /* ===================== Exam Modal ===================== */
  const openExamCreateModal = () => {
    setEditingExam(null)
    examForm.resetFields()
    setExamModalOpen(true)
  }

  const openExamEditModal = (record: OhHealthExam) => {
    setEditingExam(record)
    examForm.setFieldsValue({
      exam_no: record.exam_no,
      employee_name: record.employee_name,
      employee_id: record.employee_id,
      department: record.department,
      job_position: record.job_position,
      exam_type: record.exam_type,
      exam_agency: record.exam_agency,
      hazard_factors: record.hazard_factors,
      notes: record.notes,
    })
    setExamModalOpen(true)
  }

  const handleExamSave = async () => {
    try {
      const values = await examForm.validateFields()
      setExamSaving(true)
      let res
      if (editingExam) {
        res = await updateOhHealthExam(editingExam.id, values)
      } else {
        res = await createOhHealthExam(values)
      }
      if (res.code === 0) {
        message.success(editingExam ? '体检记录已更新' : '体检记录已创建')
        setExamModalOpen(false)
        loadExams()
      } else {
        message.error(res.message || '操作失败')
      }
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'errorFields' in error) {
        // form validation error
      } else {
        message.error('操作失败')
      }
    } finally {
      setExamSaving(false)
    }
  }

  /* ===================== Exam Workflow ===================== */
  const handleStartExam = async (id: string) => {
    const res = await startExam(id)
    if (res.code === 0) {
      message.success('已开始体检')
      loadExams()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleCompleteExam = async (id: string) => {
    const res = await completeExam(id)
    if (res.code === 0) {
      message.success('体检已完成')
      loadExams()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleArchiveExam = async (id: string) => {
    const res = await archiveExam(id)
    if (res.code === 0) {
      message.success('体检已归档')
      loadExams()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleDeleteExam = async (id: string) => {
    const res = await deleteOhHealthExam(id)
    if (res.code === 0) {
      message.success('已删除')
      loadExams()
    } else {
      message.error(res.message || '删除失败')
    }
  }

  /* ===================== Exam Detail Drawer ===================== */
  const openExamDetail = async (record: OhHealthExam) => {
    const res = await getOhHealthExam(record.id)
    if (res.code === 0 && res.data) {
      setSelectedExam(res.data)
    } else {
      setSelectedExam(record)
    }
    setExamDrawerOpen(true)
  }

  /* ===================== Monitor Table Columns ===================== */
  const monitorColumns = [
    {
      title: '监测编号',
      dataIndex: 'monitor_no',
      width: 160,
      render: (v: string, record: OhHazardMonitor) => (
        <a onClick={() => openMonitorDetail(record)}>{v}</a>
      ),
    },
    { title: '监测场所', dataIndex: 'workplace', width: 150, ellipsis: true },
    {
      title: '检测类型',
      dataIndex: 'detection_type',
      width: 110,
      render: (v: string) => (
        <Tag>{DETECTION_TYPE_OPTIONS.find((o) => o.value === v)?.label || v}</Tag>
      ),
    },
    {
      title: '检测日期',
      dataIndex: 'detection_date',
      width: 130,
      render: (v: string | null) => (v ? new Date(v).toLocaleDateString('zh-CN') : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => (
        <Tag color={monitorStatusColorMap[v] || 'default'}>
          {monitorStatusLabelMap[v] || v}
        </Tag>
      ),
    },
    { title: '检测人员', dataIndex: 'inspector_name', width: 100 },
    {
      title: '检测结果',
      dataIndex: 'detection_results',
      width: 120,
      render: (v: DetectionResultItem[] | undefined) => {
        if (!v || v.length === 0) return <Text type="secondary">暂无</Text>
        const exceeding = v.filter((r) => r.compliance_status === 'exceeding').length
        return (
          <Space>
            <Text>{v.length} 项</Text>
            {exceeding > 0 && <Tag color="red">{exceeding} 项超标</Tag>}
          </Space>
        )
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      width: 280,
      render: (_: unknown, record: OhHazardMonitor) => (
        <Space size="small">
          {record.status === MonitorStatus.DRAFT && (
            <>
              <Tooltip title="编辑"><Button type="link" size="small" icon={<EditOutlined />} onClick={() => openMonitorEditModal(record)} /></Tooltip>
              <Tooltip title="开始监测"><Popconfirm title="确认开始监测？" onConfirm={() => handleStartMonitor(record.id)}><Button type="link" size="small" icon={<PlayCircleOutlined />} /></Popconfirm></Tooltip>
              <Tooltip title="删除"><Popconfirm title="确认删除？" onConfirm={() => handleDeleteMonitor(record.id)}><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Popconfirm></Tooltip>
            </>
          )}
          {record.status === MonitorStatus.IN_PROGRESS && (
            <Tooltip title="完成监测"><Popconfirm title="确认完成监测？将自动计算OEL合规状态" onConfirm={() => handleCompleteMonitor(record.id)}><Button type="link" size="small" icon={<CheckCircleOutlined />}>完成</Button></Popconfirm></Tooltip>
          )}
          {record.status === MonitorStatus.COMPLETED && (
            <Tooltip title="验证"><Popconfirm title="确认验证通过？" onConfirm={() => handleVerifyMonitor(record.id)}><Button type="link" size="small" icon={<VerifiedOutlined />}>验证</Button></Popconfirm></Tooltip>
          )}
          <Tooltip title="详情"><Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openMonitorDetail(record)} /></Tooltip>
        </Space>
      ),
    },
  ]

  /* ===================== Exam Table Columns ===================== */
  const examColumns = [
    {
      title: '体检编号',
      dataIndex: 'exam_no',
      width: 160,
      render: (v: string, record: OhHealthExam) => (
        <a onClick={() => openExamDetail(record)}>{v}</a>
      ),
    },
    { title: '员工姓名', dataIndex: 'employee_name', width: 100 },
    { title: '部门', dataIndex: 'department', width: 120, ellipsis: true },
    {
      title: '体检类型',
      dataIndex: 'exam_type',
      width: 110,
      render: (v: string) => (
        <Tag>{EXAM_TYPE_OPTIONS.find((o) => o.value === v)?.label || v}</Tag>
      ),
    },
    {
      title: '体检日期',
      dataIndex: 'exam_date',
      width: 130,
      render: (v: string | null) => (v ? new Date(v).toLocaleDateString('zh-CN') : '-'),
    },
    {
      title: '体检结论',
      dataIndex: 'overall_conclusion',
      width: 140,
      render: (v: string | null) => {
        if (!v) return <Text type="secondary">-</Text>
        const color = conclusionColorMap[v] || 'default'
        const label = EXAM_CONCLUSION_OPTIONS.find((o) => o.value === v)?.label || v
        return (
          <Space>
            <Tag color={color}>{label}</Tag>
            {['suspected_od', 'od_diagnosed', 'contraindicated'].includes(v) && (
              <ExclamationCircleOutlined style={{ color: '#e03131' }} />
            )}
          </Space>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => (
        <Tag color={examStatusColorMap[v] || 'default'}>
          {examStatusLabelMap[v] || v}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      width: 280,
      render: (_: unknown, record: OhHealthExam) => (
        <Space size="small">
          {record.status === ExamStatus.SCHEDULED && (
            <>
              <Tooltip title="编辑"><Button type="link" size="small" icon={<EditOutlined />} onClick={() => openExamEditModal(record)} /></Tooltip>
              <Tooltip title="开始体检"><Popconfirm title="确认开始体检？" onConfirm={() => handleStartExam(record.id)}><Button type="link" size="small" icon={<PlayCircleOutlined />} /></Popconfirm></Tooltip>
              <Tooltip title="删除"><Popconfirm title="确认删除？" onConfirm={() => handleDeleteExam(record.id)}><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Popconfirm></Tooltip>
            </>
          )}
          {record.status === ExamStatus.IN_PROGRESS && (
            <Tooltip title="完成体检"><Popconfirm title="确认完成体检？" onConfirm={() => handleCompleteExam(record.id)}><Button type="link" size="small" icon={<CheckCircleOutlined />}>完成</Button></Popconfirm></Tooltip>
          )}
          {record.status === ExamStatus.COMPLETED && (
            <Tooltip title="归档"><Popconfirm title="确认归档？" onConfirm={() => handleArchiveExam(record.id)}><Button type="link" size="small" icon={<VerifiedOutlined />}>归档</Button></Popconfirm></Tooltip>
          )}
          <Tooltip title="详情"><Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openExamDetail(record)} /></Tooltip>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <Title level={4} className="mb-1">职业健康管理</Title>
        <Text type="secondary">职业病危害因素监测与职业健康体检管理，遵循 GBZ 159 / GBZ 2.1 / GBZ 188</Text>
      </div>

      <Tabs defaultActiveKey="monitoring">
        {/* =============================== Monitoring Tab =============================== */}
        <Tabs.TabPane tab="危害因素监测" key="monitoring">
          <Space style={{ marginBottom: 16 }} wrap>
            <Select
              allowClear
              placeholder="检测类型"
              style={{ width: 130 }}
              options={DETECTION_TYPE_OPTIONS}
              value={monitorFilters.detection_type}
              onChange={(v) => setMonitorFilters((f) => ({ ...f, detection_type: v }))}
            />
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 110 }}
              options={MONITOR_STATUS_OPTIONS}
              value={monitorFilters.status}
              onChange={(v) => setMonitorFilters((f) => ({ ...f, status: v }))}
            />
            <Input.Search
              allowClear
              placeholder="搜索编号/场所/点位"
              style={{ width: 250 }}
              value={monitorFilters.keyword}
              onChange={(e) => setMonitorFilters((f) => ({ ...f, keyword: e.target.value }))}
              onSearch={() => { setMonitorPagination((p) => ({ ...p, page: 1 })); loadMonitors() }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openMonitorCreateModal}>
              新建监测
            </Button>
          </Space>

          <Table
            columns={monitorColumns}
            dataSource={monitors}
            rowKey="id"
            loading={monitorLoading}
            pagination={{
              current: monitorPagination.page,
              pageSize: monitorPagination.page_size,
              total: monitorPagination.total,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (page, page_size) => setMonitorPagination((p) => ({ ...p, page, page_size })),
            }}
            size="middle"
            scroll={{ x: 1300 }}
          />
        </Tabs.TabPane>

        {/* =============================== Exam Tab =============================== */}
        <Tabs.TabPane tab="职业健康体检" key="exams">
          <Space style={{ marginBottom: 16 }} wrap>
            <Select
              allowClear
              placeholder="体检类型"
              style={{ width: 130 }}
              options={EXAM_TYPE_OPTIONS}
              value={examFilters.exam_type}
              onChange={(v) => setExamFilters((f) => ({ ...f, exam_type: v }))}
            />
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 110 }}
              options={EXAM_STATUS_OPTIONS}
              value={examFilters.status}
              onChange={(v) => setExamFilters((f) => ({ ...f, status: v }))}
            />
            <Input.Search
              allowClear
              placeholder="搜索编号/姓名/部门"
              style={{ width: 250 }}
              value={examFilters.keyword}
              onChange={(e) => setExamFilters((f) => ({ ...f, keyword: e.target.value }))}
              onSearch={() => { setExamPagination((p) => ({ ...p, page: 1 })); loadExams() }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openExamCreateModal}>
              新建体检
            </Button>
          </Space>

          <Table
            columns={examColumns}
            dataSource={exams}
            rowKey="id"
            loading={examLoading}
            pagination={{
              current: exampagination.page,
              pageSize: exampagination.page_size,
              total: exampagination.total,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (page, page_size) => setExamPagination((p) => ({ ...p, page, page_size })),
            }}
            size="middle"
            scroll={{ x: 1300 }}
            onRow={(record) => ({
              style: ['suspected_od', 'od_diagnosed', 'contraindicated'].includes(record.overall_conclusion || '')
                ? { backgroundColor: '#fff2f0' }
                : {},
            })}
          />
        </Tabs.TabPane>
      </Tabs>

      {/* =============================== Monitor Modal =============================== */}
      <Modal
        title={editingMonitor ? '编辑监测记录' : '新建监测记录'}
        open={monitorModalOpen}
        onCancel={() => setMonitorModalOpen(false)}
        onOk={handleMonitorSave}
        confirmLoading={monitorSaving}
        width={800}
        destroyOnHidden
      >
        <Form form={monitorForm} layout="vertical" preserve={false}>
          <Title level={5}>基本信息</Title>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="monitor_no" label="监测编号" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="workplace" label="监测场所/车间" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="location" label="具体监测点位">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="equipment_info" label="关联设备/岗位">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Divider />
          <Title level={5}>检测信息</Title>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="detection_type" label="检测类型" rules={[{ required: true }]}>
                <Select options={DETECTION_TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="detection_agency" label="检测机构">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="inspector_name" label="检测人员">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="detection_date" label="检测日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* =============================== Monitor Drawer =============================== */}
      <Drawer
        title={`监测详情 - ${selectedMonitor?.monitor_no || ''}`}
        open={monitorDrawerOpen}
        onClose={() => setMonitorDrawerOpen(false)}
        width={800}
      >
        {selectedMonitor && (
          <Tabs defaultActiveKey="basic">
            <Tabs.TabPane tab="基本信息" key="basic">
              <Descriptions column={2} bordered size="small">
                <Descriptions.Item label="监测编号">{selectedMonitor.monitor_no}</Descriptions.Item>
                <Descriptions.Item label="监测场所">{selectedMonitor.workplace}</Descriptions.Item>
                <Descriptions.Item label="监测点位">{selectedMonitor.location || '-'}</Descriptions.Item>
                <Descriptions.Item label="关联设备">{selectedMonitor.equipment_info || '-'}</Descriptions.Item>
                <Descriptions.Item label="检测类型">
                  <Tag>{DETECTION_TYPE_OPTIONS.find((o) => o.value === selectedMonitor.detection_type)?.label}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={monitorStatusColorMap[selectedMonitor.status]}>
                    {monitorStatusLabelMap[selectedMonitor.status]}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="检测机构">{selectedMonitor.detection_agency || '-'}</Descriptions.Item>
                <Descriptions.Item label="检测日期">{selectedMonitor.detection_date ? new Date(selectedMonitor.detection_date).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="检测人员">{selectedMonitor.inspector_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="验证人员">{selectedMonitor.verifier_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{new Date(selectedMonitor.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
                <Descriptions.Item label="更新时间">{new Date(selectedMonitor.updated_at).toLocaleString('zh-CN')}</Descriptions.Item>
                <Descriptions.Item label="备注" span={2}>{selectedMonitor.notes || '-'}</Descriptions.Item>
              </Descriptions>
            </Tabs.TabPane>
            <Tabs.TabPane
              tab={`检测结果 (${selectedMonitor.detection_results?.length || 0})`}
              key="results"
            >
              <MonitorResultsTab
                monitor={selectedMonitor}
                onRefresh={() => openMonitorDetail(selectedMonitor)}
              />
            </Tabs.TabPane>
            <Tabs.TabPane
              tab={`异常处置 (${selectedMonitor.abnormality_records?.length || 0})`}
              key="abnormalities"
            >
              <AbnormalityTab
                records={selectedMonitor.abnormality_records || []}
                onAdd={async (data) => {
                  const res = await addMonitorAbnormality(selectedMonitor.id, data)
                  if (res.code === 0) { message.success('已添加'); openMonitorDetail(selectedMonitor) }
                }}
                onUpdateStatus={async (index, status) => {
                  const res = await updateMonitorAbnormalityStatus(selectedMonitor.id, index, status)
                  if (res.code === 0) { message.success('已更新'); openMonitorDetail(selectedMonitor) }
                }}
              />
            </Tabs.TabPane>
          </Tabs>
        )}
      </Drawer>

      {/* =============================== Exam Modal =============================== */}
      <Modal
        title={editingExam ? '编辑体检记录' : '新建体检记录'}
        open={examModalOpen}
        onCancel={() => setExamModalOpen(false)}
        onOk={handleExamSave}
        confirmLoading={examSaving}
        width={800}
        destroyOnHidden
      >
        <Form form={examForm} layout="vertical" preserve={false}>
          <Title level={5}>人员信息</Title>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="exam_no" label="体检编号" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="employee_name" label="员工姓名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="employee_id" label="工号">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="department" label="部门">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="job_position" label="岗位">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Divider />
          <Title level={5}>体检信息</Title>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="exam_type" label="体检类型" rules={[{ required: true }]}>
                <Select options={EXAM_TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="exam_agency" label="体检机构">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="hazard_factors" label="危害因素（逗号分隔）">
                <Select mode="tags" placeholder="输入危害因素" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="scheduled_date" label="计划体检日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* =============================== Exam Drawer =============================== */}
      <Drawer
        title={`体检详情 - ${selectedExam?.exam_no || ''}`}
        open={examDrawerOpen}
        onClose={() => setExamDrawerOpen(false)}
        width={800}
      >
        {selectedExam && (
          <Tabs defaultActiveKey="basic">
            <Tabs.TabPane tab="基本信息" key="basic">
              <Descriptions column={2} bordered size="small">
                <Descriptions.Item label="体检编号">{selectedExam.exam_no}</Descriptions.Item>
                <Descriptions.Item label="员工姓名">{selectedExam.employee_name}</Descriptions.Item>
                <Descriptions.Item label="工号">{selectedExam.employee_id || '-'}</Descriptions.Item>
                <Descriptions.Item label="部门">{selectedExam.department || '-'}</Descriptions.Item>
                <Descriptions.Item label="岗位">{selectedExam.job_position || '-'}</Descriptions.Item>
                <Descriptions.Item label="体检类型">
                  <Tag>{EXAM_TYPE_OPTIONS.find((o) => o.value === selectedExam.exam_type)?.label}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={examStatusColorMap[selectedExam.status]}>
                    {examStatusLabelMap[selectedExam.status]}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="体检机构">{selectedExam.exam_agency || '-'}</Descriptions.Item>
                <Descriptions.Item label="计划日期">{selectedExam.scheduled_date ? new Date(selectedExam.scheduled_date).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="实际体检日期">{selectedExam.exam_date ? new Date(selectedExam.exam_date).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="报告日期">{selectedExam.report_date ? new Date(selectedExam.report_date).toLocaleDateString('zh-CN') : '-'}</Descriptions.Item>
                <Descriptions.Item label="危害因素">{selectedExam.hazard_factors?.join(', ') || '-'}</Descriptions.Item>
                <Descriptions.Item label="综合结论">
                  {selectedExam.overall_conclusion ? (
                    <Tag color={conclusionColorMap[selectedExam.overall_conclusion]}>
                      {EXAM_CONCLUSION_OPTIONS.find((o) => o.value === selectedExam.overall_conclusion)?.label}
                    </Tag>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">{new Date(selectedExam.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
                <Descriptions.Item label="更新时间">{new Date(selectedExam.updated_at).toLocaleString('zh-CN')}</Descriptions.Item>
                <Descriptions.Item label="备注" span={2}>{selectedExam.notes || '-'}</Descriptions.Item>
              </Descriptions>
            </Tabs.TabPane>
            <Tabs.TabPane
              tab={`体检项目 (${selectedExam.exam_items?.length || 0})`}
              key="items"
            >
              <ExamItemsTab
                exam={selectedExam}
                onRefresh={() => openExamDetail(selectedExam)}
              />
            </Tabs.TabPane>
            <Tabs.TabPane
              tab={`异常处置 (${selectedExam.abnormality_records?.length || 0})`}
              key="abnormalities"
            >
              <AbnormalityTab
                records={selectedExam.abnormality_records || []}
                onAdd={async (data) => {
                  const res = await addExamAbnormality(selectedExam.id, data)
                  if (res.code === 0) { message.success('已添加'); openExamDetail(selectedExam) }
                }}
                onUpdateStatus={async (index, status) => {
                  const res = await updateExamAbnormalityStatus(selectedExam.id, index, status)
                  if (res.code === 0) { message.success('已更新'); openExamDetail(selectedExam) }
                }}
              />
            </Tabs.TabPane>
          </Tabs>
        )}
      </Drawer>
    </div>
  )
}

/* ============================== Monitor Results Tab ============================== */

function MonitorResultsTab({
  monitor,
  onRefresh,
}: {
  monitor: OhHazardMonitor
  onRefresh: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [form] = Form.useForm()

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      const res = await addDetectionResult(monitor.id, values)
      if (res.code === 0) {
        message.success('已添加检测结果')
        setAdding(false)
        form.resetFields()
        onRefresh()
      } else {
        message.error(res.message || '添加失败')
      }
    } catch {
      // form validation
    }
  }

  const results = monitor.detection_results || []

  return (
    <div className="space-y-4">
      {results.length === 0 && !adding && (
        <Text type="secondary">暂无检测结果</Text>
      )}
      {results.map((r, i) => (
        <Card key={i} size="small" className="mb-2">
          <Row gutter={16}>
            <Col span={8}>
              <Text strong>{r.factor_name}</Text>
              <br />
              <Text type="secondary" className="text-xs">{HAZARD_FACTOR_CATEGORY_OPTIONS.find((o) => o.value === r.factor_category)?.label}</Text>
            </Col>
            <Col span={6}>
              <Text>{r.detection_value} {r.unit || ''}</Text>
              <br />
              <Text type="secondary" className="text-xs">OEL: {r.oel_limit || '-'} {r.unit || ''}</Text>
            </Col>
            <Col span={4}>
              <Tag color={OEL_COMPLIANCE_STATUS_OPTIONS.find((o) => o.value === r.compliance_status)?.color}>
                {OEL_COMPLIANCE_STATUS_OPTIONS.find((o) => o.value === r.compliance_status)?.label || r.compliance_status || '-'}
              </Tag>
            </Col>
            <Col span={6}>
              <Text type="secondary" className="text-xs">{r.sampling_method || ''}</Text>
              <br />
              <Text type="secondary" className="text-xs">{r.standard_ref || ''}</Text>
            </Col>
          </Row>
        </Card>
      ))}

      {adding && (
        <Card size="small" title="添加检测结果">
          <Form form={form} layout="vertical">
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="factor_name" label="因素名称" rules={[{ required: true }]}>
                  <Input placeholder="如: 其他粉尘-总尘" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="factor_category" label="因素类别" rules={[{ required: true }]}>
                  <Select options={HAZARD_FACTOR_CATEGORY_OPTIONS} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="detection_value" label="检测值" rules={[{ required: true }]}>
                  <Input type="number" placeholder="如: 2.5" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={6}>
                <Form.Item name="unit" label="单位">
                  <Input placeholder="如: mg/m³" />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="oel_limit" label="OEL限值">
                  <Input type="number" placeholder="如: 8" />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="sampling_method" label="采样方法">
                  <Input placeholder="如: 个体采样" />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="standard_ref" label="标准参考">
                  <Input placeholder="如: GBZ 2.1-2019" />
                </Form.Item>
              </Col>
            </Row>
            <Space>
              <Button type="primary" onClick={handleAdd}>添加</Button>
              <Button onClick={() => { setAdding(false); form.resetFields() }}>取消</Button>
            </Space>
          </Form>
        </Card>
      )}

      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={() => setAdding(true)}
        disabled={adding}
      >
        添加检测结果
      </Button>
    </div>
  )
}

/* ============================== Exam Items Tab ============================== */

function ExamItemsTab({
  exam,
  onRefresh,
}: {
  exam: OhHealthExam
  onRefresh: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [form] = Form.useForm()
  const [conclusionForm] = Form.useForm()

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      const res = await addExamItem(exam.id, values)
      if (res.code === 0) {
        message.success('已添加体检项目')
        setAdding(false)
        form.resetFields()
        onRefresh()
      } else {
        message.error(res.message || '添加失败')
      }
    } catch {
      // form validation
    }
  }

  const handleSetConclusion = async () => {
    try {
      const values = await conclusionForm.validateFields()
      const res = await setExamConclusion(exam.id, values.conclusion, values.remarks)
      if (res.code === 0) {
        message.success('已设置体检结论')
        onRefresh()
      } else {
        message.error(res.message || '设置失败')
      }
    } catch {
      // form validation
    }
  }

  const items = exam.exam_items || []

  return (
    <div className="space-y-4">
      {/* Conclusion Section */}
      <Card size="small" title="体检结论">
        {exam.overall_conclusion ? (
          <Space>
            <Tag color={conclusionColorMap[exam.overall_conclusion]}>
              {EXAM_CONCLUSION_OPTIONS.find((o) => o.value === exam.overall_conclusion)?.label}
            </Tag>
            {['suspected_od', 'od_diagnosed', 'contraindicated'].includes(exam.overall_conclusion) && (
              <Text type="danger">该结论已自动生成异常处置记录</Text>
            )}
          </Space>
        ) : (
          <Text type="secondary">尚未设置</Text>
        )}
        <Divider />
        <Form form={conclusionForm} layout="inline">
          <Form.Item name="conclusion" label="设置结论" rules={[{ required: true }]}>
            <Select options={EXAM_CONCLUSION_OPTIONS} style={{ width: 180 }} placeholder="选择结论" />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input style={{ width: 200 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" onClick={handleSetConclusion}>保存结论</Button>
          </Form.Item>
        </Form>
      </Card>

      {/* Exam Items */}
      {items.length === 0 && !adding && (
        <Text type="secondary">暂无体检项目</Text>
      )}
      {items.map((r, i) => (
        <Card key={i} size="small" className="mb-2">
          <Row gutter={16}>
            <Col span={8}>
              <Text strong>{r.item_name}</Text>
              {r.category && <><br /><Text type="secondary" className="text-xs">{r.category}</Text></>}
            </Col>
            <Col span={6}>
              <Text>{r.result || '-'}</Text>
              {r.reference_range && <><br /><Text type="secondary" className="text-xs">参考范围: {r.reference_range}</Text></>}
            </Col>
            <Col span={4}>
              {r.is_abnormal ? (
                <Tag color="red">异常</Tag>
              ) : (
                <Tag color="green">正常</Tag>
              )}
            </Col>
            <Col span={6}>
              <Text type="secondary" className="text-xs">{r.remarks || ''}</Text>
            </Col>
          </Row>
        </Card>
      ))}

      {adding && (
        <Card size="small" title="添加体检项目">
          <Form form={form} layout="vertical">
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="item_name" label="项目名称" rules={[{ required: true }]}>
                  <Input placeholder="如: 胸片、听力测试" />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="category" label="项目类别">
                  <Input placeholder="如: 影像学" />
                </Form.Item>
              </Col>
              <Col span={5}>
                <Form.Item name="result" label="检查结果">
                  <Input />
                </Form.Item>
              </Col>
              <Col span={5}>
                <Form.Item name="reference_range" label="参考范围">
                  <Input />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={6}>
                <Form.Item name="is_abnormal" label="是否异常" valuePropName="checked">
                  <Select
                    options={[
                      { value: true, label: '异常' },
                      { value: false, label: '正常' },
                    ]}
                    placeholder="选择"
                  />
                </Form.Item>
              </Col>
              <Col span={10}>
                <Form.Item name="remarks" label="备注">
                  <Input />
                </Form.Item>
              </Col>
            </Row>
            <Space>
              <Button type="primary" onClick={handleAdd}>添加</Button>
              <Button onClick={() => { setAdding(false); form.resetFields() }}>取消</Button>
            </Space>
          </Form>
        </Card>
      )}

      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={() => setAdding(true)}
        disabled={adding}
      >
        添加体检项目
      </Button>
    </div>
  )
}

/* ============================== Abnormality Tab (shared) ============================== */

function AbnormalityTab({
  records,
  onAdd,
  onUpdateStatus,
}: {
  records: AbnormalityRecord[]
  onAdd: (data: Record<string, unknown>) => Promise<void>
  onUpdateStatus: (index: number, status: string) => Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const [form] = Form.useForm()

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      await onAdd(values)
      setAdding(false)
      form.resetFields()
    } catch {
      // form validation
    }
  }

  return (
    <div className="space-y-4">
      {records.length === 0 && !adding && (
        <Text type="secondary">暂无异常处置记录</Text>
      )}
      {records.map((r, i) => (
        <Card key={i} size="small" className="mb-2">
          <Row gutter={16}>
            <Col span={16}>
              <Text>{r.abnormality_desc}</Text>
              {r.corrective_action && <><br /><Text type="secondary">{r.corrective_action}</Text></>}
              {r.responsible_person && <><br /><Text type="secondary">责任人: {r.responsible_person}</Text></>}
              {r.deadline && <><br /><Text type="secondary">截止: {r.deadline}</Text></>}
            </Col>
            <Col span={8}>
              <Tag color={ABNORMALITY_STATUS_OPTIONS.find((o) => o.value === r.status)?.color}>
                {ABNORMALITY_STATUS_OPTIONS.find((o) => o.value === r.status)?.label || r.status}
              </Tag>
              <br />
              <Space size="small" style={{ marginTop: 4 }}>
                {r.status !== 'closed' && (
                  <Popconfirm
                    title="确认关闭？"
                    onConfirm={() => onUpdateStatus(i, 'closed')}
                  >
                    <Button size="small" type="link">关闭</Button>
                  </Popconfirm>
                )}
                {r.status === 'open' && (
                  <Popconfirm
                    title="开始调查？"
                    onConfirm={() => onUpdateStatus(i, 'investigating')}
                  >
                    <Button size="small" type="link">调查</Button>
                  </Popconfirm>
                )}
                {r.status === 'investigating' && (
                  <Popconfirm
                    title="确认已纠正？"
                    onConfirm={() => onUpdateStatus(i, 'corrected')}
                  >
                    <Button size="small" type="link">纠正</Button>
                  </Popconfirm>
                )}
              </Space>
            </Col>
          </Row>
        </Card>
      ))}

      {adding && (
        <Card size="small" title="添加异常处置记录">
          <Form form={form} layout="vertical">
            <Form.Item name="abnormality_desc" label="异常描述" rules={[{ required: true }]}>
              <TextArea rows={2} />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="corrective_action" label="纠正措施">
                  <Input />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="responsible_person" label="责任人">
                  <Input />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="deadline" label="截止日期">
                  <Input placeholder="YYYY-MM-DD" />
                </Form.Item>
              </Col>
            </Row>
            <Space>
              <Button type="primary" onClick={handleAdd}>添加</Button>
              <Button onClick={() => { setAdding(false); form.resetFields() }}>取消</Button>
            </Space>
          </Form>
        </Card>
      )}

      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={() => setAdding(true)}
        disabled={adding}
      >
        添加异常记录
      </Button>
    </div>
  )
}
