'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  TimePicker,
  message,
} from 'antd'
import {
  DownloadOutlined,
  BellOutlined,
  FileExcelOutlined,
  BookOutlined,
  SendOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchDepartments,
  fetchEmployees,
  fetchTrainingLedgerPages,
  generateTrainingNotification,
  generateTrainingSignInSheet,
  generateTrainingEvaluation,
  createTrainingLedger,
  createTrainingLedgerPage,
  sendTrainingNotification,
} from '@/lib/api/hr'
import { moduleMenus, type SubMenuItem } from '@/lib/menu-config'
import EvaluationPreview from './EvaluationPreview'

const TRAINING_METHODS = [
  { value: '面授', label: '面授' },
  { value: '自学', label: '自学' },
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
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [employees, setEmployees] = useState<{ value: string; label: string }[]>([])
  const [nameToNumberMap, setNameToNumberMap] = useState<Record<string, string>>({})
  const [submittingWord, setSubmittingWord] = useState(false)
  const [submittingExcel, setSubmittingExcel] = useState(false)
  const [submittingEval, setSubmittingEval] = useState(false)
  const [addingToLedger, setAddingToLedger] = useState(false)
  const [sendingNotify, setSendingNotify] = useState(false)
  const [trainerDept, setTrainerDept] = useState<string | undefined>(undefined)
  const [trainerEmployees, setTrainerEmployees] = useState<{ value: string; label: string }[]>([])

  const searchParams = useSearchParams()

  useEffect(() => {
    fetchDepartments({ page_size: 100 }).then((res) => {
      const list = (res.data || []).map((d: any) => ({ value: d.name, label: d.name }))
      setDepartments(list)
    })
  }, [])

  // 从年度计划跳转过来时，自动填入
  useEffect(() => {
    const subject = searchParams.get('subject')
    const method = searchParams.get('method')
    const dept = searchParams.get('dept')
    if (subject) {
      form.setFieldsValue({
        subject: decodeURIComponent(subject),
        training_method: method ? decodeURIComponent(method) : undefined,
        assessment_method: searchParams.get('assessment') ? decodeURIComponent(searchParams.get('assessment')!) : undefined,
      })
      if (dept) {
        const deptName = decodeURIComponent(dept)
        setTrainerDept(deptName)
        // 加载该部门员工
        fetchEmployees({ department: deptName, page_size: 200 }).then(res => {
          const emps = (res.data || []).map((e: any) => ({
            value: e.name, label: `${e.employee_number} ${e.name}`,
            employee_number: e.employee_number
          }))
          setEmployees(emps)
          setTrainerEmployees(emps)
          const map: Record<string, string> = {}
          emps.forEach((e: any) => { map[e.value] = e.employee_number })
          setNameToNumberMap(map)
        })
      }
    }
  }, [searchParams])

  // 培训师：选部门后加载该部门员工
  const loadTrainerEmployees = async (dept: string) => {
    setTrainerDept(dept)
    form.setFieldsValue({ trainer: undefined })
    if (!dept) { setTrainerEmployees([]); return }
    try {
      const res = await fetchEmployees({ department: dept, page_size: 200 })
      setTrainerEmployees((res.data || []).map((e: any) => ({
        value: e.name,
        label: `${e.name} (${e.employee_number || ''})`,
      })))
    } catch { setTrainerEmployees([]) }
  }

  const loadEmployees = async (depts: string[]) => {
    if (!depts || depts.length === 0) {
      setEmployees([])
      setNameToNumberMap({})
      form.setFieldsValue({ employee_names: [] })
      return
    }
    const all: { value: string; label: string }[] = []
    const numberMap: Record<string, string> = {}
    for (const dept of depts) {
      try {
        const res = await fetchEmployees({ department: dept, page_size: 100 })
        const list = (res.data || []).map((e: any) => ({
          value: e.name,
          label: `${e.name} (${e.employee_number || ''})`,
        }))
        all.push(...list)
        for (const e of res.data || []) {
          if (e.name && e.employee_number) {
            numberMap[e.name] = e.employee_number
          }
        }
      } catch {
        // ignore
      }
    }
    const map = new Map(all.map((e) => [e.value, e]))
    const uniqueList = Array.from(map.values())
    setEmployees(uniqueList)
    setNameToNumberMap(numberMap)
    const names = uniqueList.map((e) => e.value)
    form.setFieldsValue({ employee_names: names })
  }

  const handleExportWord = async () => {
    const values = await form.validateFields()
    const traineeDepts: string[] = values.trainee_departments || []

    setSubmittingWord(true)
    try {
      const payload = {
        department: values.department,
        training_date: values.training_date.format('YYYY-MM-DD'),
        subject: values.subject,
        training_time_start: values.training_time
          ? dayjs(values.training_time[0]).format('HH:mm')
          : undefined,
        training_time_end: values.training_time
          ? dayjs(values.training_time[1]).format('HH:mm')
          : undefined,
        location: values.location,
        trainer: values.trainer,
        training_method: values.training_method,
        assessment_method: values.assessment_method,
        content: values.content,
        trainee_names: traineeDepts,
        issuer_department: values.issuer_department || values.department,
        issue_date: values.issue_date
          ? values.issue_date.format('YYYY-MM-DD')
          : values.training_date.format('YYYY-MM-DD'),
      }
      await generateTrainingNotification(payload)
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

    setSubmittingExcel(true)
    try {
      const topic = [values.subject, values.content].filter(Boolean).join(' ')
      const payload = {
        training_date: values.training_date.format('YYYY-MM-DD'),
        training_time_start: values.training_time
          ? dayjs(values.training_time[0]).format('HH:mm')
          : undefined,
        training_time_end: values.training_time
          ? dayjs(values.training_time[1]).format('HH:mm')
          : undefined,
        department: traineeDepts[0] || values.department,
        topic,
        instructor: values.trainer,
        location: values.location,
        training_method: values.training_method,
        assessment_method: values.assessment_method,
        employee_names: values.employee_names || [],
      }
      await generateTrainingSignInSheet(payload)
      message.success('培训签到表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmittingExcel(false)
    }
  }

  const handleExportEvaluation = async () => {
    const values = await form.validateFields()
    setSubmittingEval(true)
    try {
      let durationHours: number | undefined = undefined
      if (values.training_time && values.training_time.length === 2) {
        const start = dayjs(values.training_time[0])
        const end = dayjs(values.training_time[1])
        const diffMinutes = end.diff(start, 'minute')
        durationHours = Math.round(diffMinutes / 30) / 2
      }

      const payload = {
        subject: values.subject,
        training_date: values.training_date.format('YYYY-MM-DD'),
        training_time_start: values.training_time ? dayjs(values.training_time[0]).format('HH:mm') : undefined,
        training_time_end: values.training_time ? dayjs(values.training_time[1]).format('HH:mm') : undefined,
        duration_hours: durationHours,
        training_method: values.training_method,
        trainer: values.trainer,
        trainee_names: values.employee_names || [],
        assessment_method: values.assessment_method,
      }
      await generateTrainingEvaluation(payload)
      message.success('培训效果评估表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmittingEval(false)
    }
  }

  const handleAddToLedger = async () => {
    try {
      await form.validateFields([
        'department',
        'training_date',
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
          const trainingDate = values.training_date.format('YYYY-MM-DD')
          const subject = values.subject
          const method = values.training_method || ''
          const department = values.department || ''
          const trainerVal = values.trainer || ''
          const trainerFull = trainerVal
            ? `${department}/${trainerVal}`
            : department

          let durationHours: number | undefined = undefined
          if (values.training_time && values.training_time.length === 2) {
            const start = dayjs(values.training_time[0])
            const end = dayjs(values.training_time[1])
            const diffMinutes = end.diff(start, 'minute')
            durationHours = Math.round(diffMinutes / 30) / 2
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

  const handleSendNotify = async () => {
    const values = form.getFieldsValue()
    const selectedNames: string[] = values.employee_names || []
    if (selectedNames.length === 0) {
      message.warning('请先选择应出席受训人员')
      return
    }

    const numbers: string[] = []
    for (const name of selectedNames) {
      const num = nameToNumberMap[name]
      if (num) numbers.push(num)
    }

    if (numbers.length === 0) {
      message.warning('所选人员缺少工号信息，无法发送通知')
      return
    }

    try {
      await form.validateFields(['department', 'training_date', 'subject'])
    } catch {
      message.warning('请填写主办部门、培训日期和培训主题')
      return
    }

    Modal.confirm({
      title: '确认发送培训通知',
      content: `将向 ${numbers.length} 位受训人员发送飞书消息，是否继续？`,
      onOk: async () => {
        setSendingNotify(true)
        try {
          const payload = {
            employee_numbers: numbers,
            department: values.department,
            subject: values.subject,
            training_date: values.training_date.format('YYYY-MM-DD'),
            training_time_start: values.training_time
              ? dayjs(values.training_time[0]).format('HH:mm')
              : undefined,
            training_time_end: values.training_time
              ? dayjs(values.training_time[1]).format('HH:mm')
              : undefined,
            location: values.location,
            trainer: values.trainer,
            content: values.content,
            training_method: values.training_method,
            issuer_department: values.issuer_department || values.department,
            issue_date: values.issue_date
              ? values.issue_date.format('YYYY-MM-DD')
              : values.training_date.format('YYYY-MM-DD'),
          }
          const res = await sendTrainingNotification(payload)
          message.success(res.message)
        } catch (err: any) {
          message.error(err.message || '添加失败')
        } finally {
          setSendingNotify(false)
        }
      },
    })
  }

  const formValues = form.getFieldsValue()
  const traineeDepts: string[] = formValues?.trainee_departments || []
  const deptValue = formValues?.department || ''
  const dateValue = formValues?.training_date
  const subjectValue = formValues?.subject || ''
  const timeValue = formValues?.training_time
  const locationValue = formValues?.location || ''
  const trainerValue = formValues?.trainer || ''
  const contentValue = formValues?.content || ''
  const issuerValue = formValues?.issuer_department || deptValue
  const issueDateValue = formValues?.issue_date || dateValue
  const trainingMethodValue = formValues?.training_method || ''
  const previewNames: string[] = formValues?.employee_names || []

  const dateStr = dateValue ? dateValue.format('YYYY年MM月DD日') : '____年__月__日'
  const timeStr =
    timeValue
      ? `${dayjs(timeValue[0]).format('HH:mm')} ~ ${dayjs(timeValue[1]).format('HH:mm')}`
      : ''
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

  const hasBasicInfo = !!deptValue && !!dateValue && !!subjectValue
  // Compute duration hours for preview
  const evalHours = (() => {
    if (timeValue && timeValue.length === 2) {
      const diff = dayjs(timeValue[1]).diff(dayjs(timeValue[0]), 'minute')
      const h = Math.round(diff / 30) / 2
      return h === Math.floor(h) ? `${h}小时` : `${h}小时`
    }
    return ''
  })()
  const evalDurationHours = (() => {
    if (timeValue && timeValue.length === 2) {
      const diff = dayjs(timeValue[1]).diff(dayjs(timeValue[0]), 'minute')
      return Math.round(diff / 30) / 2
    }
    return ''
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
              />
            </Form.Item>

            <Form.Item
              name="training_date"
              label="培训日期"
              rules={[{ required: true, message: '请选择培训日期' }]}
            >
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>

            <Form.Item
              name="subject"
              label="培训主题"
              rules={[{ required: true, message: '请填写培训主题' }]}
              className="md:col-span-2"
            >
              <Input placeholder="请输入培训主题，如：安全生产规范培训" />
            </Form.Item>

            <Form.Item
              name="training_time"
              label="培训时间"
              initialValue={[dayjs('08:00', 'HH:mm'), dayjs('12:00', 'HH:mm')]}
            >
              <TimePicker.RangePicker className="w-full" format="HH:mm" />
            </Form.Item>

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
            name="employee_names"
            label="应出席受训人员"
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
                icon={<DownloadOutlined />}
                onClick={handleExportEvaluation}
                loading={submittingEval}
              >
                导出培训效果评估表
              </Button>
              <Button
                type="default"
                icon={<BookOutlined />}
                onClick={handleAddToLedger}
                loading={addingToLedger}
              >
                添加到培训台账
              </Button>
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSendNotify}
                loading={sendingNotify}
              >
                通知受训人员
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

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
                      {traineeDepts.join('、') || deptValue || '___'}
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
                          {traineeDepts.join('、') || deptValue || '___'}
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
                            {pageNames[ri] ? (traineeDepts[0] || deptValue) : ''}
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
