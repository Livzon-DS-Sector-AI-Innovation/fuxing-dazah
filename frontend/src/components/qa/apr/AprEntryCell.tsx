'use client'

import { Input } from 'antd'
import { AprChromeStyles, AprValue } from './AprChrome'
import { cellTextInvalid, focusRowSibling, numberCellPatch, type GridValue } from './AprEntryShared'
import type { AprItem } from '@/types/qa'

/**
 * 录入矩阵的单个可编辑格：数值列带快捷文字结果按钮与单位后缀，
 * 文字列是纯文本输入；只读/已删行回退为静态展示。
 *
 * 从 AprEntryPage 拆出：格子只关心「当前值 + 校验状态」，编辑态由页面持有；
 * 数值列文字结果在离开格子时才校验（onBlurValidate），避免「未检出」打到一半就标红。
 */
export function AprEntryCell({
  item,
  cell,
  status,
  error,
  removed,
  readOnly,
  focused,
  cellLabel,
  onCellChange,
  onFocusedChange,
  onBlurValidate,
}: {
  item: AprItem
  cell: GridValue
  status: 'normal' | 'oot' | 'oos' | null
  /** 保存预检/失焦校验写入的错误信息。 */
  error: string | undefined
  removed: boolean
  readOnly: boolean
  /** 数值格是否聚焦（快捷文字结果按钮只在聚焦且为空时出现）。 */
  focused: boolean
  /** 无障碍标签，如「DT2501001 第2行 1号罐 酸碱度」。 */
  cellLabel: string
  onCellChange: (patch: GridValue) => void
  onFocusedChange: (focused: boolean) => void
  /** 数值格失焦校验回调（携带失焦时刻的格值）。 */
  onBlurValidate: (cell: GridValue) => void
}) {
  const color =
    status === 'oos' ? 'var(--color-error)' : status === 'oot' ? 'var(--color-warning)' : undefined
  const invalid = item.value_type === 'number' && cellTextInvalid(item, cell)

  if (readOnly || removed) {
    return (
      <AprValue
        value={cell.num ?? cell.text ?? ''}
        status={removed ? null : status}
        unit={cell.num != null ? item.unit : null}
      />
    )
  }
  if (item.value_type === 'text') {
    return (
      <Input
        variant="borderless"
        size="small"
        maxLength={300}
        style={{ width: '100%', color }}
        status={error ? 'error' : undefined}
        aria-invalid={error ? true : undefined}
        aria-label={cellLabel}
        title={error ?? '文字判定，如 符合规定 / 未检出'}
        value={cell.text}
        data-apr-col={item.id}
        onPressEnter={(e) => focusRowSibling(e, item.id, e.shiftKey ? -1 : 1)}
        onChange={(e) => onCellChange({ num: null, raw: e.target.value, text: e.target.value })}
      />
    )
  }
  return (
    <Input
      variant="borderless"
      size="small"
      style={{ width: '100%', color }}
      status={error || invalid ? 'error' : undefined}
      aria-invalid={error ? true : undefined}
      aria-label={cellLabel}
      title={error}
      inputMode="decimal"
      value={cell.raw}
      data-apr-col={item.id}
      onPressEnter={(e) => focusRowSibling(e, item.id, e.shiftKey ? -1 : 1)}
      onFocus={() => onFocusedChange(true)}
      onBlur={(e) => {
        onFocusedChange(false)
        // 离开格子时才判非法，避免「未检出」打到一半就标红
        onBlurValidate(numberCellPatch(e.currentTarget.value))
      }}
      // suffix 容器必须常驻、只切换内部内容：聚焦时动态增删 suffix 会改变
      // DOM 结构导致输入框失焦（antd 官方已知行为）。快捷标签仅在聚焦且为空的格子出现，
      // 已有值时让位给数值和单位，避免窄列里按钮把输入内容挤没。
      suffix={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {focused && !cell.raw.trim()
            ? item.quick_values.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={AprChromeStyles.ndQuick}
                  aria-label={`填入${value}`}
                  title={`${value}（原样保留，统计口径由列定义决定）`}
                  // 阻止 mousedown 抢焦点，点击后输入框保持聚焦状态
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onCellChange({ num: null, raw: value, text: value })}
                >
                  {value}
                </button>
              ))
            : null}
          {item.unit && (cell.num != null || !cell.raw.trim()) ? (
            <span className={AprChromeStyles.unit}>{item.unit}</span>
          ) : null}
        </span>
      }
      onChange={(e) => onCellChange(numberCellPatch(e.target.value))}
    />
  )
}
