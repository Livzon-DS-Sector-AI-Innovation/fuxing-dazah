'use client'

import { useEffect, useRef, useState } from 'react'
import dayjs, { type Dayjs } from 'dayjs'
import { App, Checkbox, DatePicker, Form, Input, Modal, Select, TimePicker } from 'antd'
import type { Candidate, Interview } from '@/types/hr'
import { createInterview, updateInterview, fetchEmployeesAction } from '@/actions/hr'

// 面试轮次链：新建时按候选人已有轮次自动推下一轮（初试→复试→终试）
const NEXT_ROUND: Record<string, string> = { '初试': '复试', '复试': '终试' }

function nextRoundType(existingTypes: string[]) {
  const held = new Set(existingTypes)
  let t = '初试'
  while (held.has(t) && NEXT_ROUND[t]) t = NEXT_ROUND[t]
  return t
}

interface InterviewScheduleModalProps {
  open: boolean
  /** 编辑已有面试；null = 新建（新建需传 candidate）。面试总览行带 candidate_name 用于标题 */
  editing: (Interview & { candidate_name?: string | null }) | null
  /** 新建时的候选人（取 candidate_id / job_requirement_id / 标题展示）；编辑可缺省 */
  candidate?: Candidate | null
  /** 候选人已有轮次（父组件应排除已取消的面试），新建时智能默认下一轮 */
  existingTypes?: string[]
  onCancel: () => void
  /** 保存成功后的回调（父组件关弹窗 + 刷新列表） */
  onSaved: () => void
}

/** 安排/编辑面试的共享弹窗：候选人详情与面试总览复用。
 *  面试官时段冲突 → 二次确认后 force_conflict 强制保存；日历同步失败提示补建。 */
export default function InterviewScheduleModal({
  open, editing, candidate, existingTypes = [], onCancel, onSaved,
}: InterviewScheduleModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  // 面试官选择器：远程搜索在职员工（值存姓名——飞书日程/冲突检测按姓名匹配）
  const [interviewerOptions, setInterviewerOptions] = useState<{ value: string; label: string }[]>([])
  const [interviewerSearching, setInterviewerSearching] = useState(false)
  const interviewerSeq = useRef(0)
  const searchInterviewerOptions = async (keyword: string) => {
    const seq = ++interviewerSeq.current
    setInterviewerSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== interviewerSeq.current) return  // 过期响应丢弃
      setInterviewerOptions(((d?.data as any)?.items || (d?.data as any) || []).map((e: any) => ({
        value: e.name,
        label: `${e.name}（${e.department || ''}）`,
      })))
    } catch (err: any) {
      message.error(err?.message || '员工搜索失败，请稍后重试')
    }
    finally { if (seq === interviewerSeq.current) setInterviewerSearching(false) }
  }

  // 打开即按模式预填：新建给智能默认（下一轮 + 下一个整点 + 默认 1 小时），编辑回填原值
  useEffect(() => {
    if (!open) return
    if (editing) {
      // DatePicker/TimePicker 需要 dayjs 对象；直接塞字符串日期框显示为空
      const [eh, em] = (editing.end_time || '').split(':').map(Number)
      form.setFieldsValue({
        ...editing,
        interview_start: editing.interview_date
          ? dayjs(`${editing.interview_date} ${editing.start_time || '09:00'}`)
          : undefined,
        end_time: editing.end_time ? dayjs().hour(eh || 0).minute(em || 0).second(0) : undefined,
        create_calendar_event: false,
      })
    } else {
      form.resetFields()
      const start = dayjs().add(1, 'hour').minute(0).second(0)
      form.setFieldsValue({
        interview_type: nextRoundType(existingTypes),
        interview_start: start,
        end_time: start.add(1, 'hour'),
      })
    }
    // existingTypes 只在打开瞬间参与默认值计算，无需作为依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing])

  // 选了开始时间且还没填结束时间 → 默认 1 小时后；用户已手填过则不动
  const handleStartChange = (val: Dayjs | null) => {
    if (val && !form.getFieldValue('end_time')) {
      form.setFieldsValue({ end_time: val.add(1, 'hour') })
    }
  }

  const buildPayload = (v: Record<string, any>, forceConflict = false) => {
    // 面试开始 = 日期+钟点合一的 DateTimePicker；结束只取钟点
    const start: Dayjs | undefined = v.interview_start
    const rest: Record<string, any> = { ...v }
    delete rest.interview_start  // DateTimePicker 值拆成 interview_date/start_time 后不再透传
    return {
      ...rest,
      interview_date: start ? start.format('YYYY-MM-DD') : undefined,
      start_time: start ? start.format('HH:mm') : undefined,
      end_time: v.end_time ? v.end_time.format('HH:mm') : undefined,
      force_conflict: forceConflict || undefined,
    }
  }

  const doSave = (payload: Record<string, any>) => {
    return editing
      ? updateInterview(editing.id, payload)
      : createInterview({ ...payload, candidate_id: candidate!.id, job_requirement_id: candidate?.job_requirement_id || undefined })
  }

  const handleOk = async () => {
    if (!editing && !candidate) { message.error('缺少候选人信息，无法保存'); return }
    const v = await form.validateFields()
    const payload = buildPayload(v)
    setSaving(true)
    try {
      let res: any
      try {
        res = await doSave(payload)
      } catch (err: any) {
        // 面试官时段冲突：确认后带 force_conflict 强制保存
        if (err?.message?.includes('冲突')) {
          const force = await new Promise<boolean>((resolve) => {
            Modal.confirm({
              title: '面试官时段冲突',
              content: `${err.message}。仍要保存这场面试吗？`,
              okText: '仍然保存', cancelText: '返回修改',
              onOk: () => resolve(true),
              onCancel: () => resolve(false),
            })
          })
          if (!force) return
          res = await doSave({ ...payload, force_conflict: true })
        } else {
          throw err
        }
      }
      message.success(editing ? '面试已更新' : '面试已安排')
      // 含逐字稿/备注的保存会后台生成胜任度报告（LLM 最长 90s，不阻塞响应）
      if ((res?.data?.transcript_text || res?.data?.notes || '').trim()) {
        message.info('胜任度报告后台生成中，稍后刷新查看')
      }
      // 日历同步失败不再静默：面试已保存成功，但提示用户可编辑补建
      if (res?.data?.calendar_sync_error) {
        message.warning(res.data.calendar_sync_error + '，可稍后在编辑中勾选「补建飞书日程」')
      }
      onSaved()
    } catch (err: any) { message.error(err.message || '操作失败') }
    finally { setSaving(false) }
  }

  const title = editing
    ? `编辑面试${editing.candidate_name ? ` — ${editing.candidate_name}` : ''}`
    : `安排面试${candidate ? ` — ${candidate.name}` : ''}`

  return (
    <Modal title={title} open={open} onCancel={onCancel} onOk={handleOk} confirmLoading={saving}>
      <Form form={form} layout="vertical">
        <Form.Item name="interview_type" label="面试类型" initialValue="初试" rules={[{ required: true, message: '请选择面试类型' }]}>
          <Select options={[{ label: '初试', value: '初试' }, { label: '复试', value: '复试' }, { label: '终试', value: '终试' }]} />
        </Form.Item>
        <Form.Item name="interview_start" label="面试开始时间" rules={[{ required: true, message: '请选择面试开始时间' }]}>
          <DatePicker showTime={{ format: 'HH:mm', minuteStep: 5 }} format="YYYY-MM-DD HH:mm"
            style={{ width: '100%' }} onChange={handleStartChange} />
        </Form.Item>
        <Form.Item name="end_time" label="结束时间" dependencies={['interview_start']}
          rules={[{
            validator: (_, value) => {
              if (!value) return Promise.resolve()
              const start: Dayjs | undefined = form.getFieldValue('interview_start')
              if (start && !value.isAfter(start, 'minute')) {
                return Promise.reject(new Error('结束时间必须晚于开始时间'))
              }
              return Promise.resolve()
            },
          }]}>
          <TimePicker format="HH:mm" minuteStep={5} style={{ width: '100%' }} placeholder="不填默认 1 小时" />
        </Form.Item>
        <Form.Item name="interviewer" label="面试官" rules={[{ required: true, message: '请选择面试官' }]}>
          <Select
            showSearch
            filterOption={false}
            onSearch={searchInterviewerOptions}
            options={interviewerOptions}
            loading={interviewerSearching}
            placeholder="输入姓名搜索，或直接从列表选择"
            allowClear
            onOpenChange={(open) => { if (open && interviewerOptions.length === 0) void searchInterviewerOptions('') }}
          />
        </Form.Item>
        <Form.Item name="location" label="面试地点"><Input placeholder="会议室/线上链接等" /></Form.Item>
        {(!editing || !editing.calendar_event_id) && (
          <Form.Item name="create_calendar_event" label="飞书日历" valuePropName="checked" initialValue={false}>
            <Checkbox>{editing ? '补建飞书日历日程（此前未同步成功）' : '同步创建飞书日历日程'}</Checkbox>
          </Form.Item>
        )}
        {editing && (
          <>
            <Form.Item name="status" label="状态">
              <Select options={[{ label: '待安排', value: '待安排' }, { label: '已安排', value: '已安排' }, { label: '已完成', value: '已完成' }, { label: '已取消', value: '已取消' }]} />
            </Form.Item>
            <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
          </>
        )}
      </Form>
    </Modal>
  )
}
