'use client'

import { useEffect, useState, useCallback } from 'react'
import { Input, Select, Button } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useEnergyStore } from '@/stores/energy'
import { DeviceTable } from '@/components/energy/DeviceTable'
import { DeviceDrawer } from '@/components/energy/DeviceDrawer'
import { getEnergyDevices } from '@/actions/energy'
import { EnergyDeviceConfig, PaginatedResponse } from '@/types/energy'

export default function DevicesPage() {
  const { deviceFilters, setDeviceFilters, openDeviceDrawer } = useEnergyStore()

  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<PaginatedResponse<EnergyDeviceConfig>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 10,
  })

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const result = await getEnergyDevices(deviceFilters)
      setData(result)
    } catch (error) {
      console.error('获取数据源列表失败:', error)
    } finally {
      setLoading(false)
    }
  }, [deviceFilters])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // ── 共享的 filled-input 样式 ──
  const filledInputStyle = { background: '#f6f5f4', border: 'none', borderRadius: 8, height: 36 }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1280, minHeight: '100%', background: '#fafaf9' }}>
      {/* ════ 标题区 ════ */}
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
        数据源配置
      </h1>
      <p
        style={{
          fontSize: 13,
          color: '#a4a097',
          margin: '4px 0 0',
          lineHeight: 1.5,
        }}
      >
        管理能源数据采集来源与平台连接配置
      </p>

      {/* 渐变分割线 */}
      <div
        style={{
          height: 1,
          marginTop: 18,
          marginBottom: 20,
          background: 'linear-gradient(to right, #5645d4 0%, #e6e0f5 40%, transparent 100%)',
        }}
      />

      {/* ════ 筛选栏 — 轻质卡片 ════ */}
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
        <Input
          placeholder="搜索数据源名称…"
          prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          variant="filled"
          style={{ width: 220, ...filledInputStyle }}
          value={deviceFilters.keyword}
          onChange={(e) => setDeviceFilters({ keyword: e.target.value || undefined, page: 1 })}
          allowClear
        />

        <Select
          placeholder="能源类型"
          allowClear
          variant="filled"
          style={{ width: 110, ...filledInputStyle }}
          value={deviceFilters.energy_type}
          onChange={(value) => setDeviceFilters({ energy_type: value, page: 1 })}
          options={[
            { label: '电耗数据',   value: 'electricity' },
            { label: '水耗数据',   value: 'water' },
            { label: '蒸汽数据',   value: 'steam' },
            { label: '冷量数据',   value: 'cooling' },
            { label: '压缩空气数据', value: 'compressed_air' },
            { label: '氮气数据',   value: 'nitrogen' },
            { label: '天然气数据', value: 'natural_gas' },
          ]}
        />

        <Select
          placeholder="状态"
          allowClear
          variant="filled"
          style={{ width: 90, ...filledInputStyle }}
          value={deviceFilters.is_enabled}
          onChange={(value) => setDeviceFilters({ is_enabled: value, page: 1 })}
          options={[
            { label: '启用', value: true },
            { label: '禁用', value: false },
          ]}
        />

        {/* 右侧弹簧 */}
        <div style={{ flex: 1 }} />

        <Button
          icon={<PlusOutlined />}
          onClick={() => openDeviceDrawer('create')}
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
          新增数据源
        </Button>
      </div>

      {/* ════ 数据表格 ════ */}
      <DeviceTable
        data={data.items}
        loading={loading}
        total={data.total}
        onRefresh={fetchData}
      />

      <DeviceDrawer onRefresh={fetchData} />
    </div>
  )
}
