'use client'

import { Typography } from 'antd'
import { TaskFillIn } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function TaskListPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>📝 检验填报</Title>
        <Paragraph type="secondary">
          以 COA（产品+批号）检阅当日 SOP：建任务即从标准库快照全部项目行，逐项填报（数值型自动判定、文字型人工判定），沉淀一手检验数据。
        </Paragraph>
      </div>
      <TaskFillIn />
    </div>
  )
}
