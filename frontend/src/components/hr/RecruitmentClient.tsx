'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import { App, Badge, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Spin, Tabs, Tag, Upload } from 'antd'
import { PlusOutlined, UploadOutlined, SendOutlined, DownOutlined, RightOutlined, DeleteOutlined, FileSearchOutlined } from '@ant-design/icons'
import {
  createJobRequirement, updateJobRequirement, deleteJobRequirement,
  createCandidate, deleteCandidate,
  sendOfferAction, parseResumeAction, transitionCandidateStatus,
  fetchPositions, fetchCandidates, fetchJobRequirements, fetchPendingReviews,
  fetchCandidateComparison, fetchRecruitmentStats, previewOffer,
  decideCandidateReview,
  fetchEmployeesAction, screenCandidateAction,
} from '@/actions/hr'
import type { Candidate, JobRequirement, RecruitmentStats } from '@/types/hr'
import ResumeScreeningPanel from './ResumeScreeningPanel'

// 与后端 _CANDIDATE_TRANSITIONS 对齐：下拉只显示当前状态可流转的目标
const CANDIDATE_TRANSITIONS: Record<string, string[]> = {
  '待筛选': ['已筛选', '已拒绝'],
  '已筛选': ['待部门审核', '已拒绝'],
  '待部门审核': ['面试中', '已拒绝'],
  '面试中': ['已面试', '已拒绝'],
  '已面试': ['录用中', '已拒绝'],
  '录用中': ['已录用', '已拒绝'],
  '已录用': ['待入职审批', '已拒绝'],
  // 已入职只能通过「入职操作」完成（创建入职记录/工号/子任务），不放裸流转
  '待入职审批': ['已录用', '已拒绝'],
  '已拒绝': [],
}

// 候选人状态全集（排序 + 下拉候选用），颜色对齐招聘漏斗
const STATUS_OPTIONS = [
  { label: '待筛选', value: '待筛选' }, { label: '已筛选', value: '已筛选' },
  { label: '待部门审核', value: '待部门审核' }, { label: '面试中', value: '面试中' },
  { label: '已面试', value: '已面试' }, { label: '录用中', value: '录用中' },
  { label: '已录用', value: '已录用' }, { label: '待入职审批', value: '待入职审批' },
  { label: '已入职', value: '已入职' }, { label: '已拒绝', value: '已拒绝' },
]
const STATUS_COLORS: Record<string, string> = {
  '待筛选': '#a4a097', '已筛选': '#0075de', '待部门审核': '#dd5b00',
  '面试中': '#7b3ff2', '已面试': '#2a9d99', '录用中': '#1aae39',
  '已录用': '#5645d4', '待入职审批': '#e8b830', '已入职': '#389e0d', '已拒绝': '#ff4d4f',
}
const STATUS_ORDER = STATUS_OPTIONS.map(s => s.value)

/** 批量上传简历的逐份流水线状态：AI 解析 → 建档（关联岗位）→ 可选 AI 初筛 */
interface BatchResumeItem {
  key: string
  file: File
  stage: '待处理' | '解析中' | '建档中' | '已建档' | '初筛中' | '初筛完成' | '失败'
  name?: string
  parsed?: any
  candidateId?: string
  error?: string
  reco?: string
  score?: number
}

const BATCH_STAGE_COLOR: Record<BatchResumeItem['stage'], string> = {
  待处理: 'default', 解析中: 'processing', 建档中: 'processing',
  已建档: 'green', 初筛中: 'processing', 初筛完成: 'success', 失败: 'error',
}

export default function RecruitmentClient() {
  const { message: msg } = App.useApp()
  const router = useRouter()
  const [jobs, setJobs] = useState<JobRequirement[]>([])
  const [allCandidates, setAllCandidates] = useState<Candidate[]>([])
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set())
  const [changingStatus, setChangingStatus] = useState<string | null>(null)
  const [reqOpen, setReqOpen] = useState(false)
  const [reqForm] = Form.useForm()
  const [editingReq, setEditingReq] = useState<JobRequirement | null>(null)
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeItems, setResumeItems] = useState<BatchResumeItem[]>([])
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchScreening, setBatchScreening] = useState(false)
  const [resumeJobId, setResumeJobId] = useState<string | null>(null)
  const [posOptions, setPosOptions] = useState<{ value: string; label: string }[]>([])
  const [offerOpen, setOfferOpen] = useState(false)
  const [offerCandidate, setOfferCandidate] = useState<Candidate | null>(null)
  const [offerForm] = Form.useForm()
  const [offerSending, setOfferSending] = useState(false)

  // 待我审核
  const [activeTab, setActiveTab] = useState<'jobs' | 'reviews' | 'stats' | 'screening'>('jobs')
  const [pendingReviews, setPendingReviews] = useState<any[]>([])
  const [reviewsLoading, setReviewsLoading] = useState(false)

  // 数据分析
  const [stats, setStats] = useState<RecruitmentStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  const loadStats = async () => {
    setStatsLoading(true)
    try { const r = await fetchRecruitmentStats(); setStats(r.data) }
    catch { setStats(null) }
    finally { setStatsLoading(false) }
  }

  // 候选人对比
  const [compareData, setCompareData] = useState<any[]>([])
  const [compareLoading, setCompareLoading] = useState(false)
  const [showCompare, setShowCompare] = useState(false)

  const loadPendingReviews = useCallback(async () => {
    setReviewsLoading(true)
    try {
      const r = await fetchPendingReviews()
      setPendingReviews(r.data || [])
    } catch { setPendingReviews([]) }
    finally { setReviewsLoading(false) }
  }, [])

  const handleDecideReview = async (candidateId: string, decision: string) => {
    try {
      await decideCandidateReview(candidateId, { decision })
      msg.success(decision === '已同意' ? '已同意' : '已驳回')
      loadPendingReviews()
    } catch (err: any) { msg.error(err.message || '操作失败') }
  }

  // 用人部门负责人选择器：远程搜索在职员工（值存姓名，发卡按姓名查人）
  const [ownerOptions, setOwnerOptions] = useState<{ value: string; label: string }[]>([])
  const [ownerSearching, setOwnerSearching] = useState(false)
  const ownerSearchSeq = useRef(0)
  const searchOwnerOptions = async (keyword: string) => {
    const seq = ++ownerSearchSeq.current
    setOwnerSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== ownerSearchSeq.current) return  // 过期响应丢弃
      setOwnerOptions(((d?.data as any)?.items || (d?.data as any) || []).map((e: any) => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || ''}）`,
      })))
    } catch (err: any) {
      msg.error(err?.message || '员工搜索失败，请稍后重试')
    }
    finally { if (seq === ownerSearchSeq.current) setOwnerSearching(false) }
  }

  useEffect(() => {
    fetchPositions().then(d => setPosOptions(d.map((p: any) => ({ value: `${p.department}|||${p.name}`, label: `${p.name} (${p.department})` })))).catch(() => { })
  }, [])

  // 挂载即拉待审数：Tab 上的 Badge 需要初始值
  useEffect(() => { loadPendingReviews() }, [loadPendingReviews])

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetchJobRequirements()
      setJobs(r.data || [])
    } catch { /* ignore */ }
  }, [])

  const loadAllCandidates = useCallback(async () => {
    try {
      const r = await fetchCandidates({ page_size: 100 })
      setAllCandidates(r.data || [])
    } catch { setAllCandidates([]) }
  }, [])

  useEffect(() => { loadJobs(); loadAllCandidates() }, [loadJobs, loadAllCandidates])

  // 有候选人时自动展开岗位
  useEffect(() => {
    if (allCandidates.length === 0 || jobs.length === 0) return
    setExpandedJobs(new Set(jobs.filter(j => allCandidates.some(c => c.job_requirement_id === j.id)).map(j => j.id)))
  }, [allCandidates, jobs])

  const toggleJob = (jobId: string) => {
    setExpandedJobs(prev => {
      const next = new Set(prev)
      next.has(jobId) ? next.delete(jobId) : next.add(jobId)
      return next
    })
  }

  const handleStatusChange = async (candidateId: string, newStatus: string) => {
    setChangingStatus(candidateId)
    try {
      await transitionCandidateStatus(candidateId, { status: newStatus, remark: '快捷流转' })
      msg.success('状态已变更')
      loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '变更失败') }
    finally { setChangingStatus(null) }
  }

  const loadCompare = async (jobId: string) => {
    setShowCompare(true)
    setCompareLoading(true)
    try {
      const r = await fetchCandidateComparison(jobId)
      setCompareData(r.data || [])
    } catch { setCompareData([]) }
    finally { setCompareLoading(false) }
  }

  const handleSaveReq = async () => {
    const v = await reqForm.validateFields()
    const parts = (v.position_name || '').split('|||')
    const payload: any = {
      position_name: parts[1] || parts[0],
      department: v.department || parts[0],
      headcount: v.headcount ?? 1,
      requirements: v.requirements || undefined,
      duties: v.duties || undefined,
      urgency: v.urgency || undefined,
      owner: v.owner || undefined,
      deadline: v.deadline ? dayjs(v.deadline).format('YYYY-MM-DD') : undefined,
    }
    if (editingReq) {
      payload.status = v.status || undefined
    }
    try {
      if (editingReq) {
        await updateJobRequirement(editingReq.id, payload)
      } else {
        await createJobRequirement(payload)
      }
      msg.success(editingReq ? '已更新' : '岗位需求已创建')
      setReqOpen(false); reqForm.resetFields(); setEditingReq(null); loadJobs()
    } catch (err: any) { msg.error(err.message || '保存失败') }
  }

  const handleDeleteReq = async (id: string) => {
    try {
      const r = await deleteJobRequirement(id)
      msg.success(r.message || '已删除')
      loadJobs(); loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '删除失败') }
  }

  // ─── 批量上传简历流水线：逐份 AI 解析 → 自动建档（关联当前岗位）→ 一键 AI 初筛 ───
  const updateResumeItem = (key: string, patch: Partial<BatchResumeItem>) => {
    setResumeItems(prev => prev.map(it => (it.key === key ? { ...it, ...patch } : it)))
  }

  const handleProcessBatch = async () => {
    const pending = resumeItems.filter(it => it.stage === '待处理')
    if (!pending.length) { msg.warning('请先选择简历 PDF 文件'); return }
    if (!resumeJobId) { msg.error('未关联岗位，无法建档'); return }
    const jd = jobs.find(j => j.id === resumeJobId)
    setBatchRunning(true)
    let created = 0
    for (const it of pending) {
      try {
        updateResumeItem(it.key, { stage: '解析中', error: undefined })
        const fd = new FormData(); fd.append('resume', it.file)
        const d = await parseResumeAction(fd)
        const p = d.data || {}
        const fallbackName = it.file.name.replace(/\.pdf$/i, '')
        updateResumeItem(it.key, { stage: '建档中', parsed: p, name: p.name || fallbackName })
        const res = await createCandidate({
          name: p.name || fallbackName,
          phone: p.phone || undefined,
          email: p.email || undefined,
          gender: p.gender || undefined,
          school: p.school || undefined,
          education: p.education || undefined,
          major: p.major || undefined,
          position: jd?.position_name || '',
          department: jd?.department || '',
          job_requirement_id: resumeJobId,
          status: '待筛选',
          candidate_type: '职能',
          resume_url: p.resume_file_path || '',
          current_company: p.current_company || undefined,
          work_years: p.work_years ?? undefined,
          expected_salary: p.expected_salary || undefined,
          source: p.source || '自主上传',
        } as any)
        updateResumeItem(it.key, { stage: '已建档', candidateId: res?.data?.id })
        created += 1
      } catch (err: any) {
        updateResumeItem(it.key, { stage: '失败', error: err?.message || '处理失败' })
      }
    }
    setBatchRunning(false)
    if (created > 0) {
      if (resumeJobId) setExpandedJobs(prev => new Set([...prev, resumeJobId]))
      await loadAllCandidates()
      msg.success(`已为「${jd?.position_name || '岗位'}」建档 ${created} 名候选人`)
    }
  }

  // 对本批已建档、尚未初筛的简历批量跑 AI 初筛（串行，逐份回写行内结果）
  const handleBatchScreen = async () => {
    const targets = resumeItems.filter(it => it.stage === '已建档' && it.candidateId)
    if (!targets.length) return
    setBatchScreening(true)
    let ok = 0
    for (const it of targets) {
      updateResumeItem(it.key, { stage: '初筛中' })
      try {
        const r = await screenCandidateAction(it.candidateId!)
        updateResumeItem(it.key, {
          stage: '初筛完成', reco: r.data.recommendation, score: r.data.total_score,
        })
        ok += 1
      } catch (err: any) {
        // 初筛失败不影响已建档结果：回落「已建档」可重试
        updateResumeItem(it.key, { stage: '已建档', error: err?.message || '初筛失败' })
      }
    }
    setBatchScreening(false)
    if (ok > 0) {
      await loadAllCandidates()
      msg.success(`AI 初筛完成 ${ok} 份，推荐等级与匹配报告已写入候选人档案`)
    }
  }

  const closeResumeModal = () => {
    if (batchRunning || batchScreening) { msg.warning('正在处理中，请等待本轮完成后再关闭'); return }
    setResumeOpen(false)
    setResumeItems([])
    setResumeJobId(null)
  }

  // AI 初筛：对已建档候选人的存量简历直接筛选（免重复上传，结果回写候选人档案）
  const [screeningCand, setScreeningCand] = useState<string | null>(null)
  const runScreenCandidate = async (candidateId: string) => {
    setScreeningCand(candidateId)
    try {
      const r = await screenCandidateAction(candidateId)
      msg.success(`AI 初筛完成：${r.data.recommendation}（胜任度 ${r.data.total_score}/100），报告已写入候选人档案`)
      await loadAllCandidates()
    } catch (err: any) { msg.error(err.message || 'AI 初筛失败') }
    finally { setScreeningCand(null) }
  }

  const handleDeleteCandidate = async (id: string) => {
    try { await deleteCandidate(id); loadAllCandidates() }
    catch (err: any) { msg.error(err.message || '删除失败') }
  }

  const handleSendOffer = (candidate: Candidate) => {
    setOfferCandidate(candidate)
    offerForm.resetFields()
    offerForm.setFieldsValue({
      candidate_email: candidate.email || '',
      candidate_name: candidate.name || '',
      position: candidate.position || '',
      department: candidate.department || '',
    })
    setOfferOpen(true)
  }

  const fmtDate = (d: any) => d ? (d.format ? d.format('YYYY年M月D日') : String(d)) : ''

  const handlePreviewOffer = async () => {
    const v = offerForm.getFieldsValue()
    const fd = new FormData()
    Object.entries(v).forEach(([k, val]) => fd.append(k, (k.endsWith('_date') ? fmtDate(val) : (val as string)) || ''))
    try {
      const html = await previewOffer(offerCandidate!.id, fd)
      const w = window.open('', '_blank')
      if (w) { w.document.write(html); w.document.close() }
    } catch (err: any) { msg.error(err.message || '预览失败') }
  }

  const handleSendOfferSubmit = async () => {
    const v = await offerForm.validateFields()
    setOfferSending(true)
    try {
      const fd = new FormData()
      Object.entries(v).forEach(([k, val]) => fd.append(k, (k.endsWith('_date') ? fmtDate(val) : (val as string)) || ''))
      await sendOfferAction(offerCandidate!.id, fd)
      msg.success('Offer 已发送')
      setOfferOpen(false); offerForm.resetFields()
    } catch (err: any) { msg.error(err.message || '发送失败') }
    finally { setOfferSending(false) }
  }

  const handleTabChange = (key: string) => {
    setActiveTab(key as typeof activeTab)
    if (key === 'reviews') loadPendingReviews()
    if (key === 'stats') loadStats()
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">招聘管理</h1>
        <span className="text-xs text-[var(--color-stone)]">{jobs.length} 个岗位 · {allCandidates.length} 个候选人</span>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        tabBarExtraContent={{
          right: activeTab === 'jobs' && (
            <div className="flex gap-2 pb-1">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingReq(null); reqForm.resetFields(); setReqOpen(true) }}>新建岗位需求</Button>
            </div>
          ),
        }}
        items={[
          {
            key: 'jobs',
            label: '岗位招聘',
            children: (<>
              {showCompare ? (
                /* 横向对比弹窗 */
                <Card size="small" title="候选人横向对比（按AI综合评分排序）"
                  extra={<Button size="small" onClick={() => setShowCompare(false)}>关闭对比</Button>}
                >
                  {compareLoading ? <div className="text-center py-12"><Spin /></div> :
                    compareData.length === 0 ? <Empty description="暂无候选人数据" className="py-12" /> :
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs border-collapse">
                        <thead><tr className="bg-gray-50">
                          <th className="p-2 text-left border">姓名</th><th className="p-2 text-left border">学历</th><th className="p-2 text-left border">状态</th>
                          <th className="p-2 border">JD匹配</th><th className="p-2 border">专业</th><th className="p-2 border">沟通</th><th className="p-2 border">学习</th><th className="p-2 border">稳定</th>
                          <th className="p-2 border font-bold">综合</th><th className="p-2 border">AI摘要</th>
                        </tr></thead>
                        <tbody>{compareData.map((item: any, idx: number) => {
                          const c = item.candidate || {}; const ev = item.evaluation
                          const sc = (v: any) => v == null ? '#ccc' : v >= 8 ? '#52c41a' : v >= 6 ? '#1677ff' : v >= 4 ? '#fa8c16' : '#ff4d4f'
                          return (<tr key={c.id} className="hover:bg-blue-50 cursor-pointer border-t" onClick={() => router.push(`/hr/recruitment/${c.id}`)}>
                            <td className="p-2 font-medium"><span className="text-gray-400">{idx + 1}.</span> {c.name}</td>
                            <td className="p-2 border">{c.education || '-'}</td>
                            <td className="p-2 border"><Tag style={{ fontSize: 10 }}>{c.status || '-'}</Tag></td>
                            <td className="p-2 border text-center font-medium" style={{ color: sc(ev?.jd_match_score) }}>{ev?.jd_match_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border text-center" style={{ color: sc(ev?.professional_score) }}>{ev?.professional_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border text-center" style={{ color: sc(ev?.communication_score) }}>{ev?.communication_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border text-center" style={{ color: sc(ev?.learning_score) }}>{ev?.learning_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border text-center" style={{ color: sc(ev?.stability_score) }}>{ev?.stability_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border text-center font-bold" style={{ color: sc(ev?.overall_score) }}>{ev?.overall_score?.toFixed(1) || '-'}</td>
                            <td className="p-2 border max-w-[200px] truncate" title={ev?.ai_summary}>{ev?.ai_summary?.slice(0, 50) || '-'}</td>
                          </tr>)
                        })}</tbody></table></div>}
                </Card>
              ) : (
                /* 统一按岗位视图 */
                <div className="space-y-2">
                  {jobs.length === 0 && <Empty description="暂无岗位需求，点击右上角新建" className="py-8" />}
                  {jobs.map(j => {
                    const jobCandidates = allCandidates.filter(c => c.job_requirement_id === j.id)
                    const isExpanded = expandedJobs.has(j.id)
                    const hiredCount = jobCandidates.filter(c => c.status === '已入职').length
                    const sortedCandidates = [...jobCandidates].sort((a, b) => {
                      const ia = STATUS_ORDER.indexOf(a.status || ''); const ib = STATUS_ORDER.indexOf(b.status || '')
                      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
                    })
                    return (
                      <Card key={j.id} size="small"
                        title={
                          <div className="flex items-center gap-2.5 cursor-pointer select-none min-w-0" onClick={() => toggleJob(j.id)}>
                            <span className="text-gray-400 flex-shrink-0">
                              {isExpanded ? <DownOutlined style={{ fontSize: 10 }} /> : <RightOutlined style={{ fontSize: 10 }} />}
                            </span>
                            <b className="text-sm">{j.position_name}</b>
                            <span className="text-xs text-gray-400 flex-shrink-0">{j.department}</span>
                            <Tag color={j.status === '招聘中' ? 'green' : 'default'} style={{ fontSize: 10, margin: 0 }} className="flex-shrink-0">{j.status}</Tag>
                            <span className="text-xs text-gray-400 flex-shrink-0">{jobCandidates.length}/{j.headcount} 人</span>
                            {j.urgency === '紧急' && <Tag color="red" style={{ fontSize: 10, margin: 0 }} className="flex-shrink-0">紧急</Tag>}
                            {!isExpanded && jobCandidates.length > 0 && (
                              <span className="text-xs text-gray-300 truncate">
                                {sortedCandidates.slice(0, 4).map(c => c.name).join('、')}{jobCandidates.length > 4 ? '…' : ''}
                              </span>
                            )}
                          </div>
                        }
                        extra={
                          <div className="flex gap-1.5 items-center" onClick={e => e.stopPropagation()}>
                            <Button size="small" onClick={() => loadCompare(j.id)}>对比</Button>
                            <Button size="small" icon={<UploadOutlined />} title="批量上传简历（自动解析建档，可一键 AI 初筛）" onClick={() => { setResumeItems([]); setResumeJobId(j.id); setResumeOpen(true) }} />
                            <Button size="small" type="text" onClick={() => { setEditingReq(j); if (j.owner) setOwnerOptions([{ value: j.owner, label: j.owner }]); reqForm.setFieldsValue({ ...j, position_name: `${j.department}|||${j.position_name}`, deadline: j.deadline ? dayjs(j.deadline) : undefined }); setReqOpen(true) }}>编辑</Button>
                            <Popconfirm
                              title="删除该岗位？"
                              description={jobCandidates.length === 0
                                ? '名下暂无候选人'
                                : `将一并清理名下 ${jobCandidates.length - hiredCount} 名候选人记录${hiredCount > 0 ? `，已入职 ${hiredCount} 名保留` : ''}`}
                              onConfirm={() => handleDeleteReq(j.id)} okText="删除" cancelText="取消"
                            >
                              <Button size="small" danger icon={<DeleteOutlined />} disabled={j.status === '招聘中'}
                                title={j.status === '招聘中' ? '招聘中岗位不可删除，请先在「编辑」中改为已关闭' : '删除岗位'} />
                            </Popconfirm>
                          </div>
                        }
                      >
                        {!isExpanded ? null : jobCandidates.length === 0 ? (
                          <div className="text-center text-gray-400 text-xs py-4">暂无候选人 — 上传简历或导入Excel添加</div>
                        ) : (
                          <div className="flex flex-col gap-1.5">
                            {sortedCandidates.map(c => {
                              const days = c.updated_at ? Math.floor((Date.now() - new Date(c.updated_at).getTime()) / (1000 * 60 * 60 * 24)) : 0
                              const isStale = days > 7 && c.status !== '已入职' && c.status !== '已拒绝'
                              return (
                                <div key={c.id} className="rounded border px-3 py-2 flex items-center gap-3 hover:shadow-sm transition-shadow w-full cursor-pointer"
                                  style={{
                                    borderColor: isStale ? '#ffccc7' : '#e8e8e8',
                                    background: isStale ? '#fff5f5' : '#fff',
                                  }}
                                  onClick={() => router.push(`/hr/recruitment/${c.id}`)}
                                >
                                  <div className="w-1 self-stretch rounded-full flex-shrink-0" style={{ background: STATUS_COLORS[c.status || '待筛选'] || '#d9d9d9' }} />
                                  <div className="flex items-center gap-2 min-w-0 w-44 flex-shrink-0">
                                    <span className="text-sm font-medium truncate">{c.name}</span>
                                    <span className="text-xs text-gray-400 flex-shrink-0">{c.gender}</span>
                                    {c.recommendation_level && (
                                      <Tag color={c.recommendation_level === '强烈推荐' ? 'green' : c.recommendation_level === '推荐' ? 'blue' : 'default'}
                                        style={{ fontSize: 10, margin: 0 }} className="flex-shrink-0">{c.recommendation_level}</Tag>
                                    )}
                                  </div>
                                  <div className="text-xs text-gray-500 truncate w-48 flex-shrink-0 hidden md:block">{c.education || '-'} · {c.school || '-'}</div>
                                  <div className="text-xs text-gray-500 truncate flex-1 min-w-0 hidden lg:block">{c.phone || '-'} · {c.email || '-'}</div>
                                  <div className="flex items-center gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
                                    {isStale && <span className="text-xs text-red-400 whitespace-nowrap" title={`已停留${days}天`}>⚠️{days}天</span>}
                                    {c.resume_url && c.job_requirement_id && (
                                      <Button size="small" icon={<FileSearchOutlined />}
                                        loading={screeningCand === c.id}
                                        title="AI 初筛（用已存简历按关联岗位打分，免重复上传）"
                                        onClick={() => runScreenCandidate(c.id)} />
                                    )}
                                    <Select size="small" value={c.status} loading={changingStatus === c.id}
                                      style={{ width: 110 }}
                                      options={STATUS_OPTIONS.filter(o => o.value === c.status || CANDIDATE_TRANSITIONS[c.status || '']?.includes(o.value))}
                                      onChange={v => handleStatusChange(c.id, v)}
                                    />
                                    <Button size="small" icon={<SendOutlined />} onClick={() => handleSendOffer(c)} title="发Offer" />
                                    <Popconfirm title="确定删除此候选人？" onConfirm={() => handleDeleteCandidate(c.id)} okText="删除" cancelText="取消">
                                      <Button size="small" danger icon={<DeleteOutlined />} title="删除" />
                                    </Popconfirm>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </Card>
                    )
                  })}
                </div>
              )}

              <Modal title={editingReq ? '编辑' : '新建岗位需求'} open={reqOpen} onCancel={() => setReqOpen(false)} onOk={handleSaveReq}>
                <Form form={reqForm} layout="vertical">
                  <Form.Item name="position_name" label="岗位名称" rules={[{ required: true }]}>
                    <Select showSearch placeholder="选择岗位（含部门）" options={posOptions}
                      filterOption={(inp, opt) => (opt?.label ?? '').toLowerCase().includes(inp.toLowerCase())}
                      onChange={(val: string) => { const parts = val.split('|||'); reqForm.setFieldsValue({ department: parts[0] || '' }) }} />
                  </Form.Item>
                  <Form.Item name="department" hidden><Input /></Form.Item>
                  <Form.Item name="headcount" label="招聘人数"><InputNumber min={1} /></Form.Item>
                  <Form.Item name="requirements" label="岗位要求"><Input.TextArea rows={4} /></Form.Item>
                  <Form.Item name="duties" label="岗位职责"><Input.TextArea rows={3} placeholder="可选，胜任度分析报告「岗位要求回顾」使用" /></Form.Item>
                  <Form.Item name="owner" label="用人部门负责人" tooltip="推送审核时默认发给此人">
                    <Select
                      showSearch
                      filterOption={false}
                      allowClear
                      loading={ownerSearching}
                      placeholder="输入姓名搜索；或直接从下方列表选择"
                      options={ownerOptions}
                      onSearch={searchOwnerOptions}
                      onOpenChange={(open) => { if (open && ownerOptions.length === 0) void searchOwnerOptions('') }}
                    />
                  </Form.Item>
                  <Form.Item name="urgency" label="紧急程度">
                    <Select options={[{ label: '普通', value: '普通' }, { label: '紧急', value: '紧急' }]} allowClear />
                  </Form.Item>
                  <Form.Item name="deadline" label="期望到岗日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
                  {editingReq && <Form.Item name="status" label="状态"><Select options={[{ label: '招聘中', value: '招聘中' }, { label: '已关闭', value: '已关闭' }]} /></Form.Item>}
                </Form>
              </Modal>

              <Modal title={`发放入职 Offer — ${offerCandidate?.name || ''}`} open={offerOpen}
                onCancel={() => setOfferOpen(false)} width={640}
                footer={[
                  <Button key="preview" onClick={handlePreviewOffer}>预览</Button>,
                  <Button key="send" type="primary" loading={offerSending} onClick={handleSendOfferSubmit}>发送</Button>,
                ]}
              >
                <Form form={offerForm} layout="vertical" className="mt-2">
                  <Form.Item name="candidate_email" label="收件邮箱" rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="candidate@example.com" />
                  </Form.Item>
                  <Form.Item name="candidate_name" label="姓名"><Input disabled /></Form.Item>
                  <Form.Item name="department" label="部门"><Input disabled /></Form.Item>
                  <Form.Item name="position" label="岗位"><Input disabled /></Form.Item>
                  <Form.Item name="base_salary" label="转正底薪（元）"><Input placeholder="如 3800" /></Form.Item>
                  <Form.Item name="salary_range" label="综合税前月薪范围"><Input placeholder="如 7000-8000" /></Form.Item>
                  <Form.Item name="medical_date" label="体检截止日期"><DatePicker style={{ width: '100%' }} placeholder="选择日期" /></Form.Item>
                  <Form.Item name="report_date" label="报到截止日期"><DatePicker style={{ width: '100%' }} placeholder="选择日期" /></Form.Item>
                  <Form.Item name="offer_expire_date" label="Offer保留至"><DatePicker style={{ width: '100%' }} placeholder="选择日期" /></Form.Item>
                  <Form.Item name="additional_terms" label="补充条款（选填）"><Input.TextArea rows={3} placeholder="自定义补充条款，将追加在Offer正文末尾" /></Form.Item>
                </Form>
              </Modal>

              <Modal
                title={`批量上传简历 — ${jobs.find(j => j.id === resumeJobId)?.position_name || ''}`}
                open={resumeOpen}
                onCancel={closeResumeModal}
                mask={{ closable: false }}
                width={560}
                footer={[
                  <Button key="close" onClick={closeResumeModal}>关闭</Button>,
                  (() => {
                    const screenable = resumeItems.filter(it => it.stage === '已建档' && it.candidateId).length
                    return (
                      <Button key="screen" type="primary" ghost icon={<FileSearchOutlined />}
                        disabled={screenable === 0 || batchRunning}
                        loading={batchScreening}
                        onClick={() => { void handleBatchScreen() }}>
                        AI 初筛 {screenable > 0 ? `${screenable} 份` : ''}
                      </Button>
                    )
                  })(),
                  <Button key="process" type="primary" icon={<UploadOutlined />}
                    loading={batchRunning}
                    disabled={batchRunning || batchScreening || resumeItems.filter(it => it.stage === '待处理').length === 0}
                    onClick={() => { void handleProcessBatch() }}>
                    开始处理{resumeItems.length > 0 ? `（${resumeItems.filter(it => it.stage === '待处理').length}/${resumeItems.length}）` : ''}
                  </Button>,
                ]}>
                <div className="space-y-3">
                  <div className="text-xs text-gray-500">
                    支持一次选择多份 PDF：逐份自动「AI 解析 → 建档为该岗位候选人」，完成后可一键对全部新简历跑 AI 初筛（推荐等级 + 匹配报告直接写入候选人档案）。
                  </div>
                  <Upload
                    accept=".pdf"
                    multiple
                    disabled={batchRunning || batchScreening}
                    showUploadList={false}
                    beforeUpload={(_, fileList) => {
                      // beforeUpload 逐个触发：等本批最后一个文件到齐再整批建行
                      // （fileList 元素 RcFile 即 File 子类，直接使用）
                      if (fileList[fileList.length - 1]?.uid === _.uid) {
                        setResumeItems(fileList.map((f, i) => ({
                          key: `${Date.now()}-${i}-${f.name}`, file: f, stage: '待处理' as const,
                        })))
                      }
                      return false
                    }}
                  >
                    <Button icon={<UploadOutlined />} disabled={batchRunning || batchScreening}>选择 PDF 文件（可多选）</Button>
                  </Upload>
                  {resumeItems.length > 0 && (
                    <div className="border rounded divide-y max-h-80 overflow-y-auto">
                      {resumeItems.map(it => (
                        <div key={it.key} className="flex items-center gap-2 px-3 py-2 text-sm">
                          <div className="flex-1 min-w-0">
                            <div className="truncate" title={it.file.name}>
                              {it.name ? <b>{it.name}</b> : it.file.name}
                              <span className="text-xs text-gray-400 ml-2">{(it.file.size / 1024).toFixed(0)}KB</span>
                            </div>
                            {it.stage === '失败' && it.error && (
                              <div className="text-xs text-red-500 truncate" title={it.error}>{it.error}</div>
                            )}
                            {it.stage === '初筛完成' && (
                              <div className="text-xs text-gray-500">
                                AI 初筛：<span className="font-medium">{it.reco}</span> · 胜任度 {it.score}/100（报告已入档案）
                              </div>
                            )}
                            {it.stage === '已建档' && it.error && (
                              <div className="text-xs text-orange-500 truncate" title={it.error}>上次初筛未完成：{it.error}</div>
                            )}
                          </div>
                          <Tag color={BATCH_STAGE_COLOR[it.stage]} style={{ margin: 0 }}>{it.stage}</Tag>
                          {it.stage === '失败' && !batchRunning && !batchScreening && (
                            <a className="text-xs" onClick={() => updateResumeItem(it.key, { stage: '待处理', error: undefined })}>重试</a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Modal>
            </>),
          },
          {
            key: 'reviews',
            label: (
              <Badge count={pendingReviews.length} size="small" offset={[8, -2]}>
                <span className="px-1">待我审核</span>
              </Badge>
            ),
            children: (
              <Card title="待我审核的候选人" loading={reviewsLoading}>
                {pendingReviews.length === 0 ? <Empty description="暂无待审核候选人" className="py-12" /> : (
                  <div className="space-y-3">
                    {pendingReviews.map((item: any) => {
                      const c = item.candidate || {}; const jd = item.job_requirement; const rv = item.review || {}
                      return (
                        <Card key={c.id} size="small" hoverable className="cursor-pointer"
                          onClick={() => router.push(`/hr/recruitment/${c.id}`)}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-medium">{c.name}</span>
                                <span className="text-xs text-gray-400">{c.gender || '-'}</span>
                                <span className="text-xs text-gray-500">{c.education || '-'}</span>
                              </div>
                              <div className="text-xs text-gray-500 mt-1 truncate">
                                {[c.school, c.major, c.work_years != null ? `${c.work_years}年经验` : '', c.current_company].filter(Boolean).join(' · ')}
                              </div>
                              <div className="text-xs text-gray-500">岗位：{jd?.position_name || c.position} · {jd?.department || c.department}</div>
                              {rv.push_note && <div className="text-xs text-blue-600 mt-1">💬 HR备注：{rv.push_note}</div>}
                            </div>
                            <div className="flex gap-2 flex-shrink-0 pt-0.5" onClick={(e) => e.stopPropagation()}>
                              <Button size="small" type="primary" onClick={() => handleDecideReview(c.id, '已同意')}>同意</Button>
                              <Button size="small" danger onClick={() => handleDecideReview(c.id, '已拒绝')}>驳回</Button>
                            </div>
                          </div>
                        </Card>
                      )
                    })}
                  </div>
                )}
              </Card>
            ),
          },
          {
            key: 'screening',
            label: <span className="flex items-center gap-1.5"><FileSearchOutlined />AI 筛简历</span>,
            children: <ResumeScreeningPanel />,
          },
          {
            key: 'stats',
            label: '数据分析',
            children: (
              <Card title="招聘数据分析" loading={statsLoading}>
                {stats ? (
                  <div className="space-y-6">
                    <div className={`grid gap-4 ${stats.avg_cycle_days != null ? 'grid-cols-2 md:grid-cols-3' : 'grid-cols-2'}`}>
                      <Card size="small" className="text-center">
                        <div className="text-3xl font-bold text-blue-600">{stats.total_candidates}</div>
                        <div className="text-xs text-gray-500 mt-1">候选人总数</div>
                      </Card>
                      <Card size="small" className="text-center">
                        <div className="text-3xl font-bold text-green-600">{stats.active_jobs}</div>
                        <div className="text-xs text-gray-500 mt-1">在招岗位数</div>
                      </Card>
                      {stats.avg_cycle_days != null && (
                        <Card size="small" className="text-center col-span-2 md:col-span-1">
                          <div className="text-3xl font-bold text-orange-500">{stats.avg_cycle_days}</div>
                          <div className="text-xs text-gray-500 mt-1">平均招聘周期（天）</div>
                        </Card>
                      )}
                    </div>
                    <div>
                      <h3 className="text-sm font-medium mb-3">招聘漏斗</h3>
                      <div className="space-y-2">
                        {stats.funnel?.map((item: any) => {
                          const max = Math.max(...stats.funnel.map((f: any) => f.count), 1)
                          const pct = Math.round((item.count / max) * 100)
                          const colors: Record<string, string> = {
                            '待筛选': '#1677ff', '已筛选': '#722ed1', '待部门审核': '#fa8c16',
                            '面试中': '#13c2c2', '已面试': '#52c41a', '录用中': '#2f54eb',
                            '已录用': '#389e0d', '已拒绝': '#ff4d4f',
                          }
                          return (
                            <div key={item.status} className="flex items-center gap-2">
                              <span className="text-xs w-20 text-right text-gray-500">{item.status}</span>
                              <div className="flex-1 bg-gray-100 rounded h-5 overflow-hidden">
                                <div className="h-full rounded transition-all" style={{
                                  width: `${pct}%`,
                                  backgroundColor: colors[item.status] || '#d9d9d9',
                                }} />
                              </div>
                              <span className="text-xs font-medium w-8">{item.count}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                    {stats.monthly_hires && stats.monthly_hires.length > 0 && (
                      <div>
                        <h3 className="text-sm font-medium mb-3">月度入职趋势</h3>
                        <div className="space-y-2">
                          {stats.monthly_hires.map((item: { month: string; count: number }) => {
                            const maxH = Math.max(...stats.monthly_hires!.map((h: { count: number }) => h.count), 1)
                            const pctH = Math.round((item.count / maxH) * 100)
                            return (
                              <div key={item.month} className="flex items-center gap-2">
                                <span className="text-xs w-20 text-right text-gray-500">{item.month}</span>
                                <div className="flex-1 bg-gray-100 rounded h-5 overflow-hidden">
                                  <div className="h-full rounded bg-teal-500 transition-all" style={{ width: `${pctH}%` }} />
                                </div>
                                <span className="text-xs font-medium w-8">{item.count}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {stats.source_stats && stats.source_stats.length > 0 && (
                      <div>
                        <h3 className="text-sm font-medium mb-3">简历来源分布</h3>
                        <div className="space-y-2">
                          {stats.source_stats.map((item: { source: string; count: number }, idx: number) => {
                            const maxS = Math.max(...stats.source_stats!.map((s: { count: number }) => s.count), 1)
                            const pctS = Math.round((item.count / maxS) * 100)
                            const sourceColors = ['#1677ff', '#722ed1', '#fa8c16', '#13c2c2', '#52c41a', '#eb2f96', '#2f54eb']
                            const color = sourceColors[idx % sourceColors.length]
                            return (
                              <div key={item.source} className="flex items-center gap-2">
                                <span className="text-xs w-20 text-right text-gray-500">{item.source || '未知'}</span>
                                <div className="flex-1 bg-gray-100 rounded h-5 overflow-hidden">
                                  <div className="h-full rounded transition-all" style={{ width: `${pctS}%`, backgroundColor: color }} />
                                </div>
                                <span className="text-xs font-medium w-8">{item.count}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <Empty description="暂无数据" className="py-12" />
                )}
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
