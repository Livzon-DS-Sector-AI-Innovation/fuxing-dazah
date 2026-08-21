'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  TimePicker,
  Upload,
  message,
} from 'antd'
import {
  DownloadOutlined,
  BellOutlined,
  FileExcelOutlined,
  BookOutlined,
  UploadOutlined,
  RobotOutlined,
  FormOutlined,
  DatabaseOutlined,
  SearchOutlined,
  PlusOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchDepartmentsAction,
  fetchEmployeesAction,
  fetchEmployeeVarieties,
  fetchTrainingLedgerPages,
  generateTrainingNotification,
  generateTrainingSignInSheet,
  createTrainingLedger,
  createTrainingLedgerPage,
  exportQaRecord,
  saveExamPaper,
  fetchTrainers,
  upsertTrainingEvaluation,
  generateAssessmentQuestions,
  fetchQuestionBank,
  exportScoreReport,
  exportQaRecordWithScores,
  exportTrainingAssessmentScores,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { moduleMenus, type SubMenuItem } from '@/lib/menu-config'
import EvaluationPreview from './EvaluationPreview'
import AssessmentFlow from './AssessmentFlow'

const TRAINING_METHODS = [
  { value: '面授', label: '面授' },
  { value: '自学', label: '自学' },
  { value: '面授+自学', label: '面授+自学' },
  { value: '自学+面授', label: '自学+面授' },
]

const ASSESSMENT_METHODS = [
  { value: '笔试', label: '笔试' },
  { value: '问答', label: '问答' },
]

const TD_LABEL = {
  border: '1px solid #1f2937',
  padding: '8px',
} as React.CSSProperties

/** Check whether an employee already has a dedicated training-ledger menu page (static + DB). */
async function getExistingLedgerNumbers(): Promise<Set<string>> {
  const numbers = new Set<string>()
  const hr = moduleMenus.find((m) => m.key === 'hr')
  const training = hr?.children?.find((c) => c.key === 'training')
  const trainingLedger = training?.children?.find((c) => c.key === 'training-ledger')

  function collectChildren(items: SubMenuItem[] | undefined) {
    items?.forEach((c) => {
      const match = c.path?.match(/employee_number=(\d+)/)
      if (match) numbers.add(match[1])
      if (c.children) collectChildren(c.children)
    })
  }
  if (trainingLedger?.path) {
    const match = trainingLedger.path.match(/employee_number=(\d+)/)
    if (match) numbers.add(match[1])
  }
  collectChildren(trainingLedger?.children)

  try {
    const res = await fetchTrainingLedgerPages()
    ;(res.data || []).forEach((p) => numbers.add(p.employee_number))
  } catch {
    // ignore
  }
  return numbers
}

export default function TrainingNotificationClient() {
  const [form] = Form.useForm()
  const watchedNames = Form.useWatch('employee_names', form) as string[] | undefined
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [employees, setEmployees] = useState<{ value: string; label: string }[]>([])
  const [allDeptEmployees, setAllDeptEmployees] = useState<any[]>([]) // 完整员工列表（含品种），用于品种筛选
  const [varieties, setVarieties] = useState<string[]>([])
  const [nameToNumberMap, setNameToNumberMap] = useState<Record<string, string>>({})
  const [nameToDeptMap, setNameToDeptMap] = useState<Record<string, string>>({})
  const [submittingWord, setSubmittingWord] = useState(false)
  const [submittingExcel, setSubmittingExcel] = useState(false)
  const [addingToLedger, setAddingToLedger] = useState(false)
  const [trainerDept, setTrainerDept] = useState<string | undefined>(undefined)
  const [trainerEmployees, setTrainerEmployees] = useState<{ value: string; label: string }[]>([])
  const [assessmentModalOpen, setAssessmentModalOpen] = useState(false)
  const [scoreModalOpen, setScoreModalOpen] = useState(false)
  const [scoreMap, setScoreMap] = useState<Record<string, number>>({})
  const [exportingScore, setExportingScore] = useState(false)
  const [generatingAssessment, setGeneratingAssessment] = useState(false)
  const [assessmentFile, setAssessmentFile] = useState<File | null>(null)
  const [assessmentQuestions, setAssessmentQuestions] = useState<any>(null)
  const [trainingMethod, setTrainingMethod] = useState<string | undefined>(undefined)
  const [assessmentMethod, setAssessmentMethod] = useState<string | undefined>(undefined)
  // 学员错题评分：{ traineeName: { wrongIndices: number[], score: number } }
  const [traineeScoreMap, setTraineeScoreMap] = useState<Record<string, { wrongIndices: number[]; score: number }>>({})
  // 题库选题
  const [bankQuestions, setBankQuestions] = useState<any[]>([])
  const [loadingBank, setLoadingBank] = useState(false)
  const [selectedBankIds, setSelectedBankIds] = useState<Set<string>>(new Set())
  const [bankSearch, setBankSearch] = useState('')
  const [bankPage, setBankPage] = useState(1)
  const [traineePage, setTraineePage] = useState(1)
  const BANK_PAGE_SIZE = 50
  const TRAINEE_PAGE_SIZE = 15

  const searchParams = useSearchParams()
  const router = useRouter()

  useEffect(() => {
    fetchDepartmentsAction({ page_size: 100 }).then((res) => {
      const list = (res.data || []).map((d: any) => ({ value: d.name, label: d.name }))
      setDepartments(list)
    })
  }, [])

  // 从年度计划跳转过来时，自动填入
  useEffect(() => {
    const subject = searchParams.get('subject')
    const dept = searchParams.get('dept')
    if (!subject) return

    const get = (k: string) => {
      const v = searchParams.get(k)
      return v ? decodeURIComponent(v) : undefined
    }

    const confirmDate = get('confirm_date')
    const method = get('method')
    const dateFields: Record<string, any> = {}
    if (confirmDate) {
      const d = dayjs(confirmDate)
      dateFields.time_slots = [{ date: d, time: [dayjs('08:00', 'HH:mm'), dayjs('12:00', 'HH:mm')] }]
      dateFields.issue_date = d
    }

    form.setFieldsValue({
      subject: get('subject'),
      training_method: method,
      assessment_method: get('assessment'),
      location: get('location'),
      trainer: get('trainer'),
      department: get('dept'),
      trainee_departments: get('dept') ? [get('dept')] : undefined,
      ...dateFields,
    })

    if (dept) {
      const deptName = decodeURIComponent(dept)
      setTrainerDept(deptName)
      fetchEmployeesAction({ department: deptName, page_size: 200 }).then(res => {
        const emps = (res.data || []).map((e: any) => ({
          value: e.name, label: `${e.name} - ${e.department || deptName} (${e.employee_number})`,
          employee_number: e.employee_number,
        }))
        setEmployees(emps)
        setTrainerEmployees(emps)
        const deptMap2: Record<string, string> = {}
        emps.forEach((e: any) => { if (e.value) deptMap2[e.value] = deptName })
        setNameToDeptMap(deptMap2)
        const map: Record<string, string> = {}
        emps.forEach((e: any) => { map[e.value] = e.employee_number })
        setNameToNumberMap(map)
        // 自动全选为出席受训人员
        form.setFieldsValue({ employee_names: emps.map((e: any) => e.value) })
      })
    }
  }, [searchParams])

  // 培训师：从内训师台账加载
  const loadTrainerEmployees = async (dept: string) => {
    setTrainerDept(dept)
    form.setFieldsValue({ trainer: undefined })
    if (!dept) { setTrainerEmployees([]); return }
    try {
      const d = await fetchTrainers({ department: dept, page_size: 200 })
      setTrainerEmployees((d.data || []).map((t: any) => ({
        value: t.name,
        label: `${t.name} (${t.department})`,
      })))
    } catch { setTrainerEmployees([]) }
  }

  const loadEmployees = async (depts: string[]) => {
    if (!depts || depts.length === 0) {
      setEmployees([])
      setAllDeptEmployees([])
      setVarieties([])
      setNameToNumberMap({})
      setNameToDeptMap({})
      form.setFieldsValue({ employee_names: [], variety_filter: [] })
      return
    }
    const allFull: any[] = []
    const numberMap: Record<string, string> = {}
    const deptMap: Record<string, string> = {}
    for (const dept of depts) {
      try {
        const res = await fetchEmployeesAction({ department: dept, page_size: 200 })
        // 病假/产假员工自动过滤，不进入出席名单
        const activeList = (res.data || []).filter((e: any) => e.status !== '病假' && e.status !== '产假')
        allFull.push(...activeList)
        for (const e of activeList) {
          if (e.name && e.employee_number) numberMap[e.name] = e.employee_number
          if (e.name && e.department) deptMap[e.name] = e.department
        }
      } catch { /* ignore */ }
    }
    // 按「姓名+工号」去重：兼任部门重叠时同一人只保留一条，同名不同工号视为两人
    const dedupeKey = (e: any) => `${e.name}::${e.employee_number || ''}`
    const uniqueFull = Array.from(new Map(allFull.map((e) => [dedupeKey(e), e])).values())
    const uniqueList = uniqueFull.map((e) => ({
      value: e.name,
      label: `${e.name} - ${e.department || ''} (${e.employee_number || ''})`,
    }))
    setEmployees(uniqueList)
    setAllDeptEmployees(uniqueFull)
    setNameToNumberMap(numberMap)
    setNameToDeptMap(deptMap)
    const names = uniqueList.map((e) => e.value)
    form.setFieldsValue({ employee_names: names, variety_filter: [] })
    // 加载品种列表：汇总全部受训部门（含兼任部门）的品种
    const varietySet = new Set<string>()
    for (const dept of depts) {
      try {
        const vRes = await fetchEmployeeVarieties(dept)
        ;(vRes.data || []).forEach((v: string) => varietySet.add(v))
      } catch { /* ignore */ }
    }
    setVarieties(Array.from(varietySet))
  }

  const handleExportWord = async () => {
    const values = await form.validateFields()
    const traineeDepts: string[] = values.trainee_departments || []
    const timeSlots: Array<{ date: any; time: any }> = values.time_slots || []

    const firstSlot = timeSlots[0]
    const firstDate = firstSlot?.date

    setSubmittingWord(true)
    try {
      // 构建 time_slots 数组发送到后端
      const timeSlotsPayload = timeSlots
        .filter((s: any) => s?.date)
        .map((s: any) => ({
          date: s.date.format('YYYY-MM-DD'),
          start: s.time?.[0] ? dayjs(s.time[0]).format('HH:mm') : '',
          end: s.time?.[1] ? dayjs(s.time[1]).format('HH:mm') : '',
        }))

      const payload = {
        department: values.department,
        training_date: firstDate ? firstDate.format('YYYY-MM-DD') : new Date().toISOString().slice(0, 10),
        subject: values.subject,
        time_slots: timeSlotsPayload,
        location: values.location,
        trainer: values.trainer,
        training_method: values.training_method,
        assessment_method: values.assessment_method,
        content: values.content,
        trainee_names: traineeDepts,
        issuer_department: values.issuer_department || values.department,
        issue_date: values.issue_date
          ? values.issue_date.format('YYYY-MM-DD')
          : (firstDate ? firstDate.format('YYYY-MM-DD') : undefined),
      }
      const r = await generateTrainingNotification(payload)
      downloadBase64File(r.base64, r.filename || '培训通知.docx')
      message.success('培训通知已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmittingWord(false)
    }
  }

  const handleExportExcel = async () => {
    const values = await form.validateFields()
    const traineeDepts: string[] = values.trainee_departments || []
    const timeSlots: Array<{ date: any; time: any }> = values.time_slots || []
    const firstSlot = timeSlots[0]
    const firstDate = firstSlot?.date

    setSubmittingExcel(true)
    try {
      const trainDate = firstDate ? firstDate.format('YYYY-MM-DD') : ''
      if (!trainDate) throw new Error('请选择培训日期')
      const topic = [values.subject, values.content].filter(Boolean).join(' ')
      // 构建 time_slots payload
      const timeSlotsPayload = timeSlots
        .filter((s: any) => s?.date)
        .map((s: any) => ({
          date: s.date.format('YYYY-MM-DD'),
          start: s.time?.[0] ? dayjs(s.time[0]).format('HH:mm') : '',
          end: s.time?.[1] ? dayjs(s.time[1]).format('HH:mm') : '',
        }))
      const payload = {
        training_date: trainDate,
        time_slots: timeSlotsPayload,
        department: traineeDepts[0] || values.department,
        topic,
        instructor: values.trainer,
        location: values.location,
        training_method: values.training_method,
        assessment_method: values.assessment_method,
        employee_names: values.employee_names || [],
        employee_departments: values.employee_names?.length ? Object.fromEntries(values.employee_names.map((n: string) => [n, nameToDeptMap[n] || ''])) : {},
      }
      const r = await generateTrainingSignInSheet(payload)
      downloadBase64File(r.base64, r.filename || '培训签到表.docx')
      message.success('培训签到表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmittingExcel(false)
    }
  }

  const handleAddToLedger = async () => {
    try {
    await form.validateFields([
        'department',
        ['time_slots', 0, 'date'],
        'subject',
        'employee_names',
      ])
    } catch {
      message.warning('请填写主办部门、培训日期、培训主题，并选择应出席受训人员')
      return
    }

    const values = form.getFieldsValue()
    const selectedNames: string[] = values.employee_names || []

    if (selectedNames.length === 0) {
      message.warning('请先选择应出席受训人员')
      return
    }

    // 收集有工号的员工
    const targets: { name: string; number: string }[] = []
    const missing: string[] = []
    for (const name of selectedNames) {
      const num = nameToNumberMap[name]
      if (num) {
        targets.push({ name, number: num })
      } else {
        missing.push(name)
      }
    }

    if (targets.length === 0) {
      message.warning('所选人员缺少工号信息，无法添加到培训台账')
      return
    }

    if (missing.length > 0) {
      message.warning(`以下人员缺少工号，将跳过：${missing.join('、')}`)
    }

    // 检查哪些员工还没有专属培训台账菜单页面
    const existingNumbers = await getExistingLedgerNumbers()
    const noPage = targets.filter((t) => !existingNumbers.has(t.number))

    Modal.confirm({
      title: '确认添加到培训台账',
      content: `是否给 ${targets.map((t) => t.name).join('、')} 添加本次培训记录到培训台账？`,
      onOk: async () => {
        setAddingToLedger(true)
        try {
          const timeSlots: Array<{ date: any; time: any }> = values.time_slots || []
          const firstDate = timeSlots[0]?.date
          const trainingDate = firstDate ? firstDate.format('YYYY-MM-DD') : ''
          const subject = values.subject
          const method = values.training_method || ''
          const department = values.department || ''
          const trainerVal = values.trainer || ''
          const trainerFull = trainerVal
            ? `${department}/${trainerVal}`
            : department

          let durationHours: number | undefined = undefined
          if (timeSlots.length > 0) {
            let totalMin = 0
            timeSlots.forEach((s: any) => {
              const t = s?.time
              if (t && t.length === 2) {
                const diff = dayjs(t[1]).diff(dayjs(t[0]), 'minute')
                if (diff > 0) totalMin += diff
              }
            })
            if (totalMin > 0) durationHours = Math.round(totalMin / 30) / 2
          }

          for (const target of targets) {
            await createTrainingLedger({
              employee_number: target.number,
              training_date: trainingDate,
              training_subject: subject,
              training_method: method,
              duration_hours: durationHours,
              trainer: trainerFull,
              source_type: 'notification',
            })
          }
          // 同步写入评估补录表（培训内容+部门+应到人数）
          try {
            await upsertTrainingEvaluation({
              training_content: subject,
              department,
              expected_count: targets.length,
              training_method: method,
              trainer_name: trainerVal,
              assessment_method: values.assessment_method || '',
            })
          } catch { message.warning('评估补录同步失败，请手动录入') }
          message.success(
            `已成功为 ${targets.map((t) => t.name).join('、')} 添加培训台账记录`
          )

          // 对没有专属菜单页面的员工，询问是否新建页面
          if (noPage.length > 0) {
            Modal.confirm({
              title: '新建培训台账页面',
              content: `当前没有 ${noPage.map((n) => n.name).join('、')} 的培训台账页面，是否新建？`,
              onOk: async () => {
                const created: string[] = []
                for (const p of noPage) {
                  try {
                    await createTrainingLedgerPage({
                      employee_number: p.number,
                      employee_name: p.name,
                    })
                    created.push(p.name)
                  } catch {
                    // 已存在或其他错误，跳过
                  }
                }
                if (created.length > 0) {
                  message.success(
                    `已为 ${created.join('、')} 新建培训台账页面，刷新页面后可在左侧菜单查看`
                  )
                }
              },
            })
          }
        } catch (err: any) {
          message.error(err.message || '添加到培训台账失败')
        } finally {
          setAddingToLedger(false)
        }
      },
    })
  }

  const handleGenerateAssessment = async () => {
    const values = form.getFieldsValue()
    if (!values.assessment_method) {
      message.warning('请先选择考核方式')
      return
    }
    setAssessmentModalOpen(true)
    setAssessmentFile(null)
    setAssessmentQuestions(null)
  }

  const handleAssessmentFileUpload = async () => {
    const values = form.getFieldsValue()
    if (!assessmentFile) {
      message.warning('请上传培训材料文件')
      return
    }
    setGeneratingAssessment(true)
    try {
      const formData = new FormData()
      formData.append('file', assessmentFile)
      formData.append('assessment_method', values.assessment_method || '笔试')
      formData.append('subject', values.subject || '')

      const result = await generateAssessmentQuestions(formData)
      setAssessmentQuestions(result.data)
      message.success('考核内容生成成功')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setGeneratingAssessment(false)
    }
  }

  const handleExportQaRecord = async () => {
    const values = form.getFieldsValue()
    const timeSlots: Array<{ date: any; time: any }> = values.time_slots || []
    const firstDate = timeSlots[0]?.date
    // 表头信息取自培训通知表单；已用 AI 出题则带上题目，否则考题区留空手写
    const qs = (assessmentQuestions?.questions || []).map((q: any) => ({
      file_no: q.file_no || '',
      question: q.question || q.content || '',
      answer: q.answer || '',
      score: q.score || 10,
    }))
    try {
      await exportQaRecord({
        training_content: [values.subject, values.content].filter(Boolean).join(' - '),
        training_date: firstDate ? firstDate.format('YYYY-MM-DD') : '',
        training_method: values.training_method || '问答',
        training_department: values.department || '',
        questions: qs,
        trainee_names: values.employee_names || [],
      })
      message.success('问答实操记录表已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
  }

  const trainingMethodWatch = Form.useWatch('training_method', form)
  const assessmentMethodWatch = Form.useWatch('assessment_method', form)
  const subjectWatch = Form.useWatch('subject', form) as string | undefined
  const deptWatch = Form.useWatch('department', form) as string | undefined
  const trainerWatch = Form.useWatch('trainer', form) as string | undefined
  const employeeNamesWatch = Form.useWatch('employee_names', form) as string[] | undefined

  const previewNames: string[] = employeeNamesWatch || []
  const subjectValue = subjectWatch || ''
  const deptValue = deptWatch || ''
  const trainingMethodValue = trainingMethodWatch || ''
  const trainerValue = trainerWatch || ''

  const traineeDepts: string[] = Form.useWatch('trainee_departments', form) || []
  const formValues = form.getFieldsValue()
  const timeSlotsValue: Array<{ date: any; time: any }> = Form.useWatch('time_slots', form) || []
  const locationValue = formValues?.location || ''
  const contentValue = formValues?.content || ''
  const issuerValue = formValues?.issuer_department || deptValue
  const firstSlotDate = timeSlotsValue?.[0]?.date || null
  const issueDateValue = formValues?.issue_date || firstSlotDate

  // 从 time_slots 计算日期字符串
  const dateStr = (() => {
    if (!timeSlotsValue || timeSlotsValue.length === 0) return '____年__月__日'
    const parts = timeSlotsValue.map((s: any) => {
      const d = s?.date
      const t = s?.time
      if (!d) return ''
      const datePart = d.format('YYYY年MM月DD日')
      if (t && t.length === 2) {
        return `${datePart} ${dayjs(t[0]).format('HH:mm')} ~ ${dayjs(t[1]).format('HH:mm')}`
      }
      return datePart
    }).filter(Boolean)
    return parts.join('；') || '____年__月__日'
  })()
  const singleDateStr = firstSlotDate ? firstSlotDate.format('YYYY年MM月DD日') : '____年__月__日'
  const issueDateStr = issueDateValue
    ? issueDateValue.format('YYYY年MM月DD日')
    : dateStr
  const topicStr = [subjectValue, contentValue].filter(Boolean).join(' ')

  const assessmentMethodValue = formValues?.assessment_method || ''
  const signInPageSize = 15
  const signInPages = previewNames.length > 0
    ? Array.from({ length: Math.ceil(previewNames.length / signInPageSize) }, (_, i) =>
        previewNames.slice(i * signInPageSize, (i + 1) * signInPageSize)
      )
    : []

  const hasBasicInfo = !!deptValue && !!firstSlotDate && !!subjectValue
  // Compute duration hours from time_slots (sum of all slots)
  const evalHours = (() => {
    if (!timeSlotsValue || timeSlotsValue.length === 0) return ''
    let totalMin = 0
    timeSlotsValue.forEach((s: any) => {
      const t = s?.time
      if (t && t.length === 2) {
        const diff = dayjs(t[1]).diff(dayjs(t[0]), 'minute')
        if (diff > 0) totalMin += diff
      }
    })
    if (totalMin === 0) return ''
    const h = Math.round(totalMin / 30) / 2
    return h === Math.floor(h) ? `${h}小时` : `${h}小时`
  })()
  const evalDurationHours = (() => {
    if (!timeSlotsValue || timeSlotsValue.length === 0) return 0
    let totalMin = 0
    timeSlotsValue.forEach((s: any) => {
      const t = s?.time
      if (t && t.length === 2) {
        const diff = dayjs(t[1]).diff(dayjs(t[0]), 'minute')
        if (diff > 0) totalMin += diff
      }
    })
    return Math.round(totalMin / 30) / 2
  })()

  return (
    <div className="space-y-6">
      <Card title="填写培训通知">
        <Form form={form} layout="vertical" className="max-w-4xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item
              name="department"
              label="主办部门"
              rules={[{ required: true, message: '请选择主办部门' }]}
            >
              <Select
                showSearch
                placeholder="选择部门"
                options={departments}
                className="w-full"
                onChange={async (dept: string) => {
                  if (!dept) return
                  // 自动加载该部门员工作为受训人员
                  try {
                    const res = await fetchEmployeesAction({ department: dept, page_size: 200 })
                    const emps = (res.data || []).map((e: any) => ({
                      value: e.name, label: `${e.name} - ${e.department || dept} (${e.employee_number})`,
                      employee_number: e.employee_number,
                    }))
                    setEmployees(emps)
                    setTrainerEmployees(emps)
                    const map: Record<string, string> = {}
                    const dmap: Record<string, string> = {}
                    emps.forEach((e: any) => { map[e.value] = e.employee_number; dmap[e.value] = e.department || dept })
                    setNameToNumberMap(map)
                    setNameToDeptMap(dmap)
                    // 自动填入受训部门
                    form.setFieldsValue({ trainee_departments: [dept] })
                    message.info(`已加载「${dept}」${emps.length} 名员工`)
                  } catch { message.error('加载员工失败') }
                }}
              />
            </Form.Item>

            <Form.Item
              name="subject"
              label="培训主题"
              rules={[{ required: true, message: '请填写培训主题' }]}
              className="md:col-span-2"
            >
              <Input placeholder="请输入培训主题，如：安全生产规范培训" />
            </Form.Item>

            {/* 多时段选择 */}
            <Form.List name="time_slots" initialValue={[{ date: null, time: [dayjs('08:00', 'HH:mm'), dayjs('12:00', 'HH:mm')] }]}>
              {(fields, { add, remove }) => (
                <div className="md:col-span-2 space-y-2">
                  {fields.map(({ key, name, ...rest }, index) => (
                    <Space key={key} className="w-full" align="start" wrap>
                      <Form.Item
                        name={[name, 'date']}
                        label={fields.length > 1 ? `时段${index + 1}日期` : '培训日期'}
                        rules={[{ required: true, message: '请选择日期' }]}
                        style={{ marginBottom: 0 }}
                      >
                        <DatePicker placeholder="选择日期" style={{ width: 160 }} />
                      </Form.Item>
                      <Form.Item
                        name={[name, 'time']}
                        label={fields.length > 1 ? `时段${index + 1}时间` : '培训时间'}
                        rules={[{ required: true, message: '请选择时间' }]}
                        style={{ marginBottom: 0 }}
                      >
                        <TimePicker.RangePicker format="HH:mm" style={{ width: 200 }} />
                      </Form.Item>
                      {fields.length > 1 && (
                        <Button
                          type="text"
                          icon={<MinusCircleOutlined />}
                          onClick={() => remove(name)}
                          style={{ marginTop: 30 }}
                          danger
                        />
                      )}
                    </Space>
                  ))}
                  <Button
                    type="dashed"
                    onClick={() => add({ date: null, time: [dayjs('09:00', 'HH:mm'), dayjs('10:00', 'HH:mm')] })}
                    icon={<PlusOutlined />}
                    block
                  >
                    添加时段
                  </Button>
                </div>
              )}
            </Form.List>

            <Form.Item name="location" label="培训地点">
              <Input placeholder="请输入培训地点" />
            </Form.Item>

            <Form.Item label="培训师">
              <div className="flex gap-2">
                <Select
                  showSearch
                  placeholder="选择部门"
                  options={departments}
                  value={trainerDept}
                  onChange={(v) => loadTrainerEmployees(v)}
                  allowClear
                  className="flex-1"
                />
                <Form.Item name="trainer" noStyle>
                  <Select
                    showSearch
                    placeholder="选择人员"
                    options={trainerEmployees}
                    disabled={!trainerDept}
                    allowClear
                    className="flex-1"
                    filterOption={(input, option) =>
                      (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                  />
                </Form.Item>
              </div>
            </Form.Item>

            <Form.Item name="training_method" label="培训方式">
              <Select
                showSearch
                placeholder="选择培训方式"
                options={TRAINING_METHODS}
                className="w-full"
                onChange={() => {}}
              />
            </Form.Item>

            <Form.Item name="assessment_method" label="考核方式">
              <Select
                showSearch
                placeholder="选择考核方式"
                options={ASSESSMENT_METHODS}
                className="w-full"
              />
            </Form.Item>

            {assessmentMethodWatch && (
              <Form.Item label="生成考核材料">
                <Space>
                  {assessmentMethodWatch === '笔试' ? (
                    <Button icon={<RobotOutlined />} onClick={handleGenerateAssessment}>
                      生成笔试试卷
                    </Button>
                  ) : (
                    <span className="text-[13px] text-[var(--color-steel)]">
                      <FormOutlined /> 问答考核请使用下方「考核矩阵」选题并录入成绩
                    </span>
                  )}
                </Space>
              </Form.Item>
            )}

            <Form.Item name="issuer_department" label="落款部门">
              <Select
                showSearch
                placeholder="默认为主办部门"
                options={departments}
                allowClear
                className="w-full"
              />
            </Form.Item>

            <Form.Item name="issue_date" label="落款日期">
              <DatePicker className="w-full" placeholder="默认为培训日期" />
            </Form.Item>

            <Form.Item name="content" label="培训内容" className="md:col-span-2">
              <Input.TextArea rows={3} placeholder="请输入培训内容" />
            </Form.Item>
          </div>

          <Form.Item
            name="trainee_departments"
            label="培训人员（受训部门）"
          >
            <Select
              mode="multiple"
              placeholder="选择受训部门（可多选）"
              options={departments}
              className="w-full"
              onChange={(value: string[]) => loadEmployees(value)}
            />
          </Form.Item>

          <Form.Item
            name="variety_filter"
            label="品种关键词筛选（可选，多选）"
          >
            <Select
              mode="multiple"
              showSearch
              placeholder="选择品种关键词，未命中的员工自动屏蔽"
              options={(varieties || []).map(v => ({ label: v, value: v }))}
              className="w-full"
              allowClear
              filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
              onChange={(vals: string[]) => {
                // 品种关键词筛选：体现品种/兼任品种命中关键词即保留，未命中自动屏蔽
                const filtered = allDeptEmployees.filter((e: any) =>
                  vals.length === 0 || vals.some((v: string) =>
                    (e.variety || '').includes(v) || (e.concurrent_variety || '').includes(v)
                  )
                )
                // 按「姓名+工号」去重后取姓名列表
                const dedupeKey = (e: any) => `${e.name}::${e.employee_number || ''}`
                const names = Array.from(new Set(
                  Array.from(new Map(filtered.map((e: any) => [dedupeKey(e), e])).values())
                    .map((e: any) => e.name)
                ))
                form.setFieldsValue({ employee_names: names, variety_filter: vals })
              }}
            />
          </Form.Item>

          <Form.Item
            name="employee_names"
            label={`应出席受训人员（${(watchedNames || []).length}人）`}
          >
            <Select
              mode="multiple"
              placeholder="选择应出席受训人员"
              options={employees}
              className="w-full"
            />
          </Form.Item>
          {previewNames.length > 0 && (
            <p className="text-gray-500 text-sm -mt-4 mb-4">
              已选 {previewNames.length} 人
              {previewNames.length > signInPageSize && (
                <span>，签到表将分为 {Math.ceil(previewNames.length / signInPageSize)} 页</span>
              )}
            </p>
          )}

          <Form.Item>
            <Space wrap>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={handleExportWord}
                loading={submittingWord}
              >
                导出培训通知
              </Button>
              <Button
                icon={<FileExcelOutlined />}
                onClick={handleExportExcel}
                loading={submittingExcel}
              >
                导出签到表
              </Button>
              <Button
                icon={<FormOutlined />}
                onClick={() => {
                  if (!subjectValue) return message.warning('请先填写培训主题')
                  if (previewNames.length === 0) return message.warning('请先选择出席受训人员')
                  setScoreModalOpen(true)
                }}
              >
                导出成绩单
              </Button>
              <Button
                type="default"
                icon={<BookOutlined />}
                onClick={handleAddToLedger}
                loading={addingToLedger}
              >
                添加到培训台账
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* 实操考核矩阵：考核方式选"问答"后出现 */}
      {assessmentMethodWatch === '问答' && subjectValue && deptValue && (
        <Card title="考核矩阵（选题 → 录成绩 → 同步台账）" className="mt-4">
          <AssessmentFlow
            subject={subjectValue}
            department={deptValue}
            trainingDate={
              firstSlotDate ? firstSlotDate.format('YYYY-MM-DD') : ''
            }
            trainingMethod={trainingMethodWatch || ''}
            trainer={trainerWatch}
            employeeNames={previewNames}
            employeeNumberMap={nameToNumberMap}
          />
        </Card>
      )}

      {/* Print preview area */}
      {hasBasicInfo && (
        <div id="print-area" className="space-y-6">
          {/* 培训通知预览 — 匹配 Word 模板布局 */}
          <Card>
            <div className="max-w-4xl mx-auto text-sm leading-relaxed">
              {/* 公司抬头 */}
              <div className="text-center mb-4">
                <p className="text-base font-bold">丽珠集团福州福兴医药有限公司</p>
                <p className="text-xs font-bold">LIVZON GROUP FUZHOU FUXING PHARMACEUTICAL CO., LTD.</p>
                <p className="text-xl font-bold mt-2">培训通知书</p>
                <p className="text-sm font-bold">Training Notification Form</p>
                <p className="text-xs mt-1 text-gray-500">
                  附件10/Annex 10&nbsp;&nbsp;SOP.01.1102.017
                </p>
              </div>

              {/* 信息表 — 匹配模板 */}
              <table className="w-full border-collapse border border-gray-700 text-center" style={{ tableLayout: 'fixed' }}>
                <colgroup>
                  <col style={{ width: '18%' }} />
                  <col style={{ width: '32%' }} />
                  <col style={{ width: '15%' }} />
                  <col style={{ width: '35%' }} />
                </colgroup>
                <tbody>
                  {/* 培训内容 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      培训内容<br /><span className="text-xs font-normal">Training content</span>
                    </td>
                    <td className="border border-gray-700 p-2" colSpan={3}>
                      {topicStr || '___'}
                    </td>
                  </tr>
                  {/* 培训日期 + 课时 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      培训日期<br /><span className="text-xs font-normal">Training date</span>
                    </td>
                    <td className="border border-gray-700 p-2">{dateStr}</td>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50">课时<br /><span className="text-xs font-normal">Hours</span></td>
                    <td className="border border-gray-700 p-2">{evalHours || '___'}</td>
                  </tr>
                  {/* 培训方式 + 授课人 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      培训方式<br /><span className="text-xs font-normal">Training method</span>
                    </td>
                    <td className="border border-gray-700 p-2">{trainingMethodValue || '___'}</td>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50">授课人<br /><span className="text-xs font-normal">Trainer</span></td>
                    <td className="border border-gray-700 p-2">{trainerValue || '___'}</td>
                  </tr>
                  {/* 培训对象 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      培训对象<br /><span className="text-xs font-normal">Trainees</span>
                    </td>
                    <td className="border border-gray-700 p-2" colSpan={3}>
                      {traineeDepts.length
                        ? traineeDepts.map((d) => `「${d}」全体成员`).join('、')
                        : `「${deptValue}」全体成员`}
                    </td>
                  </tr>
                  {/* 培训地点 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      培训地点<br /><span className="text-xs font-normal">Training place</span>
                    </td>
                    <td className="border border-gray-700 p-2" colSpan={3}>
                      {locationValue || '___'}
                    </td>
                  </tr>
                  {/* 考核方式 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                      考核方式<br /><span className="text-xs font-normal">Assessment way</span>
                    </td>
                    <td className="border border-gray-700 p-2" colSpan={3}>
                      {assessmentMethodValue || '___'}
                    </td>
                  </tr>
                  {/* 注意事项 */}
                  <tr>
                    <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '60px' }}>
                      注意事项<br /><span className="text-xs font-normal">Precautions</span>
                    </td>
                    <td className="border border-gray-700 p-2 text-left text-xs" colSpan={3}>
                      1. 请培训人员自带笔记本、笔，做好笔记。<br />
                      2. 请部门安排好参训人员的工作时间，做到培训工作两不误。<br />
                      3. 不得无故缺席、迟到，到场签到，有特殊情况须提前请假。
                    </td>
                  </tr>
                </tbody>
              </table>

              {/* 底部签发 */}
              <div className="flex justify-between items-end mt-4 text-sm px-2">
                <p>
                  部门/Dept：<span className="border-b border-gray-800 px-4 min-w-[100px] inline-block">{issuerValue || '___'}</span>
                  &nbsp;&nbsp;&nbsp;&nbsp;签发人/Issued by：<span className="border-b border-gray-800 px-4 min-w-[80px] inline-block"></span>
                </p>
                <p>
                  <span className="border-b border-gray-800 px-2 inline-block text-center min-w-[60px]">
                    {issueDateValue ? issueDateValue.format('YYYY') : '____'}
                  </span>年
                  <span className="border-b border-gray-800 px-2 inline-block text-center min-w-[30px]">
                    {issueDateValue ? issueDateValue.format('MM') : '__'}
                  </span>月
                  <span className="border-b border-gray-800 px-2 inline-block text-center min-w-[30px]">
                    {issueDateValue ? issueDateValue.format('DD') : '__'}
                  </span>日
                </p>
              </div>
            </div>
          </Card>

          {/* 签到表预览 — 匹配 Word 模板布局 */}
          {signInPages.map((pageNames, pageIdx) => {
            const totalPages = signInPages.length
            return (
              <Card key={pageIdx} className="mt-6 print:break-before-page">
                <div className="max-w-4xl mx-auto text-sm leading-relaxed">
                  {/* 公司抬头 — 匹配模板页眉 */}
                  <div className="text-center mb-4">
                    <p className="text-base font-bold">丽珠集团福州福兴医药有限公司</p>
                    <p className="text-xs font-bold">LIVZON GROUP FUZHOU FUXING PHARMACEUTICAL CO., LTD.</p>
                    <p className="text-xl font-bold mt-2">员工培训签到表</p>
                    <p className="text-sm font-bold">Employee Training Attendance Form</p>
                    <p className="text-xs mt-1 text-gray-500">
                      附件5/Annex 5&nbsp;&nbsp;SOP.01.1102.017（1/1）&nbsp;&nbsp;&nbsp;&nbsp;
                      第 {pageIdx + 1} 页 / page，共 {totalPages} 页 / in total
                    </p>
                  </div>

                  {/* 信息表 — 匹配模板 Table */}
                  <table className="w-full border-collapse border border-gray-700 text-center" style={{ tableLayout: 'fixed' }}>
                    <colgroup>
                      <col style={{ width: '20%' }} />
                      <col style={{ width: '31%' }} />
                      <col style={{ width: '18%' }} />
                      <col style={{ width: '31%' }} />
                    </colgroup>
                    <tbody>
                      {/* Row 1: 培训内容 */}
                      <tr>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                          培训内容<br /><span className="text-xs font-normal">Training content</span>
                        </td>
                        <td className="border border-gray-700 p-2" colSpan={3}>
                          {topicStr || '___'}
                        </td>
                      </tr>
                      {/* Row 2: 培训对象 + 培训方式 */}
                      <tr>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                          培训对象<br /><span className="text-xs font-normal">Trainees</span>
                        </td>
                        <td className="border border-gray-700 p-2">
                          {traineeDepts.length
                            ? traineeDepts.map((d) => `「${d}」全体成员`).join('、')
                            : `「${deptValue}」全体成员`}
                        </td>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50">
                          培训方式<br /><span className="text-xs font-normal">Training method</span>
                        </td>
                        <td className="border border-gray-700 p-2">
                          {trainingMethodValue || '___'}
                        </td>
                      </tr>
                      {/* Row 3: 培训课时 + 考核方式 */}
                      <tr>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                          培训课时<br /><span className="text-xs font-normal">Training hours</span>
                        </td>
                        <td className="border border-gray-700 p-2">
                          {evalHours || '___'}
                        </td>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50">
                          考核方式<br /><span className="text-xs font-normal">Assessment method</span>
                        </td>
                        <td className="border border-gray-700 p-2">
                          {assessmentMethodValue || '___'}
                        </td>
                      </tr>
                      {/* Row 4: 培训日期 */}
                      <tr>
                        <td className="border border-gray-700 p-2 font-bold bg-gray-50" style={{ height: '40px' }}>
                          培训日期<br /><span className="text-xs font-normal">Training date</span>
                        </td>
                        <td className="border border-gray-700 p-2" colSpan={3}>
                          {dateStr || '____年__月__日'}
                        </td>
                      </tr>
                      {/* Row 5: 表头 */}
                      <tr className="bg-gray-100 font-bold">
                        <td className="border border-gray-700 p-2" style={{ height: '36px' }}>
                          姓名<br /><span className="text-xs">Name</span>
                        </td>
                        <td className="border border-gray-700 p-2" colSpan={2}>
                          部门<br /><span className="text-xs">Dept.</span>
                        </td>
                        <td className="border border-gray-700 p-2">
                          签名+日期<br /><span className="text-xs">Signature + date</span>
                        </td>
                      </tr>
                      {/* Employee rows */}
                      {Array.from({ length: signInPageSize }).map((_, ri) => (
                        <tr key={ri} style={{ height: '28px' }}>
                          <td className="border border-gray-400 p-1 text-center">
                            {pageNames[ri] || ''}
                          </td>
                          <td className="border border-gray-400 p-1 text-center" colSpan={2}>
                            {pageNames[ri] ? (nameToDeptMap[pageNames[ri]] || traineeDepts[0] || deptValue) : ''}
                          </td>
                          <td className="border border-gray-400 p-1"></td>
                        </tr>
                      ))}
                      {/* Footer: 培训师签名 — 仅最后一页显示 */}
                      {pageIdx === totalPages - 1 && (
                        <>
                          <tr>
                            <td className="border border-gray-700 p-2 font-bold bg-gray-50" colSpan={2} style={{ height: '40px' }}>
                              培训师/培训组织者 签名/日期<br /><span className="text-xs font-normal">Trainer/training organizer&apos;s signature/date</span>
                            </td>
                            <td className="border border-gray-700 p-2" colSpan={2}></td>
                          </tr>
                          <tr>
                            <td className="border border-gray-400 p-2" colSpan={2}></td>
                            <td className="border border-gray-400 p-2" colSpan={2}></td>
                          </tr>
                        </>
                      )}
                    </tbody>
                  </table>

                  {/* 页码指示 */}
                  {totalPages > 1 && (
                    <p className="text-center text-xs text-gray-400 mt-2">
                      — 第 {pageIdx + 1} / {totalPages} 页 —
                    </p>
                  )}
                </div>
              </Card>
            )
          })}

          <Card className="mt-6">
            <EvaluationPreview
              topicStr={topicStr} dateStr={dateStr}
              trainingMethodValue={trainingMethodValue} trainerValue={trainerValue}
              assessmentMethodValue={assessmentMethodValue} deptValue={deptValue}
              traineeDepts={traineeDepts} previewNames={previewNames}
              evalDurationHours={evalDurationHours}
            />
          </Card>
        </div>
      )}

      {!hasBasicInfo && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <BellOutlined className="text-5xl mb-4" />
          <p>填写主办部门、培训日期和培训主题后预览培训通知、签到表和效果评估表</p>
        </div>
      )}

      {/* 生成考核材料 Modal */}
      <Modal
        title={assessmentMethodWatch === '笔试' ? '生成笔试试卷' : '生成问答实操'}
        open={assessmentModalOpen}
        footer={null}
        onCancel={() => { setAssessmentModalOpen(false); setAssessmentQuestions(null); setTraineeScoreMap({}) }}
        width={900}
      >
        <div className="space-y-4">
          {/* 未生成考题时：上传区 / 题库选题 */}
          {!assessmentQuestions && (
            <>
              <p className="text-gray-500">
                {assessmentMethodWatch === '笔试'
                  ? '上传培训材料文件（支持 .docx / .txt），AI 自动生成考题；或从题库直接选题。'
                  : '请从题库直接选题。'}
              </p>
              <Space wrap>
                {assessmentMethodWatch === '笔试' && (
                  <Upload accept=".docx,.txt" maxCount={1} beforeUpload={(file) => { setAssessmentFile(file); return false }} onRemove={() => setAssessmentFile(null)}>
                    <Button icon={<UploadOutlined />}>选择文件</Button>
                  </Upload>
                )}
                <Button icon={<SearchOutlined />} loading={loadingBank} onClick={async () => {
                  setLoadingBank(true)
                  try {
                    const d = await fetchQuestionBank({ page_size: 500 })
                    setBankQuestions(d.data || [])
                  } catch { message.error('加载题库失败') }
                  finally { setLoadingBank(false) }
                }}>从题库选题</Button>
              </Space>
              {assessmentMethodWatch === '笔试' && assessmentFile && (
                <p className="text-sm text-green-600">已选择：{assessmentFile.name}</p>
              )}
              {assessmentMethodWatch === '笔试' && (
                <Button type="primary" loading={generatingAssessment} onClick={handleAssessmentFileUpload} disabled={!assessmentFile}>
                  AI 开始生成
                </Button>
              )}

              {/* 题库列表 */}
              {bankQuestions.length > 0 && (
                <div className="border rounded p-3 max-h-80 overflow-y-auto">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold">题库 (共{bankQuestions.length}题，已选{selectedBankIds.size}题)</span>
                    <Space>
                      <Button size="small" onClick={() => setSelectedBankIds(new Set(bankQuestions.map((q: any) => q.id)))}>全部</Button>
                      <Button size="small" onClick={() => setSelectedBankIds(new Set())}>清空</Button>
                      {(() => {
                        const filtered = bankQuestions.filter((q: any) => {
                          if (!bankSearch) return true
                          const kw = bankSearch.toLowerCase()
                          return (q.file_no || '').toLowerCase().includes(kw) || (q.question || '').toLowerCase().includes(kw)
                        })
                        const start = (bankPage - 1) * BANK_PAGE_SIZE
                        const pageItems = filtered.slice(start, start + BANK_PAGE_SIZE)
                        const pageIds = new Set(pageItems.map((q: any) => q.id))
                        const allPageSelected = pageItems.length > 0 && pageItems.every((q: any) => selectedBankIds.has(q.id))
                        return (<Button size="small" onClick={() => {
                          const next = new Set(selectedBankIds)
                          if (allPageSelected) { for (const id of pageIds) next.delete(id) }
                          else { for (const id of pageIds) next.add(id) }
                          setSelectedBankIds(next)
                        }}>{allPageSelected ? '取消本页' : '本页全选'}</Button>)
                      })()}
                      <Button type="primary" size="small" disabled={selectedBankIds.size === 0} onClick={() => {
                        const selected = bankQuestions.filter((q: any) => selectedBankIds.has(q.id))
                        const questions = selected.map((q: any) => ({
                          file_no: q.file_no || '',
                          question: q.question || '',
                          answer: q.answer || '',
                          score: q.score || 10,
                        }))
                        const totalScore = questions.reduce((s: number, q: any) => s + (q.score || 0), 0)
                        setAssessmentQuestions({ questions, total_score: totalScore, title: '题库选题' })
                        setBankQuestions([])
                        setSelectedBankIds(new Set())
                        setBankSearch('')
                      }}>确认选题 ({selectedBankIds.size}题)</Button>
                    </Space>
                  </div>
                  <Input prefix={<SearchOutlined />} placeholder="搜索题目或文件编号" size="small" className="mb-2"
                    value={bankSearch} onChange={e => { setBankSearch(e.target.value); setBankPage(1) }} allowClear />
                  {(() => {
                    const filtered = bankQuestions.filter((q: any) => {
                      if (!bankSearch) return true
                      const kw = bankSearch.toLowerCase()
                      return (q.file_no || '').toLowerCase().includes(kw) || (q.question || '').toLowerCase().includes(kw)
                    })
                    const totalPages = Math.ceil(filtered.length / BANK_PAGE_SIZE)
                    const start = (bankPage - 1) * BANK_PAGE_SIZE
                    const pageItems = filtered.slice(start, start + BANK_PAGE_SIZE)
                    return (<>
                      {pageItems.map((q: any) => (
                        <div key={q.id} className={`flex items-center gap-2 py-1 px-2 cursor-pointer rounded ${selectedBankIds.has(q.id) ? 'bg-blue-50' : ''}`}
                          onClick={() => {
                            const next = new Set(selectedBankIds)
                            next.has(q.id) ? next.delete(q.id) : next.add(q.id)
                            setSelectedBankIds(next)
                          }}>
                          <input type="checkbox" checked={selectedBankIds.has(q.id)} readOnly className="shrink-0" />
                          <span className="text-xs text-gray-400 w-16 truncate">{q.file_no || '-'}</span>
                          <span className="text-sm flex-1 truncate">{q.question}</span>
                          <Tag color="green" className="text-xs">{q.score || 10}分</Tag>
                        </div>
                      ))}
                      {totalPages > 1 && (
                        <div className="flex justify-center items-center gap-2 pt-2 border-t mt-2">
                          <Button size="small" disabled={bankPage <= 1} onClick={() => setBankPage(p => p - 1)}>上一页</Button>
                          <span className="text-sm text-gray-500">{bankPage} / {totalPages} (共{filtered.length}题)</span>
                          <Button size="small" disabled={bankPage >= totalPages} onClick={() => setBankPage(p => p + 1)}>下一页</Button>
                        </div>
                      )}
                    </>)
                  })()}
                </div>
              )}
            </>
          )}

          {/* 生成后：题目预览 + 学员评分表 */}
          {assessmentQuestions && (
            <>
              <div className="border rounded p-4 max-h-64 overflow-y-auto">
                <h3 className="font-bold mb-2">
                  考题 (共{assessmentQuestions.questions?.length || 0}题，满分{assessmentQuestions.total_score || 100}分)
                </h3>
                {(assessmentQuestions.questions || []).map((q: any, i: number) => (
                  <div key={i} className="mb-2 border-b pb-1 text-sm">
                    <span className="font-medium">{i + 1}. </span>
                    <span>{q.question || q.content}</span>
                    {q.answer && <span className="text-green-600 ml-2">(答案：{q.answer})</span>}
                  </div>
                ))}
            </div>

            {/* 学员评分区 */}
            {assessmentQuestions && (() => {
              const traineeNames: string[] = form.getFieldValue('employee_names') || []
              const maxScore = (assessmentQuestions.questions || []).reduce((s: number, q: any) => s + (q.score || 10), 0)
              return traineeNames.length > 0 ? (
                <div className="border rounded p-4">
                  <h3 className="font-bold mb-1">学员评分 (满分{maxScore}分，点击题号标记错题)</h3>
                  <p className="text-xs text-gray-400 mb-3">默认全对满分，点击题号变红即为错题，自动扣分</p>
                  {(() => {
                    const questions = assessmentQuestions.questions || []
                    const totalPages = Math.ceil(traineeNames.length / TRAINEE_PAGE_SIZE)
                    const start = (traineePage - 1) * TRAINEE_PAGE_SIZE
                    const pageNames = traineeNames.slice(start, start + TRAINEE_PAGE_SIZE)
                    return (<>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm border-collapse">
                          <thead>
                            <tr className="bg-gray-50">
                              <th className="border px-2 py-1 text-left">学员</th>
                              {questions.map((q: any, qi: number) => (
                                <th key={qi} className="border px-1 py-1 text-center w-10" title={q.question}>{qi + 1}</th>
                              ))}
                              <th className="border px-2 py-1 text-center w-14">得分</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pageNames.map((name: string) => {
                              const data = traineeScoreMap[name] || { wrongIndices: [], score: maxScore }
                              const computedScore = maxScore - data.wrongIndices.reduce((s: number, i: number) => s + (questions[i]?.score || 10), 0)
                              return (
                                <tr key={name}>
                                  <td className="border px-2 py-1 font-medium whitespace-nowrap">{name}</td>
                                  {questions.map((q: any, qi: number) => {
                                    const isWrong = data.wrongIndices.includes(qi)
                                    return (
                                      <td key={qi} className="border px-1 py-1 text-center">
                                        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs cursor-pointer font-bold select-none ${isWrong ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'}`}
                                          onClick={() => {
                                            const cur = traineeScoreMap[name] || { wrongIndices: [], score: maxScore }
                                            const idx = cur.wrongIndices.indexOf(qi)
                                            const newWrong = idx >= 0 ? cur.wrongIndices.filter((i: number) => i !== qi) : [...cur.wrongIndices, qi].sort((a: number, b: number) => a - b)
                                            setTraineeScoreMap(prev => ({ ...prev, [name]: { ...cur, wrongIndices: newWrong, score: 0 } }))
                                          }} title={isWrong ? '点击取消错题' : '点击标记错题'}>
                                          {isWrong ? '✗' : '✓'}
                                        </span>
                                      </td>
                                    )
                                  })}
                                  <td className="border px-2 py-1 text-center font-bold">
                                    <span className={computedScore < maxScore * 0.6 ? 'text-red-500' : 'text-green-600'}>{computedScore}</span>
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                      {totalPages > 1 && (
                        <div className="flex justify-center items-center gap-2 pt-2">
                          <Button size="small" disabled={traineePage <= 1} onClick={() => setTraineePage(p => p - 1)}>上一页</Button>
                          <span className="text-sm text-gray-500">{traineePage} / {totalPages} (共{traineeNames.length}人)</span>
                          <Button size="small" disabled={traineePage >= totalPages} onClick={() => setTraineePage(p => p + 1)}>下一页</Button>
                        </div>
                      )}
                    </>)
                  })()}
                </div>
              ) : null
            })()}

            {/* 底部操作 */}
            {assessmentQuestions && (
              <Space wrap className="w-full justify-end">
                <Button onClick={() => { setAssessmentModalOpen(false); setAssessmentQuestions(null); setTraineeScoreMap({}) }}>关闭</Button>
                {assessmentMethodWatch === '笔试' && (
                  <Button onClick={async () => {
                    try {
                      const v = form.getFieldsValue()
                      const questions = (assessmentQuestions?.questions || []).map((q: any) => ({ type: q.type || 'choice', question: q.question || q.content || '', options: q.options || [], answer: q.answer || '', score: q.score || 5 }))
                      const counts: Record<string, number> = {}
                      questions.forEach((q: any) => { counts[q.type] = (counts[q.type] || 0) + 1 })
                      await saveExamPaper({ subject: [v.subject, v.content].filter(Boolean).join(' - ') || '笔试试卷', department: v.department || undefined, training_date: (v.time_slots?.[0]?.date ? v.time_slots[0].date.format('YYYY-MM-DD') : ''), training_method: v.training_method, questions, full_score: assessmentQuestions?.total_score || 100, choice_count: counts.choice || 0, true_false_count: counts.true_false || 0, multi_choice_count: counts.multi_choice || 0, fill_blank_count: counts.fill_blank || 0 })
                      message.success('考卷已保存，可在资料下载中查看')
                    } catch (err: any) { message.error(err.message || '保存考卷失败') }
                  }}>保存考卷</Button>
                )}
                <Button onClick={async () => {
                  const v = form.getFieldsValue()
                  const questions = (assessmentQuestions?.questions || []).map((q: any) => ({ file_no: q.file_no || '', question: q.question || q.content || '', answer: q.answer || '', score: q.score || 10 }))
                  const traineeNames = v.employee_names || []
                  const maxScore = questions.reduce((s: number, q: any) => s + (q.score || 0), 0)
                  const scores = traineeNames.map((name: string) => {
                    const data = traineeScoreMap[name] || { wrongIndices: [], score: maxScore }
                    return { name, department: nameToDeptMap[name] || v.department || '', wrong_questions: data.wrongIndices, total_score: maxScore - data.wrongIndices.reduce((s: number, i: number) => s + (questions[i]?.score || 0), 0) }
                  })
                  try {
                    const r = await exportScoreReport({
                      training_content: [v.subject, v.content].filter(Boolean).join(' - '),
                      training_date: (v.time_slots?.[0]?.date ? v.time_slots[0].date.format('YYYY-MM-DD') : '') || '',
                      training_department: v.department || '',
                      scores_json: JSON.stringify(scores),
                    })
                    downloadBase64File(r.base64, r.filename)
                    message.success('成绩单已导出')
                  } catch (err: any) { message.error(err.message || '导出失败') }
                }}>导出成绩单</Button>
                <Button type="primary" onClick={async () => {
                  const v = form.getFieldsValue()
                  const questions = (assessmentQuestions?.questions || []).map((q: any) => ({ file_no: q.file_no || '', question: q.question || q.content || '', answer: q.answer || '', score: q.score || 10 }))
                  const traineeNames = v.employee_names || []
                  const maxScore = questions.reduce((s: number, q: any) => s + (q.score || 0), 0)
                  const scores = traineeNames.map((name: string) => {
                    const data = traineeScoreMap[name] || { wrongIndices: [], score: maxScore }
                    const computed = maxScore - data.wrongIndices.reduce((s: number, i: number) => s + (questions[i]?.score || 0), 0)
                    return { name, wrong_questions: data.wrongIndices, total_score: computed }
                  })
                  try {
                    const r = await exportQaRecordWithScores({
                      training_content: [v.subject, v.content].filter(Boolean).join(' - '),
                      training_date: (v.time_slots?.[0]?.date ? v.time_slots[0].date.format('YYYY-MM-DD') : '') || '',
                      training_method: v.training_method || '问答',
                      training_department: v.department || '',
                      questions_json: JSON.stringify(questions),
                      trainee_names_json: JSON.stringify(traineeNames),
                      scores_json: JSON.stringify(scores),
                    })
                    downloadBase64File(r.base64, r.filename)
                    message.success('导出成功')
                  } catch (err: any) { message.error(err.message || '导出失败') }
                }}>
                  导出实操记录表（含错题）
                </Button>
              </Space>
            )}
          </>
          )}
        </div>
      </Modal>

      {/* 成绩单导出弹窗 */}
      <Modal
        title="导出考核成绩单"
        open={scoreModalOpen}
        onCancel={() => setScoreModalOpen(false)}
        width={500}
        footer={[
          <Button key="cancel" onClick={() => setScoreModalOpen(false)}>取消</Button>,
          <Button key="export" type="primary" loading={exportingScore} onClick={async () => {
            const scores = previewNames.map(name => ({
              name,
              department: nameToDeptMap[name] || traineeDepts[0] || deptValue || '',
              score: scoreMap[name] || 0,
            }))
            setExportingScore(true)
            try {
              const r = await exportTrainingAssessmentScores({
                training_content: subjectValue,
                training_date: firstSlotDate ? firstSlotDate.format('YYYY-MM-DD') : '',
                department: traineeDepts.join('、') || deptValue || '',
                scores,
              })
              downloadBase64File(r.base64, r.filename)
              message.success('成绩单已导出')
            } catch { message.error('导出失败') }
            finally { setExportingScore(false) }
          }}>导出 Word</Button>,
        ]}
      >
        <p className="text-sm text-gray-500 mb-3">
          培训内容：{subjectValue}<br />
          培训部门：{traineeDepts.join('、') || deptValue}
        </p>
        <div style={{ maxHeight: 400, overflow: 'auto' }}>
          <table className="w-full border-collapse border border-gray-300 text-sm">
            <thead>
              <tr className="bg-gray-50">
                <th className="border p-2">序号</th>
                <th className="border p-2">姓名</th>
                <th className="border p-2">部门</th>
                <th className="border p-2">成绩</th>
              </tr>
            </thead>
            <tbody>
              {previewNames.map((name, idx) => (
                <tr key={idx}>
                  <td className="border p-2 text-center">{idx + 1}</td>
                  <td className="border p-2">{name}</td>
                  <td className="border p-2">{nameToDeptMap[name] || traineeDepts[0] || deptValue}</td>
                  <td className="border p-1">
                    <InputNumber min={0} max={100} size="small" className="w-full"
                      value={scoreMap[name]} onChange={v => setScoreMap(prev => ({ ...prev, [name]: v || 0 }))} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Modal>

      <style jsx global>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #print-area,
          #print-area * {
            visibility: visible;
          }
          #print-area {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
          .ant-card-head {
            border-bottom: 1px solid #000 !important;
          }
        }
      `}</style>
    </div>
  )
}
