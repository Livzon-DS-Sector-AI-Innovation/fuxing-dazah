'use client'

/**
 * AI 建议人工确认流 — 通用确认列表 Modal（#2 地点→分区 / #4 岗位族归类共用）。
 *
 * 「AI 资产确认」同构模式（DESIGN 3x §12/§13）：AI 只产建议行（中间表），
 * 人工在确认列表逐条确认/忽略（或改值后确认，业务方在 onConfirm 闭包里读
 * 编辑态）→ 确认才写资产表。本组件只管布局与操作编排：业务列由调用方
 * 以 antd columns 注入（含各自的「AI 建议」列呈现），操作列（确认/忽略）
 * 与底部批量动作（批量确认 high + 扩展按钮）由本组件统一追加。
 */

import { useState } from 'react'
import { Button, Modal, Table, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { EmptyGuide } from '@/components/ui-kit'

export interface AiConfirmRow {
  id: string
}

/** 置信度展示口径（#2/#4 共用）：high 绿 / mid 黄 / low 红（待人工） */
export const CONFIDENCE_TAG: Record<string, { label: string; color: string }> = {
  high: { label: '高', color: 'green' },
  mid: { label: '中', color: 'gold' },
  low: { label: '低', color: 'red' },
}

export function ConfidenceTag({ value }: { value: string }) {
  const conf = CONFIDENCE_TAG[value] ?? CONFIDENCE_TAG.low
  return <Tag color={conf.color}>{conf.label}</Tag>
}

export interface AiSuggestionConfirmModalProps<T extends AiConfirmRow> {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  /** 建议行（通常=待确认工作集，父层 useQuery 持有） */
  rows: T[]
  loading?: boolean
  /** 业务列（含 AI 建议列的呈现/编辑控件），操作列由本组件追加 */
  columns: ColumnsType<T>
  /** 单行确认（含改值提交：业务方闭包读编辑态后自行组请求） */
  onConfirm: (row: T) => Promise<unknown>
  /** 行级确认可用性（如 #2 无分区建议的行只可忽略）；缺省恒可用 */
  canConfirm?: (row: T) => boolean
  /** 提供时行内显示忽略按钮 */
  onIgnore?: (row: T) => Promise<unknown>
  confirmText?: string
  /** 批量确认 high（提供时底部显示按钮）；run 返回确认条数 */
  batchConfirmHigh?: { run: () => Promise<{ confirmed: number }>; label?: string }
  /** 底部扩展区（#2 放「触发扫描」等业务按钮） */
  extraFooter?: React.ReactNode
  emptyText?: React.ReactNode
  width?: number
}

export function AiSuggestionConfirmModal<T extends AiConfirmRow>({
  open,
  onClose,
  title,
  description,
  rows,
  loading = false,
  columns,
  onConfirm,
  canConfirm,
  onIgnore,
  confirmText = '确认',
  batchConfirmHigh,
  extraFooter,
  emptyText,
  width = 860,
}: AiSuggestionConfirmModalProps<T>) {
  const [actingId, setActingId] = useState<string | null>(null)
  const [batchLoading, setBatchLoading] = useState(false)

  async function runRowAction(row: T, action: (row: T) => Promise<unknown>) {
    setActingId(row.id)
    try {
      await action(row)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败，请稍后重试')
    } finally {
      setActingId(null)
    }
  }

  async function runBatchHigh() {
    if (!batchConfirmHigh) return
    setBatchLoading(true)
    try {
      const { confirmed } = await batchConfirmHigh.run()
      message.success(`已批量确认 ${confirmed} 条 high 置信建议`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '批量确认失败，请稍后重试')
    } finally {
      setBatchLoading(false)
    }
  }

  const actionColumn: ColumnsType<T>[number] = {
    title: '操作',
    key: '__action',
    width: onIgnore ? 132 : 76,
    fixed: 'right',
    render: (_, row) => (
      <span className="flex gap-1">
        <Button
          size="small"
          type="primary"
          icon={<CheckOutlined />}
          loading={actingId === row.id}
          disabled={
            actingId !== null && actingId !== row.id
              ? true
              : canConfirm ? !canConfirm(row) : false
          }
          onClick={() => runRowAction(row, onConfirm)}
        >
          {confirmText}
        </Button>
        {onIgnore && (
          <Button
            size="small"
            icon={<CloseOutlined />}
            disabled={actingId !== null}
            onClick={() => runRowAction(row, (r) => onIgnore(r))}
          >
            忽略
          </Button>
        )}
      </span>
    ),
  }

  return (
    <Modal
      open={open}
      title={title}
      onCancel={onClose}
      width={width}
      footer={
        <div className="flex items-center justify-between">
          <div>{extraFooter}</div>
          <div className="flex gap-2">
            {batchConfirmHigh && (
              <Button
                type="primary"
                ghost
                loading={batchLoading}
                disabled={actingId !== null}
                onClick={runBatchHigh}
              >
                {batchConfirmHigh.label ?? '批量确认 high'}
              </Button>
            )}
            <Button onClick={onClose}>关闭</Button>
          </div>
        </div>
      }
    >
      {description && (
        <div className="pb-3 text-[12px] text-[var(--color-steel)]">{description}</div>
      )}
      <Table<T>
        rowKey="id"
        size="small"
        loading={loading}
        columns={[...columns, actionColumn]}
        dataSource={rows}
        pagination={rows.length > 8 ? { pageSize: 8, showTotal: (t) => `共 ${t} 条` } : false}
        scroll={{ x: 'max-content' }}
        locale={{
          emptyText:
            emptyText ?? (
              <EmptyGuide
                compact
                title="暂无待确认建议"
                description="触发一次批量扫描，AI 将对未映射/未归类文本给出建议"
              />
            ),
        }}
      />
    </Modal>
  )
}
