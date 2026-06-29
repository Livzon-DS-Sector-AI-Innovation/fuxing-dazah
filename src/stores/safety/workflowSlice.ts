'use client'

import { create } from 'zustand'
import type { GraphConfig, GraphEdge, GraphNode, NodeResultEntry } from '@/types/safety'

interface WorkflowStore {
  // Graph editor state
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedNodeId: string | null
  isDirty: boolean

  // Run state
  isRunning: boolean
  runStatus: string | null
  nodeResults: Record<string, NodeResultEntry>

  // Actions
  setNodes: (nodes: GraphNode[]) => void
  setEdges: (edges: GraphEdge[]) => void
  setSelectedNode: (nodeId: string | null) => void
  setDirty: (dirty: boolean) => void
  loadGraph: (graph: GraphConfig) => void
  getGraph: () => GraphConfig
  setIsRunning: (running: boolean) => void
  setNodeResult: (nodeId: string, result: NodeResultEntry) => void
  resetRunState: () => void
}

export const useWorkflowStore = create<WorkflowStore>((set, get) => ({
  // Graph editor state
  nodes: [],
  edges: [],
  selectedNodeId: null,
  isDirty: false,

  // Run state
  isRunning: false,
  runStatus: null,
  nodeResults: {},

  // Actions
  setNodes: (nodes) => set({ nodes, isDirty: true }),
  setEdges: (edges) => set({ edges, isDirty: true }),
  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),
  setDirty: (dirty) => set({ isDirty: dirty }),
  loadGraph: (graph) => {
    set({
      nodes: graph.nodes || [],
      edges: graph.edges || [],
      isDirty: false,
    })
  },
  getGraph: () => {
    const { nodes, edges } = get()
    return { nodes, edges }
  },
  setIsRunning: (running) => set({ isRunning: running }),
  setNodeResult: (nodeId, result) =>
    set((state) => ({
      nodeResults: { ...state.nodeResults, [nodeId]: result },
    })),
  resetRunState: () =>
    set({
      isRunning: false,
      runStatus: null,
      nodeResults: {},
    }),
}))
