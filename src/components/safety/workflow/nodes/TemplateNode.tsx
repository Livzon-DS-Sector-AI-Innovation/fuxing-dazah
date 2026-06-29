'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * Template transform node — Jinja2-style template rendering.
 * Pink header.
 */

export const TemplateNode = memo(function TemplateNode(props: BaseNodeProps) {
  const { data } = props
  const template = data.template as string | undefined
  const outputVariable = data.output_variable as string | undefined

  return (
    <BaseNode {...props} headerColor="#eb2f96">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        {outputVariable && (
          <div style={{ marginBottom: 4 }}>
            <span style={{ color: '#999' }}>输出: </span>
            <span style={{ fontWeight: 500, color: '#c41d7f' }}>{outputVariable}</span>
          </div>
        )}
        {template ? (
          <pre
            style={{
              fontSize: 10,
              maxHeight: 40,
              overflow: 'hidden',
              background: '#fff0f6',
              padding: '4px 6px',
              borderRadius: 4,
              color: '#c41d7f',
              margin: 0,
              fontFamily: 'monospace',
            }}
          >
            {template.slice(0, 80)}
          </pre>
        ) : (
          <span style={{ color: '#999', fontSize: 11 }}>待编辑模板...</span>
        )}
      </div>
    </BaseNode>
  )
})
