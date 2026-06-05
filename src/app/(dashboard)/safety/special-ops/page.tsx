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
  Tabs,
  Typography,
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
  PlayCircleOutlined,
  FlagOutlined,
  InboxOutlined,
  TeamOutlined,
  SafetyCertificateOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  // Personnel actions
  getPersonnelList,
  createPersonnel,
  updatePersonnel,
  deletePersonnel,
  // Permit actions
  getPermitList,
  createPermit,
  updatePermit,
  deletePermit,
  submitPermit,
  approvePermit,
  rejectPermit,
  startPermit,
  completePermit,
  archivePermit,
} from '@/actions/safety'
import type {
  SpecialOperationPersonnel,
  SpecialOperationPersonnelFormData,
  SpecialOperationPermit,
  SpecialOperationPermitFormData,
} from '@/types/safety'
import {
  OPERATION_TYPE_OPTIONS,
  OPERATION_LEVEL_OPTIONS,
  PERSONNEL_STATUS_OPTIONS,
  PERMIT_STATUS_OPTIONS,
  COMPLETION_METHOD_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

// ==================== Personnel Panel ====================

function PersonnelPanel() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SpecialOperationPersonnel | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [certTypeFilter, setCertTypeFilter] = useState<string | undefined>()

  const {
    personnel,
    personnelTotal,
    personnelQueryParams,
    setPersonnel,
    setPersonnelTotal,
    setPersonnelQueryParams,
    addPersonnel,
    updatePersonnel: updatePersonnelInStore,
    removePersonnel,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getPersonnelList({
        ...personnelQueryParams,
        status: statusFilter,
        certificate_type: certTypeFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setPersonnel(response.data)
        setPersonnelTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载人员列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [personnelQueryParams.page, personnelQueryParams.page_size, statusFilter, certTypeFilter])

  const handleSearch = () => {
    setPersonnelQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: SpecialOperationPersonnel) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      issue_date: record.issue_date ? dayjs(record.issue_date) : undefined,
      expiry_date: record.expiry_date ? dayjs(record.expiry_date) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该人员资质记录吗？',
      onOk: async () => {
        const response = await deletePersonnel(id)
        if (response.code === 200) {
          message.success('删除成功')
          removePersonnel(id)
        } else {
          message.error(response.message || '删除失败')
        }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        issue_date: values.issue_date ? values.issue_date.toISOString() : undefined,
        expiry_date: values.expiry_date ? values.expiry_date.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updatePersonnel(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updatePersonnelInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createPersonnel(formattedValues as SpecialOperationPersonnelFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addPersonnel(response.data)
          setModalVisible(false)
          form.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const columns: ColumnsType<SpecialOperationPersonnel> = [
    { title: '人员编号', dataIndex: 'personnel_no', key: 'personnel_no', width: 130 },
    { title: '姓名', dataIndex: 'name', key: 'name', width: 100 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 110 },
    {
      title: '证书类型', dataIndex: 'certificate_type', key: 'certificate_type', width: 120,
      render: (t: string) => {
        const opt = OPERATION_TYPE_OPTIONS.find(o => o.value === t)
        return <Tag>{opt?.label || t}</Tag>
      },
    },
    { title: '证书编号', dataIndex: 'certificate_number', key: 'certificate_number', width: 140 },
    {
      title: '有效期至', dataIndex: 'expiry_date', key: 'expiry_date', width: 115,
      render: (d: string) => {
        if (!d) return '-'
        const expired = dayjs(d).isBefore(dayjs())
        return <Text type={expired ? 'danger' : undefined} strong={expired}>{dayjs(d).format('YYYY-MM-DD')}</Text>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const opt = PERSONNEL_STATUS_OPTIONS.find(o => o.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 160, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
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
          <Form.Item name="personnel_no" label="人员编号" rules={[{ required: true }]}>
            <Input placeholder="请输入人员编号" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="name" label="姓名" rules={[{ required: true }]}>
            <Input placeholder="请输入姓名" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="department" label="所属部门">
            <Input placeholder="请输入部门" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="certificate_type" label="证书类型" rules={[{ required: true }]}>
            <Select options={OPERATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择证书类型" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="certificate_number" label="证书编号">
            <Input placeholder="请输入证书编号" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="issuing_authority" label="发证机关">
            <Input placeholder="请输入发证机关" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="issue_date" label="发证日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="expiry_date" label="有效期至">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="qualification_scope" label="资质范围">
        <Input.TextArea rows={2} placeholder="请输入资质范围" />
      </Form.Item>
      <Form.Item name="notes" label="备注">
        <Input.TextArea rows={2} placeholder="请输入备注" />
      </Form.Item>
    </>
  )

  return (
    <div>
      <Row gutter={16} className="mb-4">
        <Col span={6}>
          <Input placeholder="搜索姓名/编号" prefix={<SearchOutlined />} value={searchText}
            onChange={e => setSearchText(e.target.value)} onPressEnter={handleSearch} />
        </Col>
        <Col span={5}>
          <Select placeholder="证书类型" allowClear value={certTypeFilter}
            onChange={v => { setCertTypeFilter(v); setPersonnelQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={OPERATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={5}>
          <Select placeholder="状态" allowClear value={statusFilter}
            onChange={v => { setStatusFilter(v); setPersonnelQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={PERSONNEL_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={3}>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
        </Col>
        <Col span={5} className="text-right">
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增人员</Button>
        </Col>
      </Row>

      <Table columns={columns} dataSource={personnel} rowKey="id" loading={loading} scroll={{ x: 1100 }}
        pagination={{
          current: personnelQueryParams.page, pageSize: personnelQueryParams.page_size, total: personnelTotal,
          showSizeChanger: true, showTotal: t => `共 ${t} 条`,
          onChange: (page, pageSize) => setPersonnelQueryParams({ page, page_size: pageSize }),
        }} />

      <Modal title={editingRecord ? '编辑人员资质' : '新增人员资质'} open={modalVisible}
        onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={750} okText="确认" cancelText="取消">
        <Form form={editingRecord ? editForm : form} layout="vertical">
          {formContent}
        </Form>
      </Modal>
    </div>
  )
}

// ==================== Permit Panel ====================

function PermitPanel() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SpecialOperationPermit | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [operationTypeFilter, setOperationTypeFilter] = useState<string | undefined>()
  const [rejectModalVisible, setRejectModalVisible] = useState(false)
  const [rejectRecordId, setRejectRecordId] = useState<string>('')
  const [rejectReason, setRejectReason] = useState('')

  const {
    permits, permitTotal, permitQueryParams,
    setPermits, setPermitTotal, setPermitQueryParams,
    addPermit, updatePermit: updatePermitInStore, removePermit,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getPermitList({
        ...permitQueryParams,
        status: statusFilter,
        operation_type: operationTypeFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setPermits(response.data)
        setPermitTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载作业票列表失败')
    } finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [permitQueryParams.page, permitQueryParams.page_size, statusFilter, operationTypeFilter])

  const handleSearch = () => { setPermitQueryParams({ page: 1 }); loadData() }

  const handleAdd = () => { setEditingRecord(null); form.resetFields(); setModalVisible(true) }

  const handleEdit = (record: SpecialOperationPermit) => {
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
      title: '确认删除', content: '确定要删除该作业票吗？',
      onOk: async () => {
        const response = await deletePermit(id)
        if (response.code === 200) { message.success('删除成功'); removePermit(id) }
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
        const response = await updatePermit(editingRecord.id, formattedValues)
        if (response.code === 200) { message.success('更新成功'); updatePermitInStore(editingRecord.id, response.data); setModalVisible(false) }
        else { message.error(response.message || '更新失败') }
      } else {
        const response = await createPermit(formattedValues as SpecialOperationPermitFormData)
        if (response.code === 200) { message.success('创建成功'); addPermit(response.data); setModalVisible(false); form.resetFields() }
        else { message.error(response.message || '创建失败') }
      }
    } catch { console.error('表单验证失败') }
  }

  const handleSubmitPermit = async (id: string) => {
    const response = await submitPermit(id)
    if (response.code === 200) { message.success('提交成功'); updatePermitInStore(id, response.data) }
    else { message.error(response.message || '提交失败') }
  }

  const handleApprovePermit = async (id: string) => {
    const response = await approvePermit(id)
    if (response.code === 200) { message.success('审批通过'); updatePermitInStore(id, response.data) }
    else { message.error(response.message || '审批失败') }
  }

  const handleRejectClick = (id: string) => { setRejectRecordId(id); setRejectReason(''); setRejectModalVisible(true) }

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) { message.warning('请输入驳回原因'); return }
    const response = await rejectPermit(rejectRecordId, rejectReason)
    if (response.code === 200) { message.success('已驳回'); updatePermitInStore(rejectRecordId, response.data); setRejectModalVisible(false) }
    else { message.error(response.message || '驳回失败') }
  }

  const handleStartPermit = async (id: string) => {
    const response = await startPermit(id)
    if (response.code === 200) { message.success('作业已开始'); updatePermitInStore(id, response.data) }
    else { message.error(response.message || '操作失败') }
  }

  const handleCompletePermit = (id: string) => {
    Modal.confirm({
      title: '完工确认', content: '请选择完工方式：',
      okText: '正常完工', cancelText: '提前终止',
      onOk: async () => {
        const response = await completePermit(id, 'normal')
        if (response.code === 200) { message.success('已正常完工'); updatePermitInStore(id, response.data) }
        else { message.error(response.message || '操作失败') }
      },
      onCancel: async () => {
        const response = await completePermit(id, 'early_termination')
        if (response.code === 200) { message.success('已提前终止'); updatePermitInStore(id, response.data) }
        else { message.error(response.message || '操作失败') }
      },
    })
  }

  const handleArchivePermit = async (id: string) => {
    const response = await archivePermit(id)
    if (response.code === 200) { message.success('已归档'); updatePermitInStore(id, response.data) }
    else { message.error(response.message || '归档失败') }
  }

  const columns: ColumnsType<SpecialOperationPermit> = [
    { title: '作业票编号', dataIndex: 'permit_no', key: 'permit_no', width: 140 },
    {
      title: '作业类型', dataIndex: 'operation_type', key: 'operation_type', width: 120,
      render: (t: string) => { const opt = OPERATION_TYPE_OPTIONS.find(o => o.value === t); return <Tag>{opt?.label || t}</Tag> },
    },
    {
      title: '级别', dataIndex: 'operation_level', key: 'operation_level', width: 80,
      render: (l: string) => { const opt = OPERATION_LEVEL_OPTIONS.find(o => o.value === l); return <Tag color={opt?.color}>{opt?.label || l}</Tag> },
    },
    { title: '作业地点', dataIndex: 'location', key: 'location', width: 130, ellipsis: true },
    { title: '设备位号', dataIndex: 'equipment_tag', key: 'equipment_tag', width: 100 },
    {
      title: '计划开始', dataIndex: 'planned_start_time', key: 'planned_start_time', width: 120,
      render: (d: string) => d ? dayjs(d).format('MM-DD HH:mm') : '-',
    },
    {
      title: '计划结束', dataIndex: 'planned_end_time', key: 'planned_end_time', width: 120,
      render: (d: string) => d ? dayjs(d).format('MM-DD HH:mm') : '-',
    },
    { title: '申请人', dataIndex: 'applicant_name', key: 'applicant_name', width: 90 },
    { title: '作业负责人', dataIndex: 'work_leader_name', key: 'work_leader_name', width: 110 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => { const opt = PERMIT_STATUS_OPTIONS.find(o => o.value === s); return <Tag color={opt?.color}>{opt?.label || s}</Tag> },
    },
    {
      title: '操作', key: 'action', width: 320, fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSubmitPermit(record.id)}>提交</Button>
          )}
          {record.status === 'submitted' && (
            <>
              <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleApprovePermit(record.id)}>审批</Button>
              <Button type="link" size="small" icon={<CloseCircleOutlined />} onClick={() => handleRejectClick(record.id)}>驳回</Button>
            </>
          )}
          {record.status === 'approved' && (
            <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => handleStartPermit(record.id)}>开始作业</Button>
          )}
          {record.status === 'in_progress' && (
            <Button type="link" size="small" icon={<FlagOutlined />} onClick={() => handleCompletePermit(record.id)}>完工</Button>
          )}
          {record.status === 'completed' && (
            <Button type="link" size="small" icon={<InboxOutlined />} onClick={() => handleArchivePermit(record.id)}>归档</Button>
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
          <Form.Item name="permit_no" label="作业票编号" rules={[{ required: true }]}>
            <Input placeholder="自动生成或手动输入" />
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
          <Form.Item name="operation_level" label="作业级别">
            <Select options={OPERATION_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="请选择级别" />
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
          <Form.Item name="equipment_tag" label="设备位号">
            <Input placeholder="请输入设备位号" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="planned_start_time" label="计划开始时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="planned_end_time" label="计划结束时间">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="work_description" label="作业内容描述">
        <Input.TextArea rows={2} placeholder="请输入作业内容描述" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="applicant_name" label="申请人">
            <Input placeholder="申请人" />
          </Form.Item>
        </Col>
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
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="operator_names" label="作业人员">
            <Input placeholder="多名以逗号分隔" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="approver_name" label="审批人">
            <Input placeholder="审批人" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="safety_measures" label="安全措施">
        <Input.TextArea rows={2} placeholder="请描述安全措施" />
      </Form.Item>
      <Form.Item name="emergency_equipment" label="应急消防器材">
        <Input.TextArea rows={2} placeholder="请列出应急消防器材" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="gas_analysis" label="气体分析结果">
            <Input.TextArea rows={2} placeholder="气体分析结果" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="risk_assessment" label="风险评估">
            <Input.TextArea rows={2} placeholder="风险评估" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="notes" label="备注">
        <Input.TextArea rows={2} placeholder="请输入备注" />
      </Form.Item>
    </>
  )

  return (
    <div>
      <Row gutter={16} className="mb-4">
        <Col span={6}>
          <Input placeholder="搜索编号/描述" prefix={<SearchOutlined />} value={searchText}
            onChange={e => setSearchText(e.target.value)} onPressEnter={handleSearch} />
        </Col>
        <Col span={5}>
          <Select placeholder="作业类型" allowClear value={operationTypeFilter}
            onChange={v => { setOperationTypeFilter(v); setPermitQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={OPERATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={5}>
          <Select placeholder="状态" allowClear value={statusFilter}
            onChange={v => { setStatusFilter(v); setPermitQueryParams({ page: 1 }) }}
            style={{ width: '100%' }}
            options={PERMIT_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} />
        </Col>
        <Col span={3}>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
        </Col>
        <Col span={5} className="text-right">
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建作业票</Button>
        </Col>
      </Row>

      <Table columns={columns} dataSource={permits} rowKey="id" loading={loading} scroll={{ x: 1600 }}
        pagination={{
          current: permitQueryParams.page, pageSize: permitQueryParams.page_size, total: permitTotal,
          showSizeChanger: true, showTotal: t => `共 ${t} 条`,
          onChange: (page, pageSize) => setPermitQueryParams({ page, page_size: pageSize }),
        }} />

      <Modal title={editingRecord ? '编辑作业票' : '新建作业票'} open={modalVisible}
        onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={850} okText="确认" cancelText="取消">
        <Form form={editingRecord ? editForm : form} layout="vertical" initialValues={{ operation_level: 'grade2' }}>
          {formContent}
        </Form>
      </Modal>

      <Modal title="驳回原因" open={rejectModalVisible}
        onOk={handleRejectConfirm} onCancel={() => setRejectModalVisible(false)} okText="确认驳回">
        <Input.TextArea rows={3} value={rejectReason} onChange={e => setRejectReason(e.target.value)}
          placeholder="请输入驳回原因" />
      </Modal>
    </div>
  )
}

// ==================== Main Page ====================

export default function SpecialOpsPage() {
  return (
    <div className="space-y-4">
      <Typography.Title level={4} className="mb-1">特殊作业管理</Typography.Title>
      <Typography.Text type="secondary">八大特殊作业票管理、人员资质证书管理与有效期跟踪</Typography.Text>

      <Tabs
        defaultActiveKey="permits"
        items={[
          {
            key: 'permits',
            label: <span><SafetyCertificateOutlined /> 作业票管理</span>,
            children: <PermitPanel />,
          },
          {
            key: 'personnel',
            label: <span><TeamOutlined /> 人员资质管理</span>,
            children: <PersonnelPanel />,
          },
        ]}
      />
    </div>
  )
}
