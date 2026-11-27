'use client'

import { Typography } from 'antd'
import { TaskBoard } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function BoardPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>任务看板</Title>
        <Paragraph type="secondary">
          今天及以后的请检任务排班看板：按计划展示待检 SOP，逐 SOP 选择负责人员，分配后人员名字显示在任务下方；建任务后分工自动带到检验任务。
        </Paragraph>
      </div>
      <TaskBoard />
    </div>
  )
}
