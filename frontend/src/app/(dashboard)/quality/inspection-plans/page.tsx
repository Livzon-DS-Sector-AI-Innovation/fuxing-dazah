'use client'

import { Typography } from 'antd'
import { InspectionPlans } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function InspectionPlansPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>请检计划</Title>
        <Paragraph type="secondary">
          车间中控及成品请检计划统一台账：Excel 批量导入或手动新增，请检当天 08:15 飞书推送提醒相关车间与 QC。
        </Paragraph>
      </div>
      <InspectionPlans />
    </div>
  )
}
