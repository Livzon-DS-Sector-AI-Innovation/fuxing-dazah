'use client'

import { useRef, useState } from 'react'
import { App, Modal, Table, Button, Upload, Tag, Space, Progress } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { FileMatchItem, BatchUploadResult, ExtractResultEvent, ExtractCompleteEvent } from '@/types/meter'
import { matchReportFiles, batchUploadReports } from '@/actions/meter'
import { fetchBatchExtractDatesStream } from '@/lib/api/meter'
import type { UploadFile } from 'antd/es/upload/interface'

const { Dragger } = Upload

interface Props {
  open: boolean
  source: 'instrument' | 'gas_detector'
  uploadHint: string
  onClose: () => void
}

type MatchRow = FileMatchItem & { _key: string }

interface ExtractState {
  phase: 'idle' | 'running' | 'interrupted' | 'done'
  current: number
  total: number
  currentFileName: string
  completedIds: Set<string>       // 已处理完成的 report_id
  results: ExtractResultEvent[]    // 所有结果
}

export function BatchUploadDialog({ open, source, uploadHint, onClose }: Props) {
  const { message } = App.useApp()

  const [step, setStep] = useState<'select' | 'preview' | 'result'>('select')
  const [files, setFiles] = useState<UploadFile[]>([])
  const [matches, setMatches] = useState<MatchRow[]>([])
  const [matching, setMatching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<BatchUploadResult | null>(null)

  // ── AI 识别进度状态 ──
  const [extract, setExtract] = useState<ExtractState>({
    phase: 'idle', current: 0, total: 0, currentFileName: '',
    completedIds: new Set(), results: [],
  })
  const controllerRef = useRef<AbortController | null>(null)

  // ── 步骤1：选择文件 → 自动匹配 ──
  const handleFileSelect = async (fileList: UploadFile[]) => {
    if (fileList.length === 0) return
    setFiles(fileList)
    setMatching(true)
    setStep('preview')
    try {
      const filenames = fileList.map(f => f.name)
      const data = await matchReportFiles(filenames)
      setMatches(data.map(d => ({ ...d, _key: d.filename })))
    } catch {
      message.error('文件匹配失败，请重试')
      setStep('select')
    } finally {
      setMatching(false)
    }
  }

  // ── 步骤2：确认上传 ──
  const handleConfirmUpload = async () => {
    setUploading(true)
    try {
      const formData = new FormData()
      files.forEach(f => {
        if (f.originFileObj) {
          formData.append('files', f.originFileObj)
        }
      })
      const items = matches.map(m => ({
        filename: m.filename,
        instrument_id: m.matched_type === 'instrument' ? m.matched_id : null,
        gas_detector_id: m.matched_type === 'gas_detector' ? m.matched_id : null,
      }))
      formData.append('items_json', JSON.stringify(items))

      const res = await batchUploadReports(formData)
      setResult(res)
      setStep('result')
      // 重置 AI 识别状态
      setExtract({ phase: 'idle', current: 0, total: 0, currentFileName: '', completedIds: new Set(), results: [] })
    } catch {
      message.error('批量上传失败')
    } finally {
      setUploading(false)
    }
  }

  // ── 批量 AI 识别（SSE 流式） ──
  const handleBatchExtract = () => {
    if (!result || result.report_ids.length === 0) return

    // 断点续传：排除已完成的 ID
    const { completedIds } = extract
    const remainingIds =
      extract.phase === 'interrupted'
        ? result.report_ids.filter(id => !completedIds.has(id))
        : result.report_ids

    if (remainingIds.length === 0) {
      message.info('所有报告已处理完毕')
      return
    }

    // 初始化进度
    setExtract(prev => ({
      ...prev,
      phase: 'running',
      current: prev.phase === 'interrupted' ? prev.current : 0,
      total: result.report_ids.length,
      currentFileName: remainingIds[0] ? '准备中...' : '',
      // 保留已完成的结果
    }))

    const controller = fetchBatchExtractDatesStream(remainingIds, {
      onProgress: (e) => {
        setExtract(prev => ({
          ...prev,
          current: prev.current + 1,
          currentFileName: e.file_name,
        }))
      },
      onResult: (e) => {
        setExtract(prev => {
          const newCompleted = new Set(prev.completedIds)
          newCompleted.add(e.report_id)
          return {
            ...prev,
            completedIds: newCompleted,
            results: [...prev.results, e],
          }
        })
      },
      onError: (msg) => {
        message.error(msg)
        setExtract(prev => ({ ...prev, phase: 'done' }))
      },
      onComplete: (e) => {
        if (e.interrupted) {
          setExtract(prev => ({ ...prev, phase: 'interrupted' }))
          message.warning('任务已中断，可继续处理剩余报告')
        } else {
          setExtract(prev => ({ ...prev, phase: 'done' }))
          message.success(`识别完成：成功 ${e.success} 个，失败 ${e.failed} 个`)
        }
      },
    })
    controllerRef.current = controller
  }

  // ── 中断 AI 识别 ──
  const handleInterrupt = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }

  // ── 关闭重置 ──
  const handleClose = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setStep('select')
    setFiles([])
    setMatches([])
    setResult(null)
    setExtract({ phase: 'idle', current: 0, total: 0, currentFileName: '', completedIds: new Set(), results: [] })
    onClose()
  }

  // ── 预览表格列 ──
  const matchColumns: TableColumnsType<MatchRow> = [
    { title: '文件名', dataIndex: 'filename', key: 'filename', ellipsis: true },
    {
      title: '匹配结果', dataIndex: 'matched_name', key: 'matched_name', width: 240, ellipsis: true,
      render: (v: string | null | undefined) => {
        if (v) return <Tag color="green">{v}</Tag>
        return <Tag color="red">未匹配</Tag>
      },
    },
    {
      title: '部门', dataIndex: 'matched_department', key: 'matched_department', width: 140, ellipsis: true,
      render: (v: string | null | undefined) => v || '-',
    },
  ]

  const matchedCount = matches.filter(m => m.matched_id).length
  const unmatchedCount = matches.length - matchedCount

  const handleReset = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setStep('select')
    setFiles([])
    setMatches([])
    setResult(null)
    setExtract({ phase: 'idle', current: 0, total: 0, currentFileName: '', completedIds: new Set(), results: [] })
  }

  const isExtracting = extract.phase === 'running'
  const extractPercent = extract.total > 0 ? Math.round((extract.completedIds.size / extract.total) * 100) : 0
  const successCount = extract.results.filter(r => r.status === 'success').length
  const failedCount = extract.results.filter(r => r.status === 'failed').length

  return (
    <Modal
      title={source === 'instrument' ? '批量上传 — 标准计量器具报告' : '批量上传 — 探测器报告'}
      open={open}
      onCancel={handleClose}
      width={800}
      footer={null}
      destroyOnHidden
    >
      {/* ── 步骤1：选择文件 ── */}
      {step === 'select' && (
        <Dragger
          multiple
          beforeUpload={() => false}
          onChange={(info) => handleFileSelect(info.fileList)}
          showUploadList={false}
          accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此区域</p>
          <p className="ant-upload-hint">支持 PDF、图片、Word 文档，单文件最大 50MB</p>
          <p className="ant-upload-hint">文件名格式：{uploadHint}</p>
        </Dragger>
      )}

      {/* ── 步骤2：匹配预览 ── */}
      {step === 'preview' && (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>
              已匹配 <b>{matchedCount}</b> / {matches.length} 个文件
              {unmatchedCount > 0 && <Tag color="orange" style={{ marginLeft: 8 }}>{unmatchedCount} 个未匹配</Tag>}
            </span>
            <Space>
              <Button onClick={handleReset}>重新选择</Button>
              <Button
                type="primary"
                loading={uploading}
                disabled={matchedCount === 0}
                onClick={handleConfirmUpload}
              >
                确认上传（{matchedCount} 个）
              </Button>
            </Space>
          </div>
          <Table
            rowKey="_key"
            columns={matchColumns}
            dataSource={matches}
            loading={matching}
            size="small"
            pagination={matches.length > 20 ? { pageSize: 20 } : false}
            scroll={{ y: 400 }}
          />
          {unmatchedCount > 0 && (
            <div style={{ marginTop: 8, color: '#999', fontSize: 13 }}>
              未匹配的文件不会上传。请检查文件名是否符合格式："{uploadHint}"
            </div>
          )}
        </div>
      )}

      {/* ── 步骤3：结果 ── */}
      {step === 'result' && result && (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>
            {result.failed === 0 ? '✅' : '⚠️'}
          </div>
          <p style={{ fontSize: 18, marginBottom: 8 }}>
            上传完成：成功 <b style={{ color: '#52c41a' }}>{result.success}</b> 个
            {result.failed > 0 && <span>，失败 <b style={{ color: '#ff4d4f' }}>{result.failed}</b> 个</span>}
          </p>
          {result.errors.length > 0 && (
            <div style={{ textAlign: 'left', maxHeight: 200, overflow: 'auto', background: '#fafafa', padding: 12, borderRadius: 8, marginTop: 12 }}>
              {result.errors.map((err, i) => (
                <p key={i} style={{ color: '#ff4d4f', margin: '4px 0', fontSize: 13 }}>• {err}</p>
              ))}
            </div>
          )}

          {/* ── AI 识别区域 ── */}
          {result.success > 0 && result.report_ids.length > 0 && (
            <div style={{ marginTop: 24 }}>
              {/* 进度条 */}
              {isExtracting && (
                <div style={{ marginBottom: 16 }}>
                  <Progress
                    percent={extractPercent}
                    status="active"
                    format={() => `${extract.completedIds.size} / ${extract.total}`}
                  />
                  <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                    正在识别：{extract.currentFileName}
                  </div>
                </div>
              )}

              {/* 中断状态提示 */}
              {extract.phase === 'interrupted' && (
                <div style={{
                  marginBottom: 16, padding: 12, background: '#fff7e6',
                  border: '1px solid #ffd591', borderRadius: 8, textAlign: 'left',
                }}>
                  <p style={{ margin: 0, color: '#d46b08', fontWeight: 500 }}>
                    ⚠️ 任务已中断
                  </p>
                  <p style={{ margin: '4px 0 0', color: '#888', fontSize: 13 }}>
                    已完成 {extract.completedIds.size} / {extract.total} 个报告，
                    未处理的 {extract.total - extract.completedIds.size} 个可继续识别。
                  </p>
                  <Progress
                    percent={extractPercent}
                    style={{ marginTop: 8 }}
                    size="small"
                  />
                </div>
              )}

              {/* 完成状态 */}
              {extract.phase === 'done' && successCount + failedCount > 0 && (
                <div style={{ marginBottom: 16, textAlign: 'left' }}>
                  <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
                    AI 识别完成：成功 <b style={{ color: '#52c41a' }}>{successCount}</b> 个
                    {failedCount > 0 && <span>，失败 <b style={{ color: '#ff4d4f' }}>{failedCount}</b> 个</span>}
                  </div>
                  <Progress
                    percent={extractPercent}
                    status={failedCount > 0 ? 'exception' : 'success'}
                    size="small"
                  />
                </div>
              )}

              {/* 操作按钮 */}
              <Space>
                {!isExtracting && extract.phase !== 'done' && (
                  <Button
                    type="primary"
                    icon={<span>🔍</span>}
                    onClick={handleBatchExtract}
                  >
                    {extract.phase === 'interrupted'
                      ? `继续 AI 识别（剩余 ${extract.total - extract.completedIds.size} 个）`
                      : '批量 AI 识别日期'}
                  </Button>
                )}
                {isExtracting && (
                  <Button danger onClick={handleInterrupt}>
                    中断识别
                  </Button>
                )}
                {extract.phase === 'done' && extract.total > 0 && (
                  <Button onClick={handleBatchExtract} disabled={extract.completedIds.size >= extract.total}>
                    重新识别全部
                  </Button>
                )}
              </Space>

              {/* 结果列表 */}
              {extract.results.length > 0 && (
                <div style={{ textAlign: 'left', marginTop: 16 }}>
                  <div style={{ maxHeight: 240, overflow: 'auto', background: '#fafafa', padding: 12, borderRadius: 8 }}>
                    {extract.results.map((item, i) => (
                      <p key={i} style={{ margin: '4px 0', fontSize: 13, color: item.status === 'success' ? '#333' : '#ff4d4f' }}>
                        {item.status === 'success' ? '✅' : '❌'} {item.file_name}
                        {item.status === 'success' && (
                          <span style={{ color: '#52c41a' }}>
                            &nbsp;→ 检定日期: {item.calibration_date}
                            {item.next_calibration_date && `，下次检定: ${item.next_calibration_date}`}
                          </span>
                        )}
                        {item.status === 'failed' && item.error && <span> — {item.error}</span>}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <Space style={{ marginTop: 24 }}>
            <Button onClick={handleReset}>继续上传</Button>
            <Button onClick={handleClose}>关闭</Button>
          </Space>
        </div>
      )}
    </Modal>
  )
}
