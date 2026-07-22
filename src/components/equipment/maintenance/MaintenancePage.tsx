'use client'

import { useState, useEffect, useCallback } from 'react'
import { App, ConfigProvider, Tabs, Button, Spin, Collapse, Input, InputNumber, Space, Switch } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { PlusOutlined } from '@ant-design/icons'
import {
  Equipment, FailureCode, WorkOrder, WorkOrderStatistics,
  MaintenancePlan,
} from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import {
  fetchWorkOrdersClient, fetchWorkOrderStatisticsClient,
  fetchFailureCodesClient,
  fetchMaintenancePlansClient,
  fetchEquipmentsClient,
  fetchCategoriesClient,
  fetchClaimTimeoutConfigClient,
  fetchAdvanceDaysConfigClient,
} from '@/lib/api/equipment-client'
import { updateClaimTimeoutConfig, updateAdvanceDaysConfig } from '@/actions/equipment'
import { EquipmentCategory } from '@/types/equipment'
import { WorkOrderStatsCards } from './WorkOrderStatsCards'
import { WorkOrderTable } from './WorkOrderTable'
import { WorkOrderDrawer } from './WorkOrderDrawer'
import { WorkOrderDetailDrawer } from './WorkOrderDetailDrawer'
import { FailureCodePanel } from './FailureCodePanel'
import { FailureCodeDrawer } from './FailureCodeDrawer'
import { MaintenancePlanTable } from './MaintenancePlanTable'
import { MaintenancePlanDrawer } from './MaintenancePlanDrawer'
import { InspectionCompleteDrawer } from './InspectionCompleteDrawer'
import { usePermission } from '@/hooks/usePermission'

interface MaintenancePageProps {
  initialEquipments: Equipment[]
  initialWorkOrders: WorkOrder[]
  initialWorkOrderTotal: number
  initialWorkOrderStatistics: WorkOrderStatistics
  initialFailureCodes: Record<'symptoms' | 'causes' | 'actions', FailureCode[]>
  initialMaintenancePlans: MaintenancePlan[]
  initialMaintenancePlanTotal: number
}

export function MaintenancePage({
  initialEquipments,
  initialWorkOrders, initialWorkOrderTotal, initialWorkOrderStatistics,
  initialFailureCodes,
  initialMaintenancePlans, initialMaintenancePlanTotal,
}: MaintenancePageProps) {
  const {
    maintenanceTab, setMaintenanceTab,
    workOrderStatusFilter, workOrderPriorityFilter, workOrderTypeFilter,
    workOrderPage, workOrderPageSize, workOrderStatistics,
    setWorkOrders, setWorkOrderTotal, setWorkOrderStatistics, setWorkOrderLoading,
    setFailureCodes,
    setMaintenancePlans, setMaintenancePlanTotal, setMaintenancePlanLoading,
    maintenancePlanStatusFilter, maintenancePlanKeyword, maintenancePlanModeFilter,
    maintenancePlanPage, maintenancePlanPageSize,
    maintenancePlanSortField, maintenancePlanSortOrder,
    openWorkOrderDrawer,
    openMaintenancePlanDrawer,
  } = useEquipmentStore()

  const { hasPermission } = usePermission()

  // 超时配置
  const [claimTimeoutConfig, setClaimTimeoutConfig] = useState({
    emergency: 15, high: 30, medium: 60, low: 120,
  })

  useEffect(() => {
    fetchClaimTimeoutConfigClient().then(setClaimTimeoutConfig).catch(() => {})
  }, [])

  // 维护计划自动创建配置
  const [advanceDays, setAdvanceDays] = useState(0)
  const [autoExecute, setAutoExecute] = useState(true)

  useEffect(() => {
    fetchAdvanceDaysConfigClient().then(c => {
      setAdvanceDays(c.advance_days)
      setAutoExecute(c.auto_execute)
    }).catch(() => {})
  }, [])

  const { message: configMsg } = App.useApp()

  const handleSaveConfig = async () => {
    const result = await updateClaimTimeoutConfig(claimTimeoutConfig)
    if (!result.success) {
      configMsg.error(result.error)
      return
    }
    configMsg.success('超时配置保存成功')
  }

  const handleSaveAdvanceDays = async () => {
    const result = await updateAdvanceDaysConfig(advanceDays, autoExecute)
    if (!result.success) {
      configMsg.error(result.error)
      return
    }
    configMsg.success('自动创建配置保存成功')
  }

  // 设备列表和分类（客户端回退）
  const [equipments, setEquipmentsState] = useState<Equipment[]>(initialEquipments)
  const [categories, setCategoriesState] = useState<EquipmentCategory[]>([])

  useEffect(() => {
    // 如果服务端没拿到设备数据，客户端重新获取
    if (initialEquipments.length === 0) {
      fetchEquipmentsClient({ page: 1, page_size: 200 }).then((res) => {
        setEquipmentsState(res.items)
      }).catch(() => {})
    }
    fetchCategoriesClient().then(setCategoriesState).catch(() => {})
  }, [initialEquipments.length])

  // 初始化
  useEffect(() => {
    setWorkOrders(initialWorkOrders)
    setWorkOrderTotal(initialWorkOrderTotal)
    setWorkOrderStatistics(initialWorkOrderStatistics)
    setFailureCodes('symptoms', initialFailureCodes.symptoms)
    setFailureCodes('causes', initialFailureCodes.causes)
    setFailureCodes('actions', initialFailureCodes.actions)
    setMaintenancePlans(initialMaintenancePlans)
    setMaintenancePlanTotal(initialMaintenancePlanTotal)
  }, [
    initialWorkOrders, initialWorkOrderTotal, initialWorkOrderStatistics,
    initialFailureCodes,
    initialMaintenancePlans, initialMaintenancePlanTotal,
    setWorkOrders, setWorkOrderTotal, setWorkOrderStatistics,
    setFailureCodes,
    setMaintenancePlans, setMaintenancePlanTotal,
  ])

  const fetchWorkOrderData = useCallback(async () => {
    setWorkOrderLoading(true)
    try {
      const [ordersRes, stats] = await Promise.all([
        fetchWorkOrdersClient({
          status: workOrderStatusFilter || undefined,
          exclude_status: workOrderStatusFilter ? undefined : '已关闭',
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

  const fetchMaintenancePlanData = useCallback(async () => {
    setMaintenancePlanLoading(true)
    try {
      const res = await fetchMaintenancePlansClient({
        status: maintenancePlanStatusFilter || undefined,
        keyword: maintenancePlanKeyword || undefined,
        plan_mode: maintenancePlanModeFilter || undefined,
        page: maintenancePlanPage, page_size: maintenancePlanPageSize,
        sort_field: maintenancePlanSortField || undefined,
        sort_order: maintenancePlanSortOrder || undefined,
      })
      setMaintenancePlans(res.items)
      setMaintenancePlanTotal(res.total)
    } catch (e) {
      console.error('获取维护计划数据失败:', e)
    } finally {
      setMaintenancePlanLoading(false)
    }
  }, [
    maintenancePlanStatusFilter, maintenancePlanKeyword, maintenancePlanModeFilter,
    maintenancePlanPage, maintenancePlanPageSize,
    maintenancePlanSortField, maintenancePlanSortOrder,
    setMaintenancePlans, setMaintenancePlanTotal, setMaintenancePlanLoading,
  ])

  useEffect(() => {
    if (maintenanceTab === 'work-orders') fetchWorkOrderData()
  }, [maintenanceTab, fetchWorkOrderData])

  useEffect(() => {
    if (maintenanceTab === 'maintenance-plans') fetchMaintenancePlanData()
  }, [maintenanceTab, fetchMaintenancePlanData])

  const tabItems = [
    {
      key: 'work-orders',
      label: '维修工单',
      children: (
        <div>
          <WorkOrderStatsCards statistics={workOrderStatistics} />

          <Collapse
            style={{ marginTop: 16, marginBottom: 16 }}
            items={[{
              key: 'timeout-config',
              label: '抢单超时配置',
              children: (
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                  {[
                    { key: 'emergency', label: '紧急', color: '#e03131' },
                    { key: 'high', label: '高', color: '#dd5b00' },
                    { key: 'medium', label: '中', color: '#5645d4' },
                    { key: 'low', label: '低', color: '#787671' },
                  ].map(({ key, label, color }) => (
                    <div key={key}>
                      <div style={{ marginBottom: 4, fontSize: 13, color, fontWeight: 500 }}>{label}优先级</div>
                      <Space.Compact>
                        <InputNumber
                          min={1} max={1440}
                          value={claimTimeoutConfig[key as keyof typeof claimTimeoutConfig]}
                          onChange={(v) => setClaimTimeoutConfig(prev => ({ ...prev, [key]: v || 15 }))}
                        />
                        <Button disabled>分钟</Button>
                      </Space.Compact>
                    </div>
                  ))}
                  {hasPermission('equipment:work_order:update') && (
                    <Button type="primary" onClick={handleSaveConfig}>保存配置</Button>
                  )}
                </div>
              ),
            }]}
          />

          <div style={{ marginTop: 16 }}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold" style={{ fontSize: 18, color: '#1a1a1a', lineHeight: 1.4, margin: 0 }}>
                工单列表
              </h2>
              {hasPermission('equipment:work_order:create') && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openWorkOrderDrawer()}>
                  新建工单
                </Button>
              )}
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
      key: 'maintenance-plans',
      label: '维护计划',
      children: (
        <div>
          <Collapse
            style={{ marginBottom: 16 }}
            items={[{
              key: 'advance-days-config',
              label: '维护计划自动创建配置',
              children: (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, padding: '4px 0 16px' }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', lineHeight: 1.5 }}>
                        提前创建
                      </div>
                      <div style={{ fontSize: 13, color: '#787671', lineHeight: 1.4, marginTop: 2 }}>
                        维护到期前多少天自动创建「计划维护」工单
                      </div>
                    </div>
                    <Space.Compact style={{ flexShrink: 0 }}>
                      <InputNumber
                        min={1} max={364}
                        value={advanceDays}
                        onChange={(v) => setAdvanceDays(v || 0)}
                        style={{ width: 72 }}
                      />
                      <Button disabled>天</Button>
                    </Space.Compact>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, padding: '16px 0', borderTop: '1px solid #ede9e4' }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', lineHeight: 1.5 }}>
                        自动执行
                      </div>
                      <div style={{ fontSize: 13, color: '#787671', lineHeight: 1.4, marginTop: 2 }}>
                        {autoExecute
                          ? '已配置执行人的工单将直接进入「执行中」'
                          : '工单创建后保持「待处理」，由维修人手动开始'}
                      </div>
                    </div>
                    <Switch
                      checked={autoExecute}
                      onChange={setAutoExecute}
                      style={{ flexShrink: 0 }}
                    />
                  </div>
                  {hasPermission('equipment:maintenance:update') && (
                    <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 16, borderTop: '1px solid #e5e3df' }}>
                      <Button type="primary" onClick={handleSaveAdvanceDays}>保存配置</Button>
                    </div>
                  )}
                </div>
              ),
            }]}
          />
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold" style={{ fontSize: 18, color: '#1a1a1a', lineHeight: 1.4, margin: 0 }}>
              维护计划列表
            </h2>
            {hasPermission('equipment:maintenance:create') && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openMaintenancePlanDrawer()}>
                新建维护计划
              </Button>
            )}
          </div>
          <MaintenancePlanTable onRefresh={fetchMaintenancePlanData} equipments={equipments} />
        </div>
      ),
    },
  ]

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        <div style={{ marginBottom: 24 }}>
          <h2 style={{
            fontSize: 22, fontWeight: 600, color: '#1a1a1a',
            margin: 0, marginBottom: 4, lineHeight: 1.3,
          }}>
            维护保养
          </h2>
          <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
            工单管理 · 故障代码 · 维护计划
          </p>
        </div>
        <div style={{ background: '#ffffff', padding: 20, borderRadius: 12, border: '1px solid #e5e3df' }}>
          <Tabs activeKey={maintenanceTab} onChange={setMaintenanceTab} items={tabItems} />
        </div>

        <WorkOrderDrawer equipments={equipments} symptoms={initialFailureCodes.symptoms} onRefresh={fetchWorkOrderData} />
        <WorkOrderDetailDrawer onRefresh={fetchWorkOrderData} />
        <FailureCodeDrawer onRefresh={fetchFailureCodeData} />
        <MaintenancePlanDrawer equipments={equipments} onRefresh={fetchMaintenancePlanData} />
        <InspectionCompleteDrawer onRefresh={fetchWorkOrderData} />
      </App>
    </ConfigProvider>
  )
}
