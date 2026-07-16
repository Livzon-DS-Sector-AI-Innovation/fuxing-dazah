'use client'

import { useMemo } from 'react'
import { Tag } from 'antd'
import { Handle, Position, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { FlowGraph } from '../shared/FlowGraph'
import { BATCH_STATUS_META } from './BatchTable'
import type { TraceData } from '@/types/production'

type BatchNodeData = {
  batch_no: string
  status: string
  quantity: number | null
  unit: string | null
  isCurrent: boolean
}

function BatchNode({ data }: NodeProps) {
  const d = data as BatchNodeData
  const meta = BATCH_STATUS_META[d.status]
  return (
    <div
      style={{
        width: 200,
        background: '#fff',
        border: d.isCurrent ? '2px solid #5645d4' : '1px solid #e5e3df',
        borderRadius: 12,
        padding: '8px 12px',
        cursor: 'pointer',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ fontWeight: 600, fontSize: 14, color: '#1a1a1a' }}>{d.batch_no}</div>
      <div style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
        <Tag color={meta?.color} style={{ marginRight: 0 }}>
          {meta?.label ?? d.status}
        </Tag>
        {d.quantity != null && (
          <span style={{ color: '#787671' }}>
            {d.quantity} {d.unit ?? ''}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  )
}

const nodeTypes = { batchNode: BatchNode }

interface Props {
  trace: TraceData
  currentBatchId: string
  onBatchClick: (batchId: string, batchNo: string) => void
}

export function TraceGraph({ trace, currentBatchId, onBatchClick }: Props) {
  const { rfNodes, rfEdges } = useMemo(() => {
    const rfNodes: Node[] = trace.batches.map(b => ({
      id: b.id,
      type: 'batchNode',
      position: { x: 0, y: 0 },
      data: {
        batch_no: b.batch_no,
        status: b.status,
        quantity: b.quantity,
        unit: b.unit,
        isCurrent: b.id === currentBatchId,
      },
    }))
    const rfEdges: Edge[] = trace.links.map(l => ({
      id: `${l.parent_batch_id}-${l.child_batch_id}`,
      source: l.parent_batch_id,
      target: l.child_batch_id,
      type: 'smoothstep',
      animated: true,
      label: l.allocated_qty != null ? `${l.allocated_qty}` : undefined,
      labelStyle: { fontSize: 11 },
      style: l.is_deviation
        ? { stroke: '#dd5b00', strokeDasharray: '6 4' }
        : { stroke: '#5645d4' },
    }))
    return { rfNodes, rfEdges }
  }, [trace, currentBatchId])

  return (
    <FlowGraph
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={id => {
        if (id === currentBatchId) return
        const node = rfNodes.find(n => n.id === id)
        if (node) onBatchClick(id, (node.data as BatchNodeData).batch_no)
      }}
      height={260}
    />
  )
}
