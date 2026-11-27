'use client'

/**
 * 员工档案列头筛选：把字段级筛选条件直接装到表格列头上（filterDropdown，选择即生效）。
 * 取代此前的折叠筛选面板——列在哪筛选就在哪，不再单独占一块卡片。
 *
 * 实现要点：
 * - 数据是服务端分页，因此不走 antd 的本地筛选（不提供 onFilter），只用受控 filteredValue
 *   驱动列头图标高亮；筛选值本体仍是 EmployeeFieldFilters（列表查询与 Excel 导出共用口径）。
 * - 下拉控件直接绑定外部筛选值（不经过 antd 的 selectedKeys/confirm），onChange 即提交。
 * - 可枚举字段 → 下拉（选项由后端聚合现有数据，跟随飞书源表变化）；日期 → 范围选择；
 *   年龄 → 数字区间；域账号/离职原因 → 文本（防抖，失焦/回车立即生效——筛选弹层关闭会卸载
 *   内容并取消防抖，仅靠防抖会丢输入）。
 * - 活跃筛选以标签行呈现在工具栏下方：被列设置隐藏的列若带筛选，仍可见、可单独清除。
 */

import { useState } from 'react'
import { Button, DatePicker, Input, InputNumber, Select, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { Employee, EmployeeFieldFilters, EmployeeFilterOptions } from '@/types/hr'
import { useDebouncedCallback } from '@/hooks/hr'

type FilterKind = 'select' | 'text' | 'age' | 'yearRange' | 'dateRange'

/** 一个可筛选列的规格：筛选字段（EmployeeFieldFilters 的 key）对应到表格列 key（columns.tsx） */
interface ColumnFilterSpec {
  fields: (keyof EmployeeFieldFilters)[]
  columnKey: string
  label: string
  kind: FilterKind
  /** select 类对应的聚合选项 key（默认取 fields[0]） */
  optionKey?: keyof EmployeeFilterOptions
  /** text 类占位提示 */
  placeholder?: string
}

// 顺序即「活跃筛选」标签行的展示顺序；列 key 与 employee/columns.tsx 保持一致
const COLUMN_FILTER_SPECS: ColumnFilterSpec[] = [
  { fields: ['position'], columnKey: 'position', label: '岗位', kind: 'select' },
  { fields: ['duty'], columnKey: 'duty', label: '职务', kind: 'select' },
  { fields: ['job_category'], columnKey: 'job_category', label: '职能分类', kind: 'select' },
  { fields: ['level'], columnKey: 'level', label: '职级', kind: 'select' },
  { fields: ['report_grade'], columnKey: 'report_grade', label: '岗位职级', kind: 'select' },
  { fields: ['status_category'], columnKey: 'status_category', label: '员工性质', kind: 'select' },
  { fields: ['gender'], columnKey: 'gender', label: '性别', kind: 'select' },
  { fields: ['ethnicity'], columnKey: 'ethnicity', label: '民族', kind: 'select' },
  { fields: ['native_place'], columnKey: 'native_place', label: '籍贯', kind: 'select' },
  { fields: ['marital_status'], columnKey: 'marital_status', label: '婚姻状况', kind: 'select' },
  { fields: ['household_type'], columnKey: 'household_type', label: '户口类型', kind: 'select' },
  { fields: ['education'], columnKey: 'education', label: '学历', kind: 'select' },
  { fields: ['degree_type'], columnKey: 'degree_type', label: '学位类型', kind: 'select' },
  { fields: ['classification'], columnKey: 'classification', label: '学习形式', kind: 'select' },
  { fields: ['school'], columnKey: 'school', label: '毕业院校', kind: 'select' },
  { fields: ['major'], columnKey: 'major', label: '专业', kind: 'select' },
  { fields: ['hr_analysis'], columnKey: 'hr_analysis', label: '人力资源分析', kind: 'select' },
  { fields: ['domain_account'], columnKey: 'domain_account', label: '域账号', kind: 'text', placeholder: '前缀匹配' },
  { fields: ['departure_reason'], columnKey: 'departure_reason', label: '离职原因', kind: 'text', placeholder: '包含匹配' },
  { fields: ['age_min', 'age_max'], columnKey: 'age', label: '年龄', kind: 'age' },
  { fields: ['birth_year'], columnKey: 'birth_date', label: '出生年份', kind: 'yearRange' },
  { fields: ['graduation_date'], columnKey: 'graduation_date', label: '毕业时间', kind: 'dateRange' },
  { fields: ['work_start_date'], columnKey: 'work_start_date', label: '参加工作时间', kind: 'dateRange' },
  { fields: ['hire_date'], columnKey: 'hire_date', label: '入职日期', kind: 'dateRange' },
  { fields: ['departure_date'], columnKey: 'departure_date', label: '离职日期', kind: 'dateRange' },
  { fields: ['contract_start_date'], columnKey: 'contract_start_date', label: '合同开始日期', kind: 'dateRange' },
  { fields: ['contract_end_date'], columnKey: 'contract_end_date', label: '合同结束日期', kind: 'dateRange' },
]

export interface ColumnFilterContext {
  options: EmployeeFilterOptions
  filters: EmployeeFieldFilters
  onChange: (next: EmployeeFieldFilters) => void
}

/** 已启用筛选项数（年龄 min/max 合并计 1 项） */
export function countActiveFilters(filters: EmployeeFieldFilters): number {
  const hasValue = (v: unknown) => v !== undefined && v !== '' && v !== null
  const specs = new Set(
    COLUMN_FILTER_SPECS
      .filter((s) => s.fields.some((f) => hasValue(filters[f])))
      .map((s) => s.columnKey),
  )
  return specs.size
}

/** 合并筛选补丁：值为 undefined/null/'' 视为清除该字段 */
function patchFilters(prev: EmployeeFieldFilters, patch: EmployeeFieldFilters): EmployeeFieldFilters {
  const next = { ...prev } as Record<string, unknown>
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined || v === null || v === '') delete next[k]
    else next[k] = v
  }
  return next as EmployeeFieldFilters
}

/** 该列的受控 filteredValue：仅用于图标高亮，不参与本地过滤 */
function activeFilteredValue(spec: ColumnFilterSpec, filters: EmployeeFieldFilters): string[] {
  if (spec.kind === 'age') {
    return filters.age_min != null || filters.age_max != null
      ? [`${filters.age_min ?? ''}~${filters.age_max ?? ''}`]
      : []
  }
  if (spec.kind === 'yearRange') {
    return filters.birth_year ? [filters.birth_year.join('~')] : []
  }
  const v = filters[spec.fields[0]]
  return v ? [String(v)] : []
}

// ── 各类型筛选弹层 ──────────────────────────────────────────────
// 弹层控件直接绑定外部筛选值：onChange 即提交。onCommit 接收「补丁」，不碰其它字段。

function SelectFilterBody({ spec, ctx, close }: { spec: ColumnFilterSpec; ctx: ColumnFilterContext; close: () => void }) {
  const field = spec.fields[0]
  const optionKey = spec.optionKey ?? (field as keyof EmployeeFilterOptions)
  const value = ctx.filters[field] as string | undefined
  return (
    <div className="p-2" style={{ width: 240 }}>
      <Select
        className="w-full"
        value={value}
        placeholder="全部"
        allowClear
        showSearch
        optionFilterProp="label"
        aria-label={`筛选${spec.label}`}
        options={(ctx.options[optionKey] || []).map((v) => ({ value: v, label: v }))}
        onChange={(v) => {
          ctx.onChange(patchFilters(ctx.filters, { [field]: v }) as EmployeeFieldFilters)
          close()
        }}
      />
    </div>
  )
}

function TextFilterBody({ spec, ctx }: { spec: ColumnFilterSpec; ctx: ColumnFilterContext }) {
  const field = spec.fields[0]
  // 本地即时回显，提交走防抖；卸载会取消未触发的防抖（hooks），因此失焦/回车兜底立即提交。
  // 打字过程中不做「外部值→本地」回同步：防抖窗口内旧值晚到会把输入弹回（吃字），
  // 重开弹层时 useState 初始值自然恢复成已提交值。
  const [text, setText] = useState((ctx.filters[field] as string | undefined) ?? '')
  const { run: debouncedCommit, cancel: cancelCommit } = useDebouncedCallback(
    (v: string) => ctx.onChange(patchFilters(ctx.filters, { [field]: v || undefined }) as EmployeeFieldFilters),
    300,
  )
  const flush = (v: string) => {
    cancelCommit()
    ctx.onChange(patchFilters(ctx.filters, { [field]: v.trim() || undefined }) as EmployeeFieldFilters)
  }
  return (
    <div className="p-2" style={{ width: 240 }}>
      <Input
        value={text}
        placeholder={spec.placeholder}
        aria-label={`筛选${spec.label}`}
        allowClear
        onChange={(e) => {
          const v = e.target.value
          setText(v)
          debouncedCommit(v.trim())
        }}
        onPressEnter={() => flush(text)}
        onBlur={() => flush(text)}
      />
    </div>
  )
}

function AgeFilterBody({ ctx }: { ctx: ColumnFilterContext }) {
  // 与旧面板一致：数字改动即时生效（age_min/age_max 各自独立，互不覆盖）
  const commit = (key: 'age_min' | 'age_max', v: number | null) => {
    ctx.onChange(patchFilters(ctx.filters, { [key]: v ?? undefined }) as EmployeeFieldFilters)
  }
  return (
    <div className="p-2">
      <div className="flex items-center gap-1">
        <InputNumber
          value={ctx.filters.age_min ?? undefined}
          min={0}
          placeholder="最小"
          aria-label="筛选年龄最小值"
          style={{ width: 80 }}
          onChange={(v) => commit('age_min', typeof v === 'number' ? v : null)}
        />
        <span className="text-[var(--color-steel)]">~</span>
        <InputNumber
          value={ctx.filters.age_max ?? undefined}
          min={0}
          placeholder="最大"
          aria-label="筛选年龄最大值"
          style={{ width: 80 }}
          onChange={(v) => commit('age_max', typeof v === 'number' ? v : null)}
        />
        <span className="text-xs text-[var(--color-stone)]">岁</span>
      </div>
    </div>
  )
}

function YearRangeFilterBody({ ctx }: { ctx: ColumnFilterContext }) {
  const value = ctx.filters.birth_year
  const controlled: [Dayjs, Dayjs] | undefined = value
    ? [dayjs(`${value[0]}-01-01`), dayjs(`${value[1]}-01-01`)]
    : undefined
  return (
    <div className="p-2">
      <DatePicker.RangePicker
        picker="year"
        allowEmpty={[true, true]}
        aria-label="筛选出生年份"
        value={controlled}
        onChange={(_, dateStrings) => {
          const from = Number.parseInt(dateStrings[0], 10)
          const to = Number.parseInt(dateStrings[1], 10)
          if (Number.isFinite(from) && Number.isFinite(to)) {
            ctx.onChange(patchFilters(ctx.filters, { birth_year: [from, to] }) as EmployeeFieldFilters)
          } else {
            ctx.onChange(patchFilters(ctx.filters, { birth_year: undefined }) as EmployeeFieldFilters)
          }
        }}
      />
    </div>
  )
}

function DateRangeFilterBody({ spec, ctx }: { spec: ColumnFilterSpec; ctx: ColumnFilterContext }) {
  const field = spec.fields[0]
  const value = ctx.filters[field] as [string, string] | undefined
  const controlled: [Dayjs, Dayjs] | undefined = value
    ? [dayjs(value[0]), dayjs(value[1])]
    : undefined
  return (
    <div className="p-2">
      <DatePicker.RangePicker
        allowEmpty={[true, true]}
        aria-label={`筛选${spec.label}`}
        value={controlled}
        onChange={(_, dateStrings) => {
          if (dateStrings[0] && dateStrings[1]) {
            ctx.onChange(patchFilters(ctx.filters, { [field]: [dateStrings[0], dateStrings[1]] }) as EmployeeFieldFilters)
          } else {
            ctx.onChange(patchFilters(ctx.filters, { [field]: undefined }) as EmployeeFieldFilters)
          }
        }}
      />
    </div>
  )
}

function renderFilterBody(spec: ColumnFilterSpec, ctx: ColumnFilterContext, close: () => void) {
  switch (spec.kind) {
    case 'select': return <SelectFilterBody spec={spec} ctx={ctx} close={close} />
    case 'text': return <TextFilterBody spec={spec} ctx={ctx} />
    case 'age': return <AgeFilterBody ctx={ctx} />
    case 'yearRange': return <YearRangeFilterBody ctx={ctx} />
    case 'dateRange': return <DateRangeFilterBody spec={spec} ctx={ctx} />
  }
}

/** 给列装配筛选：按列 key 匹配规格，附上受控 filteredValue 与自定义筛选弹层 */
export function applyColumnFilters(columns: ColumnsType<Employee>, ctx: ColumnFilterContext): ColumnsType<Employee> {
  const byColumn = new Map(COLUMN_FILTER_SPECS.map((s) => [s.columnKey, s]))
  return columns.map((col) => {
    const spec = byColumn.get(col.key as string)
    if (!spec) return col
    return {
      // 筛选图标会挤占列头：窄列按标题长度抬高宽度，避免「学历」折行、「员工性质」截断
      ...ensureHeaderWidth(col),
      filteredValue: activeFilteredValue(spec, ctx.filters),
      filterDropdown: ({ close }: { close: () => void }) => renderFilterBody(spec, ctx, close),
    }
  })
}

// 图标 16 + 间隙 + 列头左右 padding 的经验值（antd 默认 16px 字号下 CJK 字宽≈14px）
const FILTER_ICON_SPACE = 52
function ensureHeaderWidth(col: ColumnsType<Employee>[number]): ColumnsType<Employee>[number] {
  if (typeof col.width !== 'number') return col
  const need = [...String(col.title)].length * 14 + FILTER_ICON_SPACE
  return need > col.width ? { ...col, width: need } : col
}

// ── 活跃筛选标签行 ──────────────────────────────────────────────
// 列头图标只在列可见时看得见；被列设置隐藏的列若带筛选，靠这行可见、可单独清除。

interface ActiveFilterChip {
  key: string
  label: string
  text: string
}

function buildActiveChips(filters: EmployeeFieldFilters): ActiveFilterChip[] {
  const chips: ActiveFilterChip[] = []
  for (const spec of COLUMN_FILTER_SPECS) {
    if (spec.kind === 'age') {
      const { age_min: min, age_max: max } = filters
      if (min == null && max == null) continue
      const text = min != null && max != null ? `${min}~${max} 岁` : min != null ? `≥ ${min} 岁` : `≤ ${max} 岁`
      chips.push({ key: spec.columnKey, label: spec.label, text })
    } else if (spec.kind === 'yearRange') {
      if (!filters.birth_year) continue
      chips.push({
        key: spec.columnKey, label: spec.label,
        text: `${filters.birth_year[0]}~${filters.birth_year[1]} 年`,
      })
    } else if (spec.kind === 'dateRange') {
      const v = filters[spec.fields[0]] as [string, string] | undefined
      if (!v) continue
      chips.push({ key: spec.columnKey, label: spec.label, text: `${v[0]} ~ ${v[1]}` })
    } else {
      const v = filters[spec.fields[0]] as string | undefined
      if (!v) continue
      chips.push({ key: spec.columnKey, label: spec.label, text: v })
    }
  }
  return chips
}

export function ActiveFilterChips({ filters, onChange }: {
  filters: EmployeeFieldFilters
  onChange: (next: EmployeeFieldFilters) => void
}) {
  const chips = buildActiveChips(filters)
  if (!chips.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-[var(--color-stone)]">筛选条件：</span>
      {chips.map((chip) => (
        <Tag
          key={chip.key}
          closable
          onClose={(e) => { e.preventDefault(); onChange(patchFilters(filters, clearFieldsOf(chip.key))) }}
        >
          <span className="text-[var(--color-stone)]">{chip.label}：</span>
          <span
            className="inline-block max-w-40 align-bottom overflow-hidden whitespace-nowrap text-ellipsis"
            title={chip.text}
          >
            {chip.text}
          </span>
        </Tag>
      ))}
      <Button type="link" size="small" className="px-0" onClick={() => onChange({})}>
        清空
      </Button>
    </div>
  )
}

// 按列 key 反查该 chip 要清除的筛选字段（chips 由 COLUMN_FILTER_SPECS 派生，必然命中）
function clearFieldsOf(columnKey: string): EmployeeFieldFilters {
  const spec = COLUMN_FILTER_SPECS.find((s) => s.columnKey === columnKey)
  return Object.fromEntries((spec?.fields ?? []).map((f) => [f, undefined])) as EmployeeFieldFilters
}
