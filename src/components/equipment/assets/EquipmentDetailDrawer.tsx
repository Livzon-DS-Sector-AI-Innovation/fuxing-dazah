'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { App, Drawer, Descriptions, Table, Tabs, Tag, Space, Empty, Spin, Timeline } from 'antd'
import { ToolOutlined, SearchOutlined, CalendarOutlined, HistoryOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { Equipment, MaintenancePlan, WorkOrder, EquipmentStatusLog, StatusLogSource } from '@/types/equipment'
import type { InspectionTask } from '@/types/inspection'
import { fetchMaintenancePlansClient, fetchWorkOrdersClient, fetchStatusLogsClient } from '@/lib/api/equipment-client'
import { fetchInspectionHistory } from '@/lib/api/inspection'
import { EQUIP_STATUS_PILL_COLORS, RUNNING_STATUS_PILL_COLORS, EQUIPMENT_STATUS_COLORS, RUNNING_STATUS_COLORS, monoFont, pillNeutral, pillSuccess, pillError, pillPurple, statusPill } from '@/components/equipment/shared/shared-styles'
import type { EquipmentImportance } from '@/types/equipment'

interface EquipmentDetailDrawerProps {
  open: boolean
  equipment: Equipment | null
  categoryName: string
  locationName: string
  onClose: () => void
}

const MAINTENANCE_STATUS_MAP: Record<string, { color: string; bg: string }> = {
  '启用': { color: '#1aae39', bg: '#d9f3e1' },
  '停用': { color: '#787671', bg: '#f0eeec' },
  '已完成': { color: '#0075de', bg: '#dcecfa' },
}

const WORK_ORDER_STATUS_MAP: Record<string, { color: string; bg: string }> = {
  '待处理': { color: '#e03131', bg: '#fde0ec' },
  '执行中': { color: '#7b3ff2', bg: '#e6e0f5' },
  '待验收': { color: '#0075de', bg: '#dcecfa' },
  '已完成': { color: '#1aae39', bg: '#d9f3e1' },
  '已关闭': { color: '#787671', bg: '#f0eeec' },
}

const TASK_STATUS_MAP: Record<string, { color: string; bg: string }> = {
  '待执行': { color: '#0075de', bg: '#dcecfa' },
  '执行中': { color: '#dd5b00', bg: '#ffe8d4' },
  '已完成': { color: '#1aae39', bg: '#d9f3e1' },
  '已关闭': { color: '#787671', bg: '#f0eeec' },
}

// 从共享色表派生 full pill style
const EQUIP_STATUS_MAP: Record<string, React.CSSProperties> = Object.fromEntries(
  Object.entries(EQUIP_STATUS_PILL_COLORS).map(([k, v]) => [k, statusPill(v.color, v.bg)])
)

const RUNNING_STATUS_MAP: Record<string, React.CSSProperties> = Object.fromEntries(
  Object.entries(RUNNING_STATUS_PILL_COLORS).map(([k, v]) => [k, statusPill(v.color, v.bg)])
)

// 状态历史时间线同时渲染设备状态与运行状态两类日志
const LOG_PILL_MAP: Record<string, React.CSSProperties> = {
  ...EQUIP_STATUS_MAP,
  ...RUNNING_STATUS_MAP,
}

const LOG_DOT_COLORS: Record<string, string> = {
  ...EQUIPMENT_STATUS_COLORS,
  ...RUNNING_STATUS_COLORS,
}

const IMPORTANCE_MAP: Record<EquipmentImportance, React.CSSProperties> = {
  '高': pillPurple,
  '中': pillNeutral,
  '低': pillNeutral,
}

const STATUS_LOG_SOURCE_MAP: Record<StatusLogSource, string> = {
  init: '初始基线',
  create: '新建登记',
  manual: '台账编辑',
  work_order: '工单联动',
  import: 'Excel导入',
}

const PRIORITY_STYLE_MAP: Record<string, React.CSSProperties> = {
  '紧急': { color: '#e03131', fontWeight: 600 },
  '高':   { color: '#dd5b00', fontWeight: 600 },
}

export function EquipmentDetailDrawer({ open, equipment, categoryName, locationName, onClose }: EquipmentDetailDrawerProps) {
  const { message } = App.useApp()
  const [activeTab, setActiveTab] = useState<'plans' | 'history' | 'orders' | 'status'>('plans')

  // 维护保养计划
  const [plans, setPlans] = useState<MaintenancePlan[]>([])
  const [plansLoading, setPlansLoading] = useState(false)

  // 巡检记录
  const [history, setHistory] = useState<InspectionTask[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // 维修工单
  const [orders, setOrders] = useState<WorkOrder[]>([])
  const [ordersLoading, setOrdersLoading] = useState(false)

  // 状态历史
  const [statusLogs, setStatusLogs] = useState<EquipmentStatusLog[]>([])
  const [statusLogsLoading, setStatusLogsLoading] = useState(false)

  // 代际计数器 — 快速切换设备时忽略旧请求
  const genRef = useRef(0)

  const loadPlans = useCallback(async (gen: number) => {
    if (!equipment) return
    setPlansLoading(true)
    try {
      const result = await fetchMaintenancePlansClient({ equipment_id: equipment.id, page: 1, page_size: 50 })
      if (genRef.current === gen) setPlans(result.items)
    } catch {
      if (genRef.current === gen) message.error('加载维护保养计划失败')
    } finally {
      if (genRef.current === gen) setPlansLoading(false)
    }
  }, [equipment, message])

  const loadHistory = useCallback(async (gen: number) => {
    if (!equipment) return
    setHistoryLoading(true)
    try {
      const result = await fetchInspectionHistory({ equipment_id: equipment.id, page: 1, page_size: 50 })
      if (genRef.current === gen) setHistory(result.items)
    } catch {
      if (genRef.current === gen) message.error('加载巡检记录失败')
    } finally {
      if (genRef.current === gen) setHistoryLoading(false)
    }
  }, [equipment, message])

  const loadOrders = useCallback(async (gen: number) => {
    if (!equipment) return
    setOrdersLoading(true)
    try {
      const result = await fetchWorkOrdersClient({ equipment_id: equipment.id, page: 1, page_size: 50 })
      if (genRef.current === gen) setOrders(result.items)
    } catch {
      if (genRef.current === gen) message.error('加载维修工单失败')
    } finally {
      if (genRef.current === gen) setOrdersLoading(false)
    }
  }, [equipment, message])

  const loadStatusLogs = useCallback(async (gen: number) => {
    if (!equipment) return
    setStatusLogsLoading(true)
    try {
      const data = await fetchStatusLogsClient(equipment.id)
      if (genRef.current === gen) setStatusLogs(data)
    } catch {
      if (genRef.current === gen) message.error('加载状态历史失败')
    } finally {
      if (genRef.current === gen) setStatusLogsLoading(false)
    }
  }, [equipment, message])

  useEffect(() => {
    if (open && equipment) {
      const gen = ++genRef.current
      Promise.allSettled([loadPlans(gen), loadHistory(gen), loadOrders(gen), loadStatusLogs(gen)])
      setActiveTab('plans')
    }
  }, [open, equipment, loadPlans, loadHistory, loadOrders, loadStatusLogs])

  // ── 维护保养计划列 ──
  const planColumns: ColumnsType<MaintenancePlan> = [
    { title: '计划名称', dataIndex: 'plan_name', key: 'plan_name', width: 150, ellipsis: true },
    {
      title: '类型', dataIndex: 'plan_type', key: 'plan_type', width: 100,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: '周期', key: 'frequency', width: 100,
      render: (_: unknown, r: MaintenancePlan) => `${r.frequency}${r.frequency_unit}`,
    },
    { title: '上次维护', dataIndex: 'last_maintenance_date', key: 'last_maintenance_date', width: 110, render: (d: string | null) => d || '-' },
    { title: '下次维护', dataIndex: 'next_maintenance_date', key: 'next_maintenance_date', width: 110, render: (d: string | null) => d || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const m = MAINTENANCE_STATUS_MAP[s] || { color: '#787671', bg: '#f0eeec' }
        return <span style={statusPill(m.color, m.bg)}>{s}</span>
      },
    },
  ]

  // ── 巡检记录列 ──
  const historyColumns: ColumnsType<InspectionTask> = [
    {
      title: '任务编号', dataIndex: 'task_no', key: 'task_no', width: 170,
      render: (no: string) => <span style={monoFont}>{no}</span>,
    },
    { title: '巡检类型', dataIndex: 'plan_type', key: 'plan_type', width: 90 },
    { title: '计划日期', dataIndex: 'planned_date', key: 'planned_date', width: 100 },
    { title: '巡检人', dataIndex: 'assignee_name', key: 'assignee_name', width: 80, render: (n: string | undefined) => n || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const m = TASK_STATUS_MAP[s] || { color: '#787671', bg: '#f0eeec' }
        return <span style={statusPill(m.color, m.bg)}>{s}</span>
      },
    },
    {
      title: '结果', dataIndex: 'overall_result', key: 'overall_result', width: 75,
      render: (r: string | null) => {
        if (r == null) return '-'
        return <span style={r === '正常' ? pillSuccess : pillError}>{r}</span>
      },
    },
  ]

  // ── 维修工单列 ──
  const orderColumns: ColumnsType<WorkOrder> = [
    {
      title: '工单编号', dataIndex: 'work_order_no', key: 'work_order_no', width: 170,
      render: (no: string) => <span style={monoFont}>{no}</span>,
    },
    {
      title: '类型', dataIndex: 'order_type', key: 'order_type', width: 90,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 70,
      render: (p: string) => (
        <span style={{ fontSize: 13, ...PRIORITY_STYLE_MAP[p] }}>{p}</span>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const m = WORK_ORDER_STATUS_MAP[s] || { color: '#787671', bg: '#f0eeec' }
        return <span style={statusPill(m.color, m.bg)}>{s}</span>
      },
    },
    { title: '报修人', dataIndex: 'reporter_name', key: 'reporter_name', width: 80, render: (n: string | undefined) => n || '-' },
    { title: '维修人', dataIndex: 'assignee_name', key: 'assignee_name', width: 80, render: (n: string | undefined) => n || '-' },
    { title: '报修时间', dataIndex: 'reported_at', key: 'reported_at', width: 100, render: (d: string) => d?.slice(0, 10) || '-' },
  ]

  const tabItems = [
    {
      key: 'plans' as const,
      label: <span><CalendarOutlined /> 维护保养计划</span>,
      children: (
        <Spin spinning={plansLoading}>
          {plans.length === 0 ? (
            <Empty description="暂无维护保养计划" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table columns={planColumns} dataSource={plans} rowKey="id" size="small" pagination={false} scroll={{ x: 'max-content' }} />
          )}
        </Spin>
      ),
    },
    {
      key: 'history' as const,
      label: <span><SearchOutlined /> 巡检记录</span>,
      children: (
        <Spin spinning={historyLoading}>
          {history.length === 0 ? (
            <Empty description="暂无巡检记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table columns={historyColumns} dataSource={history} rowKey="id" size="small" pagination={false} scroll={{ x: 'max-content' }} />
          )}
        </Spin>
      ),
    },
    {
      key: 'orders' as const,
      label: <span><ToolOutlined /> 维修工单</span>,
      children: (
        <Spin spinning={ordersLoading}>
          {orders.length === 0 ? (
            <Empty description="暂无维修工单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table columns={orderColumns} dataSource={orders} rowKey="id" size="small" pagination={false} scroll={{ x: 'max-content' }} />
          )}
        </Spin>
      ),
    },
    {
      key: 'status' as const,
      label: <span><HistoryOutlined /> 状态历史</span>,
      children: (
        <Spin spinning={statusLogsLoading}>
          {statusLogs.length === 0 ? (
            <Empty description="暂无状态变更记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Timeline
              style={{ paddingTop: 8 }}
              items={statusLogs.map(log => ({
                key: log.id,
                color: LOG_DOT_COLORS[log.new_status] || '#787671',
                content: (
                  <div>
                    <Space size={8}>
                      {log.log_type === 'running' && (
                        <Tag style={{ color: '#0075de', marginInlineEnd: 0 }}>运行</Tag>
                      )}
                      {log.old_status ? (
                        <span style={LOG_PILL_MAP[log.old_status] || pillNeutral}>{log.old_status}</span>
                      ) : (
                        <span style={{ fontSize: 12, color: '#a4a097' }}>初始状态</span>
                      )}
                      <span style={{ color: '#a4a097' }}>→</span>
                      <span style={LOG_PILL_MAP[log.new_status] || pillNeutral}>{log.new_status}</span>
                    </Space>
                    <div style={{ fontSize: 12, color: '#a4a097', marginTop: 4 }}>
                      {dayjs(log.changed_at).format('YYYY-MM-DD HH:mm')}
                      <Tag style={{ marginLeft: 8, color: '#787671' }}>{STATUS_LOG_SOURCE_MAP[log.source] || log.source}</Tag>
                    </div>
                  </div>
                ),
              }))}
            />
          )}
        </Spin>
      ),
    },
  ]

  if (!equipment) return null

  return (
    <Drawer
      title="设备详情"
      size={860}
      open={open}
      onClose={onClose}
      destroyOnHidden
      styles={{
        header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
        body: { padding: '24px' },
      }}
    >
      {/* 基本信息 */}
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: '0 0 16px 0' }}>基本信息</h3>
        <Descriptions bordered size="small" column={2} styles={{ label: { fontWeight: 500, color: '#5d5b54', width: 100 } }}>
          <Descriptions.Item label="设备编号">
            <span style={monoFont}>{equipment.equipment_no}</span>
          </Descriptions.Item>
          <Descriptions.Item label="设备名称">
            <span style={{ fontWeight: 600 }}>{equipment.name}</span>
          </Descriptions.Item>
          <Descriptions.Item label="设备分类">{categoryName || '-'}</Descriptions.Item>
          <Descriptions.Item label="设备位置">{locationName || '-'}</Descriptions.Item>
          <Descriptions.Item label="归属部门">{equipment.department_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="负责人">{equipment.responsible_person_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="设备状态">
            <span style={EQUIP_STATUS_MAP[equipment.status] || pillNeutral}>{equipment.status}</span>
          </Descriptions.Item>
          <Descriptions.Item label="运行状态">
            <span style={RUNNING_STATUS_MAP[equipment.running_status] || pillNeutral}>{equipment.running_status}</span>
          </Descriptions.Item>
          <Descriptions.Item label="重要性">
            <span style={IMPORTANCE_MAP[equipment.importance as EquipmentImportance] || pillNeutral}>{equipment.importance}</span>
          </Descriptions.Item>
          <Descriptions.Item label="设备型号">{equipment.model || '-'}</Descriptions.Item>
          <Descriptions.Item label="设备规格">{equipment.specification || '-'}</Descriptions.Item>
          <Descriptions.Item label="制造商">{equipment.manufacturer || '-'}</Descriptions.Item>
          <Descriptions.Item label="供应商">{equipment.supplier || '-'}</Descriptions.Item>
          <Descriptions.Item label="出厂日期">{equipment.production_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="投用日期" span={2}>{equipment.commissioning_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>{equipment.description || '-'}</Descriptions.Item>
        </Descriptions>
      </div>

      {/* 关联记录 */}
      <div>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: '0 0 16px 0' }}>关联记录</h3>
        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as 'plans' | 'history' | 'orders' | 'status')}
          items={tabItems}
        />
      </div>
    </Drawer>
  )
}
