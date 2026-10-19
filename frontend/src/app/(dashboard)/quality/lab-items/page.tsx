'use client'

import { Typography } from 'antd'
import { LabItems } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function LabItemsPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>试剂/仪器台账</Title>
        <Paragraph type="secondary">
          实验室试剂/对照品/滴定液与仪器校验台账，效期临期 30 天内标黄、过期标红，每日 08:15 飞书推送提醒。
        </Paragraph>
      </div>
      <LabItems />
    </div>
  )
}
