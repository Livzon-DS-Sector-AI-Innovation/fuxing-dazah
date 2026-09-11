'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { App, Modal, Tabs, Table, Button, Space, Upload, Popconfirm, Image, Tooltip, Input } from 'antd'
import { UploadOutlined, DownloadOutlined, DeleteOutlined, InboxOutlined, EyeOutlined, CalendarOutlined, EditOutlined } from '@ant-design/icons'
import type { TableColumnsType, UploadFile } from 'antd'
import { ReportResponse, ReportAnalyzeItem, InstrumentRecord, GasDetectorRecord } from '@/types/meter'
import {
  getReportsByInstrument, getReportsByGasDetector,
  deleteReport, uploadReport, extractDate, updateReport,
} from '@/actions/meter'
import { reportDownloadUrl, reportPreviewUrl, analyzeReportFilesClient, batchUploadReportsClient } from '@/lib/api/meter'
import { ReportMatchTable, ReportMatchRow, isCalibrationDateValid } from '@/components/meter/ReportMatchTable'
import dayjs from 'dayjs'
import dynamic from 'next/dynamic'

const PdfViewer = dynamic(() => import('./PdfViewer'), { ssr: false })

const { Dragger } = Upload

// 识别分批大小：与后端 analyze 并发数对齐；上传分批避免单请求体过大
const ANALYZE_BATCH_SIZE = 10
const UPLOAD_BATCH_SIZE = 50

interface Props {
  open: boolean
  record: InstrumentRecord | GasDetectorRecord | null
  source: 'instrument' | 'gas_detector'
  onClose: () => void
}

export function ReportDialog({ open, record, source, onClose }: Props) {
  const { message } = App.useApp()
  const router = useRouter()
  const [reports, setReports] = useState<ReportResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('history')

  // 批量上传状态
  const [batchFiles, setBatchFiles] = useState<UploadFile[]>([])
  const [matchResults, setMatchResults] = useState<ReportMatchRow[]>([])
  const [matching, setMatching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [previewImage, setPreviewImage] = useState<string | null>(null)

  // 请求序号：关闭时递增使 in-flight 响应失效
  const seqRef = useRef(0)

  // 编辑证书编号
  const [certEdit, setCertEdit] = useState<ReportResponse | null>(null)
  const [certValue, setCertValue] = useState('')
  const [certSaving, setCertSaving] = useState(false)

  const handleSaveCertificateNo = async () => {
    if (!certEdit || certSaving) return
    setCertSaving(true)
    try {
      await updateReport(certEdit.id, certValue.trim() || null)
      message.success('证书编号已更新')
      setCertEdit(null)
      fetchReports()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '更新失败')
    } finally {
      setCertSaving(false)
    }
  }

  // PDF 预览
  const [pdfModalOpen, setPdfModalOpen] = useState(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfTitle, setPdfTitle] = useState('')

  const fetchReports = useCallback(async () => {
    if (!record) return
    setLoading(true)
    try {
      const data = source === 'instrument'
        ? await getReportsByInstrument(record.id)
        : await getReportsByGasDetector(record.id)
      setReports(data || [])
    } catch {
      message.error('获取报告列表失败')
    } finally {
      setLoading(false)
    }
  }, [record, source, message])

  useEffect(() => {
    if (open && record) { fetchReports() }
  }, [open, record, fetchReports])

  // 关闭重置：防止上一台器具的批量上传状态泄漏到下一台器具的弹窗
  const handleClose = () => {
    seqRef.current++
    setBatchFiles([])
    setMatchResults([])
    setCertEdit(null)
    setPreviewImage(null)
    setActiveTab('history')
    onClose()
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteReport(id)
      message.success('删除成功')
      fetchReports()
    } catch {
      message.error('删除失败')
    }
  }

  // 单文件上传
  const handleSingleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    if (source === 'instrument') {
      formData.append('instrument_id', record!.id)
    } else {
      formData.append('gas_detector_id', record!.id)
    }
    try {
      const res = await uploadReport(formData)
      message.success('上传成功')
      fetchReports()
      // PDF 文件上传后询问是否 AI 识别
      if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        Modal.confirm({
          title: 'AI 识别日期',
          content: '是否使用 AI 识别该报告中的校准日期，自动更新对应仪表？',
          okText: '识别',
          cancelText: '暂不',
          onOk: async () => {
            try {
              const extractRes = await extractDate(res.id)
              if (extractRes.success) {
                message.success(`已更新检定日期: ${extractRes.calibration_date}，下次检定: ${extractRes.next_calibration_date || '—'}`)
                fetchReports()
              } else {
                message.warning(extractRes.error || '未识别到日期')
              }
            } catch (e: unknown) {
              message.error(e instanceof Error ? e.message : '识别失败')
            }
          },
        })
      }
    } catch {
      message.error('上传失败')
    }
    return false
  }

  // 批量上传：选择文件后识别报告内容并匹配
  const handleBatchSelect = async (files: UploadFile[]) => {
    if (files.length === 0) return
    const names = files.map(f => f.name)
    if (names.length !== new Set(names).size) {
      message.error('存在同名文件，请重命名后重新选择')
      return
    }
    const seq = ++seqRef.current
    setBatchFiles(files)
    setMatchResults([])
    setMatching(true)
    try {
      // 分批识别：避免单请求体过大，批间检查 seq 支持关闭时中止
      const accumulated: ReportMatchRow[] = []
      for (let start = 0; start < files.length; start += ANALYZE_BATCH_SIZE) {
        if (seq !== seqRef.current) return
        const batch = files.slice(start, start + ANALYZE_BATCH_SIZE)
        const formData = new FormData()
        batch.forEach(f => {
          if (f.originFileObj) {
            formData.append('files', f.originFileObj)
          }
        })
        const results = await analyzeReportFilesClient(formData, source)
        if (seq !== seqRef.current) return
        accumulated.push(...results.map((d, i) => ({ ...d, _key: `${start + i}-${d.filename}` })))
        setMatchResults([...accumulated])
      }
    } catch (e) {
      if (seq !== seqRef.current) return
      message.error(e instanceof Error ? `报告识别失败：${e.message}` : '报告识别失败，请重试')
    } finally {
      if (seq === seqRef.current) setMatching(false)
    }
  }

  const handleRowChange = (key: string, patch: Partial<ReportAnalyzeItem>) => {
    setMatchResults(prev => prev.map(r => r._key === key ? { ...r, ...patch } : r))
  }

  // 确认批量上传
  const handleBatchConfirm = async () => {
    const matched = matchResults.filter(r => r.matched_id)
    if (!matched.length) return
    const invalidDates = matched.filter(r => !isCalibrationDateValid(r.extraction.calibration_date))
    if (invalidDates.length > 0) {
      message.error(
        `以下文件校准日期格式不正确（需 YYYY-MM-DD，如 2024-03-05）：${invalidDates.map(r => r.filename).join('、')}`
      )
      return
    }
    setUploading(true)
    const seq = ++seqRef.current
    try {
      // 分批提交：每批只带本批文件（后端按文件名与 items 配对），聚合各批结果
      const fileByName = new Map(batchFiles.map(f => [f.name, f.originFileObj]))
      let success = 0
      let failed = 0
      const allErrors: string[] = []
      const allNotes: string[] = []
      for (let start = 0; start < matched.length; start += UPLOAD_BATCH_SIZE) {
        if (seq !== seqRef.current) return
        const batch = matched.slice(start, start + UPLOAD_BATCH_SIZE)
        const formData = new FormData()
        batch.forEach(r => {
          const f = fileByName.get(r.filename)
          if (f) formData.append('files', f)
        })
        const items = batch.map(r => ({
          filename: r.filename,
          instrument_id: r.matched_type === 'instrument' ? r.matched_id : null,
          gas_detector_id: r.matched_type === 'gas_detector' ? r.matched_id : null,
          certificate_no: r.extraction.certificate_no ?? null,
          calibration_date: r.extraction.calibration_date ?? null,
        }))
        formData.append('items_json', JSON.stringify(items))

        try {
          const result = await batchUploadReportsClient(formData)
          if (seq !== seqRef.current) return
          success += result.success
          failed += result.failed
          allErrors.push(...result.errors)
          allNotes.push(...(result.notes ?? []))
        } catch (e) {
          if (seq !== seqRef.current) return
          failed += batch.length
          allErrors.push(e instanceof Error ? `批量上传失败：${e.message}` : '批量上传失败')
        }
      }

      message.success(`上传完成：成功 ${success} 个，失败 ${failed} 个`)
      if (allErrors.length > 0) {
        message.warning(allErrors.slice(0, 5).join('; '))
      }
      if (allNotes.length > 0) {
        message.info(allNotes.slice(0, 5).join('; '))
      }
      setBatchFiles([])
      setMatchResults([])
      fetchReports()
      router.refresh()
    } finally {
      if (seq === seqRef.current) setUploading(false)
    }
  }

  const recordLabel = record
    ? 'asset_number' in record
      ? `${record.instrument_name} [${record.asset_number}]`
      : `${record.instrument_name} [${(record as GasDetectorRecord).product_number || record.id}]`
    : ''

  const isImage = (ct?: string | null) => ct?.startsWith('image/')
  const isPdf = (ct?: string | null) => ct === 'application/pdf'

  const handlePreview = (r: ReportResponse) => {
    if (isImage(r.content_type)) {
      setPreviewImage(reportPreviewUrl(r.id))
    } else {
      setPdfTitle(r.file_name)
      setPdfUrl(reportPreviewUrl(r.id))
      setPdfModalOpen(true)
    }
  }

  const handleExtractDate = async (r: ReportResponse) => {
    if (!isPdf(r.content_type)) { message.warning('仅支持 PDF 文件'); return }
    try {
      const result = await extractDate(r.id)
      if (result.success) {
        message.success(`已更新检定日期: ${result.calibration_date}，下次检定: ${result.next_calibration_date || '—'}`)
        fetchReports()
      } else {
        message.warning(result.error || '未识别到日期')
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '提取日期失败')
    }
  }

  const columns: TableColumnsType<ReportResponse> = [
    { title: '文件名', dataIndex: 'file_name', ellipsis: true },
    {
      title: '证书编号', dataIndex: 'certificate_no', width: 170, ellipsis: true,
      render: (v: string | null, r: ReportResponse) => (
        <Space size="small">
          <span>{v || '-'}</span>
          <Button
            size="small"
            type="text"
            icon={<EditOutlined />}
            onClick={() => { setCertEdit(r); setCertValue(v ?? '') }}
          />
        </Space>
      ),
    },
    { title: '大小', dataIndex: 'file_size', width: 80, render: (v: number) => v ? `${(v / 1024).toFixed(0)} KB` : '-' },
    {
      title: '报告日期', dataIndex: 'report_date', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    { title: '备注', dataIndex: 'remark', width: 100, ellipsis: true },
    {
      title: '上传时间', dataIndex: 'uploaded_at', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: unknown, r: ReportResponse) => {
        const canPreview = isImage(r.content_type) || isPdf(r.content_type)
        return (
        <div style={{ overflowX: 'auto', whiteSpace: 'nowrap', cursor: 'grab' }}>
          <Space size="small">
            {canPreview ? (
              <Button size="small" icon={<EyeOutlined />} onClick={() => handlePreview(r)}>预览</Button>
            ) : (
              <Tooltip title="此格式不支持预览，请下载查看">
                <Button size="small" icon={<EyeOutlined />} disabled>预览</Button>
              </Tooltip>
            )}
            <a href={reportDownloadUrl(r.id)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<DownloadOutlined />}>下载</Button>
            </a>
            {isPdf(r.content_type) && (
              <Tooltip title="用 AI 识别校准日期并自动更新仪表">
                <Button size="small" icon={<CalendarOutlined />} onClick={() => handleExtractDate(r)}>提取日期</Button>
              </Tooltip>
            )}
            <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
              <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          </Space>
        </div>
        )
      },
    },
  ]

  const matchedCount = matchResults.filter(r => r.matched_id).length
  const invalidDateKeys = new Set(
    matchResults.filter(r => !isCalibrationDateValid(r.extraction.calibration_date)).map(r => r._key)
  )

  return (
    <>
    <Modal
      title={`报告管理 — ${recordLabel}`}
      open={open}
      onCancel={handleClose}
      width={900}
      footer={null}
      destroyOnHidden
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab}
        items={[
          {
            key: 'history',
            label: '历次报告',
            children: (
              <Table
                rowKey="id" columns={columns} dataSource={reports}
                loading={loading} size="small"
                pagination={{ showTotal: (t) => `共 ${t} 份` }}
              />
            ),
          },
          {
            key: 'upload',
            label: '上传报告',
            children: (
              <div>
                <h4 style={{ marginBottom: 12 }}>单文件上传</h4>
                <Upload
                  beforeUpload={handleSingleUpload}
                  showUploadList={false}
                  accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                >
                  <Button icon={<UploadOutlined />}>选择文件上传（最大50MB）</Button>
                </Upload>

                <h4 style={{ marginTop: 24, marginBottom: 12 }}>批量上传</h4>
                <Dragger
                  multiple
                  beforeUpload={() => false}
                  fileList={batchFiles}
                  onChange={(info) => handleBatchSelect(info.fileList)}
                  showUploadList={false}
                  accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽文件到此区域</p>
                  <p className="ant-upload-hint">支持 PDF、图片、Word 文档，单文件最大 50MB</p>
                  <p className="ant-upload-hint">系统将自动识别报告内容（仪器名称、出厂编号、校准日期、证书编号）并匹配台账</p>
                </Dragger>

                {matching && <div style={{ marginTop: 12 }}>正在识别报告内容并匹配...</div>}

                {matchResults.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                      <span>匹配结果（{matchedCount}/{matchResults.length} 已匹配）</span>
                      <Button
                        type="primary"
                        loading={uploading}
                        disabled={matchedCount === 0}
                        onClick={handleBatchConfirm}
                      >
                        确认批量上传（{matchedCount} 个）
                      </Button>
                    </div>
                    <ReportMatchTable rows={matchResults} loading={matching} source={source} onRowChange={handleRowChange} invalidDateKeys={invalidDateKeys} />
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />

      {/* 证书编号编辑弹窗 */}
      <Modal
        title="编辑证书编号"
        open={!!certEdit}
        onCancel={() => setCertEdit(null)}
        onOk={handleSaveCertificateNo}
        confirmLoading={certSaving}
        okText="保存"
        width={420}
        destroyOnHidden
      >
        <Input
          placeholder="证书编号（留空清除）"
          value={certValue}
          onChange={(e) => setCertValue(e.target.value)}
          onPressEnter={handleSaveCertificateNo}
        />
      </Modal>

      <Image
        style={{ display: 'none' }}
        preview={{
          open: !!previewImage,
          src: previewImage || '',
          onOpenChange: (v) => { if (!v) setPreviewImage(null) },
        }}
      />
    </Modal>

    {/* PDF 预览弹窗 */}
    <Modal
      title={`预览 — ${pdfTitle}`}
      open={pdfModalOpen}
      onCancel={() => { setPdfModalOpen(false); setPdfUrl(null) }}
      width={900}
      footer={null}
      destroyOnHidden
    >
      <div style={{ display: 'flex', justifyContent: 'center', minHeight: 400 }}>
        {pdfUrl && <PdfViewer url={pdfUrl} />}
      </div>
    </Modal>
    </>
  )
}
