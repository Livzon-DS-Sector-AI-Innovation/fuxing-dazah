'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, App, Button, Popconfirm, Progress, Select, Space, Table, Tag, Upload,
} from 'antd'
import { DeleteOutlined, FilePdfOutlined, ReloadOutlined, UploadOutlined, UserAddOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  convertScreeningResult, deleteScreeningResult,
  fetchJobRequirements, fetchScreeningResults, screenResumeAction,
  type ResumeScreeningResultItem, type ScreeningSection,
} from '@/actions/hr'

/** 单批上限与后端一致：控制 AI 调用时长与成本 */
const MAX_BATCH = 20

const RECO_COLOR: Record<string, string> = { 推荐: 'success', 待定: 'warning', 不推荐: 'default' }

function scoreColor(score: number): string {
  if (score >= 80) return '#52c41a'
  if (score >= 60) return '#faad14'
  return '#ff4d4f'
}

/** 上传中单份文件的状态 */
interface PendingFile {
  uid: string
  file: File
  status: 'queued' | 'running' | 'done' | 'failed'
  error?: string
}

export default function ResumeScreeningPanel() {
  const { message } = App.useApp()
  const [jobs, setJobs] = useState<{ id: string; position_name: string; department: string; status: string }[]>([])
  const [jdId, setJdId] = useState<string | null>(null)
  const [results, setResults] = useState<ResumeScreeningResultItem[]>([])
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState<PendingFile[]>([])
  const [uploading, setUploading] = useState(false)
  const runningRef = useRef(false)

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetchJobRequirements()
      setJobs(r.data || [])
    } catch { setJobs([]) }
  }, [])

  const loadResults = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const r = await fetchScreeningResults(id)
      setResults(r.data || [])
    } catch {
      setResults([])
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    void loadJobs()
  }, [loadJobs])

  useEffect(() => {
    if (jdId) void loadResults(jdId)
  }, [jdId, loadResults])

  // 逐份顺序处理：进度可见、失败不中断整批（结果列表最后统一刷新）
  const runScreening = useCallback(async (items: PendingFile[], jd: string) => {
    if (runningRef.current) return
    runningRef.current = true
    setUploading(true)
    try {
      for (const item of items) {
        if (item.status !== 'queued') continue
        setPending(prev => prev.map(p => p.uid === item.uid ? { ...p, status: 'running' } : p))
        try {
          await screenResumeAction(jd, item.file)
          setPending(prev => prev.map(p => p.uid === item.uid ? { ...p, status: 'done' } : p))
        } catch (err) {
          setPending(prev => prev.map(p => p.uid === item.uid
            ? { ...p, status: 'failed', error: err instanceof Error ? err.message : '筛选失败' } : p))
        }
      }
      await loadResults(jd)
      message.success('本批筛选完成')
    } finally {
      runningRef.current = false
      setUploading(false)
      // 清掉已完成的，保留失败项便于重试
      setPending(prev => prev.filter(p => p.status === 'failed'))
    }
  }, [loadResults, message])

  const handleFiles = (files: File[]) => {
    if (!jdId) return
    const pdfs = files.filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    const skipped = files.length - pdfs.length
    if (skipped > 0) message.warning(`已忽略 ${skipped} 个非 PDF 文件`)
    const queuedCount = pending.filter(p => p.status === 'queued' || p.status === 'running').length
    if (queuedCount + pdfs.length > MAX_BATCH) {
      message.warning(`单批最多 ${MAX_BATCH} 份，请分批上传`)
      pdfs.splice(Math.max(0, MAX_BATCH - queuedCount))
    }
    if (!pdfs.length) return
    const items: PendingFile[] = pdfs.map(f => ({
      uid: `${f.name}_${f.size}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      file: f, status: 'queued',
    }))
    setPending(prev => [...prev, ...items])
    void runScreening(items, jdId)
  }

  const retryFailed = () => {
    if (!jdId) return
    const retried = pending.map(p => p.status === 'failed' ? { ...p, status: 'queued' as const } : p)
    setPending(retried)
    void runScreening(retried, jdId)
  }

  const handleConvert = async (row: ResumeScreeningResultItem) => {
    try {
      const r = await convertScreeningResult(row.id)
      message.success(`已转为候选人「${r.data.name}」，可在「岗位招聘」中查看`)
      if (jdId) await loadResults(jdId)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '转为候选人失败')
    }
  }

  const handleDelete = async (row: ResumeScreeningResultItem) => {
    try {
      await deleteScreeningResult(row.id)
      message.success('已删除')
      if (jdId) await loadResults(jdId)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败')
    }
  }

  const columns: ColumnsType<ResumeScreeningResultItem> = [
    {
      title: '#', key: 'rank', width: 46,
      render: (_v, _r, i) => <span className="font-medium">{i + 1}</span>,
    },
    {
      title: '姓名', key: 'name', width: 90,
      render: (_v, r) => r.candidate_name || <span className="text-gray-400">未识别</span>,
    },
    { title: '简历文件', dataIndex: 'file_name', key: 'file_name', width: 180, ellipsis: true },
    {
      title: '胜任度总分', dataIndex: 'total_score', key: 'total_score', width: 110,
      sorter: (a, b) => a.total_score - b.total_score,
      render: (v: number) => (
        <span className="font-semibold" style={{ color: scoreColor(v) }}>{v}/100</span>
      ),
    },
    {
      title: '推荐档位', dataIndex: 'recommendation', key: 'recommendation', width: 90,
      filters: [
        { text: '推荐', value: '推荐' }, { text: '待定', value: '待定' }, { text: '不推荐', value: '不推荐' },
      ],
      onFilter: (value, record) => record.recommendation === value,
      render: (v: string) => <Tag color={RECO_COLOR[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '最终意见', dataIndex: 'final_verdict', key: 'final_verdict', ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '操作', key: 'action', width: 150, fixed: 'right',
      render: (_v, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<UserAddOutlined />} onClick={() => { void handleConvert(r) }}>
            转候选人
          </Button>
          <Popconfirm title="删除该筛选结果？" onConfirm={() => { void handleDelete(r) }}>
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const jd = jobs.find(j => j.id === jdId)
  const doneCount = pending.filter(p => p.status === 'done').length
  const activeCount = pending.filter(p => p.status === 'queued' || p.status === 'running' || p.status === 'failed').length

  return (
    <div className="space-y-4">
      <Alert
        type="info" showIcon
        message="选择岗位需求后批量上传 PDF 简历，AI 按岗位要求逐份打分排名，辅助初筛过滤"
        description="仅支持文字版 PDF（扫描件无法提取文本）；结果按总分降序排名，可回看历史筛选、一键转为候选人进入招聘流程。"
      />

      <div className="flex gap-3 flex-wrap items-center">
        <Select
          style={{ width: 320 }} placeholder="选择岗位需求（用人要求）"
          showSearch optionFilterProp="label"
          value={jdId} onChange={setJdId}
          options={jobs.map(j => ({
            value: j.id,
            label: `${j.position_name}（${j.department}）${j.status === '招聘中' ? '' : ' · 已关闭'}`,
          }))}
        />
        {jdId && (
          <Button icon={<ReloadOutlined />} onClick={() => { void loadResults(jdId) }} loading={loading}>
            刷新结果
          </Button>
        )}
      </div>

      {jd && jdId && (
        <>
          <Upload.Dragger
            multiple
            accept=".pdf,application/pdf"
            showUploadList={false}
            disabled={uploading}
            beforeUpload={(_file, fileList) => {
              // beforeUpload 逐个触发，用 fileList 首次触发时统一收文件
              if (_file === fileList[0]) handleFiles(fileList as unknown as File[])
              return false
            }}
          >
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p className="ant-upload-text">点击或拖拽 PDF 简历到此处（可多选，单批最多 {MAX_BATCH} 份）</p>
            <p className="ant-upload-hint">上传后自动开始逐份 AI 分析，进度在下方展示</p>
          </Upload.Dragger>

          {pending.length > 0 && (
            <div className="rounded-[var(--rounded-sm)] border border-[var(--color-hairline)] p-3 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-[13px] font-medium">
                  {uploading ? `AI 分析中…（已完成 ${doneCount}/${pending.length}）` : `待处理 ${activeCount} 份`}
                </span>
                {uploading ? (
                  <Progress percent={Math.round((doneCount / pending.length) * 100)} size="small" style={{ width: 200 }} />
                ) : (
                  pending.some(p => p.status === 'failed') && (
                    <Button size="small" onClick={retryFailed}>重试失败项</Button>
                  )
                )}
              </div>
              <div className="max-h-44 overflow-auto space-y-1">
                {pending.map(p => (
                  <div key={p.uid} className="flex items-center gap-2 text-[13px]">
                    <FilePdfOutlined className="text-[var(--color-steel)]" />
                    <span className="truncate flex-1">{p.file.name}</span>
                    {p.status === 'queued' && <Tag>排队中</Tag>}
                    {p.status === 'running' && <Tag color="processing">AI 分析中</Tag>}
                    {p.status === 'done' && <Tag color="success">完成</Tag>}
                    {p.status === 'failed' && (
                      <Tag color="error" style={{ maxWidth: 360, whiteSpace: 'normal' }}>{p.error || '失败'}</Tag>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <Table<ResumeScreeningResultItem>
            rowKey="id"
            columns={columns}
            dataSource={results}
            loading={loading}
            scroll={{ x: 1100 }}
            pagination={{ pageSize: 20, showTotal: t => `共 ${t} 份` }}
            expandable={{
              expandedRowRender: r => <ScreeningReport item={r} />,
            }}
            locale={{ emptyText: uploading ? 'AI 分析完成后展示排名' : '暂无筛选结果，上传简历开始' }}
          />
        </>
      )}
      {!jdId && (
        <div className="text-center py-8 text-[var(--color-stone)]">
          请先选择岗位需求，再上传简历
        </div>
      )}
    </div>
  )
}

// ─── 展开行：完整《岗位适配度分析+复试推荐意见》报告 ───

function SectionList({ title, sections, color }: {
  title: string
  sections: ScreeningSection[]
  color: 'green' | 'red'
}) {
  if (!sections.length) return null
  return (
    <div>
      <div className={`font-medium mb-1 ${color === 'green' ? 'text-[#389e0d]' : 'text-[#cf1322]'}`}>{title}</div>
      <div className="space-y-2">
        {sections.map((s, i) => (
          <div key={i} className="pl-2 border-l-2" style={{ borderColor: color === 'green' ? '#b7eb8f' : '#ffa39e' }}>
            {s.title && <div className="font-medium text-[13px]">{i + 1}. {s.title}</div>}
            {s.detail && <div className="text-[13px] text-[var(--color-steel)] leading-relaxed">{s.detail}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function ScreeningReport({ item }: { item: ResumeScreeningResultItem }) {
  return (
    <div className="space-y-4 max-w-4xl">
      <SectionList title="一、优势分析" sections={item.advantages} color="green" />
      <SectionList title="二、核心硬伤 / 短板" sections={item.flaws} color="red" />

      {item.score_table.length > 0 && (
        <div>
          <div className="font-medium mb-1">
            三、综合胜任度打分：<span className="font-semibold" style={{ color: scoreColor(item.total_score) }}>{item.total_score}/100</span>
          </div>
          <table className="text-[13px] border-collapse" style={{ width: '100%', maxWidth: 720 }}>
            <thead>
              <tr className="bg-[var(--color-surface)]">
                <th className="border border-[var(--color-hairline)] px-3 py-1.5 text-left">维度</th>
                <th className="border border-[var(--color-hairline)] px-3 py-1.5" style={{ width: 90 }}>得分</th>
                <th className="border border-[var(--color-hairline)] px-3 py-1.5 text-left">说明</th>
              </tr>
            </thead>
            <tbody>
              {item.score_table.map((row, i) => (
                <tr key={i}>
                  <td className="border border-[var(--color-hairline)] px-3 py-1.5">{row.dimension}</td>
                  <td className="border border-[var(--color-hairline)] px-3 py-1.5 text-center font-medium" style={{ color: scoreColor(row.score) }}>
                    {row.score}/100
                  </td>
                  <td className="border border-[var(--color-hairline)] px-3 py-1.5 text-[var(--color-steel)]">{row.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(item.final_verdict || item.final_reasons.length > 0) && (
        <div>
          <div className="font-medium mb-1">四、最终推荐意见</div>
          {item.final_verdict && (
            <div className="text-[14px] font-medium mb-1">
              <Tag color={RECO_COLOR[item.recommendation] || 'default'}>{item.recommendation}</Tag>
              {item.final_verdict}
            </div>
          )}
          {item.final_reasons.length > 0 && (
            <ol className="list-decimal pl-6 space-y-1 text-[13px] text-[var(--color-steel)]">
              {item.final_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ol>
          )}
        </div>
      )}

      <div className="text-[var(--color-stone)] text-[12px] pt-1 border-t border-[var(--color-hairline)]">
        筛选依据：{item.jd_snapshot.split('\n')[0]} · 模型 {item.model_version || '-'} · {item.created_by_name || ''} {item.created_at?.slice(0, 10) || ''}
      </div>
    </div>
  )
}
