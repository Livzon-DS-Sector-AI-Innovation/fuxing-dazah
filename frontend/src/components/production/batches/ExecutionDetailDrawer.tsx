'use client'

import { Descriptions, Drawer, Skeleton, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchBatchDetailClient } from '@/lib/api/production-client'
import type { NodeExecutionListItem } from '@/types/production'
import { FieldValueDisplay } from '../shared/FieldValueDisplay'

const TIMEOUT_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '监控中', color: 'processing' },
  processing: { label: '提醒处理中', color: 'warning' },
  sending: { label: '提醒处理中', color: 'warning' },
  retry: { label: '提醒重试中', color: 'warning' },
  notified: { label: '已提醒', color: 'warning' },
  monitoring: { label: '监控中', color: 'processing' },
  overdue: { label: '已超时', color: 'error' },
  not_monitored: { label: '未纳入监控', color: 'default' },
  sent: { label: '已提醒', color: 'warning' },
  resolved: { label: '已结束', color: 'success' },
  failed: { label: '提醒失败', color: 'warning' },
}

function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return '—'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = minutes / 60
  if (hours < 24) return `${hours.toFixed(1)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function timeoutStatusTag(status: string | null | undefined) {
  if (!status) return null
  const meta = TIMEOUT_STATUS_META[status]
  return <Tag color={meta?.color ?? 'default'}>{meta?.label ?? status}</Tag>
}

interface Props {
  item: NodeExecutionListItem
  onClose: () => void
}

export function ExecutionDetailDrawer({ item, onClose }: Props) {
  const { data: batchDetail, isLoading } = useQuery({
    queryKey: ['production-batch-detail', item.batch_id],
    queryFn: () => fetchBatchDetailClient(item.batch_id),
  })
  const execution = batchDetail?.executions.find(e => e.id === item.id)
  const monitorStatus = execution?.timeout_monitor_status ?? item.timeout_monitor_status
  const estimatedDurationSeconds =
    execution?.estimated_duration_seconds ?? item.estimated_duration_seconds
  const expectedFinishAt = execution?.expected_finish_at ?? item.expected_finish_at
  const timeoutNotifiedAt = execution?.timeout_notified_at ?? item.timeout_notified_at

  return (
    <Drawer
      title={`执行详情 · ${item.batch_no}`}
      open
      onClose={onClose}
      size={520}
      destroyOnHidden
    >
      {isLoading || !execution ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : (
        <>
          <Descriptions
            column={1}
            size="small"
            bordered
            items={[
              { key: 'node', label: '工序', children: `${execution.node_name ?? '—'}（第 ${execution.execution_seq} 次）` },
              { key: 'owner', label: '执行人', children: execution.owner_name ?? '—' },
              {
                key: 'time',
                label: '起止时间',
                children: `${formatDateTime(execution.started_at)} ~ ${
                  execution.finished_at ? formatDateTime(execution.finished_at) : '进行中'
                }`,
              },
              ...(monitorStatus
                ? [
                    {
                      key: 'timeout-status',
                      label: '监控状态',
                      children: timeoutStatusTag(monitorStatus),
                    },
                  ]
                : []),
              ...(estimatedDurationSeconds != null
                ? [
                    {
                      key: 'estimated-duration',
                      label: '参考时长（P80）',
                      children: formatDurationSeconds(estimatedDurationSeconds),
                    },
                  ]
                : []),
              ...(expectedFinishAt
                ? [
                    {
                      key: 'expected-finish',
                      label: '预计完成',
                      children: formatDateTime(expectedFinishAt),
                    },
                  ]
                : []),
              ...(timeoutNotifiedAt
                ? [
                    {
                      key: 'timeout-notified-at',
                      label: '提醒时间',
                      children: formatDateTime(timeoutNotifiedAt),
                    },
                  ]
                : []),
              {
                key: 'equipments',
                label: '设备',
                children: execution.equipments.length
                  ? execution.equipments.map(eq => (
                      <Tag key={eq.equipment_id}>
                        {eq.equipment_name}（{eq.equipment_no}）
                      </Tag>
                    ))
                  : '—',
              },
              ...(execution.is_deviation
                ? [
                    {
                      key: 'deviation',
                      label: '偏离原因',
                      children: execution.deviation_reason ?? '—',
                    },
                  ]
                : []),
            ]}
          />
          {execution.field_values.length > 0 && (
            <Descriptions
              title="字段数据"
              column={1}
              size="small"
              bordered
              style={{ marginTop: 16 }}
              items={execution.field_values.map(v => ({
                key: v.field_key,
                label: `${v.field_label}${v.phase === 'start' ? '（开始）' : '（结束）'}`,
                children: <FieldValueDisplay value={v} />,
              }))}
            />
          )}
        </>
      )}
    </Drawer>
  )
}
