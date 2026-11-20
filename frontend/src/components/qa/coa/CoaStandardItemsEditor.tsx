'use client'

import { useState } from 'react'
import { App, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { CoaItemInput, CoaStandardItem } from '@/types/qa'
import {
  CoaItemsEditTable,
  standardItemsToRows,
  toItemRow,
  rowsToItemPayload,
  validateItemRows,
  type CoaItemRow,
} from './CoaItemsEditTable'

/**
 * 标准项目编辑器（含工具行与保存）：表格本体是受控 CoaItemsEditTable，
 * 父组件用 key=standardId 重挂载来重置初始快照。
 */
export function CoaStandardItemsEditor({
  initialItems,
  saving,
  canManage,
  onSave,
}: {
  initialItems: CoaStandardItem[]
  saving: boolean
  canManage: boolean
  onSave: (items: CoaItemInput[]) => Promise<boolean>
}) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<CoaItemRow[]>(() => standardItemsToRows(initialItems))
  const [dirty, setDirty] = useState(false)
  // 最近一次新增的行：表格挂载该行时聚焦中文名输入框（聚焦即滚动定位，长列表不用手动找新行）
  const [focusRowKey, setFocusRowKey] = useState<string | null>(null)

  const touch = (next: CoaItemRow[]) => {
    setRows(next)
    setDirty(true)
  }

  const handleAddRow = () => {
    const row = toItemRow({ name_cn: '', value_type: 'text' })
    touch([...rows, row])
    setFocusRowKey(row.key)
  }

  const handleSave = async () => {
    const problem = validateItemRows(rows)
    if (problem) {
      message.warning(problem)
      return
    }
    if (await onSave(rowsToItemPayload(rows))) setDirty(false)
  }

  return (
    // content-visibility 的 containment 边界：单元格输入突变只重排本区域，
    // 不引发整页 reflow（数据网格 INP 优化，不支持时优雅降级为普通渲染）
    <div
      style={{
        contentVisibility: 'auto',
        containIntrinsicSize: 'auto 1200px auto 520px',
      }}
    >
      {canManage && (
        // 表格工具条：小号按钮贴右，和页面级按钮拉开层级；未保存提示占左侧
        <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
          {dirty && (
            <span style={{ marginInlineEnd: 'auto', fontSize: 12, color: 'var(--color-warning-deep, #d46b08)' }}>
              有未保存的修改
            </span>
          )}
          <Button size="small" icon={<PlusOutlined />} onClick={handleAddRow}>
            新增项目
          </Button>
          <Button size="small" type="primary" loading={saving} disabled={!dirty} onClick={handleSave}>
            保存项目
          </Button>
        </div>
      )}
      <CoaItemsEditTable rows={rows} onChange={touch} editable={canManage} focusRowKey={focusRowKey} />
    </div>
  )
}
