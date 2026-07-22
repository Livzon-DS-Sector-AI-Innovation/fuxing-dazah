'use client'

import { create } from 'zustand'
import type { RegulationRevision, RegulationRevisionQueryParams } from '@/types/safety'

interface RevisionState {
  items: RegulationRevision[]
  currentItem: RegulationRevision | null
  queryParams: RegulationRevisionQueryParams
  total: number
  loading: boolean
  setItems: (items: RegulationRevision[]) => void
  setCurrentItem: (item: RegulationRevision | null) => void
  setQueryParams: (params: Partial<RegulationRevisionQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: RegulationRevision) => void
  updateItem: (id: string, updates: Partial<RegulationRevision>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as RegulationRevision[],
  currentItem: null as RegulationRevision | null,
  queryParams: { page: 1, page_size: 20 } as RegulationRevisionQueryParams,
  total: 0,
  loading: false,
}

export const useRevisionStore = create<RevisionState>((set) => ({
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
      items: state.items.map((r) => (r.id === id ? { ...r, ...updates } : r)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((r) => r.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
