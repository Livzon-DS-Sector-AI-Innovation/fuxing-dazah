'use client'

import { create } from 'zustand'
import type {
  SpecialOperationPersonnel,
  SpecialOperationPersonnelQueryParams,
} from '@/types/safety'

interface SpecialOpsPersonnelState {
  items: SpecialOperationPersonnel[]
  currentItem: SpecialOperationPersonnel | null
  queryParams: SpecialOperationPersonnelQueryParams
  total: number
  loading: boolean
  setItems: (items: SpecialOperationPersonnel[]) => void
  setCurrentItem: (item: SpecialOperationPersonnel | null) => void
  setQueryParams: (params: Partial<SpecialOperationPersonnelQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SpecialOperationPersonnel) => void
  updateItem: (id: string, updates: Partial<SpecialOperationPersonnel>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SpecialOperationPersonnel[],
  currentItem: null as SpecialOperationPersonnel | null,
  queryParams: { page: 1, page_size: 20 } as SpecialOperationPersonnelQueryParams,
  total: 0,
  loading: false,
}

export const useSpecialOpsPersonnelStore = create<SpecialOpsPersonnelState>((set) => ({
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
      items: state.items.map((p) => (p.id === id ? { ...p, ...updates } : p)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((p) => p.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
