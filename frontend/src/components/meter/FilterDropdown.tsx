'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AutoComplete, Button, Select } from 'antd'

type FetchTypeahead = (q: string) => Promise<{ items: string[]; total: number }>

/** 文本列筛选项本体（稳定组件，避免每次渲染被 antd 重挂载导致输入焦点丢失）。 */
function TextFilterDropdown({
  value,
  onChange,
  placeholder,
  fetchTypeahead,
}: {
  value?: string
  onChange: (v: string | undefined) => void
  placeholder: string
  fetchTypeahead: FetchTypeahead
}) {
  // 首次挂载时以当前筛选项作为初值；此后由用户输入驱动，不随外部 value 回写（避免 focus 抖动）。
  const [text, setText] = useState<string | undefined>(value)
  const [options, setOptions] = useState<string[]>([])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reqRef = useRef(0)

  const loadOptions = useCallback(
    async (q: string) => {
      const req = ++reqRef.current
      const res = await fetchTypeahead(q).catch(() => ({ items: [], total: 0 }))
      if (req === reqRef.current && Array.isArray(res?.items)) setOptions(res.items)
    },
    [fetchTypeahead],
  )

  // 立即应用筛选值：先取消未触发的防抖定时器，避免旧文本晚到覆盖新值/清空结果
  const apply = useCallback(
    (v: string | undefined) => {
      if (timer.current) {
        clearTimeout(timer.current)
        timer.current = null
      }
      onChange(v)
    },
    [onChange],
  )

  const handleSearch = (t: string) => {
    setText(t)
    loadOptions(t)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => apply(t || undefined), 300)
  }

  return (
    <div style={{ padding: 8, minWidth: 240 }}>
      <AutoComplete
        value={text}
        options={options.map(v => ({ value: v }))}
        style={{ width: '100%' }}
        placeholder={placeholder}
        allowClear
        showSearch
        onSearch={handleSearch}
        onSelect={(t) => {
          setText(t)
          apply(t)
        }}
        onChange={(t) => {
          const val = t as string | undefined
          setText(val)
          if (!val) apply(undefined)
        }}
        filterOption={(input, option) =>
          (option?.value as string)?.toLowerCase().includes(input.toLowerCase())
        }
      />
      {text && (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setText(undefined)
              apply(undefined)
            }}
          >
            重置
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * 文本列筛选项：输入即过滤（部分匹配）+ 远程 typeahead 建议。
 * 返回 antd Table `filterDropdown` 的渲染函数。
 */
export function renderTextFilterDropdown(opts: {
  value?: string
  onChange: (v: string | undefined) => void
  field: string
  placeholder: string
  fetchTypeahead: FetchTypeahead
}) {
  const { value, onChange, field, placeholder, fetchTypeahead } = opts

  const TextFilterRender = (): ReactNode => (
    <TextFilterDropdown
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      fetchTypeahead={fetchTypeahead}
    />
  )
  TextFilterRender.displayName = `TextFilter_${field}`
  return TextFilterRender
}

/** 分类列筛选项本体（部门/状态等低基数，打开时按需取 distinct，避免全量预载）。 */
function MultiSelectFilterDropdown({
  value,
  onChange,
  placeholder,
  fetchOptions,
}: {
  value?: string
  onChange: (v: string | undefined) => void
  placeholder: string
  fetchOptions: () => Promise<string[]>
}) {
  const [options, setOptions] = useState<string[]>([])

  useEffect(() => {
    let alive = true
    fetchOptions()
      .then(o => {
        if (alive) setOptions(o)
      })
      .catch(() => {
        if (alive) setOptions([])
      })
    return () => {
      alive = false
    }
  }, [fetchOptions])

  const selectedArr = value ? value.split(',').filter(Boolean) : []

  return (
    <div style={{ padding: 8, minWidth: 220 }}>
      <Select
        mode="multiple"
        allowClear
        showSearch
        placeholder={placeholder}
        value={selectedArr}
        onChange={(values) => {
          const arr = values as string[]
          onChange(arr.length > 0 ? arr.join(',') : undefined)
        }}
        options={options.map(v => ({ label: v, value: v }))}
        filterOption={(input, option) =>
          (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
        }
        style={{ width: '100%' }}
        maxTagCount="responsive"
      />
    </div>
  )
}

/**
 * 分类列筛选项：多选精确 IN，选项按需拉取。
 * 返回 antd Table `filterDropdown` 的渲染函数。
 */
export function renderMultiSelectFilterDropdown(opts: {
  value?: string
  onChange: (v: string | undefined) => void
  field: string
  placeholder: string
  fetchOptions: () => Promise<string[]>
}) {
  const { value, onChange, field, placeholder, fetchOptions } = opts

  const MultiSelectRender = (): ReactNode => (
    <MultiSelectFilterDropdown
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      fetchOptions={fetchOptions}
    />
  )
  MultiSelectRender.displayName = `MultiSelectFilter_${field}`
  return MultiSelectRender
}
