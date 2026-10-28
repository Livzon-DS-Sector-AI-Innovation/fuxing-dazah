'use client'

import { Typography } from 'antd'
import { BatchReleases } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function ReleasePage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>批放行</Title>
        <Paragraph type="secondary">
          已完成检验任务的批放行记录：发起时快照判定/复核/报告单/留样状态，专员放行留痕。偏差/CAPA 联动检查由对应模块接入。
        </Paragraph>
      </div>
      <BatchReleases />
    </div>
  )
}
