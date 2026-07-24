'use client'

import { useState, useEffect } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Tag,
  Typography,
  Spin,
} from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { deletePlanOrder } from '@/actions/production'
import type { PlanOrder } from '@/types/production'
import { fetchPlanOrdersClient } from '@/lib/api/production-client'
import { PlanOrderDetailDrawer } from './PlanOrderDetailDrawer'
import { CreatePlanOrderModal } from './CreatePlanOrderModal'
import { STATUS_CONFIG, PRIORITY_CONFIG } from './constants'

const { Text } = Typography

export function PlanOrderList() {
  const { modal, message } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [debouncedKeyword, setDebouncedKeyword] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [detailOrderId, setDetailOrderId] = useState<string | null>(null)

  // ponytail: debounce keyword to avoid per-keystroke API calls
  useEffect(() => {
    const t = setTimeout(() => setDebouncedKeyword(keyword), 300)
    return () => clearTimeout(t)
  }, [keyword])

  const { data: orders = [], isLoading, refetch } = useQuery({
    queryKey: ['plan-orders', debouncedKeyword],
    queryFn: () => fetchPlanOrdersClient({ keyword: debouncedKeyword || undefined, page_size: 100 }),
  })

  const handleDelete = (order: PlanOrder) => {
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
        } else {
          message.error(r.error)
        }
      },
    })
  }

  const formatDate = (d: string | null) => {
    if (!d) return '—'
    return new Date(d).toLocaleDateString('zh-CN')
  }

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Input
          placeholder="搜索计划单编号/标题"
          prefix={<SearchOutlined />}
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{ width: 280 }}
          allowClear
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建计划单
        </Button>
      </div>

      {orders.length === 0 ? (
        <Empty description="暂无计划单" />
      ) : (
        <Row gutter={[16, 16]}>
          {orders
            .map(order => {
              const status = STATUS_CONFIG[order.status] ?? { label: order.status, color: 'default' }
              const priority = PRIORITY_CONFIG[order.priority] ?? { label: order.priority, color: 'default' }
              return (
                <Col key={order.id} xs={24} sm={12} lg={8} xl={6}>
                  <Card
                    size="small"
                    style={{ height: '100%' }}
                    title={
                      <div style={{ width: '100%' }}>
                        <Text strong style={{ fontSize: 14 }}>{order.order_no}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{order.title}</Text>
                      </div>
                    }
                    extra={<Tag>{`v${order.plan_version}`}</Tag>}
                    styles={{ body: { padding: '12px 16px' } }}
                  >
                    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Tag color={status.color}>{status.label}</Tag>
                        <Tag color={priority.color}>{priority.label}</Tag>
                      </div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatDate(order.scheduled_start)} ~ {formatDate(order.scheduled_end)}
                      </Text>
                      {order.remark && (
                        <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                          备注：{order.remark}
                        </Text>
                      )}
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                        <Button size="small" onClick={() => setDetailOrderId(order.id)}>
                          查看详情
                        </Button>
                        {order.status === 'draft' && (
                          <>
                            <Button
                              size="small"
                              type="primary"
                              onClick={async () => {
                                const { confirmPlanOrder } = await import('@/actions/production')
                                const r = await confirmPlanOrder(order.id)
                                if (r.success) { message.success('已确认'); refetch() } else { message.error(r.error) }
                              }}
                            >
                              确认
                            </Button>
                            <Button size="small" onClick={() => {
                              // ponytail: edit reuses CreatePlanOrderModal with edit mode
                              // For now, open detail which has edit capabilities
                              setDetailOrderId(order.id)
                            }}>
                              编辑
                            </Button>
                            <Button size="small" danger onClick={() => handleDelete(order)}>
                              删除
                            </Button>
                          </>
                        )}
                        {order.status === 'confirmed' && (
                          <Button
                            size="small"
                            type="primary"
                            onClick={async () => {
                              const { releasePlanOrder } = await import('@/actions/production')
                              const r = await releasePlanOrder(order.id)
                              if (r.success) { message.success('已下达'); refetch() } else { message.error(r.error) }
                            }}
                          >
                            下达
                          </Button>
                        )}
                        {(order.status === 'released' || order.status === 'completed') && (
                          <Button
                            size="small"
                            onClick={async () => {
                              const { closePlanOrder } = await import('@/actions/production')
                              const r = await closePlanOrder(order.id)
                              if (r.success) { message.success('已关闭'); refetch() } else { message.error(r.error) }
                            }}
                          >
                            关闭
                          </Button>
                        )}
                      </div>
                    </div>
                  </Card>
                </Col>
              )
            })}
        </Row>
      )}

      <CreatePlanOrderModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSuccess={() => { setCreateOpen(false); refetch() }}
      />

      <PlanOrderDetailDrawer
        orderId={detailOrderId}
        onClose={() => setDetailOrderId(null)}
      />
    </div>
  )
}
