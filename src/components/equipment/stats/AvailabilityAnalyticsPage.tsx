'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { App, DatePicker, Progress, Spin, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { fetchAvailabilityClient } from '@/lib/api/equipment-client'
import type { AvailabilityItem, AvailabilityResponse, EquipmentStatus, RunningStatus } from '@/types/equipment'
import { EQUIP_STATUS_PILL_COLORS, RUNNING_STATUS_PILL_COLORS, monoFont, statusPill } from '@/components/equipment/shared/shared-styles'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── DESIGN.md tokens ──
const T = {
  primary: '#5645d4',
  canvas: '#ffffff',
  ink: '#1a1a1a',
  slate: '#5d5b54',
  stone: '#a4a097',
  hairline: '#e5e3df',
}

function ratePercent(rate: number | null): string {
  return rate == null ? '-' : `${(rate * 100).toFixed(1)}%`
}

export function AvailabilityAnalyticsPage() {
  const { message } = App.useApp()
  const [data, setData] = useState<AvailabilityResponse | null>(null)
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 30)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  const loadData = useCallback(async () => {
    if (!dateRange) return
    setLoading(true)
    try {
      setData(await fetchAvailabilityClient(dateRange[0], dateRange[1]))
    } catch {
      message.error('开动率数据加载失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [dateRange, message])

  useEffect(() => { loadData() }, [loadData])

  const items = useMemo(
    () => [...(data?.items ?? [])].sort(
      (a, b) => (b.availability_rate ?? -1) - (a.availability_rate ?? -1)
    ),
    [data]
  )

  // ── 统计卡数据 ──
  const stats = useMemo(() => {
    const rates = items.map(i => i.availability_rate).filter((r): r is number => r != null)
    return {
      overall: data?.overall_rate ?? null,
      count: items.length,
      average: rates.length > 0 ? rates.reduce((a, b) => a + b, 0) / rates.length : null,
      lowCount: rates.filter(r => r < 0.5).length,
    }
  }, [data, items])

  // ── 明细表列 ──
  const columns: ColumnsType<AvailabilityItem> = [
    {
      title: '设备编号', dataIndex: 'equipment_no', key: 'equipment_no', width: 140,
      render: (no: string) => <span style={monoFont}>{no}</span>,
    },
    { title: '设备名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true },
    {
      title: '当前状态', dataIndex: 'current_status', key: 'current_status', width: 90,
      render: (s: EquipmentStatus) => (
        <span style={statusPill(EQUIP_STATUS_PILL_COLORS[s]?.color || '#787671', EQUIP_STATUS_PILL_COLORS[s]?.bg || '#f0eeec')}>{s}</span>
      ),
    },
    {
      title: '运行状态', dataIndex: 'current_running_status', key: 'current_running_status', width: 90,
      render: (s: RunningStatus) => (
        <span style={statusPill(RUNNING_STATUS_PILL_COLORS[s]?.color || '#787671', RUNNING_STATUS_PILL_COLORS[s]?.bg || '#f0eeec')}>{s}</span>
      ),
    },
    {
      title: '开机时长(h)', dataIndex: 'available_hours', key: 'available_hours', width: 110,
      sorter: (a, b) => a.available_hours - b.available_hours,
      render: (v: number) => v.toFixed(1),
    },
    {
      title: '统计时长(h)', dataIndex: 'total_hours', key: 'total_hours', width: 110,
      sorter: (a, b) => a.total_hours - b.total_hours,
      render: (v: number) => v.toFixed(1),
    },
    {
      title: '时间开动率', dataIndex: 'availability_rate', key: 'availability_rate', width: 220,
      sorter: (a, b) => (a.availability_rate ?? -1) - (b.availability_rate ?? -1),
      defaultSortOrder: 'descend',
      render: (rate: number | null) =>
        rate == null ? '-' : (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 600, width: 52 }}>{ratePercent(rate)}</span>
            <Progress
              percent={Math.round(rate * 100)} showInfo={false} size="small"
              style={{ width: 100 }}
              strokeColor={rate < 0.5 ? '#e03131' : T.primary}
            />
          </span>
        ),
    },
  ]

  const statCards: { label: string; value: string; color?: string }[] = [
    { label: '整体开动率', value: ratePercent(stats.overall), color: T.primary },
    { label: '统计设备数', value: String(stats.count) },
    { label: '平均开动率', value: ratePercent(stats.average) },
    { label: '低开动率设备(<50%)', value: String(stats.lowCount), color: stats.lowCount > 0 ? '#e03131' : undefined },
  ]

  return (
    <div style={{ background: '#f6f5f4', minHeight: '100vh' }}>
      {/* ── hero-band-dark header ── */}
      <div style={{ background: '#0a1530', padding: '20px 32px', borderBottom: '3px solid #5645d4' }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>
          Equipment Analytics
        </div>
        <div style={{ fontSize: 22, fontWeight: 600, color: '#ffffff' }}>
          设备分析
        </div>
      </div>

      <div style={{ padding: '32px' }}>
        {/* ── 工具条 ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          <Text style={{ fontSize: 13, color: T.slate }}>统计范围</Text>
          <RangePicker
            value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
            onChange={(_, ds) => { if (ds[0] && ds[1]) setDateRange([ds[0], ds[1]]) }}
            allowClear={false}
          />
        </div>

        <Spin spinning={loading}>
          {/* ── 统计卡 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
            {statCards.map(card => (
              <div key={card.label} style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24 }}>
                <div style={{ fontSize: 13, color: T.slate, marginBottom: 8 }}>{card.label}</div>
                <div style={{ fontSize: 28, fontWeight: 600, color: card.color || T.ink }}>{card.value}</div>
              </div>
            ))}
          </div>

          {/* ── 明细表 ── */}
          <div style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24 }}>
            <div style={{ fontSize: 22, fontWeight: 600, color: T.ink, marginBottom: 20 }}>设备开动率明细</div>
            <Table
              columns={columns}
              dataSource={items}
              rowKey="equipment_id"
              size="small"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        </Spin>
      </div>
    </div>
  )
}
