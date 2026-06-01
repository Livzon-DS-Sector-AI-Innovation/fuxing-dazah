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
  EyeOutlined,
} from '@ant-design/icons'
import { useProductionStore } from '@/stores/production'
import { getProcessSpecs, createProcessSpec, updateProcessSpec, deleteProcessSpec } from '@/actions/production'
import type { ProcessSpec, ProcessSpecFormData, ProcessSpecStatus } from '@/types/production'
import { PROCESS_SPEC_STATUS_OPTIONS } from '@/types/production'

const getStatusColor = (status: ProcessSpecStatus) => {
  const option = PROCESS_SPEC_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

const getStatusLabel = (status: ProcessSpecStatus) => {
  const option = PROCESS_SPEC_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

export default function ProcessPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSpec, setEditingSpec] = useState<ProcessSpec | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<ProcessSpecStatus | undefined>()

  const {
    processSpecs,
    processSpecTotal,
    processSpecQueryParams,
    setProcessSpecs,
    setProcessSpecTotal,
    setProcessSpecQueryParams,
    addProcessSpec,
    updateProcessSpec: updateSpecInStore,
    removeProcessSpec,
  } = useProductionStore()

  const loadProcessSpecs = async () => {
    setLoading(true)
    try {
      const response = await getProcessSpecs({
        ...processSpecQueryParams,
        status: statusFilter,
        product_code: searchText || undefined,
      })
      if (response.code === 200) {
        setProcessSpecs(response.data)
        setProcessSpecTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载工艺规程列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProcessSpecs()
  }, [processSpecQueryParams.page, processSpecQueryParams.page_size, statusFilter])

  const handleSearch = () => {
    setProcessSpecQueryParams({ page: 1 })
    loadProcessSpecs()
  }

  const handleAdd = () => {
    setEditingSpec(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: ProcessSpec) => {
    setEditingSpec(record)
    editForm.setFieldsValue(record)
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个工艺规程吗？',
      onOk: async () => {
        try {
          const response = await deleteProcessSpec(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeProcessSpec(id)
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
      const values = editingSpec ? await editForm.validateFields() : await form.validateFields()

      if (editingSpec) {
        const response = await updateProcessSpec(editingSpec.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateSpecInStore(editingSpec.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createProcessSpec(values as ProcessSpecFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addProcessSpec(response.data)
          setModalVisible(false)
          form.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch (error) {
      console.error('表单验证失败:', error)
    }
  }

  const columns: ColumnsType<ProcessSpec> = [
    {
      title: '规程编号',
      dataIndex: 'spec_code',
      key: 'spec_code',
      width: 150,
    },
    {
      title: '规程名称',
      dataIndex: 'spec_name',
      key: 'spec_name',
      width: 200,
    },
    {
      title: '产品编码',
      dataIndex: 'product_code',
      key: 'product_code',
      width: 120,
    },
    {
      title: '产品名称',
      dataIndex: 'product_name',
      key: 'product_name',
      width: 150,
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: ProcessSpecStatus) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '批准人',
      dataIndex: 'approved_by_name',
      key: 'approved_by_name',
      width: 100,
    },
    {
      title: '生效日期',
      dataIndex: 'effective_date',
      key: 'effective_date',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString('zh-CN') : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />}>
            查看
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="p-6">
      <Card
        title="工艺规程"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建规程
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={6}>
            <Input
              placeholder="搜索产品编码"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="选择状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setProcessSpecQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'approved', label: '已批准' },
                { value: 'effective', label: '已生效' },
                { value: 'archived', label: '已归档' },
              ]}
            />
          </Col>
          <Col span={4}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
              查询
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={processSpecs}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: processSpecQueryParams.page,
            pageSize: processSpecQueryParams.page_size,
            total: processSpecTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setProcessSpecQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingSpec ? '编辑工艺规程' : '新建工艺规程'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form form={editingSpec ? editForm : form} layout="vertical" initialValues={editingSpec || undefined}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="spec_code"
                label="规程编号"
                rules={[{ required: true, message: '请输入规程编号' }]}
              >
                <Input placeholder="请输入规程编号" disabled={!!editingSpec} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="spec_name" label="规程名称">
                <Input placeholder="请输入规程名称" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="product_code"
                label="产品编码"
                rules={[{ required: true, message: '请输入产品编码' }]}
              >
                <Input placeholder="请输入产品编码" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="product_name" label="产品名称">
                <Input placeholder="请输入产品名称" />
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