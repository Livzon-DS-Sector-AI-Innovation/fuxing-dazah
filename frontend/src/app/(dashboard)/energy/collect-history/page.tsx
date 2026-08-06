'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { Table, DatePicker, App, Menu, Empty, Spin, Input, Button, InputNumber } from 'antd'
import type { TableColumnsType } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { getEnergyDataHistory, getEnabledTypeConfigs, updateEnergyDataValue } from '@/actions/energy'
import type { EnergyDataHistory, EnergyTypeMeta } from '@/types/energy'
import dayjs, { type Dayjs } from 'dayjs'
import { Line } from '@ant-design/charts'

const { RangePicker } = DatePicker

/** 预设时间范围：昨天→逐小时，7天/30天→日汇总 */
const PRESETS: Record<string, { range: [Dayjs, Dayjs]; granularity: 'hourly' | 'daily' }> = {
  '昨天': {
    range: [dayjs().subtract(1, 'day').startOf('day'), dayjs().subtract(1, 'day').endOf('day')],
    granularity: 'hourly',
  },
  '7天': {
    range: [dayjs().subtract(6, 'day').startOf('day'), dayjs().endOf('day')],
    granularity: 'daily',
  },
  '30天': {
    range: [dayjs().subtract(29, 'day').startOf('day'), dayjs().endOf('day')],
    granularity: 'daily',
  },
}

interface DeptRow {
  key: string
  workshop: string
  total: number
  deviceCount: number
  deviceMap: Map<string, EnergyDataHistory[]>
}

export default function CollectHistoryPage() {
  const { message } = App.useApp()

  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])
  const [activeType, setActiveType] = useState<string>('')
  const [range, setRange] = useState<[Dayjs, Dayjs]>(PRESETS['7天'].range)
  const [activePreset, setActivePreset] = useState('7天')
  const [allRows, setAllRows] = useState<EnergyDataHistory[]>([])
  const [loading, setLoading] = useState(false)
  const [totalCount, setTotalCount] = useState(0)

  // ---- 编辑模式（仅逐小时模式可用）----
  const [editing, setEditing] = useState(false)
  const [editingValues, setEditingValues] = useState<Record<string, number | undefined>>({})
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set())

  // ---- 搜索 & 多行展开 ----
  const [search, setSearch] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const fetchIdRef = useRef(0)

  // 根据 activePreset 确定 granularity；自定义日期范围默认 daily
  const granularity = activePreset ? PRESETS[activePreset]?.granularity ?? 'daily' : 'daily'
  const presetLabels = Object.keys(PRESETS)

  // 加载能源类型列表
  useEffect(() => {
    getEnabledTypeConfigs().then((list) => {
      setTypeMetadata(list)
      if (list.length > 0 && !activeType) setActiveType(list[0].type_code)
    }).catch(() => {})
  }, [])

  const fetchData = useCallback(async () => {
    if (!activeType) return
    const fetchId = ++fetchIdRef.current
    setLoading(true)
    try {
      const baseParams: Record<string, unknown> = {
        energy_type: activeType,
        granularity,
        start_time: range[0].startOf('day').toISOString(),
        end_time: range[1].endOf('day').toISOString(),
        page_size: 100,
      }
      const allItems: EnergyDataHistory[] = []
      let page = 1
      let total = 0
      while (true) {
        if (fetchId !== fetchIdRef.current) return
        const result = await getEnergyDataHistory({ ...baseParams, page } as any)
        if (fetchId !== fetchIdRef.current) return
        allItems.push(...result.items)
        total = result.total
        if (allItems.length >= total) break
        page++
      }
      if (fetchId !== fetchIdRef.current) return
      setAllRows(allItems)
      setTotalCount(total)
    } catch (e) {
      if (fetchId !== fetchIdRef.current) return
      console.error('获取采集历史失败:', e)
      message.error('获取数据失败')
    } finally {
      setLoading(false)
    }
  }, [activeType, granularity, range, message])

  useEffect(() => { fetchData() }, [fetchData])

  // ---- 编辑保存（仅逐小时模式）----
  const handleSaveValue = useCallback(async (id: string) => {
    const v = editingValues[id]
    if (v === undefined) return
    setSavingIds((prev) => new Set(prev).add(id))
    try {
      await updateEnergyDataValue(id, v)
      message.success('已保存')
      setAllRows((prev) => prev.map((r) => (r.id === id ? { ...r, value: v } : r)))
      setEditingValues((prev) => { const n = { ...prev }; delete n[id]; return n })
    } catch {
      message.error('保存失败')
    } finally {
      setSavingIds((prev) => { const n = new Set(prev); n.delete(id); return n })
    }
  }, [editingValues, message])

  const handleValueChange = useCallback((id: string, value: number | null) => {
    if (value != null) {
      setEditingValues((prev) => ({ ...prev, [id]: value }))
    }
  }, [])

  const unit = allRows[0]?.unit || ''

  // 按部门 + 数据源分组
  const deptRows = useMemo(() => {
    const map = new Map<string, Map<string, EnergyDataHistory[]>>()
    for (const row of allRows) {
      const ws = row.workshop || '未知部门'
      const dev = row.device_name || row.platform_device_code || '未知设备'
      if (!map.has(ws)) map.set(ws, new Map())
      const devMap = map.get(ws)!
      if (!devMap.has(dev)) devMap.set(dev, [])
      devMap.get(dev)!.push(row)
    }
    const list: DeptRow[] = []
    for (const [workshop, deviceMap] of map) {
      let total = 0
      for (const rows of deviceMap.values()) {
        total += rows.reduce((s, r) => s + r.value, 0)
      }
      list.push({ key: workshop, workshop, total, deviceCount: deviceMap.size, deviceMap })
    }
    list.sort((a, b) => b.total - a.total)
    return list
  }, [allRows])

  // 搜索过滤
  const filteredDepts = useMemo(() => {
    if (!search.trim()) return deptRows
    const keyword = search.trim().toLowerCase()
    return deptRows.filter((d) => d.workshop.toLowerCase().includes(keyword))
  }, [deptRows, search])

  const activeMeta = typeMetadata.find((m) => m.type_code === activeType)
  const totalDeviceCount = filteredDepts.reduce((s, d) => s + d.deviceCount, 0)
  const grandTotal = filteredDepts.reduce((s, d) => s + d.total, 0)
  const isHourly = granularity === 'hourly'

  // ---- 主表格列 ----
  const mainColumns: TableColumnsType<DeptRow> = [
    {
      title: '部门', dataIndex: 'workshop', key: 'workshop', width: 200,
      sorter: (a, b) => a.workshop.localeCompare(b.workshop, 'zh-CN'),
      render: (v: string) => (
        <span style={{ fontWeight: 500, color: '#37352f' }}>{v}</span>
      ),
    },
    {
      title: '数据源数', dataIndex: 'deviceCount', key: 'deviceCount', width: 80, align: 'center',
      sorter: (a, b) => a.deviceCount - b.deviceCount,
      render: (v: number) => (
        <span style={{ color: '#787671' }}>{v}</span>
      ),
    },
    {
      title: '合计', dataIndex: 'total', key: 'total', width: 180, align: 'right',
      sorter: (a, b) => a.total - b.total,
      defaultSortOrder: 'descend',
      render: (v: number) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: '#37352f' }}>
          {v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
          <span style={{ fontSize: 12, color: '#a4a097', marginLeft: 4, fontWeight: 400 }}>{unit}</span>
        </span>
      ),
    },
  ]

  // ---- 菜单项 ----
  const menuItems = typeMetadata.map((m) => ({
    key: m.type_code,
    label: (
      <span style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>
          <span style={{ color: m.color || '#999', marginRight: 8 }}>●</span>
          {m.display_name}
        </span>
        {m.type_code === activeType && totalCount > 0 && (
          <span style={{
            fontSize: 11, color: '#a4a097', background: '#f5f2ed',
            padding: '0 6px', borderRadius: 10, lineHeight: '18px',
            minWidth: 20, textAlign: 'center',
          }}>
            {totalCount > 999 ? '999+' : totalCount}
          </span>
        )}
      </span>
    ),
  }))

  return (
    <div style={{ display: 'flex', minHeight: '100%' }}>
      {/* ======== 左侧能源类型菜单 ======== */}
      <div style={{
        width: 180, flexShrink: 0, background: '#fff',
        borderRight: '1px solid #ede9e4', paddingTop: 20,
      }}>
        <div style={{ padding: '0 16px 12px', fontSize: 12, color: '#a4a097', fontWeight: 500, letterSpacing: 1 }}>
          能源类型
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activeType]}
          onClick={({ key }) => { setActiveType(key); setExpandedKeys([]); setSearch('') }}
          items={menuItems}
          style={{ borderInlineEnd: 'none' }}
        />
      </div>

      {/* ======== 右侧内容区 ======== */}
      <div style={{ flex: 1, padding: '24px 32px', overflow: 'auto', minWidth: 0 }}>
        {/* ---- 标题栏 ---- */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <h1 style={{ fontSize: 24, fontWeight: 500, color: '#1a1a1a', margin: 0 }}>
              采集历史{activeMeta ? ` · ${activeMeta.display_name}` : ''}
            </h1>
            <p style={{ fontSize: 13, color: '#a4a097', margin: '4px 0 0' }}>
              {filteredDepts.length} 个部门 · {totalDeviceCount} 个数据源
              {totalCount > 0 && (
                <span> · 共 {totalCount.toLocaleString('zh-CN')} 条记录</span>
              )}
              {grandTotal > 0 && (
                <span> · 合计 {grandTotal.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} {unit}</span>
              )}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {presetLabels.map((label) => (
              <button
                key={label}
                onClick={() => {
                  const p = PRESETS[label]
                  setRange(p.range)
                  setActivePreset(label)
                  setExpandedKeys([])
                }}
                style={{
                  padding: '4px 12px', borderRadius: 6,
                  border: activePreset === label ? '1.5px solid #5645d4' : '1px solid #e8e3f0',
                  background: activePreset === label ? '#f6f3ff' : '#fff',
                  color: activePreset === label ? '#5645d4' : '#787671',
                  cursor: 'pointer', fontSize: 12, fontWeight: 500,
                }}
              >
                {label}
              </button>
            ))}
            <RangePicker
              value={range}
              onChange={(d) => {
                if (d?.[0] && d?.[1]) { setRange([d[0], d[1]]); setActivePreset('') }
              }}
              allowClear={false}
              style={{ marginLeft: 4 }}
            />
          </div>
        </div>

        {/* ---- 搜索栏 + 编辑按钮 ---- */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Input
              prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
              placeholder="搜索部门名称..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setExpandedKeys([]) }}
              allowClear
              style={{ width: 260, borderRadius: 8 }}
            />
            {expandedKeys.length > 0 && (
              <Button
                type="link"
                size="small"
                onClick={() => setExpandedKeys([])}
                style={{ color: '#787671', fontSize: 12 }}
              >
                收起全部
              </Button>
            )}
            {/* 粒度指示标签 */}
            <span style={{
              fontSize: 11, color: '#a4a097', background: '#f5f2ed',
              padding: '2px 8px', borderRadius: 4,
            }}>
              {isHourly ? '逐小时' : '日汇总'}
            </span>
          </div>
          {/* 编辑按钮仅逐小时模式可用 */}
          {isHourly && (
            <Button
              type={editing ? 'primary' : 'default'}
              size="small"
              onClick={() => { setEditing(!editing); setEditingValues({}) }}
              style={{
                background: editing ? '#5645d4' : undefined,
                borderColor: editing ? '#5645d4' : '#c8c4be',
                color: editing ? '#fff' : '#787671',
                borderRadius: 8, fontSize: 12, fontWeight: 500, height: 28,
              }}
            >
              ✏️ {editing ? '退出编辑' : '编辑数据'}
            </Button>
          )}
        </div>

        {/* ---- 加载状态 ---- */}
        <Spin
          spinning={loading}
          description={activeMeta ? `正在加载 ${activeMeta.display_name} 采集数据...` : '加载中...'}
        >
          {deptRows.length > 0 ? (
            <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #ede9e4', padding: '0 16px 16px' }}>
              <Table
                columns={mainColumns}
                dataSource={filteredDepts}
                rowKey="key"
                size="middle"
                pagination={false}
                showSorterTooltip={false}
                expandable={{
                  expandedRowKeys: expandedKeys,
                  onExpandedRowsChange: (keys) => setExpandedKeys(keys as string[]),
                  expandIcon: ({ expanded, onExpand, record }) => (
                    <span
                      onClick={(e) => onExpand(record, e)}
                      style={{
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 22, height: 22,
                        borderRadius: 5,
                        background: expanded ? '#5645d4' : '#f0edf7',
                        color: expanded ? '#fff' : '#5645d4',
                        fontSize: 13,
                        fontWeight: 700,
                        lineHeight: 1,
                        transition: 'all 0.2s ease',
                        userSelect: 'none',
                      }}
                    >
                      {expanded ? '−' : '+'}
                    </span>
                  ),
                  expandedRowRender: (dept) => {
                    const chartColor = activeMeta?.color || '#5645d4'

                    // 近30天（不含今天）可编辑 — 仅逐小时模式
                    const editMin = dayjs().subtract(30, 'day').startOf('day')
                    const editMax = dayjs().subtract(1, 'day').endOf('day')
                    const isWithinEditRange = (ts: string) => {
                      const t = dayjs(ts)
                      return t.isAfter(editMin) && t.isBefore(editMax)
                    }

                    const deviceEntries = [...dept.deviceMap.entries()]
                      .map(([name, rows]) => ({
                        name,
                        total: rows.reduce((s, r) => s + r.value, 0),
                        rows: [...rows].sort((a, b) => {
                          const da = new Date(a.timestamp).getTime()
                          const db = new Date(b.timestamp).getTime()
                          return da - db  // 时间升序（折线图从左到右）
                        }),
                      }))
                      .sort((a, b) => b.total - a.total)

                    return (
                      <div style={{
                        background: '#fff',
                        borderRadius: 8,
                        padding: '12px 16px',
                        border: '1px solid #ede9e4',
                        animation: 'fadeIn 0.2s ease',
                      }}>
                        {deviceEntries.map((dev, idx) => {
                          // X 轴格式
                          const xFormat = isHourly ? 'MM-DD HH:00' : 'MM-DD'
                          const hasChartData = dev.rows.length >= 2

                          return (
                          <div key={dev.name}>
                            {idx > 0 && (
                              <div style={{ borderTop: '1px solid #e8e3f0', margin: '16px 0' }} />
                            )}
                            {/* 数据源标题 */}
                            <div style={{
                              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                              marginBottom: 8,
                            }}>
                              <span style={{ fontWeight: 600, fontSize: 13, color: '#37352f' }}>
                                📊 {dev.name}
                                <span style={{ fontWeight: 400, fontSize: 11, color: '#a4a097', marginLeft: 6 }}>
                                  {dev.rows.length} 条
                                </span>
                              </span>
                              <span style={{ fontSize: 12, color: '#a4a097' }}>
                                合计 {dev.total.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                                <span style={{ marginLeft: 2 }}>{unit}</span>
                              </span>
                            </div>

                            {/* 折线图：有 ≥2 个数据点时渲染 */}
                            {hasChartData ? (
                              <Line
                                data={dev.rows.map((r) => ({
                                  date: dayjs(r.timestamp).format(xFormat),
                                  value: r.value,
                                }))}
                                xField="date"
                                yField="value"
                                smooth
                                height={200}
                                point={{ size: 3, shape: 'circle' }}
                                xAxis={{
                                  label: { autoRotate: true, style: { fontSize: 11, fill: '#a4a097' } },
                                  grid: null,
                                  tickLine: null,
                                }}
                                yAxis={{
                                  grid: { line: { style: { stroke: '#f0f0f0', lineDash: [3, 3] } } },
                                  label: { style: { fontSize: 11, fill: '#a4a097' } },
                                }}
                                tooltip={{
                                  crosshairs: { type: 'xy' as const },
                                  items: [{
                                    channel: 'y',
                                    valueFormatter: (v: number) =>
                                      `${v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} ${unit}`,
                                  }],
                                }}
                                color={chartColor}
                                areaStyle={{ fill: chartColor, fillOpacity: 0.08 }}
                                lineStyle={{ stroke: chartColor, lineWidth: 2 }}
                                animate={{ appear: { animation: 'wave-in', duration: 600 } }}
                              />
                            ) : (
                              <div style={{
                                padding: '20px 0', textAlign: 'center', color: '#a4a097', fontSize: 13,
                                background: '#fafaf9', borderRadius: 6, marginBottom: 8,
                              }}>
                                {dev.rows.length === 1
                                  ? `${dayjs(dev.rows[0].timestamp).format(xFormat)} · ${dev.rows[0].value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} ${unit}`
                                  : '暂无数据'}
                              </div>
                            )}

                            {/* 数据明细列表 */}
                            <div style={{
                              display: 'flex', flexDirection: 'column', gap: 3,
                              marginTop: 8,
                              borderTop: '1px dashed #ede9e4',
                              paddingTop: 8,
                            }}>
                              {dev.rows.map((row) => {
                                const canEdit = editing && isHourly && isWithinEditRange(row.timestamp)
                                return (
                                  <div
                                    key={row.id}
                                    style={{
                                      display: 'flex', justifyContent: 'space-between',
                                      padding: '3px 8px', borderRadius: 4, transition: 'background 0.15s',
                                    }}
                                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#f0edf7' }}
                                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '' }}
                                  >
                                    <span style={{ fontSize: 13, color: '#787671' }}>
                                      {dayjs(row.timestamp).format(xFormat)}
                                    </span>
                                    <span style={{ fontSize: 13, color: '#37352f', fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
                                      {canEdit ? (
                                        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                          <InputNumber
                                            size="small"
                                            value={editingValues[row.id] !== undefined ? editingValues[row.id] : row.value}
                                            onChange={(v) => handleValueChange(row.id, v)}
                                            onPressEnter={() => handleSaveValue(row.id)}
                                            style={{ width: 120, height: 26, fontSize: 13 }}
                                            precision={0}
                                          />
                                          <Button
                                            type="link"
                                            size="small"
                                            loading={savingIds.has(row.id)}
                                            onClick={() => handleSaveValue(row.id)}
                                            style={{ padding: 0, height: 22, fontSize: 11 }}
                                          >
                                            保存
                                          </Button>
                                        </span>
                                      ) : (
                                        <span>
                                          {row.value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                                        </span>
                                      )}
                                      <span style={{ fontSize: 11, color: '#a4a097', marginLeft: 4, fontWeight: 400 }}>{unit}</span>
                                    </span>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                          )
                        })}

                        {/* 底部收起按钮 */}
                        <div style={{
                          textAlign: 'center', marginTop: 12, paddingTop: 12,
                          borderTop: '1px solid #e8e3f0',
                        }}>
                          <Button
                            type="link"
                            size="small"
                            onClick={() => setExpandedKeys((prev) => prev.filter((k) => k !== dept.key))}
                            style={{ color: '#a4a097', fontSize: 12 }}
                          >
                            收起
                          </Button>
                        </div>
                      </div>
                    )
                  },
                }}
                locale={{
                  triggerDesc: '点击降序排序',
                  triggerAsc: '点击升序排序',
                  cancelSort: '取消排序',
                }}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
              <Empty
                description={
                  loading
                    ? `正在加载${activeMeta?.display_name || ''}采集数据...`
                    : deptRows.length === 0 && allRows.length === 0
                      ? '当前时间范围内无采集数据'
                      : '未找到匹配的部门'
                }
              />
            </div>
          )}
        </Spin>
      </div>

      {/* ---- 展开动画 keyframes ---- */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
