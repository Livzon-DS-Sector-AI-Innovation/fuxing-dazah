'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Select, Modal, Descriptions, Empty, Spin, App } from 'antd'
import {
  ClockCircleOutlined, PlayCircleOutlined, CheckCircleOutlined,
  InboxOutlined, MergeCellsOutlined, SettingOutlined,
} from '@ant-design/icons'
import { useState, useMemo, useRef } from 'react'
import { fetchWorkbench, completeBatch, fetchBatchOutputs, fetchBatchConsumptions } from '@/actions/production'
import { fetchBatchDetailClient } from '@/lib/api/production-client'
import { stageColor } from '@/components/production/shared/stageColor'
import type { WorkbenchItem, Execution } from '@/types/production'
import { usePermission } from '@/hooks/usePermission'
import { ReceiveModal } from './ReceiveModal'
import { AssigneeConfig } from './AssigneeConfig'
import { StartExecutionModal } from '../batches/StartExecutionModal'
import { CompleteExecutionModal } from '../batches/CompleteExecutionModal'

// ── 常量 ──

const STATUS_CFG: Record<string, { label: string; color: string; bg: string; borderColor: string; icon: React.ReactNode }> = {
  pending_receive: { label: '待接收', color: '#dd5b00', bg: '#fff7e6', borderColor: '#dd5b00', icon: <InboxOutlined /> },
  pending_start: { label: '待开始', color: '#0075de', bg: '#e8f4fd', borderColor: '#0075de', icon: <PlayCircleOutlined /> },
  pending_complete: { label: '进行中', color: '#1aae39', bg: '#e8f8e8', borderColor: '#1aae39', icon: <ClockCircleOutlined /> },
  ready_to_complete: { label: '待完成批次', color: '#7b3ff2', bg: '#f4edfc', borderColor: '#7b3ff2', icon: <CheckCircleOutlined /> },
}

// ── CSS 动画 ──

const ANIM_STYLES = `
@keyframes wb-card-in {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes wb-dot-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(86, 69, 212, 0.45); }
  50% { box-shadow: 0 0 0 8px rgba(86, 69, 212, 0); }
}
.wb-card { animation: wb-card-in 0.45s ease-out both; }
.wb-stage-dot { animation: wb-dot-pulse 2.2s ease-in-out infinite; }
`

// ── 可折叠区块 ──

function CollapsiblePanel({
  open, onToggle, label, count, icon, children,
}: {
  open: boolean; onToggle: () => void;
  label: string; count?: number;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginTop: 24 }}>
      <button
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, width: '100%',
          border: 'none', background: 'none', cursor: 'pointer',
          padding: '8px 0', fontSize: 13, fontWeight: 500, color: '#787671',
          transition: 'color 0.15s',
        }}
      >
        <span style={{
          display: 'inline-flex', transition: 'transform 0.2s',
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          fontSize: 10, color: '#a4a097',
        }}>▶</span>
        {icon}
        <span>{label}</span>
        {count != null && (
          <span style={{ fontSize: 12, color: '#a4a097', marginLeft: 4 }}>· {count}</span>
        )}
      </button>
      {open && <div style={{ paddingTop: 4 }}>{children}</div>}
    </div>
  )
}

// ── 批次卡片 ──

function BatchCard({
  item, canSubmit, index, role, onReceive, onStart, onComplete, onCompleteBatch,
}: {
  item: WorkbenchItem
  canSubmit: boolean
  index: number
  role: 'stage_owner' | 'node_owner'
  onReceive: () => void
  onStart: () => void
  onComplete: () => void
  onCompleteBatch: () => void
}) {
  const cfg = STATUS_CFG[item.type] ?? STATUS_CFG.pending_start
  const assignee = item.node_assignees?.[0]

  return (
    <div
      className="wb-card"
      style={{
        position: 'relative', overflow: 'hidden',
        padding: '18px 18px 18px 16px',
        borderRadius: 12,
        background: '#ffffff',
        border: '1px solid #ede9e4',
        borderLeft: `3px solid ${cfg.borderColor}`,
        display: 'flex', flexDirection: 'column', gap: 10,
        cursor: 'default',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        animationDelay: `${index * 60}ms`,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = '0 6px 20px rgba(0,0,0,0.07)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      {/* 头部：工段负责人→批次号+产品同行 / 工序负责人→批次号优先 */}
      {role === 'stage_owner' ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.3 }}>
                <span>{item.batch_no ?? '待创建批次'}</span>
                {(item.product_name || item.route_name) && (
                  <span style={{ color: '#37352f' }}>
                    {' '}·{' '}
                    {item.product_name || item.route_name}
                  </span>
                )}
              </div>
              {(item.product_name || item.route_version) && (
                <div style={{ fontSize: 13, color: '#787671', marginTop: 1 }}>
                  {item.product_name ? item.route_name : ''}
                  {item.route_version ? <span style={{ color: '#a4a097' }}> v{item.route_version}</span> : null}
                </div>
              )}
            </div>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '3px 10px', borderRadius: 6,
              fontSize: 12, fontWeight: 600, lineHeight: '18px',
              background: cfg.bg, color: cfg.color,
              whiteSpace: 'nowrap', flexShrink: 0,
            }}>
              {cfg.icon}
              {cfg.label}
            </span>
          </div>
        </>
      ) : (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
            <span style={{
              fontSize: 17, fontWeight: 600, color: '#1a1a1a',
              lineHeight: 1.3, wordBreak: 'break-all',
            }}>
              {item.batch_no ?? '待创建批次'}
            </span>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '3px 10px', borderRadius: 6,
              fontSize: 12, fontWeight: 600, lineHeight: '18px',
              background: cfg.bg, color: cfg.color,
              whiteSpace: 'nowrap', flexShrink: 0,
            }}>
              {cfg.icon}
              {cfg.label}
            </span>
          </div>

          {/* 产品 + 路线 */}
          {(item.product_name || item.route_name) && (
            <div style={{ fontSize: 13, color: '#787671', lineHeight: 1.4 }}>
              {item.product_name && <span>{item.product_name}</span>}
              {item.product_name && item.route_name && <span style={{ color: '#c8c4be' }}> · </span>}
              {item.route_name && <span>{item.route_name}</span>}
              {item.route_version ? <span style={{ color: '#a4a097' }}> v{item.route_version}</span> : null}
            </div>
          )}
        </>
      )}

      {/* 前序批次 */}
      {item.predecessor_batches.length > 0 && (
        <div style={{ fontSize: 12, color: '#a4a097', lineHeight: 1.4 }}>
          前序：{item.predecessor_batches.join('、')}
        </div>
      )}

      {/* 工序名 + 负责人 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 14, fontWeight: 500, color: '#37352f' }}>
          {item.node_name}
        </span>
        {item.type === 'pending_complete' && item.owner_name && (
          <span style={{
            fontSize: 11, color: '#5645d4',
            background: '#f4f0ff', padding: '2px 8px', borderRadius: 4,
          }}>
            {item.owner_name}
          </span>
        )}
      </div>

      {/* 默认负责人 */}
      {item.type !== 'pending_complete' && (
        <div style={{ fontSize: 11, color: '#b5b1a8' }}>
          负责人：{assignee?.name ?? assignee?.user_id?.slice(0, 8) ?? '未设置'}
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ marginTop: 2 }}>
        {item.type === 'pending_receive' && canSubmit && item.parent_batch_ids.length > 0 && (
          <button
            onClick={onReceive}
            style={{
              border: 'none', borderRadius: 8, cursor: 'pointer',
              padding: '7px 18px', fontSize: 13, fontWeight: 500,
              background: '#5645d4', color: '#ffffff',
              transition: 'background 0.15s, transform 0.1s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#4534b3' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#5645d4' }}
            onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.97)' }}
            onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)' }}
          >
            接收
          </button>
        )}
        {item.type === 'pending_start' && item.batch_id && (
          <button
            onClick={onStart}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              border: 'none', borderRadius: 8, cursor: 'pointer',
              padding: '7px 18px', fontSize: 13, fontWeight: 500,
              background: '#5645d4', color: '#ffffff',
              transition: 'background 0.15s, transform 0.1s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#4534b3' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#5645d4' }}
            onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.97)' }}
            onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)' }}
          >
            <PlayCircleOutlined style={{ fontSize: 14 }} />
            开始工序
          </button>
        )}
        {item.type === 'pending_complete' && (
          <button
            onClick={onComplete}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              border: 'none', borderRadius: 8, cursor: 'pointer',
              padding: '7px 18px', fontSize: 13, fontWeight: 500,
              background: '#1aae39', color: '#ffffff',
              transition: 'background 0.15s, transform 0.1s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#169435' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#1aae39' }}
            onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.97)' }}
            onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)' }}
          >
            <CheckCircleOutlined style={{ fontSize: 14 }} />
            结束工序
          </button>
        )}
        {item.type === 'ready_to_complete' && canSubmit && (
          <button
            onClick={onCompleteBatch}
            style={{
              border: 'none', borderRadius: 8, cursor: 'pointer',
              padding: '7px 18px', fontSize: 13, fontWeight: 500,
              background: '#7b3ff2', color: '#ffffff',
              transition: 'background 0.15s, transform 0.1s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#6a32d9' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#7b3ff2' }}
            onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.97)' }}
            onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)' }}
          >
            完成批次
          </button>
        )}
      </div>
    </div>
  )
}

// ── 主组件 ──

export function WorkbenchInner() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:batch:submit')
  const queryClient = useQueryClient()

  const [receiveItem, setReceiveItem] = useState<WorkbenchItem | null>(null)
  const [mergeOpen, setMergeOpen] = useState<{ nodeId: string; nodeName: string; candidates: WorkbenchItem[] } | null>(null)
  const [mergeParentIds, setMergeParentIds] = useState<string[]>([])
  const [recentDetail, setRecentDetail] = useState<{ batchId: string; execId: string } | null>(null)
  const [recentDetailData, setRecentDetailData] = useState<Execution | null>(null)
  const [recentOutputs, setRecentOutputs] = useState<any[]>([])
  const [recentConsumptions, setRecentConsumptions] = useState<any[]>([])
  const [startBatchId, setStartBatchId] = useState<string | null>(null)
  const [startNodeId, setStartNodeId] = useState<string | undefined>(undefined)
  const [completeExec, setCompleteExec] = useState<{ execution: Execution; routeId: string } | null>(null)
  const completeSuccessRef = useRef<(() => void) | null>(null)

  const [showConfig, setShowConfig] = useState(false)
  const [showRecent, setShowRecent] = useState(false)

  // 筛选状态
  const [filterProduct, setFilterProduct] = useState<string | undefined>(undefined)
  const [filterRoute, setFilterRoute] = useState<string | undefined>(undefined)
  const [filterStatus, setFilterStatus] = useState<string | undefined>(undefined)

  const { data, isLoading, error } = useQuery({
    queryKey: ['production-workbench'],
    queryFn: async () => {
      const r = await fetchWorkbench()
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data!
    },
    refetchInterval: 30_000,
  })

  const openRecentDetail = async (batchId: string, execId: string) => {
    setRecentDetail({ batchId, execId })
    try {
      const [detail, outputsR, consumptionsR] = await Promise.all([
        fetchBatchDetailClient(batchId),
        fetchBatchOutputs(batchId),
        fetchBatchConsumptions(batchId),
      ])
      const exec = detail.executions.find(e => e.id === execId) ?? null
      setRecentDetailData(exec)
      setRecentOutputs(outputsR.success ? (outputsR.data ?? []) : [])
      setRecentConsumptions(consumptionsR.success ? (consumptionsR.data ?? []) : [])
    } catch { setRecentDetailData(null) }
  }

  // 筛选选项（从全量数据提取，不受筛选影响）
  const filterOptions = useMemo(() => {
    if (!data?.items) return { products: [] as { label: string; value: string }[], routes: [] as { label: string; value: string }[] }
    const productSet = new Map<string, string>()
    const routeSet = new Map<string, string>()
    for (const item of data.items) {
      if (item.product_name && !productSet.has(item.product_name)) productSet.set(item.product_name, item.product_name)
      if (!routeSet.has(item.route_id)) routeSet.set(item.route_id, item.route_name)
    }
    return {
      products: [...productSet.values()].map(v => ({ label: v, value: v })),
      routes: [...routeSet.entries()].map(([id, name]) => ({ label: name, value: id })),
    }
  }, [data])

  const statusOptions = useMemo(() =>
    Object.entries(STATUS_CFG).map(([key, cfg]) => ({ label: cfg.label, value: key })),
  [])

  // 筛选后的 items
  const filteredItems = useMemo(() => {
    if (!data?.items) return []
    let items = data.items
    if (filterProduct) items = items.filter(i => i.product_name === filterProduct)
    if (filterRoute) items = items.filter(i => i.route_id === filterRoute)
    if (filterStatus) items = items.filter(i => i.type === filterStatus)
    return items
  }, [data, filterProduct, filterRoute, filterStatus])

  const stageGroups = useMemo(() => {
    if (!filteredItems.length) return []
    const priority: Record<string, number> = { ready_to_complete: 4, pending_complete: 3, pending_start: 2, pending_receive: 1 }
    const byStage: Record<string, Record<string, Record<string, WorkbenchItem>>> = {}
    for (const item of filteredItems) {
      const stage = item.stage_name ?? '未分组'
      const batchKey = item.batch_id ?? item.parent_batch_ids.join('_')
      const routeKey = item.route_id
      byStage[stage] ??= {}
      byStage[stage][routeKey] ??= {}
      const existing = byStage[stage][routeKey][batchKey]
      if (!existing || priority[item.type] > priority[existing.type]) {
        byStage[stage][routeKey][batchKey] = item
      }
    }
    return Object.entries(byStage)
      .map(([stage, routes]) => ({
        stage,
        color: stageColor(stage),
        routes: Object.entries(routes).map(([routeId, batches]) => ({
          routeId,
          routeName: Object.values(batches)[0].route_name,
          routeVersion: Object.values(batches)[0].route_version,
          productName: Object.values(batches)[0].product_name,
          items: Object.values(batches),
        })),
      }))
      .sort((a, b) => a.stage.localeCompare(b.stage))
  }, [filteredItems])

  const openCompleteModal = async (item: WorkbenchItem, onSuccess?: () => void) => {
    if (!item.batch_id || !item.execution_id) return
    try {
      const detail = await fetchBatchDetailClient(item.batch_id)
      const exec = detail.executions.find(e => e.id === item.execution_id)
      if (exec) {
        setCompleteExec({ execution: exec, routeId: item.route_id })
        completeSuccessRef.current = onSuccess ?? null
      } else message.error('未找到执行记录')
    } catch { message.error('获取执行详情失败') }
  }

  if (error) return (
    <div style={{ textAlign: 'center', padding: 80 }}>
      <Empty description="加载失败，请刷新重试" />
    </div>
  )

  const stageOwner = data?.role === 'stage_owner'
  const hasAssignedRoutes = (data?.assigned_routes?.length ?? 0) > 0
  const totalCount = stageGroups.reduce((s, g) => s + g.routes.reduce((s2, r) => s2 + r.items.length, 0), 0)

  return (
    <>
      <style>{ANIM_STYLES}</style>

      {/* ── 页面头部 ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24,
      }}>
        <h2 style={{
          margin: 0, fontSize: 22, fontWeight: 600, color: '#1a1a1a',
          lineHeight: 1.3,
        }}>
          工作台
        </h2>
        <span style={{
          display: 'inline-block', padding: '3px 10px', borderRadius: 20,
          fontSize: 11, fontWeight: 600, color: '#5645d4',
          background: '#f4f0ff',
        }}>
          {stageOwner ? '工段负责人' : '工序负责人'}
        </span>
        <span style={{ fontSize: 14, color: '#787671' }}>
          {stageOwner ? '管理工段任务与工序负责人分配' : '我的工序待办'}
        </span>
      </div>

      {isLoading ? (
        <Spin><div style={{ minHeight: 200 }} /></Spin>
      ) : (
        <>
          {/* ── 工序负责人配置 ── */}
          {stageOwner && hasAssignedRoutes && (
            <CollapsiblePanel
              open={showConfig}
              onToggle={() => setShowConfig(v => !v)}
              label="工序负责人配置"
              icon={<SettingOutlined style={{ fontSize: 14 }} />}
            >
              <AssigneeConfig
                routes={data!.assigned_routes}
                onChanged={() => queryClient.invalidateQueries({ queryKey: ['production-workbench'] })}
              />
            </CollapsiblePanel>
          )}

          {/* ── 空状态 ── */}
          {!hasAssignedRoutes ? (
            <div style={{ padding: '60px 20px', textAlign: 'center' }}>
              <Empty description="暂无待办事项，也未分配负责的工段或工序" />
            </div>
          ) : (
            <>
              {/* ── 总览条 + 筛选 ── */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, marginBottom: 28,
                padding: '10px 0', flexWrap: 'wrap',
              }}>
                <span style={{ fontSize: 14, fontWeight: 500, color: '#37352f', whiteSpace: 'nowrap' }}>
                  共 {stageGroups.length} 个工段 · {totalCount} 项待办
                </span>
                <div style={{ flex: 1, height: 1, background: '#ede9e4', minWidth: 20 }} />
                <Select
                  allowClear
                  placeholder="产品"
                  style={{ width: 150 }}
                  value={filterProduct}
                  onChange={setFilterProduct}
                  options={filterOptions.products}
                  size="small"
                  getPopupContainer={triggerNode => triggerNode.parentElement ?? document.body}
                />
                <Select
                  allowClear
                  placeholder="路线"
                  style={{ width: 150 }}
                  value={filterRoute}
                  onChange={setFilterRoute}
                  options={filterOptions.routes}
                  size="small"
                  getPopupContainer={triggerNode => triggerNode.parentElement ?? document.body}
                />
                <Select
                  allowClear
                  placeholder="状态"
                  style={{ width: 110 }}
                  value={filterStatus}
                  onChange={setFilterStatus}
                  options={statusOptions}
                  size="small"
                  getPopupContainer={triggerNode => triggerNode.parentElement ?? document.body}
                />
              </div>

              {stageGroups.length === 0 && (filterProduct || filterRoute || filterStatus) ? (
                <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                  <Empty description="无匹配结果，请调整筛选条件" />
                </div>
              ) : stageGroups.length === 0 ? (
                <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                  <Empty
                    image={<InboxOutlined style={{ fontSize: 48, color: '#b5b1a8' }} />}
                    description="暂无待办事项"
                  />
                </div>
              ) : (
                <>
                  {/* ── 卡片区域 ── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 36 }}>
                {stageGroups.map(group => {
                  const receiveItems = group.routes.flatMap(r => r.items)
                    .filter(it => it.type === 'pending_receive' && it.batch_id)
                  const byNode: Record<string, WorkbenchItem[]> = {}
                  for (const it of receiveItems) {
                    byNode[it.node_id] ??= []
                    byNode[it.node_id]!.push(it)
                  }
                  const mergeGroups = Object.entries(byNode).filter(([, items]) => items.length >= 2)

                  let cardIdx = 0
                  return (
                    <div key={group.stage}>
                      {/* 工段头 */}
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
                      }}>
                        <span
                          className="wb-stage-dot"
                          style={{
                            width: 10, height: 10, borderRadius: '50%',
                            background: group.color, flexShrink: 0,
                          }}
                        />
                        <h3 style={{
                          margin: 0, fontSize: 16, fontWeight: 600, color: '#1a1a1a',
                          lineHeight: 1.3,
                        }}>
                          {group.stage}
                        </h3>
                        <span style={{
                          fontSize: 12, color: '#a4a097',
                          background: '#f6f5f4', padding: '2px 10px', borderRadius: 10,
                        }}>
                          {group.routes.reduce((s, r) => s + r.items.length, 0)} 项
                        </span>

                        {mergeGroups.map(([nodeId, items]) => (
                          <Button
                            key={nodeId}
                            size="small"
                            icon={<MergeCellsOutlined />}
                            style={{ marginLeft: 4, borderRadius: 6 }}
                            onClick={() => {
                              setMergeOpen({ nodeId, nodeName: items[0].node_name || '', candidates: items })
                              setMergeParentIds([])
                            }}
                          >
                            合并接收
                          </Button>
                        ))}
                      </div>

                      {/* 卡片网格 */}
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
                        gap: 14,
                      }}>
                        {group.routes.map(route =>
                          route.items.map(item => {
                            const idx = cardIdx++
                            return (
                              <BatchCard
                                key={`${item.node_id}-${item.batch_id ?? item.parent_batch_ids.join('-')}`}
                                item={item}
                                canSubmit={canSubmit}
                                index={idx}
                                role={data!.role}
                                onReceive={() => setReceiveItem(item)}
                                onStart={() => { setStartBatchId(item.batch_id!); setStartNodeId(item.node_id) }}
                                onComplete={() => openCompleteModal(item)}
                                onCompleteBatch={async () => {
                                  if (!item.batch_id) return
                                  const r = await completeBatch(item.batch_id)
                                  if (r.success) {
                                    message.success('批次已完成')
                                    queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
                                  } else {
                                    message.error(r.error ?? '完成批次失败')
                                  }
                                }}
                              />
                            )
                          }),
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {/* ── 最近完成 ── */}
          {data?.recent_completed && data.recent_completed.length > 0 && (
            <CollapsiblePanel
              open={showRecent}
              onToggle={() => setShowRecent(v => !v)}
              label="最近完成"
              count={data.recent_completed.length}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {data.recent_completed.map((rc, i) => (
                  <span
                    key={rc.execution_id ?? i}
                    onClick={() => rc.batch_id && rc.execution_id && openRecentDetail(rc.batch_id, rc.execution_id)}
                    title={`${rc.stage_name} · ${rc.node_name}${rc.owner_name ? ` · ${rc.owner_name}` : ''}${rc.finished_at ? ` · ${new Date(rc.finished_at).toLocaleDateString('zh-CN')}` : ''}`}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      padding: '2px 10px', borderRadius: 4,
                      fontSize: 12, fontWeight: 500,
                      background: '#fafaf8', color: '#37352f',
                      border: '1px solid #ede9e4',
                      cursor: 'pointer', transition: 'background 0.15s, border-color 0.15s',
                      whiteSpace: 'nowrap',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.background = '#f4f0ff'
                      e.currentTarget.style.borderColor = '#d6b6f6'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.background = '#fafaf8'
                      e.currentTarget.style.borderColor = '#ede9e4'
                    }}
                  >
                    {rc.batch_no}
                    <span style={{ color: '#a4a097', fontWeight: 400 }}>{rc.node_name}</span>
                  </span>
                ))}
              </div>
            </CollapsiblePanel>
          )}
        </>
      )}
      </>
    )}

      {/* ═══════ 弹窗 ═══════ */}

      {receiveItem && (
        <ReceiveModal item={receiveItem} onClose={() => {
          setReceiveItem(null)
          queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
          queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        }} />
      )}

      {/* ── 合并接收弹窗 ── */}
      {mergeOpen && (
        <Modal
          title={
            <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
              合并接收 · {mergeOpen.nodeName}
            </span>
          }
          open
          onOk={() => {
            if (mergeParentIds.length < 2) { message.warning('请至少选择 2 个父批次'); return }
            const selected = mergeOpen.candidates.filter(c => c.batch_id && mergeParentIds.includes(c.batch_id))
            const first = selected[0]
            const combined: WorkbenchItem = {
              ...first,
              batch_id: null,
              batch_no: null,
              parent_batch_ids: selected.flatMap(c => c.parent_batch_ids),
              predecessor_batches: selected.map(c => c.batch_no).filter(Boolean) as string[],
            }
            setMergeOpen(null)
            setReceiveItem(combined)
          }}
          onCancel={() => setMergeOpen(null)}
          okText="选择并接收"
          cancelText="取消"
          width={480}
          styles={{
            body: { padding: '20px 24px' },
          }}
        >
          <div style={{ marginBottom: 8, fontSize: 13, color: '#787671' }}>
            选择要合并接收的父批次（至少 2 个）
          </div>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            placeholder="选择父批次"
            value={mergeParentIds}
            onChange={v => setMergeParentIds(v)}
            options={mergeOpen.candidates
              .filter(c => c.batch_id)
              .map(c => ({ value: c.batch_id!, label: c.batch_no }))}
          />
        </Modal>
      )}

      {startBatchId && (
        <StartExecutionModal
          batchId={startBatchId}
          defaultNodeId={startNodeId}
          onClose={() => {
            setStartBatchId(null)
            setStartNodeId(undefined)
            queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
          }}
        />
      )}

      {completeExec && (
        <CompleteExecutionModal
          execution={completeExec.execution}
          routeId={completeExec.routeId}
          onSuccess={completeSuccessRef.current ?? undefined}
          onClose={() => {
            setCompleteExec(null)
            queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
          }}
        />
      )}

      {/* ── 工序详情弹窗 ── */}
      {recentDetail && (
        <Modal
          title={
            <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
              工序详情
            </span>
          }
          open
          width={640}
          onCancel={() => { setRecentDetail(null); setRecentDetailData(null) }}
          footer={
            <button
              onClick={() => { setRecentDetail(null); setRecentDetailData(null) }}
              style={{
                border: '1px solid #c8c4be', borderRadius: 8, cursor: 'pointer',
                padding: '7px 20px', fontSize: 13, fontWeight: 500,
                background: '#ffffff', color: '#37352f',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#f6f5f4' }}
              onMouseLeave={e => { e.currentTarget.style.background = '#ffffff' }}
            >
              关闭
            </button>
          }
          styles={{ body: { padding: '16px 24px' } }}
        >
          {!recentDetailData ? (
            <Spin><div style={{ minHeight: 120 }} /></Spin>
          ) : (
            <>
              <Descriptions
                column={2}
                size="small"
                bordered
                style={{ marginBottom: 20 }}
                styles={{
                  label: {
                    fontSize: 12, fontWeight: 500, color: '#787671',
                    background: '#fafaf8', padding: '8px 12px',
                  },
                  content: {
                    fontSize: 13, color: '#1a1a1a', padding: '8px 12px',
                  },
                }}
              >
                <Descriptions.Item label="工序">{recentDetailData.node_name}</Descriptions.Item>
                <Descriptions.Item label="负责人">{recentDetailData.owner_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="开始时间">
                  {recentDetailData.started_at ? new Date(recentDetailData.started_at).toLocaleString('zh-CN') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="完成时间">
                  {recentDetailData.finished_at ? new Date(recentDetailData.finished_at).toLocaleString('zh-CN') : '-'}
                </Descriptions.Item>
              </Descriptions>

              {recentDetailData.field_values.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: '#37352f',
                    marginBottom: 10,
                  }}>
                    工序数据
                  </div>
                  {(['start', 'end'] as const).map(phase => {
                    const fvs = recentDetailData.field_values.filter(f => f.phase === phase)
                    if (!fvs.length) return null
                    return (
                      <div key={phase} style={{ marginBottom: 10 }}>
                        <span style={{
                          display: 'inline-block', padding: '2px 10px', borderRadius: 4,
                          fontSize: 11, fontWeight: 600, marginBottom: 6,
                          background: phase === 'start' ? '#e8f4fd' : '#f4edfc',
                          color: phase === 'start' ? '#0075de' : '#7b3ff2',
                        }}>
                          {phase === 'start' ? '开始阶段' : '结束阶段'}
                        </span>
                        <Descriptions
                          column={2}
                          size="small"
                          styles={{
                            label: {
                              fontSize: 12, fontWeight: 500, color: '#787671',
                              background: '#fafaf8', padding: '6px 10px',
                            },
                            content: {
                              fontSize: 13, color: '#1a1a1a', padding: '6px 10px',
                            },
                          }}
                        >
                          {fvs.map(fv => (
                            <Descriptions.Item key={fv.field_key} label={fv.field_label || fv.field_key}>
                              {fv.value_text ?? fv.value_numeric ?? (fv.value_bool ? '是' : fv.value_bool === false ? '否' : '-')}
                              {fv.unit ? ` ${fv.unit}` : ''}
                              {fv.is_abnormal && (
                                <span style={{
                                  display: 'inline-block', marginLeft: 6, padding: '1px 6px',
                                  borderRadius: 3, fontSize: 10, fontWeight: 600,
                                  background: '#ffe8e8', color: '#e03131',
                                }}>
                                  异常
                                </span>
                              )}
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      </div>
                    )
                  })}
                </div>
              )}

              {recentOutputs.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: '#37352f',
                    marginBottom: 8,
                  }}>
                    中间体产出
                  </div>
                  <div style={{
                    display: 'flex', flexDirection: 'column', gap: 4,
                    padding: '10px 14px', borderRadius: 8,
                    background: '#fafaf8', border: '1px solid #ede9e4',
                  }}>
                    {recentOutputs.map((o: any, i: number) => (
                      <div key={i} style={{ fontSize: 13, color: '#37352f', padding: '3px 0' }}>
                        <span style={{ fontWeight: 500 }}>{o.intermediate_type_name ?? '-'}</span>
                        <span style={{ color: '#a4a097' }}> · </span>
                        {o.intermediate_batch_no || o.batch_no}
                        <span style={{ color: '#a4a097' }}> · </span>
                        <span style={{ fontWeight: 500 }}>{o.quantity}</span>{o.unit}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {recentConsumptions.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{
                    fontSize: 13, fontWeight: 600, color: '#37352f',
                    marginBottom: 8,
                  }}>
                    中间体消耗
                  </div>
                  <div style={{
                    display: 'flex', flexDirection: 'column', gap: 4,
                    padding: '10px 14px', borderRadius: 8,
                    background: '#fafaf8', border: '1px solid #ede9e4',
                  }}>
                    {recentConsumptions.map((c: any, i: number) => (
                      <div key={i} style={{ fontSize: 13, color: '#37352f', padding: '3px 0' }}>
                        <span style={{ fontWeight: 500 }}>{c.intermediate_type_name ?? '-'}</span>
                        <span style={{ color: '#a4a097' }}> · </span>
                        {c.output_batch_no ?? '-'}
                        <span style={{ color: '#a4a097' }}> · </span>
                        <span style={{ fontWeight: 500 }}>{c.quantity}</span>{c.unit}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </Modal>
      )}
    </>
  )
}
