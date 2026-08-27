'use client'

import type { ReactNode } from 'react'
import { Tag } from 'antd'
import { WarningOutlined } from '@ant-design/icons'
import type { ProcessBoardExecution, ProcessBoardPlannedItem } from '@/types/production'
import { formatDateTime } from '@/lib/utils'
import { BATCH_STATUS_META } from './BatchTable'
import { ITEM_STATUS_CONFIG, PRIORITY_CONFIG } from '../planning-center/constants'
import { FieldValueDisplay } from '../shared/FieldValueDisplay'

/** 看板工序列状态：dot 用于列内色条，color/label 用于 hover 卡片 Tag。ProcessBoard 图例共用。 */
export const BOARD_STATE_META: Record<string, { dot: string; color: string; label: string }> = {
  in_progress: { dot: '#5645d4', color: 'blue', label: '进行中' },
  waiting: { dot: '#2a9d99', color: 'cyan', label: '待流转' },
  aborted: { dot: '#dd5b00', color: 'orange', label: '已中止' },
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 10, fontSize: 12, lineHeight: '22px' }}>
      <span style={{ color: '#a4a097', flexShrink: 0, width: 60 }}>{label}</span>
      <span style={{ color: '#37352f', flex: 1, minWidth: 0, wordBreak: 'break-all' }}>
        {children}
      </span>
    </div>
  )
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.5,
        color: '#a4a097',
        margin: '10px 0 6px',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      {children}
      <span style={{ flex: 1, height: 1, background: '#ede9e4' }} />
    </div>
  )
}

/** 工序看板 hover 浮层：批次信息 + 字段数据（数据随看板 payload 返回，即时渲染） */
export function BatchHoverCard({ item }: { item: ProcessBoardExecution }) {
  const meta = BOARD_STATE_META[item.board_state] ?? { color: 'default', label: item.board_state }

  return (
    <div style={{ width: 304, maxHeight: 400, overflowY: 'auto', padding: 2 }}>
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <span
          style={{
            fontSize: 14,
            fontWeight: 700,
            color: '#1a1a1a',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {item.batch_no}
        </span>
        <Tag color={meta.color} style={{ marginInlineEnd: 0, lineHeight: '18px' }}>
          {meta.label}
        </Tag>
        <span style={{ fontSize: 11, color: '#a4a097', marginLeft: 'auto' }}>
          第 {item.execution_seq} 次
        </span>
      </div>

      {/* 批次信息 */}
      <SectionLabel>批次信息</SectionLabel>
      <InfoRow label="批次状态">
        {(BATCH_STATUS_META[item.batch_status]?.label ?? item.batch_status) || '—'}
      </InfoRow>
      <InfoRow label="数量">
        {item.batch_quantity != null ? `${item.batch_quantity} ${item.batch_unit ?? ''}` : '—'}
      </InfoRow>
      <InfoRow label="归属人">{item.owner_name ?? '—'}</InfoRow>
      <InfoRow label="开始时间">{formatDateTime(item.started_at)}</InfoRow>
      <InfoRow label="结束时间">
        {item.finished_at ? formatDateTime(item.finished_at) : '—'}
      </InfoRow>
      <InfoRow label="异常字段">
        {item.abnormal_count > 0 ? (
          <span style={{ color: '#e03131', fontWeight: 600 }}>
            <WarningOutlined style={{ marginRight: 4 }} />
            {item.abnormal_count} 个
          </span>
        ) : (
          '无'
        )}
      </InfoRow>
      {item.is_deviation && <InfoRow label="偏离">是</InfoRow>}
      {item.equipments.length > 0 && (
        <InfoRow label="设备">
          {item.equipments.map(eq => eq.equipment_name).join('、')}
        </InfoRow>
      )}

      {/* 字段数据 */}
      {item.field_values.length > 0 && (
        <>
          <SectionLabel>字段数据</SectionLabel>
          {item.field_values.map(v => (
            <div
              key={`${v.field_key}-${v.phase}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '3px 0',
                borderBottom: '1px solid #f0eeec',
              }}
            >
              <span style={{ fontSize: 12, color: '#5d5b54', flex: 1, minWidth: 0 }}>
                {v.field_label}
                <span
                  style={{
                    fontSize: 10,
                    color: '#a4a097',
                    marginLeft: 4,
                    padding: '0 4px',
                    borderRadius: 3,
                    background: '#f6f5f4',
                  }}
                >
                  {v.phase === 'start' ? '开始' : '结束'}
                </span>
              </span>
              <span style={{ fontSize: 12, fontWeight: 500 }}>
                <FieldValueDisplay value={v} />
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

/** 计划批次列 hover 浮层：实际批次 + 计划来源 */
export function PlannedHoverCard({ item }: { item: ProcessBoardPlannedItem }) {
  return (
    <div style={{ width: 288, padding: 2 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <span
          style={{
            fontSize: 14,
            fontWeight: 700,
            color: '#1a1a1a',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {item.batch_no}
        </span>
        <Tag style={{ marginInlineEnd: 0, lineHeight: '18px' }} color="purple">
          {ITEM_STATUS_CONFIG[item.item_status]?.label ?? item.item_status}
        </Tag>
      </div>
      <InfoRow label="批次状态">
        {(BATCH_STATUS_META[item.batch_status]?.label ?? item.batch_status) || '—'}
      </InfoRow>
      <InfoRow label="计划单">{item.order_no}（v{item.plan_version}）</InfoRow>
      <InfoRow label="计划项">第 {item.item_no} 项</InfoRow>
      <InfoRow label="数量">
        {item.planned_quantity != null ? `${item.planned_quantity} ${item.unit ?? ''}` : '—'}
      </InfoRow>
      <InfoRow label="计划开始">{formatDateTime(item.planned_start)}</InfoRow>
      <InfoRow label="计划结束">{formatDateTime(item.planned_end)}</InfoRow>
      <InfoRow label="优先级">{PRIORITY_CONFIG[item.priority]?.label ?? item.priority}</InfoRow>
      <InfoRow label="目标设备">{item.equipment_id ?? '—'}</InfoRow>
    </div>
  )
}
