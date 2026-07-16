'use client'

import { useState } from 'react'
import { App, Button, Drawer, Popconfirm, Skeleton, Space, Tag } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelBatch, completeBatch, abortExecution } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchTraceClient,
} from '@/lib/api/production-client'
import type { Execution } from '@/types/production'
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
        </>
      )}
    </Drawer>
  )
}
