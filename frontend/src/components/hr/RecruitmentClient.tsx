'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import { App, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Select, Space, Spin, Tag, Upload } from 'antd'
import { PlusOutlined, UploadOutlined, SendOutlined } from '@ant-design/icons'
import CandidateCardView from './CandidateCardView'
import {
  fetchPositions, fetchCandidates, fetchJobRequirements, fetchPendingReviews,
  fetchCandidateComparison, fetchRecruitmentStats, API_BASE,
} from '@/lib/hr'
import {
  createJobRequirement, updateJobRequirement, deleteJobRequirement,
  createCandidate, deleteCandidate,
  sendOfferAction, parseResumeAction,
} from '@/actions/hr'
import type { JobRequirement, Candidate } from '@/types/hr'

export default function RecruitmentClient() {
  const { message: msg } = App.useApp()
  const router = useRouter()
  const [jobs, setJobs] = useState<JobRequirement[]>([])
  const [selectedJob, setSelectedJob] = useState<JobRequirement | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [loading, setLoading] = useState(false)
  const [reqOpen, setReqOpen] = useState(false)
  const [reqForm] = Form.useForm()
  const [editingReq, setEditingReq] = useState<JobRequirement | null>(null)
  const [resumeOpen, setResumeOpen] = useState(false)
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [resumeResult, setResumeResult] = useState<any>(null)
  const [resumeLoading, setResumeLoading] = useState(false)
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
  const [stats, setStats] = useState<{ total_candidates: number; active_jobs: number; funnel: any[] } | null>(null)
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

  const loadCompare = async (jobId: string) => {
    setCompareLoading(true)
    try { const r = await fetchCandidateComparison(jobId); setCompareData(r.data || []); setShowCompare(true) }
    catch { setCompareData([]) }
    finally { setCompareLoading(false) }
  }

  const loadPendingReviews = useCallback(async () => {
    setReviewsLoading(true)
    try {
      const r = await fetchPendingReviews()
      setPendingReviews(r.data || [])
    } catch { setPendingReviews([]) }
    finally { setReviewsLoading(false) }
  }, [])

  useEffect(() => {
    fetchPositions().then(d => setPosOptions(d.map((p: any) => ({ value: `${p.department}|||${p.name}`, label: `${p.name} (${p.department})` })))).catch(() => { })
  }, [])

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetchJobRequirements()
      setJobs(r.data || [])
    } catch { /* ignore */ }
  }, [])

  const loadCandidates = useCallback(async (jobId: string) => {
    setLoading(true)
    try {
      const r = await fetchCandidates({ job_requirement_id: jobId, page_size: 100 })
      setCandidates(r.data || [])
    } catch { setCandidates([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadJobs() }, [loadJobs])

  const handleSelectJob = (job: JobRequirement) => { setSelectedJob(job); loadCandidates(job.id) }

  const handleSaveReq = async () => {
    const v = await reqForm.validateFields()
    const parts = (v.position_name || '').split('|||')
    const payload: any = {
      position_name: parts[1] || parts[0],
      department: v.department || parts[0],
      headcount: v.headcount ?? 1,
      requirements: v.requirements || undefined,
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
    try { await deleteJobRequirement(id); msg.success('已删除'); loadJobs(); setSelectedJob(null); setCandidates([]) }
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
    if (!resumeResult || !selectedJob) return
    try {
      await createCandidate({
        ...resumeResult,
        position: selectedJob.position_name,
        department: selectedJob.department,
        job_requirement_id: selectedJob.id,
        status: '待筛选',
        candidate_type: '职能',
        name: resumeResult.name || '',
        resume_url: resumeResult.resume_file_path || '',
      })
      msg.success('候选人已关联到岗位')
      setResumeOpen(false); setResumeFile(null); setResumeResult(null)
      loadCandidates(selectedJob.id)
    } catch (err: any) { msg.error(err.message || '创建失败') }
  }

  const handleDeleteCandidate = async (id: string) => {
    try { await deleteCandidate(id); if (selectedJob) loadCandidates(selectedJob.id) }
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
      const r = await fetch(`${API_BASE}/api/v1/hr/candidates/${offerCandidate!.id}/preview-offer`, { method: 'POST', body: fd, credentials: 'include' })
      if (!r.ok) throw new Error('预览失败')
      const html = await r.text()
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
      if (selectedJob) loadCandidates(selectedJob.id)
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
          {activeTab === 'jobs' && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingReq(null); reqForm.resetFields(); setReqOpen(true) }}>新建岗位需求</Button>}
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
            </div>
          ) : (
            <Empty description="暂无数据" className="py-12" />
          )}
        </Card>
      )}

      {activeTab === 'jobs' && (<>
      <div className="flex gap-4">
        <div className="w-72 shrink-0">
          <Card size="small" title={`岗位需求 (${jobs.length})`}>
            {jobs.map(j => (
              <div key={j.id}
                className={`p-2 mb-1 rounded cursor-pointer text-sm border ${selectedJob?.id === j.id ? 'bg-blue-50 border-blue-300' : 'hover:bg-gray-50 border-transparent'}`}
                onClick={() => handleSelectJob(j)}
              >
                <div className="flex justify-between items-center">
                  <div className="font-medium">{j.position_name}</div>
                  <a className="text-[10px]" onClick={e => { e.stopPropagation(); handleDeleteReq(j.id) }}>删除</a>
                </div>
                <div className="text-gray-500 text-xs">{j.department} · {j.hired_count}/{j.headcount}人
                  <Tag color={statusColor[j.status] || 'default'} style={{ fontSize: 10, marginLeft: 4 }}>{j.status}</Tag>
                </div>
                <a className="text-xs" onClick={e => { e.stopPropagation(); setEditingReq(j); reqForm.setFieldsValue({ ...j, position_name: `${j.department}|||${j.position_name}` }); setReqOpen(true) }}>编辑</a>
              </div>
            ))}
            {jobs.length === 0 && <div className="text-gray-400 text-xs text-center py-8">暂无岗位需求</div>}
          </Card>
        </div>
        <div className="flex-1">
          {selectedJob ? (
            <Card size="small" title={`${selectedJob.position_name} — 候选人`}
              extra={<div className="flex gap-1">
                <Button size="small" onClick={() => loadCompare(selectedJob.id)}>{showCompare ? '刷新' : '横向对比'}</Button>
                {showCompare && <Button size="small" onClick={() => setShowCompare(false)}>返回卡片</Button>}
                {!showCompare && <Button size="small" icon={<UploadOutlined />} onClick={() => { setResumeFile(null); setResumeResult(null); setResumeOpen(true) }}>上传简历</Button>}
              </div>}
            >
              {showCompare ? (
                compareLoading ? <div className="text-center py-12"><Spin /></div> :
                compareData.length === 0 ? <Empty description="暂无候选人数据" className="py-12" /> :
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead><tr className="bg-gray-50">
                      <th className="p-2 text-left border sticky left-0 bg-gray-50">姓名</th><th className="p-2 text-left border">学历</th><th className="p-2 text-left border">状态</th>
                      <th className="p-2 border">JD匹配</th><th className="p-2 border">专业</th><th className="p-2 border">沟通</th><th className="p-2 border">学习</th><th className="p-2 border">稳定</th>
                      <th className="p-2 border font-bold">综合</th><th className="p-2 border">AI摘要</th>
                    </tr></thead>
                    <tbody>{compareData.map((item: any, idx: number) => {
                      const c = item.candidate || {}; const ev = item.evaluation
                      const sc = (v: any) => v == null ? '#ccc' : v >= 8 ? '#52c41a' : v >= 6 ? '#1677ff' : v >= 4 ? '#fa8c16' : '#ff4d4f'
                      return (<tr key={c.id} className="hover:bg-blue-50 cursor-pointer border-t" onClick={() => router.push(`/hr/recruitment/${c.id}`)}>
                        <td className="p-2 font-medium sticky left-0 bg-white border"><span className="text-gray-400">{idx + 1}.</span> {c.name}</td>
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
                    })}</tbody></table></div>
              ) : (
                candidates.length === 0 && !loading ? (
                  <div className="text-center text-gray-400 py-12">暂无候选人</div>
                ) : (
                  <CandidateCardView candidates={candidates} onDelete={handleDeleteCandidate} loading={loading}
                    extraActions={(c: Candidate) => (<Button size="small" type="primary" icon={<SendOutlined />} onClick={e => { e.stopPropagation(); handleSendOffer(c) }}>发Offer</Button>) as any} />
                )
              )}
            </Card>
          ) : (
            <div className="text-center text-gray-400 py-20">← 选择左侧岗位查看候选人</div>
          )}
        </div>
      </div>

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
          <Form.Item name="owner" label="招聘负责人"><Input placeholder="可选" /></Form.Item>
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
              <div className="text-gray-400">将关联到：{selectedJob?.position_name}（{selectedJob?.department}）</div>
            </div>
          )}
        </div>
      </Modal>
      </>)}
    </div>
  )
}
