'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Input, Modal, Select, Space, Tree } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { TreeDataNode } from 'antd'
import dayjs from 'dayjs'
import { fetchGasDetectorDateStats } from '@/lib/api/meter'
import { exportGasDetectorsExcel } from '@/actions/meter'
import type { DateStatsResponse, GasDetectorFilter } from '@/types/meter'

interface Props {
  open: boolean
  initialField: 'calibration_date' | 'next_calibration_date'
  columnFilters: Record<string, string | undefined>
  keyword: string
  onClose: () => void
  onConfirm: (params: { field: string; after?: string; before?: string }) => void
}

type DateNodeKey = `year:${number}` | `month:${number}-${number}` | `day:${string}`

function isDayKey(key: string): boolean {
  return key.startsWith('day:')
}

function parseDayKey(key: string): string {
  return key.slice(4)
}

function buildTreeData(
  stats: DateStatsResponse | null,
  searchText: string,
  sortMode: 'name_asc' | 'count_desc',
): TreeDataNode[] {
  if (!stats || !stats.years) return []
  const lowerSearch = searchText.toLowerCase()

  return stats.years
    .map((y) => {
      const months = y.months
        .map((m) => {
          let days = m.days.map((d) => ({
            title: `${m.month}月${d.day}日 (${d.count})`,
            key: `day:${y.year}-${String(m.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}` as DateNodeKey,
            isLeaf: true,
          }))

          if (sortMode === 'count_desc') {
            days = days.sort((a, b) => {
              const countA = parseInt(a.title.match(/\((\d+)\)$/)?.[1] || '0')
              const countB = parseInt(b.title.match(/\((\d+)\)$/)?.[1] || '0')
              return countB - countA
            })
          }

          if (lowerSearch) {
            const monthLabel = `${m.month}月`
            const monthMatch = monthLabel.includes(lowerSearch) || String(y.year).includes(lowerSearch)
            days = days.filter((d) => {
              const dayStr = dayjs(parseDayKey(d.key as string)).format('M月D日')
              return monthMatch || dayStr.includes(lowerSearch) || String(y.year).includes(lowerSearch)
            })
          }

          if (days.length === 0 && lowerSearch) return null

          return {
            title: `${m.month}月 (${m.count})`,
            key: `month:${y.year}-${m.month}` as DateNodeKey,
            children: days,
          }
        })
        .filter(Boolean) as TreeDataNode[]

      if (months.length === 0 && lowerSearch) return null

      return {
        title: `${y.year}年 (${y.count})`,
        key: `year:${y.year}` as DateNodeKey,
        children: months,
      }
    })
    .filter(Boolean) as TreeDataNode[]
}

export function GasDetectorDateFilterModal({ open, initialField, columnFilters, keyword, onClose, onConfirm }: Props) {
  const { message } = App.useApp()
  const [dateField, setDateField] = useState<'calibration_date' | 'next_calibration_date'>(initialField)
  const [stats, setStats] = useState<DateStatsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([])
  const [searchText, setSearchText] = useState('')
  const [sortMode, setSortMode] = useState<'name_asc' | 'count_desc'>('count_desc')
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (!open) return
    setDateField(initialField)
    setCheckedKeys([])
    setSearchText('')
    setLoading(true)
    const filters: GasDetectorFilter = {}
    if (keyword) filters.keyword = keyword
    for (const [field, value] of Object.entries(columnFilters)) {
      if (value) (filters as Record<string, unknown>)[field] = value
    }
    fetchGasDetectorDateStats(initialField, filters)
      .then((res) => setStats(res))
      .catch(() => message.error('获取日期统计失败'))
      .finally(() => setLoading(false))
  }, [open, initialField, columnFilters, keyword, message])

  const handleFieldChange = useCallback(
    (val: 'calibration_date' | 'next_calibration_date') => {
      setDateField(val)
      setCheckedKeys([])
      setLoading(true)
      const filters: GasDetectorFilter = {}
      if (keyword) filters.keyword = keyword
      for (const [field, value] of Object.entries(columnFilters)) {
        if (value) (filters as Record<string, unknown>)[field] = value
      }
      fetchGasDetectorDateStats(val, filters)
        .then((res) => setStats(res))
        .catch(() => message.error('获取日期统计失败'))
        .finally(() => setLoading(false))
    },
    [columnFilters, keyword, message],
  )

  const treeData = useMemo(
    () => buildTreeData(stats, searchText, sortMode),
    [stats, searchText, sortMode],
  )

  const allLeafKeys = useMemo(() => {
    const keys: React.Key[] = []
    if (!stats?.years) return keys
    for (const y of stats.years) {
      for (const m of y.months) {
        for (const d of m.days) {
          keys.push(`day:${y.year}-${String(m.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}`)
        }
      }
    }
    return keys
  }, [stats])

  const totalCount = stats?.years?.reduce((sum, y) => sum + y.count, 0) || 0

  const handleCheck = useCallback((keys: React.Key[] | { checked: React.Key[]; halfChecked: React.Key[] }) => {
    if (Array.isArray(keys)) {
      setCheckedKeys(keys)
    } else {
      setCheckedKeys(keys.checked)
    }
  }, [])

  const handleSelectAll = useCallback(() => {
    setCheckedKeys(allLeafKeys)
  }, [allLeafKeys])

  const handleInvert = useCallback(() => {
    const currentSet = new Set(checkedKeys.map(String))
    const newKeys = allLeafKeys.filter((k) => !currentSet.has(String(k)))
    setCheckedKeys(newKeys)
  }, [checkedKeys, allLeafKeys])

  const handleConfirm = useCallback(() => {
    if (checkedKeys.length === 0) {
      message.warning('请至少选择一个日期')
      return
    }
    const dayKeys = checkedKeys.filter((k) => isDayKey(String(k)))
    if (dayKeys.length === 0) {
      message.warning('请至少选择一个日期')
      return
    }
    const dates = dayKeys.map((k) => parseDayKey(String(k))).sort()
    const after = dates[0]
    const before = dates[dates.length - 1]
    onConfirm({ field: dateField, after, before })
  }, [checkedKeys, dateField, onConfirm, message])

  const handleExport = useCallback(async () => {
    const selectedDayKeys = checkedKeys.filter((k) => isDayKey(String(k)))
    let after: string | undefined
    let before: string | undefined
    if (selectedDayKeys.length > 0) {
      const dates = selectedDayKeys.map((k) => parseDayKey(String(k))).sort()
      after = dates[0]
      before = dates[dates.length - 1]
    }

    setExporting(true)
    try {
      const filterParams: GasDetectorFilter = {}
      if (keyword) filterParams.keyword = keyword
      for (const [field, value] of Object.entries(columnFilters)) {
        if (value) (filterParams as Record<string, unknown>)[field] = value
      }
      if (after && dateField === 'calibration_date') {
        filterParams.calibration_date_after = after
        filterParams.calibration_date_before = before
      } else if (after && dateField === 'next_calibration_date') {
        filterParams.next_calibration_after = after
        filterParams.next_calibration_before = before
      }
      const result = await exportGasDetectorsExcel(filterParams)
      const byteChars = atob(result.blob)
      const byteNums = new Array(byteChars.length)
      for (let i = 0; i < byteChars.length; i++) byteNums[i] = byteChars.charCodeAt(i)
      const blob = new Blob([new Uint8Array(byteNums)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = result.filename
      a.click()
      window.URL.revokeObjectURL(url)
      message.success('导出完成')
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }, [checkedKeys, dateField, columnFilters, keyword, message])

  return (
    <Modal
      title="日期筛选"
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <Select
          value={dateField}
          onChange={handleFieldChange}
          style={{ width: '100%', marginBottom: 8 }}
          options={[
            { label: '检定时间', value: 'calibration_date' },
            { label: '下次检定', value: 'next_calibration_date' },
          ]}
        />
        <Space style={{ width: '100%' }}>
          <Input
            placeholder="搜索年月日..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ flex: 1 }}
            allowClear
          />
          <Select
            value={sortMode}
            onChange={setSortMode}
            style={{ width: 120 }}
            options={[
              { label: '名称升序', value: 'name_asc' },
              { label: '计数降序', value: 'count_desc' },
            ]}
          />
        </Space>
      </div>

      <div style={{ maxHeight: 420, overflow: 'auto', marginBottom: 12, border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>加载中...</div>
        ) : treeData.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无数据</div>
        ) : (
          <Tree
            checkable
            checkedKeys={checkedKeys}
            onCheck={handleCheck}
            treeData={treeData}
            defaultExpandAll
            blockNode
          />
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <Space>
          <Button size="small" onClick={handleSelectAll}>全选({totalCount})</Button>
          <Button size="small" onClick={handleInvert}>反选</Button>
        </Space>
        <Space>
          <Button loading={exporting} onClick={handleExport}>导出</Button>
          <Button type="primary" onClick={handleConfirm}>确定</Button>
          <Button onClick={onClose}>取消</Button>
        </Space>
      </div>
    </Modal>
  )
}
