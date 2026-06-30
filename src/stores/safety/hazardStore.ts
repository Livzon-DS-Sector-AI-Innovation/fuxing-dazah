'use client'

import { create } from 'zustand'
import type { HazardReport, HazardReportQueryParams } from '@/types/safety'

interface HazardState {
  items: HazardReport[]
  currentItem: HazardReport | null
  queryParams: HazardReportQueryParams
  total: number
  loading: boolean
  setItems: (items: HazardReport[]) => void
  setCurrentItem: (item: HazardReport | null) => void
  setQueryParams: (params: Partial<HazardReportQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: HazardReport) => void
  updateItem: (id: string, updates: Partial<HazardReport>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as HazardReport[],
  currentItem: null as HazardReport | null,
  queryParams: { page: 1, page_size: 20 } as HazardReportQueryParams,
  total: 0,
  loading: false,
}

export const useHazardStore = create<HazardState>((set) => ({
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
      items: state.items.map((h) => (h.id === id ? { ...h, ...updates } : h)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((h) => h.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
