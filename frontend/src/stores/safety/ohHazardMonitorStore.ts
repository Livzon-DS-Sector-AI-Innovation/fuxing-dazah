'use client'

import { create } from 'zustand'
import type { OhHazardMonitor, OhHazardMonitorQueryParams } from '@/types/safety'

interface OhHazardMonitorState {
  items: OhHazardMonitor[]
  currentItem: OhHazardMonitor | null
  queryParams: OhHazardMonitorQueryParams
  total: number
  loading: boolean
  setItems: (items: OhHazardMonitor[]) => void
  setCurrentItem: (item: OhHazardMonitor | null) => void
  setQueryParams: (params: Partial<OhHazardMonitorQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: OhHazardMonitor) => void
  updateItem: (id: string, updates: Partial<OhHazardMonitor>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as OhHazardMonitor[],
  currentItem: null as OhHazardMonitor | null,
  queryParams: { page: 1, page_size: 20 } as OhHazardMonitorQueryParams,
  total: 0,
  loading: false,
}

export const useOhHazardMonitorStore = create<OhHazardMonitorState>((set) => ({
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
      items: state.items.map((m) => (m.id === id ? { ...m, ...updates } : m)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((m) => m.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
