'use client'

import { create } from 'zustand'
import type { SafetyCheck, SafetyCheckQueryParams } from '@/types/safety'

interface CheckState {
  items: SafetyCheck[]
  currentItem: SafetyCheck | null
  queryParams: SafetyCheckQueryParams
  total: number
  loading: boolean
  setItems: (items: SafetyCheck[]) => void
  setCurrentItem: (item: SafetyCheck | null) => void
  setQueryParams: (params: Partial<SafetyCheckQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SafetyCheck) => void
  updateItem: (id: string, updates: Partial<SafetyCheck>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SafetyCheck[],
  currentItem: null as SafetyCheck | null,
  queryParams: { page: 1, page_size: 20 } as SafetyCheckQueryParams,
  total: 0,
  loading: false,
}

export const useCheckStore = create<CheckState>((set) => ({
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
      items: state.items.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((c) => c.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
