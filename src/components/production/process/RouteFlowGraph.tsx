'use client'

import { useMemo } from 'react'
import { Handle, Position, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { FlowGraph } from '../shared/FlowGraph'
import type { RouteEdge, RouteNode } from '@/types/production'

// 工段 pastel 色板（与 DESIGN.md pastel tint 对齐，如有出入以 DESIGN.md 为准）
const STAGE_TINTS = ['#f6e5d8', '#f8e0e6', '#dff2e4', '#e8e4f6', '#ddedf8', '#f8f0d8']

function stageTint(stage: string | null): string {
  if (!stage) return '#f6f5f4'
  let h = 0
  for (let i = 0; i < stage.length; i++) h = stage.charCodeAt(i) + ((h << 5) - h)
  return STAGE_TINTS[Math.abs(h) % STAGE_TINTS.length]
}

type ProcessNodeData = {
  name: string
  node_code: string
  stage_name: string | null
  fieldCount: number
}

function ProcessNode({ data, selected }: NodeProps) {
  const d = data as ProcessNodeData
  return (
    <div
      style={{
        width: 200,
        background: '#fff',
        border: selected ? '2px solid #5645d4' : '1px solid #e5e3df',
        borderRadius: 12,
        overflow: 'hidden',
        cursor: 'pointer',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div style={{ height: 6, background: stageTint(d.stage_name) }} />
      <div style={{ padding: '8px 12px' }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: '#1a1a1a' }}>{d.name}</div>
        <div style={{ fontSize: 12, color: '#787671', display: 'flex', gap: 8 }}>
          <span>{d.node_code}</span>
          {d.stage_name && <span>{d.stage_name}</span>}
          <span>{d.fieldCount} 字段</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  )
}

const nodeTypes = { processNode: ProcessNode }

export function toRouteFlowElements(
  nodes: RouteNode[],
  edges: RouteEdge[],
): { rfNodes: Node[]; rfEdges: Edge[] } {
  const rfNodes: Node[] = nodes.map(n => ({
    id: n.id,
    type: 'processNode',
    position: { x: 0, y: 0 }, // layoutGraph 会覆盖
    data: {
      name: n.name,
      node_code: n.node_code,
      stage_name: n.stage_name,
      fieldCount: n.fields.length,
    },
  }))
  const rfEdges: Edge[] = edges.map(e => {
    const isRework = e.edge_type === 'rework'
    const isBoundary = e.is_batch_boundary
    return {
      id: e.id,
      source: e.from_node_id,
      target: e.to_node_id,
      type: 'smoothstep',
      animated: true,
      label: isBoundary ? '批次边界' : isRework ? '回流' : undefined,
      labelStyle: { fontSize: 11, fill: isRework ? '#dd5b00' : '#5645d4' },
      style: isRework
        ? { stroke: '#dd5b00', strokeDasharray: '6 4' }
        : isBoundary
          ? { stroke: '#5645d4', strokeWidth: 2.5 }
          : { stroke: '#b8b6b1' },
    }
  })
  return { rfNodes, rfEdges }
}

interface Props {
  nodes: RouteNode[]
  edges: RouteEdge[]
  onNodeClick?: (nodeId: string) => void
}

export function RouteFlowGraph({ nodes, edges, onNodeClick }: Props) {
  const { rfNodes, rfEdges } = useMemo(
    () => toRouteFlowElements(nodes, edges),
    [nodes, edges],
  )
  return (
    <FlowGraph
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      height={460}
    />
  )
}
