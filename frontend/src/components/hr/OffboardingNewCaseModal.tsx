'use client'

// 发起离职办理：选员工（在职 / 试用期）→ 带出档案信息 → 离职日期 / 类型 / 原因 / 是否递交申请。
// 重点岗位默认要求离岗体检（可改）：发起后在办理抽屉登记体检完成，才能提交部门审批。
// 从离职台账的某一行发起时带 prefill：人、离职日期、离职类型都从台账行带出，不用重新填；
// 台账行来自飞书同步的，离职日期与类型只读（离职台账以飞书表为准，要改去飞书表改）。
// 表单的值全部走 initialValues：每次打开都是新挂载的表单实例，不靠「打开后回填」。

import { useEffect, useRef, useState } from 'react'
import { App as AntdApp, DatePicker, Form, Input, Modal, Radio, Select } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { createOffboardingCase, fetchEmployeesAction } from '@/actions/hr'
import { OFFBOARDING_CASE_TYPE_OPTIONS } from '@/lib/hr'
import type { Employee } from '@/types/hr'

interface FormValues {
  employee_id: string
  offboarding_date: Dayjs
  offboarding_type?: string
  reason?: string
  application_submitted: boolean
  health_check_required: boolean
  remark?: string
}

/** 发起时带出的信息：从离职台账行发起时带台账行；从员工档案发起时只有员工 */
export interface OffboardingCasePrefill {
  /** 台账行 id；没有台账行（从员工档案发起）时为空，离职日期与类型可以直接改 */
  departureRecordId?: string | null
  employeeId: string
  employeeNumber: string
  /** 下拉框里显示的那一行（工号 姓名（部门 / 岗位）） */
  label: string
  /** 空串 = 不带日期，按提前天数规则给默认值 */
  offboardingDate: string
  offboardingType: string
  /** 台账行来自飞书同步：离职日期与类型只读 */
  ledgerSynced: boolean
}

const YES_NO = [
  { label: '已递交', value: true },
  { label: '未递交', value: false },
]
const NEED_NO = [
  { label: '需要', value: true },
  { label: '不需要', value: false },
]

export default function OffboardingNewCaseModal({
  open,
  prefill = null,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (caseId: string) => void
  prefill?: OffboardingCasePrefill | null
}) {
  // 不渲染 = 完全卸载：下次打开是全新的表单和本地状态
  if (!open) return null
  return <NewCaseForm prefill={prefill} onClose={onClose} onCreated={onCreated} />
}

function NewCaseForm({
  prefill,
  onClose,
  onCreated,
}: {
  prefill: OffboardingCasePrefill | null
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

  useEffect(() => {
    let cancelled = false
    if (prefill) {
      // 台账行带出：是否重点岗位按档案再取一次，决定体检查不查（档案已被同步软删的取不到，按不需要处理）
      fetchEmployeesAction({ keyword: prefill.employeeNumber, page: 1, page_size: 5 })
        .then((res) => {
          const employee = (res.data || []).find((e: Employee) => e.id === prefill.employeeId) ?? null
          if (cancelled || !employee) return
          setSelected(employee)
          const probation = employee.status === '试用期'
          form.setFieldsValue({
            health_check_required: Boolean(employee.is_key_position),
            // 没带日期（从员工档案发起）时按提前天数规则给默认值
            ...(!prefill.offboardingDate ? { offboarding_date: dayjs().add(probation ? 7 : 30, 'day') } : {}),
          })
        })
        .catch(() => {})
    } else {
      // 首屏员工选项：写状态都在 search 里的 await 之后，不在 effect 里同步触发级联渲染
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void search('')
    }
    return () => {
      cancelled = true
      searchSeq.current += 1 // 关掉弹窗后，在途的搜索结果不再写回
    }
    // form / message 是稳定实例，刻意不进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 选中员工时带出默认值：重点岗位默认要体检；离职日期按提前天数规则给个合规起点 */
  const applyEmployeeDefaults = (employee: Employee | null) => {
    setSelected(employee)
    const probation = employee?.status === '试用期'
    form.setFieldsValue({
      health_check_required: Boolean(employee?.is_key_position),
      offboarding_date: dayjs().add(probation ? 7 : 30, 'day'),
    })
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
        // 台账行带出时后端以台账为准，这里的类型只是表单必填项
        offboarding_type: prefill?.ledgerSynced ? prefill.offboardingType : values.offboarding_type,
        reason: values.reason?.trim() || undefined,
        application_submitted: values.application_submitted,
        health_check_required: values.health_check_required,
        remark: values.remark?.trim() || undefined,
        ...(prefill?.departureRecordId ? { departure_record_id: prefill.departureRecordId } : {}),
      })
      message.success(`已发起（${res.data?.case_no || ''}），下一步：提交部门审批`)
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
      open
      onCancel={onClose}
      onOk={() => void handleSubmit()}
      okText="发起"
      cancelText="取消"
      confirmLoading={submitting}
      width={560}
      // 表单项较多：内容区内部滚动，底部「发起」始终可见
      styles={{ body: { maxHeight: '62vh', overflowY: 'auto', paddingRight: 4 } }}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        initialValues={{
          ...(prefill
            ? {
              employee_id: prefill.employeeId,
              ...(prefill.offboardingDate ? { offboarding_date: dayjs(prefill.offboardingDate) } : {}),
            }
            : {}),
          offboarding_type: prefill && !prefill.ledgerSynced ? prefill.offboardingType : '辞职',
          application_submitted: true,
          health_check_required: false,
        }}
      >
        <Form.Item
          name="employee_id"
          label="员工"
          rules={[{ required: true, message: '请选择员工' }]}
          extra={prefill ? (prefill.departureRecordId ? '从离职台账带出' : '来自员工档案') : undefined}
        >
          <Select
            showSearch
            disabled={!!prefill}
            filterOption={false}
            loading={searching}
            onSearch={(v) => void search(v.trim())}
            onFocus={() => { if (!prefill && options.length === 0) void search('') }}
            onChange={(id) => applyEmployeeDefaults(options.find((o) => o.value === id)?.employee ?? null)}
            options={prefill
              ? [{ value: prefill.employeeId, label: prefill.label }]
              : options.map(({ value, label }) => ({ value, label }))}
            placeholder="输入姓名 / 工号搜索；仅在职、试用期员工可发起"
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
                ? ' 该员工为重点岗位：须先完成离岗体检登记才能提交审批。'
                : ' 非重点岗位，无需离岗体检。'}
            </div>
          </div>
        )}
        <Form.Item
          name="offboarding_date"
          label="离职日期"
          rules={[{ required: true, message: '请选择离职日期' }]}
          extra={prefill?.ledgerSynced ? '来自飞书离职表，以飞书表为准；要改请到飞书表修改，整点同步后自动更新' : undefined}
        >
          <DatePicker className="w-full" disabled={!!prefill?.ledgerSynced} />
        </Form.Item>
        {prefill?.ledgerSynced ? (
          <Form.Item label="离职类型" extra="来自飞书离职表，以飞书表为准">
            <Input readOnly value={prefill.offboardingType} />
          </Form.Item>
        ) : (
          <Form.Item name="offboarding_type" label="离职类型" rules={[{ required: true, message: '请选择离职类型' }]}>
            <Select options={OFFBOARDING_CASE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
        )}
        <Form.Item name="reason" label="离职原因" extra="将写入离职证明正文">
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
        <Form.Item name="application_submitted" label="是否已递交离职申请">
          <Radio.Group optionType="button" options={YES_NO} />
        </Form.Item>
        <Form.Item
          name="health_check_required"
          label="需完成离岗体检"
          extra="开启后，须先登记离岗体检完成才能提交审批"
        >
          <Radio.Group optionType="button" options={NEED_NO} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}
