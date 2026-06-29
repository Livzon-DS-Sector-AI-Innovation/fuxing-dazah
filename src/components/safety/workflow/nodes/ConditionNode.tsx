'use client'

import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'

/**
 * If/Else condition node with multiple output handles.
 * Orange header. One source handle per condition branch.
 */

interface Condition {
  variable_selector?: string[]
  operator?: string
  value?: string
}

export const ConditionNode = memo(function ConditionNode(props: NodeProps) {
  const { data, selected } = props
  const conditions = (data.conditions as Condition[]) || []
  const title = (data.title as string) || 'If/Else'

  return (
    <div
      style={{
        minWidth: 200,
        maxWidth: 280,
        borderRadius: 8,
        border: selected ? '2px solid #fa8c16' : '1px solid #d9d9d9',
        boxShadow: selected ? '0 0 0 2px rgba(250,140,22,0.2)' : '0 1px 3px rgba(0,0,0,0.1)',
        background: '#fff',
        fontSize: 13,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '6px 12px',
          borderRadius: '7px 7px 0 0',
          background: '#fa8c16',
          color: '#fff',
          fontWeight: 600,
          fontSize: 13,
        }}
      >
        {title}
      </div>

      {/* Body */}
      <div style={{ padding: '8px 12px' }}>
        {conditions.length > 0 ? (
          <div style={{ fontSize: 12, lineHeight: 1.6 }}>
            {conditions.map((cond, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 4,
                  padding: '2px 6px',
                  background: '#fff7e6',
                  borderRadius: 3,
                  position: 'relative',
                }}
              >
                <span>
                  {cond.variable_selector ? (
                    <code style={{ fontSize: 10, color: '#d46b08' }}>
                      {'{{#'}{cond.variable_selector.join('.')}{'#}}'}
                    </code>
                  ) : (
                    <span style={{ color: '#999' }}>IF</span>
                  )}
                  <span style={{ margin: '0 4px', color: '#666' }}>
                    {cond.operator || '=='}
                  </span>
                  <span style={{ color: '#d46b08' }}>{cond.value || '?'}</span>
                </span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={`branch-${i}`}
                  style={{
                    background: '#fa8c16',
                    width: 8,
                    height: 8,
                    position: 'relative',
                    right: -8,
                  }}
                />
              </div>
            ))}
          </div>
        ) : (
          <span style={{ color: '#999', fontSize: 12 }}>未配置条件</span>
        )}
      </div>

      {/* Target handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: '#999', width: 8, height: 8 }}
      />
      {/* Default source handle for the "else" branch */}
      <Handle
        type="source"
        position={Position.Right}
        id="default"
        style={{ background: '#d9d9d9', width: 8, height: 8 }}
      />
    </div>
  )
})
