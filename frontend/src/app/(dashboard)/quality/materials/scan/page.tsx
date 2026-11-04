'use client'

import { Typography } from 'antd'
import { ScanStation } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function MaterialScanPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>扫码操作台</Title>
        <Paragraph type="secondary">
          仓库桌面扫码专用：USB 扫码枪（或手工输号回车）连续处理物料入库登记与领料出库，结果就地展示。
        </Paragraph>
      </div>
      <ScanStation />
    </div>
  )
}
