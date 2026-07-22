'use client'

import { WarningOutlined } from '@ant-design/icons'
import type { FieldValue } from '@/types/production'

export function FieldValueDisplay({ value }: { value: FieldValue }) {
  let display: string
  if (value.value_numeric !== null && value.value_numeric !== undefined) {
    display = `${value.value_numeric}${value.unit ? ` ${value.unit}` : ''}`
  } else if (value.value_bool !== null && value.value_bool !== undefined) {
    display = value.value_bool ? '是' : '否'
  } else {
    display = value.value_text ?? '—'
  }
  if (!value.is_abnormal) return <span>{display}</span>
  return (
    <span
      style={{
        background: '#fff1f0',
        color: '#e03131',
        padding: '0 6px',
        borderRadius: 4,
        fontWeight: 600,
      }}
    >
      <WarningOutlined style={{ marginRight: 4 }} />
      {display}
    </span>
  )
}
