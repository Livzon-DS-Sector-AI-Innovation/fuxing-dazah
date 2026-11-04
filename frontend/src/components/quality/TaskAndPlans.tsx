'use client'

import { useState } from 'react'
import { Tabs } from 'antd'
import { useRouter } from 'next/navigation'
import { TaskFillIn, InspectionPlans } from '@/components/quality'

export default function TaskAndPlans() {
  const router = useRouter()
  const [active, setActive] = useState('tasks')

  const onBuildTask = (batch: string, product: string) => {
    // 切到检验任务页签并深链预填建任务弹窗（一次消费后自动清参数）
    setActive('tasks')
    router.push(
      `/quality/task?create=1&product_name=${encodeURIComponent(product)}&batch_number=${encodeURIComponent(batch)}`
    )
  }

  return (
    <Tabs
      activeKey={active}
      onChange={setActive}
      items={[
        { key: 'tasks', label: '检验任务', children: <TaskFillIn /> },
        { key: 'plans', label: '请检计划', children: <InspectionPlans onBuildTask={onBuildTask} /> },
      ]}
    />
  )
}
