'use client'

import { Button, Descriptions, Empty, Popconfirm, Space, Tag, Timeline } from 'antd'
import { FieldValueDisplay } from '../shared/FieldValueDisplay'
import type { Execution, FieldValue } from '@/types/production'

const EXEC_STATUS_META: Record<string, { color: string; label: string; dotColor: string }> = {
  in_progress: { color: 'blue', label: '进行中', dotColor: 'blue' },
  completed: { color: 'green', label: '已完成', dotColor: 'green' },
  aborted: { color: 'default', label: '已中止', dotColor: 'gray' },
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
  onComplete: (execution: Execution) => void
  onAbort: (execution: Execution) => void
}

export function ExecutionTimeline({ executions, canSubmit, onComplete, onAbort }: Props) {
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
              <div style={{ fontSize: 12, color: '#787671', marginTop: 4 }}>
                负责人 {e.owner_name ?? '—'} · 开始{' '}
                {new Date(e.started_at).toLocaleString('zh-CN')}
                {e.finished_at &&
                  ` · 结束 ${new Date(e.finished_at).toLocaleString('zh-CN')}`}
              </div>
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
