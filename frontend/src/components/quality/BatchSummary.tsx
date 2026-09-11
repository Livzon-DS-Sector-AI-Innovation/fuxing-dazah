'use client'

import { Card, Descriptions, Tag, List, Typography, Space } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, WarningOutlined } from '@ant-design/icons'
import type { InspectionRecordDetail } from '@/types/quality'

const { Text } = Typography

interface Props {
  detail: InspectionRecordDetail
  summaryText: string
}

export default function BatchSummary({ detail, summaryText }: Props) {
  return (
    <div>
      {/* 判定总览 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="产品">{detail.product_name}</Descriptions.Item>
          <Descriptions.Item label="批号">{detail.batch_number}</Descriptions.Item>
          <Descriptions.Item label="标准">{detail.standard_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="表号">{detail.form_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="总体判定">
            {detail.all_pass
              ? <Tag color="success">合格</Tag>
              : <Tag color="error">不合格</Tag>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 文字化摘要 */}
      <Card size="small" title="判定摘要" style={{ marginBottom: 16 }}>
        <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit' }}>
          {summaryText}
        </pre>
      </Card>

      {/* 杂质明细 */}
      {detail.impurities.length > 0 && (
        <Card size="small" title={`杂质明细（共 ${detail.impurities.length} 项）`}>
          <List
            size="small"
            dataSource={detail.impurities}
            renderItem={(imp) => (
              <List.Item>
                <List.Item.Meta
                  title={imp.name}
                  description={
                    <Space>
                      <Text>第一份: {(imp.first_percent ?? 0) * 100}%</Text>
                      <Text>第二份: {(imp.second_percent ?? 0) * 100}%</Text>
                      <Text type="secondary">限度: {imp.limit != null ? `${imp.limit * 100}%` : '-'}</Text>
                    </Space>
                  }
                />
                <Space>
                  {imp.is_pass
                    ? <Tag color="success">合格</Tag>
                    : <Tag color="error">不合格</Tag>}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}
    </div>
  )
}
