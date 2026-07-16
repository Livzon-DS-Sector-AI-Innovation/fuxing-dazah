'use client'

import { App, Button, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  archiveRoute,
  createRoute,
  deleteRoute,
  newRouteVersion,
  publishRoute,
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

  const run = async (fn: () => Promise<{ success: boolean; error?: string }>, ok: string) => {
    const result = await fn()
    if (result.success) {
      message.success(ok)
      onChanged()
    } else {
      message.error(result.error ?? '操作失败')
    }
  }

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
            V{r.version}
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
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() =>
              run(
                () => createRoute({ product_id: productId, name: '工艺路线' }),
                '已创建 draft 路线',
              )
            }
          >
            新建路线
          </Button>
          {current?.status === 'draft' && !editing && (
            <>
              <Button size="small" type="primary" onClick={onEdit}>
                编辑工艺
              </Button>
              <Button
                size="small"
                onClick={() => run(() => publishRoute(current.id), '已发布')}
              >
                发布
              </Button>
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
              <Button
                size="small"
                onClick={() => run(() => archiveRoute(current.id), '已归档')}
              >
                归档
              </Button>
              <Button
                size="small"
                onClick={() => run(() => newRouteVersion(current.id), '已复制新版本')}
              >
                复制新版本
              </Button>
            </>
          )}
          {current?.status === 'archived' && (
            <Button
              size="small"
              onClick={() => run(() => newRouteVersion(current.id), '已复制新版本')}
            >
              复制新版本
            </Button>
          )}
        </Space>
      )}
    </div>
  )
}
