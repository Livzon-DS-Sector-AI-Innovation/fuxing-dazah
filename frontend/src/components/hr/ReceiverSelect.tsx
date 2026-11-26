'use client'

// 提醒接收人选择：远程搜索在职员工，选项显示「姓名（工号 · 部门）」；找不到的人可直接粘贴 open_id。
// 存的是姓名（后端发送时解析成 open_id，同名多人不发送），也允许直接填 open_id。
// 提醒配置卡与离职管理配置卡共用。

import { useRef, useState } from 'react'
import { Select, Spin } from 'antd'
import { fetchEmployeesAction } from '@/actions/hr'
import { useDebouncedCallback } from '@/hooks/hr'

export default function ReceiverSelect({ value, onChange }: { value?: string[]; onChange?: (v: string[]) => void }) {
  const seqRef = useRef(0)
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  const [searching, setSearching] = useState(false)

  const search = async (keyword: string) => {
    const seq = ++seqRef.current
    setSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword: keyword || undefined, page: 1, page_size: 20 })
      if (seq !== seqRef.current) return // 过期响应丢弃
      setOptions(d.data.map(e => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || '-'} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默：保留下拉里的上一次结果 */ }
    finally { if (seq === seqRef.current) setSearching(false) }
  }
  const { run: debouncedSearch } = useDebouncedCallback(search, 300)

  return (
    <Select
      mode="tags"
      showSearch
      allowClear
      filterOption={false}
      tokenSeparators={[',', '，']}
      maxTagCount="responsive"
      style={{ width: '100%' }}
      placeholder="输入姓名搜索在职员工；也可直接粘贴 open_id"
      value={value}
      onChange={onChange}
      onSearch={debouncedSearch}
      onOpenChange={(open) => { if (open && options.length === 0) void search('') }}
      options={options}
      loading={searching}
      notFoundContent={searching ? <Spin size="small" /> : null}
    />
  )
}
