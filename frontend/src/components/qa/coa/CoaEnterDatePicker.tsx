'use client'

import { useRef } from 'react'
import { DatePicker } from 'antd'
import type { DatePickerProps } from 'antd'
import type { Dayjs } from 'dayjs'
import { focusNextHeadInput } from './CoaResultInput'

/**
 * 带回车跳格的日期框（报告信息面板用），其余用法与 DatePicker 相同。
 *
 * 日期框自己的回车是「打开面板」：面板关着时按回车会弹出日历。这里拦掉它，改成跳到
 * 下一个输入框；面板开着时回车是「确认选中日期」，照旧交给日期框。
 */
// 第二个类型参数 false = 不开多选：值是单个 Dayjs，不是数组
export function CoaEnterDatePicker({ onOpenChange, ...props }: DatePickerProps<Dayjs, false>) {
  const openRef = useRef(false)
  return (
    <DatePicker
      {...props}
      data-coa-head-input
      onOpenChange={(open) => {
        openRef.current = open
        onOpenChange?.(open)
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Enter' || openRef.current) return
        event.preventDefault()
        focusNextHeadInput(event)
      }}
    />
  )
}
