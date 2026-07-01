import type {
  EquipmentCategory,
  Location,
  Equipment,
  EquipmentStatistics,
  FailureCode,
  WorkOrder,
  WorkOrderStatistics,
  CalibrationPlan,
  CalibrationRecord,
  SparePart,
  StockWarning,
  MaintenancePlan,
  InspectionTemplate,
  InspectionTemplateItem,
  Maintainer,
  DepartmentOption,
} from '@/types/equipment'

// ============ 设备列表基础状态 ============

export const initialEquipmentListState = {
  categories: [] as EquipmentCategory[],
  locations: [] as Location[],
  equipments: [] as Equipment[],
  statistics: null as EquipmentStatistics | null,

  selectedCategory: null as string | null,
  selectedLocation: null as string | null,
  statusFilter: '' as '' | '在用' | '备用' | '维修中' | '停用' | '报废',
  departmentFilter: null as string | null,
  departments: [] as DepartmentOption[],
  keyword: '',
  page: 1,
  pageSize: 20,
  total: 0,
  loading: false,

  equipmentDrawerOpen: false,
  categoryDrawerOpen: false,
  locationDrawerOpen: false,
  editingEquipment: null as Equipment | null,
  editingCategory: null as EquipmentCategory | null,
  editingLocation: null as Location | null,
}

// ============ 工单状态 ============

export const initialWorkOrderState = {
  workOrders: [] as WorkOrder[],
  workOrderTotal: 0,
  workOrderPage: 1,
  workOrderPageSize: 20,
  workOrderStatistics: null as WorkOrderStatistics | null,
  workOrderLoading: false,
  workOrderStatusFilter: '' as '' | '待处理' | '执行中' | '待验收' | '已完成' | '已关闭',
  workOrderPriorityFilter: '' as '' | '紧急' | '高' | '中' | '低',
  workOrderTypeFilter: '' as '' | '故障维修' | '计划维护' | '校准' | '异常处理' | '日常维护',
  workOrderDrawerOpen: false,
  workOrderDetailOpen: false,
  editingWorkOrder: null as WorkOrder | null,
  viewingWorkOrder: null as WorkOrder | null,
}

// ============ 故障代码状态 ============

export const initialFailureCodeState = {
  failureCodes: { symptoms: [], causes: [], actions: [] } as Record<'symptoms' | 'causes' | 'actions', FailureCode[]>,
  failureCodeLoading: false,
  failureCodeDrawerOpen: false,
  failureCodeDrawerType: 'symptoms' as 'symptoms' | 'causes' | 'actions',
  editingFailureCode: null as FailureCode | null,
}

// ============ 校准计划状态 ============

export const initialCalibrationPlanState = {
  calibrationPlans: [] as CalibrationPlan[],
  calibrationPlanTotal: 0,
  calibrationPlanPage: 1,
  calibrationPlanPageSize: 20,
  calibrationPlanLoading: false,
  calibrationPlanStatusFilter: '' as '' | '启用' | '停用',
  calibrationPlanDrawerOpen: false,
  editingCalibrationPlan: null as CalibrationPlan | null,
}

// ============ 校准记录状态 ============

export const initialCalibrationRecordState = {
  calibrationRecords: [] as CalibrationRecord[],
  calibrationRecordTotal: 0,
  calibrationRecordPage: 1,
  calibrationRecordPageSize: 20,
  calibrationRecordLoading: false,
  calibrationRecordDrawerOpen: false,
  editingCalibrationRecord: null as CalibrationRecord | null,
}

// ============ 备件管理状态 ============

export const initialSparePartState = {
  spareParts: [] as SparePart[],
  sparePartTotal: 0,
  sparePartPage: 1,
  sparePartPageSize: 20,
  sparePartLoading: false,
  sparePartKeyword: '',
  stockWarnings: [] as StockWarning[],
  stockWarningsLoading: false,
  sparePartDrawerOpen: false,
  editingSparePart: null as SparePart | null,
  stockInboundDrawerOpen: false,
  stockInboundSparePartId: null as string | null,
}

// ============ 维护计划状态 ============

export const initialMaintenancePlanState = {
  maintenancePlans: [] as MaintenancePlan[],
  maintenancePlanTotal: 0,
  maintenancePlanPage: 1,
  maintenancePlanPageSize: 20,
  maintenancePlanLoading: false,
  maintenancePlanStatusFilter: '' as '' | '启用' | '停用' | '已完成',
  maintenancePlanKeyword: '',
  maintenancePlanDrawerOpen: false,
  editingMaintenancePlan: null as MaintenancePlan | null,
}

// ============ 巡检模板状态 ============

export const initialInspectionTemplateState = {
  inspectionTemplates: [] as InspectionTemplate[],
  inspectionTemplateTotal: 0,
  inspectionTemplatePage: 1,
  inspectionTemplatePageSize: 20,
  inspectionTemplateLoading: false,
  inspectionTemplateKeyword: '',
  inspectionTemplateDrawerOpen: false,
  editingInspectionTemplate: null as InspectionTemplate | null,
  inspectionItemDrawerOpen: false,
  inspectionItemTemplateId: null as string | null,
  editingInspectionItem: null as InspectionTemplateItem | null,
}

// ============ 巡检完成状态 ============

export const initialInspectionCompleteState = {
  inspectionCompleteDrawerOpen: false,
  completingWorkOrderId: null as string | null,
  completingTemplateName: null as string | null,
  completingTemplateItems: [] as InspectionTemplateItem[],
}

// ============ 报修抽屉状态 ============

export const initialRepairState = {
  repairDrawerOpen: false,
  repairEquipmentId: null as string | null,
}

// ============ 超时配置 & 维修人员 ============

export const initialTimeoutConfigState = {
  claimTimeoutConfig: { emergency: 15, high: 30, medium: 60, low: 120 },
}

export const initialMaintainerState = {
  maintainers: [] as Maintainer[],
}
