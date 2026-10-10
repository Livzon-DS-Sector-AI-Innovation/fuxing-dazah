'use client'

import { Typography } from 'antd'
import { MaterialContainers } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function MaterialsPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>📦 物料容器</Title>
        <Paragraph type="secondary">
          每瓶（桶）物料唯一二维码赋码管理：批量生成容器号（MC-物料代码-日期-流水）与不干胶标签，入库登记、领料出库全流程扫码留痕。
        </Paragraph>
      </div>
      <MaterialContainers />
    </div>
  )
}
