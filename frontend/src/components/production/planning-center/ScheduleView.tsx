'use client'

import { useState, useCallback } from 'react'
import { DatePicker, Select, Radio, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { Equipment } from '@/types/equipment'
import type { PlanOrder } from '@/types/production'
import { fetchScheduleViewClient, fetchPlanOrdersClient } from '@/lib/api/production-client'
import { fetchEquipmentsClient } from '@/lib/api/equipment-client'
import { ScheduleGantt } from './ScheduleGantt'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'

type ViewMode = 'day' | 'week' | 'month'

export function ScheduleView() {
  const [viewMode, setViewMode] = useState<ViewMode>('week')
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>(() => [
    dayjs().startOf('week'),
    dayjs().endOf('week'),
  ])
  const [equipmentId, setEquipmentId] = useState<string | undefined>()
  const [planOrderId, setPlanOrderId] = useState<string | undefined>()

  const { data: items, isLoading } = useQuery({
    queryKey: ['scheduleView', dateRange[0].toISOString(), dateRange[1].toISOString(), equipmentId],
    queryFn: () => fetchScheduleViewClient({
      from_time: dateRange[0].toISOString(),
      to_time: dateRange[1].toISOString(),
      equipment_id: equipmentId,
    }),
    placeholderData: (prev) => prev,
  })

  const { data: equipmentData } = useQuery({
    queryKey: ['equipmentList'],
    queryFn: () => fetchEquipmentsClient({ page: 1, page_size: 200 }),
    staleTime: 5 * 60 * 1000,
  })

  const { data: planOrders } = useQuery({
    queryKey: ['planOrders'],
    queryFn: () => fetchPlanOrdersClient({ page_size: 100 }),
    staleTime: 2 * 60 * 1000,
  })

  const handleViewModeChange = useCallback((mode: ViewMode) => {
    setViewMode(mode)
    const now = dayjs()
    if (mode === 'day') {
      setDateRange([now.startOf('day'), now.endOf('day')])
    } else if (mode === 'week') {
      setDateRange([now.startOf('week'), now.endOf('week')])
    } else {
      setDateRange([now.startOf('month'), now.endOf('month')])
    }
  }, [])

  const handleDateRangeChange = useCallback((dates: [Dayjs | null, Dayjs | null] | null) => {
    if (dates?.[0] && dates?.[1]) {
      setDateRange([dates[0], dates[1]])
    }
  }, [])

  const equipmentOptions = (equipmentData?.items ?? []).map((eq: Equipment) => ({
    value: eq.id,
    label: `${eq.equipment_no} ${eq.name}`.trim(),
  }))

  const planOrderOptions = (planOrders ?? []).map((po: PlanOrder) => ({
    value: po.id,
    label: `${po.order_no} ${po.title}`.trim(),
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Filter bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap' as const,
      }}>
        <Radio.Group
          value={viewMode}
          onChange={(e) => handleViewModeChange(e.target.value as ViewMode)}
          optionType="button"
          buttonStyle="solid"
          size="small"
        >
          <Radio.Button value="day">日</Radio.Button>
          <Radio.Button value="week">周</Radio.Button>
          <Radio.Button value="month">月</Radio.Button>
        </Radio.Group>

        <DatePicker.RangePicker
          value={dateRange}
          onChange={handleDateRangeChange as any}
          size="small"
          style={{ width: 240 }}
          picker={viewMode === 'day' ? 'date' : viewMode === 'month' ? 'month' : 'week'}
        />

        <Select
          placeholder="全部设备"
          allowClear
          showSearch={{ filterOption: (input, option) =>
            (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }}
          size="small"
          style={{ width: 220 }}
          value={equipmentId}
          onChange={setEquipmentId}
          options={equipmentOptions}
        />

        <Select
          placeholder="全部计划单"
          allowClear
          showSearch={{ filterOption: (input, option) =>
            (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }}
          size="small"
          style={{ width: 220 }}
          value={planOrderId}
          onChange={setPlanOrderId}
          options={planOrderOptions}
        />
      </div>

      {/* Content */}
      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 320 }}>
          <Spin />
        </div>
      ) : !items || items.length === 0 ? (
        <Empty description="暂无排程数据" />
      ) : (
        <ScheduleGantt
          items={items}
          viewMode={viewMode}
          timelineStart={dateRange[0].toISOString()}
          timelineEnd={dateRange[1].toISOString()}
          planOrderId={planOrderId}
        />
      )}
    </div>
  )
}
