'use client'

import { create } from 'zustand'
import type { GraphNode, GraphEdge, FullGraphData } from '@/types/safety'

interface KnowledgeGraphState {
  // 图数据
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: FullGraphData['stats'] | null

  // 选中
  selectedNodeId: string | null
  selectedEdgeId: string | null

  // 搜索
  searchQuery: string
  searchResults: GraphNode[]

  // 筛选
  nodeTypeFilter: string | null
  relationTypeFilter: string | null
  statusFilter: string | null

  // 状态
  loading: boolean
  generating: boolean
  error: string | null

  // 画布
  viewport: { x: number; y: number; zoom: number }

  // Actions
  setGraphData: (data: FullGraphData) => void
  selectNode: (nodeId: string | null) => void
  selectEdge: (edgeId: string | null) => void
  setSearchQuery: (query: string) => void
  setSearchResults: (results: GraphNode[]) => void
  setNodeTypeFilter: (filter: string | null) => void
  setRelationTypeFilter: (filter: string | null) => void
  setStatusFilter: (filter: string | null) => void
  setLoading: (loading: boolean) => void
  setGenerating: (generating: boolean) => void
  setError: (error: string | null) => void
  setViewport: (viewport: { x: number; y: number; zoom: number }) => void
  reset: () => void
}

const initialState = {
  nodes: [],
  edges: [],
  stats: null,
  selectedNodeId: null,
  selectedEdgeId: null,
  searchQuery: '',
  searchResults: [],
  nodeTypeFilter: null,
  relationTypeFilter: null,
  statusFilter: null,
  loading: false,
  generating: false,
  error: null,
  viewport: { x: 0, y: 0, zoom: 1 },
}

export const useKnowledgeGraphStore = create<KnowledgeGraphState>((set) => ({
  ...initialState,

  setGraphData: (data) =>
    set({
      nodes: data.nodes,
      edges: data.edges,
      stats: data.stats,
      loading: false,
      error: null,
    }),

  selectNode: (nodeId) => set({ selectedNodeId: nodeId, selectedEdgeId: null }),

  selectEdge: (edgeId) => set({ selectedEdgeId: edgeId, selectedNodeId: null }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setSearchResults: (results) => set({ searchResults: results }),

  setNodeTypeFilter: (filter) => set({ nodeTypeFilter: filter }),

  setRelationTypeFilter: (filter) => set({ relationTypeFilter: filter }),

  setStatusFilter: (filter) => set({ statusFilter: filter }),

  setLoading: (loading) => set({ loading }),

  setGenerating: (generating) => set({ generating }),

  setError: (error) => set({ error }),

  setViewport: (viewport) => set({ viewport }),

  reset: () => set(initialState),
}))
