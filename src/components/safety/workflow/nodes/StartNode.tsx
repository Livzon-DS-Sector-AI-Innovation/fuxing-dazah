'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * Start node — defines input variables.
 * Green header, source handle only.
 */

interface VariableDef {
  variable: string
  label: string
  type?: string
  required?: boolean
}

export const StartNode = memo(function StartNode(props: BaseNodeProps) {
  const { data } = props
  const variables = (data.variables as VariableDef[]) || []

  return (
    <BaseNode {...props} headerColor="#52c41a" inputHandles={false}>
      {variables.length > 0 ? (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          {variables.map((v, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: '#52c41a' }}>→</span>
              <span style={{ fontWeight: 500 }}>{v.label || v.variable}</span>
              <span style={{ color: '#999' }}>({v.variable})</span>
              {v.required && <span style={{ color: '#ff4d4f', fontSize: 10 }}>*必填</span>}
            </div>
          ))}
        </div>
      ) : (
        <span style={{ color: '#999', fontSize: 12 }}>无输入变量</span>
      )}
    </BaseNode>
  )
})
