'use client'

import { create } from 'zustand'
import type { OperationRegulation, OperationRegulationQueryParams } from '@/types/safety'

interface RegulationState {
  items: OperationRegulation[]
  currentItem: OperationRegulation | null
  queryParams: OperationRegulationQueryParams
  total: number
  loading: boolean
  setItems: (items: OperationRegulation[]) => void
  setCurrentItem: (item: OperationRegulation | null) => void
  setQueryParams: (params: Partial<OperationRegulationQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: OperationRegulation) => void
  updateItem: (id: string, updates: Partial<OperationRegulation>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as OperationRegulation[],
  currentItem: null as OperationRegulation | null,
  queryParams: { page: 1, page_size: 20 } as OperationRegulationQueryParams,
  total: 0,
  loading: false,
}

export const useRegulationStore = create<RegulationState>((set) => ({
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
