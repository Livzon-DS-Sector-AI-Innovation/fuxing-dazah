'use client'

// 发起离职办理：选员工（在职 / 试用期）→ 带出档案信息 → 离职日期 / 类型 / 原因 / 是否递交申请。
// 重点岗位默认要求离岗体检（可改）：建单后在办理抽屉登记体检完成，才能发起审批。

import { useRef, useState } from 'react'
import { App as AntdApp, DatePicker, Form, Input, Modal, Select, Switch } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { createOffboardingCase, fetchEmployeesAction } from '@/actions/hr'
import { OFFBOARDING_CASE_TYPE_OPTIONS } from '@/lib/hr'
import type { Employee } from '@/types/hr'

interface FormValues {
  employee_id: string
  offboarding_date: Dayjs
  offboarding_type: string
  reason?: string
  application_submitted: boolean
  health_check_required: boolean
  remark?: string
}

export default function OffboardingNewCaseModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (caseId: string) => void
}) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()
  const [options, setOptions] = useState<{ value: string; label: string; employee: Employee }[]>([])
  const [searching, setSearching] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selected, setSelected] = useState<Employee | null>(null)
  // 请求序号：慢响应回来时若已有更新的搜索，丢弃旧结果（必须是 ref，普通对象每次渲染都会重置）
  const searchSeq = useRef(0)

  const search = async (keyword: string) => {
    const seq = ++searchSeq.current
    setSearching(true)
    try {
      const res = await fetchEmployeesAction({ keyword: keyword || undefined, page: 1, page_size: 50 })
      if (seq !== searchSeq.current) return // 过期响应丢弃
      setOptions((res.data || [])
        .filter((e: Employee) => !['离职', '待审批'].includes(e.status))
        .map((e: Employee) => ({
          value: e.id,
          label: `${e.employee_number} ${e.name}（${e.department} / ${e.position || '-'}${e.status === '试用期' ? ' · 试用期' : ''}）`,
          employee: e,
        })))
    } catch (err) {
      if (seq === searchSeq.current) message.error(err instanceof Error ? err.message : '搜索员工失败')
    } finally {
      if (seq === searchSeq.current) setSearching(false)
    }
  }

  const handleSubmit = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return // 校验失败：表单已就地提示
    }
    setSubmitting(true)
    try {
      const res = await createOffboardingCase({
        employee_id: values.employee_id,
        offboarding_date: values.offboarding_date.format('YYYY-MM-DD'),
        offboarding_type: values.offboarding_type,
        reason: values.reason?.trim() || undefined,
        application_submitted: values.application_submitted,
        health_check_required: values.health_check_required,
        remark: values.remark?.trim() || undefined,
      })
      message.success(`已创建离职办理（${res.data?.case_no || ''}）`)
      onCreated(res.data?.id)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '发起失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="发起离职办理"
      open={open}
      onCancel={onClose}
      afterOpenChange={(opened) => {
        if (!opened) return
        form.resetFields()
        setSelected(null)
        void search('')
      }}
      onOk={() => void handleSubmit()}
      okText="创建办理单"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
      width={560}
      // 表单项较多：内容区内部滚动，底部「创建办理单」始终可见
      styles={{ body: { maxHeight: "62vh", overflowY: "auto", paddingRight: 4 } }}
    >
      <Form<FormValues> form={form} layout="vertical" initialValues={{ offboarding_type: '辞职', application_submitted: true }}>
        <Form.Item
          name="employee_id"
          label="选择员工（输入姓名 / 工号搜索）"
          rules={[{ required: true, message: '请选择员工' }]}
        >
          <Select
            showSearch
            filterOption={false}
            loading={searching}
            onSearch={(v) => void search(v.trim())}
            onFocus={() => { if (options.length === 0) void search('') }}
            onChange={(id) => {
              const employee = options.find((o) => o.value === id)?.employee ?? null
              setSelected(employee)
              // 选中员工时带出默认值：重点岗位默认要体检；离职日期按提前天数规则给个合规起点
              const probation = employee?.status === '试用期'
              form.setFieldsValue({
                health_check_required: Boolean(employee?.is_key_position),
                offboarding_date: dayjs().add(probation ? 7 : 30, 'day'),
              })
            }}
            options={options}
            placeholder="仅在职 / 试用期员工可发起"
            notFoundContent={searching ? '搜索中…' : '无匹配员工'}
          />
        </Form.Item>
        {selected && (
          <div className="mb-3 rounded-[var(--rounded-md)] bg-[var(--color-surface)] px-3 py-2 text-[13px] leading-[1.6] text-[var(--color-slate)]">
            <div>
              {selected.department} / {selected.position || '-'}
              {selected.level ? ` · ${selected.level}` : ''}
            </div>
            <div>
              {selected.status === '试用期'
                ? '试用期员工按制度应提前 3 天发起。'
                : '转正员工按制度应提前 1 个月发起。'}
              {selected.is_key_position
                ? ' 该员工为重点岗位：须先完成离岗体检登记才能发起审批。'
                : ' 非重点岗位，无需离岗体检。'}
            </div>
          </div>
        )}
        <Form.Item
          name="offboarding_date"
          label="离职日期"
          rules={[{ required: true, message: '请选择离职日期' }]}
        >
          <DatePicker className="w-full" />
        </Form.Item>
        <Form.Item name="offboarding_type" label="离职类型" rules={[{ required: true }]}>
          <Select options={OFFBOARDING_CASE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
        </Form.Item>
        <Form.Item name="reason" label="离职原因" extra="将带入离职证明正文">
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
        <Form.Item name="application_submitted" label="是否已递交离职申请" valuePropName="checked">
          <Switch checkedChildren="已递交" unCheckedChildren="未递交" />
        </Form.Item>
        <Form.Item
          name="health_check_required"
          label="需完成离岗体检"
          valuePropName="checked"
          extra="开启后，须先登记离岗体检完成才能发起审批"
        >
          <Switch checkedChildren="需要" unCheckedChildren="不需要" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}
