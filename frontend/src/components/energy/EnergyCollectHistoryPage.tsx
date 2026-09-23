'use client'

import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, DatePicker, Empty, Input, InputNumber, Spin, Table } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { Line } from '@ant-design/charts'
import dayjs, { type Dayjs } from 'dayjs'
import type { TableColumnsType } from 'antd'
import { getEnabledTypeConfigs, getEnergyDataHistory, updateEnergyDataValue } from '@/actions/energy'
import type { EnergyDataHistory } from '@/types/energy'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { EnergyPageFrame } from './EnergyPageFrame'
import styles from './EnergyCollection.module.css'

const { RangePicker } = DatePicker
const PRESETS = {
  昨天: { range: () => [dayjs().subtract(1, 'day').startOf('day'), dayjs().subtract(1, 'day').endOf('day')] as [Dayjs, Dayjs], granularity: 'hourly' as const },
  '7天': { range: () => [dayjs().subtract(6, 'day').startOf('day'), dayjs().endOf('day')] as [Dayjs, Dayjs], granularity: 'daily' as const },
  '30天': { range: () => [dayjs().subtract(29, 'day').startOf('day'), dayjs().endOf('day')] as [Dayjs, Dayjs], granularity: 'daily' as const },
}

type DeptRow = { key: string; workshop: string; total: number; deviceCount: number; deviceMap: Map<string, EnergyDataHistory[]> }

export default function EnergyCollectHistoryPage() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [activeType, setActiveType] = useState('')
  const [range, setRange] = useState<[Dayjs, Dayjs]>(PRESETS['7天'].range())
  const [activePreset, setActivePreset] = useState<keyof typeof PRESETS | ''>('7天')
  const [search, setSearch] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [editing, setEditing] = useState(false)
  const [editingValues, setEditingValues] = useState<Record<string, number | undefined>>({})
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set())
  const queryClient = useQueryClient()
  const metadataQuery = useQuery({ queryKey: ['energy', 'type-configs', 'enabled'], queryFn: () => getEnabledTypeConfigs() })
  const typeMetadata = Array.isArray(metadataQuery.data) ? metadataQuery.data : []
  const selectedType = activeType || typeMetadata[0]?.type_code || ''

  const granularity = activePreset ? PRESETS[activePreset].granularity : 'daily'
  const historyQueryKey = useMemo(() => ['energy', 'collect-history', selectedType, granularity, range[0].valueOf(), range[1].valueOf()], [selectedType, granularity, range])
  const historyQuery = useQuery({
    queryKey: historyQueryKey,
    enabled: Boolean(selectedType),
    queryFn: async () => {
      const base = { energy_type: selectedType, granularity, start_time: range[0].startOf('day').toISOString(), end_time: range[1].endOf('day').toISOString(), page_size: 100 }
      const items: EnergyDataHistory[] = []
      let page = 1
      let total = 0
      do {
        const result = await getEnergyDataHistory({ ...base, page })
        items.push(...result.items)
        total = result.total
        page += 1
      } while (items.length < total && page <= 500)
      // 用实际取到的行数做总数：聚合口径与「记录数」指标同源，不会出现两个互相矛盾的数字。
      // ponytail: 500 页（5 万行）只是防 total 异常导致死循环的上限，接口若提供汇总值可整段替换。
      return { items, total: items.length }
    },
  })
  const allRows = useMemo(() => historyQuery.data?.items ?? [], [historyQuery.data?.items])
  const totalCount = historyQuery.data?.total ?? 0
  const loading = historyQuery.isLoading || historyQuery.isFetching
  // 失败时必须说出来：否则请求出错和「这段时间没有数据」在界面上一模一样。
  const historyError = historyQuery.isError ? (historyQuery.error instanceof Error ? historyQuery.error.message : '请稍后重试') : null
  const metadataError = metadataQuery.isError ? '能源类型加载失败' : null

  const deptRows = useMemo<DeptRow[]>(() => {
    const grouped = new Map<string, Map<string, EnergyDataHistory[]>>()
    allRows.forEach((row) => {
      const workshop = row.workshop || '未知部门'
      const device = row.device_name || row.platform_device_code || '未知数据源'
      if (!grouped.has(workshop)) grouped.set(workshop, new Map())
      const devices = grouped.get(workshop)!
      if (!devices.has(device)) devices.set(device, [])
      devices.get(device)!.push(row)
    })
    return [...grouped].map(([workshop, deviceMap]) => ({ key: workshop, workshop, deviceMap, deviceCount: deviceMap.size, total: [...deviceMap.values()].flat().reduce((sum, row) => sum + row.value, 0) })).sort((a, b) => b.total - a.total)
  }, [allRows])
  const filteredDepts = useMemo(() => {
    const query = search.trim().toLowerCase()
    return query ? deptRows.filter((row) => row.workshop.toLowerCase().includes(query)) : deptRows
  }, [deptRows, search])
  const activeMeta = typeMetadata.find((meta) => meta.type_code === selectedType)
  const unit = allRows[0]?.unit || activeMeta?.unit || ''
  const totalDevices = filteredDepts.reduce((sum, row) => sum + row.deviceCount, 0)
  const totalValue = filteredDepts.reduce((sum, row) => sum + row.total, 0)
  const isHourly = granularity === 'hourly'
  const canEditHistory = hasPermission('energy:overview:delete')

  const handleSaveValue = useCallback(async (id: string) => {
    const value = editingValues[id]
    if (value === undefined || !Number.isFinite(value)) return
    setSavingIds((prev) => new Set(prev).add(id))
    try {
      await updateEnergyDataValue(id, value)
      // 就地更新缓存里的那一行：多页 refetch 落地前输入框不会回退到旧值，也不必重新拉全部页。
      queryClient.setQueryData<{ items: EnergyDataHistory[]; total: number }>(historyQueryKey, (prev) => prev ? { ...prev, items: prev.items.map((row) => (row.id === id ? { ...row, value } : row)) } : prev)
      setEditingValues((prev) => { const next = { ...prev }; delete next[id]; return next })
      message.success('数据已保存')
    } catch { message.error('保存失败，请稍后重试') } finally { setSavingIds((prev) => { const next = new Set(prev); next.delete(id); return next }) }
  }, [editingValues, historyQueryKey, message, queryClient])

  const columns: TableColumnsType<DeptRow> = [
    { title: '部门', dataIndex: 'workshop', key: 'workshop', sorter: (a, b) => a.workshop.localeCompare(b.workshop, 'zh-CN'), render: (value: string) => <strong>{value}</strong> },
    { title: '数据源', dataIndex: 'deviceCount', key: 'deviceCount', width: 120, align: 'center', sorter: (a, b) => a.deviceCount - b.deviceCount },
    { title: '周期合计', dataIndex: 'total', key: 'total', width: 180, align: 'right', defaultSortOrder: 'descend', sorter: (a, b) => a.total - b.total, render: (value: number) => <span className={styles.numeric}>{value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} <span className={styles.muted}>{unit}</span></span> },
  ]

  return (
    <EnergyPageFrame>
      <div className={styles.stack}>
        <PageHeading title="采集历史" subtitle={activeMeta ? `查看 ${activeMeta.display_name} 的分部门采集趋势与数据明细。` : '查看分部门采集趋势与数据明细。'} />
        <section className={styles.panel} aria-label="能源类型和时间筛选">
          <div className={styles.sectionHeader}><div><h2>筛选范围</h2><p className={styles.description}>选择能源类型和时间范围，展开部门查看数据源趋势。</p></div><span className={styles.status}>{isHourly ? '逐小时' : '日汇总'}</span></div>
          <div className={styles.panelBody}>
            <div className={styles.typeList} role="group" aria-label="能源类型">
              {typeMetadata.map((meta) => <button key={meta.type_code} type="button" className={styles.typeButton} aria-pressed={selectedType === meta.type_code} onClick={() => { setActiveType(meta.type_code); setExpandedKeys([]); setSearch('') }}><span className={styles.typeDot} style={{ color: meta.color || '#5645d4' }} />{meta.display_name}</button>)}
              {!typeMetadata.length && <span className={styles.muted}>{metadataError ?? '暂无可用能源类型'}</span>}
            </div>
            <div className={styles.filterGrid} style={{ padding: '20px 0 0' }}>
              <div className={styles.field}><span className={styles.fieldLabel}>日期范围</span><div className={styles.inlineField}>{Object.keys(PRESETS).map((label) => <Button key={label} size="small" type={activePreset === label ? 'primary' : 'default'} onClick={() => { const preset = PRESETS[label as keyof typeof PRESETS]; setRange(preset.range()); setActivePreset(label as keyof typeof PRESETS); setExpandedKeys([]) }}>{label}</Button>)}<RangePicker value={range} allowClear={false} onChange={(dates) => { if (dates?.[0] && dates[1]) { setRange([dates[0], dates[1]]); setActivePreset(''); setExpandedKeys([]) } }} /></div></div>
              <div className={styles.field}><span className={styles.fieldLabel}>部门搜索</span><Input className={styles.search} prefix={<SearchOutlined />} placeholder="搜索部门名称" allowClear value={search} onChange={(event) => { setSearch(event.target.value); setExpandedKeys([]) }} /></div>
              <Button disabled={!canEditHistory} aria-pressed={editing} type={editing ? 'primary' : 'default'} onClick={() => { setEditing((value) => !value); setEditingValues({}) }}>{editing ? '退出编辑' : '编辑历史数据'}</Button>
            </div>
          </div>
        </section>
        <div className={styles.metrics} aria-label="采集历史统计">
          <div className={styles.metric}><span className={styles.metricLabel}>部门</span><strong className={styles.metricValue}>{filteredDepts.length}</strong><span className={styles.metricHint}>{search ? '当前筛选' : '当前范围'}</span></div>
          <div className={styles.metric}><span className={styles.metricLabel}>数据源</span><strong className={styles.metricValue}>{totalDevices}</strong><span className={styles.metricHint}>参与统计的数据源</span></div>
          <div className={styles.metric}><span className={styles.metricLabel}>记录数</span><strong className={styles.metricValue}>{totalCount.toLocaleString('zh-CN')}</strong><span className={styles.metricHint}>已加载记录数</span></div>
          <div className={styles.metric}><span className={styles.metricLabel}>周期合计</span><strong className={styles.metricValue}>{totalValue.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}<small>{unit}</small></strong><span className={styles.metricHint}>当前部门筛选口径</span></div>
        </div>
        <section className={styles.panel} aria-label="采集历史表格">
          <div className={styles.sectionHeader}><div><h2>部门明细</h2><p className={styles.description}>{filteredDepts.length ? '按合计从高到低排列，点击行展开数据源。' : '当前筛选没有匹配的部门。'}</p></div>{expandedKeys.length > 0 && <Button type="link" onClick={() => setExpandedKeys([])}>收起全部</Button>}</div>
          <Spin spinning={loading} description="正在加载采集历史…">
            {filteredDepts.length ? <Table<DeptRow> className={styles.table} rowKey="key" columns={columns} dataSource={filteredDepts} pagination={false} scroll={{ x: 620 }} expandable={{ expandedRowKeys: expandedKeys, onExpandedRowsChange: (keys) => setExpandedKeys(keys as string[]), expandedRowRender: (dept) => <DeviceDetails dept={dept} unit={unit} chartColor={activeMeta?.color || '#5645d4'} isHourly={isHourly} editing={editing} editingValues={editingValues} savingIds={savingIds} onValueChange={(id, value) => setEditingValues((prev) => ({ ...prev, [id]: value }))} onSave={handleSaveValue} onCollapse={() => setExpandedKeys((prev) => prev.filter((key) => key !== dept.key))} /> }} locale={{ emptyText: <Empty className={styles.empty} description="暂无采集数据" /> }} /> : <Empty className={styles.empty} description={loading ? '正在加载…' : historyError ? `加载失败：${historyError}` : allRows.length ? '未找到匹配的部门' : '当前时间范围内无采集数据'}>{historyError && <Button onClick={() => void historyQuery.refetch()}>重新加载</Button>}</Empty>}
          </Spin>
        </section>
      </div>
    </EnergyPageFrame>
  )
}

function DeviceDetails({ dept, unit, chartColor, isHourly, editing, editingValues, savingIds, onValueChange, onSave, onCollapse }: { dept: DeptRow; unit: string; chartColor: string; isHourly: boolean; editing: boolean; editingValues: Record<string, number | undefined>; savingIds: Set<string>; onValueChange: (id: string, value: number) => void; onSave: (id: string) => void; onCollapse: () => void }) {
  const devices = [...dept.deviceMap.entries()].map(([name, rows]) => ({ name, rows: [...rows].sort((a, b) => a.timestamp.localeCompare(b.timestamp)), total: rows.reduce((sum, row) => sum + row.value, 0) })).sort((a, b) => b.total - a.total)
  return <div className={styles.deviceList}>{devices.map((device) => <article className={styles.device} key={device.name}><div className={styles.deviceHeader}><div><div className={styles.deviceName}>{device.name}</div><span className={styles.muted}>{device.rows.length} 条记录</span></div><div className={styles.deviceTotal}>{device.total.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} {unit}</div></div>{device.rows.length > 1 ? <div className={styles.chart}><Line data={device.rows.map((row) => ({ date: dayjs(row.timestamp).format(isHourly ? 'MM-DD HH:00' : 'MM-DD'), value: row.value }))} xField="date" yField="value" smooth height={190} color={chartColor} point={{ size: 3 }} tooltip={{ items: [{ channel: 'y', valueFormatter: (value: number) => `${value.toLocaleString('zh-CN')} ${unit}` }] }} /></div> : <div className={styles.singlePoint}>{device.rows.length ? `${dayjs(device.rows[0].timestamp).format(isHourly ? 'MM-DD HH:00' : 'MM-DD')} · ${device.rows[0].value.toLocaleString('zh-CN')} ${unit}` : '暂无数据'}</div>}<div className={styles.records}>{device.rows.map((row) => { const canEdit = editing && dayjs(row.timestamp).isBefore(dayjs().startOf('day')); const value = editingValues[row.id] ?? row.value; return <div className={styles.record} key={row.id}><span className={styles.muted}>{dayjs(row.timestamp).format(isHourly ? 'MM-DD HH:00' : 'YYYY-MM-DD')}</span><span className={styles.recordValue}>{canEdit ? <><InputNumber className={styles.valueInput} size="small" value={value} onChange={(next) => { if (next !== null) onValueChange(row.id, next) }} onPressEnter={() => onSave(row.id)} /><Button type="link" size="small" loading={savingIds.has(row.id)} onClick={() => onSave(row.id)}>保存</Button></> : <>{row.value.toLocaleString('zh-CN')} {unit}</>}</span></div> })}</div></article>)}<div className={styles.collapseFooter}><Button type="link" onClick={onCollapse}>收起部门</Button></div></div>
}
