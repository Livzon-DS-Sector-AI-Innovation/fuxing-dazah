'use client'

// 导出 Excel 的字段勾选弹窗（需求「导出字段可勾选，不必整表带出」）。
// 字段清单来自后端注册表（EXPORT_COLUMNS），按需求「离职人员台账」分五组；
// 每次导出后端都会写一条导出留痕。

import { useMemo, useState } from 'react'
import { Button, Checkbox, Empty, Input, Modal, Space, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { DepartureExportColumn } from '@/types/hr'

const GROUP_ORDER = ['人员信息', '离职信息', '证明信息', '清退与结算', '流程信息']

export default function DepartureExportModal({
  open,
  columns,
  defaultKeys,
  selected,
  onChange,
  loading,
  onClose,
  onExport,
}: {
  open: boolean
  columns: DepartureExportColumn[]
  defaultKeys: string[]
  selected: string[]
  onChange: (next: string[]) => void
  loading: boolean
  onClose: () => void
  onExport: () => void
}) {
  const [query, setQuery] = useState('')

  const grouped = useMemo(() => {
    const map = new Map<string, DepartureExportColumn[]>()
    for (const column of columns) {
      const list = map.get(column.group) ?? []
      list.push(column)
      map.set(column.group, list)
    }
    return [...map.entries()].sort(
      ([a], [b]) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b),
    )
  }, [columns])

  const keyword = query.trim()
  const visible = grouped.map(([group, list]) => [
    group,
    keyword ? list.filter((column) => column.label.includes(keyword) || column.key.includes(keyword)) : list,
  ] as const).filter(([, list]) => list.length > 0)

  const setColumn = (key: string, checked: boolean) =>
    onChange(checked ? [...selected, key] : selected.filter((item) => item !== key))

  const setGroup = (keys: string[], checked: boolean) => {
    const owned = new Set(keys)
    const kept = selected.filter((item) => !owned.has(item))
    onChange(checked ? [...kept, ...keys] : kept)
  }

  return (
    <Modal
      open={open}
      title="导出 Excel"
      okText={`导出 ${selected.length} 个字段`}
      okButtonProps={{ disabled: selected.length === 0 }}
      cancelText="取消"
      confirmLoading={loading}
      onOk={onExport}
      onCancel={onClose}
      width={720}
      destroyOnHidden
      // 46 个字段比屏幕高：内容区内部滚动，标题和底部按钮始终可见
      styles={{ body: { maxHeight: "62vh", overflowY: "auto", paddingRight: 4 } }}
    >
      <div className="space-y-3 pt-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[13px] text-[var(--color-slate)]">
            按当前筛选条件导出全部匹配记录；身份证号在导出中屏蔽。
          </span>
          <Space wrap>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="查找字段"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ width: 180 }}
            />
            <Button size="small" onClick={() => onChange(defaultKeys)}>
              恢复默认
            </Button>
            <Button size="small" onClick={() => onChange([])}>
              清空
            </Button>
          </Space>
        </div>

        {visible.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的字段" />
        ) : (
          visible.map(([group, list]) => {
            const keys = list.map((column) => column.key)
            const checkedCount = keys.filter((key) => selected.includes(key)).length
            return (
              <div key={group} className="rounded-[var(--rounded-md)] border border-[var(--color-hairline)] p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Checkbox
                    indeterminate={checkedCount > 0 && checkedCount < keys.length}
                    checked={checkedCount === keys.length}
                    onChange={(e) => setGroup(keys, e.target.checked)}
                  >
                    <span className="text-[13px] font-medium text-[var(--color-ink)]">{group}</span>
                  </Checkbox>
                  <Tag className="!mr-0">{checkedCount}/{keys.length}</Tag>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-3">
                  {list.map((column) => (
                    <Checkbox
                      key={column.key}
                      checked={selected.includes(column.key)}
                      onChange={(e) => setColumn(column.key, e.target.checked)}
                    >
                      <span className="text-[13px]">{column.label}</span>
                    </Checkbox>
                  ))}
                </div>
              </div>
            )
          })
        )}
      </div>
    </Modal>
  )
}
