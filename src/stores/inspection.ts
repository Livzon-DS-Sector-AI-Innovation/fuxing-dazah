import { create } from 'zustand'
import {
  InspectionRoute, InspectionTask, InspectionTaskStatus,
  InspectionRouteDetail, InspectionOverallResult,
} from '@/types/inspection'
import type { InspectionTemplate, InspectionTemplateItem } from '@/types/equipment'

interface InspectionStore {
  // 当前 Tab
  activeTab: 'tasks' | 'routes' | 'history' | 'templates'
  setActiveTab: (tab: 'tasks' | 'routes' | 'history' | 'templates') => void

  // ── 任务 ──
  tasks: InspectionTask[]
  tasksTotal: number
  tasksPage: number
  tasksPageSize: number
  tasksLoading: boolean
  tasksStatusFilter: InspectionTaskStatus | ''
  tasksRefreshKey: number
  setTasks: (tasks: InspectionTask[]) => void
  setTasksTotal: (total: number) => void
  setTasksPage: (page: number) => void
  setTasksPageSize: (size: number) => void
  setTasksLoading: (loading: boolean) => void
  setTasksStatusFilter: (status: InspectionTaskStatus | '') => void
  triggerTasksRefresh: () => void

  // 任务抽屉
  taskDrawerOpen: boolean
  openTaskDrawer: () => void
  closeTaskDrawer: () => void

  // 执行视图
  executingTaskId: string | null
  executingPlanType: string
  executingRouteDetail: InspectionRouteDetail | null
  executingTemplateItems: Record<string, InspectionTemplateItem[]>
  executingTemplateName: string
  executingEquipmentId: string | null
  executingEquipmentName: string
  executingEquipmentNo: string
  executingEquipmentIds: string[] | null
  executingEquipments: { id: string; name: string; no: string }[]
  executingCompletedEquipmentIds: string[]
  setExecutingTask: (
    taskId: string,
    planType: string,
    routeDetail: InspectionRouteDetail | null,
    templateItems: Record<string, InspectionTemplateItem[]>,
    templateName: string,
    equipmentId?: string | null,
    equipmentName?: string,
    equipmentNo?: string,
    equipmentIds?: string[] | null,
    equipments?: { id: string; name: string; no: string }[],
    completedEquipmentIds?: string[],
  ) => void
  clearExecuting: () => void

  // ── 路线 ──
  routes: InspectionRoute[]
  routesTotal: number
  routesPage: number
  routesPageSize: number
  routesLoading: boolean
  routesKeyword: string
  routesRefreshKey: number
  setRoutes: (routes: InspectionRoute[]) => void
  setRoutesTotal: (total: number) => void
  setRoutesPage: (page: number) => void
  setRoutesPageSize: (size: number) => void
  setRoutesLoading: (loading: boolean) => void
  setRoutesKeyword: (kw: string) => void
  triggerRoutesRefresh: () => void

  // 路线抽屉
  routeDrawerOpen: boolean
  editingRoute: InspectionRoute | null
  openRouteDrawer: (route?: InspectionRoute) => void
  closeRouteDrawer: () => void

  // 路线设备抽屉
  routeEquipmentDrawerOpen: boolean
  editingRouteId: string | null
  openRouteEquipmentDrawer: (routeId: string) => void
  closeRouteEquipmentDrawer: () => void

  // ── 历史 ──
  historyItems: InspectionTask[]
  historyTotal: number
  historyPage: number
  historyPageSize: number
  historyLoading: boolean
  historyDateFrom: string
  historyDateTo: string
  historyEquipmentId: string | null
  historyResult: InspectionOverallResult | null
  setHistoryItems: (items: InspectionTask[]) => void
  setHistoryTotal: (total: number) => void
  setHistoryPage: (page: number) => void
  setHistoryPageSize: (size: number) => void
  setHistoryLoading: (loading: boolean) => void
  setHistoryDateFrom: (d: string) => void
  setHistoryDateTo: (d: string) => void
  setHistoryEquipmentId: (id: string | null) => void
  setHistoryResult: (result: InspectionOverallResult | null) => void

  // 历史详情抽屉
  historyDetailOpen: boolean
  detailTaskId: string | null
  openHistoryDetail: (taskId: string) => void
  closeHistoryDetail: () => void

  // ── 定时任务抽屉 ──
  scheduleDrawerOpen: boolean
  scheduleRouteId: string | null
  scheduleRouteName: string
  openScheduleDrawer: (routeId: string, routeName: string) => void
  closeScheduleDrawer: () => void

  // ── 共享数据 ──
  templates: InspectionTemplate[]
  setTemplates: (templates: InspectionTemplate[]) => void
}

export const useInspectionStore = create<InspectionStore>()((set) => ({
  activeTab: 'tasks',
  setActiveTab: (tab) => set({ activeTab: tab }),

  // 任务
  tasks: [],
  tasksTotal: 0,
  tasksPage: 1,
  tasksPageSize: 20,
  tasksLoading: false,
  tasksStatusFilter: '',
  tasksRefreshKey: 0,
  setTasks: (tasks) => set({ tasks }),
  setTasksTotal: (total) => set({ tasksTotal: total }),
  setTasksPage: (page) => set({ tasksPage: page }),
  setTasksPageSize: (size) => set({ tasksPageSize: size }),
  setTasksLoading: (loading) => set({ tasksLoading: loading }),
  setTasksStatusFilter: (status) => set({ tasksStatusFilter: status, tasksPage: 1 }),
  triggerTasksRefresh: () => set((s) => ({ tasksRefreshKey: s.tasksRefreshKey + 1 })),

  taskDrawerOpen: false,
  openTaskDrawer: () => set({ taskDrawerOpen: true }),
  closeTaskDrawer: () => set({ taskDrawerOpen: false }),

  executingTaskId: null,
  executingPlanType: '',
  executingRouteDetail: null,
  executingTemplateItems: {},
  executingTemplateName: '',
  executingEquipmentId: null,
  executingEquipmentName: '',
  executingEquipmentNo: '',
  executingEquipmentIds: null,
  executingEquipments: [],
  executingCompletedEquipmentIds: [],
  setExecutingTask: (taskId, planType, routeDetail, templateItems, templateName, equipmentId, equipmentName, equipmentNo, equipmentIds, equipments, completedEquipmentIds) => set({
    executingTaskId: taskId,
    executingPlanType: planType,
    executingRouteDetail: routeDetail,
    executingTemplateItems: templateItems,
    executingTemplateName: templateName,
    executingEquipmentId: equipmentId || null,
    executingEquipmentName: equipmentName || '',
    executingEquipmentNo: equipmentNo || '',
    executingEquipmentIds: equipmentIds || null,
    executingEquipments: equipments || [],
    executingCompletedEquipmentIds: completedEquipmentIds || [],
  }),
  clearExecuting: () => set({
    executingTaskId: null,
    executingPlanType: '',
    executingRouteDetail: null,
    executingTemplateItems: {},
    executingTemplateName: '',
    executingEquipmentId: null,
    executingEquipmentName: '',
    executingEquipmentNo: '',
    executingEquipmentIds: null,
    executingEquipments: [],
    executingCompletedEquipmentIds: [],
  }),

  // 路线
  routes: [],
  routesTotal: 0,
  routesPage: 1,
  routesPageSize: 20,
  routesLoading: false,
  routesKeyword: '',
  routesRefreshKey: 0,
  setRoutes: (routes) => set({ routes }),
  setRoutesTotal: (total) => set({ routesTotal: total }),
  setRoutesPage: (page) => set({ routesPage: page }),
  setRoutesPageSize: (size) => set({ routesPageSize: size }),
  setRoutesLoading: (loading) => set({ routesLoading: loading }),
  setRoutesKeyword: (kw) => set({ routesKeyword: kw, routesPage: 1 }),
  triggerRoutesRefresh: () => set((s) => ({ routesRefreshKey: s.routesRefreshKey + 1 })),

  routeDrawerOpen: false,
  editingRoute: null,
  openRouteDrawer: (route) => set({ routeDrawerOpen: true, editingRoute: route || null }),
  closeRouteDrawer: () => set({ routeDrawerOpen: false, editingRoute: null }),

  routeEquipmentDrawerOpen: false,
  editingRouteId: null,
  openRouteEquipmentDrawer: (routeId) => set({ routeEquipmentDrawerOpen: true, editingRouteId: routeId }),
  closeRouteEquipmentDrawer: () => set({ routeEquipmentDrawerOpen: false, editingRouteId: null }),

  // 历史
  historyItems: [],
  historyTotal: 0,
  historyPage: 1,
  historyPageSize: 20,
  historyLoading: false,
  historyDateFrom: '',
  historyDateTo: '',
  historyEquipmentId: null,
  historyResult: null,
  setHistoryItems: (items) => set({ historyItems: items }),
  setHistoryTotal: (total) => set({ historyTotal: total }),
  setHistoryPage: (page) => set({ historyPage: page }),
  setHistoryPageSize: (size) => set({ historyPageSize: size }),
  setHistoryLoading: (loading) => set({ historyLoading: loading }),
  setHistoryDateFrom: (d) => set({ historyDateFrom: d, historyPage: 1 }),
  setHistoryDateTo: (d) => set({ historyDateTo: d, historyPage: 1 }),
  setHistoryEquipmentId: (id) => set({ historyEquipmentId: id, historyPage: 1 }),
  setHistoryResult: (result) => set({ historyResult: result, historyPage: 1 }),

  historyDetailOpen: false,
  detailTaskId: null,
  openHistoryDetail: (taskId) => set({ historyDetailOpen: true, detailTaskId: taskId }),
  closeHistoryDetail: () => set({ historyDetailOpen: false, detailTaskId: null }),

  scheduleDrawerOpen: false,
  scheduleRouteId: null,
  scheduleRouteName: '',
  openScheduleDrawer: (routeId, routeName) => set({
    scheduleDrawerOpen: true,
    scheduleRouteId: routeId,
    scheduleRouteName: routeName,
  }),
  closeScheduleDrawer: () => set({
    scheduleDrawerOpen: false,
    scheduleRouteId: null,
    scheduleRouteName: '',
  }),

  // 共享
  templates: [],
  setTemplates: (templates) => set({ templates }),
}))
