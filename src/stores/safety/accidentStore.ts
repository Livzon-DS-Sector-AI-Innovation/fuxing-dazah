'use client'

import { create } from 'zustand'
import type { Accident, AccidentQueryParams } from '@/types/safety'

interface AccidentState {
  items: Accident[]
  currentItem: Accident | null
  queryParams: AccidentQueryParams
  total: number
  loading: boolean
  setItems: (items: Accident[]) => void
  setCurrentItem: (item: Accident | null) => void
  setQueryParams: (params: Partial<AccidentQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: Accident) => void
  updateItem: (id: string, updates: Partial<Accident>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as Accident[],
  currentItem: null as Accident | null,
  queryParams: { page: 1, page_size: 20 } as AccidentQueryParams,
  total: 0,
  loading: false,
}

export const useAccidentStore = create<AccidentState>((set) => ({
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
      items: state.items.map((a) => (a.id === id ? { ...a, ...updates } : a)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((a) => a.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
