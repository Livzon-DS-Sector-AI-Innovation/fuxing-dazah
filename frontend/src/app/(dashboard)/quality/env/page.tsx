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
          洁净区环境监测台账：按点位登记沉降菌/浮游菌/悬浮粒子/温湿度/压差，按警戒限/行动限双限自动判定，超行动限立即在飞书群预警。手机填报：飞书发「环境 点位 P001 值 5」。每周/每月频次点位自动生成周期计划，每日飞书推送应测清单，趋势图按点位回看。
        </Paragraph>
      </div>
      <EnvMonitor />
    </div>
  )
}
