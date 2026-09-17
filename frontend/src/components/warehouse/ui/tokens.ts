/**
 * 仓储模块 UI 语义 tone（V2.0 改版底座）。
 * 颜色与 globals.css 的 --wh-* token 一一对应：组件里用 TS 常量取色，
 * 需要工具类时用 text-wh-danger / bg-wh-danger-bg 等 Tailwind 映射。
 */

export type Tone = 'default' | 'primary' | 'ok' | 'warn' | 'danger' | 'expired' | 'info'

interface ToneStyle {
  color: string
  bg: string
}

export const TONE_STYLE: Record<Tone, ToneStyle> = {
  default: { color: 'var(--color-charcoal)', bg: 'var(--color-surface)' },
  primary: { color: 'var(--color-primary)', bg: 'var(--wh-primary-bg)' },
  ok: { color: 'var(--wh-ok)', bg: 'var(--wh-ok-bg)' },
  warn: { color: 'var(--wh-warn)', bg: 'var(--wh-warn-bg)' },
  danger: { color: 'var(--wh-danger)', bg: 'var(--wh-danger-bg)' },
  expired: { color: 'var(--wh-expired)', bg: 'var(--wh-expired-bg)' },
  info: { color: 'var(--wh-info)', bg: 'var(--wh-info-bg)' },
}

/** antd Tag color 名（页面里偶尔直接用 antd Tag 时保持同一套语义） */
export const TONE_TAG_COLOR: Record<Tone, string> = {
  default: 'default',
  primary: 'purple',
  ok: 'green',
  warn: 'gold',
  danger: 'red',
  expired: 'volcano',
  info: 'blue',
}

/**
 * 具体色值（echarts 等 canvas 场景无法读 CSS 变量，需要字面量）。
 * 必须与 globals.css 的 --wh-* 保持一致，改色时两处同步。
 */
export const TONE_HEX = {
  primary: '#5645d4',
  ok: '#1aae39',
  warn: '#dd5b00',
  danger: '#e03131',
  expired: '#a61e24',
  info: '#2f6bd8',
} as const
