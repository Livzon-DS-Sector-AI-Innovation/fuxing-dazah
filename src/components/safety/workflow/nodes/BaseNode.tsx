'use client'

import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'

/**
 * Common wrapper for all workflow node types.
 * Provides source/target handles and consistent card styling.
 */

interface BaseNodeData {
  title: string
  type: string
  [key: string]: unknown
}

export interface BaseNodeProps extends NodeProps {
  data: BaseNodeData
}

export const BaseNode = memo(function BaseNode({
  data,
  selected,
  children,
  headerColor = '#1890ff',
  outputHandles = true,
  inputHandles = true,
}: BaseNodeProps & {
  children?: React.ReactNode
  headerColor?: string
  outputHandles?: boolean
  inputHandles?: boolean
}) {
  return (
    <div
      style={{
        minWidth: 200,
        maxWidth: 280,
        borderRadius: 8,
        border: selected ? '2px solid #1890ff' : '1px solid #d9d9d9',
        boxShadow: selected ? '0 0 0 2px rgba(24,144,255,0.2)' : '0 1px 3px rgba(0,0,0,0.1)',
        background: '#fff',
        fontSize: 13,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '6px 12px',
          borderRadius: '7px 7px 0 0',
          background: headerColor,
          color: '#fff',
          fontWeight: 600,
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span>{data.title || data.type}</span>
      </div>

      {/* Body */}
      <div style={{ padding: '8px 12px' }}>
        {children || (
          <span style={{ color: '#999', fontSize: 12 }}>
            {data.type}
          </span>
        )}
      </div>

      {/* Handles */}
      {inputHandles && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ background: '#999', width: 8, height: 8 }}
        />
      )}
      {outputHandles && (
        <Handle
          type="source"
          position={Position.Right}
          style={{ background: headerColor, width: 8, height: 8 }}
        />
      )}
    </div>
  )
})
