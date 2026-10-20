'use client'

import { Typography } from 'antd'
import { MicroRecords } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function MicroPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>微生物登记</Title>
        <Paragraph type="secondary">
          微生物限度/平板菌落计数登记：人工确认数判定（超警戒线/超标准限），平皿照片归档为原始证据，一键导出 Excel 登记表。AI 自动计数为预留插件（需照片样本）。
        </Paragraph>
      </div>
      <MicroRecords />
    </div>
  )
}
