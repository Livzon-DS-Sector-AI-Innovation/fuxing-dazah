'use client'

import { useEffect, useCallback, useState } from 'react'
import { App, Button, Space, Table, Tooltip } from 'antd'
import { PlayCircleOutlined, CloseCircleOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useInspectionStore } from '@/stores/inspection'
import { startInspectionTask, closeInspectionTask } from '@/actions/inspection'
import {
  fetchInspectionTasks, fetchInspectionRouteById,
  fetchInspectionTemplateByIdClient, fetchInspectionTaskById,
} from '@/lib/api/inspection'
import { statusPill, pillSuccess, pillError, pillTab, actionLink, linkSuccess, linkWarning, linkMuted } from '@/components/equipment/shared/shared-styles'
import type { InspectionTask, InspectionTaskStatus } from '@/types/inspection'
import type { InspectionTemplate, InspectionTemplateItem } from '@/types/equipment'
import { usePermission } from '@/hooks/usePermission'

interface Props {
  templates: InspectionTemplate[]
  equipments: { id: string; name: string; equipment_no: string }[]
}

const STATUS_MAP: Record<string, { label: string; color: string; bg: string; icon: string }> = {
  '待执行': { label: '待执行', color: '#0075de', bg: '#dcecfa', icon: '○' },
  '执行中': { label: '执行中', color: '#dd5b00', bg: '#ffe8d4', icon: '◉' },
  '已完成': { label: '已完成', color: '#1aae39', bg: '#d9f3e1', icon: '✓' },
  '已关闭': { label: '已关闭', color: '#787671', bg: '#f0eeec', icon: '✕' },
}

const ALL_STATUSES: InspectionTaskStatus[] = ['待执行', '执行中', '已完成']

export function InspectionTasksTab({ templates, equipments: allEquipments }: Props) {
  const { hasPermission } = usePermission()
  const { message, modal } = App.useApp()
  const {
    tasks, tasksTotal, tasksPage, tasksPageSize, tasksLoading, tasksStatusFilter, tasksRefreshKey,
    setTasks, setTasksTotal, setTasksLoading, setTasksPage, setTasksPageSize, setTasksStatusFilter,
    openTaskDrawer, setExecutingTask, triggerTasksRefresh,
  } = useInspectionStore()

  const [startingIds, setStartingIds] = useState<Set<string>>(new Set())

  const loadTasks = useCallback(async () => {
    setTasksLoading(true)
    try {
      // 默认排除已关闭任务（在历史记录中查看），指定 status 时不过滤
      const result = await fetchInspectionTasks({
        status: tasksStatusFilter || undefined,
        exclude_status: tasksStatusFilter ? undefined : '已关闭',
        page: tasksPage, page_size: tasksPageSize,
      })
      setTasks(result.items)
      setTasksTotal(result.total)
    } catch (err: unknown) {
      message.error((err as Error).message || '加载任务失败')
    } finally {
      setTasksLoading(false)
    }
  }, [tasksStatusFilter, tasksPage, tasksPageSize, tasksRefreshKey, setTasks, setTasksTotal, setTasksLoading, message])

  useEffect(() => { loadTasks() }, [loadTasks])

  const enterExecuteView = useCallback(async (record: InspectionTask) => {
    let routeDetail = null
    const items: Record<string, InspectionTemplateItem[]> = {}

    if (record.route_id) {
      // 线路巡检：按设备收集各自绑定的模板检查项
      try { routeDetail = await fetchInspectionRouteById(record.route_id) } catch { /* */ }
      if (routeDetail?.locations) {
        // 缓存已加载的模板（同模板可被多设备共享）
        const tplCache = new Map<string, InspectionTemplateItem[]>()
        for (const loc of routeDetail.locations) {
          for (const eq of (loc.equipments || [])) {
            const eqId = eq.equipment_id
            if (!items[eqId]) items[eqId] = []
            for (const rt of (eq.templates || [])) {
              if (!rt.template_id) continue
              if (!tplCache.has(rt.template_id)) {
                try {
                  const tpl = await fetchInspectionTemplateByIdClient(rt.template_id)
                  tplCache.set(rt.template_id, tpl?.items || [])
                } catch { tplCache.set(rt.template_id, []) }
              }
              const tplItems = tplCache.get(rt.template_id) || []
              for (const item of tplItems) {
                if (!items[eqId].some(i => i.id === item.id)) {
                  items[eqId].push(item)
                }
              }
            }
          }
        }
      }
    } else {
      // 设备巡检：按 equipment_templates 收集各设备的检查项
      const tplCache = new Map<string, InspectionTemplateItem[]>()
      const allEqIds = record.equipment_ids || (record.equipment_id ? [record.equipment_id] : [])
      if (record.equipment_templates) {
        // 新方式：每个设备有各自的模板列表
        for (const eqId of allEqIds) {
          if (!items[eqId]) items[eqId] = []
          const tids = record.equipment_templates[eqId] || []
          for (const tid of tids) {
            if (!tplCache.has(tid)) {
              try {
                const tpl = await fetchInspectionTemplateByIdClient(tid)
                tplCache.set(tid, tpl?.items || [])
              } catch { tplCache.set(tid, []) }
            }
            const tplItems = tplCache.get(tid) || []
            for (const item of tplItems) {
              if (!items[eqId].some(i => i.id === item.id)) {
                items[eqId].push(item)
              }
            }
          }
        }
      }
      // 兼容旧数据：template_ids 扁平列表 → 所有设备共用
      if (record.template_ids && record.template_ids.length > 0) {
        const shared: InspectionTemplateItem[] = []
        for (const tid of record.template_ids) {
          if (!tplCache.has(tid)) {
            try {
              const tpl = await fetchInspectionTemplateByIdClient(tid)
              tplCache.set(tid, tpl?.items || [])
            } catch { tplCache.set(tid, []) }
          }
          shared.push(...(tplCache.get(tid) || []))
        }
        for (const eqId of allEqIds) {
          if (!items[eqId]) items[eqId] = []
          for (const item of shared) {
            if (!items[eqId].some(i => i.id === item.id)) {
              items[eqId].push(item)
            }
          }
        }
      }
    }
    const eqIds = record.equipment_ids || undefined
    const eqInfos = eqIds
      ? allEquipments.filter(e => eqIds.includes(e.id)).map(e => ({ id: e.id, name: e.name, no: e.equipment_no }))
      : undefined
    // 获取任务详情以拿到已完成设备列表
    let completedIds: string[] = []
    try {
      const taskDetail = await fetchInspectionTaskById(record.id)
      completedIds = taskDetail.completed_equipment_ids || []
    } catch { /* 获取失败不阻塞 */ }
    const totalItemCount = Object.values(items).reduce((sum, arr) => sum + arr.length, 0)
    setExecutingTask(
      record.id, record.plan_type, routeDetail, items,
      totalItemCount > 0 ? '合并模板' : '检查模板',
      record.equipment_id, record.equipment_name, record.equipment_no,
      eqIds, eqInfos, completedIds,
    )
  }, [allEquipments, setExecutingTask])

  const handleStart = useCallback(async (record: InspectionTask) => {
    if (startingIds.has(record.id)) return
    setStartingIds(prev => new Set(prev).add(record.id))
    try {
      if (record.status === '待执行') {
        const result = await startInspectionTask(record.id)
        if (!result.success) { message.error(result.error); return }
        message.success('已开始巡检')
        triggerTasksRefresh()
      }
      await enterExecuteView(record)
    } catch (err: unknown) {
      message.error((err as Error).message || '操作失败')
    } finally {
      setStartingIds(prev => { const next = new Set(prev); next.delete(record.id); return next })
    }
  }, [message, enterExecuteView, triggerTasksRefresh, startingIds])

  const handleClose = useCallback((record: InspectionTask) => {
    const isCancelling = record.status === '执行中'
    modal.confirm({
      title: isCancelling ? '取消巡检' : '关闭任务',
      content: isCancelling
        ? '任务正在执行中，关闭后巡检结果将不会保存。确定取消吗？'
        : '确定要关闭此巡检任务吗？',
      okText: isCancelling ? '确认取消' : '确认关闭',
      cancelText: '返回',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await closeInspectionTask(record.id)
        if (!result.success) {
          message.error(result.error)
          return
        }
        message.success(isCancelling ? '任务已取消' : '任务已关闭')
        loadTasks()
      },
    })
  }, [modal, message, loadTasks])

  const columns: ColumnsType<InspectionTask> = [
    {
      title: '任务编号', dataIndex: 'task_no', key: 'task_no', width: 180,
      sorter: (a, b) => a.task_no.localeCompare(b.task_no),
      defaultSortOrder: 'descend',
      render: (no: string) => (
        <span style={{ fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, color: '#5d5b54', letterSpacing: -0.2 }}>
          {no}
        </span>
      ),
    },
    {
      title: '类型', dataIndex: 'plan_type', key: 'plan_type', width: 90,
      render: (t: string) => {
        const cmap: Record<string, string> = { '线路巡检': '#5645d4', '设备巡检': '#dd5b00' }
        return <span style={{ fontSize: 13, fontWeight: 500, color: cmap[t] || '#5d5b54' }}>{t}</span>
      },
    },
    {
      title: '设备', key: 'target', width: 170, ellipsis: true,
      render: (_: unknown, r: InspectionTask) => {
        if (r.route_name) return <span style={{ fontSize: 13 }}>{r.route_name}</span>
        if (r.equipment_name) return <span style={{ fontSize: 13 }}>{r.equipment_name}</span>
        if (r.equipment_ids && r.equipment_ids.length > 0) {
          return <span style={{ fontSize: 12, color: '#5d5b54' }}>{r.equipment_ids.length} 台设备</span>
        }
        return <span style={{ color: '#bbb8b1' }}>—</span>
      },
    },
    {
      title: '计划日期', dataIndex: 'planned_date', key: 'planned_date', width: 105,
      render: (d: string) => <span style={{ fontSize: 13, color: '#5d5b54' }}>{d}</span>,
    },
    {
      title: '巡检人', dataIndex: 'assignee_name', key: 'assignee_name', width: 90,
      render: (n: string | undefined) => n || <span style={{ color: '#bbb8b1' }}>—</span>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 85,
      render: (s: string) => {
        const m = STATUS_MAP[s] || { color: '#787671', bg: '#f0eeec', label: s }
        return <span style={statusPill(m.color, m.bg)}>{m.label}</span>
      },
    },
    {
      title: '结果', dataIndex: 'overall_result', key: 'overall_result', width: 75,
      render: (r: string | null) => {
        if (!r) return <span style={{ color: '#bbb8b1' }}>—</span>
        return <span style={r === '正常' ? pillSuccess : pillError}>{r}</span>
      },
    },
    {
      title: '操作', key: 'action', width: 140, fixed: 'end' as const,
      render: (_: unknown, record: InspectionTask) => {
        if (!hasPermission('equipment:inspection:update')) return null
        return (
        <Space size={12}>
          {(record.status === '待执行' || record.status === '执行中') && (
            startingIds.has(record.id) ? (
              <span style={{ ...linkMuted, cursor: 'not-allowed' }}>
                <PlayCircleOutlined />处理中...
              </span>
            ) : (
              <span role="button" onClick={() => handleStart(record)} style={record.status === '待执行' ? linkSuccess : linkWarning}>
                <PlayCircleOutlined />
                {record.status === '待执行' ? '开始' : '继续'}
              </span>
            )
          )}
          {record.status === '执行中' && (
            <span role="button" onClick={() => handleClose(record)} style={linkMuted}>
              <CloseCircleOutlined />关闭
            </span>
          )}
          {record.status === '已完成' && (
            <span role="button" onClick={() => handleClose(record)} style={linkMuted}>
              <CloseCircleOutlined />归档
            </span>
          )}
        </Space>
        )
      },
    },
  ]

  return (
    <div>
      {/* 筛选 + 操作栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20,
      }}>
        {/* 状态筛选 — DESIGN.md pill-tab */}
        <div style={{ display: 'flex', gap: 8 }}>
          {ALL_STATUSES.map(s => {
            const active = tasksStatusFilter === s
            return (
              <button
                key={s}
                onClick={() => setTasksStatusFilter(tasksStatusFilter === s ? '' : s)}
                style={pillTab(active)}
              >
                {s}
              </button>
            )
          })}
        </div>

        {hasPermission('equipment:inspection:create') && (
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openTaskDrawer}
          style={{
            borderRadius: 8, height: 36,
            background: '#5645d4', borderColor: '#5645d4',
            fontWeight: 600, fontSize: 13,
            boxShadow: 'none',
          }}
        >
          创建任务
        </Button>
        )}
      </div>

      <Table
        columns={columns}
        dataSource={tasks}
        rowKey="id"
        size="small"
        loading={tasksLoading}
        scroll={{ x: 'max-content' }}
        rowClassName={() => 'inspection-task-row'}
        pagination={{
          current: tasksPage, pageSize: tasksPageSize, total: tasksTotal,
          showSizeChanger: true, showQuickJumper: true,
          showTotal: t => <span style={{ color: '#a4a097', fontSize: 13 }}>共 {t} 条</span>,
          onChange: (p, s) => { setTasksPage(p); setTasksPageSize(s) },
        }}
        style={{ borderRadius: 0 }}
      />
    </div>
  )
}
