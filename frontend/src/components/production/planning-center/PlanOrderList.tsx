'use client'

import { useState, useEffect, useMemo } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Input,
  Row,
  Select,
  Spin,
  Tag,
} from 'antd'
import type { MenuProps } from 'antd'
import {
  EllipsisOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  closePlanOrder,
  confirmPlanOrder,
  deletePlanOrder,
  releasePlanOrder,
} from '@/actions/production'
import type { PlanOrder, Product } from '@/types/production'
import { fetchPlanOrdersClient, fetchProductsClient } from '@/lib/api/production-client'
import { PlanOrderDetailDrawer } from './PlanOrderDetailDrawer'
import { CreatePlanOrderModal } from './CreatePlanOrderModal'
import { STATUS_CONFIG } from './constants'

const PRIORITY_DOTS: Record<string, number> = { urgent: 3, high: 2, medium: 1, low: 0 }

const STATUS_BAR_COLORS: Record<string, string> = {
  draft: 'var(--color-stone)',
  confirmed: 'var(--color-primary, #5645d4)',
  released: '#7b3ff2',
  completed: 'var(--color-success, #1aae39)',
  closed: 'var(--color-stone)',
}

export function PlanOrderList() {
  const { modal, message } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [debouncedKeyword, setDebouncedKeyword] = useState('')
  const [productFilter, setProductFilter] = useState<string | undefined>()
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

  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: () => fetchProductsClient(),
    staleTime: 60_000,
  })

  const productMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of (products ?? [])) { m.set(p.id, p.product_name) }
    return m
  }, [products])

  const filteredOrders = useMemo(() => {
    if (!productFilter) return orders
    return orders.filter((o) => o.product_id === productFilter)
  }, [orders, productFilter])

  const stats = useMemo(() => {
    const total = filteredOrders.length
    const draft = filteredOrders.filter(o => o.status === 'draft').length
    const confirmed = filteredOrders.filter(o => o.status === 'confirmed').length
    const released = filteredOrders.filter(o => o.status === 'released').length
    return { total, draft, confirmed, released }
  }, [filteredOrders])

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

  const buildMenuItems = (order: PlanOrder): MenuProps['items'] => {
    const items: MenuProps['items'] = []
    if (order.status === 'draft') {
      items.push(
        { key: 'confirm', label: '确认', onClick: async () => {
          const r = await confirmPlanOrder(order.id)
          if (r.success) { message.success('已确认'); refetch() } else { message.error(r.error) }
        }},
        { key: 'edit', label: '编辑', onClick: () => setDetailOrderId(order.id) },
        { key: 'delete', label: '删除', danger: true, onClick: () => handleDelete(order) },
      )
    } else if (order.status === 'confirmed') {
      items.push(
        { key: 'release', label: '下达', onClick: async () => {
          const r = await releasePlanOrder(order.id)
          if (r.success) { message.success('已下达'); refetch() } else { message.error(r.error) }
        }},
        { key: 'edit', label: '编辑', onClick: () => setDetailOrderId(order.id) },
        { key: 'close', label: '关闭', onClick: async () => {
          const r = await closePlanOrder(order.id)
          if (r.success) { message.success('已关闭'); refetch() } else { message.error(r.error) }
        }},
      )
    } else if (order.status === 'released' || order.status === 'completed') {
      items.push(
        { key: 'close', label: '关闭', onClick: async () => {
          const r = await closePlanOrder(order.id)
          if (r.success) { message.success('已关闭'); refetch() } else { message.error(r.error) }
        }},
      )
    }
    return items
  }

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flex: 1 }}>
          <Input
            placeholder="搜索计划单编号/标题"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            style={{ width: 240 }}
            allowClear
          />
          <Select
            placeholder="按产品筛选"
            allowClear
            style={{ width: 200 }}
            value={productFilter}
            onChange={setProductFilter}
            options={(products ?? []).map((p: Product) => ({
              value: p.id,
              label: p.product_name,
            }))}
          />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建计划单
        </Button>
      </div>

      {filteredOrders.length > 0 && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 13, color: 'var(--color-slate)' }}>
          <span>全部 <strong style={{ color: 'var(--color-charcoal)' }}>{stats.total}</strong></span>
          <span>草稿 <strong style={{ color: 'var(--color-charcoal)' }}>{stats.draft}</strong></span>
          <span>已确认 <strong style={{ color: 'var(--color-charcoal)' }}>{stats.confirmed}</strong></span>
          <span>已下达 <strong style={{ color: 'var(--color-charcoal)' }}>{stats.released}</strong></span>
        </div>
      )}

      {filteredOrders.length === 0 ? (
        <Empty description="暂无计划单" />
      ) : (
        <Row gutter={[16, 16]}>
          {filteredOrders.map(order => {
            const status = STATUS_CONFIG[order.status] ?? { label: order.status, color: 'default' }
            const priorityDots = PRIORITY_DOTS[order.priority] ?? 0
            const barColor = STATUS_BAR_COLORS[order.status] ?? 'var(--color-stone)'
            const menuItems = buildMenuItems(order)

            return (
              <Col key={order.id} xs={24} sm={12} lg={8} xl={6}>
                <Card
                  size="small"
                  style={{
                    height: '100%',
                    transition: 'transform 0.15s ease, box-shadow 0.15s ease',
                  }}
                  className="plan-order-card"
                  styles={{ body: { padding: '12px 16px' } }}
                >
                  {/* Header: color bar + order_no + version */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <div style={{
                      width: 4, height: 36, borderRadius: 2,
                      backgroundColor: barColor,
                      flexShrink: 0,
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-charcoal)', lineHeight: 1.3 }}>
                        {order.order_no}
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--color-steel)', lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {order.title}
                      </div>
                    </div>
                    <Tag style={{ fontSize: 11, margin: 0 }}>v{order.plan_version}</Tag>
                  </div>

                  {/* Info row: product + period */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
                    {order.product_id && productMap.get(order.product_id) && (
                      <div style={{ fontSize: 12, color: 'var(--color-stone)' }}>
                        产品：{productMap.get(order.product_id)}
                      </div>
                    )}
                    <div style={{ fontSize: 12, color: 'var(--color-stone)' }}>
                      {formatDate(order.scheduled_start)} ~ {formatDate(order.scheduled_end)}
                    </div>
                  </div>

                  {/* Status dot + priority circles */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{
                        width: 8, height: 8, borderRadius: '50%',
                        backgroundColor: status.color === 'default' ? 'var(--color-stone)' : `var(--ant-color-${status.color})`,
                        display: 'inline-block',
                      }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>{status.label}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 3 }}>
                      {[1, 2, 3].map((n) => (
                        <span key={n} style={{
                          width: 7, height: 7, borderRadius: '50%',
                          border: '1.5px solid var(--color-stone)',
                          backgroundColor: n <= priorityDots ? 'var(--color-charcoal)' : 'transparent',
                          display: 'inline-block',
                        }} />
                      ))}
                    </div>
                  </div>

                  {/* Actions: detail button + overflow menu */}
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Button size="small" onClick={() => setDetailOrderId(order.id)}>查看详情</Button>
                    {menuItems && menuItems.length > 0 && (
                      <Dropdown menu={{ items: menuItems }} trigger={['click']}>
                        <Button size="small" icon={<EllipsisOutlined />} />
                      </Dropdown>
                    )}
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
