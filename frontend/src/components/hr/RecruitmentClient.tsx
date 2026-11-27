'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import dayjs from 'dayjs'
import { Alert, App, Badge, Button, Card, DatePicker, Dropdown, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Spin, Table, Tabs, Tag, Tooltip, Upload } from 'antd'
import {
  DownOutlined, RightOutlined, FileSearchOutlined, ClockCircleOutlined,
  EditOutlined, DeleteOutlined, SwapOutlined, WarningOutlined, CommentOutlined,
  CheckCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import {
  createJobRequirement, updateJobRequirement, deleteJobRequirement,
  createCandidate, deleteCandidate,
  sendOfferAction, parseResumeAction, transitionCandidateStatus,
  fetchPositions, fetchCandidates, fetchJobRequirements, fetchPendingReviews,
  fetchCandidateComparison, fetchRecruitmentStats, previewOffer,
  decideCandidateReview,
  fetchEmployeesAction, screenCandidateAction, fetchInterviewsOverview,
  updateInterview, deleteInterview, fetchRecruitmentPositionInfo,
} from '@/actions/hr'
import type { Candidate, InterviewOverviewItem, JobRequirement, JobRequirementCreateInput, JobRequirementUpdateInput, RecruitmentPositionInfo, RecruitmentStats } from '@/types/hr'
import { usePermission } from '@/hooks/usePermission'
import { useDebouncedCallback } from '@/hooks/hr'
import { CANDIDATE_STATUS_COLORS, RECOMMENDATION_LEVEL_TAG_COLORS } from '@/lib/hr'
import ResumeScreeningPanel from './ResumeScreeningPanel'
import InterviewScheduleModal from './InterviewScheduleModal'
import { RecruitmentPositionInfoModal, type RecruitmentPositionTarget } from './recruitment-positions'
import PageHeader from './PageHeader'

// 后端对「发 Offer」有状态限制（其它状态直接 400），按钮只在这些状态显示
const OFFER_STATUSES = new Set(['已面试', '录用中', '已录用', '待入职审批'])

type RecruitmentTab = 'jobs' | 'reviews' | 'stats' | 'screening' | 'interviews'
const RECRUITMENT_TABS: RecruitmentTab[] = ['jobs', 'reviews', 'stats', 'screening', 'interviews']

/** 新建 / 编辑岗位需求表单的取值 */
interface ReqFormValues {
  position_name?: string
  department?: string
  headcount?: number
  requirements?: string
  duties?: string
  urgency?: string
  owner?: string
  deadline?: dayjs.Dayjs | null
  status?: string
}

/** 岗位需求弹窗里当前选中的岗位，以及它在「招聘岗位信息」里的配置情况 */
type SelectedPosition = RecruitmentPositionTarget & {
  info: 'loading' | 'configured' | 'missing' | 'failed'
}

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

// 候选人状态全集（排序 + 下拉候选用），状态色统一走共享 CANDIDATE_STATUS_COLORS
const STATUS_OPTIONS = [
  { label: '待筛选', value: '待筛选' }, { label: '已筛选', value: '已筛选' },
  { label: '待部门审核', value: '待部门审核' }, { label: '面试中', value: '面试中' },
  { label: '已面试', value: '已面试' }, { label: '录用中', value: '录用中' },
  { label: '已录用', value: '已录用' }, { label: '待入职审批', value: '待入职审批' },
  { label: '已入职', value: '已入职' }, { label: '已拒绝', value: '已拒绝' },
]
// 面试前筛简历阶段：AI 简历初筛按钮只在这些状态显示（进入面试后以胜任度分析报告为准）
const SCREENING_PHASE_STATUSES = new Set(['待筛选', '已筛选', '待部门审核'])
const STATUS_COLORS = CANDIDATE_STATUS_COLORS
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
  const { message: msg, modal } = App.useApp()
  const router = useRouter()
  // 跳转候选人详情前把当前列表上下文（id 顺序 + 当前位置）写入 sessionStorage，
  // 供详情页"上一条/下一条"顺序切换（CandidateDetailClient 读取 candidate_list_context）
  // tab：直达详情页某个 Tab（如面试总览行点击带 interviews，免去再手动切换）
  const openCandidateDetail = (id: string, listIds: string[], tab?: string) => {
    const ids = [...new Set(listIds)].filter(Boolean)
    if (ids.length > 1 && ids.includes(id)) {
      sessionStorage.setItem('candidate_list_context', JSON.stringify({ ids, currentIndex: ids.indexOf(id) }))
    } else {
      sessionStorage.removeItem('candidate_list_context')
    }
    router.push(`/hr/recruitment/${id}${tab ? `?tab=${tab}` : ''}`)
  }
  // 招聘管理权限：人事专员见全功能；用人部门负责人（审核人）仅见"待我审核"。
  // 页面外层 PermissionGuard 已等权限加载完成，此处 hasPermission 结果可靠。
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:recruitment:manage')
  const [jobs, setJobs] = useState<JobRequirement[]>([])
  const [allCandidates, setAllCandidates] = useState<Candidate[]>([])
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set())
  // 各岗位表格的状态筛选（漏斗 chips 点击），null/缺省=不筛选
  const [jobStatusFilter, setJobStatusFilter] = useState<Record<string, string | null>>({})
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
  // 下拉选项值（「部门|||岗位名」）→ 岗位库里的岗位 id，选中岗位后按 id 读它的招聘信息
  const [posIdByKey, setPosIdByKey] = useState<Record<string, string>>({})
  const [selectedPosition, setSelectedPosition] = useState<SelectedPosition | null>(null)
  // 表单里的两个描述字段是不是刚从岗位信息原样带出来的（用户一改就清掉）：换岗位时据此决定要不要跟着换。
  // 读取在 await 之后才用它判断，所以真值放 ref，state 只管让提示条重渲染
  const filledFromRef = useRef<string | null>(null)
  const [filledFromId, setFilledFromIdState] = useState<string | null>(null)
  const setFilledFromId = (id: string | null) => {
    filledFromRef.current = id
    setFilledFromIdState(id)
  }
  // 读取招聘信息的序号守卫：连着换岗位时，慢的旧响应不得覆盖新选的岗位
  const positionInfoSeq = useRef(0)
  // 选中岗位还没配置招聘信息时，就地配置
  const [infoEditorOpen, setInfoEditorOpen] = useState(false)
  const [infoEditorTarget, setInfoEditorTarget] = useState<RecruitmentPositionTarget | null>(null)
  const [offerOpen, setOfferOpen] = useState(false)
  const [offerCandidate, setOfferCandidate] = useState<Candidate | null>(null)
  const [offerForm] = Form.useForm()
  const [offerSending, setOfferSending] = useState(false)

  // 待我审核（无管理权限的审核人默认落在"待我审核"）
  // 当前页签写进网址 ?tab=：候选人详情页「返回」时能回到原来的页签
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const urlTab = searchParams.get('tab') as RecruitmentTab | null
  const [activeTab, setActiveTab] = useState<RecruitmentTab>(
    canManage ? (urlTab && RECRUITMENT_TABS.includes(urlTab) ? urlTab : 'jobs') : 'reviews',
  )
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

  // 面试总览：跨候选人按日期查看（默认过去 7 天 ~ 未来 30 天）
  const [overviewRows, setOverviewRows] = useState<InterviewOverviewItem[]>([])
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [overviewTotal, setOverviewTotal] = useState(0)
  const [overviewDateRange, setOverviewDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>([
    dayjs().subtract(7, 'day'), dayjs().add(30, 'day'),
  ])
  const [overviewCandidate, setOverviewCandidate] = useState('')
  const [overviewStatus, setOverviewStatus] = useState<string | undefined>(undefined)
  // 姓名即查（防抖 300ms），回车/点搜索按钮立即查：此前要按回车才查，旁边还多一个「查询」按钮
  const { run: debouncedSetOverviewCandidate, cancel: cancelOverviewDebounce } = useDebouncedCallback(
    (v: string) => setOverviewCandidate(v), 300,
  )
  // 总览行内操作：编辑走共享弹窗；完成/取消一键（免跳候选人详情）
  const [overviewEdit, setOverviewEdit] = useState<InterviewOverviewItem | null>(null)
  const [actingId, setActingId] = useState<string | null>(null)
  // 请求序号守卫：筛选连续变化时，慢的旧响应不得覆盖新结果
  const overviewSeq = useRef(0)
  const loadOverview = useCallback(async () => {
    const seq = ++overviewSeq.current
    setOverviewLoading(true)
    try {
      const r = await fetchInterviewsOverview({
        date_from: overviewDateRange?.[0]?.format('YYYY-MM-DD'),
        date_to: overviewDateRange?.[1]?.format('YYYY-MM-DD'),
        candidate_name: overviewCandidate || undefined,
        status: overviewStatus,
        page_size: 200,
      })
      if (seq !== overviewSeq.current) return
      setOverviewRows(r.data || [])
      setOverviewTotal(r.meta?.total ?? (r.data || []).length)
    } catch (err: any) {
      if (seq !== overviewSeq.current) return
      msg.error(err?.message || '获取面试总览失败')
      setOverviewRows([])
    } finally { if (seq === overviewSeq.current) setOverviewLoading(false) }
  }, [overviewDateRange, overviewCandidate, overviewStatus, msg])

  // 总览行内快捷操作：标记完成 / 取消（都刷新总览列表）
  const handleOverviewComplete = async (id: string) => {
    setActingId(id)
    try {
      await updateInterview(id, { status: '已完成' })
      msg.success('面试已标记完成')
      loadOverview()
    } catch (err: any) { msg.error(err?.message || '操作失败') }
    finally { setActingId(null) }
  }

  const handleOverviewCancel = async (id: string) => {
    setActingId(id)
    try {
      await deleteInterview(id)
      msg.success('面试已取消')
      loadOverview()
    } catch (err: any) { msg.error(err?.message || '操作失败') }
    finally { setActingId(null) }
  }

  const loadPendingReviews = useCallback(async () => {
    setReviewsLoading(true)
    try {
      const r = await fetchPendingReviews()
      setPendingReviews(r.data || [])
    } catch { setPendingReviews([]) }
    finally { setReviewsLoading(false) }
  }, [])

  // 审核「同意 / 驳回」是写操作：按候选人记录提交中，防止连点
  const [decidingReview, setDecidingReview] = useState<string | null>(null)
  const handleDecideReview = async (candidateId: string, decision: string) => {
    setDecidingReview(candidateId + decision)
    try {
      await decideCandidateReview(candidateId, { decision })
      msg.success(decision === '已同意' ? '已同意' : '已驳回')
      loadPendingReviews()
    } catch (err: any) { msg.error(err.message || '操作失败') }
    finally { setDecidingReview(null) }
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
  // 远程搜索防抖（300ms）；首拉（onOpenChange）不经防抖直接执行
  const { run: debouncedSearchOwnerOptions } = useDebouncedCallback(searchOwnerOptions, 300)

  useEffect(() => {
    fetchPositions().then(d => {
      setPosOptions(d.map((p) => ({ value: `${p.department}|||${p.name}`, label: `${p.name} (${p.department})` })))
      setPosIdByKey(Object.fromEntries(d.map((p) => [`${p.department}|||${p.name}`, p.id])))
    }).catch(() => { })
  }, [])

  // 挂载即拉待审数：Tab 上的 Badge 需要初始值
  useEffect(() => { loadPendingReviews() }, [loadPendingReviews])

  // 岗位列表的加载/失败态：此前请求返回前和失败后都显示「暂无岗位需求，点击右上角新建」，
  // 网络一抖就被当成真的没有岗位
  const [jobsLoading, setJobsLoading] = useState(true)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const loadJobs = useCallback(async () => {
    setJobsLoading(true)
    setJobsError(null)
    try {
      const r = await fetchJobRequirements()
      setJobs(r.data || [])
    } catch (err: unknown) {
      const m = (err instanceof Error ? err.message : '') || '岗位需求加载失败'
      setJobsError(m)
      msg.error(m)
    } finally { setJobsLoading(false) }
  }, [msg])

  const loadAllCandidates = useCallback(async () => {
    try {
      // 页面按岗位分组展示需要全量数据：循环拉取所有分页（上限 5 页防御），
      // 不再因单页 100 条把后续候选人"藏"掉
      const pageSize = 100
      const all: any[] = []
      let total = 0
      for (let page = 1; page <= 5; page++) {
        const r = await fetchCandidates({ page, page_size: pageSize })
        all.push(...(r.data || []))
        total = r.meta?.total ?? all.length
        if (all.length >= total) break
      }
      setAllCandidates(all)
      if (all.length < total) {
        msg.warning(`候选人较多，仅显示前 ${all.length} 条（共 ${total} 条），请用筛选缩小范围`)
      }
    } catch (err: unknown) {
      setAllCandidates([])
      msg.error((err instanceof Error ? err.message : '') || '候选人列表加载失败')
    }
  }, [msg])

  // 岗位/候选人全量列表仅管理权限加载（审核人只待我审核 tab，后端也会按数据范围收敛）
  useEffect(() => { if (canManage) { loadJobs(); loadAllCandidates() } }, [canManage, loadJobs, loadAllCandidates])

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

  // ── 状态流转 ──
  // 流转到「已拒绝」不可逆（没有回退路径），此前在下拉里一点就生效、零确认零原因：
  // 改为先弹窗要求填写拒绝原因，确认后再流转。
  const [rejectTarget, setRejectTarget] = useState<Candidate | null>(null)
  const [rejectSaving, setRejectSaving] = useState(false)
  // 拒绝原因用普通 state 而不是 Form：弹窗关闭即销毁，Form 实例在未挂载时调 resetFields 会报
  // 「useForm is not connected」；改 forceRender 预渲染又会让这一段前后端输出不一致（hydration 报错）
  const [rejectReason, setRejectReason] = useState('')
  const [rejectReasonError, setRejectReasonError] = useState<string | undefined>()

  const doStatusChange = async (candidateId: string, newStatus: string, remark: string) => {
    setChangingStatus(candidateId)
    try {
      await transitionCandidateStatus(candidateId, { status: newStatus, remark })
      msg.success(`状态已变更为「${newStatus}」`)
      loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '变更失败') }
    finally { setChangingStatus(null) }
  }

  const handleStatusChange = (candidate: Candidate, newStatus: string) => {
    if (newStatus === '已拒绝') {
      // 上次放弃的原因不能带到下一个人身上
      setRejectReason('')
      setRejectReasonError(undefined)
      setRejectTarget(candidate)
      return
    }
    void doStatusChange(candidate.id, newStatus, '快捷流转')
  }

  const handleRejectSubmit = async () => {
    if (!rejectTarget) return
    const reason = rejectReason.trim()
    if (!reason) { setRejectReasonError('请填写拒绝原因'); return }
    setRejectSaving(true)
    try {
      await doStatusChange(rejectTarget.id, '已拒绝', reason)
      setRejectTarget(null)
    } finally { setRejectSaving(false) }
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

  // ── 岗位描述：从「招聘岗位信息」带出（岗位库里每个岗位保存一份，配置一次长期复用） ──

  /** 关掉岗位需求弹窗后清掉选中岗位相关状态，并作废还在路上的读取 */
  const resetSelectedPosition = () => {
    positionInfoSeq.current += 1
    setSelectedPosition(null)
    setFilledFromId(null)
  }

  /** 读取岗位库里该岗位的招聘信息。
   *  select：新建 / 换岗位。配置过的直接填进两个描述字段；没配置的，表单里若还是从别的岗位带出来的内容
   *          就清掉（用户手填的不动）
   *  edit：打开编辑弹窗。只了解这个岗位配没配置，不动需求上已有的描述
   *  apply：用户点了「套用」，以岗位库里的为准覆盖 */
  const loadPositionInfo = async (target: RecruitmentPositionTarget, mode: 'select' | 'edit' | 'apply') => {
    const seq = ++positionInfoSeq.current
    setSelectedPosition({ ...target, info: 'loading' })
    let duties = ''
    let requirements = ''
    try {
      const res = await fetchRecruitmentPositionInfo(target.id)
      if (seq !== positionInfoSeq.current) return
      duties = res.data.duties || ''
      requirements = res.data.requirements || ''
    } catch (err: unknown) {
      if (seq !== positionInfoSeq.current) return
      setSelectedPosition({ ...target, info: 'failed' })
      msg.error(err instanceof Error && err.message ? err.message : '读取岗位招聘信息失败')
      return
    }
    const hasInfo = !!(duties || requirements)
    if (mode === 'apply' || (mode === 'select' && hasInfo)) {
      reqForm.setFieldsValue({ duties, requirements })
      setFilledFromId(hasInfo ? target.id : null)
    } else if (mode === 'select' && filledFromRef.current) {
      reqForm.setFieldsValue({ duties: '', requirements: '' })
      setFilledFromId(null)
    }
    setSelectedPosition({ ...target, info: hasInfo ? 'configured' : 'missing' })
  }

  const handlePositionChange = (value: string) => {
    const [department = '', name = ''] = value.split('|||')
    reqForm.setFieldsValue({ department })
    const id = posIdByKey[value]
    if (id) {
      void loadPositionInfo({ id, department, name }, 'select')
      return
    }
    // 岗位库里对不上的（比如已删除的历史岗位）：没有可带出的内容
    positionInfoSeq.current += 1
    setSelectedPosition(null)
    if (filledFromRef.current) {
      reqForm.setFieldsValue({ duties: '', requirements: '' })
      setFilledFromId(null)
    }
  }

  /** 选中岗位还没配置招聘信息：就地配置，保存后直接带进表单 */
  const openInfoEditor = () => {
    if (!selectedPosition) return
    setInfoEditorTarget({
      id: selectedPosition.id, department: selectedPosition.department, name: selectedPosition.name,
    })
    setInfoEditorOpen(true)
  }

  const handleInfoSaved = (info: RecruitmentPositionInfo) => {
    reqForm.setFieldsValue({ duties: info.duties || '', requirements: info.requirements || '' })
    setFilledFromId(info.position_id)
    positionInfoSeq.current += 1
    setSelectedPosition((prev) => (prev && prev.id === info.position_id
      ? { ...prev, info: info.configured ? 'configured' : 'missing' }
      : prev))
  }

  // 新建/编辑岗位需求：提交期间 Modal 转圈，防止连点建出两条一样的岗位需求
  const [reqSaving, setReqSaving] = useState(false)
  const handleSaveReq = async () => {
    // 校验失败只走表单行内提示
    let v: ReqFormValues
    try {
      v = await reqForm.validateFields()
    } catch {
      return
    }
    const parts = (v.position_name || '').split('|||')
    const duties = (v.duties ?? '').trim()
    const requirements = (v.requirements ?? '').trim()
    const payload: JobRequirementCreateInput & JobRequirementUpdateInput = {
      position_name: parts[1] || parts[0],
      department: v.department || parts[0],
      headcount: v.headcount ?? 1,
      urgency: v.urgency || undefined,
      owner: v.owner || undefined,
      deadline: v.deadline ? dayjs(v.deadline).format('YYYY-MM-DD') : undefined,
      // 两个描述字段显式传，编辑时清空才能生效。新建时两项都空就不传，由后端按岗位库里配置的招聘信息带出
      ...(editingReq || duties || requirements ? { duties, requirements } : {}),
    }
    if (editingReq) {
      payload.status = v.status || undefined
    }
    setReqSaving(true)
    try {
      if (editingReq) {
        await updateJobRequirement(editingReq.id, payload)
      } else {
        await createJobRequirement(payload)
      }
      msg.success(editingReq ? '已更新' : '岗位需求已创建')
      setReqOpen(false); reqForm.resetFields(); setEditingReq(null); resetSelectedPosition(); loadJobs()
    } catch (err: any) { msg.error(err.message || '保存失败') }
    finally { setReqSaving(false) }
  }

  const handleDeleteReq = async (id: string) => {
    try {
      const r = await deleteJobRequirement(id)
      msg.success(r.message || '已删除')
      loadJobs(); loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '删除失败') }
  }

  /** 打开新建岗位需求弹窗：表单和选中岗位状态都从零开始 */
  const openCreateReq = () => {
    setEditingReq(null)
    reqForm.resetFields()
    resetSelectedPosition()
    setReqOpen(true)
  }

  /** 打开岗位需求的编辑弹窗（岗位卡「更多 → 编辑岗位需求」） */
  const openEditReq = (j: JobRequirement) => {
    setEditingReq(j)
    if (j.owner) setOwnerOptions([{ value: j.owner, label: j.owner }])
    reqForm.setFieldsValue({ ...j, position_name: `${j.department}|||${j.position_name}`, deadline: j.deadline ? dayjs(j.deadline) : undefined })
    resetSelectedPosition()
    setReqOpen(true)
    // 看看这个岗位在岗位库里有没有可套用的招聘信息（不动需求上已有的描述）
    const id = posIdByKey[`${j.department}|||${j.position_name}`]
    if (id) {
      void loadPositionInfo({ id, department: j.department, name: j.position_name }, 'edit')
    }
  }

  /** 删除岗位：确认框里写明会连带清理多少名候选人、已入职的保留 */
  const confirmDeleteReq = (j: JobRequirement, jobCandidates: Candidate[], hiredCount: number) => {
    modal.confirm({
      title: `删除岗位「${j.position_name}」？`,
      content: jobCandidates.length === 0
        ? '名下暂无候选人。'
        : `将一并清理名下 ${jobCandidates.length - hiredCount} 名候选人记录${hiredCount > 0 ? `，已入职 ${hiredCount} 名保留` : ''}。此操作不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => handleDeleteReq(j.id),
    })
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
    let unrecognized = 0
    for (const it of pending) {
      try {
        updateResumeItem(it.key, { stage: '解析中', error: undefined })
        const fd = new FormData(); fd.append('resume', it.file)
        const d = await parseResumeAction(fd)
        const p = d.data || {}
        // 名字只用简历正文提取的姓名；提取不到用明确的占位（批内递增），
        // 不回退简历文件名——岗位下不应出现一长串文件名当名字
        const name = p.name?.trim() || (unrecognized += 1, `未识别姓名${unrecognized > 1 ? unrecognized : ''}`)
        updateResumeItem(it.key, { stage: '建档中', parsed: p, name })
        const res = await createCandidate({
          name,
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
      if (unrecognized > 0) {
        msg.warning(`其中 ${unrecognized} 份未从简历正文中识别到姓名（显示为「未识别姓名」），可点开候选人详情修改`)
      }
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
      const r = await screenCandidateAction(it.candidateId!)
      if (r.ok) {
        updateResumeItem(it.key, {
          stage: '初筛完成', reco: r.data.recommendation, score: r.data.total_score,
        })
        ok += 1
      } else {
        // 初筛失败不影响已建档结果：回落「已建档」可重试
        updateResumeItem(it.key, { stage: '已建档', error: r.error })
      }
    }
    setBatchScreening(false)
    if (ok > 0) {
      await loadAllCandidates()
      setScreenRefreshToken((t) => t + 1)
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
  // 初筛结果会进入「AI 筛简历」面板；该面板随 Tab 常驻不会重建，初筛后靠自增信号让它重拉
  const [screenRefreshToken, setScreenRefreshToken] = useState(0)
  const runScreenCandidate = async (candidateId: string) => {
    setScreeningCand(candidateId)
    try {
      const r = await screenCandidateAction(candidateId)
      if (!r.ok) { msg.error(r.error); return }
      msg.success(`AI 初筛完成：${r.data.recommendation}（胜任度 ${r.data.total_score}/100），报告已写入候选人档案`)
      await loadAllCandidates()
      setScreenRefreshToken((t) => t + 1)
    } catch (err: any) { msg.error(err.message || 'AI 初筛失败') }
    finally { setScreeningCand(null) }
  }

  // 一键初筛：对岗位下存量未初筛简历（有简历+未定级+筛选阶段）批量跑 AI（串行，与单份同一 action）
  const [batchScreenJobId, setBatchScreenJobId] = useState<string | null>(null)
  const handleBatchScreenExisting = async (jobId: string, targets: Candidate[]) => {
    if (!targets.length) return
    setBatchScreenJobId(jobId)
    let ok = 0, fail = 0
    let lastError = ''
    for (let i = 0; i < targets.length; i++) {
      const r = await screenCandidateAction(targets[i].id)
      if (r.ok) ok += 1
      else { fail += 1; lastError = r.error }
      // 每份 10-20s：带 key 的进度提示覆盖更新，让用户知道在动
      msg.open({
        key: 'batch-screen', type: 'loading',
        content: `AI 初筛进度：${i + 1}/${targets.length}（成功 ${ok}${fail ? `，失败 ${fail}` : ''}）`,
      })
    }
    setBatchScreenJobId(null)
    await loadAllCandidates()
    setScreenRefreshToken((t) => t + 1)
    msg.destroy('batch-screen')
    if (fail === 0) msg.success(`AI 初筛完成：${ok} 份，推荐等级与匹配报告已写入候选人档案`)
    else msg.warning({
      content: `AI 初筛完成：成功 ${ok} 份、失败 ${fail} 份（稍后可重试）。最近失败原因：${lastError}`,
      duration: 8,
    })
  }

  const handleDeleteCandidate = async (id: string) => {
    try {
      await deleteCandidate(id)
      // 此前成功后没有任何反馈，列表刷新了但不知道是不是删对了
      msg.success('候选人已删除')
      loadAllCandidates()
    } catch (err: any) { msg.error(err.message || '删除失败') }
  }

  const [offerPreviewing, setOfferPreviewing] = useState(false)

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
    // 先同步开窗再取数：await 之后再 window.open 会脱离用户手势，被浏览器当弹窗广告拦截
    const w = window.open('', '_blank')
    if (!w) {
      msg.warning('浏览器拦截了预览窗口，请允许本站弹出窗口后重试')
      return
    }
    setOfferPreviewing(true)
    try {
      const html = await previewOffer(offerCandidate!.id, fd)
      w.document.write(html); w.document.close()
    } catch (err: any) {
      w.close()
      msg.error(err.message || '预览失败')
    } finally { setOfferPreviewing(false) }
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

  // 总览 Tab 激活或筛选条件变化时自动加载（loadOverview 随筛选闭包更新）
  useEffect(() => {
    if (activeTab === 'interviews') loadOverview()
  }, [activeTab, loadOverview])

  const handleTabChange = (key: string) => {
    setActiveTab(key as RecruitmentTab)
    if (key === 'reviews') loadPendingReviews()
    if (key === 'stats') loadStats()
    // 页签镜像到网址（replace，不新增历史）；默认页签不带参数，保持链接干净
    const next = new URLSearchParams(searchParams)
    if (key === 'jobs') next.delete('tab'); else next.set('tab', key)
    const qs = next.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  // 选中岗位的招聘信息提示条：已经带出 / 可套用最新内容 / 还没配置（可就地配置）
  let positionInfoHint: ReactNode = null
  if (selectedPosition) {
    const { name, info } = selectedPosition
    const hintClass = 'mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-[var(--rounded-md)] border border-[var(--color-hairline)] px-3 py-2 text-[13px]'
    if (info === 'loading') {
      positionInfoHint = (
        <div className="mb-4 flex items-center gap-2 text-[13px] text-[var(--color-steel)]">
          <Spin size="small" /> 正在读取「{name}」的招聘信息…
        </div>
      )
    } else if (info === 'failed') {
      positionInfoHint = (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-[var(--color-steel)]">
          <span>没读到「{name}」的招聘信息。</span>
          <Button type="link" size="small" className="px-0" onClick={() => { void loadPositionInfo(selectedPosition, editingReq ? 'edit' : 'select') }}>重试</Button>
        </div>
      )
    } else if (info === 'configured') {
      const applyButton = (
        <Popconfirm
          title={`套用「${name}」的招聘信息？`}
          description="会用岗位库里保存的内容覆盖下方的岗位要求和岗位职责。"
          okText="套用"
          cancelText="取消"
          onConfirm={() => { void loadPositionInfo(selectedPosition, 'apply') }}
        >
          <Button type="link" size="small" className="px-0">套用</Button>
        </Popconfirm>
      )
      positionInfoHint = filledFromId === selectedPosition.id ? (
        <div className={`${hintClass} bg-[var(--color-tint-mint)] text-[var(--color-charcoal)]`}>
          <span><CheckCircleOutlined className="mr-1.5 text-[var(--color-success)]" />已带出「{name}」的招聘信息，本次有不同要求可直接在下方修改</span>
        </div>
      ) : (
        <div className={`${hintClass} bg-[var(--color-surface-soft)]`}>
          <span className="text-[var(--color-charcoal)]"><CheckCircleOutlined className="mr-1.5 text-[var(--color-success)]" />「{name}」在「招聘岗位信息」里保存有岗位描述</span>
          {applyButton}
        </div>
      )
    } else {
      positionInfoHint = (
        <div className={`${hintClass} bg-[var(--color-surface-soft)]`}>
          <span className="min-w-0 flex-1 text-[var(--color-steel)]">
            <InfoCircleOutlined className="mr-1.5 text-[var(--color-stone)]" />
            「{name}」还没有配置招聘信息，这次需要手动填写
          </span>
          {canManage && (
            <span className="shrink-0">
              <Button type="link" size="small" className="px-0" onClick={openInfoEditor}>现在配置</Button>
            </span>
          )}
        </div>
      )
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="招聘管理"
        description={canManage
          ? `${jobs.length} 个岗位 · ${allCandidates.length} 个候选人`
          : `${pendingReviews.length} 位候选人待您审核`}
        actions={canManage && (
          <Button type="primary" onClick={openCreateReq}>新建岗位需求</Button>
        )}
      />

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          // 岗位招聘/AI 筛简历/数据分析是 HR 工具：用人部门负责人（审核人）仅见"待我审核"
          ...(canManage ? [{
            key: 'jobs',
            label: '岗位招聘',
            children: (<>
              {showCompare ? (
                /* 横向对比弹窗 */
                <Card size="small" title="候选人横向对比（按AI综合评分排序）"
                  extra={<Button onClick={() => setShowCompare(false)}>关闭对比</Button>}
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
                          return (<tr key={c.id} className="hover:bg-blue-50 cursor-pointer border-t" onClick={() => openCandidateDetail(c.id, compareData.map((i: any) => i.candidate?.id))}>
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
                  {jobsLoading && jobs.length === 0 ? (
                    <div className="py-12 text-center"><Spin /></div>
                  ) : jobsError && jobs.length === 0 ? (
                    <div className="py-12 text-center space-y-3">
                      <div className="text-[var(--color-steel)]">岗位列表加载失败：{jobsError}</div>
                      <Button onClick={() => void loadJobs()}>重试</Button>
                    </div>
                  ) : jobs.length === 0 ? (
                    <Empty description="暂无岗位需求，点击右上角新建" className="py-8" />
                  ) : null}
                      {jobs.map(j => {
                        const jobCandidates = allCandidates.filter(c => c.job_requirement_id === j.id)
                        const isExpanded = expandedJobs.has(j.id)
                        const hiredCount = jobCandidates.filter(c => c.status === '已入职').length
                        const sortedCandidates = [...jobCandidates].sort((a, b) => {
                          const ia = STATUS_ORDER.indexOf(a.status || ''); const ib = STATUS_ORDER.indexOf(b.status || '')
                          return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
                        })
                        // 漏斗筛选后的可见列表：dataSource 与详情跳转上下文共用同一口径
                        const visibleJobCandidates = jobStatusFilter[j.id]
                          ? sortedCandidates.filter(c => (c.status || '待筛选') === jobStatusFilter[j.id])
                          : sortedCandidates
                    return (
                      <Card key={j.id}
                        styles={{
                          header: { padding: '12px 16px' },
                          body: isExpanded ? { padding: '12px 16px' } : { padding: 0 },
                        }}
                        title={
                          /* 岗位为主实体：两行头部（岗位名+状态 / 部门·进度·负责人·到岗），视觉重量压过候选人行 */
                          <div className="flex items-center gap-3 cursor-pointer select-none min-w-0" onClick={() => toggleJob(j.id)}>
                            <span className="text-[var(--color-stone)] flex-shrink-0 w-4 flex justify-center">
                              {isExpanded ? <DownOutlined style={{ fontSize: 12 }} /> : <RightOutlined style={{ fontSize: 12 }} />}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-[15px] font-semibold text-[var(--color-charcoal)]">{j.position_name}</span>
                                <Tag color={j.status === '招聘中' ? 'green' : 'default'} style={{ fontSize: 11, margin: 0 }}>{j.status}</Tag>
                                {j.urgency === '紧急' && <Tag color="red" style={{ fontSize: 11, margin: 0 }}>紧急</Tag>}
                              </div>
                              <div className="text-xs text-[var(--color-stone)] mt-1 flex items-center gap-1.5 flex-wrap">
                                <span className="flex-shrink-0">{j.department}</span>
                                <span className="text-[var(--color-hairline-strong)]">·</span>
                                <span className="flex-shrink-0">在招 <b className="text-[var(--color-charcoal)]">{jobCandidates.length}</b>/{j.headcount} 人</span>
                                {j.owner && <><span className="text-[var(--color-hairline-strong)]">·</span><span className="flex-shrink-0">负责人 {j.owner}</span></>}
                                {j.deadline && <><span className="text-[var(--color-hairline-strong)]">·</span><span className="flex-shrink-0">期望到岗 {j.deadline}</span></>}
                              </div>
                              {/* 折叠时第三行单行截断展示候选人名，独立成行避免在 flex-wrap 里被撑开换行 */}
                              {!isExpanded && jobCandidates.length > 0 && (
                                <div className="text-xs text-[var(--color-muted)] mt-1 truncate">
                                  {sortedCandidates.slice(0, 4).map(c => c.name).join('、')}{jobCandidates.length > 4 ? '…' : ''}
                                </div>
                              )}
                            </div>
                          </div>
                        }
                        extra={
                          <div className="flex gap-2 items-center" onClick={e => e.stopPropagation()}>
                            {(() => {
                              // 该岗位存量可初筛的：有简历 + 未定推荐等级 + 仍在筛选阶段
                              const screenables = jobCandidates.filter(c =>
                                c.resume_url && c.job_requirement_id && !c.recommendation_level &&
                                SCREENING_PHASE_STATUSES.has(c.status || '待筛选'))
                              return screenables.length > 0 ? (
                                <Button type="primary" ghost
                                  loading={batchScreenJobId === j.id}
                                  disabled={batchScreenJobId !== null || screeningCand !== null}
                                  title="对该岗位所有未初筛的存量简历一键批量 AI 初筛（串行执行，每份约 10-20 秒）"
                                  onClick={() => handleBatchScreenExisting(j.id, screenables)}>
                                  AI 初筛 {screenables.length} 份
                                </Button>
                              ) : null
                            })()}
                            <Button title="批量上传简历（自动解析建档，可一键 AI 初筛）" onClick={() => { setResumeItems([]); setResumeJobId(j.id); setResumeOpen(true) }}>上传简历</Button>
                            {/* 低频操作收进「更多」：此前岗位卡头部并排 5 个默认尺寸按钮，一屏全是按钮 */}
                            <Dropdown
                              trigger={['click']}
                              menu={{
                                items: [
                                  { key: 'compare', icon: <SwapOutlined />, label: '候选人对比', disabled: jobCandidates.length === 0 },
                                  { key: 'edit', icon: <EditOutlined />, label: '编辑岗位需求' },
                                  { type: 'divider' },
                                  {
                                    key: 'delete', icon: <DeleteOutlined />, danger: true,
                                    label: j.status === '招聘中' ? '删除岗位（招聘中不可删除）' : '删除岗位',
                                    disabled: j.status === '招聘中',
                                  },
                                ],
                                onClick: ({ key }) => {
                                  if (key === 'compare') loadCompare(j.id)
                                  else if (key === 'edit') openEditReq(j)
                                  else if (key === 'delete') confirmDeleteReq(j, jobCandidates, hiredCount)
                                },
                              }}
                            >
                              <Button aria-label="更多操作">更多 <DownOutlined /></Button>
                            </Dropdown>
                          </div>
                        }
                      >
                        {!isExpanded ? null : jobCandidates.length === 0 ? (
                          <div className="text-center text-[var(--color-stone)] text-xs py-5 border border-dashed border-[var(--color-hairline)] rounded-lg">暂无候选人 — 上传简历添加候选人</div>
                        ) : (
                          <>
                            {/* 漏斗统计 chips：点击筛选下方表格，再点取消 */}
                            <div className="flex items-center gap-1.5 flex-wrap mb-2">
                              {STATUS_ORDER.filter(s => jobCandidates.some(c => (c.status || '待筛选') === s)).map(s => {
                                const cnt = jobCandidates.filter(c => (c.status || '待筛选') === s).length
                                const active = jobStatusFilter[j.id] === s
                                const color = STATUS_COLORS[s] || '#d9d9d9'
                                return (
                                  <button key={s} type="button"
                                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs border transition-colors cursor-pointer"
                                    style={{
                                      color: active ? '#fff' : color,
                                      borderColor: color,
                                      background: active ? color : `${color}14`,
                                    }}
                                    onClick={() => setJobStatusFilter(prev => ({ ...prev, [j.id]: active ? null : s }))}
                                  >
                                    <span>{s}</span><b>{cnt}</b>
                                  </button>
                                )
                              })}
                              {jobStatusFilter[j.id] && (
                                <a className="text-xs text-[var(--color-steel)] ml-1" onClick={() => setJobStatusFilter(prev => ({ ...prev, [j.id]: null }))}>清除筛选</a>
                              )}
                            </div>
                            <Table size="small" rowKey="id"
                              dataSource={visibleJobCandidates}
                              pagination={jobCandidates.length > 10 ? {
                                pageSize: 10, showSizeChanger: false, size: 'small',
                                showTotal: t => `共 ${t} 条`,
                              } : false}
                              onRow={(record) => {
                                const days = record.updated_at ? Math.floor((Date.now() - new Date(record.updated_at).getTime()) / (1000 * 60 * 60 * 24)) : 0
                                const isStale = days > 7 && record.status !== '已入职' && record.status !== '已拒绝'
                                return {
                                  className: 'cursor-pointer',
                                  style: isStale ? { background: '#fff5f5' } : undefined,
                                  onClick: () => openCandidateDetail(record.id, visibleJobCandidates.map(c => c.id)),
                                }
                              }}
                              columns={[
                                {
                                  title: '候选人', key: 'name',
                                  render: (_: any, c: Candidate) => {
                                    const days = c.updated_at ? Math.floor((Date.now() - new Date(c.updated_at).getTime()) / (1000 * 60 * 60 * 24)) : 0
                                    const isStale = days > 7 && c.status !== '已入职' && c.status !== '已拒绝'
                                    return (
                                      <div className="flex items-center gap-1.5 min-w-0">
                                        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: STATUS_COLORS[c.status || '待筛选'] || '#d9d9d9' }} />
                                        <span className="font-medium truncate max-w-[200px]" title={c.name}>{c.name}</span>
                                        {c.gender && <span className="text-xs text-gray-400 flex-shrink-0">{c.gender}</span>}
                                        {c.recommendation_level && (
                                          <Tag color={RECOMMENDATION_LEVEL_TAG_COLORS[c.recommendation_level] || 'default'}
                                            style={{ fontSize: 11, margin: 0 }} className="flex-shrink-0">{c.recommendation_level}</Tag>
                                        )}
                                        {isStale && (
                                          <Tooltip title={`该候选人已 ${days} 天没有更新（超过 7 天标红提醒）`}>
                                            <span className="text-xs text-[var(--color-error)] whitespace-nowrap flex-shrink-0 inline-flex items-center gap-0.5">
                                              <WarningOutlined />{days}天
                                            </span>
                                          </Tooltip>
                                        )}
                                      </div>
                                    )
                                  },
                                },
                                {
                                  title: '学历 / 院校', key: 'edu', width: 210,
                                  render: (_: any, c: Candidate) => (
                                    <span className="text-xs text-gray-500">{c.education || '-'} · {c.school || '-'}</span>
                                  ),
                                },
                                {
                                  title: '联系方式', key: 'contact',
                                  render: (_: any, c: Candidate) => (
                                    <span className="text-xs text-gray-500">{c.phone || '-'} · {c.email || '-'}</span>
                                  ),
                                },
                                {
                                  title: '状态', key: 'status', width: 130,
                                  render: (_: any, c: Candidate) => (
                                    <div onClick={e => e.stopPropagation()}>
                                      <Select size="small" value={c.status} loading={changingStatus === c.id}
                                        style={{ width: 110 }}
                                        options={STATUS_OPTIONS.filter(o => o.value === c.status || CANDIDATE_TRANSITIONS[c.status || '']?.includes(o.value))}
                                        onChange={v => handleStatusChange(c, v)}
                                      />
                                    </div>
                                  ),
                                },
                                {
                                  // 行内操作按状态显隐并收窄：此前每行固定挂着「AI 初筛 / 发 Offer / 红框删除」
                                  // 三个默认尺寸按钮（已拒绝的候选人也有「发 Offer」，点下去后端直接 400）
                                  title: '操作', key: 'actions', width: 150,
                                  render: (_: any, c: Candidate) => (
                                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                                      {c.resume_url && c.job_requirement_id && !c.recommendation_level && SCREENING_PHASE_STATUSES.has(c.status || '待筛选') && (
                                        <Button size="small"
                                          loading={screeningCand === c.id}
                                          title="AI 简历初筛（面试前：按已存简历+岗位JD打分，写入推荐等级与匹配报告）"
                                          onClick={() => runScreenCandidate(c.id)}>AI 初筛</Button>
                                      )}
                                      {OFFER_STATUSES.has(c.status || '') && (
                                        <Button size="small" onClick={() => handleSendOffer(c)}>发 Offer</Button>
                                      )}
                                      {/* 已入职的候选人后端不允许删除（需保留档案溯源），不显示删除 */}
                                      {c.status !== '已入职' && (
                                        <Popconfirm title="确定删除此候选人？" description="删除后不可恢复。" onConfirm={() => handleDeleteCandidate(c.id)}
                                          okText="删除" okButtonProps={{ danger: true }} cancelText="取消">
                                          <Button size="small" type="link" danger>删除</Button>
                                        </Popconfirm>
                                      )}
                                    </div>
                                  ),
                                },
                              ]}
                            />
                          </>
                        )}
                      </Card>
                    )
                  })}
                </div>
              )}

                              <Modal title={editingReq ? '编辑岗位需求' : '新建岗位需求'} open={reqOpen} onCancel={() => setReqOpen(false)} onOk={handleSaveReq}
                                okText="保存" confirmLoading={reqSaving} mask={{ closable: false }}>
                <Form form={reqForm} layout="vertical"
                  onValuesChange={(changed) => {
                    // 用户动了描述字段：之后换岗位就不再自动清掉或覆盖它
                    if (filledFromRef.current && ('duties' in changed || 'requirements' in changed)) setFilledFromId(null)
                  }}>
                  <Form.Item name="position_name" label="岗位名称" rules={[{ required: true }]}>
                    <Select showSearch placeholder="选择岗位（含部门）" options={posOptions}
                      filterOption={(inp, opt) => (opt?.label ?? '').toLowerCase().includes(inp.toLowerCase())}
                      onChange={handlePositionChange} />
                  </Form.Item>
                  <Form.Item name="department" hidden><Input /></Form.Item>
                  <Form.Item name="headcount" label="招聘人数" className="mb-3"><InputNumber min={1} /></Form.Item>
                  {positionInfoHint}
                  <Form.Item name="requirements" label="岗位要求"><Input.TextArea rows={5} /></Form.Item>
                  <Form.Item name="duties" label="岗位职责"><Input.TextArea rows={5} placeholder="可选，胜任度分析报告「岗位要求回顾」使用" /></Form.Item>
                  <Form.Item name="owner" label="用人部门负责人" tooltip="推送审核时默认发给此人">
                    <Select
                      showSearch
                      filterOption={false}
                      allowClear
                      loading={ownerSearching}
                      placeholder="输入姓名搜索；或直接从下方列表选择"
                      options={ownerOptions}
                      onSearch={debouncedSearchOwnerOptions}
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

              {/* 选中岗位还没配置招聘信息时，在需求弹窗上就地配置；保存后直接带进上面的表单 */}
              <RecruitmentPositionInfoModal
                open={infoEditorOpen}
                position={infoEditorTarget}
                onClose={() => setInfoEditorOpen(false)}
                onSaved={handleInfoSaved}
              />

              <Modal title={`拒绝候选人${rejectTarget?.name ? `「${rejectTarget.name}」` : ''}`} open={!!rejectTarget}
                onCancel={() => setRejectTarget(null)} onOk={handleRejectSubmit}
                okText="确认拒绝" okButtonProps={{ danger: true }} cancelText="再想想"
                confirmLoading={rejectSaving} destroyOnHidden mask={{ closable: false }}>
                <Alert type="warning" showIcon className="mb-3"
                  title="拒绝后不可回退"
                  description="候选人将移出招聘流程，无法再流转到其它状态；如需重新考虑，要重新上传简历建档。" />
                {/* 输入框带 maxLength，长度上限由组件兜底；这里只校验必填 */}
                <div className="mb-2 text-[14px] text-[var(--color-charcoal)]">
                  <span className="mr-0.5 text-[var(--color-error)]">*</span>拒绝原因
                </div>
                <Input.TextArea rows={3} maxLength={200} showCount
                  value={rejectReason} status={rejectReasonError ? 'error' : undefined}
                  onChange={e => { setRejectReason(e.target.value); if (rejectReasonError) setRejectReasonError(undefined) }}
                  placeholder="例如：薪资期望超出岗位预算 / 技能与岗位要求不匹配 / 已另有安排" />
                {rejectReasonError && <div role="alert" className="mt-1 text-xs text-[var(--color-error)]">{rejectReasonError}</div>}
              </Modal>

              <Modal title={`发放入职 Offer — ${offerCandidate?.name || ''}`} open={offerOpen}
                onCancel={() => setOfferOpen(false)} width={640}
                footer={[
                  <Button key="preview" loading={offerPreviewing} onClick={handlePreviewOffer}>预览</Button>,
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
                      <Button key="screen" type="primary" ghost
                        disabled={screenable === 0 || batchRunning}
                        loading={batchScreening}
                        onClick={() => { void handleBatchScreen() }}>
                        AI 初筛 {screenable > 0 ? `${screenable} 份` : ''}
                      </Button>
                    )
                  })(),
                  <Button key="process" type="primary"
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
                    <Button size="large" disabled={batchRunning || batchScreening}>选择 PDF 文件（可多选）</Button>
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
          }, {
            key: 'interviews',
            label: <span className="flex items-center gap-1.5"><ClockCircleOutlined />面试总览</span>,
            children: (<>
              <Card>
                <div className="flex flex-wrap gap-3 mb-4 items-center">
                  <DatePicker.RangePicker
                    value={overviewDateRange}
                    onChange={(v) => setOverviewDateRange(v)}
                  />
                  {/* 非受控：受控值在防抖窗口内会被列表刷新打回旧值（吃字） */}
                  <Input.Search
                    placeholder="候选人姓名"
                    style={{ width: 180 }}
                    allowClear
                    onChange={(e) => debouncedSetOverviewCandidate(e.target.value)}
                    onSearch={(v) => { cancelOverviewDebounce(); setOverviewCandidate(v || '') }}
                  />
                  <Select
                    placeholder="状态" allowClear style={{ width: 120 }}
                    options={['待安排', '已安排', '已完成', '已取消'].map((x) => ({ label: x, value: x }))}
                    onChange={(v) => setOverviewStatus(v)}
                  />
                  <span className="text-xs text-gray-400 ml-auto">
                    {overviewLoading ? '加载中…' : `共 ${overviewTotal} 场`}
                  </span>
                </div>
                {overviewLoading ? <div className="text-center py-12"><Spin /></div> :
                  overviewRows.length === 0 ? <Empty description="该条件下暂无面试安排" className="py-12" /> : (
                    <div className="space-y-5">
                      {(() => {
                        const today = dayjs().format('YYYY-MM-DD')
                        const groups: { title: string; rows: typeof overviewRows }[] = [
                          { title: '时间待定', rows: [] },
                          { title: '今天面试', rows: [] },
                          { title: '即将到来', rows: [] },
                          { title: '更早 / 已结束', rows: [] },
                        ]
                        overviewRows.forEach((iv) => {
                          if (!iv.interview_date) { groups[0].rows.push(iv); return }
                          if (iv.interview_date === today) groups[1].rows.push(iv)
                          else if (iv.interview_date > today) groups[2].rows.push(iv)
                          else groups[3].rows.push(iv)
                        })
                        return groups.filter((g) => g.rows.length > 0).map((g) => (
                          <div key={g.title}>
                            <div className="text-sm font-medium mb-2 text-[var(--color-charcoal)]">
                              {g.title} <span className="text-gray-400 font-normal">({g.rows.length})</span>
                            </div>
                            <div className="space-y-2">
                              {g.rows.map((iv) => (
                                <div key={iv.id}
                                  className="flex items-center gap-3 p-2.5 rounded-lg border border-[var(--color-hairline)] hover:bg-blue-50 cursor-pointer transition-colors"
                                  onClick={() => openCandidateDetail(iv.candidate_id, overviewRows.map(r => r.candidate_id), 'interviews')}>
                                  <Tag color={iv.status === '已完成' ? 'green' : iv.status === '已取消' ? 'red' : 'blue'}>{iv.status}</Tag>
                                  <span className="text-xs text-gray-500 w-40 shrink-0">
                                    {iv.interview_date || '时间待定'}{iv.start_time ? ` ${iv.start_time.slice(0, 5)}${iv.end_time ? `-${iv.end_time.slice(0, 5)}` : ''}` : ''}
                                  </span>
                                  <span className="font-medium text-sm">{iv.candidate_name || '未知候选人'}</span>
                                  <span className="text-xs text-gray-400">{iv.candidate_position || ''}</span>
                                  <Tag style={{ fontSize: 10 }}>{iv.interview_type}</Tag>
                                  <span className="text-xs text-gray-500 flex-1 truncate">
                                    面试官：{iv.interviewer || '-'}{iv.location ? ` · ${iv.location}` : ''}
                                  </span>
                                  {/* 面试官人工评价结论 + AI 胜任度综合分：总览直接看结果，免进详情 */}
                                  {iv.feedback_result && (
                                    <Tag color={iv.feedback_result === '通过' ? 'green' : iv.feedback_result === '不通过' ? 'red' : 'orange'} style={{ fontSize: 10 }} className="shrink-0">
                                      评价：{iv.feedback_result}{iv.feedback_score != null ? ` ${iv.feedback_score}分` : ''}
                                    </Tag>
                                  )}
                                  {iv.ai_total_score != null && (
                                    <Tag color={iv.ai_recommend_level === '不推荐' ? 'red' : (iv.ai_recommend_level === '强烈推荐' || iv.ai_recommend_level === '推荐') ? 'geekblue' : 'default'} style={{ fontSize: 10 }} className="shrink-0">
                                      AI {Math.round(iv.ai_total_score)}分{iv.ai_recommend_level ? ` · ${iv.ai_recommend_level}` : ''}
                                    </Tag>
                                  )}
                                  {iv.calendar_event_id && <Tag color="purple" style={{ fontSize: 10 }}>日历</Tag>}
                                  <div className="flex gap-1 flex-shrink-0" onClick={e => e.stopPropagation()}>
                                    {(iv.status === '待安排' || iv.status === '已安排') && (
                                      <>
                                        <Popconfirm title="标记为已完成？" description="完成后不可回退"
                                          onConfirm={() => handleOverviewComplete(iv.id)} okText="确认完成" cancelText="取消">
                                          <Button size="small" type="primary" ghost loading={actingId === iv.id}>完成</Button>
                                        </Popconfirm>
                                        {/* 已有逐字稿/备注 = 面试已实际进行，不允许再取消 */}
                                        {!(iv.transcript_text || iv.notes) && (
                                          <Popconfirm title="取消这场面试？" description="将同时删除关联的飞书日程"
                                            onConfirm={() => handleOverviewCancel(iv.id)} okText="取消面试" cancelText="保留">
                                            <Button size="small" danger>取消</Button>
                                          </Popconfirm>
                                        )}
                                      </>
                                    )}
                                    <Button size="small" onClick={() => setOverviewEdit(iv)}>编辑</Button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))
                      })()}
                    </div>
                  )}
              </Card>
              {/* 总览行内「编辑」弹窗：复用面试安排共享组件（编辑模式不需要候选人上下文） */}
              <InterviewScheduleModal
                open={!!overviewEdit}
                editing={overviewEdit}
                onCancel={() => setOverviewEdit(null)}
                onSaved={() => { setOverviewEdit(null); loadOverview() }}
              />
            </>
            ),
          }] : []),
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
                          onClick={() => openCandidateDetail(c.id, pendingReviews.map((i: any) => i.candidate?.id))}
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
                              {rv.push_note && <div className="text-xs text-blue-600 mt-1 inline-flex items-center gap-1"><CommentOutlined />HR备注：{rv.push_note}</div>}
                            </div>
                            <div className="flex gap-2 flex-shrink-0 pt-0.5" onClick={(e) => e.stopPropagation()}>
                              <Button type="primary" loading={decidingReview === `${c.id}已同意`} onClick={() => handleDecideReview(c.id, '已同意')}>同意</Button>
                              <Button danger loading={decidingReview === `${c.id}已拒绝`} onClick={() => handleDecideReview(c.id, '已拒绝')}>驳回</Button>
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
          ...(canManage ? [{
            key: 'screening',
            label: <span className="flex items-center gap-1.5"><FileSearchOutlined />AI 初筛</span>,
            children: (
              <ResumeScreeningPanel
                refreshToken={screenRefreshToken}
                onDataChanged={() => { void loadAllCandidates() }}
              />
            ),
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
                          return (
                            <div key={item.status} className="flex items-center gap-2">
                              <span className="text-xs w-20 text-right text-gray-500">{item.status}</span>
                              <div className="flex-1 bg-gray-100 rounded h-5 overflow-hidden">
                                <div className="h-full rounded transition-all" style={{
                                  width: `${pct}%`,
                                  backgroundColor: STATUS_COLORS[item.status] || '#d9d9d9',
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
          }] : []),
        ]}
      />
    </div>
  )
}
