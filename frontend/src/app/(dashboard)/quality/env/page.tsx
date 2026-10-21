'use client'

import { Typography } from 'antd'
import { EnvMonitor } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function EnvPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>环境监测</Title>
        <Paragraph type="secondary">
          洁净区环境监测台账：按点位登记沉降菌/浮游菌/悬浮粒子/温湿度/压差，按警戒限/行动限双限自动判定，超行动限立即在飞书群预警。手机填报：飞书发「环境 点位 P001 值 5」。周期计划自动生成与趋势图在后续版本。
        </Paragraph>
      </div>
      <EnvMonitor />
    </div>
  )
}
