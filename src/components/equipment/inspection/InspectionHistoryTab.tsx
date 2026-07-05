'use client'

import { useEffect, useCallback, useMemo, useState } from 'react'
import { App, Button, Table, Space, DatePicker, Input } from 'antd'
import { EyeOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useInspectionStore } from '@/stores/inspection'
import { fetchInspectionHistory } from '@/lib/api/inspection'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { statusPill, pillSuccess, pillError, pillTab, actionLink, linkPrimary } from '@/components/equipment/shared/shared-styles'
import type { InspectionTask, InspectionOverallResult } from '@/types/inspection'
import type { Personnel } from '@/types/equipment'

const { RangePicker } = DatePicker

interface Props {
  equipments: { id: string; name: string; equipment_no: string }[]
}

export function InspectionHistoryTab({ equipments }: Props) {
  const { message } = App.useApp()
  const {
    historyItems, historyTotal, historyPage, historyPageSize, historyLoading,
    historyDateFrom, historyDateTo, historyEquipmentId, historyResult,
    setHistoryItems, setHistoryTotal, setHistoryLoading, setHistoryPage, setHistoryPageSize,
    setHistoryDateFrom, setHistoryDateTo, setHistoryEquipmentId, setHistoryResult,
    openHistoryDetail,
  } = useInspectionStore()

  const load = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const res = await fetchInspectionHistory({
        date_from: historyDateFrom || undefined,
        date_to: historyDateTo || undefined,
        equipment_id: historyEquipmentId || undefined,
        result: (historyResult as InspectionOverallResult) || undefined,
        page: historyPage, page_size: historyPageSize,
      })
      setHistoryItems(res.items)
      setHistoryTotal(res.total)
    } catch (err: unknown) {
      message.error((err as Error).message || '加载失败')
    } finally { setHistoryLoading(false) }
  }, [historyDateFrom, historyDateTo, historyEquipmentId, historyResult, historyPage, historyPageSize, setHistoryItems, setHistoryTotal, setHistoryLoading, message])

  const [personnel, setPersonnel] = useState<Personnel[]>([])

  useEffect(() => { load() }, [load])

  // 加载人员配置列表作为巡检人过滤选项（与 InspectionTaskDrawer 保持一致）
  useEffect(() => {
    fetchPersonnelList({}).then(r => setPersonnel(r.items.filter(p => p.is_active))).catch(() => {})
  }, [])

  const typeFilters = useMemo(() => [
    { text: '线路巡检', value: '线路巡检' },
    { text: '设备巡检', value: '设备巡检' },
  ], [])

  const assigneeFilters = useMemo(() => {
    const seen = new Set<string>()
    personnel.forEach(p => { if (p.name) seen.add(p.name) })
    return Array.from(seen).sort().map(name => ({ text: name, value: name }))
  }, [personnel])

  const columns: ColumnsType<InspectionTask> = [
    {
      title: '任务编号', dataIndex: 'task_no', width: 175,
      sorter: (a, b) => a.task_no.localeCompare(b.task_no),
      defaultSortOrder: 'descend',
      render: (n: string) => <span style={{ fontFamily: '"SF Mono", monospace', fontSize: 12, color: '#5d5b54' }}>{n}</span>,
    },
    {
      title: '类型', dataIndex: 'plan_type', width: 85,
      filters: typeFilters,
      onFilter: (value, record) => record.plan_type === value,
    },
    {
      title: '路线 / 设备', key: 'target', width: 170, ellipsis: true,
      render: (_: unknown, r: InspectionTask) => r.route_name || r.equipment_name || <span style={{ color: '#bbb8b1' }}>—</span>,
    },
    {
      title: '计划日期', dataIndex: 'planned_date', width: 105,
      render: (d: string) => <span style={{ fontSize: 13, color: '#5d5b54' }}>{d}</span>,
    },
    { title: '巡检人', dataIndex: 'assignee_name', width: 85, filters: assigneeFilters, onFilter: (value, record) => record.assignee_name === value, render: (n: string | undefined) => n || <span style={{ color: '#bbb8b1' }}>—</span> },
    {
      title: '完成时间', dataIndex: 'completed_at', width: 155,
      render: (t: string | null) => t ? dayjs(t).format('MM-DD HH:mm') : <span style={{ color: '#bbb8b1' }}>—</span>,
    },
    {
      title: '结果', dataIndex: 'overall_result', width: 75,
      render: (r: string | null) => {
        if (!r) return <span style={{ color: '#bbb8b1' }}>—</span>
        return <span style={r === '正常' ? pillSuccess : pillError}>{r}</span>
      },
    },
    {
      title: '', key: 'action', width: 60, fixed: 'end' as const,
      render: (_: unknown, r: InspectionTask) => (
        <span role="button" onClick={() => openHistoryDetail(r.id)} style={linkPrimary}>
          <EyeOutlined />详情
        </span>
      ),
    },
  ]

  return (
    <div>
      {/* 筛选栏 */}
      <div style={{
        display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center',
        marginBottom: 20, padding: '14px 18px',
        background: '#fafaf9', borderRadius: 10, border: '1px solid #ede9e4',
      }}>
        <RangePicker
          size="small"
          placeholder={['开始日期', '结束日期']}
          value={[historyDateFrom ? dayjs(historyDateFrom) : null, historyDateTo ? dayjs(historyDateTo) : null]}
          onChange={(dates) => {
            setHistoryDateFrom(dates?.[0] ? dates[0].format('YYYY-MM-DD') : '')
            setHistoryDateTo(dates?.[1] ? dates[1].format('YYYY-MM-DD') : '')
          }}
          style={{ borderRadius: 6 }}
        />
        <Input
          size="small" placeholder="搜索设备名称或编号" allowClear
          style={{ width: 200, borderRadius: 6 }}
          prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          onChange={(e) => {
            const v = e.target.value
            if (!v) { setHistoryEquipmentId(null); return }
            const eq = equipments.find(x => x.name.includes(v) || x.equipment_no.includes(v))
            setHistoryEquipmentId(eq?.id || null)
          }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          {(['正常', '异常'] as InspectionOverallResult[]).map(r => {
            const active = historyResult === r
            return (
              <button key={r}
                onClick={() => setHistoryResult(active ? null : r)}
                style={pillTab(active)}>
                {r}
              </button>
            )
          })}
        </div>
      </div>

      <Table
        key={`history-${personnel.length}`}
        columns={columns} dataSource={historyItems} rowKey="id"
        size="small" loading={historyLoading} scroll={{ x: 'max-content' }}
        pagination={{
          current: historyPage, pageSize: historyPageSize, total: historyTotal,
          showSizeChanger: true, showQuickJumper: true,
          showTotal: t => <span style={{ color: '#a4a097', fontSize: 13 }}>共 {t} 条</span>,
          onChange: (p, s) => { setHistoryPage(p); setHistoryPageSize(s) },
        }}
        style={{ borderRadius: 0 }}
      />
    </div>
  )
}
