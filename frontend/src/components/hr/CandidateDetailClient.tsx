'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Button, Descriptions, Tag, Spin, Select, Input, message, Tabs,
  Form, DatePicker, Modal, Card, InputNumber, Empty,
} from 'antd'
import {
  ArrowLeftOutlined, ArrowUpOutlined, ArrowDownOutlined,
  EditOutlined, SaveOutlined, CloseOutlined, PlusOutlined,
  RobotOutlined, CheckCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import type { Candidate, Interview, AiEvaluation } from '@/types/hr'
import {
  updateCandidateAction, updateCandidateRecommendationLevelAction,
  transitionCandidateStatus,
} from '@/actions/hr'
import {
  fetchCandidateInterviews, fetchInterviewEvaluation, API_BASE,
} from '@/lib/hr'
import {
  createInterview, updateInterview, deleteInterview, evaluateInterview,
} from '@/actions/hr'
import AIScoreCard from './AIScoreCard'

interface CandidateDetailClientProps {
  candidate: Candidate
}

export default function CandidateDetailClient({ candidate }: CandidateDetailClientProps) {
  const router = useRouter()
  const [pdfLoading, setPdfLoading] = useState(true)
  const [pdfError, setPdfError] = useState(false)
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
  const [interviewsLoading, setInterviewsLoading] = useState(false)
  const [interviewForm] = Form.useForm()
  const [interviewModalOpen, setInterviewModalOpen] = useState(false)
  const [editingInterview, setEditingInterview] = useState<Interview | null>(null)

  // AI评估状态
  const [evaluatingId, setEvaluatingId] = useState<string | null>(null)
  const [evaluations, setEvaluations] = useState<Record<string, AiEvaluation>>({})

  // 状态流转
  const [statusUpdating, setStatusUpdating] = useState(false)

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
      // 加载已有评估
      for (const iv of (r.data || [])) {
        try {
          const er = await fetchInterviewEvaluation(iv.id)
          if (er.data) setEvaluations(prev => ({ ...prev, [iv.id]: er.data }))
        } catch { /* ignore */ }
      }
    } catch { setInterviews([]) }
    finally { setInterviewsLoading(false) }
  }, [candidate.id])

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
    '已筛选': ['面试中', '已拒绝'],
    '面试中': ['已面试', '已拒绝'],
    '已面试': ['录用中', '已拒绝'],
    '录用中': ['已录用', '已拒绝'],
  }
  const nextStatuses = statusTransitions[candidate.status || ''] || []

  // ─── 基本信息 Tab ───
  const infoTab = (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 180px)' }}>
      <div className="flex-[3] bg-white rounded-xl border border-[#e5e3df] overflow-hidden relative">
        <Spin spinning={pdfLoading} className="absolute inset-0 z-10 flex items-center justify-center" />
        {pdfError && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-white">
            <p className="text-gray-500 mb-4">简历加载失败</p>
            <Button onClick={() => window.location.reload()}>刷新页面</Button>
          </div>
        )}
        <iframe src={`/api/v1/hr/candidates/${candidate.id}/resume-preview`} className="w-full h-full border-0"
          onLoad={() => setPdfLoading(false)} title="简历预览" />
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
          <Descriptions.Item label="备注">
            {isEditing ? <Input.TextArea value={formData.notes} onChange={e => setFormData({ ...formData, notes: e.target.value })} rows={2} /> : (candidate.notes || '-')}
          </Descriptions.Item>
        </Descriptions>

        <div className="mt-6 pt-4 border-t border-gray-100 space-y-4">
          <div>
            <h3 className="text-sm font-medium mb-2">推荐等级</h3>
            <Select style={{ width: '100%' }} placeholder="选择推荐等级" value={recommendationLevel || undefined}
              onChange={handleUpdateRecommendation} options={recommendationOptions} loading={updating} />
          </div>
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
                  <div className="mt-3">
                    {eval_ ? (
                      <AIScoreCard evaluation={eval_} onReEvaluate={() => handleEvaluate(iv.id)} loading={evaluatingId === iv.id} />
                    ) : (
                      <Button icon={<RobotOutlined />} loading={evaluatingId === iv.id}
                        onClick={() => handleEvaluate(iv.id)}
                        disabled={!iv.transcript_text}>
                        {iv.transcript_text ? '🤖 AI 评估' : '请先填写逐字稿'}
                      </Button>
                    )}
                  </div>
                </Card>
              )
            })}
          </div>
      }

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
    </div>
  )

  const tabItems = [
    { key: 'info', label: '基本信息', children: infoTab },
    { key: 'interviews', label: `面试记录 (${interviews.length})`, children: interviewTab },
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
      <Tabs items={tabItems} />
    </div>
  )
}
