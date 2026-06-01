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
  InputNumber,
  message,
  Tag,
  Card,
  Row,
  Col,
  DatePicker,
  Typography,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  StopOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { useProductionStore } from '@/stores/production'
import {
  getBatches,
  createBatch,
  updateBatch,
  updateBatchStatus,
  deleteBatch,
} from '@/actions/production'
import type {
  Batch,
  BatchFormData,
  BatchStatus,
} from '@/types/production'
import { BatchStatus as BatchStatusEnum, BATCH_STATUS_OPTIONS } from '@/types/production'

const { Text } = Typography

// Helper to get status color
const getStatusColor = (status: BatchStatus) => {
  const option = BATCH_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

// Helper to get status label
const getStatusLabel = (status: BatchStatus) => {
  const option = BATCH_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

// 导出批次数据为CSV
const exportBatchesToCsv = (batches: Batch[]) => {
  const headers = ['批次号', '产品编码', '产品名称', '规格', '计划数量', '实际产出', '投入数量', '状态', '生产线', '开始时间', '结束时间']
  const rows = batches.map(b => [
    b.batch_no,
    b.product_code,
    b.product_name || '',
    b.specification || '',
    b.planned_qty || '',
    b.actual_qty || '',
    b.input_qty || '',
    getStatusLabel(b.status),
    b.production_line || '',
    b.start_time ? new Date(b.start_time).toLocaleString('zh-CN') : '',
    b.end_time ? new Date(b.end_time).toLocaleString('zh-CN') : '',
  ])

  const csvContent = [headers, ...rows]
    .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')

  const BOM = '\uFEFF'
  const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `批次列表_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

export default function BatchesPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingBatch, setEditingBatch] = useState<Batch | null>(null)
  const [searchText, setSearchText] = useState('')
  const [productNameSearch, setProductNameSearch] = useState('')
  const [productionLineFilter, setProductionLineFilter] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<BatchStatus | undefined>()
  const [exportLoading, setExportLoading] = useState(false)

  const {
    batches,
    batchTotal,
    batchQueryParams,
    setBatches,
    setBatchTotal,
    setBatchQueryParams,
    addBatch,
    updateBatch: updateBatchInStore,
    removeBatch,
  } = useProductionStore()

  const loadBatches = async () => {
    setLoading(true)
    try {
      const response = await getBatches({
        ...batchQueryParams,
        status: statusFilter,
        batch_no: searchText || undefined,
      })
      if (response.code === 200) {
        setBatches(response.data)
        setBatchTotal(response.meta?.total || 0)
      }
    } catch (error) {
      message.error('加载批次列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadBatches()
  }, [batchQueryParams.page, batchQueryParams.page_size, statusFilter])

  const handleSearch = () => {
    setBatchQueryParams({ page: 1 })
    loadBatches()
  }

  const handleAdd = () => {
    setEditingBatch(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: Batch) => {
    setEditingBatch(record)
    editForm.setFieldsValue(record)
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个批次吗？',
      onOk: async () => {
        try {
          const response = await deleteBatch(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeBatch(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleStatusChange = async (id: string, newStatus: BatchStatus) => {
    try {
      const response = await updateBatchStatus(id, newStatus)
      if (response.code === 200) {
        message.success('状态更新成功')
        updateBatchInStore(id, { status: newStatus })
      } else {
        message.error(response.message || '状态更新失败')
      }
    } catch {
      message.error('状态更新失败')
    }
  }

  const handleSubmit = async () => {
    try {
      const values = editingBatch ? await editForm.validateFields() : await form.validateFields()

      if (editingBatch) {
        const response = await updateBatch(editingBatch.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateBatchInStore(editingBatch.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createBatch(values as BatchFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addBatch(response.data)
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

  const handleExport = async () => {
    setExportLoading(true)
    try {
      // 获取所有批次数据进行导出
      const response = await getBatches({ page: 1, page_size: 10000 })
      if (response.code === 200 && response.data.length > 0) {
        exportBatchesToCsv(response.data)
        message.success(`已导出 ${response.data.length} 条批次数据`)
      } else {
        message.warning('没有可导出的批次数据')
      }
    } catch {
      message.error('导出失败')
    } finally {
      setExportLoading(false)
    }
  }

  const columns: ColumnsType<Batch> = [
    {
      title: '批次号',
      dataIndex: 'batch_no',
      key: 'batch_no',
      width: 150,
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
      ellipsis: true,
    },
    {
      title: '规格',
      dataIndex: 'specification',
      key: 'specification',
      width: 100,
    },
    {
      title: '计划数量',
      dataIndex: 'planned_qty',
      key: 'planned_qty',
      width: 100,
    },
    {
      title: '实际产出',
      dataIndex: 'actual_qty',
      key: 'actual_qty',
      width: 100,
    },
    {
      title: '投入数量',
      dataIndex: 'input_qty',
      key: 'input_qty',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: BatchStatus) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '生产线',
      dataIndex: 'production_line',
      key: 'production_line',
      width: 120,
    },
    {
      title: '开始时间',
      dataIndex: 'start_time',
      key: 'start_time',
      width: 160,
      render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '结束时间',
      dataIndex: 'end_time',
      key: 'end_time',
      width: 160,
      render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === BatchStatusEnum.DRAFT && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStatusChange(record.id, BatchStatusEnum.RELEASED)}
            >
              下达
            </Button>
          )}
          {record.status === BatchStatusEnum.RELEASED && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleStatusChange(record.id, BatchStatusEnum.IN_PROGRESS)}
            >
              开始
            </Button>
          )}
          {record.status === BatchStatusEnum.IN_PROGRESS && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleStatusChange(record.id, BatchStatusEnum.COMPLETED)}
            >
              完成
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
        title="批次管理"
        extra={
          <Space>
            <Tooltip title="导出当前筛选结果的批次数据">
              <Button icon={<DownloadOutlined />} onClick={handleExport} loading={exportLoading}>
                导出
              </Button>
            </Tooltip>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
              新建批次
            </Button>
          </Space>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={5}>
            <Input
              placeholder="搜索批次号"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Input
              placeholder="产品名称"
              value={productNameSearch}
              onChange={(e) => setProductNameSearch(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="生产线"
              allowClear
              value={productionLineFilter}
              onChange={(value) => {
                setProductionLineFilter(value)
                setBatchQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={[
                { value: 'A线', label: 'A线' },
                { value: 'B线', label: 'B线' },
                { value: 'C线', label: 'C线' },
              ]}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态"
              allowClear
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value)
                setBatchQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'released', label: '已下达' },
                { value: 'in_progress', label: '执行中' },
                { value: 'completed', label: '已完成' },
                { value: 'cancelled', label: '已取消' },
              ]}
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
          dataSource={batches}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1600 }}
          pagination={{
            current: batchQueryParams.page,
            pageSize: batchQueryParams.page_size,
            total: batchTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setBatchQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingBatch ? '编辑批次' : '新建批次'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form
          form={editingBatch ? editForm : form}
          layout="vertical"
          initialValues={editingBatch || undefined}
        >
          <Form.Item
            name="batch_no"
            label="批次号"
            rules={[{ required: true, message: '请输入批次号' }]}
          >
            <Input placeholder="请输入批次号" disabled={!!editingBatch} />
          </Form.Item>
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
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="specification" label="规格">
                <Input placeholder="请输入规格" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unit" label="单位">
                <Input placeholder="请输入单位" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="planned_qty" label="计划数量">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入计划数量" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="input_qty" label="投入数量">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入投入数量" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="actual_qty" label="实际产出">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="请输入实际产出" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="production_line" label="生产线">
                <Select placeholder="请选择生产线" allowClear>
                  <Select.Option value="A线">A线</Select.Option>
                  <Select.Option value="B线">B线</Select.Option>
                  <Select.Option value="C线">C线</Select.Option>
                </Select>
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