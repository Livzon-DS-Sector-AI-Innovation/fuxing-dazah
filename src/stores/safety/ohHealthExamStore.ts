'use client'

import { create } from 'zustand'
import type { OhHealthExam, OhHealthExamQueryParams } from '@/types/safety'

interface OhHealthExamState {
  items: OhHealthExam[]
  currentItem: OhHealthExam | null
  queryParams: OhHealthExamQueryParams
  total: number
  loading: boolean
  setItems: (items: OhHealthExam[]) => void
  setCurrentItem: (item: OhHealthExam | null) => void
  setQueryParams: (params: Partial<OhHealthExamQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: OhHealthExam) => void
  updateItem: (id: string, updates: Partial<OhHealthExam>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as OhHealthExam[],
  currentItem: null as OhHealthExam | null,
  queryParams: { page: 1, page_size: 20 } as OhHealthExamQueryParams,
  total: 0,
  loading: false,
}

export const useOhHealthExamStore = create<OhHealthExamState>((set) => ({
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
      items: state.items.map((e) => (e.id === id ? { ...e, ...updates } : e)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((e) => e.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
