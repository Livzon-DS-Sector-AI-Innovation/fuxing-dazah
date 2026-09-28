'use client'

import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  Row,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { FileImage, ScanSearch } from 'lucide-react'
import {
  webConfirmDraft,
  webRecognizeReceipt,
  webUpdateDraftFields,
  type WebRecognizeResult,
} from '@/lib/api/warehouse-quick-register-actions'
import { uploadReceiptImage } from '@/lib/api/warehouse-quick-register'
import { PageHeader } from './PageHeader'

type FieldValue = { value?: string | number | null; confidence?: number | null }
type RowItem = Record<string, string> & { key?: string }

/** 标量字段定义（key 为后端 canonical 键） */
interface FieldDef {
  key: string
  label: string
}

const RAW_FIELDS: FieldDef[] = [
  { key: 'material_name', label: '物料名称' },
  { key: 'vendor_batch_no', label: '厂家批号' },
  { key: 'quantity', label: '入库数量' },
  { key: 'unit', label: '单位' },
  { key: 'supplier', label: '供应商' },
  { key: 'manufacturer', label: '生产商' },
  { key: 'plate_no', label: '车牌号' },
  { key: 'contract_no', label: '合同号' },
]

// 原辅料选填字段（包装规格/备注等）全量展示，允许补填
const RAW_OPTIONAL_FIELDS: FieldDef[] = [
  { key: 'package_spec', label: '包装规格' },
  { key: 'produced_at', label: '生产日期' },
  { key: 'arrival_period', label: '到货时间段' },
  { key: 'remark', label: '备注' },
  { key: 'contact', label: '联系人' },
]

const FINISHED_FIELDS: FieldDef[] = [
  { key: 'product_name', label: '产品名称' },
  { key: 'product_batch_no', label: '产品批号' },
  { key: 'quantity', label: '入库数量' },
  { key: 'unit', label: '单位' },
]

// 成品选填字段全量展示（品规/日期等登记常需人工补填）
const FINISHED_OPTIONAL_FIELDS: FieldDef[] = [
  { key: 'receipt_date', label: '入库日期' },
  { key: 'receipt_type', label: '入库类型' },
  { key: 'spec', label: '品规' },
  { key: 'produced_at', label: '生产日期' },
  { key: 'expiry', label: '有效期' },
  { key: 'workshop', label: '生产车间' },
  { key: 'storage_location', label: '库区位置' },
  { key: 'remark', label: '备注' },
]

// 成品多行明细列（识别 rows 同契约；顺序即展示顺序）
const ROW_COLUMNS: Array<{ key: string; label: string; width?: number }> = [
  { key: 'product_name', label: '产品名称', width: 150 },
  { key: 'product_batch_no', label: '产品批号', width: 140 },
  { key: 'quantity', label: '数量', width: 100 },
  { key: 'unit', label: '单位', width: 90 },
  { key: 'spec', label: '品规', width: 130 },
  { key: 'produced_at', label: '生产日期', width: 120 },
  { key: 'expiry', label: '有效期', width: 120 },
]

const ROW_REQUIRED_KEYS = ['product_name', 'product_batch_no', 'quantity', 'unit']

function isLowConfidence(field: FieldValue | undefined): boolean {
  const value = field?.confidence
  return value != null && value > 0 && value < 0.6
}

function scalarText(recognized: Record<string, FieldValue>, key: string): string {
  const field = recognized[key]
  return field && field.value != null ? String(field.value) : ''
}

interface AlignedInfo {
  match_confidence?: string
  product_name?: string
  warnings?: Record<string, string>
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
  const [values, setValues] = useState<Record<string, string>>({})
  const [initialValues, setInitialValues] = useState<Record<string, string>>({})
  const [rows, setRows] = useState<RowItem[]>([])
  const [initialRows, setInitialRows] = useState<RowItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const isFinished = draft?.scene === 'finished_receipt'

  const loadDraft = (result: WebRecognizeResult) => {
    const recognized = result.recognized || {}
    const fields = isFinishedFieldSet(result.scene)
    const prefilled: Record<string, string> = {}
    for (const def of fields) prefilled[def.key] = scalarText(recognized, def.key)
    const recognizedRows = Array.isArray(recognized['rows'] as unknown)
      ? ((recognized['rows'] as unknown as RowItem[]) || []).map((row, index) => {
          const item: RowItem = { key: `row-${index}` }
          for (const col of ROW_COLUMNS) item[col.key] = row[col.key] != null ? String(row[col.key]) : ''
          return item
        })
      : []
    setValues(prefilled)
    setInitialValues(prefilled)
    setRows(recognizedRows)
    setInitialRows(recognizedRows)
    setDraft(result)
  }

  const handleUpload = async (file: File) => {
    setError(null)
    setDone(null)
    setUploading(true)
    try {
      const { upload_id } = await uploadReceiptImage(file)
      setUploadId(upload_id)
      loadDraft(await webRecognizeReceipt(upload_id))
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
      if (action === 'confirm') {
        // 表单直改先落 aligned（与飞书对话修改同一取值口径），再走确认
        const fields: Record<string, string> = {}
        for (const key of Object.keys(values)) {
          if ((values[key] ?? '') !== (initialValues[key] ?? '')) fields[key] = values[key] ?? ''
        }
        const rowsChanged = JSON.stringify(rows) !== JSON.stringify(initialRows)
        if (Object.keys(fields).length > 0 || rowsChanged) {
          await webUpdateDraftFields(draft.draft_id, {
            fields: Object.keys(fields).length > 0 ? fields : undefined,
            rows: rowsChanged ? rows : undefined,
          })
        }
      }
      const result = await webConfirmDraft(draft.draft_id, action)
      if (result.ok && action === 'confirm') {
        setDone(`草稿 ${draft.draft_no} 已确认提交，库存与飞书台账将同步更新`)
        resetDraft()
      } else if (action === 'cancel') {
        setDone(`草稿 ${draft.draft_no} 已取消`)
        resetDraft()
      } else {
        setError(result.status || '处理失败')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '处理失败')
    } finally {
      setConfirming(false)
    }
  }

  const resetDraft = () => {
    setDraft(null)
    setUploadId(null)
    setValues({})
    setInitialValues({})
    setRows([])
    setInitialRows([])
  }

  const step = stepOf({ uploading, draft, done })
  const recognized = (draft?.recognized || {}) as Record<string, FieldValue>
  const aligned = (draft?.aligned || {}) as AlignedInfo
  const warningMessages = Object.values(aligned.warnings || {})
  const matchCn =
    aligned.match_confidence === 'exact'
      ? '精确'
      : aligned.match_confidence === 'prefix'
        ? '前缀'
        : aligned.match_confidence === 'fuzzy'
          ? '近似'
          : null

  const fieldDefs = isFinished ? [...FINISHED_FIELDS, ...FINISHED_OPTIONAL_FIELDS] : [...RAW_FIELDS, ...RAW_OPTIONAL_FIELDS]

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '快速登记']}
        title="快速登记"
        description="上传送货单或成品入库单图片，自动识别、核对修改后确认登记"
      />

      <Steps
        className="mb-5"
        size="small"
        current={step}
        items={[
          { title: '上传单据' },
          { title: 'AI 识别' },
          { title: '核对确认' },
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
              {uploading ? '正在上传并识别，请稍候…' : '点击或拖拽单据图片到这里'}
            </Typography.Paragraph>
            <Typography.Text type="secondary" className="mt-1">
              支持送货单与成品入库单；识别后可直接在表单中核对修改
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
              <Tag color="purple" style={{ marginInlineStart: 8 }}>
                {isFinished ? '成品入库' : '原辅料入库'}
              </Tag>
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
          {(matchCn || warningMessages.length > 0) && (
            <Alert
              type={warningMessages.length > 0 ? 'warning' : 'success'}
              showIcon
              style={{ marginBottom: 16 }}
              message={warningMessages.length > 0 ? '识别结果存在以下疑点，请在右侧表单中核对修正' : '识别结果已对齐产品名录'}
              description={
                <>
                  {matchCn && (
                    <div>
                      产品对齐：{aligned.product_name || '-'}（名录{matchCn}匹配）
                    </div>
                  )}
                  {warningMessages.map(msg => (
                    <div key={msg}>⚠ {msg}</div>
                  ))}
                </>
              }
            />
          )}

          <Row gutter={16}>
            <Col xs={24} lg={10}>
              <Card size="small" title="单据原图" styles={{ body: { padding: 8 } }}>
                {uploadId ? (
                  <img
                    src={`/api/v1/warehouse/agent/uploads/${uploadId}`}
                    alt="单据原图"
                    style={{ width: '100%', borderRadius: 6 }}
                  />
                ) : (
                  <Typography.Text type="secondary">无原图</Typography.Text>
                )}
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card size="small" title="登记信息（可直接修改）">
                {fieldDefs.map(def => {
                  const low = isLowConfidence(recognized[def.key])
                  return (
                    <div key={def.key} className="mb-3">
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {def.label}
                        {low && (
                          <Tag color="orange" style={{ marginInlineStart: 6, fontSize: 11 }}>
                            低置信度 {Math.round((recognized[def.key]?.confidence ?? 0) * 100)}%
                          </Tag>
                        )}
                      </Typography.Text>
                      <Input
                        size="small"
                        status={low ? 'warning' : undefined}
                        value={values[def.key] ?? ''}
                        onChange={e => setValues(v => ({ ...v, [def.key]: e.target.value }))}
                      />
                    </div>
                  )
                })}

                {isFinished && rows.length > 0 && (
                  <div className="mt-2">
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      明细行（{rows.length} 行，每行一条台账；同批号提交时自动归组求和）
                    </Typography.Text>
                    <Table<RowItem>
                      size="small"
                      pagination={false}
                      dataSource={rows}
                      rowKey={row => row.key ?? ''}
                      scroll={{ x: 'max-content' }}
                      columns={ROW_COLUMNS.map(col => ({
                        title: (
                          <span>
                            {col.label}
                            {ROW_REQUIRED_KEYS.includes(col.key) && <span style={{ color: '#ff4d4f' }}> *</span>}
                          </span>
                        ),
                        width: col.width,
                        dataIndex: col.key,
                        render: (_: unknown, __: RowItem, index: number) => (
                          <Input
                            size="small"
                            value={rows[index]?.[col.key] ?? ''}
                            onChange={e =>
                              setRows(rs =>
                                rs.map((row, i) =>
                                  i === index ? { ...row, [col.key]: e.target.value } : row,
                                ),
                              )
                            }
                          />
                        ),
                      }))}
                    />
                  </div>
                )}

                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                  修改将随确认一并提交；低置信度字段（橙色）建议对照原图核对。
                </Typography.Text>
              </Card>
            </Col>
          </Row>
        </Card>
      )}
    </div>
  )
}

/** 按 scene 返回可编辑字段集（识别结果初始化用；rows 单独处理） */
function isFinishedFieldSet(scene: string): FieldDef[] {
  return scene === 'finished_receipt'
    ? [...FINISHED_FIELDS, ...FINISHED_OPTIONAL_FIELDS]
    : [...RAW_FIELDS, ...RAW_OPTIONAL_FIELDS]
}
