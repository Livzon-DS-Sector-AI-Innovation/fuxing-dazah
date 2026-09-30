'use client'

import { Typography } from 'antd'
import { TemplatesManager } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function TemplatesPage() {
  return (
    <div className="space-y-4">
      <div>
        <Title level={3}>📑 报告模板</Title>
        <Paragraph type="secondary">
          上传并管理 COA 报告模板（.docx）。建议按产品建文件夹、模板文件名与 SOP 号码保持一致（如 3205.docx），生成 COA 时按绑定模板自动填充。
        </Paragraph>
      </div>
      <TemplatesManager />
    </div>
  )
}
