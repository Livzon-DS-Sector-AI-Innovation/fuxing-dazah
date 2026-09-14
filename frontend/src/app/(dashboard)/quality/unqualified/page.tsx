'use client'

import { Typography } from 'antd'
import { UnqualifiedEvents } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function UnqualifiedEventsPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>🚨 不合格台账</Title>
        <Paragraph type="secondary">
          机器人填报不合格不落检验库，仅在此台账留痕：批号、项目、实测值与限度一目了然，人工处理后标记闭环。
        </Paragraph>
      </div>
      <UnqualifiedEvents />
    </div>
  )
}
