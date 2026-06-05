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
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getPersonnelList,
  createPersonnel,
  updatePersonnel,
  deletePersonnel,
} from '@/actions/safety'
import type {
  SpecialOperationPersonnel,
  SpecialOperationPersonnelFormData,
} from '@/types/safety'
import {
  OPERATION_TYPE_OPTIONS,
  PERSONNEL_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const getStatusColor = (status: string) => {
  const option = PERSONNEL_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

const getStatusLabel = (status: string) => {
  const option = PERSONNEL_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

export default function SpecialOpsPersonnelPage() {
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
      message.error('加载特殊作业人员列表失败')
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
      content: '确定要删除该人员记录吗？',
      onOk: async () => {
        try {
          const response = await deletePersonnel(id)
          if (response.code === 200) {
            message.success('删除成功')
            removePersonnel(id)
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
    {
      title: '人员编号',
      dataIndex: 'personnel_no',
      key: 'personnel_no',
      width: 120,
    },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100,
    },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
      render: (text: string) => text || '-',
    },
    {
      title: '证书类型',
      dataIndex: 'certificate_type',
      key: 'certificate_type',
      width: 130,
      render: (type: string) => {
        const option = OPERATION_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '证书编号',
      dataIndex: 'certificate_number',
      key: 'certificate_number',
      width: 150,
      render: (text: string) => text || '-',
    },
    {
      title: '到期日期',
      dataIndex: 'expiry_date',
      key: 'expiry_date',
      width: 120,
      render: (date: string) => {
        if (!date) return '-'
        const isExpired = dayjs(date).isBefore(dayjs(), 'day')
        return (
          <span style={{ color: isExpired ? 'red' : undefined, fontWeight: isExpired ? 'bold' : undefined }}>
            {dayjs(date).format('YYYY-MM-DD')}
          </span>
        )
      },
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
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
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
        title="特殊作业人员管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新增人员
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索人员编号/姓名"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="证书类型"
              allowClear
              value={certTypeFilter}
              onChange={(value) => {
                setCertTypeFilter(value)
                setPersonnelQueryParams({ page: 1 })
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
                setPersonnelQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={PERSONNEL_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
          dataSource={personnel}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1100 }}
          pagination={{
            current: personnelQueryParams.page,
            pageSize: personnelQueryParams.page_size,
            total: personnelTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPersonnelQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingRecord ? '编辑人员' : '新增人员'}
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
                name="personnel_no"
                label="人员编号"
                rules={[{ required: true, message: '请输入人员编号' }]}
              >
                <Input placeholder="请输入人员编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="name"
                label="姓名"
                rules={[{ required: true, message: '请输入姓名' }]}
              >
                <Input placeholder="请输入姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="department" label="部门">
                <Input placeholder="请输入部门" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="certificate_type"
                label="证书类型"
                rules={[{ required: true, message: '请选择证书类型' }]}
              >
                <Select
                  placeholder="请选择证书类型"
                  options={OPERATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
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
              <Form.Item name="expiry_date" label="到期日期">
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
        </Form>
      </Modal>
    </div>
  )
}
