import type {
  EquipmentCategory,
  Location,
  Equipment,
  EquipmentStatus,
  EquipmentStatistics,
  FailureCode,
  WorkOrder,
  WorkOrderStatus,
  WorkOrderPriority,
  WorkOrderType,
  WorkOrderStatistics,
  SparePart,
  StockWarning,
  MaintenancePlan,
  MaintenancePlanStatus,
  InspectionTemplate,
  InspectionTemplateItem,
  Maintainer,
  DepartmentOption,
} from '@/types/equipment'

// ============ Equipment Store State ============

export interface EquipmentStore {
  // ── 基础数据 ──
  categories: EquipmentCategory[]
  locations: Location[]
  equipments: Equipment[]
  statistics: EquipmentStatistics | null

  // ── 筛选状态 ──
  selectedCategory: string | null
  selectedLocation: string | null
  statusFilter: EquipmentStatus | ''
  departmentFilter: string | null
  departments: DepartmentOption[]
  keyword: string
  page: number
  pageSize: number
  total: number
  loading: boolean

  // ── 抽屉状态 ──
  equipmentDrawerOpen: boolean
  categoryDrawerOpen: boolean
  locationDrawerOpen: boolean
  editingEquipment: Equipment | null
  editingCategory: EquipmentCategory | null
  editingLocation: Location | null

  // ── 基础操作 ──
  setCategories: (categories: EquipmentCategory[]) => void
  setLocations: (locations: Location[]) => void
  setEquipments: (equipments: Equipment[]) => void
  setStatistics: (statistics: EquipmentStatistics | null) => void
  setSelectedCategory: (id: string | null) => void
  setSelectedLocation: (id: string | null) => void
  setStatusFilter: (status: EquipmentStatus | '') => void
  setDepartmentFilter: (id: string | null) => void
  setDepartments: (departments: DepartmentOption[]) => void
  setKeyword: (keyword: string) => void
  setPage: (page: number) => void
  setPageSize: (pageSize: number) => void
  setTotal: (total: number) => void
  setLoading: (loading: boolean) => void
  resetFilters: () => void
  openEquipmentDrawer: (equipment?: Equipment) => void
  closeEquipmentDrawer: () => void
  openCategoryDrawer: (category?: EquipmentCategory) => void
  closeCategoryDrawer: () => void
  openLocationDrawer: (location?: Location) => void
  closeLocationDrawer: () => void

  // ── 维护模块 ──
  maintenanceTab: string
  setMaintenanceTab: (tab: string) => void

  // ── 工单 ──
  workOrders: WorkOrder[]
  workOrderTotal: number
  workOrderPage: number
  workOrderPageSize: number
  workOrderStatistics: WorkOrderStatistics | null
  workOrderLoading: boolean
  workOrderStatusFilter: WorkOrderStatus | ''
  workOrderPriorityFilter: WorkOrderPriority | ''
  workOrderTypeFilter: WorkOrderType | ''
  setWorkOrders: (orders: WorkOrder[]) => void
  setWorkOrderTotal: (total: number) => void
  setWorkOrderPage: (page: number) => void
  setWorkOrderPageSize: (size: number) => void
  setWorkOrderStatistics: (stats: WorkOrderStatistics | null) => void
  setWorkOrderLoading: (loading: boolean) => void
  setWorkOrderStatusFilter: (status: WorkOrderStatus | '') => void
  setWorkOrderPriorityFilter: (priority: WorkOrderPriority | '') => void
  setWorkOrderTypeFilter: (type: WorkOrderType | '') => void
  workOrderDrawerOpen: boolean
  workOrderDetailOpen: boolean
  editingWorkOrder: WorkOrder | null
  viewingWorkOrder: WorkOrder | null
  setViewingWorkOrder: (order: WorkOrder | null) => void
  openWorkOrderDrawer: (order?: WorkOrder) => void
  closeWorkOrderDrawer: () => void
  openWorkOrderDetail: (order: WorkOrder) => void
  closeWorkOrderDetail: () => void

  // ── 故障代码 ──
  failureCodes: Record<'symptoms' | 'causes' | 'actions', FailureCode[]>
  failureCodeLoading: boolean
  setFailureCodes: (type: 'symptoms' | 'causes' | 'actions', codes: FailureCode[]) => void
  setFailureCodeLoading: (loading: boolean) => void
  failureCodeDrawerOpen: boolean
  failureCodeDrawerType: 'symptoms' | 'causes' | 'actions'
  editingFailureCode: FailureCode | null
  openFailureCodeDrawer: (type: 'symptoms' | 'causes' | 'actions', code?: FailureCode) => void
  closeFailureCodeDrawer: () => void

  // ── 备件管理 ──
  spareParts: SparePart[]
  sparePartTotal: number
  sparePartPage: number
  sparePartPageSize: number
  sparePartLoading: boolean
  sparePartKeyword: string
  stockWarnings: StockWarning[]
  stockWarningsLoading: boolean
  setSpareParts: (parts: SparePart[]) => void
  setSparePartTotal: (total: number) => void
  setSparePartPage: (page: number) => void
  setSparePartPageSize: (size: number) => void
  setSparePartLoading: (loading: boolean) => void
  setSparePartKeyword: (keyword: string) => void
  setStockWarnings: (warnings: StockWarning[]) => void
  setStockWarningsLoading: (loading: boolean) => void
  sparePartDrawerOpen: boolean
  editingSparePart: SparePart | null
  openSparePartDrawer: (part?: SparePart) => void
  closeSparePartDrawer: () => void
  sparePartEquipmentDrawerOpen: boolean
  equipmentManagingSparePart: SparePart | null
  openSparePartEquipmentDrawer: (part: SparePart) => void
  closeSparePartEquipmentDrawer: () => void
  stockInboundDrawerOpen: boolean
  stockInboundSparePartId: string | null
  openStockInboundDrawer: (sparePartId: string) => void
  closeStockInboundDrawer: () => void

  // ── 维护计划 ──
  maintenancePlans: MaintenancePlan[]
  maintenancePlanTotal: number
  maintenancePlanPage: number
  maintenancePlanPageSize: number
  maintenancePlanLoading: boolean
  maintenancePlanStatusFilter: MaintenancePlanStatus | ''
  maintenancePlanKeyword: string
  maintenancePlanModeFilter: 'equipment' | 'category' | ''
  maintenancePlanSortField: string | null
  maintenancePlanSortOrder: 'ascend' | 'descend' | null
  setMaintenancePlans: (plans: MaintenancePlan[]) => void
  setMaintenancePlanTotal: (total: number) => void
  setMaintenancePlanPage: (page: number) => void
  setMaintenancePlanPageSize: (size: number) => void
  setMaintenancePlanLoading: (loading: boolean) => void
  setMaintenancePlanStatusFilter: (status: MaintenancePlanStatus | '') => void
  setMaintenancePlanKeyword: (keyword: string) => void
  setMaintenancePlanModeFilter: (mode: 'equipment' | 'category' | '') => void
  setMaintenancePlanSortField: (field: string | null) => void
  setMaintenancePlanSortOrder: (order: 'ascend' | 'descend' | null) => void
  maintenancePlanDrawerOpen: boolean
  editingMaintenancePlan: MaintenancePlan | null
  openMaintenancePlanDrawer: (plan?: MaintenancePlan) => void
  closeMaintenancePlanDrawer: () => void

  // ── 巡检模板 ──
  inspectionTemplates: InspectionTemplate[]
  inspectionTemplateTotal: number
  inspectionTemplatePage: number
  inspectionTemplatePageSize: number
  inspectionTemplateLoading: boolean
  inspectionTemplateKeyword: string
  setInspectionTemplates: (templates: InspectionTemplate[]) => void
  setInspectionTemplateTotal: (total: number) => void
  setInspectionTemplatePage: (page: number) => void
  setInspectionTemplatePageSize: (size: number) => void
  setInspectionTemplateLoading: (loading: boolean) => void
  setInspectionTemplateKeyword: (keyword: string) => void
  inspectionTemplateDrawerOpen: boolean
  editingInspectionTemplate: InspectionTemplate | null
  openInspectionTemplateDrawer: (template?: InspectionTemplate) => void
  closeInspectionTemplateDrawer: () => void
  inspectionItemDrawerOpen: boolean
  inspectionItemTemplateId: string | null
  editingInspectionItem: InspectionTemplateItem | null
  openInspectionItemDrawer: (templateId: string, item?: InspectionTemplateItem) => void
  closeInspectionItemDrawer: () => void

  // ── 巡检完成 ──
  inspectionCompleteDrawerOpen: boolean
  completingWorkOrderId: string | null
  completingTemplateName: string | null
  completingTemplateItems: InspectionTemplateItem[]
  openInspectionCompleteDrawer: (workOrderId: string, templateName: string, items: InspectionTemplateItem[]) => void
  closeInspectionCompleteDrawer: () => void

  // ── 报修抽屉 ──
  repairDrawerOpen: boolean
  repairEquipmentId: string | null
  openRepairDrawer: (equipmentId: string) => void
  closeRepairDrawer: () => void

  // ── 超时配置 ──
  claimTimeoutConfig: { emergency: number; high: number; medium: number; low: number }
  setClaimTimeoutConfig: (config: { emergency: number; high: number; medium: number; low: number }) => void

  // ── 维修人员 ──
  maintainers: Maintainer[]
  setMaintainers: (maintainers: Maintainer[]) => void
}
