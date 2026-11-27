'use client'

// 离职台账筛选栏：需求「筛选与导出」的十类条件（性别 / 学历 / 部门 / 岗位 / 离职原因 / 用工类型 /
// 离职日期区间 / 审批状态 / 是否已开证明 / 是否已领取）+ 离职类型 / 关键词，可任意组合、可单独使用。
// 常用的放第一行，其余收进「更多筛选」；所有条件都是服务端过滤，分页不会把结果切散。

import { useMemo, useState } from 'react'
import { Button, DatePicker, Input, Select, Space, Tag } from 'antd'
import { DownOutlined, SearchOutlined, UpOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import type { DepartureLedgerFilterOptions, DepartureLedgerFilters } from '@/types/hr'
import { useDebouncedCallback } from '@/hooks/hr'

type Range = [Dayjs | null, Dayjs | null] | null

const toOptions = (values?: string[]) => (values || []).map((value) => ({ value, label: value }))
/** 选项不多不少、希望一屏看全的下拉用这个高度（约 10 行） */
const LIST_HEIGHT_FULL = 440
const isActive = (value: unknown) => value !== undefined && value !== null && value !== ''

/** 「更多筛选」里的条件：有任何一项生效时，这一行始终展开，不让已生效的条件藏着看不见 */
const MORE_KEYS = [
  'position', 'offboarding_reason', 'gender', 'education', 'employee_category',
  'approval_status', 'cert_issued', 'cert_signed',
] as const

function countActiveFilters(filters: DepartureLedgerFilters): number {
  return Object.values(filters).filter((value) => isActive(value)).length
}

export default function DepartureFilterBar({
  filters,
  keywordInput,
  onKeywordInput,
  options,
  onChange,
  onClear,
}: {
  filters: DepartureLedgerFilters
  /** 关键词输入框的即时值由父组件持有：输入框直接受控于防抖后的查询条件会「吃字」 */
  keywordInput: string
  onKeywordInput: (value: string) => void
  options: DepartureLedgerFilterOptions
  onChange: (patch: Partial<DepartureLedgerFilters>) => void
  onClear: () => void
}) {
  const [moreOpen, setMoreOpen] = useState(false)
  // 防抖 300ms 后才把关键词写进查询条件（每敲一个字发一次请求）
  const { run: debouncedKeyword } = useDebouncedCallback((value: string) => {
    onChange({ keyword: value.trim() || undefined })
  }, 300)

  const range = useMemo<Range>(
    () => {
      const from = filters.offboarding_date_from ? dayjs(filters.offboarding_date_from) : null
      const to = filters.offboarding_date_to ? dayjs(filters.offboarding_date_to) : null
      return from || to ? [from, to] : null
    },
    [filters.offboarding_date_from, filters.offboarding_date_to],
  )

  const moreActiveCount = MORE_KEYS.filter((key) => isActive(filters[key])).length
  const activeCount = countActiveFilters(filters)
  const showMore = moreOpen || moreActiveCount > 0

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="搜索姓名 / 工号 / 部门 / 职位"
          value={keywordInput}
          onChange={(e) => {
            onKeywordInput(e.target.value)
            debouncedKeyword(e.target.value)
          }}
          prefix={<SearchOutlined />}
          // antd 输入框自带 width:100%，宽度须走 style
          style={{ width: 230 }}
          allowClear
        />
        <Select
          placeholder="部门"
          value={filters.department}
          onChange={(value) => onChange({ department: value || undefined })}
          showSearch
          allowClear
          optionFilterProp="label"
          style={{ width: 170 }}
          options={toOptions(options.departments)}
        />
        <Select
          placeholder="离职类型"
          value={filters.offboarding_type}
          onChange={(value) => onChange({ offboarding_type: value || undefined })}
          showSearch
          allowClear
          optionFilterProp="label"
          style={{ width: 140 }}
          options={toOptions(options.offboarding_types)}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(value) => {
            onChange({
              offboarding_date_from: value?.[0]?.format('YYYY-MM-DD') || undefined,
              offboarding_date_to: value?.[1]?.format('YYYY-MM-DD') || undefined,
            })
          }}
          allowClear
        />
        <Button
          icon={moreOpen ? <UpOutlined /> : <DownOutlined />}
          onClick={() => setMoreOpen((v) => !v)}
        >
          更多筛选{moreActiveCount ? `（${moreActiveCount}）` : ''}
        </Button>
        {activeCount > 0 && (
          <Space size={4}>
            <Tag color="processing">已设 {activeCount} 项条件</Tag>
            <Button type="link" size="small" onClick={onClear}>
              清除筛选
            </Button>
          </Space>
        )}
      </div>

      {showMore && (
        <div className="flex flex-wrap items-center gap-3 rounded-[var(--rounded-lg)] bg-[var(--color-surface)] p-3">
          <Select
            placeholder="岗位"
            value={filters.position}
            onChange={(value) => onChange({ position: value || undefined })}
            showSearch
            allowClear
            optionFilterProp="label"
            style={{ width: 150 }}
            options={toOptions(options.positions)}
          />
          <Select
            placeholder="离职原因"
            value={filters.offboarding_reason}
            onChange={(value) => onChange({ offboarding_reason: value || undefined })}
            showSearch
            allowClear
            optionFilterProp="label"
            style={{ width: 170 }}
            options={toOptions(options.offboarding_reasons)}
          />
          <Select
            placeholder="性别"
            value={filters.gender}
            onChange={(value) => onChange({ gender: value || undefined })}
            allowClear
            style={{ width: 100 }}
            options={toOptions(options.genders)}
          />
          <Select
            placeholder="学历"
            value={filters.education}
            onChange={(value) => onChange({ education: value || undefined })}
            showSearch
            allowClear
            optionFilterProp="label"
            style={{ width: 130 }}
            options={toOptions(options.educations)}
          />
          <Select
            placeholder="用工类型"
            value={filters.employee_category}
            onChange={(value) => onChange({ employee_category: value || undefined })}
            showSearch
            allowClear
            optionFilterProp="label"
            style={{ width: 150 }}
            options={toOptions(options.employee_categories)}
          />
          <Select
            placeholder="办理状态"
            value={filters.approval_status}
            onChange={(value) => onChange({ approval_status: value || undefined })}
            allowClear
            showSearch
            optionFilterProp="label"
            // 9 个固定选项；本设计体系行高约 44px，默认 256px 的列表放不下，要滚动才能看到「已办结」
            listHeight={LIST_HEIGHT_FULL}
            style={{ width: 150 }}
            options={options.approval_statuses}
          />
          <Select
            placeholder="是否已开证明"
            value={filters.cert_issued === undefined ? undefined : String(filters.cert_issued)}
            onChange={(value) =>
              onChange({ cert_issued: value === undefined || value === '' ? undefined : value === 'true' })
            }
            allowClear
            style={{ width: 150 }}
            options={[
              { value: 'true', label: '已开具' },
              { value: 'false', label: '未开具' },
            ]}
          />
          <Select
            placeholder="是否已领取"
            value={filters.cert_signed === undefined ? undefined : String(filters.cert_signed)}
            onChange={(value) =>
              onChange({ cert_signed: value === undefined || value === '' ? undefined : value === 'true' })
            }
            allowClear
            style={{ width: 150 }}
            options={[
              { value: 'true', label: '已签收' },
              { value: 'false', label: '未签收' },
            ]}
          />
        </div>
      )}
    </div>
  )
}
