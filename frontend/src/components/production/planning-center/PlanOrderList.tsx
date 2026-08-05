'use client'

import { useState, useMemo } from 'react'
import {
  App,
  Button,
  Col,
  Dropdown,
  Empty,
  Input,
  Modal,
  Row,
  Select,
  Spin,
  Tag,
} from 'antd'
import type { MenuProps } from 'antd'
import {
  EllipsisOutlined,
  PlusOutlined,
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
import { PLAN_ORDER_STATUS_SEQUENCE, STATUS_CONFIG, STATUS_THEME } from './constants'
import { formatDate } from '@/lib/utils'

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'var(--color-error)',
  high: 'var(--color-warning)',
  medium: 'var(--color-primary)',
  low: 'var(--color-stone)',
}

export function PlanOrderList() {
  const { modal, message } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [productFilter, setProductFilter] = useState<string | undefined>()
  const [createOpen, setCreateOpen] = useState(false)
  const [detailOrderId, setDetailOrderId] = useState<string | null>(null)
  const [changeTargetOrderId, setChangeTargetOrderId] = useState<string | null>(null)
  const [changeReason, setChangeReason] = useState('')

  const { data: orders = [], isLoading, refetch } = useQuery({
    queryKey: ['plan-orders', searchKeyword],
    queryFn: () => fetchPlanOrdersClient({ keyword: searchKeyword || undefined, page_size: 100 }),
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

  const handleConfirm = (order: PlanOrder) => {
    modal.confirm({
      title: `确认计划单「${order.order_no}」?`,
      content: '确认后将锁定计划项，无法再增删或修改。',
      okText: '确认并锁定',
      cancelText: '取消',
      onOk: async () => {
        const r = await confirmPlanOrder(order.id)
        if (r.success) { message.success('已确认'); refetch() } else { message.error(r.error) }
      },
    })
  }

  const handleRelease = (order: PlanOrder) => {
    modal.confirm({
      title: `下达计划单「${order.order_no}」?`,
      content: '下达后将生成生产批次，确定要下达吗？',
      okText: '确认下达',
      cancelText: '取消',
      onOk: async () => {
        const r = await releasePlanOrder(order.id)
        if (r.success) { message.success('已下达'); refetch() } else { message.error(r.error) }
      },
    })
  }

  const handleChange = (order: PlanOrder) => {
    setChangeTargetOrderId(order.id)
    setChangeReason('')
  }

  const handleChangeConfirm = () => {
    if (!changeReason.trim() || !changeTargetOrderId) return
    setDetailOrderId(changeTargetOrderId)
    setChangeTargetOrderId(null)
  }

  const handleClose = (order: PlanOrder) => {
    modal.confirm({
      title: `关闭计划单「${order.order_no}」?`,
      content: '关闭后将无法继续操作。',
      okText: '确认关闭',
      cancelText: '取消',
      onOk: async () => {
        const r = await closePlanOrder(order.id)
        if (r.success) { message.success('已关闭'); refetch() } else { message.error(r.error) }
      },
    })
  }

  const buildMenuItems = (order: PlanOrder): MenuProps['items'] => {
    const items: MenuProps['items'] = []
    if (order.status === 'draft') {
      items.push(
        { key: 'confirm', label: '确认并锁定', onClick: () => handleConfirm(order) },
        { key: 'edit', label: '编辑', onClick: () => setDetailOrderId(order.id) },
        { key: 'delete', label: '删除', danger: true, onClick: () => handleDelete(order) },
      )
    } else if (order.status === 'confirmed') {
      items.push(
        { key: 'release', label: '下达', onClick: () => handleRelease(order) },
        { key: 'edit', label: '编辑', onClick: () => setDetailOrderId(order.id) },
        { key: 'close', label: '关闭', onClick: () => handleClose(order) },
      )
    } else if (order.status === 'released' || order.status === 'completed') {
      items.push(
        { key: 'change', label: '变更', onClick: () => handleChange(order) },
        { key: 'close', label: '关闭', onClick: () => handleClose(order) },
      )
    }
    return items
  }

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>
  }

  return (
    <div>
      {/* ── 搜索栏 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flex: 1 }}>
          <Input.Search
            placeholder="搜索计划单编号/标题"
            value={keyword}
            // allowClear 的 X 只触发 onChange 不触发 onSearch，清空时必须同步重置筛选
            onChange={e => {
              setKeyword(e.target.value)
              if (!e.target.value) setSearchKeyword('')
            }}
            onSearch={setSearchKeyword}
            style={{ width: 260 }}
            allowClear
            enterButton="搜索"
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

      {filteredOrders.length === 0 ? (
        <Empty description="暂无计划单" />
      ) : (
        <div className="plan-order-groups">
          {PLAN_ORDER_STATUS_SEQUENCE.map(statusKey => {
            const group = filteredOrders.filter(o => o.status === statusKey)
            if (group.length === 0) return null
            const theme = STATUS_THEME[statusKey] ?? STATUS_THEME.draft
            const label = (STATUS_CONFIG[statusKey] ?? { label: statusKey }).label

            return (
              <section key={statusKey} className="plan-order-group">
                {/* 组头 — 状态色点 + 名称 + 计数，右侧细线延伸 */}
                <header className="plan-order-group-header">
                  <span className="plan-order-group-dot" style={{ backgroundColor: theme.bar }} />
                  <span className="plan-order-group-label">{label}</span>
                  <span className="plan-order-group-count" style={{ color: theme.text, backgroundColor: theme.tint }}>
                    {group.length}
                  </span>
                </header>

                <Row gutter={[16, 16]}>
                  {group.map(order => {
                    const cardTheme = STATUS_THEME[order.status] ?? STATUS_THEME.draft
                    const cardLabel = (STATUS_CONFIG[order.status] ?? { label: order.status }).label
                    const priorityColor = PRIORITY_COLORS[order.priority] ?? 'var(--color-stone)'
                    const menuItems = buildMenuItems(order)

                    return (
                      <Col key={order.id} xs={24} sm={12} lg={8} xl={6}>
                        <div
                          className={`plan-order-card${order.status === 'closed' ? ' plan-order-card--closed' : ''}`}
                          onClick={() => setDetailOrderId(order.id)}
                          style={{
                            background: 'var(--color-canvas)',
                            borderRadius: 10,
                            border: '1px solid var(--color-hairline)',
                            cursor: 'pointer',
                            transition: 'transform 0.18s ease, box-shadow 0.18s ease, opacity 0.18s ease',
                            position: 'relative',
                            overflow: 'hidden',
                          }}
                        >
                          {/* 顶部状态色条 */}
                          <div style={{
                            height: 3,
                            backgroundColor: cardTheme.bar,
                            borderTopLeftRadius: 10,
                            borderTopRightRadius: 10,
                          }} />

                          <div style={{ padding: '14px 16px' }}>
                            {/* 头部：编号 + 状态徽章 */}
                            <div style={{
                              display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                              marginBottom: 6, gap: 8,
                            }}>
                              <span style={{
                                fontSize: 16, fontWeight: 650, color: 'var(--color-charcoal)',
                                lineHeight: 1.3, letterSpacing: '-0.01em',
                              }}>
                                {order.order_no}
                              </span>
                              <span style={{
                                fontSize: 11, fontWeight: 600, lineHeight: '18px',
                                padding: '1px 8px', borderRadius: 9999,
                                backgroundColor: cardTheme.tint,
                                color: cardTheme.text,
                                flexShrink: 0, whiteSpace: 'nowrap',
                              }}>
                                {cardLabel}
                              </span>
                            </div>

                    {/* 标题 */}
                    <div style={{
                      fontSize: 13, color: 'var(--color-steel)', lineHeight: 1.35,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      marginBottom: 10,
                    }}>
                      {order.title}
                    </div>

                    {/* 产品 */}
                    {order.product_id && productMap.get(order.product_id) && (
                      <div style={{
                        fontSize: 12, color: 'var(--color-slate)',
                        marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4,
                      }}>
                        <span style={{ opacity: 0.45, fontSize: 10, flexShrink: 0 }}>📦</span>
                        {productMap.get(order.product_id)}
                      </div>
                    )}

                    {/* 日期 */}
                    <div style={{
                      fontSize: 12, color: 'var(--color-stone)',
                      marginBottom: 12, display: 'flex', alignItems: 'center', gap: 4,
                    }}>
                      <span style={{ opacity: 0.45, fontSize: 10, flexShrink: 0 }}>📅</span>
                      {formatDate(order.scheduled_start)} ~ {formatDate(order.scheduled_end)}
                    </div>

                    {/* 底部：优先级 + 版本 + 操作 */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: '50%',
                          backgroundColor: priorityColor,
                          display: 'inline-block', flexShrink: 0,
                        }} />
                        <span style={{ fontSize: 11, color: 'var(--color-stone)' }}>
                          {order.priority === 'urgent' ? '紧急' : order.priority === 'high' ? '高' : order.priority === 'low' ? '低' : '中'}
                        </span>
                        <Tag style={{ fontSize: 10, margin: 0, lineHeight: '16px', padding: '0 6px' }}>v{order.plan_version}</Tag>
                      </div>

                      <div onClick={(e) => e.stopPropagation()}>
                        {menuItems && menuItems.length > 0 && (
                          <Dropdown menu={{ items: menuItems }} trigger={['click']}>
                            <button
                              className="plan-order-action-btn"
                              style={{
                                width: 28, height: 28, borderRadius: 6,
                                border: '1px solid transparent', background: 'transparent',
                                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: 'var(--color-stone)',
                                transition: 'all 0.15s ease',
                              }}
                            >
                              <EllipsisOutlined style={{ fontSize: 14 }} />
                            </button>
                          </Dropdown>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
                    </Col>
                  )
                })}
                </Row>
              </section>
            )
          })}
        </div>
      )}

      <CreatePlanOrderModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSuccess={() => { setCreateOpen(false); refetch() }}
      />

      <Modal
        title="变更原因"
        open={!!changeTargetOrderId}
        onOk={handleChangeConfirm}
        onCancel={() => setChangeTargetOrderId(null)}
        okText="开始变更"
        okButtonProps={{ disabled: !changeReason.trim() }}
        destroyOnHidden
      >
        <div style={{ marginBottom: 8, color: 'var(--color-slate)', fontSize: 13 }}>
          请输入本次变更的原因（必填）
        </div>
        <Input.TextArea
          placeholder="例如：客户需求调整，产量增加"
          value={changeReason}
          onChange={e => setChangeReason(e.target.value)}
          rows={4}
        />
      </Modal>

      <PlanOrderDetailDrawer
        orderId={detailOrderId}
        onClose={() => { setDetailOrderId(null); setChangeReason('') }}
        changeReason={changeReason}
      />
    </div>
  )
}
