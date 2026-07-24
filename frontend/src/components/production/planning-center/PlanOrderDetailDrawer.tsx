'use client'

import { useState } from 'react'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPlanOrderClient } from '@/lib/api/production-client'
import {
  updatePlanOrder,
  confirmPlanOrder,
  closePlanOrder,
  deletePlanOrder,
} from '@/actions/production'
import { PlanItemTable } from './PlanItemTable'
import { ReleaseConfirmModal } from './ReleaseConfirmModal'
import { STATUS_CONFIG, PRIORITY_CONFIG } from './constants'

const { Text } = Typography

interface Props {
  orderId: string | null
  onClose: () => void
}

export function PlanOrderDetailDrawer({ orderId, onClose }: Props) {
  const { modal, message } = App.useApp()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editForm] = Form.useForm()
  const [releaseModalOpen, setReleaseModalOpen] = useState(false)

  const { data: order, isLoading } = useQuery({
    queryKey: ['plan-order-detail', orderId],
    queryFn: () => fetchPlanOrderClient(orderId!),
    enabled: !!orderId,
  })

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: ['plan-order-detail', orderId] })
    queryClient.invalidateQueries({ queryKey: ['plan-orders'] })
  }

  const status = order ? (STATUS_CONFIG[order.status] ?? { label: order.status, color: 'default' }) : null
  const priority = order ? (PRIORITY_CONFIG[order.priority] ?? { label: order.priority, color: 'default' }) : null

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const handleEdit = () => {
    editForm.setFieldsValue({
      title: order?.title,
      scheduled_start: order?.scheduled_start ? order.scheduled_start.slice(0, 10) : undefined,
      scheduled_end: order?.scheduled_end ? order.scheduled_end.slice(0, 10) : undefined,
      priority: order?.priority,
      remark: order?.remark,
    })
    setEditing(true)
  }

  const handleSaveEdit = async () => {
    const values = await editForm.validateFields().catch(() => null)
    if (!values || !orderId) return
    const r = await updatePlanOrder(orderId, values)
    if (r.success) {
      message.success('已保存')
      setEditing(false)
      refetch()
    } else {
      message.error(r.error)
    }
  }

  const handleConfirm = async () => {
    if (!orderId) return
    const r = await confirmPlanOrder(orderId)
    if (r.success) {
      message.success('已确认')
      refetch()
    } else {
      message.error(r.error)
    }
  }

  const handleDelete = () => {
    if (!order) return
    modal.confirm({
      title: `删除计划单「${order.order_no}」?`,
      content: '删除后不可恢复。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const r = await deletePlanOrder(order.id)
        if (r.success) {
          message.success('已删除')
          refetch()
          onClose()
        } else {
          message.error(r.error)
        }
      },
    })
  }

  return (
    <Drawer
      title={order ? `计划单 · ${order.order_no}` : '计划单'}
      open={!!orderId}
      onClose={onClose}
      size="large"
      destroyOnHidden
      styles={{ body: { padding: '16px 24px' } }}
    >
      {isLoading || !order ? (
        <div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>
      ) : (
        <>
          {/* 编辑模式 */}
          <div style={{ display: editing ? 'block' : 'none' }}>
            <Form form={editForm} layout="vertical" style={{ marginBottom: 24 }}>
              <Form.Item name="title" label="标题" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Space size="middle" wrap>
                <Form.Item name="scheduled_start" label="计划开始">
                  <Input type="date" />
                </Form.Item>
                <Form.Item name="scheduled_end" label="计划结束">
                  <Input type="date" />
                </Form.Item>
                <Form.Item name="priority" label="优先级">
                  <Select
                    style={{ width: 100 }}
                    options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
                  />
                </Form.Item>
              </Space>
              <Form.Item name="remark" label="备注">
                <Input.TextArea rows={2} />
              </Form.Item>
              <Space>
                <Button type="primary" onClick={handleSaveEdit}>保存</Button>
                <Button onClick={() => setEditing(false)}>取消</Button>
              </Space>
            </Form>
          </div>
          <div style={{ display: editing ? 'none' : 'block' }}>
            <>
              {/* 基本信息 */}
              <Descriptions
                column={2}
                size="small"
                bordered
                style={{ marginBottom: 24 }}
                items={[
                  { key: 'order_no', label: '单号', children: order.order_no },
                  { key: 'title', label: '标题', children: order.title },
                  { key: 'version', label: '版本', children: <Tag>v{order.plan_version}</Tag> },
                  { key: 'status', label: '状态', children: status ? <Tag color={status.color}>{status.label}</Tag> : '—' },
                  { key: 'priority', label: '优先级', children: priority ? <Tag color={priority.color}>{priority.label}</Tag> : '—' },
                  { key: 'dates', label: '计划周期', children: `${formatDate(order.scheduled_start)} ~ ${formatDate(order.scheduled_end)}` },
                  { key: 'remark', label: '备注', children: order.remark || '—', span: 2 },
                ]}
              />

              {/* 状态操作按钮 */}
              <Space style={{ marginBottom: 24 }}>
                {order.status === 'draft' && (
                  <>
                    <Button type="primary" onClick={handleConfirm}>确认</Button>
                    <Button onClick={handleEdit}>编辑</Button>
                    <Button danger onClick={handleDelete}>删除</Button>
                  </>
                )}
                {order.status === 'confirmed' && (
                  <>
                    <Button onClick={handleEdit}>编辑</Button>
                    <Button type="primary" onClick={() => setReleaseModalOpen(true)}>下达</Button>
                    <Button
                      onClick={async () => {
                        const r = await closePlanOrder(order.id)
                        if (r.success) {
                          message.success('已关闭')
                          refetch()
                        } else message.error(r.error)
                      }}
                    >
                      关闭
                    </Button>
                  </>
                )}
                {(order.status === 'released' || order.status === 'completed') && (
                  <Button
                    onClick={async () => {
                      const r = await closePlanOrder(order.id)
                      if (r.success) {
                        message.success('已关闭')
                        queryClient.invalidateQueries({ queryKey: ['plan-order-detail', orderId] })
                        refetch()
                      } else message.error(r.error)
                    }}
                  >
                    关闭
                  </Button>
                )}
              </Space>
            </>
          </div>

          {/* 计划项列表 */}
          <div style={{ marginBottom: 24 }}>
            <PlanItemTable
              planOrderId={order.id}
              planOrderStatus={order.status}
              items={order.items}
              isLoading={isLoading}
              onRefresh={refetch}
            />
          </div>

          {/* 关联需求 */}
          <div>
            <Text strong style={{ fontSize: 14, marginBottom: 12, display: 'block' }}>关联需求</Text>
            {order.demand_allocations?.length ? (
              <Descriptions
                column={1}
                size="small"
                bordered
                items={order.demand_allocations.map(a => ({
                  key: a.id,
                  label: a.demand_no ?? '—',
                  children: (
                    <span>{a.intermediate_type_name ?? '—'} | 分配量: {a.allocated_quantity} | 计划项: #{a.item_no}</span>
                  ),
                }))}
              />
            ) : (
              <Empty description="暂无关联需求" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>

          <ReleaseConfirmModal
            orderId={order.id}
            open={releaseModalOpen}
            items={order.items}
            onClose={() => setReleaseModalOpen(false)}
            onRefresh={refetch}
          />
        </>
      )}
    </Drawer>
  )
}
