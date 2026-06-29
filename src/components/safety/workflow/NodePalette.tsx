'use client'

import { memo } from 'react'
import { Typography } from 'antd'
import { NODE_TYPES } from '@/types/safety'

const { Text, Title } = Typography

/**
 * Drag-and-drop palette for workflow node types.
 * Each item is draggable and can be dropped onto the WorkflowCanvas.
 */

export const NodePalette = memo(function NodePalette() {
  const onDragStart = (event: React.DragEvent, nodeType: string) => {
    event.dataTransfer.setData('application/reactflow-type', nodeType)
    event.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div
      style={{
        width: 180,
        padding: 12,
        borderRight: '1px solid #f0f0f0',
        background: '#fafafa',
      }}
    >
      <Title level={5} style={{ margin: 0, marginBottom: 12, fontSize: 14 }}>
        节点类型
      </Title>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 12 }}>
        拖放节点到画布
      </Text>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {NODE_TYPES.map((nt) => (
          <div
            key={nt.type}
            draggable
            onDragStart={(e) => onDragStart(e, nt.type)}
            title={nt.description}
            style={{
              padding: '8px 10px',
              borderRadius: 6,
              border: `1px solid ${nt.color}33`,
              borderLeft: `4px solid ${nt.color}`,
              background: '#fff',
              cursor: 'grab',
              fontSize: 12,
              fontWeight: 500,
              color: '#333',
              transition: 'box-shadow 0.15s',
              userSelect: 'none',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = `0 2px 8px ${nt.color}33`
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = ''
            }}
          >
            {nt.label}
            <div style={{ fontSize: 10, color: '#999', fontWeight: 400, marginTop: 2 }}>
              {nt.description}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
})
