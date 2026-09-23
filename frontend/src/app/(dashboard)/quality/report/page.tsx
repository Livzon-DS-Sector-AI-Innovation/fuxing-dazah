'use client'

import { useEffect, useState, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Typography, Table, Input, Space, App, Button, Modal, Select, Skeleton } from 'antd'
import { FileTextOutlined, DownloadOutlined, SearchOutlined, EyeOutlined } from '@ant-design/icons'
import type { ReportRecord, TemplateNode } from '@/types/quality'
import { fetchReportRecords, downloadReportFile, generateReport, fetchTemplates } from '@/actions/quality'
import { CoaPreviewModal } from '@/components/quality'

const { Title, Paragraph } = Typography

export default function ReportPage() {
  // useSearchParams 需 Suspense 边界，否则预渲染报错
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
      <ReportPageInner />
    </Suspense>
  )
}

function ReportPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const recordId = searchParams.get('recordId')
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ReportRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  // 输入草稿与已提交查询分离：只有点「搜索」/回车才发请求（此前每敲一键发一次）
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')

  // 从检验历史详情跳转：?recordId= 打开生成报告单弹窗（此前为死链）
  const [genOpen, setGenOpen] = useState(false)
  const [genTemplates, setGenTemplates] = useState<{ label: string; value: string }[]>([])
  const [genTemplate, setGenTemplate] = useState<string>()
  const [generating, setGenerating] = useState(false)

  // 在线预览
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = useState('')

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await fetchReportRecords(search || undefined, undefined, p)
      setData(res.data)
      setTotal(res.meta.total)
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }, [search, message])

  useEffect(() => { (async () => { await load(page) })() }, [page, load])

  const openGenModal = useCallback(async () => {
    setGenOpen(true)
    try {
      const tpls = await fetchTemplates()
      const files: { label: string; value: string }[] = []
      const walk = (nodes: TemplateNode[], prefix = '') => {
        for (const n of nodes || []) {
          if (n.children) walk(n.children, `${prefix}${n.name}/`)
          else files.push({ label: `${prefix}${n.name}`, value: `${prefix}${n.name}` })
        }
      }
      walk(tpls)
      setGenTemplates(files)
      setGenTemplate(files[0]?.value)
    } catch {
      message.error('模板列表加载失败')
    }
  }, [message])

  useEffect(() => {
    (async () => { if (recordId) await openGenModal() })()
  }, [recordId, openGenModal])

  const handleGenerate = async () => {
    if (!recordId || !genTemplate) {
      message.warning('请选择模板')
      return
    }
    setGenerating(true)
    try {
      const { filename, base64 } = await generateReport(recordId, genTemplate)
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
      const blob = new Blob([bytes], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      message.success('报告单已生成')
      setGenOpen(false)
      setPage(1)
      load(1)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '生成报告单失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownload = async (r: ReportRecord) => {
    try {
      const blob = await downloadReportFile(r.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `COA-${r.batch_number}.docx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败')
    }
  }

  const columns = [
    { title: '流水号', dataIndex: 'serial_no', key: 'serial_no', width: 110,
      render: (v: string | null) => v || '-' },
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 150 },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 120 },
    { title: '模板', dataIndex: 'template_path', key: 'template_path', ellipsis: true },
    { title: '文件大小', dataIndex: 'file_size', key: 'file_size', width: 100,
      render: (v: number) => v ? `${(v / 1024).toFixed(1)} KB` : '-' },
    { title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '操作', key: 'actions', width: 210,
      render: (_: unknown, r: ReportRecord) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />}
            onClick={() => { setPreviewId(r.id); setPreviewTitle(`报告单预览（批号 ${r.batch_number}）`) }}
            disabled={!r.file_path}>
            预览
          </Button>
          <Button size="small" icon={<DownloadOutlined />}
            onClick={() => handleDownload(r)} disabled={!r.file_path}>
            下载
          </Button>
          {r.test_task_id && (
            <Button size="small" type="link"
              onClick={() => router.push(`/quality/task/${r.test_task_id}`)}>
              查看任务
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Title level={3}><FileTextOutlined /> COA 报告单</Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        管理已生成的检验报告单（COA），支持下载历史报告。
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="搜索产品名称" allowClear value={searchDraft}
          onChange={e => setSearchDraft(e.target.value)}
          onPressEnter={() => { setSearch(searchDraft); setPage(1) }}
          style={{ width: 200 }} prefix={<SearchOutlined />} />
        <Button type="primary" onClick={() => { setSearch(searchDraft); setPage(1) }}>搜索</Button>
      </Space>

      <Table columns={columns}
        dataSource={data.map(r => ({ ...r, key: r.id }))}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small" />

      <Modal
        title="生成报告单"
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        onOk={handleGenerate}
        confirmLoading={generating}
        okText="生成并下载"
        cancelText="取消"
      >
        <Select
          style={{ width: '100%' }}
          placeholder="选择 COA 模板"
          value={genTemplate}
          onChange={setGenTemplate}
          options={genTemplates}
          showSearch
          optionFilterProp="label"
        />
      </Modal>

      <CoaPreviewModal
        open={!!previewId}
        reportId={previewId}
        title={previewTitle}
        onClose={() => setPreviewId(null)}
      />
    </div>
  )
}
