'use client'

import { useState, type ReactNode } from 'react'
import { App, Button, Drawer, Popconfirm, Skeleton, Space, Table, Tag } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelBatch, completeBatch, abortExecution } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchTraceClient,
} from '@/lib/api/production-client'
import { fetchBatchOutputs, fetchBatchConsumptions } from '@/actions/production'
import type { IntermediateConsumption, IntermediateOutput, Execution } from '@/types/production'
import { BATCH_STATUS_META } from './BatchTable'
import { TraceGraph } from './TraceGraph'
import { ExecutionTimeline } from './ExecutionTimeline'

// ── 设计令牌 ──────────────────────────────────────────────
const T = {
  accent: '#0D7377',
  border: '#E5E7EB',
  textSecondary: '#6B7280',
} as const

// ── 分段标题：左侧青蓝色强调条 ──────────────────────────────
function Section({
  title,
  extra,
  children,
}: {
  title: string
  extra?: ReactNode
  children: ReactNode
}) {
  return (
    <section style={{ marginBottom: 24 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 12,
        }}
      >
        <span
          style={{
            display: 'inline-block',
            width: 3,
            height: 18,
            borderRadius: 2,
            background: T.accent,
            flexShrink: 0,
          }}
        />
        <span style={{ fontWeight: 600, fontSize: 14 }}>{title}</span>
        {extra && (
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center' }}>
            {extra}
          </span>
        )}
      </div>
      {children}
    </section>
  )
}

interface Props {
  batchId: string
  canSubmit: boolean
  onClose: () => void
  onStartExecution?: (batchId: string) => void
  onCompleteExecution?: (execution: Execution, routeId: string) => void
  onDerive?: (batchId: string) => void
  onMerge?: (batchId: string) => void
}

export function BatchDetailDrawer({
  batchId,
  canSubmit,
  onClose,
  onStartExecution,
  onCompleteExecution,
  onDerive,
  onMerge,
}: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [currentId, setCurrentId] = useState(batchId)

  const { data: detail, isLoading } = useQuery({
    queryKey: ['production-batch-detail', currentId],
    queryFn: () => fetchBatchDetailClient(currentId),
  })
  const { data: trace } = useQuery({
    queryKey: ['production-trace', currentId],
    queryFn: () => fetchTraceClient(currentId),
  })
  const { data: outputsData } = useQuery({
    queryKey: ['production-batch-outputs', currentId],
    queryFn: async () => {
      const r = await fetchBatchOutputs(currentId)
      return r.success ? r.data ?? [] : []
    },
  })
  const { data: consumptionsData } = useQuery({
    queryKey: ['production-batch-consumptions', currentId],
    queryFn: async () => {
      const r = await fetchBatchConsumptions(currentId)
      return r.success ? r.data ?? [] : []
    },
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['production-batch-detail', currentId] })
    queryClient.invalidateQueries({ queryKey: ['production-trace', currentId] })
    queryClient.invalidateQueries({ queryKey: ['production-batches'] })
  }

  const runAction = async (
    fn: () => Promise<{ success: boolean; error?: string }>,
    ok: string,
  ) => {
    const result = await fn()
    if (result.success) {
      message.success(ok)
      invalidate()
    } else {
      message.error(result.error ?? '操作失败')
    }
  }

  const meta = detail ? BATCH_STATUS_META[detail.status] : null
  const hasMaterials = (outputsData?.length ?? 0) > 0 || (consumptionsData?.length ?? 0) > 0

  return (
    <Drawer
      open
      onClose={onClose}
      size="80%"
      destroyOnHidden
      title={
        <Space>
          <span>{detail?.batch_no ?? '批次详情'}</span>
          {meta && <Tag color={meta.color}>{meta.label}</Tag>}
        </Space>
      }
      extra={
        canSubmit &&
        detail &&
        detail.status !== 'completed' &&
        detail.status !== 'cancelled' && (
          <Popconfirm
            title="报废该批次？不可恢复"
            onConfirm={() => runAction(() => cancelBatch(currentId), '批次已报废')}
          >
            <Button danger>报废</Button>
          </Popconfirm>
        )
      }
    >
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <>
          {/* ── 批次溯源 ──────────────────────────── */}
          {trace && trace.batches.length > 1 && (
            <Section title="批次溯源">
              <TraceGraph
                trace={trace}
                currentBatchId={currentId}
                onBatchClick={id => setCurrentId(id)}
              />
            </Section>
          )}

          {/* ── 工序执行时间线 ────────────────────── */}
          <Section
            title="工序执行时间线"
            extra={
              canSubmit && detail?.status === 'in_progress' && (
                <Popconfirm
                  title="确认批次完成？"
                  onConfirm={() => runAction(() => completeBatch(currentId), '批次已完成')}
                >
                  <Button type="primary">完成批次</Button>
                </Popconfirm>
              )
            }
          >
            <ExecutionTimeline
              executions={detail?.executions ?? []}
              canSubmit={canSubmit && detail?.status !== 'cancelled'}
              onComplete={e => detail && onCompleteExecution?.(e, detail.route_id)}
              onAbort={e => runAction(() => abortExecution(e.id), '已中止')}
            />

            {/* 时间线操作栏 */}
            {canSubmit && detail && (
              <div
                style={{
                  marginTop: 16,
                  paddingTop: 16,
                  borderTop: `1px solid ${T.border}`,
                }}
              >
                <Space>
                  {(detail.status === 'pending' || detail.status === 'in_progress') &&
                    onStartExecution && (
                      <Button type="primary" onClick={() => onStartExecution(currentId)}>
                        开始工序
                      </Button>
                    )}
                  {(detail.status === 'in_progress' || detail.status === 'completed') && (
                    <>
                      {onDerive && <Button onClick={() => onDerive(currentId)}>分裂</Button>}
                      {onMerge && <Button onClick={() => onMerge(currentId)}>合并</Button>}
                    </>
                  )}
                </Space>
              </div>
            )}
          </Section>

          {/* ── 物料记录 ──────────────────────────── */}
          {hasMaterials && (
            <Section title="物料记录">
              {(outputsData?.length ?? 0) > 0 && (
                <div style={{ marginBottom: consumptionsData?.length ? 16 : 0 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      marginBottom: 8,
                      color: T.textSecondary,
                    }}
                  >
                    产出记录
                  </div>
                  <Table<IntermediateOutput>
                    size="small"
                    rowKey="id"
                    dataSource={outputsData}
                    pagination={false}
                    columns={[
                      {
                        title: '产物',
                        dataIndex: 'intermediate_type_name',
                        width: 140,
                        render: (v, r) => (
                          <Space size={4}>
                            <span>{v || '-'}</span>
                            {r.is_product && (
                              <Tag color="green" style={{ fontSize: 11 }}>
                                成品
                              </Tag>
                            )}
                          </Space>
                        ),
                      },
                      { title: '批号', dataIndex: 'intermediate_batch_no', width: 120, render: v => v || '-' },
                      { title: '数量', width: 100, render: (_, r) => `${r.quantity} ${r.unit}` },
                      { title: '产出工序', dataIndex: 'node_name', width: 120, render: v => v || '-' },
                      { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v || '-' },
                    ]}
                  />
                </div>
              )}
              {(consumptionsData?.length ?? 0) > 0 && (
                <div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      marginBottom: 8,
                      color: T.textSecondary,
                    }}
                  >
                    消耗记录
                  </div>
                  <Table<IntermediateConsumption>
                    size="small"
                    rowKey="id"
                    dataSource={consumptionsData}
                    pagination={false}
                    columns={[
                      { title: '中间体', dataIndex: 'intermediate_type_name', width: 120, render: v => v || '-' },
                      { title: '来源批号', dataIndex: 'output_batch_no', width: 120, render: v => v || '-' },
                      { title: '数量', width: 100, render: (_, r) => `${r.quantity} ${r.unit}` },
                      { title: '消耗工序', dataIndex: 'node_name', width: 120, render: v => v || '-' },
                      { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v || '-' },
                    ]}
                  />
                </div>
              )}
            </Section>
          )}
        </>
      )}
    </Drawer>
  )
}
