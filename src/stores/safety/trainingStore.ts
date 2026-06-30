'use client'

import { create } from 'zustand'
import type { SafetyTraining, SafetyTrainingQueryParams, TrainingRecord } from '@/types/safety'

interface TrainingState {
  items: SafetyTraining[]
  currentItem: SafetyTraining | null
  records: TrainingRecord[]
  queryParams: SafetyTrainingQueryParams
  total: number
  loading: boolean
  setItems: (items: SafetyTraining[]) => void
  setCurrentItem: (item: SafetyTraining | null) => void
  setRecords: (records: TrainingRecord[]) => void
  setQueryParams: (params: Partial<SafetyTrainingQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  addItem: (item: SafetyTraining) => void
  updateItem: (id: string, updates: Partial<SafetyTraining>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as SafetyTraining[],
  currentItem: null as SafetyTraining | null,
  records: [] as TrainingRecord[],
  queryParams: { page: 1, page_size: 20 } as SafetyTrainingQueryParams,
  total: 0,
  loading: false,
}

export const useTrainingStore = create<TrainingState>((set) => ({
  ...initialState,

  setItems: (items) => set({ items }),
  setCurrentItem: (currentItem) => set({ currentItem }),
  setRecords: (records) => set({ records }),
  setQueryParams: (params) =>
    set((state) => ({ queryParams: { ...state.queryParams, ...params } })),
  setTotal: (total) => set({ total }),
  setLoading: (loading) => set({ loading }),

  addItem: (item) => set((state) => ({ items: [item, ...state.items] })),
  updateItem: (id, updates) =>
    set((state) => ({
      items: state.items.map((t) => (t.id === id ? { ...t, ...updates } : t)),
      currentItem:
        state.currentItem?.id === id ? { ...state.currentItem, ...updates } : state.currentItem,
    })),
  removeItem: (id) =>
    set((state) => ({
      items: state.items.filter((t) => t.id !== id),
      currentItem: state.currentItem?.id === id ? null : state.currentItem,
    })),

  reset: () => set(initialState),
}))
