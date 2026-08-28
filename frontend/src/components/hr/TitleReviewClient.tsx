'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Card, Empty, Select, Tabs } from 'antd'
import { usePermission } from '@/hooks/usePermission'
import type { TitleReviewActivityListItem } from '@/types/hr'
import { fetchTitleActivities } from '@/actions/hr'
import TitleReviewActivityTab from './TitleReviewActivityTab'
import TitleReviewApplicationTab from './TitleReviewApplicationTab'
import TitleReviewResultTab from './TitleReviewResultTab'

const STATUS_LABEL: Record<string, string> = {
  draft: '配置中',
  open: '申报中',
  reviewing: '评审中',
  closed: '已结束',
}

export default function TitleReviewClient() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [activities, setActivities] = useState<TitleReviewActivityListItem[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activeTab, setActiveTab] = useState('activity')

  const loadActivities = useCallback(() => {
    fetchTitleActivities({ page: 1, page_size: 100 })
      .then((d) => {
        const list = d?.data || []
        setActivities(list)
        setSelectedId((prev) => prev ?? list[0]?.id)
      })
      .catch((err: any) => message.error(err.message || '加载活动失败'))
  }, [message])

  useEffect(() => {
    loadActivities()
  }, [loadActivities])

  const selected = activities.find((a) => a.id === selectedId)

  const items = [
    {
      key: 'activity',
      label: '活动管理',
      children: (
        <TitleReviewActivityTab
          activities={activities}
          onRefresh={loadActivities}
          onSelectActivity={(id) => {
            setSelectedId(id)
            setActiveTab('applications')
          }}
        />
      ),
    },
    {
      key: 'applications',
      label: '申报与评审',
      disabled: !selectedId,
      children: selectedId ? (
        <TitleReviewApplicationTab activityId={selectedId} activityStatus={selected?.status} />
      ) : null,
    },
    {
      key: 'results',
      label: '评审结果',
      disabled: !selectedId,
      children: selectedId ? (
        <TitleReviewResultTab
          activityId={selectedId}
          canViewScores={hasPermission('hr:title:scores:read')}
        />
      ) : null,
    },
  ]

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">职称评审</h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          员工飞书审批申报（部门负责人→HR）→ 系统同步 → 评委内网匿名投票 → 票数判定 → 飞书通知结果
        </p>
      </div>

      <Card>
        <div className="flex items-center gap-3 mb-4">
          <span className="text-[14px] text-[var(--color-steel)]">当前活动：</span>
          <Select
            style={{ width: 340 }}
            placeholder="选择评定活动"
            value={selectedId}
            onChange={setSelectedId}
            options={activities.map((a) => ({
              value: a.id,
              label: `${a.name}（${STATUS_LABEL[a.status] || a.status}）`,
            }))}
            notFoundContent={<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无活动，请先在“活动管理”中创建" />}
          />
        </div>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} />
      </Card>
    </div>
  )
}
