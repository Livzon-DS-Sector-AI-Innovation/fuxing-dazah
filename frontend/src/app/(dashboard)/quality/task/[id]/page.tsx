'use client'

import { use } from 'react'
import { Typography } from 'antd'
import { TaskDetail } from '@/components/quality'

const { Title } = Typography

export default function TaskDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  return (
    <div className="space-y-4">
      <Title level={3}>📝 检验填报</Title>
      <TaskDetail id={id} />
    </div>
  )
}
