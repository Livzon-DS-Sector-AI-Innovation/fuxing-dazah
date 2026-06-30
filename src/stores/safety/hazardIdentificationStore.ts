'use client'

import { create } from 'zustand'
import type { HazardIdentification, HazardIdentificationQueryParams } from '@/types/safety'

interface HazardIdentificationState {
  items: HazardIdentification[]
  currentItem: HazardIdentification | null
  queryParams: HazardIdentificationQueryParams
  total: number
  loading: boolean
  setItems: (items: HazardIdentification[], total?: number) => void
  setCurrentItem: (item: HazardIdentification | null) => void
  setQueryParams: (params: Partial<HazardIdentificationQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: HazardIdentification) => void
  updateItem: (id: string, updates: Partial<HazardIdentification>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as HazardIdentification[],
  currentItem: null as HazardIdentification | null,
  queryParams: { page: 1, page_size: 20 } as HazardIdentificationQueryParams,
  total: 0,
  loading: false,
}

export const useHazardIdentificationStore = create<HazardIdentificationState>((set) => ({
  ...initialState,

  setItems: (items, total) =>
    set({ items, total: total ?? items.length }),
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
