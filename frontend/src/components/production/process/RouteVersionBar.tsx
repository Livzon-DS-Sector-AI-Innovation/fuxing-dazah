'use client'

import { useState } from 'react'
import { App, Button, Input, Modal, Popconfirm, Space, Tag } from 'antd'
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

const STATUS_META: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  published: { color: 'green', label: '已发布' },
  archived: { color: 'default', label: '已归档' },
}

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
  const [nameModal, setNameModal] = useState<NameModalAction | null>(null)
  const [nameValue, setNameValue] = useState('')

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
      run(() => copyRoute(current!.id, name), '已复制新路线')
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
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 8,
      }}
    >
      <Space size={4} wrap>
        {routes.map(r => (
          <Tag.CheckableTag
            key={r.id}
            checked={r.id === currentRouteId}
            onChange={() => onSelect(r.id)}
          >
            {r.route_name}
            <Tag
              color={STATUS_META[r.status]?.color}
              style={{ marginLeft: 4, marginRight: 0 }}
            >
              {STATUS_META[r.status]?.label}
            </Tag>
          </Tag.CheckableTag>
        ))}
      </Space>
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
      </Modal>
    </div>
  )
}
