'use client'

import { useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'

const DEFAULT_W = 200
const DEFAULT_H = 76

// ── 物料节点常量与类型 ──
export const MATERIAL_INPUT = 'materialInputNode' as const
export const MATERIAL_OUTPUT = 'materialOutputNode' as const
export const MATERIAL_NODE_W = 140
const MATERIAL_GAP_X = 40
const MATERIAL_TITLE_H = 28
const MATERIAL_ROW_H = 20
const MATERIAL_PAD_B = 8

const MATERIAL_COLORS = {
  input: {
    border: '#dd5b00',
    bg: '#fef0e6',
    label: '物料消耗',
    handleType: 'source' as const,
    handlePosition: Position.Right,
    handleId: 'material-source',
  },
  output: {
    border: '#1aae39',
    bg: '#e6f9eb',
    label: '产出物',
    handleType: 'target' as const,
    handlePosition: Position.Left,
    handleId: 'material-target',
  },
}

export interface MaterialNodeData {
  parentNodeId: string
  direction: 'input' | 'output'
  materials: Array<{ name: string }>
}

/** 物料节点组件 — direction 决定外观（input=消耗/左侧, output=产出物/右侧） */
export function MaterialNode({ data }: NodeProps) {
  // ponytail: xyflow Node.data 为 Record<string, unknown>，无法直接 typed cast
  const d = data as unknown as MaterialNodeData
  const c = MATERIAL_COLORS[d.direction] ?? MATERIAL_COLORS.input
  return (
    <div
      style={{
        width: MATERIAL_NODE_W,
        background: '#fff',
        border: `1px solid ${c.border}`,
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: MATERIAL_TITLE_H,
          background: c.bg,
          display: 'flex',
          alignItems: 'center',
          padding: '0 8px',
          fontSize: 12,
          fontWeight: 500,
          color: c.border,
        }}
      >
        {c.label}
      </div>
      <div style={{ padding: '4px 8px' }}>
        {d.materials.map((m, i) => (
          <div key={i} style={{ fontSize: 12, color: '#37352f', lineHeight: '20px' }}>
            {m.name}
          </div>
        ))}
      </div>
      <Handle
        type={c.handleType}
        position={c.handlePosition}
        id={c.handleId}
        style={{ background: c.border, width: 6, height: 6 }}
      />
    </div>
  )
}

/** dagre TB 自动布局：工序节点由 dagre 排列，物料节点相对于父工序节点偏移定位 */
export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  nodeW = DEFAULT_W,
  nodeH = DEFAULT_H,
): Node[] {
  const processNodes = nodes.filter(
    n => n.type !== MATERIAL_INPUT && n.type !== MATERIAL_OUTPUT,
  )
  const materialNodes = nodes.filter(
    n => n.type === MATERIAL_INPUT || n.type === MATERIAL_OUTPUT,
  )

  // dagre 仅对工序节点和工序间连线布局
  const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', ranksep: 60, nodesep: 40 })
  processNodes.forEach(n => g.setNode(n.id, { width: nodeW, height: nodeH }))

  // ponytail: Set 成员判断，不需要完整 typeMap
  const materialIds = new Set(materialNodes.map(n => n.id))
  edges
    .filter(e => !materialIds.has(e.source) && !materialIds.has(e.target))
    .forEach(e => g.setEdge(e.source, e.target))
  dagre.layout(g)

  const laidOut = processNodes.map(n => {
    const pos = g.node(n.id)
    if (!pos) return n
    return {
      ...n,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      position: { x: pos.x - nodeW / 2, y: pos.y - nodeH / 2 },
    }
  })

  // ponytail: Map O(1) 取代 Array.find O(n)
  const parentMap = new Map(laidOut.map(n => [n.id, n]))

  const positionedMaterials = materialNodes.map(n => {
    const { parentNodeId: parentId, direction, materials } = n.data as unknown as MaterialNodeData
    if (!parentId) return n
    const parent = parentMap.get(parentId)
    if (!parent) {
      console.warn(`物料节点 "${n.id}" 的父工序节点 "${parentId}" 未找到`)
      return n
    }
    const estH = MATERIAL_TITLE_H + (materials?.length ?? 0) * MATERIAL_ROW_H + MATERIAL_PAD_B
    const offsetY = (nodeH - estH) / 2
    const x =
      direction === 'input'
        ? parent.position.x - MATERIAL_NODE_W - MATERIAL_GAP_X
        : parent.position.x + nodeW + MATERIAL_GAP_X
    return { ...n, position: { x, y: parent.position.y + offsetY } }
  })

  return [...laidOut, ...positionedMaterials]
}

interface FlowGraphProps {
  nodes: Node[]
  edges: Edge[]
  nodeTypes: NodeTypes
  onNodeClick?: (id: string) => void
  height?: number | string
}

export function FlowGraph({
  nodes,
  edges,
  nodeTypes,
  onNodeClick,
  height = 420,
}: FlowGraphProps) {
  const laidOut = useMemo(() => layoutGraph(nodes, edges), [nodes, edges])
  return (
    <div style={{ height, width: '100%' }}>
      <ReactFlow
        nodes={laidOut}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          // 物料节点不触发点击回调
          if (node.type !== MATERIAL_INPUT && node.type !== MATERIAL_OUTPUT) {
            onNodeClick?.(node.id)
          }
        }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
