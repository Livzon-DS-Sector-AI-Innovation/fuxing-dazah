'use client'

import { create } from 'zustand'
import type { DailyRiskReport, DailyRiskReportQueryParams } from '@/types/safety'

interface DailyRiskReportState {
  items: DailyRiskReport[]
  currentItem: DailyRiskReport | null
  queryParams: DailyRiskReportQueryParams
  total: number
  loading: boolean
  setItems: (items: DailyRiskReport[]) => void
  setCurrentItem: (item: DailyRiskReport | null) => void
  setQueryParams: (params: Partial<DailyRiskReportQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: DailyRiskReport) => void
  updateItem: (id: string, updates: Partial<DailyRiskReport>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as DailyRiskReport[],
  currentItem: null as DailyRiskReport | null,
  queryParams: { page: 1, page_size: 20 } as DailyRiskReportQueryParams,
  total: 0,
  loading: false,
}

export const useDailyRiskReportStore = create<DailyRiskReportState>((set) => ({
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
