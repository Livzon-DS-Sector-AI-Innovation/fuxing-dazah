'use client'

import { Typography } from 'antd'
import { HistoryOutlined } from '@ant-design/icons'
import { LcHistoryList } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function HistoryPage() {
  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>
        <HistoryOutlined /> 检验记录
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        查看所有液相解析的历史记录，支持按产品和批号筛选。
      </Paragraph>
      <LcHistoryList />
    </div>
  )
}
