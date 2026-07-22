export const dynamic = 'force-dynamic'

import '@/lib/http-server'
import { StatsDashboard } from '@/components/equipment'
import {
  fetchEquipmentStatistics,
  fetchWorkOrderStatistics,
  fetchStockWarnings,
  fetchOverdueMaintenancePlans,
  fetchWorkOrders,
} from '@/lib/api/equipment'
import type {
  EquipmentStatus,
  WorkOrderStatus,
  WorkOrderPriority,
  WorkOrderType,
  EquipmentStatistics,
  WorkOrderStatistics,
  StockWarning,
  MaintenancePlan,
  WorkOrder,
} from '@/types/equipment'

// 默认空数据
const defaultEquipmentStats: EquipmentStatistics = {
  total: 0,
  by_status: { '完好': 0, '备用': 0, '故障待检': 0, '维修中': 0, '报废': 0 } as Record<EquipmentStatus, number>,
  by_category: {} as Record<string, number>,
  by_location: {} as Record<string, number>,
}

const defaultWorkOrderStats: WorkOrderStatistics = {
  total: 0,
  by_status: { '待处理': 0, '执行中': 0, '待验收': 0, '已完成': 0, '已关闭': 0 } as Record<WorkOrderStatus, number>,
  by_type: { '故障维修': 0, '计划维护': 0, '校准': 0, '异常处理': 0, '日常维护': 0 } as Record<WorkOrderType, number>,
  by_priority: { '紧急': 0, '高': 0, '中': 0, '低': 0 } as Record<WorkOrderPriority, number>,
}

export default async function StatsPage() {
  let equipmentStats: EquipmentStatistics = defaultEquipmentStats
  let workOrderStats: WorkOrderStatistics = defaultWorkOrderStats
  let stockWarnings: StockWarning[] = []
  let overduePlans: MaintenancePlan[] = []
  let recentWorkOrders: WorkOrder[] = []

  try {
    const results = await Promise.allSettled([
      fetchEquipmentStatistics(),
      fetchWorkOrderStatistics(),
      fetchStockWarnings(),
      fetchOverdueMaintenancePlans(),
      fetchWorkOrders({ page: 1, page_size: 10 }),
    ])

    // 依次解构，每个接口错误不影响其他
    const [eqResult, woResult, swResult, overdueResult, ordersResult] = results

    if (eqResult.status === 'fulfilled') {
      equipmentStats = eqResult.value
    } else {
      console.warn('设备统计加载失败:', eqResult.reason)
    }

    if (woResult.status === 'fulfilled') {
      workOrderStats = woResult.value
    } else {
      console.warn('工单统计加载失败:', woResult.reason)
    }

    if (swResult.status === 'fulfilled') {
      stockWarnings = swResult.value
    } else {
      console.warn('库存预警加载失败:', swResult.reason)
    }

    if (overdueResult.status === 'fulfilled') {
      overduePlans = overdueResult.value
    } else {
      console.warn('逾期维护计划加载失败:', overdueResult.reason)
    }

    if (ordersResult.status === 'fulfilled') {
      recentWorkOrders = ordersResult.value.items || []
    } else {
      console.warn('近期工单加载失败:', ordersResult.reason)
    }
  } catch (error) {
    console.warn('设备仪表盘数据加载异常:', error)
  }

  return (
    <StatsDashboard
      initialData={{
        equipmentStats,
        workOrderStats,
        stockWarnings,
        overduePlans,
        recentWorkOrders,
      }}
    />
  )
}
