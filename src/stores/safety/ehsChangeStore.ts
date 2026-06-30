'use client'

import { create } from 'zustand'
import type { EhsChange, EhsChangeQueryParams } from '@/types/safety'

interface EhsChangeState {
  items: EhsChange[]
  currentItem: EhsChange | null
  queryParams: EhsChangeQueryParams
  total: number
  loading: boolean
  setItems: (items: EhsChange[]) => void
  setCurrentItem: (item: EhsChange | null) => void
  setQueryParams: (params: Partial<EhsChangeQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: EhsChange) => void
  updateItem: (id: string, updates: Partial<EhsChange>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as EhsChange[],
  currentItem: null as EhsChange | null,
  queryParams: { page: 1, page_size: 20 } as EhsChangeQueryParams,
  total: 0,
  loading: false,
}

export const useEhsChangeStore = create<EhsChangeState>((set) => ({
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
      items: state.items.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((c) => c.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
