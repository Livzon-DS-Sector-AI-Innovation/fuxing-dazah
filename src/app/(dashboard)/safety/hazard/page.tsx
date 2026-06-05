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
  Descriptions,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  UserSwitchOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
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
  assignRectification,
  extendDeadline,
} from '@/actions/safety'
import type {
  HazardReport,
  HazardReportFormData,
  HazardType,
  HazardLevel,
  HazardCategory,
  AssignRectificationRequest,
  CompleteRectificationRequest,
  ExtendDeadlineRequest,
} from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
  HAZARD_STATUS_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

export default function HazardPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [assignForm] = Form.useForm()
  const [extendForm] = Form.useForm()
  const [completeForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<HazardReport | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [levelFilter, setLevelFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()

  // Workflow modal states
  const [assignModalVisible, setAssignModalVisible] = useState(false)
  const [extendModalVisible, setExtendModalVisible] = useState(false)
  const [completeModalVisible, setCompleteModalVisible] = useState(false)
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<HazardReport | null>(null)

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
        hazard_category: categoryFilter,
        keyword: searchText || undefined,
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
  }, [hazardQueryParams.page, hazardQueryParams.page_size, statusFilter, typeFilter, levelFilter, categoryFilter])

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
      actual_completion_date: record.actual_completion_date ? dayjs(record.actual_completion_date) : undefined,
      extended_deadline: record.extended_deadline ? dayjs(record.extended_deadline) : undefined,
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
        actual_completion_date: values.actual_completion_date ? values.actual_completion_date.toISOString() : undefined,
        extended_deadline: values.extended_deadline ? values.extended_deadline.toISOString() : undefined,
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

  // Open assign rectification modal
  const handleOpenAssign = (record: HazardReport) => {
    setSelectedRecord(record)
    assignForm.resetFields()
    assignForm.setFieldsValue({
      responsible_person_name: record.rectification_responsible_person_name || '',
      responsible_department: record.rectification_responsible_department || '',
      deadline: record.deadline ? dayjs(record.deadline) : undefined,
      corrective_preventive_measures: record.corrective_preventive_measures || '',
    })
    setAssignModalVisible(true)
  }

  const handleAssign = async () => {
    if (!selectedRecord) return
    try {
      const values = await assignForm.validateFields()
      const data: AssignRectificationRequest = {
        responsible_person_name: values.responsible_person_name,
        responsible_department: values.responsible_department,
        planned_completion_date: values.deadline ? values.deadline.toISOString() : '',
        corrective_preventive_measures: values.corrective_preventive_measures,
      }
      const response = await assignRectification(selectedRecord.id, data)
      if (response.code === 200) {
        message.success('整改任务已指派')
        updateHazardInStore(selectedRecord.id, response.data)
        setAssignModalVisible(false)
        setSelectedRecord(null)
      } else {
        message.error(response.message || '指派失败')
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  // Open extend deadline modal
  const handleOpenExtend = (record: HazardReport) => {
    setSelectedRecord(record)
    extendForm.resetFields()
    extendForm.setFieldsValue({
      extended_deadline: record.extended_deadline ? dayjs(record.extended_deadline) : undefined,
    })
    setExtendModalVisible(true)
  }

  const handleExtend = async () => {
    if (!selectedRecord) return
    try {
      const values = await extendForm.validateFields()
      const data: ExtendDeadlineRequest = {
        extended_deadline: values.extended_deadline ? values.extended_deadline.toISOString() : '',
      }
      const response = await extendDeadline(selectedRecord.id, data)
      if (response.code === 200) {
        message.success('延期申请已提交')
        updateHazardInStore(selectedRecord.id, response.data)
        setExtendModalVisible(false)
        setSelectedRecord(null)
      } else {
        message.error(response.message || '延期失败')
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  // Open complete rectification modal (enhanced)
  const handleOpenComplete = (record: HazardReport) => {
    setSelectedRecord(record)
    completeForm.resetFields()
    completeForm.setFieldsValue({
      actual_completion_date: record.actual_completion_date ? dayjs(record.actual_completion_date) : undefined,
      corrective_preventive_measures: record.corrective_preventive_measures || '',
      rectification_photos: record.rectification_photos || '',
    })
    setCompleteModalVisible(true)
  }

  const handleComplete = async () => {
    if (!selectedRecord) return
    try {
      const values = await completeForm.validateFields()
      const data: CompleteRectificationRequest = {
        actual_completion_date: values.actual_completion_date ? values.actual_completion_date.toISOString() : undefined,
        rectification_photos: values.rectification_photos || undefined,
        corrective_preventive_measures: values.corrective_preventive_measures || undefined,
      }
      const response = await completeRectification(selectedRecord.id, data)
      if (response.code === 200) {
        message.success('整改完成，等待验证')
        updateHazardInStore(selectedRecord.id, response.data)
        setCompleteModalVisible(false)
        setSelectedRecord(null)
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      console.error('表单验证失败')
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

  const handleViewDetail = (record: HazardReport) => {
    setSelectedRecord(record)
    setDetailModalVisible(true)
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
      width: 140,
    },
    {
      title: '隐患类别',
      dataIndex: 'hazard_category',
      key: 'hazard_category',
      width: 110,
      render: (category: HazardCategory) => {
        const option = HAZARD_CATEGORY_OPTIONS.find((o) => o.value === category)
        return option ? <Tag>{option.label}</Tag> : '-'
      },
    },
    {
      title: '隐患分类',
      dataIndex: 'hazard_type',
      key: 'hazard_type',
      width: 110,
      render: (type: HazardType) => {
        const option = HAZARD_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '等级',
      dataIndex: 'hazard_level',
      key: 'hazard_level',
      width: 90,
      render: (level: HazardLevel) => (
        <Tag color={getLevelColor(level)}>{getLevelLabel(level)}</Tag>
      ),
    },
    {
      title: '隐患描述',
      dataIndex: 'description',
      key: 'description',
      width: 180,
      ellipsis: true,
    },
    {
      title: '重点缺陷',
      dataIndex: 'key_defect',
      key: 'key_defect',
      width: 100,
      ellipsis: true,
      render: (text: string) => text || '-',
    },
    {
      title: '发现人',
      dataIndex: 'discovered_by_name',
      key: 'discovered_by_name',
      width: 90,
    },
    {
      title: '发现时间',
      dataIndex: 'discovered_at',
      key: 'discovered_at',
      width: 110,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '整改责任人',
      dataIndex: 'rectification_responsible_person_name',
      key: 'rectification_responsible_person_name',
      width: 110,
      render: (text: string) => text || '-',
    },
    {
      title: '计划完成',
      dataIndex: 'deadline',
      key: 'deadline',
      width: 110,
      render: (date: string, record: HazardReport) => {
        if (!date) return '-'
        const isOverdue = dayjs(date).isBefore(dayjs()) && record.rectification_status !== 'verified'
        return (
          <Text type={isOverdue ? 'danger' : undefined}>
            {dayjs(date).format('YYYY-MM-DD')}
          </Text>
        )
      },
    },
    {
      title: '延期至',
      dataIndex: 'extended_deadline',
      key: 'extended_deadline',
      width: 110,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
    },
    {
      title: '实际完成',
      dataIndex: 'actual_completion_date',
      key: 'actual_completion_date',
      width: 110,
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : '-',
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
      width: 80,
      render: (status: string) => {
        const option = HAZARD_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 360,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {record.rectification_status === 'pending' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => handleStartRectification(record.id)}
              >
                开始整改
              </Button>
              <Button
                type="link"
                size="small"
                icon={<UserSwitchOutlined />}
                onClick={() => handleOpenAssign(record)}
              >
                指派
              </Button>
            </>
          )}
          {record.rectification_status === 'in_progress' && (
            <>
              <Button
                type="link"
                size="small"
                icon={<CheckCircleOutlined />}
                onClick={() => handleOpenComplete(record)}
              >
                完成整改
              </Button>
              <Button
                type="link"
                size="small"
                icon={<ClockCircleOutlined />}
                onClick={() => handleOpenExtend(record)}
              >
                延期
              </Button>
            </>
          )}
          {record.rectification_status === 'completed' && (
            <Button
              type="link"
              size="small"
              icon={<SafetyCertificateOutlined />}
              onClick={() => handleVerify(record.id)}
            >
              验证
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
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

  const hazardFormContent = (formInstance: ReturnType<typeof Form.useForm>[0]) => (
    <>
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
            name="hazard_category"
            label="隐患类别"
          >
            <Select
              allowClear
              placeholder="请选择隐患类别"
              options={HAZARD_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item
            name="hazard_type"
            label="隐患分类"
            rules={[{ required: true, message: '请选择隐患分类' }]}
          >
            <Select options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="hazard_level"
            label="隐患等级"
            rules={[{ required: true, message: '请选择隐患等级' }]}
          >
            <Select options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
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
          <Form.Item name="key_defect" label="重点缺陷">
            <Input placeholder="请输入重点缺陷" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="location" label="地点/部位">
            <Input placeholder="请输入地点" />
          </Form.Item>
        </Col>
      </Row>
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
          <Form.Item name="deadline" label="计划完成时间">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="rectification_responsible_person_name" label="整改责任人">
            <Input placeholder="请输入整改责任人姓名" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="rectification_responsible_department" label="整改责任部门">
            <Input placeholder="请输入整改责任部门" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="major_hazard_basis" label="重大隐患判定依据">
        <Input.TextArea rows={2} placeholder="如是重大隐患，请填写判定依据" />
      </Form.Item>
      <Form.Item name="control_measures" label="管控措施">
        <Input.TextArea rows={2} placeholder="请描述管控措施" />
      </Form.Item>
      <Form.Item name="corrective_preventive_measures" label="纠正预防措施">
        <Input.TextArea rows={2} placeholder="请描述纠正预防措施" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="defect_photos" label="缺陷图片(URL)">
            <Input placeholder="请输入图片URL，多个以逗号分隔" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="rectification_photos" label="整改后图片(URL)">
            <Input placeholder="请输入图片URL，多个以逗号分隔" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="notes" label="备注">
        <Input.TextArea rows={2} placeholder="请输入备注" />
      </Form.Item>
    </>
  )

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
          <Col span={4}>
            <Input
              placeholder="搜索编号/描述"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="隐患类别"
              allowClear
              value={categoryFilter}
              onChange={(value) => {
                setCategoryFilter(value)
                setHazardQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={HAZARD_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="隐患分类"
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
          <Col span={3}>
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
          <Col span={3}>
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
          <Col span={2}>
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
          scroll={{ x: 2000 }}
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

      {/* Create/Edit Modal */}
      <Modal
        title={editingRecord ? '编辑隐患' : '新建隐患'}
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
          initialValues={editingRecord || { hazard_level: 'general' }}
        >
          {hazardFormContent(editingRecord ? editForm : form)}
        </Form>
      </Modal>

      {/* Assign Rectification Modal */}
      <Modal
        title="指派整改任务"
        open={assignModalVisible}
        onOk={handleAssign}
        onCancel={() => {
          setAssignModalVisible(false)
          setSelectedRecord(null)
        }}
        width={600}
        okText="确认指派"
        cancelText="取消"
      >
        <Form form={assignForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="responsible_person_name"
                label="整改责任人"
                rules={[{ required: true, message: '请输入整改责任人' }]}
              >
                <Input placeholder="请输入责任人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="responsible_department"
                label="整改责任部门"
                rules={[{ required: true, message: '请输入责任部门' }]}
              >
                <Input placeholder="请输入责任部门" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="deadline"
            label="计划完成时间"
            rules={[{ required: true, message: '请选择计划完成时间' }]}
          >
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="corrective_preventive_measures" label="纠正预防措施">
            <Input.TextArea rows={3} placeholder="请描述纠正预防措施" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Extend Deadline Modal */}
      <Modal
        title="延期申请"
        open={extendModalVisible}
        onOk={handleExtend}
        onCancel={() => {
          setExtendModalVisible(false)
          setSelectedRecord(null)
        }}
        width={400}
        okText="确认延期"
        cancelText="取消"
      >
        <Form form={extendForm} layout="vertical">
          <Form.Item
            name="extended_deadline"
            label="延期至"
            rules={[{ required: true, message: '请选择延期日期' }]}
          >
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Complete Rectification Modal */}
      <Modal
        title="完成整改"
        open={completeModalVisible}
        onOk={handleComplete}
        onCancel={() => {
          setCompleteModalVisible(false)
          setSelectedRecord(null)
        }}
        width={600}
        okText="确认完成"
        cancelText="取消"
      >
        <Form form={completeForm} layout="vertical">
          <Form.Item
            name="actual_completion_date"
            label="实际完成时间"
            rules={[{ required: true, message: '请选择实际完成时间' }]}
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="corrective_preventive_measures" label="纠正预防措施">
            <Input.TextArea rows={3} placeholder="请描述采取的纠正预防措施" />
          </Form.Item>
          <Form.Item name="rectification_photos" label="整改后图片(URL)">
            <Input placeholder="请输入图片URL，多个以逗号分隔" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="隐患详情"
        open={detailModalVisible}
        onCancel={() => {
          setDetailModalVisible(false)
          setSelectedRecord(null)
        }}
        footer={<Button onClick={() => { setDetailModalVisible(false); setSelectedRecord(null) }}>关闭</Button>}
        width={800}
      >
        {selectedRecord && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="隐患编号">{selectedRecord.hazard_no}</Descriptions.Item>
            <Descriptions.Item label="隐患类别">
              {selectedRecord.hazard_category
                ? HAZARD_CATEGORY_OPTIONS.find((o) => o.value === selectedRecord.hazard_category)?.label
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="隐患分类">
              {HAZARD_TYPE_OPTIONS.find((o) => o.value === selectedRecord.hazard_type)?.label}
            </Descriptions.Item>
            <Descriptions.Item label="隐患等级">
              <Tag color={getLevelColor(selectedRecord.hazard_level)}>
                {getLevelLabel(selectedRecord.hazard_level)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="重点缺陷" span={2}>
              {selectedRecord.key_defect || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="隐患描述" span={2}>
              {selectedRecord.description}
            </Descriptions.Item>
            <Descriptions.Item label="重大隐患判定依据" span={2}>
              {selectedRecord.major_hazard_basis || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="发现人">{selectedRecord.discovered_by_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="发现时间">
              {selectedRecord.discovered_at ? dayjs(selectedRecord.discovered_at).format('YYYY-MM-DD HH:mm') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="责任部门">{selectedRecord.department || '-'}</Descriptions.Item>
            <Descriptions.Item label="地点">{selectedRecord.location || '-'}</Descriptions.Item>
            <Descriptions.Item label="整改责任人">
              {selectedRecord.rectification_responsible_person_name || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="整改责任部门">
              {selectedRecord.rectification_responsible_department || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="计划完成时间">
              {selectedRecord.deadline
                ? dayjs(selectedRecord.deadline).format('YYYY-MM-DD')
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="延期至">
              {selectedRecord.extended_deadline
                ? dayjs(selectedRecord.extended_deadline).format('YYYY-MM-DD')
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="实际完成时间">
              {selectedRecord.actual_completion_date
                ? dayjs(selectedRecord.actual_completion_date).format('YYYY-MM-DD HH:mm')
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="管控措施" span={2}>
              {selectedRecord.control_measures || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="纠正预防措施" span={2}>
              {selectedRecord.corrective_preventive_measures || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="缺陷图片" span={2}>
              {selectedRecord.defect_photos || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="整改后图片" span={2}>
              {selectedRecord.rectification_photos || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="整改状态">
              <Tag color={RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === selectedRecord.rectification_status)?.color}>
                {RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === selectedRecord.rectification_status)?.label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={HAZARD_STATUS_OPTIONS.find((o) => o.value === selectedRecord.status)?.color}>
                {HAZARD_STATUS_OPTIONS.find((o) => o.value === selectedRecord.status)?.label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="备注" span={2}>
              {selectedRecord.notes || '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
