'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import { App, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Spin, Tag, Upload } from 'antd'
import { PlusOutlined, UploadOutlined, SendOutlined, DownloadOutlined, DownOutlined, RightOutlined, DeleteOutlined } from '@ant-design/icons'
import {
  createJobRequirement, updateJobRequirement, deleteJobRequirement,
  createCandidate, deleteCandidate,
  sendOfferAction, parseResumeAction, transitionCandidateStatus,
  fetchPositions, fetchCandidates, fetchJobRequirements, fetchPendingReviews,
  fetchCandidateComparison, fetchRecruitmentStats, previewOffer,
  uploadCandidates, downloadCandidateTemplate, decideCandidateReview,
  fetchEmployeesAction,
} from '@/actions/hr'
import type { Candidate, JobRequirement, RecruitmentStats } from '@/types/hr'

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

export default function RecruitmentClient() {
  const { message: msg } = App.useApp()
  const router = useRouter()
  const [mounted, setMounted] = useState(false)
  const [jobs, setJobs] = useState<JobRequirement[]>([])
  const [allCandidates, setAllCandidates] = useState<Candidate[]>([])
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set())
  const [changingStatus, setChangingStatus] = useState<string | null>(null)
  const [reqOpen, setReqOpen] = useState(false)
  const [reqForm] = Form.useForm()
  const [editingReq, setEditingReq] = useState<JobRequirement | null>(null)
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [resumeResult, setResumeResult] = useState<any>(null)
  const [resumeLoading, setResumeLoading] = useState(false)
  const resumeJobIdRef = useRef<string | null>(null)
  const [posOptions, setPosOptions] = useState<{ value: string; label: string }[]>([])
  const [offerOpen, setOfferOpen] = useState(false)
  const [offerCandidate, setOfferCandidate] = useState<Candidate | null>(null)
  const [offerForm] = Form.useForm()
  const [offerSending, setOfferSending] = useState(false)

  // 待我审核
  const [activeTab, setActiveTab] = useState<'jobs' | 'reviews' | 'stats'>('jobs')
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
    } catch { /* 搜索失败静默 */ }
    finally { if (seq === ownerSearchSeq.current) setOwnerSearching(false) }
  }

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    fetchPositions().then(d => setPosOptions(d.map((p: any) => ({ value: `${p.department}|||${p.name}`, label: `${p.name} (${p.department})` })))).catch(() => { })
  }, [])

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
    try { await deleteJobRequirement(id); msg.success('已删除'); loadJobs() }
    catch (err: any) { msg.error(err.message || '删除失败') }
  }

  const handleParseResume = async () => {
    if (!resumeFile) { msg.warning('请选择简历PDF'); return }
    setResumeLoading(true)
    try {
      const fd = new FormData(); fd.append('resume', resumeFile)
      const d = await parseResumeAction(fd)
      setResumeResult(d.data)
    } catch (err: any) { msg.error(err.message || '解析失败') }
    finally { setResumeLoading(false) }
  }

  const handleCreateCandidate = async () => {
    if (!resumeResult) return
    try {
      const payload: any = {
        name: resumeResult.name || '',
        phone: resumeResult.phone || undefined,
        email: resumeResult.email || undefined,
        gender: resumeResult.gender || undefined,
        school: resumeResult.school || undefined,
        education: resumeResult.education || undefined,
        major: resumeResult.major || undefined,
        position: jobs.find(j => j.id === resumeJobIdRef.current)?.position_name || '',
        department: jobs.find(j => j.id === resumeJobIdRef.current)?.department || '',
        job_requirement_id: resumeJobIdRef.current || undefined,
        status: '待筛选',
        candidate_type: '职能',
        resume_url: resumeResult.resume_file_path || '',
        current_company: resumeResult.current_company || undefined,
        work_years: resumeResult.work_years ?? undefined,
        expected_salary: resumeResult.expected_salary || undefined,
        source: resumeResult.source || '自主上传',
      }
      const res = await createCandidate(payload)
      msg.success('候选人已创建')
      // 乐观更新：先立即显示
      if (res?.data) {
        setAllCandidates(prev => [res.data, ...prev])
        if (resumeJobIdRef.current) setExpandedJobs(prev => new Set([...prev, resumeJobIdRef.current!]))
      }
      setResumeOpen(false); setResumeFile(null); setResumeResult(null)
      resumeJobIdRef.current = null
      // 再从后端拉取最新数据覆盖（确保持久化 + 绕过缓存）
      await loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '创建失败') }
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

  const statusColor: Record<string, string> = { '招聘中': 'green', '已关闭': 'default' }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">招聘管理</h1>
        <div className="flex gap-2">
          <Button type={activeTab === 'reviews' ? 'primary' : 'default'} onClick={() => { setActiveTab('reviews'); loadPendingReviews() }}>
            待我审核 {pendingReviews.length > 0 && `(${pendingReviews.length})`}
          </Button>
          <Button type={activeTab === 'jobs' ? 'primary' : 'default'} onClick={() => setActiveTab('jobs')}>岗位招聘</Button>
          <Button type={activeTab === 'stats' ? 'primary' : 'default'} onClick={() => { setActiveTab('stats'); loadStats() }}>数据分析</Button>
          {activeTab === 'jobs' && <>
            <Button icon={<DownloadOutlined />} onClick={async () => {
              try {
                const { base64, filename } = await downloadCandidateTemplate()
                const url = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${base64}`
                const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
              } catch (e: any) { msg.error(e?.message || '下载失败') }
            }}>模板</Button>
            {mounted && <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={async (file) => {
              const fd = new FormData(); fd.append('file', file as File)
              try {
                const d = await uploadCandidates(fd)
                if (d.code === 200) {
                  msg.success(d.message || `新增${d.data.created}，更新${d.data.updated}`)
                  if (d.data.errors?.length) msg.warning(d.data.errors.slice(0, 3).join('; '))
                  loadAllCandidates()
                }
              } catch (e: any) { msg.error(e?.message || '导入失败') }
              return false
            }}>
              <Button icon={<UploadOutlined />}>导入候选人</Button>
            </Upload>}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingReq(null); reqForm.resetFields(); setReqOpen(true) }}>新建岗位需求</Button>
          </>}
        </div>
      </div>

      {activeTab === 'reviews' && (
        <Card title="待我审核的候选人" loading={reviewsLoading}>
          {pendingReviews.length === 0 ? <Empty description="暂无待审核候选人" className="py-12" /> : (
            <div className="space-y-3">
              {pendingReviews.map((item: any) => {
                const c = item.candidate || {}; const jd = item.job_requirement; const rv = item.review || {}
                return (
                  <Card key={c.id} size="small" hoverable className="cursor-pointer"
                    onClick={() => router.push(`/hr/recruitment/${c.id}`)}
                    extra={<Tag color="orange">待审核</Tag>}
                  >
                    <div className="font-medium">{c.name} · {c.gender || '-'} · {c.education || '-'}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      {c.school} {c.major} · {c.work_years != null ? `${c.work_years}年经验` : ''}
                      {c.current_company ? ` · ${c.current_company}` : ''}
                    </div>
                    <div className="text-xs text-gray-500">岗位：{jd?.position_name || c.position} · {jd?.department || c.department}</div>
                    {rv.push_note && <div className="text-xs text-blue-600 mt-1">💬 HR备注：{rv.push_note}</div>}
                    <div className="flex gap-2 mt-2" onClick={(e) => e.stopPropagation()}>
                      <Button size="small" type="primary" onClick={() => handleDecideReview(c.id, '已同意')}>同意</Button>
                      <Button size="small" danger onClick={() => handleDecideReview(c.id, '已拒绝')}>驳回</Button>
                    </div>
                  </Card>
                )
              })}
            </div>
          )}
        </Card>
      )}

      {activeTab === 'stats' && (
        <Card title="招聘数据分析" loading={statsLoading}>
          {stats ? (
            <div className="space-y-6">
              <div className="flex gap-4">
                <Card size="small" className="flex-1 text-center">
                  <div className="text-3xl font-bold text-blue-600">{stats.total_candidates}</div>
                  <div className="text-xs text-gray-500 mt-1">候选人总数</div>
                </Card>
                <Card size="small" className="flex-1 text-center">
                  <div className="text-3xl font-bold text-green-600">{stats.active_jobs}</div>
                  <div className="text-xs text-gray-500 mt-1">在招岗位数</div>
                </Card>
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
                          <span className="text-xs w-16 text-right text-gray-500">{item.month}</span>
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
                    {stats.source_stats.map((item: { source: string; count: number }) => {
                      const maxS = Math.max(...stats.source_stats!.map((s: { count: number }) => s.count), 1)
                      const pctS = Math.round((item.count / maxS) * 100)
                      const sourceColors = ['#1677ff', '#722ed1', '#fa8c16', '#13c2c2', '#52c41a', '#eb2f96', '#2f54eb']
                      const color = sourceColors[stats.source_stats!.indexOf(item) % sourceColors.length]
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
      )}

      {activeTab === 'jobs' && (<>
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
                   <td className="p-2 border"><Tag style={{fontSize:10}}>{c.status || '-'}</Tag></td>
                   <td className="p-2 border text-center font-medium" style={{color:sc(ev?.jd_match_score)}}>{ev?.jd_match_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border text-center" style={{color:sc(ev?.professional_score)}}>{ev?.professional_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border text-center" style={{color:sc(ev?.communication_score)}}>{ev?.communication_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border text-center" style={{color:sc(ev?.learning_score)}}>{ev?.learning_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border text-center" style={{color:sc(ev?.stability_score)}}>{ev?.stability_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border text-center font-bold" style={{color:sc(ev?.overall_score)}}>{ev?.overall_score?.toFixed(1) || '-'}</td>
                   <td className="p-2 border max-w-[200px] truncate" title={ev?.ai_summary}>{ev?.ai_summary?.slice(0, 50) || '-'}</td>
                 </tr>)
               })}</tbody></table></div>}
        </Card>
      ) : (
        /* 统一按岗位视图 */
        <div className="space-y-2">
          <div className="text-xs text-gray-400 mb-1">{jobs.length} 个岗位 · {allCandidates.length} 个候选人</div>
          {jobs.length === 0 && <Empty description="暂无岗位需求，点击右上角新建" className="py-8" />}
          {jobs.map(j => {
            const jobCandidates = allCandidates.filter(c => c.job_requirement_id === j.id)
            const isExpanded = expandedJobs.has(j.id)
            const STATUS_OPTIONS = [
              { label: '待筛选', value: '待筛选' }, { label: '已筛选', value: '已筛选' },
              { label: '待部门审核', value: '待部门审核' }, { label: '面试中', value: '面试中' },
              { label: '已面试', value: '已面试' }, { label: '录用中', value: '录用中' },
              { label: '已录用', value: '已录用' }, { label: '待入职审批', value: '待入职审批' },
              { label: '已入职', value: '已入职' }, { label: '已拒绝', value: '已拒绝' },
            ]
            const statusColors: Record<string, string> = {
              '待筛选': '#a4a097', '已筛选': '#0075de', '待部门审核': '#dd5b00',
              '面试中': '#7b3ff2', '已面试': '#2a9d99', '录用中': '#1aae39',
              '已录用': '#5645d4', '待入职审批': '#e8b830', '已入职': '#389e0d', '已拒绝': '#ff4d4f',
            }
            const statusOrder = STATUS_OPTIONS.map(s => s.value)
            const sortedCandidates = [...jobCandidates].sort((a, b) => {
              const ia = statusOrder.indexOf(a.status || ''); const ib = statusOrder.indexOf(b.status || '')
              return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
            })
            return (
              <Card key={j.id} size="small"
                title={
                  <div className="flex items-center gap-3 cursor-pointer" onClick={() => toggleJob(j.id)}>
                    {isExpanded ? <DownOutlined style={{ fontSize: 10 }} /> : <RightOutlined style={{ fontSize: 10 }} />}
                    <b className="text-sm">{j.position_name}</b>
                    <span className="text-xs text-gray-400">{j.department}</span>
                    <Tag color={j.status === '招聘中' ? 'green' : 'default'} style={{ fontSize: 10 }}>{j.status}</Tag>
                    <span className="text-xs text-gray-400">{jobCandidates.length}/{j.headcount}人</span>
                    {j.urgency && <Tag color="red" style={{ fontSize: 10 }}>{j.urgency}</Tag>}
                    {!isExpanded && jobCandidates.length > 0 && (
                      <span className="text-[10px] text-gray-300">
                        {sortedCandidates.slice(0, 4).map(c => c.name).join('、')}{jobCandidates.length > 4 ? '…' : ''}
                      </span>
                    )}
                  </div>
                }
                extra={
                  <div className="flex gap-1" onClick={e => e.stopPropagation()}>
                    <Button size="small" onClick={() => loadCompare(j.id)}>对比</Button>
                    <Button size="small" icon={<UploadOutlined />} onClick={() => { setResumeFile(null); setResumeResult(null); resumeJobIdRef.current = j.id; setResumeOpen(true) }} />
                    <a className="text-xs leading-8" onClick={() => { setEditingReq(j); if (j.owner) setOwnerOptions([{ value: j.owner, label: j.owner }]); reqForm.setFieldsValue({ ...j, position_name: `${j.department}|||${j.position_name}`, deadline: j.deadline ? dayjs(j.deadline) : undefined }); setReqOpen(true) }}>编辑</a>
                  </div>
                }
              >
                {!isExpanded ? null : jobCandidates.length === 0 ? (
                  <div className="text-center text-gray-400 text-xs py-4">暂无候选人 — 上传简历或导入Excel添加</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
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
                          <div className="w-1 self-stretch rounded-full flex-shrink-0" style={{ background: statusColors[c.status || '待筛选'] || '#d9d9d9' }} />
                          <div className="flex-1 min-w-0 grid grid-cols-4 gap-x-4 gap-y-0.5">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-medium truncate">{c.name}</span>
                              <span className="text-xs text-gray-400">{c.gender}</span>
                              {c.recommendation_level && (
                                <Tag color={c.recommendation_level === '强烈推荐' ? 'green' : c.recommendation_level === '推荐' ? 'blue' : 'default'}
                                  style={{ fontSize: 10, margin: 0 }}>{c.recommendation_level}</Tag>
                              )}
                            </div>
                            <div className="text-xs text-gray-500 truncate">{c.education || '-'} · {c.school || '-'}</div>
                            <div className="text-xs text-gray-500 truncate">{c.phone || '-'} · {c.email || '-'}</div>
                            <div className="text-xs text-gray-500 truncate">{c.position || j.position_name || '-'} · {c.department || j.department || '-'}</div>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
                            {isStale && <span className="text-xs text-red-400 whitespace-nowrap" title={`已停留${days}天`}>⚠️{days}天</span>}
                            <Select size="small" value={c.status} loading={changingStatus === c.id}
                              style={{ width: 95 }}
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
              placeholder="搜索并选择员工（姓名）"
              options={ownerOptions}
              onSearch={searchOwnerOptions}
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

      <Modal title="上传简历匹配" open={resumeOpen} onCancel={() => setResumeOpen(false)} onOk={handleCreateCandidate} okText="确认创建候选人" okButtonProps={{ disabled: !resumeResult }}>
        <div className="space-y-3">
          <Input type="file" accept=".pdf" onChange={e => setResumeFile((e.target as HTMLInputElement).files?.[0] || null)} />
          <Button icon={<UploadOutlined />} loading={resumeLoading} onClick={handleParseResume} block>解析简历</Button>
          {resumeResult && (
            <div className="text-sm space-y-1 border rounded p-2 bg-gray-50">
              <div>姓名：<b>{resumeResult.name}</b> · 手机：{resumeResult.phone}</div>
              <div>邮箱：{resumeResult.email}</div>
              <div>学校：{resumeResult.school} · 学历：{resumeResult.education} · 专业：{resumeResult.major}</div>
              {resumeResult.current_company && <div>当前公司：{resumeResult.current_company}</div>}
              {resumeResult.work_years != null && <div>工作年限：{resumeResult.work_years}年</div>}
              {resumeResult.expected_salary && <div>期望薪资：{resumeResult.expected_salary}</div>}
              {resumeJobIdRef.current && <div className="text-gray-400">关联岗位：{jobs.find(j => j.id === resumeJobIdRef.current)?.position_name}</div>}
            </div>
          )}
        </div>
      </Modal>
      </>)}
    </div>
  )
}
