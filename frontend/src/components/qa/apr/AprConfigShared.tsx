'use client'

import type { CSSProperties } from 'react'
import { App } from 'antd'
import type { ButtonProps, ModalFuncProps } from 'antd'
import { PILL } from '@/components/qa/deviation/shared'
import type { AprDataKind, AprItem, AprItemCategory, AprValueType } from '@/types/qa'

// ── 文案字典（配置页与弹窗共用，避免同一枚举出现多种叫法）──

export const DATA_KIND_LABEL: Record<AprDataKind, string> = {
  production: '生产数据',
  inspection: '检验结果',
}

export const DATA_KIND_OPTIONS: { value: AprDataKind; label: string }[] = [
  { value: 'production', label: '生产数据（工艺参数）' },
  { value: 'inspection', label: '检验结果（成品/中间体）' },
]

export const CATEGORY_LABEL: Record<AprItemCategory, string> = {
  cpp: '关键工艺参数',
  ipc: '中间控制参数',
  test: '检验项目',
  info: '批次信息',
}

export const CATEGORY_OPTIONS: { value: AprItemCategory; label: string }[] = [
  { value: 'cpp', label: CATEGORY_LABEL.cpp },
  { value: 'ipc', label: CATEGORY_LABEL.ipc },
  { value: 'test', label: CATEGORY_LABEL.test },
  { value: 'info', label: CATEGORY_LABEL.info },
]

export const VALUE_TYPE_LABEL: Record<AprValueType, string> = {
  number: '数值',
  text: '文字判定',
}

export const VALUE_TYPE_OPTIONS: { value: AprValueType; label: string }[] = [
  { value: 'number', label: VALUE_TYPE_LABEL.number },
  { value: 'text', label: VALUE_TYPE_LABEL.text },
]

/** 段数据类型 → 圆点颜色；列表里一眼区分「生产」与「检验」段。 */
export const DATA_KIND_DOT: Record<AprDataKind, string> = {
  production: 'var(--color-brand-purple)',
  inspection: 'var(--color-link-blue)',
}

/** 列类别 → 标签样式（DESIGN.md pastel tint）。 */
export const CATEGORY_PILL: Record<AprItemCategory, CSSProperties> = {
  cpp: PILL.purple,
  ipc: PILL.info,
  test: PILL.success,
  info: PILL.neutral,
}

/**
 * 危险操作确认按钮：全局 .ant-btn-primary 把主按钮固定成紫色，
 * 这里用内联样式把「删除」压回红色，避免和普通主操作混淆。
 */
export const DANGER_OK_PROPS: ButtonProps = {
  danger: true,
  style: { background: 'var(--color-error)', borderColor: 'var(--color-error)' },
}

type AppModal = ReturnType<typeof App.useApp>['modal']

/**
 * 确认框收口：antd 6.6.2 + React 19 下 modal.confirm 的 onOk 返回 promise
 * 时，异步完成后确认框与遮罩不会自动关闭（只有 Escape 能关，残留的
 * .ant-modal-wrap 会拦截整页点击）。这里统一把 onOk 变成 fire-and-forget：
 * 对话框立即关闭，异步结果由调用方用 message 反馈。
 */
export function confirmAsync(
  modal: AppModal,
  config: Omit<ModalFuncProps, 'onOk'> & { onOk: () => Promise<void> | void },
): void {
  const { onOk, ...rest } = config
  modal.confirm({
    ...rest,
    onOk: () => {
      void onOk()
    },
  })
}

/** 自动生成的列编码形如 it_965ddd5c，属于内部实现，不在列表里显示。 */
export function isAutoCode(code: string): boolean {
  return /^it_[0-9a-f]{8}$/i.test(code)
}

// ── 标准限解析 ──

export interface SpecRange {
  min: number | null
  max: number | null
}

const NUMBER = String.raw`\d+(?:\.\d+)?`

/**
 * 从「标准原文」里识别上下限，支持常见写法：
 * 6.6±0.4 / 20-30分钟 / 4.0~4.6 / ≤5.0 / ≥3 / <0.5 / >1.0。
 * 只认从字符串开头起的限度，避免把「第1-2阶段」这类描述误当限度。
 */
export function parseSpecRange(raw: string | null | undefined): SpecRange | null {
  if (!raw) return null
  const text = raw
    .replace(/[（(]/g, ' ')
    .replace(/[）)]/g, ' ')
    .replace(/／/g, '/')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return null

  const pickup = (value: string): number | null => {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }

  const plusMinus = text.match(new RegExp(`^(${NUMBER})\\s*(?:±|\\+-)\\s*(${NUMBER})`))
  if (plusMinus) {
    const center = pickup(plusMinus[1])
    const tolerance = pickup(plusMinus[2])
    if (center != null && tolerance != null) {
      return { min: round(center - tolerance), max: round(center + tolerance) }
    }
  }

  const upper = text.match(new RegExp(`^(?:≤|<=|≦|＜)\\s*(${NUMBER})`))
  if (upper) return { min: null, max: pickup(upper[1]) }

  const lower = text.match(new RegExp(`^(?:≥|>=|≧|＞)\\s*(${NUMBER})`))
  if (lower) return { min: pickup(lower[1]), max: null }

  const below = text.match(new RegExp(`^(?:<|＜)\\s*(${NUMBER})`))
  if (below) return { min: null, max: pickup(below[1]) }

  const above = text.match(new RegExp(`^(?:>|＞)\\s*(${NUMBER})`))
  if (above) return { min: pickup(above[1]), max: null }

  const range = text.match(new RegExp(`^(${NUMBER})\\s*(?:-|~|～|—|－|至|到)\\s*(${NUMBER})`))
  if (range) {
    const first = pickup(range[1])
    const second = pickup(range[2])
    if (first != null && second != null) {
      return { min: round(Math.min(first, second)), max: round(Math.max(first, second)) }
    }
  }

  return null
}

/** 克制浮点尾差：6.2、7.0 而不是 6.199999999999999。 */
function round(value: number): number {
  return Math.round(value * 1e6) / 1e6
}

function decimalPlaces(value: number): number {
  const text = String(value)
  const dot = text.indexOf('.')
  return dot < 0 ? 0 : Math.min(text.length - dot - 1, 4)
}

function formatNumber(value: number, digits: number): string {
  return digits > 0 ? value.toFixed(digits) : String(value)
}

export function formatRange(min: number | null | undefined, max: number | null | undefined): string | null {
  if (min != null && max != null) {
    // 6.2 与 7 对齐成 6.2 ~ 7.0，避免和标准原文「6.6±0.4」看起来不一致
    const digits = Math.max(decimalPlaces(min), decimalPlaces(max))
    return `${formatNumber(min, digits)} ~ ${formatNumber(max, digits)}`
  }
  if (min != null) return `≥ ${formatNumber(min, decimalPlaces(min))}`
  if (max != null) return `≤ ${formatNumber(max, decimalPlaces(max))}`
  return null
}

/** 列表里显示的标准：优先标准原文，没有原文时用上下限拼。 */
export function itemSpecText(item: AprItem): string | null {
  if (item.spec_text?.trim()) return item.spec_text.trim()
  return formatRange(item.spec_min, item.spec_max)
}

/**
 * 是否缺少标准：只有需要判定的列才算缺口。
 * 批次信息（批号等）本身没有标准限，不提示补全。
 */
export function itemMissingSpec(item: AprItem): boolean {
  if (item.category === 'info') return false
  return !item.spec_text?.trim() && item.spec_min == null && item.spec_max == null
}
