'use client'

// 离职台账「保存视图」：把常用筛选条件（连同导出字段）存成个人视图，一键调用。
// 视图只属于创建人；同一人只保留一个默认视图，进入页面时自动套用。
// 筛选条件被改动后，当前视图旁会标「已修改」，提示可以覆盖更新或另存。

import { useState } from 'react'
import {
  App as AntdApp, Button, Checkbox, Input, Modal, Popconfirm, Select, Space, Table, Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, SettingOutlined, StarFilled } from '@ant-design/icons'
import type { DepartureSavedView } from '@/types/hr'

export default function DepartureViewControls({
  views,
  activeViewId,
  dirty,
  filterCount,
  columnCount,
  saving,
  onApply,
  onSave,
  onRename,
  onDelete,
  onSetDefault,
}: {
  views: DepartureSavedView[]
  activeViewId: string | null
  /** 当前筛选与所选视图不一致 */
  dirty: boolean
  /** 当前生效的筛选条件数 / 导出字段数（存视图时一并保存） */
  filterCount: number
  columnCount: number
  saving: boolean
  onApply: (view: DepartureSavedView | null) => void
  onSave: (input: { name: string; isDefault: boolean; overwrite: boolean }) => Promise<void>
  onRename: (view: DepartureSavedView, name: string) => Promise<void>
  onDelete: (view: DepartureSavedView) => Promise<void>
  onSetDefault: (view: DepartureSavedView) => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState('')
  const [asDefault, setAsDefault] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [renaming, setRenaming] = useState<DepartureSavedView | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const activeView = views.find((view) => view.id === activeViewId) ?? null

  const openSave = () => {
    setName(activeView && dirty ? `${activeView.name}（修改）` : '')
    setAsDefault(activeView?.is_default ?? false)
    setSaveOpen(true)
  }

  const submitSave = async (overwrite: boolean) => {
    const trimmed = name.trim()
    if (!overwrite && !trimmed) {
      message.warning('请填写视图名称')
      return
    }
    await onSave({ name: overwrite && activeView ? activeView.name : trimmed, isDefault: asDefault, overwrite })
    setSaveOpen(false)
  }

  const submitRename = async () => {
    if (!renaming) return
    const trimmed = renameValue.trim()
    if (!trimmed) {
      message.warning('请填写视图名称')
      return
    }
    await onRename(renaming, trimmed)
    setRenaming(null)
  }

  const columns: ColumnsType<DepartureSavedView> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (value: string, row) => (
        <Space size={4}>
          <span>{value}</span>
          {row.is_default && <StarFilled className="text-[var(--color-warning)]" aria-label="默认视图" />}
        </Space>
      ),
    },
    { title: '筛选条件', key: 'filters', width: 100, render: (_v: unknown, row) => `${Object.values(row.filters || {}).filter(Boolean).length} 项` },
    { title: '导出字段', key: 'columns', width: 100, render: (_v: unknown, row) => (row.columns?.length ? `${row.columns.length} 个` : '未保存') },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_v: unknown, row) => (
        <Space size="small">
          {!row.is_default && (
            <Button type="link" size="small" onClick={() => void onSetDefault(row)}>
              设为默认
            </Button>
          )}
          <Button
            type="link"
            size="small"
            onClick={() => {
              setRenaming(row)
              setRenameValue(row.name)
            }}
          >
            重命名
          </Button>
          <Popconfirm title={`删除视图「${row.name}」？`} okText="删除" cancelText="取消" onConfirm={() => void onDelete(row)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space size={8} wrap>
        <Select
          placeholder="我的视图"
          value={activeViewId ?? undefined}
          // 用 onSelect 而不是 onChange：筛选被改过后，用户会点回「当前已选中的视图」想重新套用，
          // 而再点同一项不会触发 onChange（实测：条件没还原）
          onSelect={(value) => onApply(views.find((view) => view.id === value) ?? null)}
          allowClear
          onClear={() => onApply(null)}
          style={{ width: 190 }}
          options={views.map((view) => ({
            value: view.id,
            label: view.is_default ? `${view.name}（默认）` : view.name,
          }))}
        />
        {dirty && activeView && <Tag color="warning">已修改</Tag>}
        <Button icon={<PlusOutlined />} onClick={openSave}>
          存为视图
        </Button>
        {views.length > 0 && (
          <Button icon={<SettingOutlined />} aria-label="管理视图" onClick={() => setManageOpen(true)} />
        )}
      </Space>

      <Modal
        open={saveOpen}
        title="保存为视图"
        onCancel={() => setSaveOpen(false)}
        destroyOnHidden
        width={460}
        footer={
          <Space wrap>
            <Button onClick={() => setSaveOpen(false)}>取消</Button>
            {activeView && (
              <Button loading={saving} disabled={!dirty} onClick={() => void submitSave(true)}>
                覆盖更新「{activeView.name}」
              </Button>
            )}
            <Button type="primary" loading={saving} onClick={() => void submitSave(false)}>
              另存为新视图
            </Button>
          </Space>
        }
      >
        <div className="space-y-3 pt-2">
          <div className="text-[13px] text-[var(--color-slate)]">
            将保存当前的 <b>{filterCount}</b> 项筛选条件和 <b>{columnCount}</b> 个导出字段，之后一键套用。
          </div>
          <div>
            <div className="mb-1 text-[13px] text-[var(--color-ink)]">视图名称</div>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={64}
              placeholder={activeView && dirty ? '留空则沿用原名' : '如：本月辞职·未开证明'}
              onPressEnter={() => void submitSave(false)}
            />
          </div>
          <Checkbox checked={asDefault} onChange={(e) => setAsDefault(e.target.checked)}>
            设为我的默认视图（进入离职台账时自动套用）
          </Checkbox>
        </div>
      </Modal>

      <Modal
        open={manageOpen}
        title="管理我的视图"
        onCancel={() => setManageOpen(false)}
        footer={null}
        destroyOnHidden
        width={620}
      >
        <Table<DepartureSavedView>
          size="small"
          rowKey="id"
          columns={columns}
          dataSource={views}
          pagination={false}
        />
      </Modal>

      <Modal
        open={renaming !== null}
        title="重命名视图"
        okText="保存"
        cancelText="取消"
        onOk={() => void submitRename()}
        onCancel={() => setRenaming(null)}
        destroyOnHidden
        width={400}
      >
        <Input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} maxLength={64} />
      </Modal>
    </>
  )
}
