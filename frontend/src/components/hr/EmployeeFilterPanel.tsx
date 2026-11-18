'use client'

/**
 * 员工档案筛选面板（受控展开）：触发按钮由页面 Tab 栏渲染（带角标），本组件只负责展开后的表单。
 * - 可枚举字段 → 下拉（选项由后端聚合现有数据，跟随飞书源表变化）
 * - 日期字段 → 时间范围选择器（出生日期按年拆分存储，用年份范围）
 * - 年龄 → 数字区间；域账号/离职原因 → 文本（防抖）
 * 部门（Tabs）与状态（Tab 栏下拉）已有独立入口，不在此面板重复。
 */

import { useMemo, useRef } from 'react'
import { Button, DatePicker, Form, Input, InputNumber, Select } from 'antd'
import { DownOutlined, UndoOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { EmployeeFieldFilters, EmployeeFilterOptions } from '@/types/hr'

// 下拉字段清单：key 与后端 filter-options 字段对齐，label 与表格列名一致
const SELECT_FIELDS: { key: keyof EmployeeFilterOptions; label: string }[] = [
  { key: 'position', label: '岗位' },
  { key: 'duty', label: '职务' },
  { key: 'job_category', label: '职能分类' },
  { key: 'level', label: '职级' },
  { key: 'report_grade', label: '岗位职级' },
  { key: 'status_category', label: '员工性质' },
  { key: 'gender', label: '性别' },
  { key: 'ethnicity', label: '民族' },
  { key: 'native_place', label: '籍贯' },
  { key: 'marital_status', label: '婚姻状况' },
  { key: 'household_type', label: '户口类型' },
  { key: 'education', label: '学历' },
  { key: 'degree_type', label: '学位类型' },
  { key: 'classification', label: '学习形式' },
  { key: 'school', label: '毕业院校' },
  { key: 'major', label: '专业' },
  { key: 'hr_analysis', label: '人力资源分析' },
]

// 日期范围字段：key 同时用于表单值与筛选参数（YYYY-MM-DD）
const DATE_RANGE_FIELDS: { key: string; label: string }[] = [
  { key: 'graduation_date', label: '毕业时间' },
  { key: 'work_start_date', label: '参加工作时间' },
  { key: 'hire_date', label: '入职日期' },
  { key: 'departure_date', label: '离职日期' },
  { key: 'contract_start_date', label: '合同开始日期' },
  { key: 'contract_end_date', label: '合同结束日期' },
]

type RangeVal = [Dayjs | null, Dayjs | null] | null | undefined

interface FilterFormValues {
  age_min?: number | null
  age_max?: number | null
  birth_year?: RangeVal
  domain_account?: string
  departure_reason?: string
  [key: string]: unknown
}

/** 已启用筛选项数（年龄 min/max 合并计 1 项，用于角标与提示） */
export function countActiveFilters(filters: EmployeeFieldFilters): number {
  const hasValue = (v: unknown) => v !== undefined && v !== '' && v !== null
  const nonAge = Object.entries(filters).filter(
    ([k, v]) => k !== 'age_min' && k !== 'age_max' && hasValue(v),
  ).length
  const hasAge = filters.age_min != null || filters.age_max != null
  return nonAge + (hasAge ? 1 : 0)
}

function toFilters(values: FilterFormValues): EmployeeFieldFilters {
  const out: Record<string, unknown> = {}
  for (const { key } of SELECT_FIELDS) {
    const v = values[key] as string | undefined
    if (v) out[key] = v
  }
  if (values.domain_account) out.domain_account = values.domain_account
  if (values.departure_reason) out.departure_reason = values.departure_reason
  if (values.age_min != null) out.age_min = values.age_min
  if (values.age_max != null) out.age_max = values.age_max
  const by = values.birth_year
  if (by?.[0] && by?.[1]) out.birth_year = [by[0].year(), by[1].year()]
  for (const { key } of DATE_RANGE_FIELDS) {
    const range = values[key] as RangeVal
    if (range?.[0] && range?.[1]) {
      out[key] = [range[0].format('YYYY-MM-DD'), range[1].format('YYYY-MM-DD')]
    }
  }
  return out as EmployeeFieldFilters
}

interface EmployeeFilterPanelProps {
  options: EmployeeFilterOptions
  value: EmployeeFieldFilters
  onChange: (filters: EmployeeFieldFilters) => void
  /** 收起面板（触发按钮在页面 Tab 栏） */
  onClose: () => void
}

export default function EmployeeFilterPanel({ options, value, onChange, onClose }: EmployeeFilterPanelProps) {
  const [form] = Form.useForm<FilterFormValues>()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const activeCount = useMemo(() => countActiveFilters(value), [value])

  const commit = (values: FilterFormValues) => {
    onChange(toFilters(values))
  }

  const handleValuesChange = (_changed: Record<string, unknown>, allValues: FilterFormValues) => {
    // 文本输入防抖 300ms（对齐搜索框节奏），下拉/日期/数字为单次操作即时生效
    const textKeys = new Set(['domain_account', 'departure_reason'])
    const isTextOnly = Object.keys(_changed).every((k) => textKeys.has(k))
    if (!isTextOnly) {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      commit(allValues)
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => commit(allValues), 300)
  }

  const handleReset = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    form.resetFields()
    onChange({})
  }

  return (
    <div className="mb-4 rounded-lg border border-[var(--color-hairline)] bg-white p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="text-xs text-[var(--color-stone)]">
          {activeCount > 0 ? `已启用 ${activeCount} 项筛选` : '可组合多项条件，选择即生效'}
        </span>
        <div className="flex items-center gap-1">
          <Button
            type="text"
            size="small"
            icon={<UndoOutlined />}
            onClick={handleReset}
            disabled={activeCount === 0}
          >
            重置
          </Button>
          <Button type="text" size="small" onClick={onClose}>
            收起 <DownOutlined />
          </Button>
        </div>
      </div>

      <Form
        form={form}
        layout="vertical"
        onValuesChange={handleValuesChange}
        className="grid grid-cols-2 gap-x-4 md:grid-cols-3 xl:grid-cols-4"
        requiredMark={false}
      >
        {SELECT_FIELDS.map(({ key, label }) => (
          <Form.Item key={key} name={key} label={label} className="mb-2">
            <Select
              placeholder="全部"
              allowClear
              showSearch
              optionFilterProp="label"
              options={(options[key] || []).map((v) => ({ value: v, label: v }))}
            />
          </Form.Item>
        ))}

        <Form.Item label="年龄（岁）" className="mb-2">
          <div className="flex items-center gap-1">
            <Form.Item name="age_min" noStyle>
              <InputNumber placeholder="最小" className="w-full" />
            </Form.Item>
            <span className="text-neutral-400">~</span>
            <Form.Item name="age_max" noStyle>
              <InputNumber placeholder="最大" className="w-full" />
            </Form.Item>
          </div>
        </Form.Item>

        <Form.Item name="birth_year" label="出生年份" className="mb-2">
          <DatePicker.RangePicker picker="year" className="w-full" allowEmpty={[true, true]} />
        </Form.Item>

        {DATE_RANGE_FIELDS.map(({ key, label }) => (
          <Form.Item key={key} name={key} label={label} className="mb-2">
            <DatePicker.RangePicker className="w-full" allowEmpty={[true, true]} />
          </Form.Item>
        ))}

        <Form.Item name="domain_account" label="域账号" className="mb-2">
          <Input placeholder="前缀匹配" allowClear />
        </Form.Item>
        <Form.Item name="departure_reason" label="离职原因" className="mb-2">
          <Input placeholder="包含匹配" allowClear />
        </Form.Item>
      </Form>
    </div>
  )
}
