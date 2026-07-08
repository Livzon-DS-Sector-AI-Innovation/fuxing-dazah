'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Table, Tag, Select, Button } from 'antd'
import { WarningOutlined, DownloadOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { CalibrationAlertItem } from '@/types/meter'
import { getCalibrationAlerts, getInstrumentDepartments, getGasDetectorDepartments } from '@/actions/meter'
import dayjs from 'dayjs'

interface Props {
  source?: 'instrument' | 'gas_detector'
}

export function CalibrationAlertPanel({ source }: Props) {
  const { message } = App.useApp()
  const [alerts, setAlerts] = useState<CalibrationAlertItem[]>([])
  const [loading, setLoading] = useState(false)
  const [daysBefore, setDaysBefore] = useState(30)
  const [deptFilter, setDeptFilter] = useState<string | undefined>(undefined)
  const [departments, setDepartments] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)

  const handleExport = async () => {
    setExporting(true)
    try {
      const params = new URLSearchParams()
      params.set('days_before', String(daysBefore))
      if (deptFilter) params.set('department', deptFilter)
      if (source) params.set('source', source)
      const url = `/api/v1/meter/calibration/alerts/export-excel?${params.toString()}`

      const res = await fetch(url, { credentials: 'include' })
      if (!res.ok) throw new Error('导出失败')
      const blob = await res.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = '检定到期提醒.xlsx'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(downloadUrl)
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 加载部门列表（独立于筛选结果，确保下拉选项始终完整）
  useEffect(() => {
    async function loadDepts() {
      try {
        const [instDepts, detDepts] = await Promise.all([
          getInstrumentDepartments(),
          getGasDetectorDepartments(),
        ])
        setDepartments([...new Set([...instDepts, ...detDepts].filter(Boolean))].sort() as string[])
      } catch { /* 非关键，失败不影响主体功能 */ }
    }
    loadDepts()
  }, [])

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getCalibrationAlerts(daysBefore, deptFilter)
      const srcFiltered = source ? data.filter(a => a.source === source) : data
      setAlerts(srcFiltered)
    } catch {
      message.error('获取到期提醒失败')
    } finally {
      setLoading(false)
    }
  }, [daysBefore, deptFilter, message, source])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  // 根据来源动态列标题
  const serialColTitle = source === 'instrument' ? '器具编号' : source === 'gas_detector' ? '产品编号' : '编号'

  const columns: TableColumnsType<CalibrationAlertItem> = [
    {
      title: '来源', dataIndex: 'source', width: 80,
      render: (v: string) => v === 'instrument' ? <Tag>计量器具</Tag> : <Tag color="purple">探测器</Tag>,
    },
    { title: serialColTitle, dataIndex: 'serial_number', width: 120, ellipsis: true },
    { title: '名称', dataIndex: 'instrument_name', width: 180, ellipsis: true },
    { title: '位置', dataIndex: 'location', width: 180, ellipsis: true },
    { title: '部门', dataIndex: 'department', width: 120, ellipsis: true },
    {
      title: '下次检定', dataIndex: 'next_calibration_date', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '距到期', dataIndex: 'days_until_due', width: 90,
      render: (v: number | undefined) => {
        if (v === undefined || v === null) return '-'
        if (v < 0) return <Tag color="red">已过期 {Math.abs(v)} 天</Tag>
        if (v === 0) return <Tag color="orange">今天到期</Tag>
        if (v <= 7) return <Tag color="volcano">{v} 天</Tag>
        return <Tag color="blue">{v} 天</Tag>
      },
    },
  ]

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
          <WarningOutlined style={{ color: '#faad14' }} />
          检定到期提醒
        </h3>
        <Select
          value={daysBefore}
          onChange={setDaysBefore}
          style={{ width: 130 }}
          options={[
            { label: '截止今天', value: 0 },
            { label: '未来 7 天', value: 7 },
            { label: '未来 30 天', value: 30 },
            { label: '未来 90 天', value: 90 },
          ]}
        />
        <Select
          allowClear
          placeholder="全部部门"
          value={deptFilter}
          onChange={setDeptFilter}
          style={{ width: 160 }}
          options={departments.map(d => ({ label: d, value: d }))}
        />
        <Tag color="processing">{alerts.length} 条</Tag>
        <Button
          icon={<DownloadOutlined />}
          loading={exporting}
          onClick={handleExport}
        >
          导出 Excel
        </Button>
      </div>

      <Table
        rowKey={(r: CalibrationAlertItem) => `${r.source}-${r.id}`}
        columns={columns}
        dataSource={alerts}
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        size="small"
        scroll={{ x: 900 }}
      />
    </div>
  )
}
