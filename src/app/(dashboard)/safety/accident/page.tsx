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
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  SearchOutlined as SearchIcon,
  AuditOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getAccidents,
  createAccident,
  updateAccident,
  investigateAccident,
  resolveAccident,
  closeAccident,
  deleteAccident,
} from '@/actions/safety'
import type {
  Accident,
  AccidentFormData,
  AccidentType,
  AccidentLevel,
} from '@/types/safety'
import {
  ACCIDENT_TYPE_OPTIONS,
  ACCIDENT_LEVEL_OPTIONS,
  ACCIDENT_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text, TextArea } = Typography

export default function AccidentPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [resolveModalVisible, setResolveModalVisible] = useState(false)
  const [currentAccidentId, setCurrentAccidentId] = useState<string | null>(null)
  const [resolveForm] = Form.useForm()
  const [editingRecord, setEditingRecord] = useState<Accident | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [levelFilter, setLevelFilter] = useState<string | undefined>()

  const {
    accidents,
    accidentTotal,
    accidentQueryParams,
    setAccidents,
    setAccidentTotal,
    setAccidentQueryParams,
    addAccident,
    updateAccident: updateAccidentInStore,
    removeAccident,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getAccidents({
        ...accidentQueryParams,
        status: statusFilter,
        accident_type: typeFilter,
        accident_level: levelFilter,
      })
      if (response.code === 200) {
        setAccidents(response.data)
        setAccidentTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载事故列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [accidentQueryParams.page, accidentQueryParams.page_size, statusFilter, typeFilter, levelFilter])

  const handleSearch = () => {
    setAccidentQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: Accident) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      happened_at: record.happened_at ? dayjs(record.happened_at) : undefined,
      reported_at: record.reported_at ? dayjs(record.reported_at) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个事故记录吗？',
      onOk: async () => {
        try {
          const response = await deleteAccident(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeAccident(id)
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
        happened_at: values.happened_at ? values.happened_at.toISOString() : undefined,
        reported_at: values.reported_at ? values.reported_at.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateAccident(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updateAccidentInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createAccident(formattedValues as AccidentFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addAccident(response.data)
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

  const handleInvestigate = async (id: string) => {
    try {
      const response = await investigateAccident(id)
      if (response.code === 200) {
        message.success('已开始调查')
        updateAccidentInStore(id, response.data)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  const handleResolve = (id: string) => {
    setCurrentAccidentId(id)
    resolveForm.resetFields()
    setResolveModalVisible(true)
  }

  const handleResolveSubmit = async () => {
    if (!currentAccidentId) return
    try {
      const values = await resolveForm.validateFields()
      const response = await resolveAccident(
        currentAccidentId,
        values.direct_cause,
        values.root_cause,
        values.handling_measures,
        values.corrective_actions,
      )
      if (response.code === 200) {
        message.success('事故已处理')
        updateAccidentInStore(currentAccidentId, response.data)
        setResolveModalVisible(false)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleClose = async (id: string) => {
    Modal.confirm({
      title: '确认关闭',
      content: '确定要关闭这个事故吗？',
      onOk: async () => {
        const response = await closeAccident(id)
        if (response.code === 200) {
          message.success('事故已关闭')
          updateAccidentInStore(id, response.data)
        } else {
          message.error(response.message || '关闭失败')
        }
      },
    })
  }

  const getLevelColor = (level: AccidentLevel) => {
    const option = ACCIDENT_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.color || 'default'
  }

  const getLevelLabel = (level: AccidentLevel) => {
    const option = ACCIDENT_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.label || level
  }

  const columns: ColumnsType<Accident> = [
    {
      title: '事故编号',
      dataIndex: 'accident_no',
      key: 'accident_no',
      width: 150,
    },
    {
      title: '事故类型',
      dataIndex: 'accident_type',
      key: 'accident_type',
      width: 100,
      render: (type: AccidentType) => {
        const option = ACCIDENT_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '等级',
      dataIndex: 'accident_level',
      key: 'accident_level',
      width: 110,
      render: (level: AccidentLevel) => (
        <Tag color={getLevelColor(level)}>{getLevelLabel(level)}</Tag>
      ),
    },
    {
      title: '发生时间',
      dataIndex: 'happened_at',
      key: 'happened_at',
      width: 130,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
      width: 130,
      ellipsis: true,
    },
    {
      title: '事故描述',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      ellipsis: true,
    },
    {
      title: '伤亡情况',
      dataIndex: 'casualties',
      key: 'casualties',
      width: 120,
      render: (text: string) => text || '-',
    },
    {
      title: '报告人',
      dataIndex: 'reported_by_name',
      key: 'reported_by_name',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const option = ACCIDENT_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === 'reported' && (
            <Button
              type="link"
              size="small"
              icon={<AuditOutlined />}
              onClick={() => handleInvestigate(record.id)}
            >
              调查
            </Button>
          )}
          {record.status === 'investigating' && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleResolve(record.id)}
            >
              处理
            </Button>
          )}
          {record.status === 'resolved' && (
            <Button
              type="link"
              size="small"
              icon={<CloseCircleOutlined />}
              onClick={() => handleClose(record.id)}
            >
              关闭
            </Button>
          )}
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

  return (
    <div className="p-6">
      <Card
        title="事故管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建事故
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索事故编号"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="事故类型"
              allowClear
              value={typeFilter}
              onChange={(value) => {
                setTypeFilter(value)
                setAccidentQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={ACCIDENT_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="事故等级"
              allowClear
              value={levelFilter}
              onChange={(value) => {
                setLevelFilter(value)
                setAccidentQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={ACCIDENT_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setAccidentQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={ACCIDENT_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
          dataSource={accidents}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1500 }}
          pagination={{
            current: accidentQueryParams.page,
            pageSize: accidentQueryParams.page_size,
            total: accidentTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setAccidentQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      {/* Create/Edit Modal */}
      <Modal
        title={editingRecord ? '编辑事故' : '新建事故'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={800}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingRecord ? editForm : form}
          layout="vertical"
          initialValues={editingRecord || { accident_level: 'general' }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="accident_no"
                label="事故编号"
                rules={[{ required: true, message: '请输入事故编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="accident_type"
                label="事故类型"
                rules={[{ required: true, message: '请选择事故类型' }]}
              >
                <Select options={ACCIDENT_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="accident_level"
                label="事故等级"
                rules={[{ required: true, message: '请选择事故等级' }]}
              >
                <Select options={ACCIDENT_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="happened_at"
                label="发生时间"
                rules={[{ required: true, message: '请选择发生时间' }]}
              >
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="location" label="发生地点">
                <Input placeholder="请输入发生地点" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="casualties" label="伤亡情况">
                <Input placeholder="如：无、1人轻伤等" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="property_damage" label="财产损失(元)">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入财产损失" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="description"
            label="事故描述"
            rules={[{ required: true, message: '请输入事故描述' }]}
          >
            <Input.TextArea rows={3} placeholder="请详细描述事故经过" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="reported_by_name" label="报告人">
                <Input placeholder="请输入报告人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="reported_at"
                label="报告时间"
                rules={[{ required: true, message: '请选择报告时间' }]}
              >
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Resolve Modal */}
      <Modal
        title="处理事故"
        open={resolveModalVisible}
        onOk={handleResolveSubmit}
        onCancel={() => setResolveModalVisible(false)}
        width={700}
        okText="确认处理"
        cancelText="取消"
      >
        <Form
          form={resolveForm}
          layout="vertical"
        >
          <Form.Item
            name="direct_cause"
            label="直接原因"
            rules={[{ required: true, message: '请输入直接原因' }]}
          >
            <Input.TextArea rows={3} placeholder="请输入事故的直接原因" />
          </Form.Item>
          <Form.Item
            name="root_cause"
            label="根本原因"
            rules={[{ required: true, message: '请输入根本原因' }]}
          >
            <Input.TextArea rows={3} placeholder="请输入事故的根本原因" />
          </Form.Item>
          <Form.Item
            name="handling_measures"
            label="处理措施"
            rules={[{ required: true, message: '请输入处理措施' }]}
          >
            <Input.TextArea rows={3} placeholder="请描述已采取的处理措施" />
          </Form.Item>
          <Form.Item name="corrective_actions" label="纠正预防措施">
            <Input.TextArea rows={3} placeholder="请描述纠正和预防措施" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
