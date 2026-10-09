'use client'

import { useEffect, useState, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Typography, Table, Input, Space, App, Button, Modal, Select, Skeleton, Tag } from 'antd'
import { FileTextOutlined, DownloadOutlined, SearchOutlined, EyeOutlined } from '@ant-design/icons'
import type { ReportRecord, TemplateNode } from '@/types/quality'
import { fetchReportRecords, downloadReportFile, generateReport, fetchTemplates } from '@/actions/quality'
import { CoaPreviewModal } from '@/components/quality'
import { usePermission } from '@/hooks/usePermission'
import { REPORT_AUDIT_META } from '@/types/quality'
import type { ReportAuditStatus } from '@/types/quality'
import { auditReport, fetchReportConsistency } from '@/actions/quality'

const { Title, Paragraph, Text } = Typography

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
  const { hasPermission } = usePermission()
  const canAudit = hasPermission('quality:report:audit')
  const [auditTarget, setAuditTarget] = useState<ReportRecord | null>(null)
  const [auditComment, setAuditComment] = useState('')
  const [auditing, setAuditing] = useState(false)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ReportRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  // 输入草稿与已提交查询分离：只有点「搜索」/回车才发请求（此前每敲一键发一次）
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [batchDraft, setBatchDraft] = useState('')
  const [batchSearch, setBatchSearch] = useState('')
  const [auditFilter, setAuditFilter] = useState<string | undefined>(
    () => searchParams.get('audit_status') || undefined
  )
  const [consistency, setConsistency] = useState<{ parsed_mismatches: { item_name: string; report_value: number; parsed_value: number }[]; standard_drifts: { item_name: string; snapshot_text: string | null; current_text: string | null }[] } | null>(null)

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
      const res = await fetchReportRecords(search || undefined, batchSearch || undefined, p, auditFilter)
      setData(res.data)
      setTotal(res.meta.total)
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }, [search, batchSearch, auditFilter, message])

  useEffect(() => { (async () => { await load(page) })() }, [page, load])

  const openGenModal = useCallback(async () => {
    setGenOpen(true)
    try {
      const tpls = await fetchTemplates()
      const files: { label: string; value: string }[] = []
      const walk = (nodes: TemplateNode[], prefix = '') => {
        for (const n of nodes || []) {
          if (n.children) walk(n.children, `${prefix}${n.name}/`)
          // 文件节点字段是 filename（name 仅文件夹有）——此前取 n.name 恒为 undefined
          else files.push({ label: `${prefix}${n.filename ?? ''}`, value: `${prefix}${n.filename ?? ''}` })
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

  const handleAudit = async (action: 'approve' | 'reject') => {
    if (!auditTarget) return
    setAuditing(true)
    try {
      await auditReport(auditTarget.id, action, auditComment || undefined)
      message.success(action === 'approve' ? '审核已通过' : '报告单已退回')
      setAuditTarget(null)
      setAuditComment('')
      load(page)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '审核提交失败')
    } finally {
      setAuditing(false)
    }
  }

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
    { title: '审核', dataIndex: 'audit_status', key: 'audit_status', width: 90,
      render: (v: ReportAuditStatus) => {
        const meta = REPORT_AUDIT_META[v] ?? { color: 'default', label: v }
        return <Tag color={meta.color}>{meta.label}</Tag>
      } },
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
          {canAudit && r.task_status !== null && r.audit_status === 'pending' && (
            <Button size="small" type="primary" ghost
              onClick={async () => {
                setAuditTarget(r)
                setAuditComment('')
                try {
                  const res = await fetchReportConsistency(r.id)
                  setConsistency(res.data)
                } catch {
                  setConsistency(null)
                }
              }}>审核</Button>
          )}
          <Button size="small" icon={<EyeOutlined />}
            onClick={() => { setPreviewId(r.id); setPreviewTitle(`报告单预览（批号 ${r.batch_number}）`) }}
            disabled={!r.file_path}>
            预览
          </Button>
          <Button size="small" icon={<DownloadOutlined />}
            onClick={() => handleDownload(r)} disabled={!r.file_path}>
            下载
          </Button>
          {r.test_task_id && r.task_status !== null && (
            <Button size="small" type="link"
              onClick={() => router.push(`/quality/task/${r.test_task_id}`)}>
              查看任务
            </Button>
          )}
          {r.test_task_id && r.task_status === null && (
            <Text type="secondary" style={{ fontSize: 12 }}>任务已删除</Text>
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
        <Select
          placeholder="审核状态"
          allowClear
          style={{ width: 120 }}
          value={auditFilter}
          onChange={(v) => { setAuditFilter(v); setPage(1) }}
          options={[
            { label: '待初审', value: 'pending' },
            { label: '已通过', value: 'approved' },
            { label: '已退回', value: 'rejected' },
          ]}
        />
        <Input placeholder="批号" allowClear value={batchDraft}
          onChange={e => setBatchDraft(e.target.value)}
          onPressEnter={() => { setBatchSearch(batchDraft); setPage(1) }}
          style={{ width: 160 }} />
        <Button type="primary" onClick={() => { setSearch(searchDraft); setBatchSearch(batchDraft); setPage(1) }}>搜索</Button>
      </Space>

      <Table columns={columns} scroll={{ x: 960 }}
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

      <Modal
        title={`报告单审核（${auditTarget?.serial_no ?? ''}｜批号 ${auditTarget?.batch_number ?? ''}）`}
        open={!!auditTarget}
        onCancel={() => setAuditTarget(null)}
        footer={[
          <Button key="cancel" onClick={() => setAuditTarget(null)}>取消</Button>,
          <Button key="reject" danger loading={auditing}
            onClick={() => handleAudit('reject')}>退回</Button>,
          <Button key="approve" type="primary" loading={auditing}
            onClick={() => handleAudit('approve')}>通过</Button>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary">
            审核前请先在任务详情比对原始证据（计算表/图谱）；可先点「预览」查看报告单内容。
          </Text>
          <Space>
            <Button size="small" icon={<EyeOutlined />}
              onClick={() => auditTarget && setPreviewId(auditTarget.id)}>
              预览报告单
            </Button>
            {auditTarget?.test_task_id && (
              <Button size="small" onClick={() => router.push(`/quality/task/${auditTarget.test_task_id}`)}>
                打开任务原始证据
              </Button>
            )}
          </Space>
          {consistency && (
            <div style={{ border: '1px solid #faad14', borderRadius: 4, padding: 8 }}>
              {consistency.parsed_mismatches.length === 0 && consistency.standard_drifts.length === 0 ? (
                <Text type="success" style={{ display: 'block' }}>✅ 一致性校验通过</Text>
              ) : (
                <>
                  {consistency.parsed_mismatches.length > 0 && (
                    <Text type="warning" style={{ display: 'block' }}>
                      ⚠️ 填报值与解析记录不一致 {consistency.parsed_mismatches.length} 项：
                      {consistency.parsed_mismatches.map((m) => `${m.item_name}（填报 ${m.report_value} / 解析 ${m.parsed_value}）`).join('；')}
                    </Text>
                  )}
                  {consistency.standard_drifts.length > 0 && (
                    <Text type="warning" style={{ display: 'block' }}>
                      ⚠️ 任务快照与现行标准不一致 {consistency.standard_drifts.length} 项：
                      {consistency.standard_drifts.map((d) => `${d.item_name}（快照 ${d.snapshot_text} / 现行 ${d.current_text}）`).join('；')}
                    </Text>
                  )}
                </>
              )}
            </div>
          )}
          <Input.TextArea
            rows={3}
            placeholder="审核备注（退回时请填写原因）"
            value={auditComment}
            onChange={(e) => setAuditComment(e.target.value)}
          />
        </Space>
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
