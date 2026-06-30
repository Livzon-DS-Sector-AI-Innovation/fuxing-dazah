'use client'

import { create } from 'zustand'
import type { Contractor, ContractorQueryParams, ContractorWorkRecord } from '@/types/safety'

interface ContractorState {
  items: Contractor[]
  currentItem: Contractor | null
  queryParams: ContractorQueryParams
  total: number
  loading: boolean
  workRecords: ContractorWorkRecord[]
  setItems: (items: Contractor[]) => void
  setCurrentItem: (item: Contractor | null) => void
  setQueryParams: (params: Partial<ContractorQueryParams>) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  setWorkRecords: (records: ContractorWorkRecord[]) => void
  addItem: (item: Contractor) => void
  updateItem: (id: string, updates: Partial<Contractor>) => void
  removeItem: (id: string) => void
  reset: () => void
}

const initialState = {
  items: [] as Contractor[],
  currentItem: null as Contractor | null,
  queryParams: { page: 1, page_size: 20 } as ContractorQueryParams,
  total: 0,
  loading: false,
  workRecords: [] as ContractorWorkRecord[],
}

export const useContractorStore = create<ContractorState>((set) => ({
  ...initialState,

  setItems: (items) => set({ items }),
  setCurrentItem: (currentItem) => set({ currentItem }),
  setQueryParams: (params) =>
    set((state) => ({ queryParams: { ...state.queryParams, ...params } })),
  setTotal: (total) => set({ total }),
  setLoading: (loading) => set({ loading }),
  setWorkRecords: (workRecords) => set({ workRecords }),

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
