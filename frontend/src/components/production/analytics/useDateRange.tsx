'use client'

import { useState } from 'react'
import dayjs from 'dayjs'
import { DatePicker } from 'antd'

const { RangePicker } = DatePicker

type RangeState = [string, string] | null

/**
 * RangePicker 的日界状态：对外暴露 ['YYYY-MM-DD', 'YYYY-MM-DD'] | null，
 * picker 为现成元素，调用点直接渲染（FieldTrendChart 需 set disabled 时传入）。
 */
export function useDateRangeState({ disabled }: { disabled?: boolean } = {}) {
  const [dateRange, setDateRange] = useState<RangeState>(null)
  const picker = (
    <RangePicker
      placeholder={['开始日期', '结束日期']}
      disabled={disabled}
      value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
      onChange={(dates: [dayjs.Dayjs | null, dayjs.Dayjs | null] | null) => {
        if (dates && dates[0] && dates[1]) {
          setDateRange([dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')])
        } else {
          setDateRange(null)
        }
      }}
      style={{ minWidth: 220 }}
    />
  )
  return { dateRange, picker }
}
