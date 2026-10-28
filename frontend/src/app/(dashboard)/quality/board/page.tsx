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
          按人员分列的检验任务看板：请检任务内各 SOP 指派负责人（人员手动选择），分工与完成进度一目了然。
        </Paragraph>
      </div>
      <TaskBoard />
    </div>
  )
}
