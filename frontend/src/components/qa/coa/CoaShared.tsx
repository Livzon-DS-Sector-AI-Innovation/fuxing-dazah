'use client'

import type { CSSProperties } from 'react'
import { App } from 'antd'
import type { ButtonProps, ModalFuncProps } from 'antd'
import type { CoaValueType } from '@/types/qa'

export const VALUE_TYPE_LABEL: Record<CoaValueType, string> = {
  number: '数值',
  text: '文字判定',
}

export const VALUE_TYPE_OPTIONS: { value: CoaValueType; label: string }[] = [
  { value: 'number', label: VALUE_TYPE_LABEL.number },
  { value: 'text', label: VALUE_TYPE_LABEL.text },
]

/** 值类型 → 圆点颜色（矩阵里区分数值/文字列）。 */
export const VALUE_TYPE_DOT: Record<CoaValueType, CSSProperties> = {
  number: { color: 'var(--color-link-blue)' },
  text: { color: 'var(--color-brand-purple)' },
}

/**
 * 危险操作确认按钮：全局 .ant-btn-primary 把主按钮固定成紫色，
 * 用内联样式把「作废/删除」压回红色（apr 同款口径）。
 */
export const DANGER_OK_PROPS: ButtonProps = {
  danger: true,
  style: { background: 'var(--color-error)', borderColor: 'var(--color-error)' },
}

type AppModal = ReturnType<typeof App.useApp>['modal']

/**
 * 确认框收口：antd 6.6.2 + React 19 下 modal.confirm 的 onOk 返回 promise
 * 时，异步完成后确认框不会自动关闭。统一 fire-and-forget，异步结果由
 * 调用方用 message 反馈（apr 域已验证的口径）。
 */
export function confirmAsync(
  modal: AppModal,
  config: Omit<ModalFuncProps, 'onOk'> & { onOk: () => Promise<void> | void }
): void {
  const { onOk, ...rest } = config
  modal.confirm({
    ...rest,
    onOk: () => {
      void onOk()
    },
  })
}

/** 矩阵单元格显示：数值右对齐等宽；文字判定原样。 */
export function renderMatrixCell(value: { num: number | null; text: string | null } | undefined): string {
  if (!value) return '—'
  if (value.num != null) return String(value.num)
  return value.text ?? '—'
}
