'use client'

// 档案页工具栏：关键词搜索（防抖）+ 状态筛选。字段级筛选已下沉到表格列头
// （employee/columnFilters），此处不再有筛选面板开关。
// 从 EmployeeProfileClient 拆出；状态本体（keyword/status）仍在页面容器。
// 搜索框显示值由本地 state 即时回显——若直接受控于防抖后的 store 值，防抖窗口内
// 列表响应回来触发重渲染会把 DOM 值弹回旧值（打字/删除吃字，且可能停在带空格中间态）。

import { useState } from 'react'
import { Input, Select } from 'antd'

interface ProfileToolbarProps {
  keyword: string
  /** 输入中：走防抖写入（300ms），避免逐键请求 */
  onKeywordInput: (val: string) => void
  /** 回车/搜索按钮：取消防抖立即提交 */
  onKeywordCommit: (val: string) => void
  status: string
  onStatusChange: (val: string) => void
}

export default function ProfileToolbar({
  keyword,
  onKeywordInput,
  onKeywordCommit,
  status,
  onStatusChange,
}: ProfileToolbarProps) {
  // 本地即时回显；外部值变化（回车提交/跨页恢复/清空）时在渲染期回同步
  // （React 官方 adjust-state-during-render 模式，替代 effect 同步派生 state）
  const [text, setText] = useState(keyword)
  const [prevKeyword, setPrevKeyword] = useState(keyword)
  if (keyword !== prevKeyword) {
    setPrevKeyword(keyword)
    setText(keyword)
  }

  return (
    // 现在位于页面工具栏一行里（左侧是部门下拉、右侧是列设置），左对齐即可
    <div className="flex flex-wrap items-center gap-2">
      <Input.Search
        placeholder="搜索姓名或工号"
        aria-label="搜索姓名或工号"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          onKeywordInput(e.target.value)
        }}
        onSearch={(val) => {
          setText(val)
          onKeywordCommit(val)
        }}
        style={{ width: 220 }}
        allowClear
      />
      <Select
        placeholder="状态筛选"
        aria-label="状态筛选"
        value={status || undefined}
        onChange={(value) => onStatusChange(value || '')}
        allowClear
        style={{ width: 120 }}
        options={[
          { value: '在职', label: '在职' },
          { value: '试用期', label: '试用期' },
          { value: '离职', label: '离职' },
          { value: '待审批', label: '待审批' },
          { value: '病假', label: '病假' },
          { value: '产假', label: '产假' },
          { value: '产假复岗', label: '产假复岗' },
        ]}
      />
    </div>
  )
}
