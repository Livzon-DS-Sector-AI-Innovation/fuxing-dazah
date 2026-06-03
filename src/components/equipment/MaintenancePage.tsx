'use client'

import { useEffect, useCallback } from 'react'
import { App, ConfigProvider, Tabs, Button, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { PlusOutlined } from '@ant-design/icons'
import { Equipment, FailureCode, WorkOrder, WorkOrderStatistics, CalibrationPlan, CalibrationRecord } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import {
  fetchWorkOrdersClient, fetchWorkOrderStatisticsClient,
  fetchFailureCodesClient, fetchCalibrationPlansClient, fetchCalibrationRecordsClient,
} from '@/lib/api/equipment-client'
import { WorkOrderStatsCards } from './WorkOrderStatsCards'
import { WorkOrderTable } from './WorkOrderTable'
import { WorkOrderDrawer } from './WorkOrderDrawer'
import { WorkOrderDetailDrawer } from './WorkOrderDetailDrawer'
import { FailureCodePanel } from './FailureCodePanel'
import { FailureCodeDrawer } from './FailureCodeDrawer'
import { CalibrationPlanTable } from './CalibrationPlanTable'
import { CalibrationPlanDrawer } from './CalibrationPlanDrawer'
import { CalibrationRecordTable } from './CalibrationRecordTable'
import { CalibrationRecordDrawer } from './CalibrationRecordDrawer'

interface MaintenancePageProps {
  initialEquipments: Equipment[]
  initialWorkOrders: WorkOrder[]
  initialWorkOrderTotal: number
  initialWorkOrderStatistics: WorkOrderStatistics
  initialFailureCodes: Record<'symptoms' | 'causes' | 'actions', FailureCode[]>
  initialCalibrationPlans: CalibrationPlan[]
  initialCalibrationPlanTotal: number
  initialCalibrationRecords: CalibrationRecord[]
  initialCalibrationRecordTotal: number
}

export function MaintenancePage({
  initialEquipments,
  initialWorkOrders, initialWorkOrderTotal, initialWorkOrderStatistics,
  initialFailureCodes,
  initialCalibrationPlans, initialCalibrationPlanTotal,
  initialCalibrationRecords, initialCalibrationRecordTotal,
}: MaintenancePageProps) {
  const {
    maintenanceTab, setMaintenanceTab,
    workOrderStatusFilter, workOrderPriorityFilter, workOrderTypeFilter,
    workOrderPage, workOrderPageSize, workOrderStatistics,
    setWorkOrders, setWorkOrderTotal, setWorkOrderStatistics, setWorkOrderLoading,
    setFailureCodes,
    setCalibrationPlans, setCalibrationPlanTotal, setCalibrationPlanLoading,
    calibrationPlanStatusFilter, calibrationPlanPage, calibrationPlanPageSize,
    setCalibrationRecords, setCalibrationRecordTotal, setCalibrationRecordLoading,
    calibrationRecordPage, calibrationRecordPageSize,
    openWorkOrderDrawer,
  } = useEquipmentStore()

  // 初始化
  useEffect(() => {
    setWorkOrders(initialWorkOrders)
    setWorkOrderTotal(initialWorkOrderTotal)
    setWorkOrderStatistics(initialWorkOrderStatistics)
    setFailureCodes('symptoms', initialFailureCodes.symptoms)
    setFailureCodes('causes', initialFailureCodes.causes)
    setFailureCodes('actions', initialFailureCodes.actions)
    setCalibrationPlans(initialCalibrationPlans)
    setCalibrationPlanTotal(initialCalibrationPlanTotal)
    setCalibrationRecords(initialCalibrationRecords)
    setCalibrationRecordTotal(initialCalibrationRecordTotal)
  }, [
    initialWorkOrders, initialWorkOrderTotal, initialWorkOrderStatistics,
    initialFailureCodes, initialCalibrationPlans, initialCalibrationPlanTotal,
    initialCalibrationRecords, initialCalibrationRecordTotal,
    setWorkOrders, setWorkOrderTotal, setWorkOrderStatistics,
    setFailureCodes, setCalibrationPlans, setCalibrationPlanTotal,
    setCalibrationRecords, setCalibrationRecordTotal,
  ])

  const fetchWorkOrderData = useCallback(async () => {
    setWorkOrderLoading(true)
    try {
      const [ordersRes, stats] = await Promise.all([
        fetchWorkOrdersClient({
          status: workOrderStatusFilter || undefined,
          priority: workOrderPriorityFilter || undefined,
          order_type: workOrderTypeFilter || undefined,
          page: workOrderPage, page_size: workOrderPageSize,
        }),
        fetchWorkOrderStatisticsClient(),
      ])
      setWorkOrders(ordersRes.items)
      setWorkOrderTotal(ordersRes.total)
      setWorkOrderStatistics(stats)
    } catch (e) {
      console.error('获取工单数据失败:', e)
    } finally {
      setWorkOrderLoading(false)
    }
  }, [workOrderStatusFilter, workOrderPriorityFilter, workOrderTypeFilter, workOrderPage, workOrderPageSize, setWorkOrders, setWorkOrderTotal, setWorkOrderStatistics, setWorkOrderLoading])

  const fetchFailureCodeData = useCallback(async () => {
    try {
      const [symptoms, causes, actions] = await Promise.all([
        fetchFailureCodesClient('symptoms'),
        fetchFailureCodesClient('causes'),
        fetchFailureCodesClient('actions'),
      ])
      setFailureCodes('symptoms', symptoms)
      setFailureCodes('causes', causes)
      setFailureCodes('actions', actions)
    } catch (e) {
      console.error('获取故障代码数据失败:', e)
    }
  }, [setFailureCodes])

  const fetchCalibrationPlanData = useCallback(async () => {
    setCalibrationPlanLoading(true)
    try {
      const res = await fetchCalibrationPlansClient({
        status: calibrationPlanStatusFilter || undefined,
        page: calibrationPlanPage, page_size: calibrationPlanPageSize,
      })
      setCalibrationPlans(res.items)
      setCalibrationPlanTotal(res.total)
    } catch (e) {
      console.error('获取校准计划数据失败:', e)
    } finally {
      setCalibrationPlanLoading(false)
    }
  }, [calibrationPlanStatusFilter, calibrationPlanPage, calibrationPlanPageSize, setCalibrationPlans, setCalibrationPlanTotal, setCalibrationPlanLoading])

  const fetchCalibrationRecordData = useCallback(async () => {
    setCalibrationRecordLoading(true)
    try {
      const res = await fetchCalibrationRecordsClient({
        page: calibrationRecordPage, page_size: calibrationRecordPageSize,
      })
      setCalibrationRecords(res.items)
      setCalibrationRecordTotal(res.total)
    } catch (e) {
      console.error('获取校准记录数据失败:', e)
    } finally {
      setCalibrationRecordLoading(false)
    }
  }, [calibrationRecordPage, calibrationRecordPageSize, setCalibrationRecords, setCalibrationRecordTotal, setCalibrationRecordLoading])

  useEffect(() => {
    if (maintenanceTab === 'work-orders') fetchWorkOrderData()
  }, [maintenanceTab, fetchWorkOrderData])

  useEffect(() => {
    if (maintenanceTab === 'calibration') fetchCalibrationPlanData()
  }, [maintenanceTab, fetchCalibrationPlanData])

  useEffect(() => {
    if (maintenanceTab === 'calibration') fetchCalibrationRecordData()
  }, [maintenanceTab, fetchCalibrationRecordData])

  const tabItems = [
    {
      key: 'work-orders',
      label: '维修工单',
      children: (
        <div>
          <WorkOrderStatsCards statistics={workOrderStatistics} />
          <div style={{ marginTop: 16 }}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold" style={{ fontSize: 18, color: '#1a1a1a', lineHeight: 1.4, margin: 0 }}>
                工单列表
              </h2>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openWorkOrderDrawer()}>
                新建工单
              </Button>
            </div>
            <WorkOrderTable onRefresh={fetchWorkOrderData} />
          </div>
        </div>
      ),
    },
    {
      key: 'failure-codes',
      label: '故障代码',
      children: <FailureCodePanel onRefresh={fetchFailureCodeData} />,
    },
    {
      key: 'calibration',
      label: '校准管理',
      children: (
        <Tabs
          defaultActiveKey="plans"
          items={[
            { key: 'plans', label: '校准计划', children: <CalibrationPlanTable onRefresh={fetchCalibrationPlanData} onRecordRefresh={fetchCalibrationRecordData} /> },
            { key: 'records', label: '校准记录', children: <CalibrationRecordTable onRefresh={fetchCalibrationRecordData} /> },
          ]}
        />
      ),
    },
  ]

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        <div className="p-6">
          <h1 className="font-semibold mb-4" style={{ fontSize: 22, color: '#1a1a1a', lineHeight: 1.3 }}>
            维护保养
          </h1>
          <div style={{ background: '#ffffff', padding: 20, borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Tabs activeKey={maintenanceTab} onChange={setMaintenanceTab} items={tabItems} />
          </div>

          <WorkOrderDrawer equipments={initialEquipments} symptoms={initialFailureCodes.symptoms} onRefresh={fetchWorkOrderData} />
          <WorkOrderDetailDrawer onRefresh={fetchWorkOrderData} />
          <FailureCodeDrawer onRefresh={fetchFailureCodeData} />
          <CalibrationPlanDrawer equipments={initialEquipments} onRefresh={fetchCalibrationPlanData} />
          <CalibrationRecordDrawer calibrationPlans={initialCalibrationPlans} onRefresh={fetchCalibrationRecordData} />
        </div>
      </App>
    </ConfigProvider>
  )
}
