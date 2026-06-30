'use client'

import { create } from 'zustand'
import type { SafetyKnowledgeArticle, SafetyKnowledgeArticleQueryParams } from '@/types/safety'

interface KnowledgeState {
  items: SafetyKnowledgeArticle[]
  currentItem: SafetyKnowledgeArticle | null
  queryParams: SafetyKnowledgeArticleQueryParams
  total: number
  loading: boolean
  setItems: (items: SafetyKnowledgeArticle[]) => void
  setCurrentItem: (item: SafetyKnowledgeArticle | null) => void
  setQueryParams: (params: Partial<SafetyKnowledgeArticleQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SafetyKnowledgeArticle) => void
  updateItem: (id: string, updates: Partial<SafetyKnowledgeArticle>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SafetyKnowledgeArticle[],
  currentItem: null as SafetyKnowledgeArticle | null,
  queryParams: { page: 1, page_size: 20 } as SafetyKnowledgeArticleQueryParams,
  total: 0,
  loading: false,
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

  reset: () => set(initialState),
}))
