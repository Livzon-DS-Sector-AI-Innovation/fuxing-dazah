import { create } from 'zustand'
import {
  EnergyType,
  DeviceQueryParams,
  DataQueryParams,
  LogQueryParams,
  CollectHistoryParams,
} from '@/types/energy'

interface EnergyState {
  // 数据源配置筛选
  deviceFilters: DeviceQueryParams
  setDeviceFilters: (filters: Partial<DeviceQueryParams>) => void
  resetDeviceFilters: () => void

  // 能耗数据筛选
  dataFilters: DataQueryParams
  setDataFilters: (filters: Partial<DataQueryParams>) => void
  resetDataFilters: () => void

  // 采集日志筛选
  logFilters: LogQueryParams
  setLogFilters: (filters: Partial<LogQueryParams>) => void
  resetLogFilters: () => void

  // 采集历史筛选
  collectHistoryFilters: CollectHistoryParams
  setCollectHistoryFilters: (filters: Partial<CollectHistoryParams>) => void
  resetCollectHistoryFilters: () => void

  // 总览页面状态
  overviewTimeRange: 'today' | 'week' | 'month'
  setOverviewTimeRange: (range: 'today' | 'week' | 'month') => void
  selectedEnergyType: EnergyType | 'all'
  setSelectedEnergyType: (type: EnergyType | 'all') => void

  // 抽屉状态
  deviceDrawerOpen: boolean
  deviceDrawerMode: 'create' | 'edit'
  deviceDrawerId: string | null
  openDeviceDrawer: (mode: 'create' | 'edit', id?: string) => void
  closeDeviceDrawer: () => void

  alertConfigDrawerOpen: boolean
  alertConfigDrawerMode: 'create' | 'edit'
  alertConfigDrawerId: string | null
  openAlertConfigDrawer: (mode: 'create' | 'edit', id?: string) => void
  closeAlertConfigDrawer: () => void

  alertRecordDrawerOpen: boolean
  alertRecordDrawerId: string | null
  openAlertRecordDrawer: (id: string) => void
  closeAlertRecordDrawer: () => void

  collectLogDrawerOpen: boolean
  collectLogDrawerId: string | null
  openCollectLogDrawer: (id: string) => void
  closeCollectLogDrawer: () => void
}

const defaultDeviceFilters: DeviceQueryParams = {
  keyword: undefined,
  energy_type: undefined,
  workshop: undefined,
  is_enabled: undefined,
  page: 1,
  page_size: 10,
}

const defaultDataFilters: DataQueryParams = {
  energy_type: undefined,
  workshop: undefined,
  device_id: undefined,
  start_time: undefined,
  end_time: undefined,
  page: 1,
  page_size: 10,
}

const defaultLogFilters: LogQueryParams = {
  platform_code: undefined,
  status: undefined,
  page: 1,
  page_size: 10,
}

// 采集历史筛选默认值：start_date / end_date 默认为今天
const todayStr = new Date().toISOString().slice(0, 10)
const defaultCollectHistoryFilters: CollectHistoryParams = {
  device_config_id: undefined,
  start_date: todayStr,
  end_date: todayStr,
  page: 1,
  page_size: 10,
}

export const useEnergyStore = create<EnergyState>((set) => ({
  // 数据源配置筛选
  deviceFilters: defaultDeviceFilters,
  setDeviceFilters: (filters) =>
    set((state) => ({
      deviceFilters: { ...state.deviceFilters, ...filters },
    })),
  resetDeviceFilters: () => set({ deviceFilters: defaultDeviceFilters }),

  // 能耗数据筛选
  dataFilters: defaultDataFilters,
  setDataFilters: (filters) =>
    set((state) => ({
      dataFilters: { ...state.dataFilters, ...filters },
    })),
  resetDataFilters: () => set({ dataFilters: defaultDataFilters }),

  // 采集日志筛选
  logFilters: defaultLogFilters,
  setLogFilters: (filters) =>
    set((state) => ({
      logFilters: { ...state.logFilters, ...filters },
    })),
  resetLogFilters: () => set({ logFilters: defaultLogFilters }),

  // 采集历史筛选
  collectHistoryFilters: defaultCollectHistoryFilters,
  setCollectHistoryFilters: (filters) =>
    set((state) => ({
      collectHistoryFilters: { ...state.collectHistoryFilters, ...filters },
    })),
  resetCollectHistoryFilters: () =>
    set({ collectHistoryFilters: defaultCollectHistoryFilters }),

  // 总览页面状态
  overviewTimeRange: 'today',
  setOverviewTimeRange: (range) => set({ overviewTimeRange: range }),
  selectedEnergyType: 'all',
  setSelectedEnergyType: (type) => set({ selectedEnergyType: type }),

  // 抽屉状态
  deviceDrawerOpen: false,
  deviceDrawerMode: 'create',
  deviceDrawerId: null,
  openDeviceDrawer: (mode, id) =>
    set({
      deviceDrawerOpen: true,
      deviceDrawerMode: mode,
      deviceDrawerId: id || null,
    }),
  closeDeviceDrawer: () =>
    set({
      deviceDrawerOpen: false,
      deviceDrawerId: null,
    }),

  alertConfigDrawerOpen: false,
  alertConfigDrawerMode: 'create',
  alertConfigDrawerId: null,
  openAlertConfigDrawer: (mode, id) =>
    set({
      alertConfigDrawerOpen: true,
      alertConfigDrawerMode: mode,
      alertConfigDrawerId: id || null,
    }),
  closeAlertConfigDrawer: () =>
    set({
      alertConfigDrawerOpen: false,
      alertConfigDrawerId: null,
    }),

  alertRecordDrawerOpen: false,
  alertRecordDrawerId: null,
  openAlertRecordDrawer: (id) =>
    set({
      alertRecordDrawerOpen: true,
      alertRecordDrawerId: id,
    }),
  closeAlertRecordDrawer: () =>
    set({
      alertRecordDrawerOpen: false,
      alertRecordDrawerId: null,
    }),

  collectLogDrawerOpen: false,
  collectLogDrawerId: null,
  openCollectLogDrawer: (id) =>
    set({
      collectLogDrawerOpen: true,
      collectLogDrawerId: id,
    }),
  closeCollectLogDrawer: () =>
    set({
      collectLogDrawerOpen: false,
      collectLogDrawerId: null,
    }),
}))
