'use client'

import { useState } from 'react'
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

interface Props {
  batchId: string
  canSubmit: boolean
  onClose: () => void
  // Task 8/9 接入：
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
        detail && (
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
            {detail.status === 'in_progress' && (
              <Popconfirm
                title="确认批次完成？"
                onConfirm={() => runAction(() => completeBatch(currentId), '批次已完成')}
              >
                <Button>完成批次</Button>
              </Popconfirm>
            )}
            {detail.status !== 'completed' && detail.status !== 'cancelled' && (
              <Popconfirm
                title="报废该批次？不可恢复"
                onConfirm={() => runAction(() => cancelBatch(currentId), '批次已报废')}
              >
                <Button danger>报废</Button>
              </Popconfirm>
            )}
          </Space>
        )
      }
    >
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <>
          {trace && trace.batches.length > 1 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>批次溯源</div>
              <TraceGraph
                trace={trace}
                currentBatchId={currentId}
                onBatchClick={id => setCurrentId(id)}
              />
            </div>
          )}
          <div style={{ fontWeight: 600, marginBottom: 8 }}>工序执行时间线</div>
          <ExecutionTimeline
            executions={detail?.executions ?? []}
            canSubmit={canSubmit && detail?.status !== 'cancelled'}
            onComplete={e => detail && onCompleteExecution?.(e, detail.route_id)}
            onAbort={e =>
              runAction(() => abortExecution(e.id), '已中止')
            }
          />
          {((outputsData?.length ?? 0) > 0 || (consumptionsData?.length ?? 0) > 0) && (
            <>
              <div style={{ fontWeight: 600, margin: '16px 0 8px' }}>中间体台账</div>
              {(outputsData?.length ?? 0) > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4, color: '#555' }}>产出记录</div>
                  <Table<IntermediateOutput>
                    size="small"
                    rowKey="id"
                    dataSource={outputsData}
                    pagination={false}
                    columns={[
                      { title: '中间体', dataIndex: 'intermediate_type_name', width: 140,
                        render: (v, r) => (
                          <Space size={4}>
                            <span>{v || '-'}</span>
                            {r.is_product && <Tag color="green" style={{ fontSize: 11 }}>成品</Tag>}
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
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4, color: '#555' }}>消耗记录</div>
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
            </>
          )}
        </>
      )}
    </Drawer>
  )
}
