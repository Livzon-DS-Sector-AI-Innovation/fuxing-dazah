'use client'

import { useState } from 'react'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  DatePicker,
  InputNumber,
  message,
  Tag,
  Card,
  Row,
  Col,
  Tabs,
  Switch,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  TeamOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchTrainings, fetchTrainingRecords, fetchTrainingCertificates } from '@/lib/api/safety/training'
import {
  createTraining,
  updateTraining,
  startTraining,
  completeTraining,
  deleteTraining,
  createTrainingRecord,
  updateTrainingRecord,
  deleteTrainingRecord,
} from '@/actions/safety'
import type {
  SafetyTraining,
  SafetyTrainingFormData,
  TrainingRecord,
  TrainingRecordFormData,
  TrainingType,
  TrainingMode,
} from '@/types/safety'
import {
  TRAINING_TYPE_OPTIONS,
  TRAINING_MODE_OPTIONS,
  TRAINING_STATUS_OPTIONS,
  TRAINING_LEVEL_OPTIONS,
  CERTIFICATE_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'


export default function TrainingPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyTraining | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // Training record state
  const [recordModalVisible, setRecordModalVisible] = useState(false)
  const [currentTrainingId, setCurrentTrainingId] = useState<string | null>(null)
  const [currentTrainingName, setCurrentTrainingName] = useState('')
  const [recordForm] = Form.useForm()
  const [editingRecordItem, setEditingRecordItem] = useState<TrainingRecord | null>(null)
  const [batchRecordVisible, setBatchRecordVisible] = useState(false)
  const [batchRecordForm] = Form.useForm()

  // Certificate tab state
  const [activeTab, setActiveTab] = useState('training')
  const [certPage, setCertPage] = useState(1)
  const [certPageSize, setCertPageSize] = useState(20)
  const [certStatusFilter, setCertStatusFilter] = useState<string | undefined>()
  const [certKeyword, setCertKeyword] = useState('')

  const queryClient = useQueryClient()

  const refreshTrainings = () => {
    queryClient.invalidateQueries({ queryKey: ['trainings'] })
  }

  // 培训列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['trainings', { page, pageSize, statusFilter, typeFilter }],
    queryFn: () => fetchTrainings({
      page, page_size: pageSize,
      status: statusFilter,
      training_type: typeFilter,
    }),
  })
  const trainings = listData?.items ?? []
  const trainingTotal = listData?.total ?? 0

  // 培训记录 query（选中培训时启用）
  const recordsQuery = useQuery({
    queryKey: ['training-records', currentTrainingId],
    queryFn: () => fetchTrainingRecords(currentTrainingId!),
    enabled: !!currentTrainingId,
  })
  const records = recordsQuery.data ?? []
  const recordsLoading = recordsQuery.isLoading

  // 证书列表 query（证书 tab 激活时启用）
  const certQuery = useQuery({
    queryKey: ['training-certificates', { certPage, certPageSize, certStatusFilter, certKeyword }],
    queryFn: () => fetchTrainingCertificates({
      page: certPage, page_size: certPageSize,
      certificate_status: certStatusFilter,
      keyword: certKeyword || undefined,
    }),
    enabled: activeTab === 'certificate',
  })
  const certificates = certQuery.data?.items ?? []
  const certTotal = certQuery.data?.total ?? 0
  const certLoading = certQuery.isLoading

  const handleSearch = () => setPage(1)

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: SafetyTraining) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      training_date: record.training_date ? dayjs(record.training_date) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个培训记录吗？',
      onOk: async () => {
        try {
          const response = await deleteTraining(id)
          if (response.code === 200) {
            message.success('删除成功')
            refreshTrainings()
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        training_date: values.training_date ? values.training_date.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateTraining(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          refreshTrainings()
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createTraining(formattedValues as SafetyTrainingFormData)
        if (response.code === 200) {
          message.success('创建成功')
          refreshTrainings()
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

  const handleStart = async (id: string) => {
    try {
      const response = await startTraining(id)
      if (response.code === 200) {
        message.success('培训已开始')
        refreshTrainings()
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  const handleComplete = async (id: string) => {
    try {
      const response = await completeTraining(id)
      if (response.code === 200) {
        message.success('培训已完成')
        refreshTrainings()
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  const certColumns: ColumnsType<TrainingRecord> = [
    { title: '员工姓名', dataIndex: 'employee_name', key: 'employee_name', width: 100 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100 },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 100 },
    { title: '证书编号', dataIndex: 'certificate_no', key: 'certificate_no', width: 140 },
    {
      title: '证书有效期', dataIndex: 'certificate_expiry', key: 'certificate_expiry', width: 120,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    {
      title: '证书状态', dataIndex: 'certificate_status', key: 'certificate_status', width: 100,
      render: (s: string) => {
        const opt = CERTIFICATE_STATUS_OPTIONS.find(o => o.value === s)
        return <Tag color={opt?.color}>{opt?.label || s || '-'}</Tag>
      },
    },
    { title: '成绩', dataIndex: 'score', key: 'score', width: 70, render: (v: number) => v != null ? `${v}分` : '-' },
    { title: '培训', dataIndex: 'training_id', key: 'training_id', width: 80, render: () => '-' },
  ]

  // ============ Training Record Operations ============

  const handleManageRecords = (record: SafetyTraining) => {
    setCurrentTrainingId(record.id)
    setCurrentTrainingName(record.training_name)
    setRecordModalVisible(true)
  }

  const handleAddRecord = () => {
    setEditingRecordItem(null)
    recordForm.resetFields()
    recordForm.setFieldsValue({ attendance: true })
    setBatchRecordVisible(false)
  }

  const handleEditRecord = (record: TrainingRecord) => {
    setEditingRecordItem(record)
    recordForm.setFieldsValue({
      ...record,
      certificate_expiry: record.certificate_expiry ? dayjs(record.certificate_expiry) : undefined,
    })
    setBatchRecordVisible(false)
  }

  const handleDeleteRecord = (recordId: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这条培训记录吗？',
      onOk: async () => {
        try {
          const response = await deleteTrainingRecord(recordId)
          if (response.code === 200) {
            message.success('删除成功')
            queryClient.invalidateQueries({ queryKey: ['training-records'] })
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleSaveRecord = async () => {
    if (!currentTrainingId) return
    try {
      const values = await recordForm.validateFields()
      const payload = {
        ...values,
        certificate_expiry: values.certificate_expiry
          ? values.certificate_expiry.toISOString() : undefined,
      }

      if (editingRecordItem) {
        const response = await updateTrainingRecord(editingRecordItem.id, payload)
        if (response.code === 200) {
          message.success('更新成功')
          queryClient.invalidateQueries({ queryKey: ['training-records'] })
          recordForm.resetFields()
          setEditingRecordItem(null)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createTrainingRecord(currentTrainingId, payload as TrainingRecordFormData)
        if (response.code === 200) {
          message.success('添加成功')
          queryClient.invalidateQueries({ queryKey: ['training-records'] })
          recordForm.resetFields()
        } else {
          message.error(response.message || '添加失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleBatchAddRecords = async () => {
    if (!currentTrainingId) return
    try {
      const values = await batchRecordForm.validateFields()
      const names = (values.employee_names || '')
        .split('\n')
        .map((s: string) => s.trim())
        .filter(Boolean)

      for (const name of names) {
        await createTrainingRecord(currentTrainingId, {
          employee_name: name,
          department: values.department,
          attendance: true,
        } as TrainingRecordFormData)
      }

      message.success(`成功添加 ${names.length} 人`)
      queryClient.invalidateQueries({ queryKey: ['training-records'] })
      setBatchRecordVisible(false)
      batchRecordForm.resetFields()
    } catch {
      console.error('批量添加失败')
    }
  }

  const columns: ColumnsType<SafetyTraining> = [
    {
      title: '培训编号',
      dataIndex: 'training_no',
      key: 'training_no',
      width: 150,
    },
    {
      title: '培训名称',
      dataIndex: 'training_name',
      key: 'training_name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'training_type',
      key: 'training_type',
      width: 100,
      render: (type: TrainingType) => {
        const option = TRAINING_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '方式',
      dataIndex: 'training_mode',
      key: 'training_mode',
      width: 80,
      render: (mode: TrainingMode) => {
        const option = TRAINING_MODE_OPTIONS.find((o) => o.value === mode)
        return <Tag>{option?.label || mode}</Tag>
      },
    },
    {
      title: '讲师',
      dataIndex: 'trainer_name',
      key: 'trainer_name',
      width: 100,
    },
    {
      title: '培训日期',
      dataIndex: 'training_date',
      key: 'training_date',
      width: 110,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '时长(h)',
      dataIndex: 'duration_hours',
      key: 'duration_hours',
      width: 80,
      render: (val: number) => val ?? '-',
    },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const option = TRAINING_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === 'draft' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStart(record.id)}
            >
              开始
            </Button>
          )}
          {record.status === 'in_progress' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<CheckCircleOutlined />}
                onClick={() => handleComplete(record.id)}
              >
                完成
              </Button>
            </>
          )}
          <Button
            type="link"
            size="small"
            icon={<TeamOutlined />}
            onClick={() => handleManageRecords(record)}
          >
            签到
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const recordColumns: ColumnsType<TrainingRecord> = [
    {
      title: '员工姓名',
      dataIndex: 'employee_name',
      key: 'employee_name',
      width: 100,
    },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 100,
    },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 100,
    },
    {
      title: '出席',
      dataIndex: 'attendance',
      key: 'attendance',
      width: 70,
      render: (val: boolean) => val ? <Tag color="success">是</Tag> : <Tag color="error">否</Tag>,
    },
    {
      title: '考核成绩',
      dataIndex: 'score',
      key: 'score',
      width: 90,
      render: (val: number) => val !== undefined && val !== null ? `${val}分` : '-',
    },
    {
      title: '合格',
      dataIndex: 'passed',
      key: 'passed',
      width: 70,
      render: (val: boolean | null) => {
        if (val === null || val === undefined) return '-'
        return val ? <Tag color="success">是</Tag> : <Tag color="error">否</Tag>
      },
    },
    {
      title: '证书编号',
      dataIndex: 'certificate_no',
      key: 'certificate_no',
      width: 130,
      ellipsis: true,
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 120,
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleEditRecord(record)}>
            编辑
          </Button>
          <Button type="link" size="small" danger onClick={() => handleDeleteRecord(record.id)}>
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="p-6">
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        {
          key: 'training',
          label: '培训计划',
          children: (
            <Card
              extra={
                <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
                  新建培训
                </Button>
              }
            >
              <Row gutter={16} className="mb-4">
                <Col span={5}>
                  <Input
                    placeholder="搜索培训名称"
                    prefix={<SearchOutlined />}
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    onPressEnter={handleSearch}
                  />
                </Col>
                <Col span={4}>
                  <Select
                    placeholder="培训类型"
                    allowClear
                    value={typeFilter}
                    onChange={(value) => {
                      setTypeFilter(value)
                      setPage(1)
                    }}
                    style={{ width: '100%' }}
                    options={TRAINING_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Col>
                <Col span={4}>
                  <Select
                    placeholder="状态"
                    allowClear
                    value={statusFilter}
                    onChange={(value) => {
                      setStatusFilter(value)
                      setPage(1)
                    }}
                    style={{ width: '100%' }}
                    options={TRAINING_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Col>
                <Col span={3}>
                  <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                    查询
                  </Button>
                </Col>
              </Row>

              <Table
                columns={columns}
                dataSource={trainings}
                rowKey="id"
                loading={isLoading}
                scroll={{ x: 1400 }}
                pagination={{
                  current: page,
                  pageSize,
                  total: trainingTotal,
                  showSizeChanger: true,
                  showQuickJumper: true,
                  showTotal: (total) => `共 ${total} 条`,
                  onChange: (nextPage, nextPageSize) => {
                    setPage(nextPage)
                    setPageSize(nextPageSize)
                  },
                }}
              />
            </Card>
          ),
        },
        {
          key: 'certificate',
          label: '证书管理',
          children: (
            <Card>
              <Row gutter={16} className="mb-4">
                <Col span={5}>
                  <Input
                    placeholder="搜索姓名/证书编号"
                    prefix={<SearchOutlined />}
                    value={certKeyword}
                    onChange={(e) => setCertKeyword(e.target.value)}
                    onPressEnter={() => { setCertPage(1) }}
                  />
                </Col>
                <Col span={4}>
                  <Select
                    placeholder="证书状态"
                    allowClear
                    value={certStatusFilter}
                    onChange={(v) => { setCertStatusFilter(v); setCertPage(1) }}
                    style={{ width: '100%' }}
                    options={CERTIFICATE_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Col>
                <Col span={3}>
                  <Button type="primary" icon={<SearchOutlined />} onClick={() => { setCertPage(1) }}>
                    查询
                  </Button>
                </Col>
              </Row>

              <Table
                columns={certColumns}
                dataSource={certificates}
                rowKey="id"
                loading={certLoading}
                scroll={{ x: 900 }}
                pagination={{
                  current: certPage,
                  pageSize: certPageSize,
                  total: certTotal,
                  showSizeChanger: true,
                  showTotal: (total) => `共 ${total} 条`,
                  onChange: (page, pageSize) => { setCertPage(page); setCertPageSize(pageSize) },
                }}
              />
            </Card>
          ),
        },
      ]} />

      {/* Create/Edit Training Modal */}
      <Modal
        title={editingRecord ? '编辑培训' : '新建培训'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={700}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingRecord ? editForm : form}
          layout="vertical"
          initialValues={editingRecord || { training_type: 'annual', training_mode: 'offline', training_level: 'dept', exam_passing_score: 60 }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="training_no"
                label="培训编号"
                rules={[{ required: true, message: '请输入培训编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="training_name"
                label="培训名称"
                rules={[{ required: true, message: '请输入培训名称' }]}
              >
                <Input placeholder="请输入培训名称" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="training_type"
                label="培训类型"
                rules={[{ required: true, message: '请选择培训类型' }]}
              >
                <Select options={TRAINING_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="training_mode"
                label="培训方式"
                rules={[{ required: true, message: '请选择培训方式' }]}
              >
                <Select options={TRAINING_MODE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="training_level" label="培训级别">
                <Select options={TRAINING_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="duration_hours" label="培训时长(小时)">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="exam_passing_score" label="及格分数线">
                <InputNumber min={0} max={100} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="training_date"
                label="培训日期"
                rules={[{ required: true, message: '请选择培训日期' }]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="location" label="培训地点">
                <Input placeholder="请输入培训地点" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="trainer_name" label="讲师">
                <Input placeholder="请输入讲师姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="department" label="培训部门">
                <Input placeholder="请输入培训部门" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="content" label="培训内容">
            <Input.TextArea rows={3} placeholder="请描述培训内容" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Training Records Modal */}
      <Modal
        title={`签到管理 - ${currentTrainingName}`}
        open={recordModalVisible}
        onCancel={() => setRecordModalVisible(false)}
        width={900}
        footer={null}
      >
        <div className="mb-4">
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddRecord}>
              添加签到
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => setBatchRecordVisible(true)}>
              批量导入
            </Button>
          </Space>
        </div>

        <Table
          columns={recordColumns}
          dataSource={records}
          rowKey="id"
          loading={recordsLoading}
          size="small"
          pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 人` }}
        />

        {/* Single Record Form */}
        {(recordForm || editingRecordItem) && (
          <Card
            title={editingRecordItem ? '编辑签到记录' : '添加签到'}
            size="small"
            className="mt-4"
          >
            <Form
              form={recordForm}
              layout="inline"
              initialValues={{ attendance: true }}
            >
              <Form.Item
                name="employee_name"
                label="姓名"
                rules={[{ required: true, message: '请输入姓名' }]}
              >
                <Input placeholder="员工姓名" style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="department" label="部门">
                <Input placeholder="部门" style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="position" label="岗位">
                <Input placeholder="岗位" style={{ width: 100 }} />
              </Form.Item>
              <Form.Item name="attendance" label="出席" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
              <Form.Item name="score" label="成绩">
                <InputNumber min={0} max={100} style={{ width: 70 }} />
              </Form.Item>
              <Form.Item name="passed" label="合格" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Form>
            <Form
              form={recordForm}
              layout="inline"
              className="mt-2"
            >
              <Form.Item name="certificate_no" label="证书编号">
                <Input placeholder="证书编号" style={{ width: 140 }} />
              </Form.Item>
              <Form.Item name="certificate_expiry" label="证书有效期">
                <DatePicker style={{ width: 140 }} placeholder="选择日期" />
              </Form.Item>
              <Form.Item name="notes" label="备注">
                <Input placeholder="备注" style={{ width: 150 }} />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" onClick={handleSaveRecord}>
                    {editingRecordItem ? '更新' : '添加'}
                  </Button>
                  {editingRecordItem && (
                    <Button onClick={() => {
                      setEditingRecordItem(null)
                      recordForm.resetFields()
                    }}>
                      取消
                    </Button>
                  )}
                </Space>
              </Form.Item>
            </Form>
          </Card>
        )}

        {/* Batch Import Form */}
        <Modal
          title="批量导入签到人员"
          open={batchRecordVisible}
          onOk={handleBatchAddRecords}
          onCancel={() => setBatchRecordVisible(false)}
          okText="导入"
          cancelText="取消"
        >
          <Form form={batchRecordForm} layout="vertical">
            <Form.Item name="department" label="部门">
              <Input placeholder="统一部门（可选）" />
            </Form.Item>
            <Form.Item
              name="employee_names"
              label="人员名单"
              rules={[{ required: true, message: '请输入人员姓名' }]}
            >
              <Input.TextArea
                rows={6}
                placeholder={"每行一个姓名，如：\n张三\n李四\n王五"}
              />
            </Form.Item>
          </Form>
        </Modal>
      </Modal>
    </div>
  )
}
