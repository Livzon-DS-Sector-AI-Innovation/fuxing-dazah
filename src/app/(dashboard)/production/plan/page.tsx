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
} from '@ant-design/icons'
import { useProductionStore } from '@/stores/production'
import { getPlans, createPlan, updatePlan, deletePlan } from '@/actions/production'
import type { ProductionPlan, ProductionPlanFormData, PlanStatus } from '@/types/production'
import { PLAN_STATUS_OPTIONS } from '@/types/production'

const getStatusColor = (status: PlanStatus) => {
  const option = PLAN_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.color || 'default'
}

const getStatusLabel = (status: PlanStatus) => {
  const option = PLAN_STATUS_OPTIONS.find((o) => o.value === status)
  return option?.label || status
}

export default function PlanPage() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingPlan, setEditingPlan] = useState<ProductionPlan | null>(null)
  const [searchMonth, setSearchMonth] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<PlanStatus | undefined>()

  const {
    plans,
    planTotal,
    planQueryParams,
    setPlans,
    setPlanTotal,
    setPlanQueryParams,
    addPlan,
    updatePlan: updatePlanInStore,
    removePlan,
  } = useProductionStore()

  const loadPlans = async () => {
    setLoading(true)
    try {
      const response = await getPlans({
        ...planQueryParams,
        status: statusFilter,
        plan_month: searchMonth,
      })
      if (response.code === 200) {
        setPlans(response.data)
        setPlanTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载生产计划列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPlans()
  }, [planQueryParams.page, planQueryParams.page_size, statusFilter])

  const handleSearch = () => {
    setPlanQueryParams({ page: 1 })
    loadPlans()
  }

  const handleAdd = () => {
    setEditingPlan(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (record: ProductionPlan) => {
    setEditingPlan(record)
    editForm.setFieldsValue(record)
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个生产计划吗？',
      onOk: async () => {
        try {
          const response = await deletePlan(id)
          if (response.code === 200) {
            message.success('删除成功')
            removePlan(id)
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
      const values = editingPlan ? await editForm.validateFields() : await form.validateFields()

      if (editingPlan) {
        const response = await updatePlan(editingPlan.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updatePlanInStore(editingPlan.id, response.data)
          setModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createPlan(values as ProductionPlanFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addPlan(response.data)
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

  const columns: ColumnsType<ProductionPlan> = [
    {
      title: '计划编号',
      dataIndex: 'plan_no',
      key: 'plan_no',
      width: 150,
    },
    {
      title: '计划名称',
      dataIndex: 'plan_name',
      key: 'plan_name',
      width: 200,
    },
    {
      title: '计划类型',
      dataIndex: 'plan_type',
      key: 'plan_type',
      width: 100,
    },
    {
      title: '计划月份',
      dataIndex: 'plan_month',
      key: 'plan_month',
      width: 120,
    },
    {
      title: '总批次',
      dataIndex: 'total_batches',
      key: 'total_batches',
      width: 80,
    },
    {
      title: '已完成批次',
      dataIndex: 'completed_batches',
      key: 'completed_batches',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: PlanStatus) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
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
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
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
        title="生产计划"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新建计划
          </Button>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={6}>
            <Input
              placeholder="搜索计划月份 (YYYY-MM)"
              value={searchMonth}
              onChange={(e) => setSearchMonth(e.target.value)}
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
                setPlanQueryParams({ page: 1 })
              }}
              style={{ width: '100%' }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'approved', label: '已批准' },
                { value: 'executing', label: '执行中' },
                { value: 'completed', label: '已完成' },
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
          dataSource={plans}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1000 }}
          pagination={{
            current: planQueryParams.page,
            pageSize: planQueryParams.page_size,
            total: planTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPlanQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      <Modal
        title={editingPlan ? '编辑生产计划' : '新建生产计划'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="确认"
        cancelText="取消"
      >
        <Form form={editingPlan ? editForm : form} layout="vertical" initialValues={editingPlan || undefined}>
          <Form.Item
            name="plan_no"
            label="计划编号"
            rules={[{ required: true, message: '请输入计划编号' }]}
          >
            <Input placeholder="请输入计划编号" disabled={!!editingPlan} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="plan_name" label="计划名称">
                <Input placeholder="请输入计划名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="plan_type" label="计划类型">
                <Select
                  placeholder="请选择"
                  options={[
                    { value: '月度计划', label: '月度计划' },
                    { value: '周计划', label: '周计划' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="plan_month" label="计划月份">
            <Input placeholder="请输入计划月份 (YYYY-MM)" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}