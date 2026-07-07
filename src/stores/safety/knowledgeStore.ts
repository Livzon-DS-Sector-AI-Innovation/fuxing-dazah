'use client'

import { create } from 'zustand'
import type { SafetyKnowledgeArticle, SafetyKnowledgeArticleQueryParams } from '@/types/safety'

interface KnowledgeState {
  items: SafetyKnowledgeArticle[]
  currentItem: SafetyKnowledgeArticle | null
  queryParams: SafetyKnowledgeArticleQueryParams
  total: number
  loading: boolean
  selectedRowKeys: string[]
  cardStatusFilter: string | undefined
  setItems: (items: SafetyKnowledgeArticle[]) => void
  setCurrentItem: (item: SafetyKnowledgeArticle | null) => void
  setQueryParams: (params: Partial<SafetyKnowledgeArticleQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SafetyKnowledgeArticle) => void
  updateItem: (id: string, updates: Partial<SafetyKnowledgeArticle>) => void
  removeItem: (id: string) => void
  setSelectedRowKeys: (keys: string[]) => void
  setCardStatusFilter: (filter: string | undefined) => void
  reset: () => void
}

const initialState = {
  items: [] as SafetyKnowledgeArticle[],
  currentItem: null as SafetyKnowledgeArticle | null,
  queryParams: { page: 1, page_size: 200 } as SafetyKnowledgeArticleQueryParams,
  total: 0,
  loading: false,
  selectedRowKeys: [] as string[],
  cardStatusFilter: undefined as string | undefined,
}

export const useKnowledgeStore = create<KnowledgeState>((set) => ({
  ...initialState,

  setItems: (items) => set({ items }),
  setCurrentItem: (currentItem) => set({ currentItem }),
  setQueryParams: (params) =>
    set((state) => ({ queryParams: { ...state.queryParams, ...params } })),
  setTotal: (total) => set({ total }),
  setLoading: (loading) => set({ loading }),

  addItem: (item) => set((state) => ({ items: [item, ...state.items] })),
  updateItem: (id, updates) =>
    set((state) => ({
      items: state.items.map((a) => (a.id === id ? { ...a, ...updates } : a)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((a) => a.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),
  setSelectedRowKeys: (selectedRowKeys) => set({ selectedRowKeys }),
  setCardStatusFilter: (cardStatusFilter) => set({ cardStatusFilter }),

  reset: () => set(initialState),
}))
