'use client'

import { useState } from 'react'
import { App, Badge, Drawer, Tabs } from 'antd'
import type { TabsProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { usePermission } from '@/hooks/usePermission'
import { FeedbackIcon } from '@/components/icons'
import { feedbackKeys, fetchFeedbackPendingCount } from '@/lib/api/feedback'
import { FeedbackQueryProvider } from './FeedbackQueryProvider'
import { FeedbackForm } from './FeedbackForm'
import { FeedbackAdminList } from './FeedbackAdminList'
import { FeedbackMineList } from './FeedbackMineList'

/** 与后端 app/platform/permission/registry.py 的平台权限码一致；超管默认拥有。 */
export const FEEDBACK_MANAGE_PERMISSION = 'system:feedback:manage'

type TabKey = 'all' | 'submit' | 'mine'

interface FeedbackEntryProps {
  /** 顶栏图标按钮样式由 TopNav 传入，避免跨目录引用其 CSS Module。 */
  buttonClassName?: string
}

/**
 * 顶栏「反馈」入口：同一个按钮服务所有角色。
 * TopNav 位于 antd <App> 与任何 QueryClientProvider 之外，这里自带两者。
 */
export function FeedbackEntry(props: FeedbackEntryProps) {
  return (
    <FeedbackQueryProvider>
      <App component={false}>
        <FeedbackEntryInner {...props} />
      </App>
    </FeedbackQueryProvider>
  )
}

function FeedbackEntryInner({ buttonClassName }: FeedbackEntryProps) {
  const { hasPermission, isLoaded } = usePermission()
  const canManage = isLoaded && hasPermission(FEEDBACK_MANAGE_PERMISSION)
  const defaultTab: TabKey = canManage ? 'all' : 'submit'
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<TabKey>(defaultTab)

  const pendingQuery = useQuery({
    queryKey: feedbackKeys.pendingCount,
    queryFn: fetchFeedbackPendingCount,
    enabled: canManage,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
  const pending = canManage ? pendingQuery.data ?? 0 : 0

  const handleOpen = () => {
    setActiveTab(defaultTab)
    setOpen(true)
  }

  const items: TabsProps['items'] = [
    ...(canManage
      ? [
          {
            key: 'all',
            label: (
              <span className="inline-flex items-center gap-1.5">
                全部反馈
                <Badge count={pending} size="small" overflowCount={99} />
              </span>
            ),
            children: <FeedbackAdminList />,
          },
        ]
      : []),
    {
      key: 'submit',
      label: '提交反馈',
      children: <FeedbackForm onSubmitted={() => setActiveTab('mine')} />,
    },
    { key: 'mine', label: '我的反馈', children: <FeedbackMineList /> },
  ]

  const buttonLabel = pending > 0 ? `反馈 · ${pending} 条待处理` : '反馈'

  return (
    <>
      <button
        type="button"
        className={buttonClassName}
        aria-label={buttonLabel}
        title={buttonLabel}
        onClick={handleOpen}
      >
        <Badge count={pending} size="small" overflowCount={99} style={{ display: 'flex' }}>
          <FeedbackIcon className="w-[18px] h-[18px]" />
        </Badge>
      </button>
      <Drawer
        title="系统反馈"
        open={open}
        onClose={() => setOpen(false)}
        size={canManage ? 880 : 520}
        destroyOnHidden
      >
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as TabKey)}
          items={items}
        />
      </Drawer>
    </>
  )
}
