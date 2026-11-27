'use client'

// 清退明细表：四部门维度的清退事项、状态、扣补金额。平台是工作数据源——
// 进入清退阶段自带一份默认清单，HR 逐项确认；表格行顺序即保存后的展示顺序。

import { Button, Empty, Input, InputNumber, Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import type { ClearanceCategory, OffboardingClearanceItem } from '@/types/hr'

export interface ClearanceRow {
  category: ClearanceCategory
  item_name: string
  status: OffboardingClearanceItem['status']
  deduction_amount?: number | null
  supplement_amount?: number | null
  remark?: string | null
  confirmed_by?: string | null
}

export const CATEGORY_LABELS: Record<ClearanceCategory, string> = {
  admin: '行政后勤部',
  finance: '财务部',
  hr: '人力资源部',
  work: '工作部门',
}
export const CATEGORY_ORDER: ClearanceCategory[] = ['admin', 'finance', 'hr', 'work']

const STATUS_OPTIONS = [
  { value: 'pending', label: '待确认' },
  { value: 'confirmed', label: '已清退' },
  { value: 'deducted', label: '有扣补' },
]

export const emptyRow = (category: ClearanceCategory): ClearanceRow => ({
  category,
  item_name: '',
  status: 'pending',
  deduction_amount: null,
  supplement_amount: null,
  remark: '',
  confirmed_by: '',
})

/** 详情里的清退明细 → 表格行（保持后端返回顺序） */
export function toRows(items: OffboardingClearanceItem[] | undefined): ClearanceRow[] {
  return (items || []).map((item) => ({
    category: item.category,
    item_name: item.item_name,
    status: item.status,
    deduction_amount: item.deduction_amount ?? null,
    supplement_amount: item.supplement_amount ?? null,
    remark: item.remark ?? '',
    confirmed_by: item.confirmed_by ?? '',
  }))
}

/** 行 → 保存接口的入参（去掉空金额，避免把「没填」存成 0） */
export function toPayload(rows: ClearanceRow[]): Record<string, unknown>[] {
  return rows.map((row) => ({
    category: row.category,
    item_name: row.item_name.trim(),
    status: row.status,
    deduction_amount: row.deduction_amount ?? null,
    supplement_amount: row.supplement_amount ?? null,
    remark: row.remark?.trim() || null,
    confirmed_by: row.confirmed_by?.trim() || null,
  }))
}

function Summary({
  rows,
  onConfirmAll,
}: {
  rows: ClearanceRow[]
  /** 某部门口头 / 飞书回复「都清完了」时，一键把该部门剩下的「待确认」标成「已清退」；已标「有扣补」的不动 */
  onConfirmAll?: (category: ClearanceCategory) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {CATEGORY_ORDER.map((category) => {
        const own = rows.filter((row) => row.category === category)
        const done = own.filter((row) => row.status !== 'pending').length
        const hasPending = own.some((row) => row.status === 'pending')
        const deduct = own.reduce((sum, row) => sum + (row.deduction_amount || 0), 0)
        const supplement = own.reduce((sum, row) => sum + (row.supplement_amount || 0), 0)
        return (
          <span
            key={category}
            className="inline-flex items-center gap-1 rounded-[var(--rounded-sm)] bg-[var(--color-surface)] px-2 py-0.5 text-[12px] text-[var(--color-slate)]"
          >
            <span>
              <b className="font-medium text-[var(--color-ink)]">{CATEGORY_LABELS[category]}</b>
              {' '}· 已确认 {done}/{own.length}
              {deduct > 0 && <span className="ml-1">扣 {deduct}</span>}
              {supplement > 0 && <span className="ml-1">补 {supplement}</span>}
            </span>
            {hasPending && onConfirmAll && (
              <Button
                type="link"
                size="small"
                // 跟着汇总条的字号行高走，别撑高整条（仓库口径：antd 高度要 ! 才压得住）
                className="!h-auto !px-1 !text-[12px] !leading-[18px]"
                onClick={() => onConfirmAll(category)}
              >
                全部已清退
              </Button>
            )}
          </span>
        )
      })}
    </div>
  )
}

export default function ClearanceTable({
  rows,
  onChange,
  disabled = false,
}: {
  rows: ClearanceRow[]
  onChange: (next: ClearanceRow[]) => void
  /** 只读：没有办理权限的人只能看 */
  disabled?: boolean
}) {
  const update = (idx: number, patch: Partial<ClearanceRow>) =>
    onChange(rows.map((row, i) => (i === idx ? { ...row, ...patch } : row)))

  const columns: ColumnsType<ClearanceRow> = [
    {
      title: '部门',
      dataIndex: 'category',
      width: 132,
      render: (value: ClearanceCategory, _row, idx) => (
        <Select
          size="small"
          className="w-full"
          value={value}
          disabled={disabled}
          options={CATEGORY_ORDER.map((c) => ({ value: c, label: CATEGORY_LABELS[c] }))}
          onChange={(v) => update(idx, { category: v })}
        />
      ),
    },
    {
      title: '清退事项',
      dataIndex: 'item_name',
      width: 180,
      render: (value: string, _row, idx) => (
        <Input
          size="small"
          value={value}
          maxLength={64}
          placeholder="如：宿舍钥匙"
          disabled={disabled}
          status={value.trim() ? undefined : 'error'}
          onChange={(e) => update(idx, { item_name: e.target.value })}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: ClearanceRow['status'], _row, idx) => (
        <Select
          size="small"
          className="w-full"
          value={value}
          options={STATUS_OPTIONS}
          disabled={disabled}
          onChange={(v) => update(idx, { status: v })}
        />
      ),
    },
    {
      title: '扣款',
      dataIndex: 'deduction_amount',
      width: 104,
      render: (value: number | null | undefined, _row, idx) => (
        <InputNumber
          size="small"
          className="w-full"
          min={0}
          precision={2}
          value={value ?? undefined}
          placeholder="0.00"
          disabled={disabled || rows[idx].status !== 'deducted'}
          onChange={(v) => update(idx, { deduction_amount: v ?? null })}
        />
      ),
    },
    {
      title: '补发',
      dataIndex: 'supplement_amount',
      width: 104,
      render: (value: number | null | undefined, _row, idx) => (
        <InputNumber
          size="small"
          className="w-full"
          min={0}
          precision={2}
          value={value ?? undefined}
          placeholder="0.00"
          disabled={disabled || rows[idx].status !== 'deducted'}
          onChange={(v) => update(idx, { supplement_amount: v ?? null })}
        />
      ),
    },
    {
      title: '确认人',
      dataIndex: 'confirmed_by',
      width: 110,
      render: (value: string | null | undefined, _row, idx) => (
        <Input
          size="small"
          value={value ?? ''}
          maxLength={64}
          disabled={disabled}
          onChange={(e) => update(idx, { confirmed_by: e.target.value })}
        />
      ),
    },
    {
      title: '备注',
      dataIndex: 'remark',
      width: 150,
      render: (value: string | null | undefined, _row, idx) => (
        <Input
          size="small"
          value={value ?? ''}
          maxLength={255}
          disabled={disabled}
          onChange={(e) => update(idx, { remark: e.target.value })}
        />
      ),
    },
    {
      title: '',
      key: 'remove',
      width: 40,
      render: (__unknown, _row, idx) => (
        <Button
          type="text"
          size="small"
          danger
          icon={<MinusCircleOutlined />}
          aria-label="删除此行"
          disabled={disabled}
          onClick={() => onChange(rows.filter((_r, i) => i !== idx))}
        />
      ),
    },
  ]

  return (
    <div className="space-y-2">
      <Summary
        rows={rows}
        onConfirmAll={disabled ? undefined : (category) =>
          onChange(
            rows.map((row) =>
              row.category === category && row.status === 'pending' ? { ...row, status: 'confirmed' } : row,
            ),
          )}
      />
      <Table<ClearanceRow>
        size="small"
        columns={columns}
        dataSource={rows}
        rowKey={(_row, idx) => String(idx)}
        pagination={false}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无清退明细，点下方按钮按部门添加"
            />
          ),
        }}
        footer={() => (disabled ? null : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-[var(--color-steel)]">添加：</span>
            {CATEGORY_ORDER.map((category) => (
              <Button
                key={category}
                size="small"
                icon={<PlusOutlined />}
                onClick={() => onChange([...rows, emptyRow(category)])}
              >
                {CATEGORY_LABELS[category]}
              </Button>
            ))}
          </div>
        ))}
      />
      <div className="text-[12px] text-[var(--color-steel)]">
        金额单位：元；状态选「有扣补」后可填扣款 / 补发，台账的「清退与结算」从这里汇总。
      </div>
    </div>
  )
}
