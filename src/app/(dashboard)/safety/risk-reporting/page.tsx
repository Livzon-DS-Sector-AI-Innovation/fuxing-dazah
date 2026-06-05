'use client'

import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  DatePicker,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Tabs,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  SendOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  AlertOutlined,
  CalendarOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getSpecialOperationReports,
  getSpecialOperationReport,
  createSpecialOperationReport,
  updateSpecialOperationReport,
  deleteSpecialOperationReport,
  submitSpecialOperationReport,
  approveSpecialOperationReport,
  rejectSpecialOperationReport,
  getDailyRiskReports,
  createDailyRiskReport,
  updateDailyRiskReport,
  deleteDailyRiskReport,
  submitDailyRiskReport,
  approveDailyRiskReport,
  rejectDailyRiskReport,
} from '@/actions/safety'
import type {
  SpecialOperationReport,
  SpecialOperationReportFormData,
  DailyRiskReport,
  DailyRiskReportFormData,
} from '@/types/safety'
import {
  OPERATION_TYPE_OPTIONS,
  OPERATION_LEVEL_OPTIONS,
  REPORT_STATUS_OPTIONS,
  RISK_LEVEL_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography
const { TextArea } = Input

// ==================== 特殊作业报备 Panel ====================

function SpecialOpReportPanel() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [rejectVisible, setRejectVisible] = useState(false)
  const [rejectId, setRejectId] = useState<string>('')
  const [rejectReason, setRejectReason] = useState('')
  const [editingRecord, setEditingRecord] = useState<SpecialOperationReport | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  const {
    specialOpReports,
    specialOpReportTotal,
    specialOpReportQueryParams,
    setSpecialOpReports,
    setSpecialOpReportTotal,
    setSpecialOpReportQueryParams,
    addSpecialOpReport,
    updateSpecialOpReport: updateInStore,
    removeSpecialOpReport,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getSpecialOperationReports({
        ...specialOpReportQueryParams,
        status: statusFilter,
        operation_type: typeFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setSpecialOpReports(response.data as SpecialOperationReport[])
        setSpecialOpReportTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载特殊作业报备列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [specialOpReportQueryParams.page, specialOpReportQueryParams.page_size, statusFilter, typeFilter])

  const handleSearch = () => {
    setSpecialOpReportQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: SpecialOperationReport) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      planned_start_time: record.planned_start_time ? dayjs(record.planned_start_time) : undefined,
      planned_end_time: record.planned_end_time ? dayjs(record.planned_end_time) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该特殊作业报备吗？',
      onOk: async () => {
        const response = await deleteSpecialOperationReport(id)
        if (response.code === 200) { message.success('删除成功'); removeSpecialOpReport(id) }
        else { message.error(response.message || '删除失败') }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        planned_start_time: values.planned_start_time ? values.planned_start_time.toISOString() : undefined,
        planned_end_time: values.planned_end_time ? values.planned_end_time.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateSpecialOperationReport(editingRecord.id, formattedValues)
        if (response.code === 200) { message.success('更新成功'); updateInStore(editingRecord.id, response.data as SpecialOperationReport); setModalVisible(false) }
        else { message.error(response.message || '更新失败') }
      } else {
        const response = await createSpecialOperationReport(formattedValues as SpecialOperationReportFormData)
        if (response.code === 200) { message.success('创建成功'); addSpecialOpReport(response.data as SpecialOperationReport); setModalVisible(false); form.resetFields() }
        else { message.error(response.message || '创建失败') }
      }
    } catch { console.error('表单验证失败') }
  }

  const handleSubmitFlow = async (id: string) => {
    const response = await submitSpecialOperationReport(id)
    if (response.code === 200) { message.success('已提交'); updateInStore(id, response.data as SpecialOperationReport) }
    else { message.error(response.message || '提交失败') }
  }

  const handleApprove = async (id: string) => {
    const response = await approveSpecialOperationReport(id)
    if (response.code === 200) { message.success('已审批'); updateInStore(id, response.data as SpecialOperationReport) }
    else { message.error(response.message || '审批失败') }
  }

  const handleOpenReject = (id: string) => {
    setRejectId(id)
    setRejectReason('')
    setRejectVisible(true)
  }

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) { message.error('请填写驳回原因'); return }
    const response = await rejectSpecialOperationReport(rejectId, rejectReason)
    if (response.code === 200) { message.success('已驳回'); updateInStore(rejectId, response.data as SpecialOperationReport); setRejectVisible(false) }
    else { message.error(response.message || '驳回失败') }
  }

  const columns: ColumnsType<SpecialOperationReport> = [
    { title: '报备编号', dataIndex: 'report_no', key: 'report_no', width: 140 },
    {
      title: '作业类型', dataIndex: 'operation_type', key: 'operation_type', width: 100,
      render: (t: string) => { const o = OPERATION_TYPE_OPTIONS.find(x => x.value === t); return <Tag>{o?.label || t}</Tag> },
    },
    {
      title: '级别', dataIndex: 'operation_level', key: 'operation_level', width: 70,
      render: (l: string) => { const o = OPERATION_LEVEL_OPTIONS.find(x => x.value === l); return <Tag color={l === 'special' ? 'red' : l === 'grade1' ? 'orange' : 'blue'}>{o?.label || l}</Tag> },
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, ellipsis: true },
    { title: '作业地点', dataIndex: 'location', key: 'location', width: 120, ellipsis: true },
    {
      title: '计划开始', dataIndex: 'planned_start_time', key: 'planned_start_time', width: 115,
      render: (t: string) => t ? dayjs(t).format('MM-DD HH:mm') : '-',
    },
    { title: '负责人', dataIndex: 'work_leader_name', key: 'work_leader_name', width: 90 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const opt = REPORT_STATUS_OPTIONS.find(x => x.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 260, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSubmitFlow(record.id)}>提交</Button>
          )}
          {record.status === 'submitted' && (
            <>
              <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleApprove(record.id)}>审批</Button>
              <Button type="link" size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleOpenReject(record.id)}>驳回</Button>
            </>
          )}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const formContent = (
    <>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="report_no" label="报备编号" rules={[{ required: true }]}>
            <Input placeholder="请输入报备编号" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="operation_type" label="作业类型" rules={[{ required: true }]}>
            <Select options={OPERATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择作业类型" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="operation_level" label="作业级别" initialValue="grade2">
            <Select options={OPERATION_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="department" label="报备部门">
            <Input placeholder="请输入报备部门" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="location" label="作业地点">
            <Input placeholder="请输入作业地点" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="equipment_tag" label="设备位号">
            <Input placeholder="请输入设备位号" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="planned_start_time" label="计划开始时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="planned_end_time" label="计划结束时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="work_leader_name" label="作业负责人">
            <Input placeholder="作业负责人" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="guardian_name" label="监护人">
            <Input placeholder="监护人" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="applicant_name" label="申请人">
            <Input placeholder="申请人" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="operator_names" label="作业人员">
            <Input placeholder="多个以逗号分隔" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="risk_level" label="风险等级">
            <Select options={RISK_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择风险等级" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="work_description" label="作业内容描述">
        <TextArea rows={2} placeholder="请输入作业内容描述" />
      </Form.Item>
      <Form.Item name="safety_measures" label="安全措施">
        <TextArea rows={3} placeholder="请输入安全措施" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="gas_analysis" label="气体分析结果">
            <TextArea rows={2} placeholder="气体分析结果" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="emergency_equipment" label="应急消防器材">
            <TextArea rows={2} placeholder="应急消防器材" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="risk_assessment" label="风险评估描述">
        <TextArea rows={2} placeholder="风险评估描述" />
      </Form.Item>
      <Form.Item name="notes" label="备注">
        <TextArea rows={2} placeholder="备注" />
      </Form.Item>
    </>
  )

  return (
    <>
      <Row gutter={16} className="mb-4">
        <Col span={6}>
          <Input placeholder="搜索报备编号/作业内容/地点" prefix={<SearchOutlined />}
            value={searchText} onChange={e => setSearchText(e.target.value)} onPressEnter={handleSearch} />
        </Col>
        <Col span={5}>
          <Select placeholder="作业类型" allowClear value={typeFilter}
            onChange={v => { setTypeFilter(v); setSpecialOpReportQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={OPERATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={5}>
          <Select placeholder="状态" allowClear value={statusFilter}
            onChange={v => { setStatusFilter(v); setSpecialOpReportQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={REPORT_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={3}>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
        </Col>
        <Col span={5}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建报备</Button>
        </Col>
      </Row>

      <Table columns={columns} dataSource={specialOpReports} rowKey="id" loading={loading} scroll={{ x: 1100 }}
        pagination={{
          current: specialOpReportQueryParams.page, pageSize: specialOpReportQueryParams.page_size, total: specialOpReportTotal,
          showSizeChanger: true, showTotal: t => `共 ${t} 条`,
          onChange: (page, pageSize) => setSpecialOpReportQueryParams({ page, page_size: pageSize }),
        }} />

      <Modal title={editingRecord ? '编辑特殊作业报备' : '新建特殊作业报备'} open={modalVisible}
        onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={850} okText="确认" cancelText="取消">
        <Form form={editingRecord ? editForm : form} layout="vertical">
          {formContent}
        </Form>
      </Modal>

      <Modal title="驳回原因" open={rejectVisible}
        onOk={handleRejectConfirm} onCancel={() => setRejectVisible(false)} okText="确认驳回" cancelText="取消">
        <TextArea rows={4} placeholder="请输入驳回原因" value={rejectReason}
          onChange={e => setRejectReason(e.target.value)} />
      </Modal>
    </>
  )
}

// ==================== 每日风险作业报备 Panel ====================

function DailyRiskReportPanel() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [rejectVisible, setRejectVisible] = useState(false)
  const [rejectId, setRejectId] = useState<string>('')
  const [rejectReason, setRejectReason] = useState('')
  const [editingRecord, setEditingRecord] = useState<DailyRiskReport | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [deptFilter, setDeptFilter] = useState<string | undefined>()

  const {
    dailyRiskReports,
    dailyRiskReportTotal,
    dailyRiskReportQueryParams,
    setDailyRiskReports,
    setDailyRiskReportTotal,
    setDailyRiskReportQueryParams,
    addDailyRiskReport,
    updateDailyRiskReport: updateInStore,
    removeDailyRiskReport,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getDailyRiskReports({
        ...dailyRiskReportQueryParams,
        status: statusFilter,
        department: deptFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setDailyRiskReports(response.data as DailyRiskReport[])
        setDailyRiskReportTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载每日风险作业报备列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [dailyRiskReportQueryParams.page, dailyRiskReportQueryParams.page_size, statusFilter, deptFilter])

  const handleSearch = () => {
    setDailyRiskReportQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: DailyRiskReport) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      report_date: record.report_date ? dayjs(record.report_date) : undefined,
      planned_start_time: record.planned_start_time ? dayjs(record.planned_start_time) : undefined,
      planned_end_time: record.planned_end_time ? dayjs(record.planned_end_time) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该每日风险作业报备吗？',
      onOk: async () => {
        const response = await deleteDailyRiskReport(id)
        if (response.code === 200) { message.success('删除成功'); removeDailyRiskReport(id) }
        else { message.error(response.message || '删除失败') }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        report_date: values.report_date ? values.report_date.toISOString() : undefined,
        planned_start_time: values.planned_start_time ? values.planned_start_time.toISOString() : undefined,
        planned_end_time: values.planned_end_time ? values.planned_end_time.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateDailyRiskReport(editingRecord.id, formattedValues)
        if (response.code === 200) { message.success('更新成功'); updateInStore(editingRecord.id, response.data as DailyRiskReport); setModalVisible(false) }
        else { message.error(response.message || '更新失败') }
      } else {
        const response = await createDailyRiskReport(formattedValues as DailyRiskReportFormData)
        if (response.code === 200) { message.success('创建成功'); addDailyRiskReport(response.data as DailyRiskReport); setModalVisible(false); form.resetFields() }
        else { message.error(response.message || '创建失败') }
      }
    } catch { console.error('表单验证失败') }
  }

  const handleSubmitFlow = async (id: string) => {
    const response = await submitDailyRiskReport(id)
    if (response.code === 200) { message.success('已提交'); updateInStore(id, response.data as DailyRiskReport) }
    else { message.error(response.message || '提交失败') }
  }

  const handleApprove = async (id: string) => {
    const response = await approveDailyRiskReport(id)
    if (response.code === 200) { message.success('已审批'); updateInStore(id, response.data as DailyRiskReport) }
    else { message.error(response.message || '审批失败') }
  }

  const handleOpenReject = (id: string) => {
    setRejectId(id)
    setRejectReason('')
    setRejectVisible(true)
  }

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) { message.error('请填写驳回原因'); return }
    const response = await rejectDailyRiskReport(rejectId, rejectReason)
    if (response.code === 200) { message.success('已驳回'); updateInStore(rejectId, response.data as DailyRiskReport); setRejectVisible(false) }
    else { message.error(response.message || '驳回失败') }
  }

  const columns: ColumnsType<DailyRiskReport> = [
    { title: '报备编号', dataIndex: 'report_no', key: 'report_no', width: 140 },
    {
      title: '作业日期', dataIndex: 'report_date', key: 'report_date', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, ellipsis: true },
    { title: '作业描述', dataIndex: 'operation_description', key: 'operation_description', width: 200, ellipsis: true },
    {
      title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', width: 100,
      render: (r: string) => {
        const opt = RISK_LEVEL_OPTIONS.find(o => o.value === r)
        return <Tag color={opt?.color}>{opt?.label || r || '-'}</Tag>
      },
    },
    { title: '负责人', dataIndex: 'responsible_person', key: 'responsible_person', width: 90 },
    { title: '作业人数', dataIndex: 'operator_count', key: 'operator_count', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const opt = REPORT_STATUS_OPTIONS.find(x => x.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 260, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSubmitFlow(record.id)}>提交</Button>
          )}
          {record.status === 'submitted' && (
            <>
              <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleApprove(record.id)}>审批</Button>
              <Button type="link" size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleOpenReject(record.id)}>驳回</Button>
            </>
          )}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const formContent = (
    <>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="report_no" label="报备编号" rules={[{ required: true }]}>
            <Input placeholder="请输入报备编号" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="report_date" label="作业日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="department" label="报备部门">
            <Input placeholder="请输入报备部门" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="location" label="作业地点">
            <Input placeholder="请输入作业地点" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="risk_level" label="风险等级">
            <Select options={RISK_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择风险等级" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="responsible_person" label="负责人">
            <Input placeholder="负责人" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="planned_start_time" label="开始时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="planned_end_time" label="结束时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="operator_count" label="作业人数">
            <Input type="number" placeholder="作业人数" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="operation_description" label="风险作业描述" rules={[{ required: true }]}>
        <TextArea rows={2} placeholder="请输入风险作业描述" />
      </Form.Item>
      <Form.Item name="operation_steps" label="作业步骤">
        <TextArea rows={3} placeholder="请输入作业步骤" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="hazard_factors" label="危险因素">
            <TextArea rows={2} placeholder="危险因素" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="control_measures" label="控制措施">
            <TextArea rows={2} placeholder="控制措施" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="applicant_name" label="申请人">
            <Input placeholder="申请人" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="approver_name" label="审批人">
            <Input placeholder="审批人" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="notes" label="备注">
        <TextArea rows={2} placeholder="备注" />
      </Form.Item>
    </>
  )

  return (
    <>
      <Row gutter={16} className="mb-4">
        <Col span={6}>
          <Input placeholder="搜索报备编号/作业描述/部门" prefix={<SearchOutlined />}
            value={searchText} onChange={e => setSearchText(e.target.value)} onPressEnter={handleSearch} />
        </Col>
        <Col span={5}>
          <Select placeholder="状态" allowClear value={statusFilter}
            onChange={v => { setStatusFilter(v); setDailyRiskReportQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={REPORT_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={5}>
          <Input placeholder="部门" allowClear value={deptFilter}
            onChange={e => { setDeptFilter(e.target.value || undefined); setDailyRiskReportQueryParams({ page: 1 }) }} />
        </Col>
        <Col span={3}>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
        </Col>
        <Col span={5}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建报备</Button>
        </Col>
      </Row>

      <Table columns={columns} dataSource={dailyRiskReports} rowKey="id" loading={loading} scroll={{ x: 1100 }}
        pagination={{
          current: dailyRiskReportQueryParams.page, pageSize: dailyRiskReportQueryParams.page_size, total: dailyRiskReportTotal,
          showSizeChanger: true, showTotal: t => `共 ${t} 条`,
          onChange: (page, pageSize) => setDailyRiskReportQueryParams({ page, page_size: pageSize }),
        }} />

      <Modal title={editingRecord ? '编辑每日风险作业报备' : '新建每日风险作业报备'} open={modalVisible}
        onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={800} okText="确认" cancelText="取消">
        <Form form={editingRecord ? editForm : form} layout="vertical">
          {formContent}
        </Form>
      </Modal>

      <Modal title="驳回原因" open={rejectVisible}
        onOk={handleRejectConfirm} onCancel={() => setRejectVisible(false)} okText="确认驳回" cancelText="取消">
        <TextArea rows={4} placeholder="请输入驳回原因" value={rejectReason}
          onChange={e => setRejectReason(e.target.value)} />
      </Modal>
    </>
  )
}

// ==================== 主页面 ====================

export default function RiskReportingPage() {
  return (
    <div className="p-6">
      <div className="mb-4">
        <Text className="text-lg font-semibold">风险作业报备</Text>
        <br />
        <Text type="secondary">关键风险作业报备审批管理，包括八大特殊作业报备和每日风险作业报备</Text>
      </div>

      <Card>
        <Tabs
          defaultActiveKey="special-op"
          items={[
            {
              key: 'special-op',
              label: <span><AlertOutlined /> 特殊作业报备</span>,
              children: <SpecialOpReportPanel />,
            },
            {
              key: 'daily-risk',
              label: <span><CalendarOutlined /> 每日风险作业报备</span>,
              children: <DailyRiskReportPanel />,
            },
          ]}
        />
      </Card>
    </div>
  )
}