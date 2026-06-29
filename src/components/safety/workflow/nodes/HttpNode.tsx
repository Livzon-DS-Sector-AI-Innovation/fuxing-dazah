'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * HTTP request node.
 * Teal header.
 */

export const HttpNode = memo(function HttpNode(props: BaseNodeProps) {
  const { data } = props
  const method = (data.method as string) || 'GET'
  const url = data.url as string | undefined

  const methodColors: Record<string, string> = {
    GET: '#52c41a',
    POST: '#1890ff',
    PUT: '#fa8c16',
    DELETE: '#ff4d4f',
    PATCH: '#722ed1',
  }

  return (
    <BaseNode {...props} headerColor="#13c2c2">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        <span
          style={{
            display: 'inline-block',
            background: methodColors[method] || '#666',
            color: '#fff',
            padding: '0 6px',
            borderRadius: 3,
            fontWeight: 600,
            fontSize: 10,
            marginRight: 6,
          }}
        >
          {method}
        </span>
        <span style={{ color: '#666', fontSize: 11, wordBreak: 'break-all' }}>
          {url || '/'}
        </span>
      </div>
    </BaseNode>
  )
})
