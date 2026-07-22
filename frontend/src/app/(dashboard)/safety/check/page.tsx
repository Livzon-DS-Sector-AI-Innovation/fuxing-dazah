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
  CheckCircleOutlined,
  SendOutlined,
  SafetyCertificateOutlined,
  AuditOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getChecks,
  createCheck,
  updateCheck,
  submitCheck,
  reviewCheck,
  deleteCheck,
  confirmCheck,
} from '@/actions/safety'
import type {
  SafetyCheck,
  SafetyCheckFormData,
  CheckType,
  ConfirmCheckRequest,
} from '@/types/safety'
import {
  CheckType as CheckTypeEnum,
  CHECK_TYPE_OPTIONS,
  CHECK_STATUS_OPTIONS,
  CHECK_RESULT_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

const getStatusColor = (status: string) => {
  const option = CHECK_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

const getStatusLabel = (status: string) => {
  const option = CHECK_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

export default function SafetyCheckPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyCheck | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  const {
    checks,
    checkTotal,
    checkQueryParams,
    setChecks,
    setCheckTotal,
    setCheckQueryParams,
    addCheck,
    updateCheck: updateCheckInStore,
    removeCheck,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getChecks({
        ...checkQueryParams,
        status: statusFilter,
        check_type: typeFilter,
      })
      if (response.code === 200) {
        setChecks(response.data)
        setCheckTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载安全检查列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [checkQueryParams.page, checkQueryParams.page_size, statusFilter, typeFilter])

  const handleSearch = () => {
    setCheckQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: SafetyCheck) => {
    setEditingRecord(record)
    editForm.setFieldsValue({
      ...record,
      check_date: record.check_date ? dayjs(record.check_date) : undefined,
      rectification_deadline: record.rectification_deadline ? dayjs(record.rectification_deadline) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个检查记录吗？',
      onOk: async () => {
        try {
          const response = await deleteCheck(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeCheck(id)
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
        check_date: values.check_date ? values.check_date.toISOString() : undefined,
        rectification_deadline: values.rectification_deadline ? values.rectification_deadline.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updateCheck(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updateCheckInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createCheck(formattedValues as SafetyCheckFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addCheck(response.data)
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

  const handleSubmitCheck = async (id: string) => {
    try {
      const response = await submitCheck(id)
      if (response.code === 200) {
        message.success('提交成功')
        updateCheckInStore(id, response.data)
      } else {
        message.error(response.message || '提交失败')
      }
    } catch {
      message.error('提交失败')
    }
  }

  const handleReview = (id: string) => {
    Modal.confirm({
      title: '审核安全检查',
      content: (
        <div className="mt-4">
          <Text>请选择审核结果：</Text>
        </div>
      ),
      okText: '合格',
      cancelText: '不合格',
      onOk: async () => {
        const response = await reviewCheck(id, 'qualified')
        if (response.code === 200) {
          message.success('审核通过')
          updateCheckInStore(id, response.data)
        } else {
          message.error(response.message || '审核失败')
        }
      },
      onCancel: async () => {
        const response = await reviewCheck(id, 'unqualified')
        if (response.code === 200) {
          message.success('已标记为不合格')
          updateCheckInStore(id, response.data)
        } else {
          message.error(response.message || '审核失败')
        }
      },
    })
  }

  const handleConfirm = async (id: string, role: ConfirmCheckRequest['role']) => {
    try {
      const response = await confirmCheck(id, { role })
      if (response.code === 200) {
        const roleLabel = role === 'inspector' ? '检查人员' : '安全办'
        message.success(`${roleLabel}确认成功`)
        updateCheckInStore(id, response.data)
      } else {
        message.error(response.message || '确认失败')
      }
    } catch {
      message.error('确认失败')
    }
  }

  const columns: ColumnsType<SafetyCheck> = [
    {
      title: '检查编号',
      dataIndex: 'check_no',
      key: 'check_no',
      width: 150,
    },
    {
      title: '检查类型',
      dataIndex: 'check_type',
      key: 'check_type',
      width: 110,
      render: (type: CheckType) => {
        const option = CHECK_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '检查日期',
      dataIndex: 'check_date',
      key: 'check_date',
      width: 120,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '检查部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
    },
    {
      title: '检查人',
      dataIndex: 'inspector_name',
      key: 'inspector_name',
      width: 100,
    },
    {
      title: '检查地点',
      dataIndex: 'location',
      key: 'location',
      width: 150,
      ellipsis: true,
    },
    {
      title: '结果',
      dataIndex: 'result',
      key: 'result',
      width: 100,
      render: (result: string) => {
        const option = CHECK_RESULT_OPTIONS.find((o) => o.value === result)
        return result ? <Tag color={option?.color}>{option?.label || result}</Tag> : '-'
      },
    },
    {
      title: '整改',
      dataIndex: 'rectification_status',
      key: 'rectification_status',
      width: 100,
      render: (status: string) => {
        const option = RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status || '-'}</Tag>
      },
    },
    {
      title: '检查人确认',
      dataIndex: 'inspector_confirmed',
      key: 'inspector_confirmed',
      width: 110,
      render: (confirmed: boolean) => (
        <Tag color={confirmed ? 'success' : 'default'}>
          {confirmed ? '已确认' : '未确认'}
        </Tag>
      ),
    },
    {
      title: '安全办确认',
      dataIndex: 'safety_officer_confirmed',
      key: 'safety_officer_confirmed',
      width: 110,
      render: (confirmed: boolean) => (
        <Tag color={confirmed ? 'success' : 'default'}>
          {confirmed ? '已确认' : '未确认'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 320,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {record.status === 'draft' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<SendOutlined />}
                onClick={() => handleSubmitCheck(record.id)}
              >
                提交
              </Button>
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => handleEdit(record)}
              >
                编辑
              </Button>
            </>
          )}
          {record.status === 'submitted' && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleReview(record.id)}
            >
              审核
            </Button>
          )}
          {record.status === 'reviewed' && !record.inspector_confirmed && (
            <Button
              type="link"
              size="small"
              icon={<SafetyCertificateOutlined />}
              onClick={() => handleConfirm(record.id, 'inspector')}
            >
              检查人确认
            </Button>
          )}
          {record.status === 'reviewed' && record.inspector_confirmed && !record.safety_officer_confirmed && (
            <Button
              type="link"
              size="small"
              icon={<AuditOutlined />}
              onClick={() => handleConfirm(record.id, 'safety_officer')}
            >
              安全办确认
            </Button>
          )}
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
        title="安全检查"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建检查
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索检查编号"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="检查类型"
              allowClear
              value={typeFilter}
              onChange={(value) => {
                setTypeFilter(value)
                setCheckQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={CHECK_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setCheckQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={CHECK_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
          dataSource={checks}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: checkQueryParams.page,
            pageSize: checkQueryParams.page_size,
            total: checkTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setCheckQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingRecord ? '编辑检查' : '新建检查'}
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
          initialValues={editingRecord || undefined}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="check_no"
                label="检查编号"
                rules={[{ required: true, message: '请输入检查编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="check_type"
                label="检查类型"
                rules={[{ required: true, message: '请选择检查类型' }]}
              >
                <Select options={CHECK_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="check_date"
                label="检查日期"
                rules={[{ required: true, message: '请选择检查日期' }]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="department" label="检查部门">
                <Input placeholder="请输入检查部门" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="inspector_name" label="检查人">
                <Input placeholder="请输入检查人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="location" label="检查地点">
                <Input placeholder="请输入检查地点" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="findings" label="检查发现">
            <Input.TextArea rows={3} placeholder="请描述检查发现" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="rectification_required" label="需要整改">
                <Select
                  options={[
                    { value: true, label: '是' },
                    { value: false, label: '否' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="rectification_deadline" label="整改期限">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
