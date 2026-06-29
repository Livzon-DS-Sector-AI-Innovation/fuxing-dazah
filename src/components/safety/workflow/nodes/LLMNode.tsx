'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * LLM node — model invocation.
 * Blue header.
 */

interface ModelConfig {
  provider?: string
  name?: string
  completion_params?: Record<string, unknown>
}

export const LLMNode = memo(function LLMNode(props: BaseNodeProps) {
  const { data } = props
  const model = data.model as ModelConfig | undefined
  const promptTemplate = data.prompt_template as Array<{ role: string; text: string }> | undefined
  const expectedKeys = data.expected_keys as string[] | undefined

  return (
    <BaseNode {...props} headerColor="#1890ff">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        {model && (
          <div style={{ marginBottom: 4 }}>
            <span style={{ color: '#999' }}>模型: </span>
            <span style={{ fontWeight: 500 }}>
              {model.provider || '?'} / {model.name || '?'}
            </span>
            {model.completion_params?.temperature != null && (
              <span style={{ color: '#999', marginLeft: 4 }}>
                τ={String(model.completion_params.temperature)}
              </span>
            )}
          </div>
        )}
        {promptTemplate && promptTemplate.length > 0 && (
          <div style={{ color: '#666', fontSize: 11, maxHeight: 40, overflow: 'hidden' }}>
            {promptTemplate[0]?.text?.slice(0, 60)}...
          </div>
        )}
        {expectedKeys && expectedKeys.length > 0 && (
          <div style={{ marginTop: 4 }}>
            {expectedKeys.map((k) => (
              <span
                key={k}
                style={{
                  display: 'inline-block',
                  background: '#e6f7ff',
                  color: '#1890ff',
                  padding: '0 4px',
                  borderRadius: 3,
                  marginRight: 4,
                  fontSize: 10,
                }}
              >
                {k}
              </span>
            ))}
          </div>
        )}
      </div>
    </BaseNode>
  )
})
