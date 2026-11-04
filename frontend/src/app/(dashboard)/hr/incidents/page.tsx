'use client'

import { Typography } from 'antd'
import { IncidentLedger } from '@/components/hr'

const { Title, Paragraph } = Typography

export default function IncidentsPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>工伤/劳动纠纷台账</Title>
        <Paragraph type="secondary">
          工伤与劳动纠纷记录维护（人力看板「用工风险」指标数据源），支持按类型筛选、状态跟踪（处理中/已结案）。
        </Paragraph>
      </div>
      <IncidentLedger />
    </div>
  )
}
