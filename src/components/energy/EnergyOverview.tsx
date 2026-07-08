'use client'

import { useEffect, useState, useCallback } from 'react'
import { App, Select, Button, Segmented } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { StatsCards } from './StatsCards'
import { TrendChart } from './TrendChart'
import { DistributionChart } from './DistributionChart'
import { useEnergyStore } from '@/stores/energy'
import {
  EnergyStatistics,
  TrendDataPoint,
  DistributionDataPoint,
} from '@/types/energy'
import { fetchEnergyOverviewClient } from '@/lib/api/energy'

export function EnergyOverview() {
  const { message } = App.useApp()
  const {
    overviewTimeRange,
    setOverviewTimeRange,
    selectedEnergyType,
    setSelectedEnergyType,
  } = useEnergyStore()

  const [loading, setLoading] = useState(false)
  const [statistics, setStatistics] = useState<EnergyStatistics>({
    total_electricity: 0,
    total_water: 0,
    total_steam: 0,
    total_cooling: 0,
    total_compressed_air: 0,
    total_nitrogen: 0,
    total_natural_gas: 0,
    total_gas: 0,
  })
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([])
  const [distributionData, setDistributionData] = useState<DistributionDataPoint[]>([])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const now = new Date()
      const endTime = now.toISOString()
      let startTime: string
      if (overviewTimeRange === 'today') {
        startTime = new Date(new Date().setHours(0, 0, 0, 0)).toISOString()
      } else if (overviewTimeRange === 'week') {
        startTime = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString()
      } else {
        startTime = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()
      }

      const overview = await fetchEnergyOverviewClient({
        start_time: startTime,
        end_time: endTime,
        energy_type: selectedEnergyType === 'all' ? undefined : selectedEnergyType,
      })

      setStatistics(overview.summary)
      setTrendData(overview.trend)
      setDistributionData(
        overview.distribution.map((d: { name?: string; group_key?: string; value?: number; total_value?: number }) => ({
          name: d.name || d.group_key || '',
          value: d.value ?? d.total_value ?? 0,
        })),
      )
    } catch (error) {
      console.error('获取能源数据失败:', error)
      message.error('获取能源数据失败')
    } finally {
      setLoading(false)
    }
  }, [overviewTimeRange, selectedEnergyType, message])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return (
    <div
      style={{
        padding: '28px 32px',
        maxWidth: 1280,
        minHeight: '100%',
        background: '#fafaf9',
      }}
    >
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
        能源总览
      </h1>
      <p
        style={{
          fontSize: 13,
          color: '#a4a097',
          margin: '4px 0 0',
          lineHeight: 1.5,
        }}
      >
        实时监控全厂能耗数据，追踪趋势与分布
      </p>

      {/* 渐变分割线 */}
      <div
        style={{
          height: 1,
          marginTop: 18,
          marginBottom: 20,
          background:
            'linear-gradient(to right, #5645d4 0%, #e6e0f5 40%, transparent 100%)',
        }}
      />

      {/* ════ 筛选卡片 ════ */}
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
          background: '#ffffff',
          borderRadius: 12,
          padding: '10px 18px',
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          border: '1px solid #ede9e4',
          marginBottom: 20,
        }}
      >
        <Segmented
          value={overviewTimeRange}
          onChange={(value) =>
            setOverviewTimeRange(value as 'today' | 'week' | 'month')
          }
          options={[
            { label: '今日', value: 'today' },
            { label: '近7天', value: 'week' },
            { label: '近30天', value: 'month' },
          ]}
          style={{
            background: '#f6f5f4',
            borderRadius: 8,
            padding: 2,
          }}
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
          value={selectedEnergyType}
          onChange={setSelectedEnergyType}
          variant="filled"
          style={{
            width: 100,
            background: '#f6f5f4',
            border: 'none',
            borderRadius: 8,
            height: 32,
          }}
          options={[
            { label: '全部能源', value: 'all' },
            { label: '电耗数据',   value: 'electricity' },
            { label: '水耗数据',   value: 'water' },
            { label: '蒸汽数据',   value: 'steam' },
            { label: '冷量数据',   value: 'cooling' },
            { label: '压缩空气数据', value: 'compressed_air' },
            { label: '氮气数据',   value: 'nitrogen' },
            { label: '天然气数据', value: 'natural_gas' },
          ]}
        />

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

      {/* ════ 统计卡片 ════ */}
      <StatsCards statistics={statistics} loading={loading} />

      {/* ════ 图表区 ════ */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
        }}
      >
        <TrendChart data={trendData} loading={loading} />
        <DistributionChart data={distributionData} loading={loading} />
      </div>
    </div>
  )
}
