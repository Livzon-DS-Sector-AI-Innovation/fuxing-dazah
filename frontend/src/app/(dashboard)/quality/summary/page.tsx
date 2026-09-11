'use client'

import { Typography } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import { SummaryView, SopSummary } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function SummaryPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          <BarChartOutlined /> 汇总表
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 24 }}>
          按产品和时间段统计检验数据；下方按 SOP 索引汇总各项目跨批次结果（一手数据）。
        </Paragraph>
      </div>
      <SummaryView />
      <SopSummary />
    </div>
  )
}
