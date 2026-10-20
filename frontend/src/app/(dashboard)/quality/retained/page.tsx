'use client'

import { Typography } from 'antd'
import { RetainedSamples } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function RetainedPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>留样台账</Title>
        <Paragraph type="secondary">
          成品/物料批留样登记：记录留样量、贮存位置与销毁到期日；到期前系统在飞书群每日提醒，销毁需双人确认登记。也可在飞书发「留样 批号 X 量 N 柜 A 到期 YYYY-MM-DD」手机登记。
        </Paragraph>
      </div>
      <RetainedSamples />
    </div>
  )
}
