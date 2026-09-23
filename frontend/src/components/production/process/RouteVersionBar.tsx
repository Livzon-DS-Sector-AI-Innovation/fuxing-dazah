'use client'

import { useState } from 'react'
import { App, Button, Checkbox, Input, Modal, Popconfirm, Select, Space, Tag, Typography } from 'antd'
import type { SelectProps } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  archiveRoute,
  copyRoute,
  createRoute,
  deleteRoute,
  publishRoute,
  renameRoute,
} from '@/actions/production'
import type { ProcessRoute } from '@/types/production'
import styles from './RouteVersionBar.module.css'

const { Text } = Typography

export const STATUS_META: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  published: { color: 'green', label: '已发布' },
  archived: { color: 'default', label: '已归档' },
}

// 下拉分组顺序：在用的在前，历史归档置底
const STATUS_GROUP_ORDER = ['published', 'draft', 'archived'] as const

interface Props {
  productId: string
  routes: ProcessRoute[]
  currentRouteId: string | null
  editing: boolean
  canManage: boolean
  onSelect: (routeId: string) => void
  onChanged: () => void // 触发 routes 重新拉取
  onEdit: () => void
}

type NameModalAction = 'create' | 'copy' | 'rename'

interface CopyOptions {
  copy_assignments: boolean
  copy_suffixes: boolean
  copy_computed_fields: boolean
}

const DEFAULT_COPY_OPTIONS: CopyOptions = {
  copy_assignments: true,
  copy_suffixes: true,
  copy_computed_fields: true,
}

export function RouteVersionBar({
  productId,
  routes,
  currentRouteId,
  editing,
  canManage,
  onSelect,
  onChanged,
  onEdit,
}: Props) {
  const { message } = App.useApp()
  const current = routes.find(r => r.id === currentRouteId) ?? null
  const routeOptions: SelectProps['options'] = STATUS_GROUP_ORDER.map(status => ({
    status,
    list: routes.filter(r => r.status === status),
  }))
    .filter(g => g.list.length > 0)
    .map(g => ({
      label: STATUS_META[g.status]?.label,
      title: STATUS_META[g.status]?.label,
      options: g.list.map(r => ({
        value: r.id,
        label: r.route_name,
      })),
    }))
  const [nameModal, setNameModal] = useState<NameModalAction | null>(null)
  const [nameValue, setNameValue] = useState('')
  const [copyOptions, setCopyOptions] = useState<CopyOptions>(DEFAULT_COPY_OPTIONS)

  const run = async (fn: () => Promise<{ success: boolean; error?: string }>, ok: string) => {
    const result = await fn()
    if (result.success) {
      message.success(ok)
      onChanged()
    } else {
      message.error(result.error ?? '操作失败')
    }
  }

  const openNameModal = (action: NameModalAction) => {
    // create/copy 需输入新产品内唯一名称，预填源名称会在确认时必然撞重名
    setNameValue(action === 'rename' ? current?.route_name ?? '' : '')
    if (action === 'copy') setCopyOptions(DEFAULT_COPY_OPTIONS)
    setNameModal(action)
  }

  const confirmNameModal = () => {
    const name = nameValue.trim()
    if (!name) {
      message.warning('请输入路线名称')
      return
    }
    if (nameModal === 'create') {
      run(() => createRoute({ product_id: productId, route_name: name }), '已创建 draft 路线')
    } else if (nameModal === 'copy') {
      run(() => copyRoute(current!.id, name, copyOptions), '已复制新路线')
    } else if (nameModal === 'rename') {
      run(() => renameRoute(current!.id, name), '已重命名')
    }
    setNameModal(null)
  }

  const nameModalTitle =
    nameModal === 'create'
      ? '新建路线'
      : nameModal === 'copy'
        ? '复制为新路线'
        : '重命名路线'

  return (
    <div className={styles.bar}>
      {routes.length > 0 && (
        <Select
          value={currentRouteId ?? undefined}
          onChange={id => onSelect(id)}
          style={{ width: 300, maxWidth: '100%' }}
          showSearch={{
            filterOption: (input, option) => {
              const r = routes.find(x => x.id === option?.value)
              return !!r && r.route_name.toLowerCase().includes(input.toLowerCase())
            },
          }}
          popupMatchSelectWidth={false}
          labelRender={({ value }) => {
            const r = routes.find(x => x.id === value)
            if (!r) return null
            return (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.route_name}
                </span>
                <Tag color={STATUS_META[r.status]?.color} style={{ marginRight: 0 }}>
                  {STATUS_META[r.status]?.label}
                </Tag>
              </span>
            )
          }}
          options={routeOptions}
        />
      )}
      {canManage && (
        <Space size={8}>
          <Button size="small" icon={<PlusOutlined />} onClick={() => openNameModal('create')}>
            新建路线
          </Button>
          {current && (
            <Button size="small" onClick={() => openNameModal('rename')}>
              重命名
            </Button>
          )}
          {current?.status === 'draft' && !editing && (
            <>
              <Button size="small" type="primary" onClick={onEdit}>
                编辑工艺
              </Button>
              <Popconfirm
                title="确认发布？发布后不可编辑"
                onConfirm={() => run(() => publishRoute(current.id), '已发布')}
              >
                <Button size="small">发布</Button>
              </Popconfirm>
              <Popconfirm
                title="删除该 draft 路线？"
                onConfirm={() => run(() => deleteRoute(current.id), '已删除')}
              >
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            </>
          )}
          {current?.status === 'published' && (
            <>
              <Popconfirm
                title="确认归档？归档后不可用于新建批次"
                onConfirm={() => run(() => archiveRoute(current.id), '已归档')}
              >
                <Button size="small">归档</Button>
              </Popconfirm>
              <Button size="small" onClick={() => openNameModal('copy')}>
                复制为
              </Button>
            </>
          )}
          {current?.status === 'archived' && (
            <Button size="small" onClick={() => openNameModal('copy')}>
              复制为
            </Button>
          )}
        </Space>
      )}
      <Modal
        title={nameModalTitle}
        open={nameModal !== null}
        onOk={confirmNameModal}
        onCancel={() => setNameModal(null)}
        width={400}
      >
        <Input
          placeholder="路线名称，产品内唯一"
          value={nameValue}
          onChange={e => setNameValue(e.target.value)}
          onPressEnter={confirmNameModal}
          autoFocus
        />
        {nameModal === 'copy' && (
          <>
            <Space orientation="vertical" size={4} style={{ display: 'flex', marginTop: 12 }}>
              <Checkbox
                checked={copyOptions.copy_computed_fields}
                onChange={e =>
                  setCopyOptions(o => ({ ...o, copy_computed_fields: e.target.checked }))
                }
              >
                复制路线计算字段
              </Checkbox>
              <Checkbox
                checked={copyOptions.copy_assignments}
                onChange={e => setCopyOptions(o => ({ ...o, copy_assignments: e.target.checked }))}
              >
                复制工段 / 工序负责人
              </Checkbox>
              <Checkbox
                checked={copyOptions.copy_suffixes}
                onChange={e => setCopyOptions(o => ({ ...o, copy_suffixes: e.target.checked }))}
              >
                复制工段批次尾缀
              </Checkbox>
            </Space>
            <Text
              type="secondary"
              style={{ display: 'block', marginTop: 8, fontSize: 12, lineHeight: 1.8 }}
            >
              将完整复制本路线的工序、连线与字段定义（中间体配置固定随带）。新路线视为本路线的后续版本：
              发布后，数据汇总会自动合并本路线及其历代前身的历史批次数据，不会出现数据断层。
              发布前编辑时请保持工序编码不变，否则该工序会被视为新增工序、无法对应历史数据。
              已完成计划单/批次仍锁定在原路线执行，新版本只影响后续新建的计划与批次。
            </Text>
          </>
        )}
      </Modal>
    </div>
  )
}
