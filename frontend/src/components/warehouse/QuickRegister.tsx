'use client'

import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Space, Steps, Tag, Typography, Upload } from 'antd'
import { FileImage, ScanSearch } from 'lucide-react'
import { webConfirmDraft, webRecognizeReceipt, type WebRecognizeResult } from '@/lib/api/warehouse-quick-register-actions'
import { uploadReceiptImage } from '@/lib/api/warehouse-quick-register'
import { PageHeader } from './PageHeader'

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

/** 步骤推进：0 上传 → 1 识别中 → 2 确认 → 3 完成 */
function stepOf(state: { uploading: boolean; draft: WebRecognizeResult | null; done: string | null }): number {
  if (state.done) return 3
  if (state.draft) return 2
  if (state.uploading) return 1
  return 0
}

export function QuickRegister() {
  const [uploading, setUploading] = useState(false)
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [draft, setDraft] = useState<WebRecognizeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

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
    setConfirming(true)
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
    } finally {
      setConfirming(false)
    }
  }

  const step = stepOf({ uploading, draft, done })

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '快速登记']}
        title="快速登记"
        description="上传送货单图片，自动识别并确认入库登记"
      />

      <Steps
        className="mb-5"
        size="small"
        current={step}
        items={[
          { title: '上传送货单' },
          { title: 'AI 识别' },
          { title: '确认入库' },
          { title: '完成' },
        ]}
      />

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}

      {done ? (
        <Card>
          <Alert type="success" showIcon message={done} style={{ marginBottom: 12 }} />
          <Button type="primary" onClick={() => setDone(null)}>
            再登记一张
          </Button>
        </Card>
      ) : !draft ? (
        <Card styles={{ body: { padding: 24 } }}>
          <Upload.Dragger
            accept=".jpg,.jpeg,.png,.webp"
            maxCount={1}
            showUploadList={false}
            disabled={uploading}
            beforeUpload={handleUpload}
            style={{
              background: 'linear-gradient(180deg, var(--wh-primary-bg) 0%, #ffffff 70%)',
              borderRadius: 12,
              border: '1.5px dashed var(--color-primary-border, #b8adeb)',
            }}
          >
            <p className="mb-0">
              <FileImage size={40} strokeWidth={1.5} style={{ color: 'var(--color-primary)' }} />
            </p>
            <Typography.Paragraph className="mt-3 mb-0 text-[15px] font-medium">
              {uploading ? '正在上传并识别，请稍候…' : '点击或拖拽送货单图片到这里'}
            </Typography.Paragraph>
            <Typography.Text type="secondary" className="mt-1">
              上传后自动识别物料 / 批次 / 数量，无需手工录入
            </Typography.Text>
            <div className="mt-3 flex items-center justify-center gap-2">
              {['jpg', 'png', 'webp'].map(fmt => (
                <Tag key={fmt} style={{ marginInlineEnd: 0 }}>
                  {fmt.toUpperCase()}
                </Tag>
              ))}
              <span className="text-[12px] text-[var(--color-stone)]">不超过 10MB</span>
            </div>
          </Upload.Dragger>
        </Card>
      ) : (
        <Card
          title={
            <span className="inline-flex items-center gap-2">
              <ScanSearch size={16} style={{ color: 'var(--color-primary)' }} />
              识别草稿 {draft.draft_no}
            </span>
          }
          extra={
            <Space>
              <Button onClick={() => handleConfirm('cancel')} loading={confirming}>
                取消
              </Button>
              <Button type="primary" onClick={() => handleConfirm('confirm')} loading={confirming}>
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
      )}
    </div>
  )
}
