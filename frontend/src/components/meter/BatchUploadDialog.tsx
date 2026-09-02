'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { App, Modal, Button, Upload, Tag, Space, Progress } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { ReportAnalyzeItem, BatchUploadResult } from '@/types/meter'
import { analyzeReportFilesClient, batchUploadReportsClient } from '@/lib/api/meter'
import { ReportMatchTable, ReportMatchRow, isCalibrationDateValid } from '@/components/meter/ReportMatchTable'
import type { UploadFile } from 'antd/es/upload/interface'

const { Dragger } = Upload

// 识别分批大小：与后端 analyze 并发数对齐，批间串行推进进度条；
// 上传分批避免单请求体过大
const ANALYZE_BATCH_SIZE = 10
const UPLOAD_BATCH_SIZE = 50

interface Props {
  open: boolean
  source: 'instrument' | 'gas_detector'
  onClose: () => void
}

export function BatchUploadDialog({ open, source, onClose }: Props) {
  const { message } = App.useApp()
  const router = useRouter()

  const [step, setStep] = useState<'select' | 'preview' | 'result'>('select')
  const [files, setFiles] = useState<UploadFile[]>([])
  const [matches, setMatches] = useState<ReportMatchRow[]>([])
  const [matching, setMatching] = useState(false)
  const [analyzeProgress, setAnalyzeProgress] = useState<{ processed: number; total: number } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<BatchUploadResult | null>(null)

  // 请求序号：关闭/重置时递增使 in-flight 响应失效；onChange 连发时丢弃过期响应
  const seqRef = useRef(0)

  // ── 步骤1：选择文件 → 报告内容识别 + 匹配 ──
  const handleFileSelect = async (fileList: UploadFile[]) => {
    if (fileList.length === 0) return
    // 同名文件会互相覆盖（归档按文件名定位），直接拒绝
    const names = fileList.map(f => f.name)
    if (names.length !== new Set(names).size) {
      message.error('存在同名文件，请重命名后重新选择')
      return
    }
    const seq = ++seqRef.current
    setFiles(fileList)
    setMatching(true)
    setStep('preview')
    setAnalyzeProgress({ processed: 0, total: fileList.length })
    try {
      // 分批识别：每批 ANALYZE_BATCH_SIZE 个，批间串行推进进度条。
      // 好处：进度可视化、可取消、避免单请求体过大、单批失败可整体重试。
      const accumulated: ReportMatchRow[] = []
      for (let start = 0; start < fileList.length; start += ANALYZE_BATCH_SIZE) {
        if (seq !== seqRef.current) return  // 已取消/重置
        const batch = fileList.slice(start, start + ANALYZE_BATCH_SIZE)
        const formData = new FormData()
        batch.forEach(f => {
          if (f.originFileObj) {
            formData.append('files', f.originFileObj)
          }
        })
        const data = await analyzeReportFilesClient(formData, source)
        if (seq !== seqRef.current) return
        accumulated.push(
          ...data.map((d, i) => ({ ...d, _key: `${start + i}-${d.filename}` })),
        )
        // 逐批展示已识别的匹配结果，进度条同步推进
        setMatches([...accumulated])
        setAnalyzeProgress({ processed: start + batch.length, total: fileList.length })
      }
    } catch (e) {
      if (seq !== seqRef.current) return
      message.error(e instanceof Error ? `报告识别失败：${e.message}` : '报告识别失败，请重试')
      setStep('select')
    } finally {
      if (seq === seqRef.current) {
        setMatching(false)
        setAnalyzeProgress(null)
      }
    }
  }

  const handleRowChange = (key: string, patch: Partial<ReportAnalyzeItem>) => {
    setMatches(prev => prev.map(m => m._key === key ? { ...m, ...patch } : m))
  }

  // ── 步骤2：确认上传 ──
  const handleConfirmUpload = async () => {
    const matched = matches.filter(m => m.matched_id)
    const invalidDates = matched.filter(m => !isCalibrationDateValid(m.extraction.calibration_date))
    if (invalidDates.length > 0) {
      message.error(
        `以下文件校准日期格式不正确（需 YYYY-MM-DD，如 2024-03-05）：${invalidDates.map(m => m.filename).join('、')}`
      )
      return
    }
    setUploading(true)
    const seq = ++seqRef.current
    try {
      // 分批提交：每批只带本批文件（后端按文件名与 items 配对），聚合各批结果
      const fileByName = new Map(files.map(f => [f.name, f.originFileObj]))
      let success = 0
      let failed = 0
      const allErrors: string[] = []
      const allNotes: string[] = []
      const allReportIds: string[] = []
      for (let start = 0; start < matched.length; start += UPLOAD_BATCH_SIZE) {
        if (seq !== seqRef.current) return
        const batch = matched.slice(start, start + UPLOAD_BATCH_SIZE)
        const formData = new FormData()
        batch.forEach(m => {
          const f = fileByName.get(m.filename)
          if (f) formData.append('files', f)
        })
        const items = batch.map(m => ({
          filename: m.filename,
          instrument_id: m.matched_type === 'instrument' ? m.matched_id : null,
          gas_detector_id: m.matched_type === 'gas_detector' ? m.matched_id : null,
          certificate_no: m.extraction.certificate_no ?? null,
          calibration_date: m.extraction.calibration_date ?? null,
        }))
        formData.append('items_json', JSON.stringify(items))

        try {
          const res = await batchUploadReportsClient(formData)
          if (seq !== seqRef.current) return
          success += res.success
          failed += res.failed
          allErrors.push(...res.errors)
          allNotes.push(...(res.notes ?? []))
          allReportIds.push(...(res.report_ids ?? []))
        } catch (e) {
          if (seq !== seqRef.current) return
          failed += batch.length
          allErrors.push(e instanceof Error ? `批量上传失败：${e.message}` : '批量上传失败')
        }
      }

      const aggregated: BatchUploadResult = {
        success,
        failed,
        errors: allErrors,
        notes: allNotes,
        report_ids: allReportIds,
      }
      setResult(aggregated)
      setStep('result')
      router.refresh()
    } finally {
      if (seq === seqRef.current) setUploading(false)
    }
  }

  // ── 关闭重置 ──
  const handleClose = () => {
    seqRef.current++
    setStep('select')
    setFiles([])
    setMatches([])
    setResult(null)
    setMatching(false)
    setAnalyzeProgress(null)
    onClose()
  }

  const matchedCount = matches.filter(m => m.matched_id).length
  const unmatchedCount = matches.length - matchedCount

  const handleReset = () => {
    seqRef.current++
    setStep('select')
    setFiles([])
    setMatches([])
    setResult(null)
    setMatching(false)
    setAnalyzeProgress(null)
  }

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
          <p className="ant-upload-hint">系统将自动识别报告内容（仪器名称、出厂编号、校准日期、证书编号）并匹配台账</p>
        </Dragger>
      )}

      {/* ── 步骤2：匹配预览 ── */}
      {step === 'preview' && (
        <div>
          {matching && analyzeProgress ? (
            <div style={{ marginBottom: 16 }}>
              <Progress
                percent={Math.round((analyzeProgress.processed / analyzeProgress.total) * 100)}
                status="active"
                format={() =>
                  `已识别 ${analyzeProgress.processed}/${analyzeProgress.total} 个文件`
                }
              />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: 8,
                }}
              >
                <span style={{ color: '#999', fontSize: 13 }}>
                  正在识别报告内容并匹配台账，可随时取消…
                </span>
                <Button size="small" onClick={handleReset}>
                  取消识别
                </Button>
              </div>
            </div>
          ) : (
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
          )}
          <ReportMatchTable
            rows={matches}
            loading={matching}
            source={source}
            onRowChange={handleRowChange}
            invalidDateKeys={
              new Set(matches.filter(m => !isCalibrationDateValid(m.extraction.calibration_date)).map(m => m._key))
            }
          />
          {unmatchedCount > 0 && (
            <div style={{ marginTop: 8, color: '#999', fontSize: 13 }}>
              未关联的文件不会上传，请修正名称/编号后点「重新关联」，或在下拉中选择台账记录。
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
          {result.notes?.length > 0 && (
            <div style={{ textAlign: 'left', maxHeight: 200, overflow: 'auto', background: '#e6f4ff', padding: 12, borderRadius: 8, marginTop: 12 }}>
              {result.notes.map((note, i) => (
                <p key={i} style={{ color: '#1677ff', margin: '4px 0', fontSize: 13 }}>ℹ️ {note}</p>
              ))}
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
