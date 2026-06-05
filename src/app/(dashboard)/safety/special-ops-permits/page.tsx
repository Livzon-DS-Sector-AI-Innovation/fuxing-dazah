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
  SendOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlayCircleOutlined,
  FlagOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
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
  SpecialOperationPermit,
  SpecialOperationPermitFormData,
} from '@/types/safety'
import {
  OPERATION_TYPE_OPTIONS,
  OPERATION_LEVEL_OPTIONS,
  PERMIT_STATUS_OPTIONS,
  COMPLETION_METHOD_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

const getStatusColor = (status: string) => {
  const option = PERMIT_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

const getStatusLabel = (status: string) => {
  const option = PERMIT_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

const getLevelColor = (level: string) => {
  const option = OPERATION_LEVEL_OPTIONS.find((o) => o.value === level)
  return option?.color || 'default'
}

const getLevelLabel = (level: string) => {
  const option = OPERATION_LEVEL_OPTIONS.find((o) => o.value === level)
  return option?.label || level
}

export default function SpecialOpsPermitsPage() {
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
    permits,
    permitTotal,
    permitQueryParams,
    setPermits,
    setPermitTotal,
    setPermitQueryParams,
    addPermit,
    updatePermit: updatePermitInStore,
    removePermit,
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
      message.error('加载特殊作业票列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [permitQueryParams.page, permitQueryParams.page_size, statusFilter, operationTypeFilter])

  const handleSearch = () => {
    setPermitQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    form.resetFields()
    setModalVisible(true)
  }

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
      title: '确认删除',
      content: '确定要删除该作业票吗？',
      onOk: async () => {
        try {
          const response = await deletePermit(id)
          if (response.code === 200) {
            message.success('删除成功')
            removePermit(id)
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
        planned_start_time: values.planned_start_time ? values.planned_start_time.toISOString() : undefined,
        planned_end_time: values.planned_end_time ? values.planned_end_time.toISOString() : undefined,
      }

      if (editingRecord) {
        const response = await updatePermit(editingRecord.id, formattedValues)
        if (response.code === 200) {
          message.success('更新成功')
          updatePermitInStore(editingRecord.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createPermit(formattedValues as SpecialOperationPermitFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addPermit(response.data)
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

  const handleSubmitPermit = async (id: string) => {
    try {
      const response = await submitPermit(id)
      if (response.code === 200) {
        message.success('提交成功')
        updatePermitInStore(id, response.data)
      } else {
        message.error(response.message || '提交失败')
      }
    } catch {
      message.error('提交失败')
    }
  }

  const handleApprovePermit = async (id: string) => {
    try {
      const response = await approvePermit(id)
      if (response.code === 200) {
        message.success('审批通过')
        updatePermitInStore(id, response.data)
      } else {
        message.error(response.message || '审批失败')
      }
    } catch {
      message.error('审批失败')
    }
  }

  const handleRejectClick = (id: string) => {
    setRejectRecordId(id)
    setRejectReason('')
    setRejectModalVisible(true)
  }

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) {
      message.warning('请输入驳回原因')
      return
    }
    try {
      const response = await rejectPermit(rejectRecordId, rejectReason)
      if (response.code === 200) {
        message.success('已驳回')
        updatePermitInStore(rejectRecordId, response.data)
        setRejectModalVisible(false)
      } else {
        message.error(response.message || '驳回失败')
      }
    } catch {
      message.error('驳回失败')
    }
  }

  const handleStartPermit = async (id: string) => {
    try {
      const response = await startPermit(id)
      if (response.code === 200) {
        message.success('作业已开始')
        updatePermitInStore(id, response.data)
      } else {
        message.error(response.message || '开始作业失败')
      }
    } catch {
      message.error('开始作业失败')
    }
  }

  const handleCompletePermit = (id: string) => {
    Modal.confirm({
      title: '完工确认',
      content: (
        <div className="mt-4">
          <Text>请选择完工方式：</Text>
        </div>
      ),
      okText: COMPLETION_METHOD_OPTIONS.find((o) => o.value === 'normal')?.label || '正常完工',
      cancelText: COMPLETION_METHOD_OPTIONS.find((o) => o.value === 'early_termination')?.label || '提前终止',
      onOk: async () => {
        const response = await completePermit(id, 'normal')
        if (response.code === 200) {
          message.success('正常完工')
          updatePermitInStore(id, response.data)
        } else {
          message.error(response.message || '完工确认失败')
        }
      },
      onCancel: async () => {
        const response = await completePermit(id, 'early_termination')
        if (response.code === 200) {
          message.success('提前终止')
          updatePermitInStore(id, response.data)
        } else {
          message.error(response.message || '提前终止失败')
        }
      },
    })
  }

  const handleArchivePermit = async (id: string) => {
    try {
      const response = await archivePermit(id)
      if (response.code === 200) {
        message.success('归档成功')
        updatePermitInStore(id, response.data)
      } else {
        message.error(response.message || '归档失败')
      }
    } catch {
      message.error('归档失败')
    }
  }

  const columns: ColumnsType<SpecialOperationPermit> = [
    {
      title: '作业票编号',
      dataIndex: 'permit_no',
      key: 'permit_no',
      width: 150,
    },
    {
      title: '作业类型',
      dataIndex: 'operation_type',
      key: 'operation_type',
      width: 130,
      render: (type: string) => {
        const option = OPERATION_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '作业级别',
      dataIndex: 'operation_level',
      key: 'operation_level',
      width: 100,
      render: (level: string) => {
        if (!level) return '-'
        return <Tag color={getLevelColor(level)}>{getLevelLabel(level)}</Tag>
      },
    },
    {
      title: '作业地点',
      dataIndex: 'location',
      key: 'location',
      width: 150,
      ellipsis: true,
      render: (text: string) => text || '-',
    },
    {
      title: '设备位号',
      dataIndex: 'equipment_tag',
      key: 'equipment_tag',
      width: 120,
      render: (text: string) => text || '-',
    },
    {
      title: '计划开始',
      dataIndex: 'planned_start_time',
      key: 'planned_start_time',
      width: 160,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '计划结束',
      dataIndex: 'planned_end_time',
      key: 'planned_end_time',
      width: 160,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '申请人',
      dataIndex: 'applicant_name',
      key: 'applicant_name',
      width: 100,
      render: (text: string) => text || '-',
    },
    {
      title: '作业负责人',
      dataIndex: 'work_leader_name',
      key: 'work_leader_name',
      width: 110,
      render: (text: string) => text || '-',
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
            <Button
              type="link"
              size="small"
              icon={<SendOutlined />}
              onClick={() => handleSubmitPermit(record.id)}
            >
              提交
            </Button>
          )}
          {record.status === 'submitted' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<CheckCircleOutlined />}
                onClick={() => handleApprovePermit(record.id)}
              >
                审批
              </Button>
              <Button
                type="link"
                size="small"
                icon={<CloseCircleOutlined />}
                danger
                onClick={() => handleRejectClick(record.id)}
              >
                驳回
              </Button>
            </>
          )}
          {record.status === 'approved' && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStartPermit(record.id)}
            >
              开始作业
            </Button>
          )}
          {record.status === 'in_progress' && (
            <Button
              type="link"
              size="small"
              icon={<FlagOutlined />}
              onClick={() => handleCompletePermit(record.id)}
            >
              完工
            </Button>
          )}
          {record.status === 'completed' && (
            <Button
              type="link"
              size="small"
              icon={<InboxOutlined />}
              onClick={() => handleArchivePermit(record.id)}
            >
              归档
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
        title="特殊作业票管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建作业票
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索作业票编号/申请人"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="作业类型"
              allowClear
              value={operationTypeFilter}
              onChange={(value) => {
                setOperationTypeFilter(value)
                setPermitQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={OPERATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setPermitQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={PERMIT_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
          dataSource={permits}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: permitQueryParams.page,
            pageSize: permitQueryParams.page_size,
            total: permitTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPermitQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingRecord ? '编辑作业票' : '新建作业票'}
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
          initialValues={editingRecord || undefined}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="permit_no"
                label="作业票编号"
                rules={[{ required: true, message: '请输入作业票编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="operation_type"
                label="作业类型"
                rules={[{ required: true, message: '请选择作业类型' }]}
              >
                <Select
                  placeholder="请选择作业类型"
                  options={OPERATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="operation_level" label="作业级别">
                <Select
                  placeholder="请选择作业级别"
                  allowClear
                  options={OPERATION_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
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
          <Form.Item name="work_description" label="作业描述">
            <Input.TextArea rows={2} placeholder="请描述作业内容" />
          </Form.Item>
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
              <Form.Item name="applicant_name" label="申请人">
                <Input placeholder="请输入申请人姓名" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="work_leader_name" label="作业负责人">
                <Input placeholder="请输入作业负责人" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="operator_names" label="作业人员">
                <Input placeholder="多人用逗号分隔" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="guardian_name" label="监护人">
                <Input placeholder="请输入监护人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="approver_name" label="审批人">
                <Input placeholder="请输入审批人姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="safety_measures" label="安全措施">
            <Input.TextArea rows={2} placeholder="请输入安全措施" />
          </Form.Item>
          <Form.Item name="emergency_equipment" label="应急设备">
            <Input.TextArea rows={2} placeholder="请输入应急设备" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="gas_analysis" label="气体分析">
                <Input.TextArea rows={2} placeholder="请输入气体分析结果" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="risk_assessment" label="风险评估">
                <Input.TextArea rows={2} placeholder="请输入风险评估" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="驳回作业票"
        open={rejectModalVisible}
        onOk={handleRejectConfirm}
        onCancel={() => setRejectModalVisible(false)}
        okText="确认驳回"
        cancelText="取消"
      >
        <Input.TextArea
          rows={3}
          placeholder="请输入驳回原因"
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
        />
      </Modal>
    </div>
  )
}
