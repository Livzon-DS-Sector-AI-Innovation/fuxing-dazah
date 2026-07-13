'use client'

import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { EquipmentStore } from './types'
import {
  initialEquipmentListState,
  initialWorkOrderState,
  initialFailureCodeState,
  initialSparePartState,
  initialMaintenancePlanState,
  initialInspectionTemplateState,
  initialInspectionCompleteState,
  initialRepairState,
  initialTimeoutConfigState,
  initialMaintainerState,
} from './initialStates'

export { type EquipmentStore } from './types'

export const useEquipmentStore = create<EquipmentStore>()(
  devtools(
    (set) => ({
      // ── 初始状态 ──
      ...initialEquipmentListState,
      ...initialWorkOrderState,
      ...initialFailureCodeState,
      ...initialSparePartState,
      ...initialMaintenancePlanState,
      ...initialInspectionTemplateState,
      ...initialInspectionCompleteState,
      ...initialRepairState,
      ...initialTimeoutConfigState,
      ...initialMaintainerState,

      // ── 基础操作 ──
      setCategories: (categories) => set({ categories }, false, 'equipment/setCategories'),
      setLocations: (locations) => set({ locations }, false, 'equipment/setLocations'),
      setEquipments: (equipments) => set({ equipments }, false, 'equipment/setEquipments'),
      setStatistics: (statistics) => set({ statistics }, false, 'equipment/setStatistics'),
      setSelectedCategory: (id) => set({ selectedCategory: id, page: 1 }, false, 'equipment/setSelectedCategory'),
      setSelectedLocation: (id) => set({ selectedLocation: id, page: 1 }, false, 'equipment/setSelectedLocation'),
      setStatusFilter: (status) => set({ statusFilter: status, page: 1 }, false, 'equipment/setStatusFilter'),
      setDepartmentFilter: (id) => set({ departmentFilter: id, page: 1 }, false, 'equipment/setDepartmentFilter'),
      setDepartments: (departments) => set({ departments }, false, 'equipment/setDepartments'),
      setKeyword: (keyword) => set({ keyword, page: 1 }, false, 'equipment/setKeyword'),
      setPage: (page) => set({ page }, false, 'equipment/setPage'),
      setPageSize: (pageSize) => set({ pageSize, page: 1 }, false, 'equipment/setPageSize'),
      setTotal: (total) => set({ total }, false, 'equipment/setTotal'),
      setLoading: (loading) => set({ loading }, false, 'equipment/setLoading'),
      resetFilters: () => set({
        selectedCategory: null,
        selectedLocation: null,
        departmentFilter: null,
        statusFilter: '',
        keyword: '',
        page: 1,
        pageSize: 20,
      }, false, 'equipment/resetFilters'),

      openEquipmentDrawer: (equipment) =>
        set({ equipmentDrawerOpen: true, editingEquipment: equipment || null }, false, 'equipment/openEquipmentDrawer'),
      closeEquipmentDrawer: () =>
        set({ equipmentDrawerOpen: false, editingEquipment: null }, false, 'equipment/closeEquipmentDrawer'),
      openCategoryDrawer: (category) =>
        set({ categoryDrawerOpen: true, editingCategory: category || null }, false, 'equipment/openCategoryDrawer'),
      closeCategoryDrawer: () =>
        set({ categoryDrawerOpen: false, editingCategory: null }, false, 'equipment/closeCategoryDrawer'),
      openLocationDrawer: (location) =>
        set({ locationDrawerOpen: true, editingLocation: location || null }, false, 'equipment/openLocationDrawer'),
      closeLocationDrawer: () =>
        set({ locationDrawerOpen: false, editingLocation: null }, false, 'equipment/closeLocationDrawer'),

      // ── 维护模块 ──
      maintenanceTab: 'work-orders',
      setMaintenanceTab: (tab) => set({ maintenanceTab: tab }, false, 'equipment/setMaintenanceTab'),

      // ── 工单操作 ──
      setWorkOrders: (orders) => set({ workOrders: orders }, false, 'equipment/setWorkOrders'),
      setWorkOrderTotal: (total) => set({ workOrderTotal: total }, false, 'equipment/setWorkOrderTotal'),
      setWorkOrderPage: (page) => set({ workOrderPage: page }, false, 'equipment/setWorkOrderPage'),
      setWorkOrderPageSize: (size) => set({ workOrderPageSize: size, workOrderPage: 1 }, false, 'equipment/setWorkOrderPageSize'),
      setWorkOrderStatistics: (stats) => set({ workOrderStatistics: stats }, false, 'equipment/setWorkOrderStatistics'),
      setWorkOrderLoading: (loading) => set({ workOrderLoading: loading }, false, 'equipment/setWorkOrderLoading'),
      setWorkOrderStatusFilter: (status) => set({ workOrderStatusFilter: status, workOrderPage: 1 }, false, 'equipment/setWorkOrderStatusFilter'),
      setWorkOrderPriorityFilter: (priority) => set({ workOrderPriorityFilter: priority, workOrderPage: 1 }, false, 'equipment/setWorkOrderPriorityFilter'),
      setWorkOrderTypeFilter: (type) => set({ workOrderTypeFilter: type, workOrderPage: 1 }, false, 'equipment/setWorkOrderTypeFilter'),
      setViewingWorkOrder: (order) => set({ viewingWorkOrder: order }, false, 'equipment/setViewingWorkOrder'),
      openWorkOrderDrawer: (order) => set({ workOrderDrawerOpen: true, editingWorkOrder: order || null }, false, 'equipment/openWorkOrderDrawer'),
      closeWorkOrderDrawer: () => set({ workOrderDrawerOpen: false, editingWorkOrder: null }, false, 'equipment/closeWorkOrderDrawer'),
      openWorkOrderDetail: (order) => set({ workOrderDetailOpen: true, viewingWorkOrder: order }, false, 'equipment/openWorkOrderDetail'),
      closeWorkOrderDetail: () => set({ workOrderDetailOpen: false, viewingWorkOrder: null }, false, 'equipment/closeWorkOrderDetail'),

      // ── 故障代码操作 ──
      setFailureCodes: (type, codes) => set(
        (state) => ({ failureCodes: { ...state.failureCodes, [type]: codes } }),
        false,
        'equipment/setFailureCodes',
      ),
      setFailureCodeLoading: (loading) => set({ failureCodeLoading: loading }, false, 'equipment/setFailureCodeLoading'),
      openFailureCodeDrawer: (type, code) => set({
        failureCodeDrawerOpen: true, failureCodeDrawerType: type, editingFailureCode: code || null,
      }, false, 'equipment/openFailureCodeDrawer'),
      closeFailureCodeDrawer: () => set({
        failureCodeDrawerOpen: false, editingFailureCode: null,
      }, false, 'equipment/closeFailureCodeDrawer'),

      // ── 备件管理操作 ──
      setSpareParts: (parts) => set({ spareParts: parts }, false, 'equipment/setSpareParts'),
      setSparePartTotal: (total) => set({ sparePartTotal: total }, false, 'equipment/setSparePartTotal'),
      setSparePartPage: (page) => set({ sparePartPage: page }, false, 'equipment/setSparePartPage'),
      setSparePartPageSize: (size) => set({ sparePartPageSize: size, sparePartPage: 1 }, false, 'equipment/setSparePartPageSize'),
      setSparePartLoading: (loading) => set({ sparePartLoading: loading }, false, 'equipment/setSparePartLoading'),
      setSparePartKeyword: (keyword) => set({ sparePartKeyword: keyword, sparePartPage: 1 }, false, 'equipment/setSparePartKeyword'),
      setStockWarnings: (warnings) => set({ stockWarnings: warnings }, false, 'equipment/setStockWarnings'),
      setStockWarningsLoading: (loading) => set({ stockWarningsLoading: loading }, false, 'equipment/setStockWarningsLoading'),
      openSparePartDrawer: (part) => set({
        sparePartDrawerOpen: true, editingSparePart: part || null,
      }, false, 'equipment/openSparePartDrawer'),
      closeSparePartDrawer: () => set({
        sparePartDrawerOpen: false, editingSparePart: null,
      }, false, 'equipment/closeSparePartDrawer'),
      openStockInboundDrawer: (sparePartId) => set({
        stockInboundDrawerOpen: true, stockInboundSparePartId: sparePartId,
      }, false, 'equipment/openStockInboundDrawer'),
      closeStockInboundDrawer: () => set({
        stockInboundDrawerOpen: false, stockInboundSparePartId: null,
      }, false, 'equipment/closeStockInboundDrawer'),

      // ── 维护计划操作 ──
      setMaintenancePlans: (plans) => set({ maintenancePlans: plans }, false, 'equipment/setMaintenancePlans'),
      setMaintenancePlanTotal: (total) => set({ maintenancePlanTotal: total }, false, 'equipment/setMaintenancePlanTotal'),
      setMaintenancePlanPage: (page) => set({ maintenancePlanPage: page }, false, 'equipment/setMaintenancePlanPage'),
      setMaintenancePlanPageSize: (size) => set({ maintenancePlanPageSize: size, maintenancePlanPage: 1 }, false, 'equipment/setMaintenancePlanPageSize'),
      setMaintenancePlanLoading: (loading) => set({ maintenancePlanLoading: loading }, false, 'equipment/setMaintenancePlanLoading'),
      setMaintenancePlanStatusFilter: (status) => set({ maintenancePlanStatusFilter: status, maintenancePlanPage: 1 }, false, 'equipment/setMaintenancePlanStatusFilter'),
      setMaintenancePlanKeyword: (keyword) => set({ maintenancePlanKeyword: keyword, maintenancePlanPage: 1 }, false, 'equipment/setMaintenancePlanKeyword'),
      openMaintenancePlanDrawer: (plan) => set({
        maintenancePlanDrawerOpen: true, editingMaintenancePlan: plan || null,
      }, false, 'equipment/openMaintenancePlanDrawer'),
      closeMaintenancePlanDrawer: () => set({
        maintenancePlanDrawerOpen: false, editingMaintenancePlan: null,
      }, false, 'equipment/closeMaintenancePlanDrawer'),

      // ── 巡检模板操作 ──
      setInspectionTemplates: (templates) => set({ inspectionTemplates: templates }, false, 'equipment/setInspectionTemplates'),
      setInspectionTemplateTotal: (total) => set({ inspectionTemplateTotal: total }, false, 'equipment/setInspectionTemplateTotal'),
      setInspectionTemplatePage: (page) => set({ inspectionTemplatePage: page }, false, 'equipment/setInspectionTemplatePage'),
      setInspectionTemplatePageSize: (size) => set({ inspectionTemplatePageSize: size, inspectionTemplatePage: 1 }, false, 'equipment/setInspectionTemplatePageSize'),
      setInspectionTemplateLoading: (loading) => set({ inspectionTemplateLoading: loading }, false, 'equipment/setInspectionTemplateLoading'),
      setInspectionTemplateKeyword: (keyword) => set({ inspectionTemplateKeyword: keyword, inspectionTemplatePage: 1 }, false, 'equipment/setInspectionTemplateKeyword'),
      openInspectionTemplateDrawer: (template) => set({
        inspectionTemplateDrawerOpen: true, editingInspectionTemplate: template || null,
      }, false, 'equipment/openInspectionTemplateDrawer'),
      closeInspectionTemplateDrawer: () => set({
        inspectionTemplateDrawerOpen: false, editingInspectionTemplate: null,
      }, false, 'equipment/closeInspectionTemplateDrawer'),
      openInspectionItemDrawer: (templateId, item) => set({
        inspectionItemDrawerOpen: true, inspectionItemTemplateId: templateId, editingInspectionItem: item || null,
      }, false, 'equipment/openInspectionItemDrawer'),
      closeInspectionItemDrawer: () => set({
        inspectionItemDrawerOpen: false, inspectionItemTemplateId: null, editingInspectionItem: null,
      }, false, 'equipment/closeInspectionItemDrawer'),

      // ── 巡检完成操作 ──
      openInspectionCompleteDrawer: (workOrderId, templateName, items) => set({
        inspectionCompleteDrawerOpen: true,
        completingWorkOrderId: workOrderId,
        completingTemplateName: templateName,
        completingTemplateItems: items,
      }, false, 'equipment/openInspectionCompleteDrawer'),
      closeInspectionCompleteDrawer: () => set({
        inspectionCompleteDrawerOpen: false,
        completingWorkOrderId: null,
        completingTemplateName: null,
        completingTemplateItems: [],
      }, false, 'equipment/closeInspectionCompleteDrawer'),

      // ── 报修抽屉操作 ──
      openRepairDrawer: (equipmentId) => set({
        repairDrawerOpen: true, repairEquipmentId: equipmentId,
      }, false, 'equipment/openRepairDrawer'),
      closeRepairDrawer: () => set({
        repairDrawerOpen: false, repairEquipmentId: null,
      }, false, 'equipment/closeRepairDrawer'),

      // ── 超时配置 ──
      setClaimTimeoutConfig: (config) => set({ claimTimeoutConfig: config }, false, 'equipment/setClaimTimeoutConfig'),

      // ── 维修人员 ──
      setMaintainers: (maintainers) => set({ maintainers }, false, 'equipment/setMaintainers'),
    }),
    { name: 'equipment-store' },
  ),
)
