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
  InputNumber,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
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
import { useSafetyStore } from '@/stores/safety'
import {
  getTrainings,
  createTraining,
  updateTraining,
  startTraining,
  completeTraining,
  deleteTraining,
  getTrainingRecords,
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
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function TrainingPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyTraining | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  // Training record state
  const [recordModalVisible, setRecordModalVisible] = useState(false)
  const [currentTrainingId, setCurrentTrainingId] = useState<string | null>(null)
  const [currentTrainingName, setCurrentTrainingName] = useState('')
  const [records, setRecords] = useState<TrainingRecord[]>([])
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [recordForm] = Form.useForm()
  const [editingRecordItem, setEditingRecordItem] = useState<TrainingRecord | null>(null)
  const [batchRecordVisible, setBatchRecordVisible] = useState(false)
  const [batchRecordForm] = Form.useForm()

  const {
    trainings,
    trainingTotal,
    trainingQueryParams,
    setTrainings,
    setTrainingTotal,
    setTrainingQueryParams,
    addTraining,
    updateTraining: updateTrainingInStore,
    removeTraining,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getTrainings({
        ...trainingQueryParams,
        status: statusFilter,
        training_type: typeFilter,
      })
      if (response.code === 200) {
        setTrainings(response.data)
        setTrainingTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载培训列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [trainingQueryParams.page, trainingQueryParams.page_size, statusFilter, typeFilter])

  const handleSearch = () => {
    setTrainingQueryParams({ page: 1 })
    loadData()
  }

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
            removeTraining(id)
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
          updateTrainingInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createTraining(formattedValues as SafetyTrainingFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addTraining(response.data)
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
        updateTrainingInStore(id, response.data)
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
        updateTrainingInStore(id, response.data)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  // ============ Training Record Operations ============

  const loadRecords = async (trainingId: string) => {
    setRecordsLoading(true)
    try {
      const response = await getTrainingRecords(trainingId)
      if (response.code === 200) {
        setRecords(response.data || [])
      }
    } catch {
      message.error('加载培训记录失败')
    } finally {
      setRecordsLoading(false)
    }
  }

  const handleManageRecords = (record: SafetyTraining) => {
    setCurrentTrainingId(record.id)
    setCurrentTrainingName(record.training_name)
    loadRecords(record.id)
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
    recordForm.setFieldsValue(record)
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
            setRecords(records.filter((r) => r.id !== recordId))
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

      if (editingRecordItem) {
        const response = await updateTrainingRecord(editingRecordItem.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          loadRecords(currentTrainingId)
          recordForm.resetFields()
          setEditingRecordItem(null)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createTrainingRecord(currentTrainingId, values as TrainingRecordFormData)
        if (response.code === 200) {
          message.success('添加成功')
          loadRecords(currentTrainingId)
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
      loadRecords(currentTrainingId)
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
      width: 120,
    },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
    },
    {
      title: '出席',
      dataIndex: 'attendance',
      key: 'attendance',
      width: 80,
      render: (val: boolean) => val ? <Tag color="success">是</Tag> : <Tag color="error">否</Tag>,
    },
    {
      title: '考核成绩',
      dataIndex: 'score',
      key: 'score',
      width: 100,
      render: (val: number) => val !== undefined && val !== null ? `${val}分` : '-',
    },
    {
      title: '合格',
      dataIndex: 'passed',
      key: 'passed',
      width: 80,
      render: (val: boolean | null) => {
        if (val === null || val === undefined) return '-'
        return val ? <Tag color="success">是</Tag> : <Tag color="error">否</Tag>
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      width: 150,
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
      <Card
        title="安全培训"
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
                setTrainingQueryParams({ page: 1 })
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
                setTrainingQueryParams({ page: 1 })
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
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: trainingQueryParams.page,
            pageSize: trainingQueryParams.page_size,
            total: trainingTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setTrainingQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

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
          initialValues={editingRecord || { training_type: 'annual', training_mode: 'offline' }}
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
              <Form.Item name="duration_hours" label="培训时长(小时)">
                <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
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
                <Input placeholder="员工姓名" style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="department" label="部门">
                <Input placeholder="部门" style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="attendance" label="出席" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
              <Form.Item name="score" label="成绩">
                <InputNumber min={0} max={100} style={{ width: 80 }} />
              </Form.Item>
              <Form.Item name="passed" label="合格" valuePropName="checked">
                <Switch checkedChildren="是" unCheckedChildren="否" />
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
