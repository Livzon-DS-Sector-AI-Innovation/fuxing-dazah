'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Select, Empty, Spin, App } from 'antd'
import { ClockCircleOutlined, InboxOutlined } from '@ant-design/icons'
import { useState, useMemo } from 'react'
import { fetchPlannedBatches, activatePlannedBatch } from '@/actions/production'
import { stageColor } from '@/components/production/shared/stageColor'
import { formatDateTime } from '@/lib/utils'
import type { PlannedBatchItem } from '@/types/production'

// ── 状态配置 ──
const STATUS_CFG: Record<string, { label: string; color: string; bg: string; borderColor: string }> = {
  scheduled: { label: '计划中', color: '#5645d4', bg: '#f4f0ff', borderColor: '#5645d4' },
}

// ── Mini 工段时间条 ──
function StageTimelineBar({ stages }: { stages: PlannedBatchItem['stage_config'] }) {
  if (!stages?.length) return null
  return (
    <div style={{ display: 'flex', height: 5, borderRadius: 3, overflow: 'hidden', gap: 2, marginTop: 2 }}>
      {stages.map(sc => (
        <div
          key={sc.stage_name}
          style={{
            flex: sc.duration_hours,
            background: sc.color,
            minWidth: 4,
          }}
          title={`${sc.stage_name}: ${sc.duration_hours}h`}
        />
      ))}
    </div>
  )
}

// ── 计划批次卡片 ──
function PlannedCard({
  item, index, canSubmit, onReceive,
}: {
  item: PlannedBatchItem
  index: number
  canSubmit: boolean
  onReceive: () => void
}) {
  const cfg = STATUS_CFG.scheduled
  const showReceive = canSubmit && item.is_first_stage_owner

  return (
    <div
      className="wb-card"
      style={{
        position: 'relative', overflow: 'hidden',
        padding: '14px 14px 14px 12px',
        borderRadius: 10,
        background: '#fafaf8',
        border: '1px solid #ede9e4',
        borderLeft: `3px solid ${cfg.borderColor}`,
        display: 'flex', flexDirection: 'column', gap: 6,
        cursor: 'default',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        animationDelay: `${index * 60}ms`,
        opacity: 0.85,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.05)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.3 }}>
            {item.batch_no}
            {item.product_name && (
              <span style={{ color: '#787671', fontWeight: 400, fontSize: 13 }}>
                {' '}·{' '}{item.product_name}
              </span>
            )}
          </div>
          {item.route_name && (
            <div style={{ fontSize: 12, color: '#a4a097', marginTop: 1 }}>
              {item.route_name}
            </div>
          )}
        </div>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          padding: '2px 8px', borderRadius: 5,
          fontSize: 11, fontWeight: 600,
          background: cfg.bg, color: cfg.color,
          whiteSpace: 'nowrap', flexShrink: 0,
        }}>
          <ClockCircleOutlined style={{ fontSize: 11 }} />
          {cfg.label}
        </span>
      </div>

      {/* 预计开始时间 */}
      <div style={{ fontSize: 13, color: '#37352f', fontWeight: 500 }}>
        预计开始：{formatDateTime(item.planned_start)}
      </div>

      {/* 进度指示 */}
      {item.current_stage && item.current_stage_progress === 'in_progress' && (
        <div style={{ fontSize: 12, color: '#1aae39' }}>
          当前：{item.current_stage} · 进行中
        </div>
      )}
      {item.current_stage && item.current_stage_progress === 'not_started' && item.planned_start && (
        <div style={{ fontSize: 12, color: '#a4a097' }}>
          等待开始
        </div>
      )}

      {/* Mini 时间条 */}
      <StageTimelineBar stages={item.stage_config} />

      {/* 接收按钮 — 仅第一工段负责人可见 */}
      {showReceive && (
        <div style={{ marginTop: 4, textAlign: 'right' }}>
          <span
            onClick={e => { e.stopPropagation(); onReceive() }}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '4px 12px', borderRadius: 6,
              fontSize: 12, fontWeight: 600,
              background: '#f4f0ff', color: '#5645d4',
              cursor: 'pointer',
              border: '1px solid #e0d8f5',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#e8e0f8' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#f4f0ff' }}
          >
            <InboxOutlined />
            接收
          </span>
        </div>
      )}
    </div>
  )
}

// ── 主组件 ──

export function PlannedSection({ stageNames, canSubmit }: { stageNames: string[]; canSubmit: boolean }) {
  const [filterProduct, setFilterProduct] = useState<string | undefined>(undefined)
  const [filterRoute, setFilterRoute] = useState<string | undefined>(undefined)
  const queryClient = useQueryClient()
  const { message, modal } = App.useApp()

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['production-workbench-planned'],
    queryFn: async () => {
      const r = await fetchPlannedBatches()
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data!
    },
    refetchInterval: 60_000,
  })

  const handleReceive = (item: PlannedBatchItem) => {
    modal.confirm({
      title: '确认接收',
      content: `确认接收计划批次「${item.batch_no}」？接收后将进入待办区，可以开始执行第一个工序。`,
      okText: '接收',
      cancelText: '取消',
      onOk: async () => {
        const r = await activatePlannedBatch(item.batch_id)
        if (r.success) {
          message.success(`批次 ${item.batch_no} 已接收，进入待办区`)
          queryClient.invalidateQueries({ queryKey: ['production-workbench-planned'] })
          queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
          queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        } else {
          message.error(r.error ?? '接收失败')
        }
      },
    })
  }

  // 筛选选项
  const filterOptions = useMemo(() => {
    if (!data?.items) return { products: [] as { label: string; value: string }[], routes: [] as { label: string; value: string }[] }
    const productSet = new Map<string, string>()
    const routeSet = new Map<string, string>()
    for (const d of data.items) {
      if (d.product_name && !productSet.has(d.product_name)) productSet.set(d.product_name, d.product_name)
      if (!routeSet.has(d.route_id)) routeSet.set(d.route_id, d.route_name)
    }
    return {
      products: [...productSet.values()].map(v => ({ label: v, value: v })),
      routes: [...routeSet.entries()].map(([id, name]) => ({ label: name, value: id })),
    }
  }, [data])

  // 筛选后的 items
  const filteredItems = useMemo(() => {
    if (!data?.items) return []
    let items = data.items
    if (filterProduct) items = items.filter(i => i.product_name === filterProduct)
    if (filterRoute) items = items.filter(i => i.route_id === filterRoute)
    return items
  }, [data, filterProduct, filterRoute])

  // 按用户工段分组（按路线工段顺序，批次归到用户第一个工段下）
  const plannedByStage = useMemo(() => {
    if (!filteredItems.length) return []
    const myStages = new Set(stageNames)
    // 从 stage_config 提取路线工段顺序
    const routeOrder: string[] = []
    for (const item of filteredItems) {
      if (item.stage_config) {
        for (const sc of item.stage_config) {
          if (!routeOrder.includes(sc.stage_name)) routeOrder.push(sc.stage_name)
        }
      }
    }
    const myOrder = routeOrder.filter(s => myStages.has(s))
    // fallback: 如果 stage_config 为空，退回到字母序
    const sortedUserStages = myOrder.length > 0
      ? myOrder
      : [...myStages].sort((a, b) => a.localeCompare(b))

    const groups: Record<string, PlannedBatchItem[]> = {}
    for (const item of filteredItems) {
      let matched = false
      for (const sn of sortedUserStages) {
        if (item.stage_times[sn] != null) {
          groups[sn] ??= []
          groups[sn].push(item)
          matched = true
          break
        }
      }
      // 无 planned_start → stage_times 为空 → 归到第一个用户工段
      if (!matched && sortedUserStages.length > 0) {
        const fallback = sortedUserStages[0]
        groups[fallback] ??= []
        groups[fallback].push(item)
      }
    }
    return Object.entries(groups)
      .map(([stage, items]) => ({ stage, items }))
      .sort((a, b) => sortedUserStages.indexOf(a.stage) - sortedUserStages.indexOf(b.stage))
  }, [filteredItems, stageNames])

  if (isLoading) return <Spin><div style={{ minHeight: 60 }} /></Spin>

  if (!data?.items.length) return null

  const totalCount = plannedByStage.reduce((s, g) => s + g.items.length, 0)
  if (totalCount === 0 && (filterProduct || filterRoute)) {
    return (
      <div style={{ marginTop: 36 }}>
        <PlannedHeader
          plannedCount={0}
          filterProduct={filterProduct} setFilterProduct={setFilterProduct}
          filterRoute={filterRoute} setFilterRoute={setFilterRoute}
          filterOptions={filterOptions}
          isFetching={isFetching}
        />
        <div style={{ padding: '40px 20px', textAlign: 'center' }}>
          <Empty description="无匹配结果，请调整筛选条件" />
        </div>
      </div>
    )
  }
  if (totalCount === 0) return null

  return (
    <div style={{ marginTop: 36 }}>
      <PlannedHeader
        plannedCount={totalCount}
        filterProduct={filterProduct} setFilterProduct={setFilterProduct}
        filterRoute={filterRoute} setFilterRoute={setFilterRoute}
        filterOptions={filterOptions}
        isFetching={isFetching}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        {plannedByStage.map(group => {
          let cardIdx = 0
          return (
            <div key={group.stage}>
              {/* 工段头 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: stageColor(group.stage), flexShrink: 0,
                  opacity: 0.6,
                }} />
                <h3 style={{
                  margin: 0, fontSize: 15, fontWeight: 600, color: '#787671',
                  lineHeight: 1.3,
                }}>
                  计划 · {group.stage}
                </h3>
                <span style={{
                  fontSize: 11, color: '#a4a097',
                  background: '#f6f5f4', padding: '2px 8px', borderRadius: 8,
                }}>
                  {group.items.length} 项
                </span>
              </div>

              {/* 卡片网格 */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                gap: 12,
              }}>
                {group.items.map(item => (
                  <PlannedCard
                    key={item.batch_id}
                    item={item}
                    index={cardIdx++}
                    canSubmit={canSubmit}
                    onReceive={() => handleReceive(item)}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 头部筛选条 ──

function PlannedHeader({
  plannedCount, filterProduct, setFilterProduct, filterRoute, setFilterRoute,
  filterOptions, isFetching,
}: {
  plannedCount: number
  filterProduct: string | undefined; setFilterProduct: (v: string | undefined) => void
  filterRoute: string | undefined; setFilterRoute: (v: string | undefined) => void
  filterOptions: { products: { label: string; value: string }[]; routes: { label: string; value: string }[] }
  isFetching: boolean
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20,
      padding: '6px 0', flexWrap: 'wrap',
    }}>
      <span style={{ fontSize: 13, fontWeight: 500, color: '#787671', whiteSpace: 'nowrap' }}>
        计划批次 · {plannedCount} 项
        {isFetching && <span style={{ color: '#a4a097', marginLeft: 6, fontSize: 11 }}>刷新中</span>}
      </span>
      <div style={{ flex: 1, height: 1, background: '#ede9e4', minWidth: 20 }} />
      <Select
        allowClear
        placeholder="产品"
        style={{ width: 130 }}
        value={filterProduct}
        onChange={setFilterProduct}
        options={filterOptions.products}
        size="small"
        getPopupContainer={triggerNode => triggerNode.parentElement ?? document.body}
      />
      <Select
        allowClear
        placeholder="路线"
        style={{ width: 130 }}
        value={filterRoute}
        onChange={setFilterRoute}
        options={filterOptions.routes}
        size="small"
        getPopupContainer={triggerNode => triggerNode.parentElement ?? document.body}
      />
    </div>
  )
}
