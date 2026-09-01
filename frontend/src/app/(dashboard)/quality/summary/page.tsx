'use client'

import { Typography } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import { SummaryView } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function SummaryPage() {
  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>
        <BarChartOutlined /> 汇总表
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        按产品和时间段统计检验数据，包含合格率、OOT 率等关键指标。
      </Paragraph>
      <SummaryView />
    </div>
  )
}
