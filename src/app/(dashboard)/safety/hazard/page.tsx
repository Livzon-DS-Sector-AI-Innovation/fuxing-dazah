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
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  VerifyOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getHazards,
  createHazard,
  updateHazard,
  startRectification,
  completeRectification,
  verifyRectification,
  deleteHazard,
} from '@/actions/safety'
import type {
  HazardReport,
  HazardReportFormData,
  HazardType,
  HazardLevel,
} from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_STATUS_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function HazardPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<HazardReport | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [levelFilter, setLevelFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  const {
    hazards,
    hazardTotal,
    hazardQueryParams,
    setHazards,
    setHazardTotal,
    setHazardQueryParams,
    addHazard,
    updateHazard: updateHazardInStore,
    removeHazard,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getHazards({
        ...hazardQueryParams,
        status: statusFilter,
        hazard_type: typeFilter,
        hazard_level: levelFilter,
      })
      if (response.code === 200) {
        setHazards(response.data)
        setHazardTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载隐患排查列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [hazardQueryParams.page, hazardQueryParams.page_size, statusFilter, typeFilter, levelFilter])

  const handleSearch = () => {
    setHazardQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: HazardReport) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      discovered_at: record.discovered_at ? dayjs(record.discovered_at) : undefined,
      deadline: record.deadline ? dayjs(record.deadline) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个隐患记录吗？',
      onOk: async () => {
        try {
          const response = await deleteHazard(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeHazard(id)
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
        discovered_at: values.discovered_at ? values.discovered_at.toISOString() : undefined,
        deadline: values.deadline ? values.deadline.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateHazard(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updateHazardInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createHazard(formattedValues as HazardReportFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addHazard(response.data)
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

  const handleStartRectification = async (id: string) => {
    try {
      const response = await startRectification(id)
      if (response.code === 200) {
        message.success('已开始整改')
        updateHazardInStore(id, response.data)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  const handleCompleteRectification = async (id: string) => {
    try {
      const response = await completeRectification(id)
      if (response.code === 200) {
        message.success('整改完成，等待验证')
        updateHazardInStore(id, response.data)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      message.error('操作失败')
    }
  }

  const handleVerify = (id: string) => {
    Modal.confirm({
      title: '验证整改',
      content: '确认整改结果是否通过验证？',
      okText: '通过',
      cancelText: '不通过',
      onOk: async () => {
        const response = await verifyRectification(id, true)
        if (response.code === 200) {
          message.success('验证通过，隐患已关闭')
          updateHazardInStore(id, response.data)
        } else {
          message.error(response.message || '验证失败')
        }
      },
      onCancel: async () => {
        const response = await verifyRectification(id, false)
        if (response.code === 200) {
          message.success('已标记为不通过')
          updateHazardInStore(id, response.data)
        } else {
          message.error(response.message || '验证失败')
        }
      },
    })
  }

  const getLevelColor = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.color || 'default'
  }

  const getLevelLabel = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.label || level
  }

  const columns: ColumnsType<HazardReport> = [
    {
      title: '隐患编号',
      dataIndex: 'hazard_no',
      key: 'hazard_no',
      width: 150,
    },
    {
      title: '隐患类型',
      dataIndex: 'hazard_type',
      key: 'hazard_type',
      width: 120,
      render: (type: HazardType) => {
        const option = HAZARD_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '等级',
      dataIndex: 'hazard_level',
      key: 'hazard_level',
      width: 80,
      render: (level: HazardLevel) => (
        <Tag color={getLevelColor(level)}>{getLevelLabel(level)}</Tag>
      ),
    },
    {
      title: '隐患描述',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      ellipsis: true,
    },
    {
      title: '发现人',
      dataIndex: 'discovered_by_name',
      key: 'discovered_by_name',
      width: 100,
    },
    {
      title: '发现时间',
      dataIndex: 'discovered_at',
      key: 'discovered_at',
      width: 120,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '责任部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
    },
    {
      title: '整改期限',
      dataIndex: 'deadline',
      key: 'deadline',
      width: 110,
      render: (date: string) => {
        if (!date) return '-'
        const isOverdue = dayjs(date).isBefore(dayjs())
        return (
          <Text type={isOverdue ? 'danger' : undefined}>
            {dayjs(date).format('YYYY-MM-DD')}
          </Text>
        )
      },
    },
    {
      title: '整改状态',
      dataIndex: 'rectification_status',
      key: 'rectification_status',
      width: 100,
      render: (status: string) => {
        const option = RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const option = HAZARD_STATUS_OPTIONS.find((o) => o.value === status)
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
          {record.rectification_status === 'pending' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStartRectification(record.id)}
            >
              开始整改
            </Button>
          )}
          {record.rectification_status === 'in_progress' && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleCompleteRectification(record.id)}
            >
              完成整改
            </Button>
          )}
          {record.rectification_status === 'completed' && (
            <Button
              type="link"
              size="small"
              icon={<VerifyOutlined />}
              onClick={() => handleVerify(record.id)}
            >
              验证
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
        title="隐患排查"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建隐患
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索隐患编号"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="隐患类型"
              allowClear
              value={typeFilter}
              onChange={(value) => {
                setTypeFilter(value)
                setHazardQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="隐患等级"
              allowClear
              value={levelFilter}
              onChange={(value) => {
                setLevelFilter(value)
                setHazardQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setHazardQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={HAZARD_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
          dataSource={hazards}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1600 }}
          pagination={{
            current: hazardQueryParams.page,
            pageSize: hazardQueryParams.page_size,
            total: hazardTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setHazardQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingRecord ? '编辑隐患' : '新建隐患'}
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
          initialValues={editingRecord || { hazard_level: 'general' }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="hazard_no"
                label="隐患编号"
                rules={[{ required: true, message: '请输入隐患编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="hazard_type"
                label="隐患类型"
                rules={[{ required: true, message: '请选择隐患类型' }]}
              >
                <Select options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="hazard_level"
                label="隐患等级"
                rules={[{ required: true, message: '请选择隐患等级' }]}
              >
                <Select options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="location" label="地点/部位">
                <Input placeholder="请输入地点" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="description"
            label="隐患描述"
            rules={[{ required: true, message: '请输入隐患描述' }]}
          >
            <Input.TextArea rows={3} placeholder="请详细描述隐患情况" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="discovered_by_name" label="发现人">
                <Input placeholder="请输入发现人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="discovered_at"
                label="发现时间"
                rules={[{ required: true, message: '请选择发现时间' }]}
              >
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="department" label="责任部门">
                <Input placeholder="请输入责任部门" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="deadline" label="整改期限">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="control_measures" label="管控措施">
            <Input.TextArea rows={3} placeholder="请描述管控措施" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
