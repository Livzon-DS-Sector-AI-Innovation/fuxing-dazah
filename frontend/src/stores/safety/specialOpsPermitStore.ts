'use client'

import { create } from 'zustand'
import type { SpecialOperationPermit, SpecialOperationPermitQueryParams } from '@/types/safety'

interface SpecialOpsPermitState {
  items: SpecialOperationPermit[]
  currentItem: SpecialOperationPermit | null
  queryParams: SpecialOperationPermitQueryParams
  total: number
  loading: boolean
  setItems: (items: SpecialOperationPermit[]) => void
  setCurrentItem: (item: SpecialOperationPermit | null) => void
  setQueryParams: (params: Partial<SpecialOperationPermitQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SpecialOperationPermit) => void
  updateItem: (id: string, updates: Partial<SpecialOperationPermit>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SpecialOperationPermit[],
  currentItem: null as SpecialOperationPermit | null,
  queryParams: { page: 1, page_size: 20 } as SpecialOperationPermitQueryParams,
  total: 0,
  loading: false,
}

export const useSpecialOpsPermitStore = create<SpecialOpsPermitState>((set) => ({
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
