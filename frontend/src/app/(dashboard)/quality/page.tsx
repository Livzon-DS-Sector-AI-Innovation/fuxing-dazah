'use client'

import { useState } from 'react'
import { Typography, Divider, Empty } from 'antd'
import { ExperimentOutlined } from '@ant-design/icons'
import { LcUploader, LcReportView } from '@/components/quality'
import type { UploadLcResponse } from '@/types/quality'

const { Title, Paragraph } = Typography

export default function QualityPage() {
  const [result, setResult] = useState<UploadLcResponse | null>(null)

  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>
        <ExperimentOutlined /> 液相计算表解析
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        上传液相计算表 Excel，自动解析峰面积、计算结果和质量标准，执行合格/超趋势判定。
      </Paragraph>

      <LcUploader onResult={setResult} />

      {result && (
        <>
          <Divider />
          <LcReportView report={result.report} />
        </>
      )}

      {!result && (
        <div style={{ marginTop: 48, textAlign: 'center' }}>
          <Empty description="请上传液相计算表 Excel 文件开始解析" />
        </div>
      )}
    </div>
  )
}
