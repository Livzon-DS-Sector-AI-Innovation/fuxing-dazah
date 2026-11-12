'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, App, Button, Popconfirm, Progress, Select, Space, Table, Tag, Upload,
} from 'antd'
import { CopyOutlined, DeleteOutlined, FilePdfOutlined, ReloadOutlined, UploadOutlined, UserAddOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  convertScreeningResult, deleteScreeningResult,
  fetchJobRequirements, fetchScreeningResults, screenResumeAction,
  type CandidateProfile, type ResumeScreeningResultItem, type ScreeningSection,
} from '@/actions/hr'

/** 单批上限与后端一致：控制 AI 调用时长与成本 */
const MAX_BATCH = 20

/** 配色对齐候选人列表（RecruitmentClient）：强烈推荐绿、推荐蓝 */
const RECO_COLOR: Record<string, string> = {
  强烈推荐: 'success', 推荐: 'processing', 待定: 'warning', 不推荐: 'default',
}

/** 人才分类（对齐飞书 AI 直聘筛选表） */
const TALENT_LABEL: Record<string, string> = {
  A: 'A类-关键人才', B: 'B类-潜力人才', C: 'C类-普通简历',
}
const TALENT_COLOR: Record<string, string> = { A: 'gold', B: 'geekblue', C: 'default' }

/** 打分四组固定框架的展示顺序（兼作能力维度评估的分组键） */
type AssessmentGroup = keyof ResumeScreeningResultItem['dimension_assessment']
const GROUP_ORDER: AssessmentGroup[] = ['专业能力', '基础匹配', '发展潜力', '软实力']

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
      message.success(`已转为候选人「${r.data.name}」并回填档案与推荐等级，可在「岗位招聘」中查看`)
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
    { title: '简历文件', dataIndex: 'file_name', key: 'file_name', width: 160, ellipsis: true },
    {
      title: '档案摘要', key: 'profile', width: 170, ellipsis: true,
      render: (_v, r) => {
        const p = r.candidate_profile || {}
        const parts = [
          p.education, p.work_years != null ? `${p.work_years}年` : undefined, p.intended_city,
        ].filter(Boolean)
        return parts.length
          ? parts.join(' · ')
          : <span className="text-gray-400">-</span>
      },
    },
    {
      title: '人才分类', dataIndex: 'talent_category', key: 'talent_category', width: 84,
      filters: [
        { text: 'A类-关键人才', value: 'A' }, { text: 'B类-潜力人才', value: 'B' }, { text: 'C类-普通简历', value: 'C' },
      ],
      onFilter: (value, record) => record.talent_category === value,
      render: (v: string | null) => v ? (
        <Tag color={TALENT_COLOR[v] || 'default'} title={TALENT_LABEL[v] || ''}>{v}类</Tag>
      ) : <span className="text-gray-400">-</span>,
    },
    {
      title: '胜任度总分', dataIndex: 'total_score', key: 'total_score', width: 104,
      sorter: (a, b) => a.total_score - b.total_score,
      render: (v: number) => (
        <span className="font-semibold" style={{ color: scoreColor(v) }}>{v}/100</span>
      ),
    },
    {
      title: '推荐档位', dataIndex: 'recommendation', key: 'recommendation', width: 92,
      filters: [
        { text: '强烈推荐', value: '强烈推荐' },
        { text: '推荐', value: '推荐' },
        { text: '待定', value: '待定' },
        { text: '不推荐', value: '不推荐' },
      ],
      onFilter: (value, record) => record.recommendation === value,
      render: (v: string) => <Tag color={RECO_COLOR[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '核心评价', dataIndex: 'core_evaluation', key: 'core_evaluation', ellipsis: true,
      render: (v: string | null) => v || <span className="text-gray-400">-</span>,
    },
    {
      title: '操作', key: 'action', width: 150, fixed: 'right',
      render: (_v, r) => (
        <Space size={4}>
          {r.candidate_id ? (
            // 岗位侧存量简历直接初筛：候选人已存在，无需再转
            <Tag title="岗位侧直接初筛的结果，候选人档案已回写">已关联候选人</Tag>
          ) : (
            <Button type="link" size="small" icon={<UserAddOutlined />} onClick={() => { void handleConvert(r) }}>
              转候选人
            </Button>
          )}
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
            scroll={{ x: 1300 }}
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

// ─── 展开行：候选人匹配度报告（对齐 AI 直聘表）+ 适配度分析 ───

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

/** 四组维度评估配色对齐 AI 直聘表：专业能力-核心(红)/基础匹配-基础(绿)/发展潜力-潜力(橙)/软实力(紫) */
const GROUP_STYLE: Record<string, { color: string; tag: string }> = {
  专业能力: { color: '#cf1322', tag: '核心' },
  基础匹配: { color: '#389e0d', tag: '基础' },
  发展潜力: { color: '#d46b08', tag: '潜力' },
  软实力: { color: '#722ed1', tag: '软实力' },
}

function DimensionAssessmentGrid({ assessment }: {
  assessment: ResumeScreeningResultItem['dimension_assessment']
}) {
  const groups = GROUP_ORDER.flatMap(
    name => assessment[name]?.length ? [{ name, items: assessment[name] ?? [] }] : [],
  )
  if (!groups.length) return null
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
      {groups.map(g => (
        <div
          key={g.name}
          className="rounded-[var(--rounded-sm)] border border-[var(--color-hairline)] border-l-[3px] p-2.5"
          style={{ borderLeftColor: GROUP_STYLE[g.name]?.color }}
        >
          <div className="text-[13px] font-medium mb-1">
            {g.name}
            <span className="ml-1.5 text-[11px] font-normal" style={{ color: GROUP_STYLE[g.name]?.color }}>
              {GROUP_STYLE[g.name]?.tag}
            </span>
          </div>
          {g.items.map((it, i) => (
            <div key={i} className="text-[13px] text-[var(--color-steel)] leading-relaxed">
              <span className="text-[var(--color-stone)]">{it.label}：</span>{it.text}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/** 信息卡片内容行（学历|学校|专业 / 当前职位 / 期望 / 核心技能） */
function ProfileRows({ profile }: { profile: CandidateProfile }) {
  const rows: { label: string; value: string }[] = [
    { label: '学历', value: [profile.education, profile.school, profile.major].filter(Boolean).join(' | ') },
    { label: '当前职位', value: [profile.current_position, profile.current_company].filter(Boolean).join(' · ') },
    { label: '期望', value: [profile.expected_position, profile.intended_city].filter(Boolean).join(' · ') },
    { label: '工作年限', value: profile.work_years != null ? `${profile.work_years} 年` : '' },
    { label: '在职状态', value: profile.employment_status || '' },
    { label: '年龄', value: profile.age || '' },
  ].filter(r => r.value)
  if (!rows.length && !profile.skills?.length) return null
  return (
    <div className="rounded-[var(--rounded-sm)] bg-[var(--color-surface)] p-2.5">
      <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[13px]">
        {rows.map(r => (
          <div key={r.label}>
            <span className="text-[var(--color-stone)]">{r.label}：</span>{r.value}
          </div>
        ))}
      </div>
      {!!profile.skills?.length && (
        <div className="mt-2 flex flex-wrap gap-1">
          {profile.skills.map((s, i) => <Tag key={i} style={{ marginInlineEnd: 0 }}>{s}</Tag>)}
        </div>
      )}
    </div>
  )
}

/** 候选人匹配度报告整卡：概览 + 信息卡片 + 四组维度评估，可一键复制全文转发 */
function MatchReportCard({ item }: { item: ResumeScreeningResultItem }) {
  const { message } = App.useApp()
  const hasProfile = Object.keys(item.candidate_profile || {}).length > 0
  const hasAssessment = Object.values(item.dimension_assessment || {}).some(v => !!v?.length)
  if (!hasProfile && !hasAssessment && !item.core_evaluation) return null

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(item.match_report || '')
      message.success('已复制完整报告，可直接粘贴转发')
    } catch {
      message.error('复制失败，请手动选择文本复制')
    }
  }

  return (
    <div className="rounded-[var(--rounded-sm)] border border-[var(--color-hairline)] p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">候选人匹配度报告</div>
        {item.match_report && (
          <Button size="small" icon={<CopyOutlined />} onClick={() => { void copyReport() }}>
            复制全文
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <Tag color={RECO_COLOR[item.recommendation]} style={{ marginInlineEnd: 0 }}>推荐等级：{item.recommendation}</Tag>
        {item.talent_category && (
          <Tag color={TALENT_COLOR[item.talent_category]} style={{ marginInlineEnd: 0 }}>
            {TALENT_LABEL[item.talent_category]}
          </Tag>
        )}
        <span>
          综合胜任度 <span className="font-semibold" style={{ color: scoreColor(item.total_score) }}>{item.total_score}/100</span>
        </span>
      </div>
      {item.core_evaluation && <div className="text-[13px] leading-relaxed">{item.core_evaluation}</div>}

      <ProfileRows profile={item.candidate_profile || {}} />
      {hasAssessment && <DimensionAssessmentGrid assessment={item.dimension_assessment} />}
    </div>
  )
}

const TD_CLS = 'border border-[var(--color-hairline)] px-3 py-1.5'

/** 胜任度打分表：按四组固定框架分块展示（组头行含组均分），未识别组的行归入「其他」 */
function GroupedScoreTable({ scoreTable }: { scoreTable: ResumeScreeningResultItem['score_table'] }) {
  if (!scoreTable.length) return null
  const groups = [
    ...GROUP_ORDER.map(name => ({ name, rows: scoreTable.filter(r => r.group === name) })),
    { name: '其他', rows: scoreTable.filter(r => !r.group) },
  ].filter(g => g.rows.length)
  return (
    <table className="text-[13px] border-collapse" style={{ width: '100%', maxWidth: 720 }}>
      <thead>
        <tr className="bg-[var(--color-surface)]">
          <th className={TD_CLS + ' text-left'}>维度</th>
          <th className={TD_CLS} style={{ width: 90 }}>得分</th>
          <th className={TD_CLS + ' text-left'}>说明</th>
        </tr>
      </thead>
      <tbody>
        {groups.flatMap(g => {
          const avg = Math.round(g.rows.reduce((sum, r) => sum + r.score, 0) / g.rows.length)
          return [
            <tr key={`${g.name}-head`} className="bg-[var(--color-surface)]">
              <td colSpan={3} className={TD_CLS + ' font-medium'}>
                {g.name}
                <span className="ml-2 font-normal" style={{ color: scoreColor(avg) }}>均分 {avg}</span>
              </td>
            </tr>,
            ...g.rows.map((row, i) => (
              <tr key={`${g.name}-${i}`}>
                <td className={TD_CLS}>{row.dimension}</td>
                <td className={TD_CLS + ' text-center font-medium'} style={{ color: scoreColor(row.score) }}>
                  {row.score}/100
                </td>
                <td className={TD_CLS + ' text-[var(--color-steel)]'}>{row.comment}</td>
              </tr>
            )),
          ]
        })}
      </tbody>
    </table>
  )
}

function ScreeningReport({ item }: { item: ResumeScreeningResultItem }) {
  return (
    <div className="space-y-4 max-w-4xl">
      <MatchReportCard item={item} />
      <SectionList title="一、优势分析" sections={item.advantages} color="green" />
      <SectionList title="二、核心硬伤 / 短板" sections={item.flaws} color="red" />

      {item.score_table.length > 0 && (
        <div>
          <div className="font-medium mb-1">
            三、综合胜任度打分：<span className="font-semibold" style={{ color: scoreColor(item.total_score) }}>{item.total_score}/100</span>
          </div>
          <GroupedScoreTable scoreTable={item.score_table} />
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
