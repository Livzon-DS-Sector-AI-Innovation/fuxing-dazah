'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * Variable aggregator node — collects multiple inputs into one output.
 * Indigo header.
 */

interface AggregatorVar {
  variable?: string
  value_selector?: string[]
}

export const AggregatorNode = memo(function AggregatorNode(props: BaseNodeProps) {
  const { data } = props
  const variables = (data.variables as AggregatorVar[]) || []
  const outputType = (data.output_type as string) || 'object'

  return (
    <BaseNode {...props} headerColor="#2f54eb">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        <div style={{ color: '#999', marginBottom: 4 }}>
          输出类型: {outputType}
        </div>
        {variables.length > 0 ? (
          <div>
            {variables.map((v, i) => (
              <div key={i} style={{ fontSize: 11, color: '#666' }}>
                ← {v.variable || `var_${i}`}
                {v.value_selector && (
                  <code style={{ fontSize: 10, color: '#2f54eb', marginLeft: 4 }}>
                    {'{{#'}{v.value_selector.join('.')}{'#}}'}
                  </code>
                )}
              </div>
            ))}
          </div>
        ) : (
          <span style={{ color: '#999', fontSize: 11 }}>无聚合变量</span>
        )}
      </div>
    </BaseNode>
  )
})
