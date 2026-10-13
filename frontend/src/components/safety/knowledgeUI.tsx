'use client'

import { Tooltip } from 'antd'
import { KB } from './knowledgeTokens'

/** 分类标签 chip：emoji + 中文标签，分类色淡底 */
export function CategoryChip({
  emoji,
  label,
  color,
  bg,
  title,
  maxWidth = '100%',
}: {
  emoji: string
  label: string
  color: string
  bg: string
  title?: string
  maxWidth?: string
}) {
  return (
    <span
      title={title || label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: KB.radius.sm,
        fontSize: 12,
        fontWeight: 600,
        color,
        background: bg,
        lineHeight: '18px',
        maxWidth,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ fontSize: 13, lineHeight: 1 }}>{emoji}</span>
      {label}
    </span>
  )
}

/** 单行元数据：小图标 + 截断文本 */
export function MetaItem({
  icon,
  text,
  title,
}: {
  icon: React.ReactNode
  text: string
  title?: string
}) {
  return (
    <Tooltip title={title || text}>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          fontSize: 12,
          lineHeight: '18px',
          color: KB.color.steel,
          minWidth: 0,
          maxWidth: '100%',
        }}
      >
        <span style={{ flexShrink: 0, display: 'inline-flex', fontSize: 12, color: KB.color.stone }}>
          {icon}
        </span>
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {text}
        </span>
      </span>
    </Tooltip>
  )
}
