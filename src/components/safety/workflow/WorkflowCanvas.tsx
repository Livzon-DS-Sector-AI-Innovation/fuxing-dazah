'use client'

import { useCallback, useState, useMemo } from 'react'
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  BackgroundVariant,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { useWorkflowStore } from '@/stores/safety'
import { StartNode } from './nodes/StartNode'
import { EndNode } from './nodes/EndNode'
import { LLMNode } from './nodes/LLMNode'
import { KnowledgeNode } from './nodes/KnowledgeNode'
import { CodeNode } from './nodes/CodeNode'
import { HttpNode } from './nodes/HttpNode'
import { ConditionNode } from './nodes/ConditionNode'
import { TemplateNode } from './nodes/TemplateNode'
import { AggregatorNode } from './nodes/AggregatorNode'
import type { GraphNode, GraphEdge } from '@/types/safety'

const nodeTypes = {
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  'knowledge-retrieval': KnowledgeNode,
  code: CodeNode,
  'http-request': HttpNode,
  'if-else': ConditionNode,
  'template-transform': TemplateNode,
  'variable-aggregator': AggregatorNode,
}

// Convert our GraphNode type to ReactFlow Node type
function toReactFlowNode(node: GraphNode): Node {
  return {
    id: node.id,
    type: node.type,
    position: node.position,
    data: node.data,
  }
}

// Convert ReactFlow Node back to GraphNode
export function fromReactFlowNode(node: Node): GraphNode {
  return {
    id: node.id,
    type: node.type || 'start',
    position: { x: node.position.x, y: node.position.y },
    data: node.data as Record<string, unknown>,
  }
}

export function WorkflowCanvas() {
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null)
  const {
    nodes,
    edges,
    selectedNodeId,
    setNodes,
    setEdges,
    setSelectedNode,
  } = useWorkflowStore()

  const rfNodes = useMemo(() => nodes.map(toReactFlowNode), [nodes])
  const rfEdges = useMemo(() => edges as Edge[], [edges])

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Apply ReactFlow changes to update positions
      const updated = [...rfNodes]
      changes.forEach((change) => {
        if (change.type === 'position' && change.position) {
          const idx = updated.findIndex((n) => n.id === change.id)
          if (idx !== -1) {
            updated[idx] = { ...updated[idx], position: change.position }
          }
        }
      })
      setNodes(updated.map(fromReactFlowNode))
    },
    [rfNodes, setNodes],
  )

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const updated = [...rfEdges]
      changes.forEach((change) => {
        if (change.type === 'remove') {
          const idx = updated.findIndex((e) => e.id === change.id)
          if (idx !== -1) updated.splice(idx, 1)
        }
      })
      setEdges(updated as GraphEdge[])
    },
    [rfEdges, setEdges],
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return
      const newEdge: GraphEdge = {
        id: `e_${connection.source}_${connection.target}_${Date.now()}`,
        source: connection.source,
        target: connection.target,
        sourceHandle: connection.sourceHandle || 'source',
        targetHandle: connection.targetHandle || 'target',
      }
      setEdges([...edges, newEdge])
    },
    [edges, setEdges],
  )

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setSelectedNode(node.id)
    },
    [setSelectedNode],
  )

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [setSelectedNode])

  // Handle drag-and-drop from palette
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      const nodeType = event.dataTransfer.getData('application/reactflow-type')
      if (!nodeType || !rfInstance) return

      const position = rfInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })

      const newNode: GraphNode = {
        id: `${nodeType}_${Date.now()}`,
        type: nodeType,
        position: { x: position.x, y: position.y },
        data: { title: nodeType, type: nodeType },
      }

      setNodes([...nodes, newNode])
      setSelectedNode(newNode.id)
    },
    [nodes, setNodes, setSelectedNode],
  )

  return (
    <div style={{ height: 600, border: '1px solid #d9d9d9', borderRadius: 8 }}>
      <ReactFlow
        onInit={setRfInstance}
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        fitView
        deleteKeyCode={['Backspace', 'Delete']}
        multiSelectionKeyCode="Shift"
        snapToGrid
        snapGrid={[16, 16]}
        defaultEdgeOptions={{
          style: { stroke: '#b1b1b7', strokeWidth: 2 },
          animated: true,
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls />
        <MiniMap
          nodeStrokeWidth={3}
          pannable
          zoomable
          style={{ border: '1px solid #d9d9d9' }}
        />
      </ReactFlow>
    </div>
  )
}
