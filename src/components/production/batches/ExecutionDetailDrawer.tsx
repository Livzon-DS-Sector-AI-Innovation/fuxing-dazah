'use client'

import { Descriptions, Drawer, Skeleton, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchBatchDetailClient } from '@/lib/api/production-client'
import type { NodeExecutionListItem } from '@/types/production'
import { FieldValueDisplay } from '../shared/FieldValueDisplay'

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
              { key: 'owner', label: '负责人', children: execution.owner_name ?? '—' },
              {
                key: 'time',
                label: '起止时间',
                children: `${new Date(execution.started_at).toLocaleString('zh-CN')} ~ ${
                  execution.finished_at
                    ? new Date(execution.finished_at).toLocaleString('zh-CN')
                    : '进行中'
                }`,
              },
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
