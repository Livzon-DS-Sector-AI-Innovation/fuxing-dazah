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
          QC 汇总表：每行一个批次，全部检验项目横向逐一列出数值结果与判定；下方按 SOP 索引查看跨批次明细。
        </Paragraph>
      </div>
      <SummaryView />
      <SopSummary />
    </div>
  )
}
