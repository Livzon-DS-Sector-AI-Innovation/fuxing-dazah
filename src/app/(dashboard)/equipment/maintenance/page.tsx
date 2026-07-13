export const dynamic = 'force-dynamic'

import '@/lib/http-server'
import { MaintenancePage } from '@/components/equipment'
import {
  fetchEquipments, fetchWorkOrders, fetchWorkOrderStatistics, fetchFailureCodes,
  fetchMaintenancePlans,
} from '@/lib/api/equipment'
import {
  Equipment, FailureCode, WorkOrder, WorkOrderStatistics,
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
      maintenancePlans = results[6].value.items
      maintenancePlanTotal = results[6].value.total
    } else { console.warn('加载维护计划失败:', results[6].reason) }
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
      initialMaintenancePlans={maintenancePlans}
      initialMaintenancePlanTotal={maintenancePlanTotal}
    />
  )
}
