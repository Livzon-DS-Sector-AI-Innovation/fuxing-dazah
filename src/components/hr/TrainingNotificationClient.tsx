'use client'

import { useEffect, useState } from 'react'
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

const TRAINING_METHODS = [
  { value: '面授', label: '面授' },
  { value: '函授', label: '函授' },
  { value: '远程教育', label: '远程教育' },
  { value: '自学', label: '自学' },
  { value: '其他', label: '其他' },
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
  const ledger = training?.children?.find((c) => c.key === 'training-ledger')

  function collectChildren(items: SubMenuItem[] | undefined) {
    items?.forEach((c) => {
      const match = c.path.match(/employee_number=(\d+)/)
      if (match) numbers.add(match[1])
      collectChildren(c.children)
    })
  }
  collectChildren(ledger?.children)

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

  useEffect(() => {
    fetchDepartments({ page_size: 100 }).then((res) => {
      const list = (res.data || []).map((d: any) => ({ value: d.name, label: d.name }))
      setDepartments(list)
    })
  }, [])

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

      const topicStr = [values.subject, values.content].filter(Boolean).join(' ')
      const payload = {
        subject: topicStr,
        training_date: values.training_date.format('YYYY-MM-DD'),
        duration_hours: durationHours,
        training_method: values.training_method,
        trainer_type: values.trainer,
        textbook: `${values.department || ''} / ${(values.trainee_departments || []).join('、')} / ${(values.employee_names || []).length}人`,
        expected_count: (values.employee_names || []).length,
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

  const signInPageSize = 30
  const signInPages = previewNames.length > 0
    ? Array.from({ length: Math.ceil(previewNames.length / signInPageSize) }, (_, i) =>
        previewNames.slice(i * signInPageSize, (i + 1) * signInPageSize)
      )
    : []

  const hasBasicInfo = !!deptValue && !!dateValue && !!subjectValue
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

            <Form.Item name="trainer" label="培训师">
              <Input placeholder="请输入培训师姓名" />
            </Form.Item>

            <Form.Item name="training_method" label="培训方式">
              <Select
                showSearch
                placeholder="选择培训方式"
                options={TRAINING_METHODS}
                className="w-full"
              />
            </Form.Item>

            <Form.Item name="issuer_department" label="落款部门">
              <Input placeholder="默认为主办部门" />
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
          <Card>
            <div className="max-w-3xl mx-auto p-8 text-sm leading-relaxed">
              <h2 className="text-center text-xl font-bold mb-8">培训通知</h2>

              <p className="mb-4 indent-8">
                <span className="border-b border-gray-800 px-2">{deptValue}</span>
                将于
                <span className="border-b border-gray-800 px-2">{dateStr}</span>
                举行
                <span className="border-b border-gray-800 px-2">{subjectValue}</span>
                的培训，详细培训安排如下：
              </p>

              <p className="mb-2">
                <strong>培训时间：</strong>
                <span className="border-b border-gray-800 px-2 min-w-[200px] inline-block">
                  {timeStr || ' '}
                </span>
              </p>
              <p className="mb-2">
                <strong>培训地点：</strong>
                <span className="border-b border-gray-800 px-2 min-w-[200px] inline-block">
                  {locationValue || ' '}
                </span>
              </p>
              <p className="mb-2">
                <strong>培训师：</strong>
                <span className="border-b border-gray-800 px-2 min-w-[200px] inline-block">
                  {trainerValue || ' '}
                </span>
              </p>
              <p className="mb-2">
                <strong>培训内容：</strong>
                <span className="border-b border-gray-800 px-2 min-w-[300px] inline-block">
                  {contentValue || ' '}
                </span>
              </p>
              <p className="mb-4">
                <strong>培训人员：</strong>
                <span className="border-b border-gray-800 px-2 min-w-[300px] inline-block">
                  {traineeDepts.join('、') || ' '}
                </span>
              </p>

              <div className="mb-6">
                <p className="mb-1">
                  <strong>备注：</strong>1.请培训人员自带笔记本、笔，做好笔记。
                </p>
                <p className="mb-1 pl-10">2.请部门安排好参训人员的工作时间，做到培训工作两不误。</p>
                <p className="pl-10">3.不得无故缺席、迟到，到场签到，有特殊情况须提前请假。</p>
              </div>

              <div className="mt-10 flex justify-between items-end">
                <div>
                  <p className="mb-1">
                    <strong>部门：</strong>
                    <span className="border-b border-gray-800 px-2 min-w-[120px] inline-block">
                      {issuerValue || ' '}
                    </span>
                  </p>
                </div>
                <div>
                  <p>
                    <span className="border-b border-gray-800 px-2 min-w-[80px] inline-block text-center">
                      {issueDateValue ? issueDateValue.format('YYYY') : '____'}
                    </span>
                    年
                    <span className="border-b border-gray-800 px-2 min-w-[40px] inline-block text-center">
                      {issueDateValue ? issueDateValue.format('MM') : '__'}
                    </span>
                    月
                    <span className="border-b border-gray-800 px-2 min-w-[40px] inline-block text-center">
                      {issueDateValue ? issueDateValue.format('DD') : '__'}
                    </span>
                    日
                  </p>
                </div>
              </div>
            </div>
          </Card>

          {/* 签到表预览 */}
          {signInPages.map((pageNames, pageIdx) => (
            <Card key={pageIdx} className="mt-6">
              <div className="max-w-3xl mx-auto p-8 text-sm leading-relaxed">
                <h2 className="text-center text-xl font-bold mb-6">
                  培训签到表{signInPages.length > 1 ? `（第${pageIdx + 1}/${signInPages.length}张）` : ''}
                </h2>

                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <strong>日期：</strong>
                    <span className="border-b border-gray-800 px-2">{dateStr}</span>
                  </div>
                  <div>
                    <strong>受训部门：</strong>
                    <span className="border-b border-gray-800 px-2">{traineeDepts[0] || deptValue || ' '}</span>
                  </div>
                  <div>
                    <strong>培训方式：</strong>
                    <span className="border-b border-gray-800 px-2">{trainingMethodValue || ' '}</span>
                  </div>
                  <div>
                    <strong>应受训人数：</strong>
                    <span className="border-b border-gray-800 px-2">{previewNames.length}人</span>
                  </div>
                  <div>
                    <strong>培训时间：</strong>
                    <span className="border-b border-gray-800 px-2">{timeStr || ' '}</span>
                  </div>
                  <div>
                    <strong>培训地点：</strong>
                    <span className="border-b border-gray-800 px-2">{locationValue || ' '}</span>
                  </div>
                </div>
                <div className="mb-4">
                  <strong>培训题目/内容概要：</strong>
                  <span className="border-b border-gray-800 px-2">{topicStr || ' '}</span>
                </div>
                <div className="mb-4">
                  <strong>授课人：</strong>
                  <span className="border-b border-gray-800 px-2">{trainerValue || ' '}</span>
                </div>

                <table className="w-full border-collapse border border-gray-800 text-center">
                  <thead>
                    <tr className="bg-gray-100">
                      <th className="border border-gray-800 p-2 w-16">序号</th>
                      <th className="border border-gray-800 p-2">姓名</th>
                      <th className="border border-gray-800 p-2 w-24">签到</th>
                      <th className="border border-gray-800 p-2 w-16">序号</th>
                      <th className="border border-gray-800 p-2">姓名</th>
                      <th className="border border-gray-800 p-2 w-24">签到</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: Math.max(15, Math.ceil(pageNames.length / 2)) }).map((_, rowIdx) => {
                      const leftIdx = rowIdx
                      const rightIdx = rowIdx + 15
                      return (
                        <tr key={rowIdx}>
                          <td className="border border-gray-800 p-2">{leftIdx + 1 + pageIdx * 30}</td>
                          <td className="border border-gray-800 p-2">{pageNames[leftIdx] || ''}</td>
                          <td className="border border-gray-800 p-2"></td>
                          <td className="border border-gray-800 p-2">{rightIdx + 1 + pageIdx * 30}</td>
                          <td className="border border-gray-800 p-2">{pageNames[rightIdx] || ''}</td>
                          <td className="border border-gray-800 p-2"></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          ))}

          {/* 培训效果评估表预览 */}
          <Card className="mt-6">
            <div className="max-w-3xl mx-auto p-4 text-sm leading-relaxed">
              <div className="text-xs text-gray-500 mb-1">QR.SOP.PM.003/18（格式） P8/12</div>
              <div className="text-center text-lg font-bold mb-1">丽珠集团新北江制药股份有限公司</div>
              <div className="text-center text-xl font-bold mb-6">培训效果评估表</div>

              <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                <tbody>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="font-bold bg-gray-50">培训主题：{topicStr}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={3} className="bg-gray-50">培训时间：{dateStr}</td>
                    <td style={TD_LABEL} colSpan={2} className="bg-gray-50">学时：{evalDurationHours}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={3} className="bg-gray-50">培训方式：{trainingMethodValue || '□面授  □函授  □远程教育  □自学  □其他方式'}</td>
                    <td style={TD_LABEL} colSpan={2} className="bg-gray-50">□考试</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">培训人员：□讲师/专家/官员等    {trainerValue}</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">应出席 {previewNames.length} 人；实际出席 ___ 人；缺席 ___ 人。</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">培训教材：{deptValue} / {traineeDepts.join('、')} / {previewNames.length}人</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, height: '48px' }} colSpan={5} className="bg-gray-50">缺席人员处理方式：</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">考核方式：□ 笔试    □ 口试   □ 实操   □ 写总结</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">考核结果：□合格 ___ 人；□不合格 ___ 人；缺考 ___ 人。</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, height: '36px' }} colSpan={5} className="bg-gray-50">缺考人员处理方式和原因：</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">综合评分：□优秀 ___ 人；□合格 ___ 人；□不合格 ___ 人。</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, height: '24px' }} colSpan={5} className="bg-gray-50"></td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, height: '48px' }} colSpan={5} className="bg-gray-50">培训效果评估及结论：</td>
                  </tr>
                  <tr>
                    <td style={TD_LABEL} colSpan={5} className="bg-gray-50">培训组织人/日期：</td>
                  </tr>
                  <tr>
                    <td style={{ ...TD_LABEL, height: '36px' }} colSpan={5} className="bg-gray-50">备注：</td>
                  </tr>
                </tbody>
              </table>
            </div>
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
