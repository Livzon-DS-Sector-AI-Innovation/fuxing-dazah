'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * Code execution node — Python sandbox.
 * Purple header.
 */

export const CodeNode = memo(function CodeNode(props: BaseNodeProps) {
  const { data } = props
  const code = data.code as string | undefined
  const codeLanguage = (data.code_language as string) || 'python'

  return (
    <BaseNode {...props} headerColor="#722ed1">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        <div style={{ color: '#999', marginBottom: 4 }}>
          语言: {codeLanguage}
        </div>
        {code ? (
          <pre
            style={{
              fontSize: 10,
              maxHeight: 48,
              overflow: 'hidden',
              background: '#f9f0ff',
              padding: '4px 6px',
              borderRadius: 4,
              color: '#531dab',
              margin: 0,
              fontFamily: 'monospace',
            }}
          >
            {code.slice(0, 100)}
          </pre>
        ) : (
          <span style={{ color: '#999', fontSize: 11 }}>待编辑代码...</span>
        )}
      </div>
    </BaseNode>
  )
})
