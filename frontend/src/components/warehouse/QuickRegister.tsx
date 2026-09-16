'use client'

import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Space, Tag, Typography, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { webConfirmDraft, webRecognizeReceipt, type WebRecognizeResult } from '@/lib/api/warehouse-quick-register-actions'
import { uploadReceiptImage } from '@/lib/api/warehouse-quick-register'

const FIELD_LABEL: Record<string, string> = {
  material_name: '物料名称',
  vendor_batch_no: '供应商批次',
  quantity: '数量',
  unit: '单位',
  supplier: '供应商',
  manufacturer: '生产厂家',
  plate_no: '车牌号',
  contract_no: '合同号',
}

function isLowConfidence(field: { confidence?: number | null } | undefined): boolean {
  const value = field?.confidence
  return value != null && value > 0 && value < 0.6
}

export function QuickRegister() {
  const [uploading, setUploading] = useState(false)
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [draft, setDraft] = useState<WebRecognizeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const handleUpload = async (file: File) => {
    setError(null)
    setDone(null)
    setUploading(true)
    try {
      const { upload_id } = await uploadReceiptImage(file)
      setUploadId(upload_id)
      setDraft(await webRecognizeReceipt(upload_id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传或识别失败')
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd Upload 自动上传
  }

  const handleConfirm = async (action: 'confirm' | 'cancel') => {
    if (!draft) return
    try {
      const result = await webConfirmDraft(draft.draft_id, action)
      if (result.ok && action === 'confirm') {
        setDone(`草稿 ${draft.draft_no} 已确认提交，库存与飞书台账将同步更新`)
        setDraft(null)
        setUploadId(null)
      } else if (action === 'cancel') {
        setDone(`草稿 ${draft.draft_no} 已取消`)
        setDraft(null)
        setUploadId(null)
      } else {
        setError(result.status || '处理失败')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '处理失败')
    }
  }

  if (done) {
    return (
      <div>
        <Alert type="success" showIcon message={done} style={{ marginBottom: 12 }} />
        <Button type="primary" onClick={() => setDone(null)}>
          再登记一张
        </Button>
      </div>
    )
  }

  return (
    <div>
      {error && (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />
      )}

      {!draft && (
        <Card
          style={{ textAlign: 'center', padding: 24 }}
          styles={{ body: { padding: 24 } }}
        >
          <Upload.Dragger
            accept=".jpg,.jpeg,.png,.webp"
            maxCount={1}
            showUploadList={false}
            beforeUpload={handleUpload}
          >
            <InboxOutlined style={{ fontSize: 40, color: 'var(--ant-color-primary, #5645d4)' }} />
            <Typography.Paragraph style={{ marginTop: 8 }}>
              点击或拖拽送货单图片到这里
            </Typography.Paragraph>
            <Typography.Text type="secondary">
              支持 jpg / png / webp，不超过 10MB；上传后自动识别
            </Typography.Text>
          </Upload.Dragger>
          {uploading && (
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
              正在上传并识别，请稍候…
            </Typography.Text>
          )}
        </Card>
      )}

      {draft && (
        <div>
          <Card
            title={`识别草稿 ${draft.draft_no}`}
            extra={
              <Space>
                <Button onClick={() => handleConfirm('cancel')}>取消</Button>
                <Button type="primary" onClick={() => handleConfirm('confirm')}>
                  确认提交
                </Button>
              </Space>
            }
          >
            <Descriptions column={1} size="small" bordered>
              {Object.entries(draft.recognized).map(([key, field]) => {
                if (key === 'raw' || field == null) return null
                const low = isLowConfidence(field)
                return (
                  <Descriptions.Item
                    key={key}
                    label={FIELD_LABEL[key] ?? key}
                    labelStyle={{ width: 140 }}
                  >
                    {field.value == null || field.value === '' ? (
                      '-'
                    ) : (
                      <span>
                        {String(field.value)}{' '}
                        {low && <Tag color="orange">低置信度 {Math.round((field.confidence ?? 0) * 100)}%</Tag>}
                      </span>
                    )}
                  </Descriptions.Item>
                )
              })}
            </Descriptions>
            {uploadId && (
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                原图引用：{uploadId}
              </Typography.Text>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
