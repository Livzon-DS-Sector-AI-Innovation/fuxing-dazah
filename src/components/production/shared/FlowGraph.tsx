'use client'

import { useMemo } from 'react'
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'

const DEFAULT_W = 200
const DEFAULT_H = 76

const MATERIAL_INPUT = 'materialInputNode'
const MATERIAL_OUTPUT = 'materialOutputNode'
const MATERIAL_NODE_W = 140

/** dagre TB 自动布局：工序节点由 dagre 排列，物料节点相对于父工序节点偏移定位 */
export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  nodeW = DEFAULT_W,
  nodeH = DEFAULT_H,
): Node[] {
  // 分离工序节点和物料节点
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
  edges
    .filter(e => {
      const srcType = nodes.find(n => n.id === e.source)?.type
      const tgtType = nodes.find(n => n.id === e.target)?.type
      return srcType !== MATERIAL_INPUT && srcType !== MATERIAL_OUTPUT
        && tgtType !== MATERIAL_INPUT && tgtType !== MATERIAL_OUTPUT
    })
    .forEach(e => g.setEdge(e.source, e.target))
  dagre.layout(g)

  // 工序节点应用 dagre 位置
  const laidOut = processNodes.map(n => {
    const pos = g.node(n.id)
    return {
      ...n,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      position: { x: pos.x - nodeW / 2, y: pos.y - nodeH / 2 },
    }
  })

  // 物料节点相对于父工序节点偏移定位
  const positionedMaterials = materialNodes.map(n => {
    const parentId = (n.data as Record<string, unknown>).parentNodeId as string
    const direction = (n.data as Record<string, unknown>).direction as string
    const parent = laidOut.find(p => p.id === parentId)
    if (!parent) return { ...n, position: { x: 0, y: 0 } }
    // 估计物料节点高度：标题栏 + N 行物料名
    const materials = (n.data as Record<string, unknown>).materials as Array<{ name: string }> ?? []
    const estH = 28 + materials.length * 20 + 8
    const offsetY = (nodeH - estH) / 2 // 垂直居中
    if (direction === 'input') {
      return { ...n, position: { x: parent.position.x - MATERIAL_NODE_W - 40, y: parent.position.y + offsetY } }
    }
    return { ...n, position: { x: parent.position.x + nodeW + 40, y: parent.position.y + offsetY } }
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
        onNodeClick={(_, node) => onNodeClick?.(node.id)}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
