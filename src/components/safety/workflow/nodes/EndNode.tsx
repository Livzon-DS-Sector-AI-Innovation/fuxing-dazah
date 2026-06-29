'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * End node — defines output variables.
 * Red header, target handle only.
 */

interface OutputDef {
  variable: string
  value_selector?: string[]
}

export const EndNode = memo(function EndNode(props: BaseNodeProps) {
  const { data } = props
  const outputs = (data.outputs as OutputDef[]) || []

  return (
    <BaseNode {...props} headerColor="#ff4d4f" outputHandles={false}>
      {outputs.length > 0 ? (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          {outputs.map((o, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: '#ff4d4f' }}>←</span>
              <span style={{ fontWeight: 500 }}>{o.variable}</span>
              {o.value_selector && (
                <span style={{ color: '#999', fontSize: 11 }}>
                  {'{{#'}{o.value_selector.join('.')}{'#}}'}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <span style={{ color: '#999', fontSize: 12 }}>无输出变量</span>
      )}
    </BaseNode>
  )
})
