'use client'

import { Suspense, useState } from 'react'
import type { ComponentType, CSSProperties } from 'react'
import {
  App,
  Button,
  ConfigProvider,
  Empty,
  Skeleton,
  Switch,
  Tag,
  Tooltip,
} from 'antd'
import zhCN from 'antd/locale/zh_CN'
import {
  BellOutlined,
  CheckCircleOutlined,
  FileDoneOutlined,
  FlagOutlined,
  RocketOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { antdTheme } from '@/lib/antd-theme'
import { usePermission } from '@/hooks/usePermission'
import {
  fetchNotificationConfigs,
  updateNotificationConfig,
} from '@/actions/production'
import type { ProductionNotificationConfig } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { CARD_STYLE } from '../shared/ProductSidebar'
import { UserSelect } from '@/components/shared/UserSelect'

type NotifyIcon = ComponentType<{ style?: CSSProperties }>

interface NotifyTypeMeta {
  icon: NotifyIcon
  color: string
  triggerLabel?: string
  triggerTone?: 'neutral' | 'warning'
}

const TRIGGER_TAG_STYLE: Record<'neutral' | 'warning', CSSProperties> = {
  neutral: {
    background: '#f6f5f4',
    border: '1px solid #e5e3df',
    color: '#5d5b54',
  },
  warning: {
    background: '#dd5b0014',
    border: '1px solid #dd5b0033',
    color: '#dd5b00',
  },
}

// 与后端 reminder_service.NOTIFICATION_TYPES 保持对齐，未知类型回退灰色铃铛
const NOTIFY_TYPE_META: Record<string, NotifyTypeMeta> = {
  plan_released: {
    icon: FileDoneOutlined,
    color: '#5645d4',
    triggerLabel: '事件触发',
    triggerTone: 'neutral',
  },
  step_completed: {
    icon: CheckCircleOutlined,
    color: '#1aae39',
    triggerLabel: '事件触发',
    triggerTone: 'neutral',
  },
  plan_completed: {
    icon: FlagOutlined,
    color: '#0075de',
    triggerLabel: '事件触发',
    triggerTone: 'neutral',
  },
  batch_start_due: {
    icon: RocketOutlined,
    color: '#dd5b00',
    triggerLabel: '每日 08:31',
    triggerTone: 'warning',
  },
  pending_batches: {
    icon: UnorderedListOutlined,
    color: '#0a1530',
    triggerLabel: '每日 08:31',
    triggerTone: 'warning',
  },
}

const FALLBACK_META: NotifyTypeMeta = { icon: BellOutlined, color: '#787671' }

type ConfigPatch = {
  is_enabled?: boolean
  extra_user_ids?: string[]
}

interface ConfigRowProps {
  record: ProductionNotificationConfig
  saving: boolean
  onSave: (record: ProductionNotificationConfig, patch: ConfigPatch) => void
}

function ConfigRow({ record, saving, onSave }: ConfigRowProps) {
  const meta = NOTIFY_TYPE_META[record.notify_type] ?? FALLBACK_META
  const muted = record.is_enabled ? 1 : 0.5
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        alignItems: 'flex-start',
        padding: '20px 24px',
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: `${meta.color}14`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          opacity: muted,
        }}
      >
        <meta.icon style={{ fontSize: 20, color: meta.color }} />
      </div>
      <div style={{ flex: 1, minWidth: 0, opacity: muted }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: '#1a1a1a',
              lineHeight: '22px',
            }}
          >
            {record.name}
          </span>
          {meta.triggerLabel && (
            <Tag
              style={{
                margin: 0,
                ...TRIGGER_TAG_STYLE[meta.triggerTone ?? 'neutral'],
              }}
            >
              {meta.triggerLabel}
            </Tag>
          )}
        </div>
        <div
          style={{ marginTop: 4, fontSize: 13, lineHeight: 1.6, color: '#787671' }}
        >
          {record.description}
        </div>
      </div>
      <div
        style={{
          width: 340,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#a4a097' }}>额外通知人员</span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: '#5d5b54', marginRight: 8 }}>
            启用
          </span>
          <Switch
            checked={record.is_enabled}
            loading={saving}
            onChange={v => onSave(record, { is_enabled: v })}
          />
        </div>
        <UserSelect
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="选择额外通知人员"
          value={record.extra_user_ids}
          allowClear
          groupSelectedFirst
          maxTagCount="responsive"
          maxTagPlaceholder={omitted => (
            <Tooltip
              styles={{ root: { pointerEvents: 'none' } }}
              title={omitted.map(o => String(o.label ?? '')).join('、')}
            >
              <span style={{ cursor: 'default' }}>+{omitted.length}</span>
            </Tooltip>
          )}
          onChange={v => onSave(record, { extra_user_ids: v as string[] })}
        />
      </div>
    </div>
  )
}

function LoadingRows() {
  return (
    <>
      {Array.from({ length: 5 }, (_, i) => (
        <div
          key={i}
          style={{
            padding: '20px 24px',
            borderTop: i > 0 ? '1px solid #ede9e4' : undefined,
          }}
        >
          <Skeleton
            active
            title={false}
            avatar={{ shape: 'square', size: 44 }}
            paragraph={{ rows: 1, width: ['50%'] }}
          />
        </div>
      ))}
    </>
  )
}

const QUERY_KEY = ['production-notification-configs'] as const

function NotificationConfigContent() {
  const { message } = App.useApp()
  const { hasPermission, isLoaded } = usePermission()
  const canManage = hasPermission('production:notification:manage')
  const queryClient = useQueryClient()
  const [savingType, setSavingType] = useState<string | null>(null)

  const { data: rows, isLoading, isError, refetch } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const r = await fetchNotificationConfigs()
      if (!r.success) throw new Error(r.error)
      return r.data ?? []
    },
  })

  if (isLoaded && !canManage) {
    return (
      <div style={CARD_STYLE}>
        <Empty description="您没有「管理生产通知配置」权限，无法查看此页面" />
      </div>
    )
  }

  const handleSave = async (
    record: ProductionNotificationConfig,
    patch: ConfigPatch,
  ) => {
    const next = {
      is_enabled: patch.is_enabled ?? record.is_enabled,
      extra_user_ids: patch.extra_user_ids ?? record.extra_user_ids,
    }
    // 先乐观写进缓存，失败再回滚，避免网络延迟造成开关回跳
    queryClient.setQueryData<ProductionNotificationConfig[]>(
      QUERY_KEY,
      old =>
        old?.map(r =>
          r.notify_type === record.notify_type ? { ...r, ...next } : r,
        ),
    )
    setSavingType(record.notify_type)
    const result = await updateNotificationConfig(record.notify_type, next)
    setSavingType(null)
    if (result.success) {
      message.success(`已更新「${record.name}」配置`)
      queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    } else {
      message.error(result.error)
      // 只回滚失败行：整数组快照回滚会覆盖期间其他行已提交的保存
      queryClient.setQueryData<ProductionNotificationConfig[]>(
        QUERY_KEY,
        old =>
          old?.map(r =>
            r.notify_type === record.notify_type ? { ...r, ...record } : r,
          ),
      )
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: '#1a1a1a' }}>
          通知配置
        </h2>
        <div style={{ marginTop: 6, fontSize: 14, color: '#787671' }}>
          各类飞书通知的触发时机与默认接收人见下方说明，可按需启停；额外通知人员在默认接收人基础上追加，系统自动去重。
        </div>
      </div>
      <div style={{ ...CARD_STYLE, overflowX: 'auto' }}>
        <div style={{ minWidth: 760 }}>
          {!rows && isLoading ? (
            <LoadingRows />
          ) : isError ? (
            <div style={{ padding: 24 }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="通知配置加载失败"
              >
                <Button type="primary" onClick={() => refetch()}>
                  重试
                </Button>
              </Empty>
            </div>
          ) : rows && rows.length > 0 ? (
            rows.map((record, i) => (
              <div
                key={record.notify_type}
                style={{
                  borderTop: i > 0 ? '1px solid #ede9e4' : undefined,
                }}
              >
                <ConfigRow
                  record={record}
                  saving={savingType === record.notify_type}
                  onSave={handleSave}
                />
              </div>
            ))
          ) : (
            <div style={{ padding: 24 }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无通知类型"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function NotificationConfigPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <NotificationConfigContent />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}
