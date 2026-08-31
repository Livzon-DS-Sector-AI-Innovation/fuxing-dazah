'use client'

import CandidateAnalysisReportCard from './CandidateAnalysisReportCard'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  App, Button, Descriptions, Tag, Spin, Select, Input, Tabs,
  Form, DatePicker, Modal, Card, InputNumber, Empty, Space, Checkbox, Upload,
} from 'antd'
import {
  ArrowLeftOutlined, ArrowUpOutlined, ArrowDownOutlined,
  EditOutlined, SaveOutlined, CloseOutlined, PlusOutlined,
  RobotOutlined, CheckCircleOutlined, ClockCircleOutlined, SendOutlined,
} from '@ant-design/icons'
import type { Candidate, Interview, AiEvaluation, OnboardingTask } from '@/types/hr'
import {
  updateCandidateAction, updateCandidateRecommendationLevelAction,
  parseResumeAction,
  transitionCandidateStatus,
  createInterview, updateInterview, deleteInterview, evaluateInterview,
  pushCandidateReview, decideCandidateReview, pushOnboardingReview,
  fetchCandidateInterviews, fetchInterviewEvaluation, fetchPendingReviews,
  onboardCandidate, fetchResumePreview,
  fetchOnboardingTasks, updateOnboardingTask,
  fetchCandidateAnalysisReports, generateCandidateAnalysisReport,
  fetchEmployeesAction,
} from '@/actions/hr'
import { base64ToObjectUrl } from '@/lib/hr'
import AIScoreCard from './AIScoreCard'

interface CandidateDetailClientProps {
  candidate: Candidate
}

export default function CandidateDetailClient({ candidate }: CandidateDetailClientProps) {
  const router = useRouter()
  const { message } = App.useApp()
  const [pdfLoading, setPdfLoading] = useState(true)
  const [pdfError, setPdfError] = useState(false)
  const [pdfErrorMsg, setPdfErrorMsg] = useState('')
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)

  // 简历 PDF 通过 Server Action 获取（不经 /api rewrite 代理），转 blob URL 嵌入 iframe
  useEffect(() => {
    let objectUrl: string | null = null
    fetchResumePreview(candidate.id)
      .then((r) => {
        objectUrl = base64ToObjectUrl(r.base64, 'application/pdf')
        setPdfUrl(objectUrl)
      })
      .catch((err: any) => {
        setPdfErrorMsg(
          err?.message?.includes('无简历文件')
            ? '简历文件缺失，请重新上传'
            : '简历加载失败'
        )
        setPdfError(true)
        setPdfLoading(false)
      })
    return () => { if (objectUrl) window.URL.revokeObjectURL(objectUrl) }
  }, [candidate.id])
  const [recommendationLevel, setRecommendationLevel] = useState(candidate.recommendation_level || '')
  const [updating, setUpdating] = useState(false)
  const [navContext, setNavContext] = useState<{ ids: string[]; currentIndex: number } | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState({
    position: candidate.position || '',
    gender: candidate.gender || '',
    school: candidate.school || '',
    education: candidate.education || '',
    major: candidate.major || '',
    phone: candidate.phone || '',
    email: candidate.email || '',
    expected_salary: candidate.expected_salary || '',
    current_company: candidate.current_company || '',
    work_years: candidate.work_years ?? undefined as number | undefined,
    notes: candidate.notes || '',
  })
  const [saving, setSaving] = useState(false)

  // 面试相关状态
  const [interviews, setInterviews] = useState<Interview[]>([])
  const [analysisReports, setAnalysisReports] = useState<any[]>([])
  const [reportGeneratingId, setReportGeneratingId] = useState<string | null>(null)
  const [interviewsLoading, setInterviewsLoading] = useState(false)
  const [interviewForm] = Form.useForm()
  const [interviewModalOpen, setInterviewModalOpen] = useState(false)
  const [editingInterview, setEditingInterview] = useState<Interview | null>(null)

  // AI评估状态
  const [evaluatingId, setEvaluatingId] = useState<string | null>(null)

  // 入职任务状态
  const [onboardingTasks, setOnboardingTasks] = useState<OnboardingTask[]>([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const tasksLoadedRef = useRef(false)

  // force=true 时跳过「已加载」短路（点「刷新」强制重拉）
  const loadOnboardingTasks = useCallback(async (force = false) => {
    if (tasksLoadedRef.current && !force) return
    setTasksLoading(true)
    try { const r = await fetchOnboardingTasks(candidate.id); setOnboardingTasks(r.data || []) } catch { /* 仅已入职候选人有任务 */ }
    finally { setTasksLoading(false); tasksLoadedRef.current = true }
  }, [candidate.id])
  const [evaluations, setEvaluations] = useState<Record<string, AiEvaluation>>({})

  // 状态流转
  const [statusUpdating, setStatusUpdating] = useState(false)

  // 推送审核
  const [pushModalOpen, setPushModalOpen] = useState(false)
  const [pushForm] = Form.useForm()
  const [pushLoading, setPushLoading] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)

  // 一键入职
  const [onboardLoading, setOnboardLoading] = useState(false)

  const handleOnboard = async () => {
    Modal.confirm({
      title: '确认入职',
      content: `确定将「${candidate.name}」转为入职员工？系统将自动创建入职记录。`,
      onOk: async () => {
        setOnboardLoading(true)
        try {
          const d = await onboardCandidate(candidate.id)
          message.success(`入职成功！工号：${d.data?.employee_number || ''}`)
          router.refresh()
        } catch (err: any) { message.error(err.message || '入职失败') }
        finally { setOnboardLoading(false) }
      },
    })
  }

  useEffect(() => {
    const raw = sessionStorage.getItem('candidate_list_context')
    if (raw) {
      try {
        const parsed = JSON.parse(raw)
        if (parsed.ids?.includes(candidate.id)) setNavContext(parsed)
      } catch { /* ignore */ }
    }
  }, [candidate.id])

  useEffect(() => {
    const timer = setTimeout(() => { if (pdfLoading) { setPdfError(true); setPdfLoading(false) } }, 30000)
    return () => clearTimeout(timer)
  }, [pdfLoading])

  const loadInterviews = useCallback(async () => {
    setInterviewsLoading(true)
    try {
      const r = await fetchCandidateInterviews(candidate.id)
      setInterviews(r.data || [])
      // 已有胜任度报告随页面加载展示（自动生成的历史报告不再隐藏）
      fetchCandidateAnalysisReports(candidate.id)
        .then((d) => setAnalysisReports(d.data || []))
        .catch(() => {})
      for (const iv of (r.data || [])) {
        try {
          const er = await fetchInterviewEvaluation(iv.id)
          if (er.data) setEvaluations(prev => ({ ...prev, [iv.id]: er.data }))
        } catch { /* AI评估加载失败不影响面试列表 */ }
      }
    } catch (err: any) {
      console.error('加载面试列表失败:', err)
      message.error('加载面试列表失败: ' + (err.message || '未知错误'))
      setInterviews([])
    }
    finally { setInterviewsLoading(false) }
  }, [candidate.id, message])

  useEffect(() => { loadInterviews() }, [loadInterviews])

  const handlePrev = () => {
    if (!navContext) return
    const prevIndex = navContext.currentIndex - 1
    const prevId = navContext.ids[prevIndex]
    if (prevId) {
      sessionStorage.setItem('candidate_list_context', JSON.stringify({ ...navContext, currentIndex: prevIndex }))
      router.push(`/hr/recruitment/${prevId}`)
    }
  }

  const handleNext = () => {
    if (!navContext) return
    const nextIndex = navContext.currentIndex + 1
    const nextId = navContext.ids[nextIndex]
    if (nextId) {
      sessionStorage.setItem('candidate_list_context', JSON.stringify({ ...navContext, currentIndex: nextIndex }))
      router.push(`/hr/recruitment/${nextId}`)
    }
  }

  const handleUpdateRecommendation = async (value: string) => {
    if (!value) return
    setUpdating(true)
    try { await updateCandidateRecommendationLevelAction(candidate.id, value); setRecommendationLevel(value); message.success('推荐等级更新成功') }
    catch (err: any) { message.error(err.message || '更新失败') }
    finally { setUpdating(false) }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateCandidateAction(candidate.id, {
        position: formData.position,
        gender: formData.gender || undefined,
        school: formData.school || undefined,
        education: formData.education || undefined,
        major: formData.major || undefined,
        phone: formData.phone || undefined,
        email: formData.email || undefined,
        expected_salary: formData.expected_salary || undefined,
        current_company: formData.current_company || undefined,
        work_years: formData.work_years,
        notes: formData.notes || undefined,
      })
      message.success('保存成功'); setIsEditing(false); router.refresh()
    } catch (err: any) { message.error(err.message || '保存失败') }
    finally { setSaving(false) }
  }

  const handleCancel = () => {
    setFormData({
      position: candidate.position || '', gender: candidate.gender || '',
      school: candidate.school || '', education: candidate.education || '',
      major: candidate.major || '', phone: candidate.phone || '',
      email: candidate.email || '', expected_salary: candidate.expected_salary || '',
      current_company: candidate.current_company || '',
      work_years: candidate.work_years ?? undefined,
      notes: candidate.notes || '',
    })
    setIsEditing(false)
  }

  // 面试操作
  const handleSaveInterview = async () => {
    const v = await interviewForm.validateFields()
    // 格式化日期为 YYYY-MM-DD 字符串，否则 dayjs 序列化后 Pydantic 无法解析
    const payload = {
      ...v,
      interview_date: v.interview_date ? (typeof v.interview_date === 'string' ? v.interview_date : v.interview_date.format('YYYY-MM-DD')) : undefined,
    }
    try {
      if (editingInterview) {
        await updateInterview(editingInterview.id, payload)
      } else {
        await createInterview({ ...payload, candidate_id: candidate.id, job_requirement_id: candidate.job_requirement_id || undefined })
      }
      message.success(editingInterview ? '面试已更新' : '面试已安排')
      setInterviewModalOpen(false); interviewForm.resetFields(); setEditingInterview(null)
      loadInterviews()
    } catch (err: any) { message.error(err.message || '操作失败') }
  }

  const handleDeleteInterview = async (id: string) => {
    Modal.confirm({ title: '确认取消', content: '取消此面试安排？', onOk: async () => { try { await deleteInterview(id); message.success('已取消'); loadInterviews() } catch (err: any) { message.error(err.message || '操作失败') } } })
  }

  const handleGenerateReport = async (interviewId: string) => {
    setReportGeneratingId(interviewId)
    try {
      const r = await generateCandidateAnalysisReport(candidate.id, interviewId)
      message.success(r?.message || '胜任度报告已生成')
      const d = await fetchCandidateAnalysisReports(candidate.id)
      setAnalysisReports(d?.data || [])
    } catch (err: any) {
      message.error(err.message || '生成报告失败')
    } finally {
      setReportGeneratingId(null)
    }
  }

  const handleEvaluate = async (interviewId: string) => {
    setEvaluatingId(interviewId)
    try {
      const r = await evaluateInterview(interviewId)
      setEvaluations(prev => ({ ...prev, [interviewId]: r.data }))
      message.success('AI评估完成')
    } catch (err: any) { message.error(err.message || '评估失败') }
    finally { setEvaluatingId(null) }
  }

  // 状态流转
  const handleStatusTransition = async (newStatus: string) => {
    setStatusUpdating(true)
    try {
      await transitionCandidateStatus(candidate.id, { status: newStatus })
      message.success(`状态已变更为「${newStatus}」`)
      router.refresh()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setStatusUpdating(false) }
  }

  const recommendationOptions = [
    { value: '强烈推荐', label: '强烈推荐' }, { value: '推荐', label: '推荐' },
    { value: '待定', label: '待定' }, { value: '不推荐', label: '不推荐' },
  ]
  const recommendationColors: Record<string, string> = { '强烈推荐': 'green', '推荐': 'blue', '待定': 'orange', '不推荐': 'red' }
  const statusTransitions: Record<string, string[]> = {
    '待筛选': ['已筛选', '已拒绝'],
    '已筛选': ['待部门审核', '已拒绝'],
    '待部门审核': ['面试中', '已拒绝'],
    '面试中': ['已面试', '已拒绝'],
    '已面试': ['录用中', '已拒绝'],
    '录用中': ['已录用', '已拒绝'],
    '已录用': ['待入职审批', '已拒绝'],
    // 已入职只能通过「入职操作」完成（创建入职记录/工号/子任务），不放裸流转
    '待入职审批': ['已录用', '已拒绝'],
  }
  // 审核人选择器：远程搜索在职员工（值存姓名，发卡按姓名查人）
  const [reviewerOptions, setReviewerOptions] = useState<{ value: string; label: string }[]>([])
  const [reviewerSearching, setReviewerSearching] = useState(false)
  const reviewerSearchSeq = useRef(0)
  const searchReviewerOptions = async (keyword: string) => {
    const seq = ++reviewerSearchSeq.current
    setReviewerSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== reviewerSearchSeq.current) return  // 过期响应丢弃
      setReviewerOptions(((d?.data as any)?.items || (d?.data as any) || []).map((e: any) => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || ''}）`,
      })))
    } catch { /* 搜索失败静默 */ }
    finally { if (seq === reviewerSearchSeq.current) setReviewerSearching(false) }
  }

  // 补传/更新简历：解析 PDF → 更新 resume_url → 刷新预览
  const handleResumeUpload = async (file: File) => {
    const fd = new FormData()
    fd.append('resume', file)
    try {
      const r = await parseResumeAction(fd)
      const path = (r?.data as any)?.resume_file_path || (r as any)?.resume_file_path
      if (!path) throw new Error('简历解析失败，未返回文件路径')
      await updateCandidateAction(candidate.id, { resume_url: path })
      message.success('简历已更新')
      window.location.reload()
    } catch (err: any) { message.error(err.message || '上传失败') }
    return false // 阻止 Upload 默认上传
  }

  // 发起入职审批（已录用状态 → 推送入职审批，审核人同意后由 HR 转为入职员工）
  const handlePushOnboarding = () => {
    Modal.confirm({
      title: '发起入职审批',
      content: '将把该候选人推送至入职审批流程，确认？',
      okText: '确认发起',
      onOk: async () => {
        try {
          await pushOnboardingReview(candidate.id, { pushed_by: 'HR' })
          message.success('已发起入职审批')
          router.refresh()
        } catch (err: any) { message.error(err.message || '发起失败') }
      },
    })
  }

  // 推送审核操作
  const handlePushReview = async () => {
    const v = await pushForm.validateFields()
    setPushLoading(true)
    try {
      await pushCandidateReview(candidate.id, { pushed_by: 'HR', push_note: v.push_note, reviewer: v.reviewer || undefined })
      message.success('已推送至用人部门审核')
      setPushModalOpen(false); pushForm.resetFields()
      router.refresh()
    } catch (err: any) { message.error(err.message || '推送失败') }
    finally { setPushLoading(false) }
  }

  const handleDecideReview = async (decision: string) => {
    let comment = ''
    if (decision === '已拒绝') {
      // 不合适时需要填写原因
      Modal.confirm({
        title: '确认不合适',
        content: (
          <div className="mt-2">
            <div className="text-sm mb-1">请填写不合适原因：</div>
            <Input.TextArea id="reject-reason" rows={3} placeholder="简述不合适原因" />
          </div>
        ),
        onOk: async () => {
          const input = document.getElementById('reject-reason') as HTMLTextAreaElement
          comment = input?.value || ''
          if (!comment.trim()) { message.warning('请填写原因'); return Promise.reject() }
          await doDecide(decision, comment)
        },
      })
    } else {
      await doDecide(decision)
    }
  }

  const doDecide = async (decision: string, comment?: string) => {
    setReviewLoading(true)
    try {
      await decideCandidateReview(candidate.id, { decision, review_comment: comment })
      message.success(decision === '已同意' ? '已同意面试' : '已标记为不合适')
      router.refresh()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setReviewLoading(false) }
  }

  const nextStatuses = statusTransitions[candidate.status || ''] || []

  // ─── 基本信息 Tab ───
  const infoTab = (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 180px)' }}>
      <div className="flex-[3] bg-white rounded-xl border border-[#e5e3df] overflow-hidden relative">
        <Spin spinning={pdfLoading} className="absolute inset-0 z-10 flex items-center justify-center" />
        {pdfError && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-white">
            <p className="text-gray-500 mb-4">{pdfErrorMsg || '简历加载失败'}</p>
            <Space>
              <Upload
                accept=".pdf"
                showUploadList={false}
                beforeUpload={handleResumeUpload}
              >
                <Button type="primary">上传简历</Button>
              </Upload>
              <Button onClick={() => window.location.reload()}>刷新页面</Button>
            </Space>
          </div>
        )}
        {pdfUrl && (
          <iframe src={pdfUrl} className="w-full h-full border-0"
            onLoad={() => setPdfLoading(false)} title="简历预览" />
        )}
      </div>
      <div className="flex-[2] bg-white rounded-xl border border-[#e5e3df] p-6 overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-semibold">{candidate.name}</h2>
            {recommendationLevel && <Tag color={recommendationColors[recommendationLevel] || 'default'}>{recommendationLevel}</Tag>}
            <Tag>{candidate.status || '未知'}</Tag>
          </div>
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={handleSave}>保存修改</Button>
                <Button icon={<CloseOutlined />} onClick={handleCancel} disabled={saving}>取消</Button>
              </>
            ) : (
              <Button icon={<EditOutlined />} onClick={() => setIsEditing(true)}>编辑</Button>
            )}
          </div>
        </div>

        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="应聘职位">
            {isEditing ? <Input value={formData.position} onChange={e => setFormData({ ...formData, position: e.target.value })} /> : (candidate.position || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="手机">
            {isEditing ? <Input value={formData.phone} onChange={e => setFormData({ ...formData, phone: e.target.value })} /> : (candidate.phone || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="邮箱">
            {isEditing ? <Input value={formData.email} onChange={e => setFormData({ ...formData, email: e.target.value })} /> : (candidate.email || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="性别">
            {isEditing ? <Input value={formData.gender} onChange={e => setFormData({ ...formData, gender: e.target.value })} /> : (candidate.gender || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="学校">
            {isEditing ? <Input value={formData.school} onChange={e => setFormData({ ...formData, school: e.target.value })} /> : (candidate.school || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="学历">{isEditing ? <Input value={formData.education} onChange={e => setFormData({ ...formData, education: e.target.value })} /> : <Tag color="blue">{candidate.education || '-'}</Tag>}</Descriptions.Item>
          <Descriptions.Item label="专业">
            {isEditing ? <Input value={formData.major} onChange={e => setFormData({ ...formData, major: e.target.value })} /> : (candidate.major || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="当前公司">
            {isEditing ? <Input value={formData.current_company} onChange={e => setFormData({ ...formData, current_company: e.target.value })} /> : (candidate.current_company || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="工作年限">
            {isEditing ? <InputNumber value={formData.work_years} onChange={v => setFormData({ ...formData, work_years: v ?? undefined })} style={{ width: '100%' }} /> : (candidate.work_years != null ? `${candidate.work_years}年` : '-')}
          </Descriptions.Item>
          <Descriptions.Item label="期望薪资">
            {isEditing ? <Input value={formData.expected_salary} onChange={e => setFormData({ ...formData, expected_salary: e.target.value })} /> : (candidate.expected_salary || '-')}
          </Descriptions.Item>
          <Descriptions.Item label="Offer状态">{candidate.offer_status ? <Tag color={candidate.offer_status === '已接受' ? 'green' : candidate.offer_status === '已拒绝' ? 'red' : 'blue'}>{candidate.offer_status}</Tag> : <span className="text-gray-400">未发送</span>}</Descriptions.Item>
          {candidate.status === '已录用' && (
            <Descriptions.Item label="入职操作">
              <Button type="primary" onClick={handlePushOnboarding}>
                📋 发起入职审批
              </Button>
            </Descriptions.Item>
          )}
          {candidate.status === '待入职审批' && (
            <Descriptions.Item label="入职操作">
              <Space>
                <Button type="primary" loading={onboardLoading} onClick={handleOnboard}>
                  🎉 转为入职员工（审批通过）
                </Button>
                <Button danger onClick={() => handleDecideReview('已拒绝')}>
                  驳回入职
                </Button>
              </Space>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="备注">
            {isEditing ? <Input.TextArea value={formData.notes} onChange={e => setFormData({ ...formData, notes: e.target.value })} rows={2} /> : (candidate.notes || '-')}
          </Descriptions.Item>
          {candidate.match_report && (
            <Descriptions.Item label="AI匹配报告">
              <div className="text-sm whitespace-pre-wrap">{candidate.match_report}</div>
            </Descriptions.Item>
          )}
        </Descriptions>

        <div className="mt-6 pt-4 border-t border-gray-100 space-y-4">
          <div>
            <h3 className="text-sm font-medium mb-2">推荐等级</h3>
            <Select style={{ width: '100%' }} placeholder="选择推荐等级" value={recommendationLevel || undefined}
              onChange={handleUpdateRecommendation} options={recommendationOptions} loading={updating} />
          </div>
          {/* 推送审核：已筛选状态时显示 */}
          {candidate.status === '已筛选' && (
            <div className="mt-2">
              <Button type="primary" icon={<SendOutlined />} onClick={() => { pushForm.resetFields(); setPushModalOpen(true) }}>
                推送给用人部门审核
              </Button>
            </div>
          )}
          {/* 审核决策：待部门审核时显示 */}
          {candidate.status === '待部门审核' && (
            <div className="mt-2 p-3 rounded bg-orange-50 border border-orange-200">
              <div className="text-sm font-medium text-orange-700 mb-2">⏳ 待用人部门审核</div>
              <div className="flex gap-2">
                <Button type="primary" icon={<CheckCircleOutlined />}
                  loading={reviewLoading} onClick={() => handleDecideReview('已同意')}>
                  同意面试
                </Button>
                <Button danger loading={reviewLoading} onClick={() => handleDecideReview('已拒绝')}>
                  不合适
                </Button>
              </div>
            </div>
          )}
          {nextStatuses.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-2">状态流转</h3>
              <div className="flex gap-2">
                {nextStatuses.map(s => (
                  <Button key={s} size="small" loading={statusUpdating} onClick={() => handleStatusTransition(s)}>{s}</Button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  // ─── 面试记录 Tab ───
  const interviewTab = (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">面试记录</h3>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingInterview(null); interviewForm.resetFields(); setInterviewModalOpen(true) }}>安排面试</Button>
      </div>

      {interviewsLoading ? <Spin className="flex justify-center py-12" /> :
        interviews.length === 0 ? <Empty description="暂无面试记录" className="py-12" /> :
          <div className="space-y-4">
            {interviews.map((iv) => {
              const eval_ = evaluations[iv.id]
              return (
                <Card key={iv.id} size="small" title={
                  <div className="flex items-center gap-2">
                    <Tag color={iv.status === '已完成' ? 'green' : iv.status === '已取消' ? 'red' : 'blue'}>{iv.status}</Tag>
                    <span>{iv.interview_type}</span>
                    <span className="text-gray-400 text-xs">{iv.interview_date}</span>
                    {iv.calendar_event_id && <Tag color="purple" className="text-xs">日历已同步</Tag>}
                  </div>
                } extra={
                  <div className="flex gap-1">
                    <Button size="small" onClick={() => { setEditingInterview(iv); interviewForm.setFieldsValue(iv); setInterviewModalOpen(true) }}>编辑</Button>
                    <Button size="small" danger onClick={() => handleDeleteInterview(iv.id)}>取消</Button>
                  </div>
                }>
                  <Descriptions size="small" column={2}>
                    <Descriptions.Item label="面试官">{iv.interviewer || '-'}</Descriptions.Item>
                    <Descriptions.Item label="地点">{iv.location || '-'}</Descriptions.Item>
                  </Descriptions>

                  {/* 逐字稿输入区 */}
                  <div className="mt-3">
                    <div className="text-xs text-gray-500 mb-1">面试逐字稿（粘贴第三方转写文本）</div>
                    <Input.TextArea
                      rows={4}
                      defaultValue={iv.transcript_text || ''}
                      placeholder="粘贴面试逐字稿..."
                      onBlur={async (e) => {
                        const val = e.target.value
                        if (val !== iv.transcript_text) {
                          try { await updateInterview(iv.id, { transcript_text: val || undefined }); message.success('逐字稿已保存') }
                          catch { /* ignore */ }
                        }
                      }}
                    />
                  </div>

                  {/* AI评估区域 */}
                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                    {eval_ ? (
                      <AIScoreCard evaluation={eval_} onReEvaluate={() => handleEvaluate(iv.id)} loading={evaluatingId === iv.id} />
                    ) : (
                      <Button icon={<RobotOutlined />} loading={evaluatingId === iv.id}
                        onClick={() => handleEvaluate(iv.id)}
                        disabled={!iv.transcript_text}>
                        {iv.transcript_text ? '🤖 AI 评估' : '请先填写逐字稿'}
                      </Button>
                    )}
                    <Button
                      icon={<SendOutlined />}
                      loading={reportGeneratingId === iv.id}
                      onClick={() => handleGenerateReport(iv.id)}
                      disabled={!(iv.transcript_text || iv.notes)}
                    >
                      {iv.transcript_text || iv.notes ? '📊 生成胜任度报告' : '请先填写面试记录'}
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
      }

      {/* 胜任度分析报告 */}
      {analysisReports.length > 0 && (
        <Card title="📊 胜任度多维分析报告" className="mt-4">
          <div className="space-y-4">
            {analysisReports.map((r) => (
              <div key={r.id} className="border-b border-[var(--color-hairline)] pb-3 last:border-b-0 last:pb-0">
                <CandidateAnalysisReportCard report={r} />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 面试安排 Modal */}
      <Modal title={editingInterview ? '编辑面试' : '安排面试'} open={interviewModalOpen}
        onCancel={() => setInterviewModalOpen(false)} onOk={handleSaveInterview}>
        <Form form={interviewForm} layout="vertical">
          <Form.Item name="interview_type" label="面试类型" initialValue="初试">
            <Select options={[{ label: '初试', value: '初试' }, { label: '复试', value: '复试' }, { label: '终试', value: '终试' }]} />
          </Form.Item>
          <Form.Item name="interview_date" label="面试日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="interviewer" label="面试官"><Input /></Form.Item>
          <Form.Item name="location" label="面试地点"><Input placeholder="会议室/线上链接等" /></Form.Item>
          {!editingInterview && (
            <Form.Item name="create_calendar_event" label="飞书日历" valuePropName="checked" initialValue={false}>
              <Checkbox>同步创建飞书日历日程</Checkbox>
            </Form.Item>
          )}
          {editingInterview && (
            <>
              <Form.Item name="status" label="状态">
                <Select options={[{ label: '待安排', value: '待安排' }, { label: '已安排', value: '已安排' }, { label: '已完成', value: '已完成' }, { label: '已取消', value: '已取消' }]} />
              </Form.Item>
              <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 推送审核 Modal */}
      <Modal title="推送候选人给用人部门" open={pushModalOpen} onCancel={() => setPushModalOpen(false)}
        onOk={handlePushReview} confirmLoading={pushLoading} okText="确认推送">
        <Form form={pushForm} layout="vertical" className="mt-2">
          <div className="text-sm text-gray-500 mb-3">
            推送至「{candidate.department}」用人部门负责人
          </div>
          <Form.Item name="reviewer" label="用人部门负责人" rules={[{ required: true, message: '请选择用人部门负责人' }]}>
            <Select
              showSearch
              filterOption={false}
              loading={reviewerSearching}
              placeholder="搜索并选择员工（姓名），将发送飞书通知"
              options={reviewerOptions}
              onSearch={searchReviewerOptions}
            />
          </Form.Item>
          <Form.Item name="push_note" label="推送备注（选填）">
            <Input.TextArea rows={3} placeholder="写给用人部门的话，如：GMP经验对口，建议面试" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )

  // ─── 入职任务 Tab ───
  const onboardingTasksTab = (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">入职任务</h3>
        <Button size="small" onClick={() => loadOnboardingTasks(true)}>刷新</Button>
      </div>
      {tasksLoading ? <Spin className="flex justify-center py-12" /> :
        onboardingTasks.length === 0 ? <Empty description="暂无入职任务（入职审批通过后自动创建）" className="py-12" /> :
          <div className="space-y-2">
            {onboardingTasks.map(task => {
              const isDone = task.status === '已完成'
              return (
                <Card key={task.id} size="small" className={isDone ? 'opacity-70' : ''}
                  style={{ borderRadius: 10, borderLeft: isDone ? '3px solid #1aae39' : '3px solid #dd5b00' }}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-lg">{isDone ? '✅' : '⏳'}</span>
                      <div>
                        <div className="font-medium text-sm" style={{ color: 'var(--color-charcoal)' }}>{task.task_type}</div>
                        {task.completed_at && <div className="text-xs text-gray-400">完成于 {new Date(task.completed_at).toLocaleDateString('zh-CN')}{task.completed_by ? ` · ${task.completed_by}` : ''}</div>}
                        {task.notes && <div className="text-xs text-gray-400 mt-0.5">{task.notes}</div>}
                      </div>
                    </div>
                    <Button size="small" type={isDone ? 'default' : 'primary'}
                      onClick={async () => {
                        const newStatus = isDone ? '待完成' : '已完成'
                        try {
                          await updateOnboardingTask(candidate.id, task.id, { status: newStatus })
                          setOnboardingTasks(prev => prev.map(t => t.id === task.id ? { ...t, status: newStatus, completed_at: newStatus === '已完成' ? new Date().toISOString() : undefined } as OnboardingTask : t))
                          message.success(isDone ? '已重置' : '已完成')
                        } catch (err: any) { message.error(err.message || '操作失败') }
                      }}>
                      {isDone ? '重置' : '完成'}
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
      }
    </div>
  )

  const tabItems = [
    { key: 'info', label: '基本信息', children: infoTab },
    { key: 'interviews', label: `面试记录 (${interviews.length})`, children: interviewTab },
    { key: 'onboarding', label: `入职任务 (${onboardingTasks.filter(t => t.status === '已完成').length}/${onboardingTasks.length})`, children: onboardingTasksTab },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/hr/recruitment')}>返回列表</Button>
        {navContext && (
          <>
            <Button icon={<ArrowUpOutlined />} onClick={handlePrev} disabled={navContext.currentIndex <= 0}>上一条</Button>
            <Button icon={<ArrowDownOutlined />} onClick={handleNext} disabled={navContext.currentIndex >= navContext.ids.length - 1}>下一条</Button>
          </>
        )}
      </div>
      <Tabs items={tabItems} onChange={key => { if (key === 'onboarding') loadOnboardingTasks() }} />
    </div>
  )
}
