'use client'

import { useCallback, useEffect, useState } from 'react'
import { message, Modal, Tabs, Table, Button, Space, Upload, Tag, Popconfirm, Image, Tooltip } from 'antd'
import { UploadOutlined, DownloadOutlined, DeleteOutlined, InboxOutlined, EyeOutlined, CalendarOutlined } from '@ant-design/icons'
import type { TableColumnsType, UploadFile } from 'antd'
import { ReportResponse, FileMatchItem, InstrumentRecord, GasDetectorRecord } from '@/types/meter'
import {
  getReportsByInstrument, getReportsByGasDetector,
  deleteReport, uploadReport, matchReportFiles, batchUploadReports, extractDate,
} from '@/actions/meter'
import { reportDownloadUrl, reportPreviewUrl } from '@/lib/api/meter'
import dayjs from 'dayjs'
import dynamic from 'next/dynamic'

const PdfViewer = dynamic(() => import('./PdfViewer'), { ssr: false })

const { Dragger } = Upload

interface Props {
  open: boolean
  record: InstrumentRecord | GasDetectorRecord | null
  source: 'instrument' | 'gas_detector'
  onClose: () => void
}

export function ReportDialog({ open, record, source, onClose }: Props) {
  const [reports, setReports] = useState<ReportResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('history')

  // 批量上传状态
  const [batchFiles, setBatchFiles] = useState<UploadFile[]>([])
  const [matchResults, setMatchResults] = useState<FileMatchItem[]>([])
  const [matching, setMatching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [previewImage, setPreviewImage] = useState<string | null>(null)

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
    if (open && record) { fetchReports(); setActiveTab('history') }
  }, [open, record, fetchReports])

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
            } catch (e: any) {
              message.error(e?.message || '识别失败')
            }
          },
        })
      }
    } catch {
      message.error('上传失败')
    }
    return false
  }

  // 批量上传：选择文件后触发匹配
  const handleBatchSelect = async (files: UploadFile[]) => {
    setBatchFiles(files)
    setMatchResults([])
    setMatching(true)
    try {
      const filenames = files.map(f => f.name)
      const results = await matchReportFiles(filenames)
      setMatchResults(results)
    } catch {
      message.error('文件匹配失败')
    } finally {
      setMatching(false)
    }
  }

  // 确认批量上传
  const handleBatchConfirm = async () => {
    if (!matchResults.length) return
    setUploading(true)
    try {
      const formData = new FormData()
      batchFiles.forEach(f => {
        if (f.originFileObj) {
          formData.append('files', f.originFileObj)
        }
      })
      const items = matchResults.map(r => ({
        filename: r.filename,
        instrument_id: r.matched_type === 'instrument' ? r.matched_id : null,
        gas_detector_id: r.matched_type === 'gas_detector' ? r.matched_id : null,
      }))
      formData.append('items_json', JSON.stringify(items))

      const result = await batchUploadReports(formData)
      message.success(`上传完成：成功 ${result.success} 个，失败 ${result.failed} 个`)
      if (result.errors.length > 0) {
        message.warning(result.errors.slice(0, 5).join('; '))
      }
      setBatchFiles([])
      setMatchResults([])
      fetchReports()
    } catch {
      message.error('批量上传失败')
    } finally {
      setUploading(false)
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
      } else {
        message.warning(result.error || '未识别到日期')
      }
    } catch (e: any) {
      message.error(e?.message || '提取日期失败')
    }
  }

  const columns: TableColumnsType<ReportResponse> = [
    { title: '文件名', dataIndex: 'file_name', ellipsis: true },
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

  const matchColumns: TableColumnsType<FileMatchItem> = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    {
      title: '匹配结果', dataIndex: 'matched_name', width: 220, ellipsis: true,
      render: (v: string | null | undefined, r: FileMatchItem) => {
        if (v) return <Tag color="green">{v}</Tag>
        return <Tag color="red">未匹配</Tag>
      },
    },
    { title: '部门', dataIndex: 'matched_department', width: 120, ellipsis: true },
  ]

  return (
    <>
    <Modal
      title={`报告管理 — ${recordLabel}`}
      open={open}
      onCancel={onClose}
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
                  onChange={(info) => handleBatchSelect(info.fileList)}
                  showUploadList={false}
                  accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽文件到此区域</p>
                  <p className="ant-upload-hint">支持 PDF、图片、Word 文档，单文件最大 50MB</p>
                  <p className="ant-upload-hint">文件名格式：{source === 'instrument' ? '器具名称_器具编号' : '器具名称_产品编号'}.pdf</p>
                </Dragger>

                {matching && <div style={{ marginTop: 12 }}>正在匹配文件...</div>}

                {matchResults.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                      <span>匹配结果（{matchResults.filter(r => r.matched_id).length}/{matchResults.length} 已匹配）</span>
                      <Button type="primary" loading={uploading} onClick={handleBatchConfirm}>
                        确认批量上传
                      </Button>
                    </div>
                    <Table
                      rowKey="filename" columns={matchColumns} dataSource={matchResults}
                      size="small" pagination={false} scroll={{ y: 300 }}
                    />
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />

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
