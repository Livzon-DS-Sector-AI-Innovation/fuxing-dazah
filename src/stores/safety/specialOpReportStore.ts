'use client'

import { create } from 'zustand'
import type { SpecialOperationReport, SpecialOperationReportQueryParams } from '@/types/safety'

interface SpecialOpReportState {
  items: SpecialOperationReport[]
  currentItem: SpecialOperationReport | null
  queryParams: SpecialOperationReportQueryParams
  total: number
  loading: boolean
  setItems: (items: SpecialOperationReport[]) => void
  setCurrentItem: (item: SpecialOperationReport | null) => void
  setQueryParams: (params: Partial<SpecialOperationReportQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SpecialOperationReport) => void
  updateItem: (id: string, updates: Partial<SpecialOperationReport>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SpecialOperationReport[],
  currentItem: null as SpecialOperationReport | null,
  queryParams: { page: 1, page_size: 20 } as SpecialOperationReportQueryParams,
  total: 0,
  loading: false,
}

export const useSpecialOpReportStore = create<SpecialOpReportState>((set) => ({
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
