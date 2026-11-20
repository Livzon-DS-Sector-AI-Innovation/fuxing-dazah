'use client'

// 档案页 Tab 栏右侧工具栏：关键词搜索（防抖）、状态筛选、字段筛选面板开关（带角标）。
// 从 EmployeeProfileClient 拆出；状态本体（keyword/status/filterOpen）仍在页面容器。

import { Badge, Button, Input, Select } from 'antd'
import { FilterOutlined } from '@ant-design/icons'

interface ProfileToolbarProps {
  keyword: string
  /** 输入中：走防抖写入（300ms），避免逐键请求 */
  onKeywordInput: (val: string) => void
  /** 回车/搜索按钮：取消防抖立即提交 */
  onKeywordCommit: (val: string) => void
  status: string
  onStatusChange: (val: string) => void
  filterCount: number
  onToggleFilter: () => void
}

export default function ProfileToolbar({
  keyword,
  onKeywordInput,
  onKeywordCommit,
  status,
  onStatusChange,
  filterCount,
  onToggleFilter,
}: ProfileToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 pb-1">
      <Input.Search
        placeholder="搜索姓名或工号"
        value={keyword}
        onChange={(e) => onKeywordInput(e.target.value)}
        onSearch={onKeywordCommit}
        style={{ width: 220 }}
        allowClear
      />
      <Select
        placeholder="状态筛选"
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
      <Badge count={filterCount} size="small" offset={[2, -2]}>
        <Button icon={<FilterOutlined />} onClick={onToggleFilter}>
          筛选
        </Button>
      </Badge>
    </div>
  )
}
