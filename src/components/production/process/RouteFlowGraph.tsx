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
      <Handle type="target" position={Position.Top} id="top" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} id="left-target" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Right} id="right-target" style={{ opacity: 0 }} />
      <div style={{ height: 6, background: stageTint(d.stage_name) }} />
      <div style={{ padding: '8px 12px' }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: '#1a1a1a' }}>{d.name}</div>
        <div style={{ fontSize: 12, color: '#787671', display: 'flex', gap: 8 }}>
          <span>{d.node_code}</span>
          {d.stage_name && <span>{d.stage_name}</span>}
          <span>{d.fieldCount} 字段</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Left} id="left-source" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="right-source" style={{ opacity: 0 }} />
    </div>
  )
}

// ── 物料节点数据 ──
type MaterialNodeData = {
  parentNodeId: string
  direction: 'input' | 'output'
  materials: { name: string }[]
}

// ── 物料消耗节点（工序左侧） ──
function MaterialInputNode({ data }: NodeProps) {
  const d = data as unknown as MaterialNodeData
  return (
    <div
      style={{
        width: 140,
        background: '#fff',
        border: '1px solid #dd5b00',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: 28,
          background: '#fef0e6',
          display: 'flex',
          alignItems: 'center',
          padding: '0 8px',
          fontSize: 12,
          fontWeight: 500,
          color: '#dd5b00',
        }}
      >
        物料消耗
      </div>
      <div style={{ padding: '4px 8px' }}>
        {d.materials.map((m, i) => (
          <div
            key={i}
            style={{ fontSize: 12, color: '#37352f', lineHeight: '20px' }}
          >
            {m.name}
          </div>
        ))}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        id="material-source"
        style={{ background: '#dd5b00', width: 6, height: 6 }}
      />
    </div>
  )
}

// ── 产出物料节点（工序右侧） ──
function MaterialOutputNode({ data }: NodeProps) {
  const d = data as unknown as MaterialNodeData
  return (
    <div
      style={{
        width: 140,
        background: '#fff',
        border: '1px solid #1aae39',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: 28,
          background: '#e6f9eb',
          display: 'flex',
          alignItems: 'center',
          padding: '0 8px',
          fontSize: 12,
          fontWeight: 500,
          color: '#1aae39',
        }}
      >
        产出物
      </div>
      <div style={{ padding: '4px 8px' }}>
        {d.materials.map((m, i) => (
          <div
            key={i}
            style={{ fontSize: 12, color: '#37352f', lineHeight: '20px' }}
          >
            {m.name}
          </div>
        ))}
      </div>
      <Handle
        type="target"
        position={Position.Left}
        id="material-target"
        style={{ background: '#1aae39', width: 6, height: 6 }}
      />
    </div>
  )
}

const nodeTypes = {
  processNode: ProcessNode,
  materialInputNode: MaterialInputNode,
  materialOutputNode: MaterialOutputNode,
}

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

  // ── 为有 intermediates 的工序生成物料节点 ──
  const materialEdges: Edge[] = []
  for (const n of nodes) {
    const intermediates = n.intermediates ?? []
    const inputs = intermediates.filter(i => i.direction === 'input')
    const outputs = intermediates.filter(i => i.direction === 'output')

    if (inputs.length > 0) {
      const inputNodeId = `${n.id}__material-input`
      rfNodes.push({
        id: inputNodeId,
        type: 'materialInputNode',
        position: { x: 0, y: 0 },
        data: {
          parentNodeId: n.id,
          direction: 'input',
          materials: inputs.map(i => ({ name: i.intermediate_type_name || i.intermediate_type_id })),
        } satisfies MaterialNodeData,
      })
      materialEdges.push({
        id: `${n.id}__material-input-edge`,
        source: inputNodeId,
        target: n.id,
        sourceHandle: 'material-source',
        targetHandle: 'left-target',
        type: 'straight',
        style: { stroke: '#dd5b00', strokeDasharray: '4 3', strokeWidth: 1.5 },
      })
    }

    if (outputs.length > 0) {
      const outputNodeId = `${n.id}__material-output`
      rfNodes.push({
        id: outputNodeId,
        type: 'materialOutputNode',
        position: { x: 0, y: 0 },
        data: {
          parentNodeId: n.id,
          direction: 'output',
          materials: outputs.map(i => ({ name: i.intermediate_type_name || i.intermediate_type_id })),
        } satisfies MaterialNodeData,
      })
      materialEdges.push({
        id: `${n.id}__material-output-edge`,
        source: n.id,
        target: outputNodeId,
        sourceHandle: 'right-source',
        targetHandle: 'material-target',
        type: 'straight',
        style: { stroke: '#1aae39', strokeDasharray: '4 3', strokeWidth: 1.5 },
      })
    }
  }

  const rfEdges: Edge[] = [
    ...edges.map(e => {
      const isRework = e.edge_type === 'rework'
      const isBoundary = e.is_batch_boundary
      return {
        id: e.id,
        source: e.from_node_id,
        target: e.to_node_id,
        type: 'smoothstep',
        animated: true,
        sourceHandle: isRework ? 'right-source' : 'bottom',
        targetHandle: isRework ? 'right-target' : 'top',
        pathOptions: isRework ? { borderRadius: 18, offset: 30 } : undefined,
        label: isBoundary ? '批次边界' : isRework ? '回流' : undefined,
        labelStyle: { fontSize: 11, fill: isRework ? '#dd5b00' : '#5645d4' },
        style: isRework
          ? { stroke: '#dd5b00', strokeDasharray: '6 4', strokeWidth: 2 }
          : isBoundary
            ? { stroke: '#5645d4', strokeWidth: 2.5 }
            : { stroke: '#b8b6b1' },
      }
    }),
    ...materialEdges,
  ]

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
      onNodeClick={onNodeClick ? (id) => { if (!id.includes('__material-')) onNodeClick(id) } : undefined}
      height={460}
    />
  )
}
