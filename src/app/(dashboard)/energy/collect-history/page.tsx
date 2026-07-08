'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { Button, DatePicker, Select, Table, App, Tag } from 'antd'
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import { getEnergyDevices, getCollectHistory } from '@/actions/energy'
import { fetchPlatformsClient } from '@/lib/api/energy'
import type { EnergyType } from '@/types/energy'
import { energyTypeLabels } from '@/components/energy/constants'
import {
  EnergyDeviceConfig,
  CollectHistoryItem,
  PaginatedResponse,
} from '@/types/energy'

// ── 平台级配置（已知平台特殊处理，新平台用默认值） ──

interface PlatformConfig {
  code: string
  label: string
  energy_type: string | undefined
  codeColumnTitle: string
  accentColor: string
  energyTypeFixed: string | null
}

const KNOWN: Record<string, Partial<PlatformConfig>> = {
  zhiheng: {
    energy_type: 'water',
    codeColumnTitle: '平台接入编码',
    accentColor: '#5645d4',
    energyTypeFixed: 'water',
  },
  platform_b: {
    codeColumnTitle: '公式ID',
    accentColor: '#dd5b00',
  },
}

const DEFAULTS: Omit<PlatformConfig, 'code' | 'label'> = {
  energy_type: undefined,
  codeColumnTitle: '平台接入编码',
  accentColor: '#5645d4',
  energyTypeFixed: null,
}

function buildConfig(code: string, name: string): PlatformConfig {
  return { code, label: name, ...{ ...DEFAULTS, ...KNOWN[code] } }
}

const todayStr = new Date().toISOString().slice(0, 10)

export default function CollectHistoryPage() {
  const { message } = App.useApp()
  const {
    collectHistoryFilters,
    setCollectHistoryFilters,
    resetCollectHistoryFilters,
  } = useEnergyStore()

  const [platforms, setPlatforms] = useState<PlatformConfig[]>([])
  const [platformCode, setPlatformCode] = useState<string>('zhiheng')
  const [energyTypeFilter, setEnergyTypeFilter] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [devices, setDevices] = useState<EnergyDeviceConfig[]>([])
  const [devicesLoading, setDevicesLoading] = useState(false)
  const [data, setData] = useState<PaginatedResponse<CollectHistoryItem>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 10,
  })

  const platform = useMemo(
    () => platforms.find((p) => p.code === platformCode) ?? buildConfig(platformCode, platformCode),
    [platforms, platformCode],
  )

  // ── 加载平台列表 ──
  useEffect(() => {
    fetchPlatformsClient()
      .then((list) => setPlatforms(list.map((p) => buildConfig(p.code, p.name))))
      .catch(() => message.error('加载平台列表失败'))
  }, [message])

  // ── 平台切换时重置 ──
  useEffect(() => {
    setDevices([])
    setData({ items: [], total: 0, page: 1, page_size: 10 })
    setCollectHistoryFilters({ device_config_id: undefined, page: 1 })
    setEnergyTypeFilter(undefined)
  }, [platformCode, setCollectHistoryFilters])

  // ── 当前平台设备中出现的能源类型（去重） ──
  const energyTypeOptions = useMemo(() => {
    const seen = new Set<string>()
    return devices.reduce<{ label: string; value: string }[]>((acc, d) => {
      if (seen.has(d.energy_type)) return acc
      seen.add(d.energy_type)
      const label = energyTypeLabels[d.energy_type as keyof typeof energyTypeLabels]
      acc.push({ label: label?.text ?? d.energy_type, value: d.energy_type })
      return acc
    }, [])
  }, [devices])

  // ── 加载当前平台设备 ──
  const loadDevices = useCallback(async () => {
    setDevicesLoading(true)
    try {
      const result = await getEnergyDevices({
        platform_code: platform.code,
        energy_type: platform.energy_type as EnergyType | undefined,
        page_size: 100,
      })
      setDevices(result.items)
    } catch {
      message.error('加载数据源列表失败')
    } finally {
      setDevicesLoading(false)
    }
  }, [message, platform])

  useEffect(() => {
    loadDevices()
  }, [loadDevices])

  // ── 查询采集历史 ──
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const result = await getCollectHistory({
        ...collectHistoryFilters,
        platform_code: platform.code,
        energy_type: energyTypeFilter ?? platform.energy_type,
      })
      setData(result)
    } catch {
      message.error('获取采集历史失败')
    } finally {
      setLoading(false)
    }
  }, [collectHistoryFilters, message, platform, energyTypeFilter])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleReset = () => {
    resetCollectHistoryFilters()
  }

  // ── 表格列 ──
  const columns: ColumnsType<CollectHistoryItem> = useMemo(
    () => [
      {
        title: '数据源名称',
        dataIndex: 'device_name',
        key: 'device_name',
        width: 220,
        ellipsis: true,
      },
      {
        title: platform.codeColumnTitle,
        dataIndex: 'platform_device_code',
        key: 'platform_device_code',
        width: platform.code === 'platform_b' ? 120 : 180,
      },
      {
        title: '能源类型',
        dataIndex: 'energy_type',
        key: 'energy_type',
        width: 130,
        render:
          platform.energyTypeFixed
            ? () => (
                <Tag color={energyTypeLabels[platform.energyTypeFixed as keyof typeof energyTypeLabels]?.color}>
                  {energyTypeLabels[platform.energyTypeFixed as keyof typeof energyTypeLabels]?.text}
                </Tag>
              )
            : (et: string) => {
                const label = energyTypeLabels[et as keyof typeof energyTypeLabels]
                return label ? <Tag color={label.color}>{label.text}</Tag> : <span>{et}</span>
              },
      },
      {
        title: '采集时间',
        dataIndex: 'timestamp',
        key: 'timestamp',
        width: 200,
        render: (val: string) => {
          const d = new Date(val)
          const pad = (n: number) => String(n).padStart(2, '0')
          return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        },
      },
      {
        title: '能耗值',
        dataIndex: 'value',
        key: 'value',
        width: 140,
        render: (val: number, record) => (
          <span>
            {val.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}{' '}
            <span style={{ color: '#a4a097', fontSize: 12 }}>{record.unit}</span>
          </span>
        ),
      },
    ],
    [platform],
  )

  const filledStyle = {
    background: '#f6f5f4',
    border: 'none',
    borderRadius: 8,
    height: 36,
  }

  return (
    <div
      style={{
        padding: '28px 32px',
        maxWidth: 1280,
        minHeight: '100%',
        background: '#fafaf9',
      }}
    >
      <h1
        style={{
          fontSize: 28,
          fontWeight: 500,
          color: '#1a1a1a',
          margin: 0,
          letterSpacing: '-0.3px',
          lineHeight: 1.3,
        }}
      >
        采集历史
      </h1>
      <p
        style={{
          fontSize: 13,
          color: '#a4a097',
          margin: '4px 0 0',
          lineHeight: 1.5,
        }}
      >
        查询{platform.label}采集记录，支持按数据源与日期筛选
      </p>

      <div
        style={{
          height: 1,
          marginTop: 18,
          marginBottom: 20,
          background: `linear-gradient(to right, ${platform.accentColor} 0%, transparent 100%)`,
        }}
      />

      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap',
          background: '#ffffff',
          borderRadius: 12,
          padding: '12px 18px',
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          border: '1px solid #ede9e4',
          marginBottom: 20,
        }}
      >
        <Select
          value={platformCode}
          onChange={(val) => setPlatformCode(val)}
          variant="filled"
          style={{ width: 160, ...filledStyle }}
          options={platforms.map((p) => ({ label: p.label, value: p.code }))}
        />

        <div
          style={{
            width: 1,
            height: 20,
            background: '#ede9e4',
            margin: '0 4px',
          }}
        />

        <Select
          placeholder="选择数据源"
          allowClear
          loading={devicesLoading}
          variant="filled"
          style={{ width: 220, ...filledStyle }}
          value={collectHistoryFilters.device_config_id || undefined}
          onChange={(value) =>
            setCollectHistoryFilters({ device_config_id: value, page: 1 })
          }
          options={devices.map((d) => ({
            label: d.device_name,
            value: d.id,
          }))}
          showSearch
        />

        <Select
          placeholder="能源筛选"
          allowClear
          variant="filled"
          style={{ width: 130, ...filledStyle }}
          value={energyTypeFilter}
          onChange={(value) => {
            setEnergyTypeFilter(value)
            setCollectHistoryFilters({ page: 1 })
          }}
          options={energyTypeOptions}
        />

        <DatePicker.RangePicker
          variant="filled"
          style={{ width: 260, ...filledStyle }}
          value={[
            dayjs(collectHistoryFilters.start_date || todayStr),
            dayjs(collectHistoryFilters.end_date || todayStr),
          ]}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setCollectHistoryFilters({
                start_date: dates[0].format('YYYY-MM-DD'),
                end_date: dates[1].format('YYYY-MM-DD'),
                page: 1,
              })
            }
          }}
          disabledDate={(current) =>
            current && current.isAfter(dayjs(), 'day')
          }
          allowClear={false}
          placeholder={['开始日期', '结束日期']}
        />

        <Button
          icon={<SearchOutlined />}
          onClick={fetchData}
          loading={loading}
          style={{
            color: '#5645d4',
            borderColor: '#5645d4',
            borderRadius: 8,
            fontWeight: 500,
            fontSize: 14,
            height: 36,
            padding: '0 16px',
          }}
        >
          查询
        </Button>

        <Button
          onClick={handleReset}
          style={{
            color: '#787671',
            borderRadius: 8,
            fontWeight: 500,
            fontSize: 13,
            height: 36,
            border: 'none',
            background: '#f6f5f4',
          }}
        >
          重置
        </Button>

        <div style={{ flex: 1 }} />

        <Button
          icon={<ReloadOutlined />}
          onClick={fetchData}
          loading={loading}
          style={{
            color: '#787671',
            borderColor: '#c8c4be',
            borderRadius: 8,
            fontWeight: 500,
            fontSize: 13,
            height: 32,
          }}
        >
          刷新
        </Button>
      </div>

      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          border: '1px solid #ede9e4',
          overflow: 'hidden',
        }}
      >
        <Table<CollectHistoryItem>
          columns={columns}
          dataSource={data.items}
          rowKey={(record) =>
            `${record.platform_device_code}-${record.timestamp}`
          }
          loading={loading}
          size="middle"
          pagination={{
            current: data.page,
            pageSize: data.page_size,
            total: data.total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            showTotal: (total: number) => `共 ${total} 条`,
            onChange: (page, pageSize) =>
              setCollectHistoryFilters({ page, page_size: pageSize }),
          }}
          scroll={{ x: 860 }}
          locale={{ emptyText: '暂无采集数据，请选择数据源和日期后查询' }}
        />
      </div>
    </div>
  )
}
