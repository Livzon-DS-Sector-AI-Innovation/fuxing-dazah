import { create } from 'zustand'
import { Employee } from '@/types/hr'

interface HrState {
  selectedEmployee: Employee | null
  setSelectedEmployee: (employee: Employee | null) => void
  searchKeyword: string
  setSearchKeyword: (keyword: string) => void
  filterDepartment: string
  setFilterDepartment: (dept: string) => void
  filterStatus: string
  setFilterStatus: (status: string) => void
}

export const useHrStore = create<HrState>((set) => ({
  selectedEmployee: null,
  setSelectedEmployee: (employee) => set({ selectedEmployee: employee }),
  searchKeyword: '',
  setSearchKeyword: (keyword) => set({ searchKeyword: keyword }),
  filterDepartment: '',
  setFilterDepartment: (dept) => set({ filterDepartment: dept }),
  filterStatus: '',
  setFilterStatus: (status) => set({ filterStatus: status }),
}))
