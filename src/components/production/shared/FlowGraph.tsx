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

/** dagre LR 自动布局：固定节点尺寸，中心点坐标转 React Flow 的左上角锚点 */
export function layoutGraph(
  nodes: Node[],
  edges: Edge[],
  nodeW = DEFAULT_W,
  nodeH = DEFAULT_H,
): Node[] {
  const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', ranksep: 60, nodesep: 40 })
  nodes.forEach(n => g.setNode(n.id, { width: nodeW, height: nodeH }))
  edges.forEach(e => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return nodes.map(n => {
    const pos = g.node(n.id)
    return {
      ...n,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      position: { x: pos.x - nodeW / 2, y: pos.y - nodeH / 2 },
    }
  })
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
