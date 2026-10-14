'use client'

import { Typography } from 'antd'
import { MaterialRequests } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function MaterialRequestsPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>物料请验</Title>
        <Paragraph type="secondary">
          进厂物料请验 取样 按物料标准建检验任务（复用检验填报/双人复核链路）放行/拒收/让步，结论自动联动该批容器状态。
        </Paragraph>
      </div>
      <MaterialRequests />
    </div>
  )
}
