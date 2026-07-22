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

  // 搜索
  searchQuery: string
  searchResults: GraphNode[]

  // 筛选
  nodeTypeFilter: string | null
  statusFilter: string | null

  // 树展开状态
  expandedKeys: Set<string>

  // 状态
  loading: boolean
  generating: boolean
  error: string | null

  // Actions
  setGraphData: (data: FullGraphData) => void
  selectNode: (nodeId: string | null) => void
  setSearchQuery: (query: string) => void
  setSearchResults: (results: GraphNode[]) => void
  setNodeTypeFilter: (filter: string | null) => void
  setStatusFilter: (filter: string | null) => void
  setExpandedKeys: (keys: Set<string>) => void
  toggleExpanded: (nodeId: string) => void
  setLoading: (loading: boolean) => void
  setGenerating: (generating: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
}

const initialState = {
  nodes: [],
  edges: [],
  stats: null,
  selectedNodeId: null,
  searchQuery: '',
  searchResults: [],
  nodeTypeFilter: null,
  statusFilter: null,
  expandedKeys: new Set<string>(),
  loading: false,
  generating: false,
  error: null,
}

export const useKnowledgeGraphStore = create<KnowledgeGraphState>((set, get) => ({
  ...initialState,

  setGraphData: (data) =>
    set({
      nodes: data.nodes,
      edges: data.edges,
      stats: data.stats,
      loading: false,
      error: null,
    }),

  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setSearchResults: (results) => set({ searchResults: results }),

  setNodeTypeFilter: (filter) => set({ nodeTypeFilter: filter }),

  setStatusFilter: (filter) => set({ statusFilter: filter }),

  setExpandedKeys: (keys) => set({ expandedKeys: keys }),

  toggleExpanded: (nodeId) => {
    const current = get().expandedKeys
    const next = new Set(current)
    if (next.has(nodeId)) {
      next.delete(nodeId)
    } else {
      next.add(nodeId)
    }
    set({ expandedKeys: next })
  },

  setLoading: (loading) => set({ loading }),

  setGenerating: (generating) => set({ generating }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
}))
