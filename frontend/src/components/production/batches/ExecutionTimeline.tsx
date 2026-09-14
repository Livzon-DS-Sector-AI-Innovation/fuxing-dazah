'use client'

import { Button, Descriptions, Empty, Popconfirm, Space, Tag, Timeline } from 'antd'
import { FieldValueDisplay } from '../shared/FieldValueDisplay'
import type { Execution, FieldValue } from '@/types/production'

const EXEC_STATUS_META: Record<string, { color: string; label: string; dotColor: string }> = {
  in_progress: { color: 'blue', label: '进行中', dotColor: 'blue' },
  completed: { color: 'green', label: '已完成', dotColor: 'green' },
  aborted: { color: 'default', label: '已中止', dotColor: 'gray' },
}

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

function FieldValuesBlock({ values }: { values: FieldValue[] }) {
  const startVals = values.filter(v => v.phase === 'start')
  const endVals = values.filter(v => v.phase === 'end')

  return (
    <>
      {startVals.length > 0 && (
        <Descriptions
          title="开始阶段"
          size="small"
          column={2}
          style={{ marginTop: 8 }}
          items={startVals.map(v => ({
            key: v.field_key,
            label: v.field_label,
            children: <FieldValueDisplay value={v} />,
          }))}
        />
      )}
      {endVals.length > 0 && (
        <Descriptions
          title="结束阶段"
          size="small"
          column={2}
          style={{ marginTop: 8 }}
          items={endVals.map(v => ({
            key: v.field_key,
            label: v.field_label,
            children: <FieldValueDisplay value={v} />,
          }))}
        />
      )}
    </>
  )
}

interface Props {
  executions: Execution[]
  canSubmit: boolean
  canAmend?: boolean
  onComplete: (execution: Execution) => void
  onAbort: (execution: Execution) => void
  onBackfill?: (execution: Execution) => void
  onAmend?: (execution: Execution) => void
}

export function ExecutionTimeline({
  executions,
  canSubmit,
  canAmend = false,
  onComplete,
  onAbort,
  onBackfill,
  onAmend,
}: Props) {
  if (!executions.length) return <Empty description="该批次还没有工序执行记录" />

  return (
    <Timeline
      items={executions.map(e => {
        const meta = EXEC_STATUS_META[e.status]
        return {
          key: e.id,
          color: meta?.dotColor ?? 'gray',
          content: (
            <div
              style={{
                background: '#fff',
                border: '1px solid #e5e3df',
                borderRadius: 12,
                padding: 12,
                marginBottom: 4,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 600 }}>{e.node_name ?? '工序'}</span>
                {e.execution_seq > 1 && <Tag color="orange">第 {e.execution_seq} 次</Tag>}
                <Tag color={meta?.color}>{meta?.label ?? e.status}</Tag>
                {e.timeout_monitor_status && (
                  <Tag color={TIMEOUT_STATUS_META[e.timeout_monitor_status]?.color ?? 'default'}>
                    {TIMEOUT_STATUS_META[e.timeout_monitor_status]?.label ?? e.timeout_monitor_status}
                  </Tag>
                )}
                {e.is_deviation && <Tag color="warning">偏离</Tag>}
                <div style={{ flex: 1 }} />
                {canSubmit && e.status === 'in_progress' && (
                  <Space size={4}>
                    <Button size="small" type="primary" onClick={() => onComplete(e)}>
                      结束工序
                    </Button>
                    <Popconfirm title="中止本次执行？" onConfirm={() => onAbort(e)}>
                      <Button size="small" danger>
                        中止
                      </Button>
                    </Popconfirm>
                  </Space>
                )}
                {e.can_backfill && onBackfill && (
                  <Button size="small" onClick={() => onBackfill(e)}>
                    补录字段
                  </Button>
                )}
                {canAmend && (e.status === 'completed' || e.status === 'aborted') && onAmend && (
                  <Button size="small" onClick={() => onAmend(e)}>
                    修改数据
                  </Button>
                )}
              </div>
              {e.is_deviation && e.deviation_reason && (
                <div
                  style={{
                    background: '#fff8e6',
                    border: '1px solid #ffe58f',
                    borderRadius: 8,
                    padding: '4px 8px',
                    margin: '8px 0',
                    fontSize: 12,
                  }}
                >
                  偏离原因：{e.deviation_reason}
                </div>
              )}
              {(e.missing_required_fields?.length ?? 0) > 0 && (
                <div
                  style={{
                    background: '#fff8e6',
                    border: '1px solid #ffe58f',
                    borderRadius: 8,
                    padding: '4px 8px',
                    margin: '8px 0',
                    fontSize: 12,
                    color: '#ad6800',
                  }}
                >
                  待补录：{e.missing_required_fields!.map(f => f.field_label).join('、')}
                </div>
              )}
              <div style={{ fontSize: 12, color: '#787671', marginTop: 4 }}>
                执行人 {e.owner_name ?? '—'} · 开始{' '}
                {formatDateTime(e.started_at)}
                {e.finished_at &&
                  ` · 结束 ${formatDateTime(e.finished_at)}`}
              </div>
              {(e.estimated_duration_seconds != null || e.expected_finish_at) && (
                <div style={{ fontSize: 12, color: '#787671', marginTop: 4 }}>
                  {e.estimated_duration_seconds != null && (
                    <>参考时长（P80） {formatDurationSeconds(e.estimated_duration_seconds)}</>
                  )}
                  {e.estimated_duration_seconds != null && e.expected_finish_at && ' · '}
                  {e.expected_finish_at && `预计完成 ${formatDateTime(e.expected_finish_at)}`}
                </div>
              )}
              {e.equipments.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  {e.equipments.map(eq => (
                    <Tag key={eq.equipment_id}>
                      {eq.equipment_name}（{eq.equipment_no}）
                    </Tag>
                  ))}
                </div>
              )}
              <FieldValuesBlock values={e.field_values} />
            </div>
          ),
        }
      })}
    />
  )
}
