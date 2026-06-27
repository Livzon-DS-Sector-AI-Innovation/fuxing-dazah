export const dynamic = 'force-dynamic'

import '@/lib/http-server'
import { MaintenancePage } from '@/components/equipment'
import {
  fetchEquipments, fetchWorkOrders, fetchWorkOrderStatistics, fetchFailureCodes,
  fetchCalibrationPlans, fetchCalibrationRecords,
  fetchMaintenancePlans,
} from '@/lib/api/equipment'
import {
  Equipment, FailureCode, WorkOrder, WorkOrderStatistics, CalibrationPlan, CalibrationRecord,
  MaintenancePlan,
} from '@/types/equipment'

const defaultStatistics: WorkOrderStatistics = {
  total: 0,
  by_status: {} as any,
  by_type: {} as any,
  by_priority: {} as any,
}

export default async function MaintenancePageWrapper() {
  let equipments: Equipment[] = []
  let workOrders: WorkOrder[] = []
  let workOrderTotal = 0
  let workOrderStatistics = defaultStatistics
  let failureCodes: Record<'symptoms' | 'causes' | 'actions', FailureCode[]> = {
    symptoms: [],
    causes: [],
    actions: [],
  }
  let calibrationPlans: CalibrationPlan[] = []
  let calibrationPlanTotal = 0
  let calibrationRecords: CalibrationRecord[] = []
  let calibrationRecordTotal = 0
  let maintenancePlans: MaintenancePlan[] = []
  let maintenancePlanTotal = 0

  try {
    const results = await Promise.allSettled([
      fetchEquipments({ page: 1, page_size: 200 }),
      fetchWorkOrders({ page: 1, page_size: 20, exclude_status: '已关闭' }),
      fetchWorkOrderStatistics(),
      fetchFailureCodes('symptoms'),
      fetchFailureCodes('causes'),
      fetchFailureCodes('actions'),
      fetchCalibrationPlans({ page: 1, page_size: 20 }),
      fetchCalibrationRecords({ page: 1, page_size: 20 }),
      fetchMaintenancePlans({ page: 1, page_size: 20 }),
    ])

    if (results[0].status === 'fulfilled') {
      equipments = results[0].value.items
    } else { console.warn('加载设备列表失败:', results[0].reason) }
    if (results[1].status === 'fulfilled') {
      workOrders = results[1].value.items
      workOrderTotal = results[1].value.total
    } else { console.warn('加载工单列表失败:', results[1].reason) }
    if (results[2].status === 'fulfilled') {
      workOrderStatistics = results[2].value
    } else { console.warn('加载工单统计失败:', results[2].reason) }
    if (results[3].status === 'fulfilled') {
      failureCodes.symptoms = results[3].value
    } else { console.warn('加载故障现象失败:', results[3].reason) }
    if (results[4].status === 'fulfilled') {
      failureCodes.causes = results[4].value
    } else { console.warn('加载故障原因失败:', results[4].reason) }
    if (results[5].status === 'fulfilled') {
      failureCodes.actions = results[5].value
    } else { console.warn('加载处理措施失败:', results[5].reason) }
    if (results[6].status === 'fulfilled') {
      calibrationPlans = results[6].value.items
      calibrationPlanTotal = results[6].value.total
    } else { console.warn('加载校准计划失败:', results[6].reason) }
    if (results[7].status === 'fulfilled') {
      calibrationRecords = results[7].value.items
      calibrationRecordTotal = results[7].value.total
    } else { console.warn('加载校准记录失败:', results[7].reason) }
    if (results[8].status === 'fulfilled') {
      maintenancePlans = results[8].value.items
      maintenancePlanTotal = results[8].value.total
    } else { console.warn('加载维护计划失败:', results[8].reason) }
  } catch (error) {
    console.warn('维护模块数据加载异常:', error)
  }

  return (
    <MaintenancePage
      initialEquipments={equipments}
      initialWorkOrders={workOrders}
      initialWorkOrderTotal={workOrderTotal}
      initialWorkOrderStatistics={workOrderStatistics}
      initialFailureCodes={failureCodes}
      initialCalibrationPlans={calibrationPlans}
      initialCalibrationPlanTotal={calibrationPlanTotal}
      initialCalibrationRecords={calibrationRecords}
      initialCalibrationRecordTotal={calibrationRecordTotal}
      initialMaintenancePlans={maintenancePlans}
      initialMaintenancePlanTotal={maintenancePlanTotal}
    />
  )
}
