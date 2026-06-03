import { MaintenancePage } from '@/components/equipment'
import { fetchEquipments, fetchWorkOrders, fetchWorkOrderStatistics, fetchFailureCodes, fetchCalibrationPlans, fetchCalibrationRecords } from '@/lib/api/equipment'
import { Equipment, FailureCode, WorkOrder, WorkOrderStatistics, CalibrationPlan, CalibrationRecord } from '@/types/equipment'

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

  try {
    const result = await Promise.all([
      fetchEquipments({ page: 1, page_size: 200 }),
      fetchWorkOrders({ page: 1, page_size: 20 }),
      fetchWorkOrderStatistics(),
      fetchFailureCodes('symptoms'),
      fetchFailureCodes('causes'),
      fetchFailureCodes('actions'),
      fetchCalibrationPlans({ page: 1, page_size: 20 }),
      fetchCalibrationRecords({ page: 1, page_size: 20 }),
    ])

    equipments = result[0].items
    workOrders = result[1].items
    workOrderTotal = result[1].total
    workOrderStatistics = result[2]
    failureCodes = {
      symptoms: result[3],
      causes: result[4],
      actions: result[5],
    }
    calibrationPlans = result[6].items
    calibrationPlanTotal = result[6].total
    calibrationRecords = result[7].items
    calibrationRecordTotal = result[7].total
  } catch (error) {
    console.warn('维护模块数据加载失败，使用空数据:', error)
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
    />
  )
}
