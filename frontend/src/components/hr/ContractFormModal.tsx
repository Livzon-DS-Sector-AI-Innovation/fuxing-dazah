'use client'

// 合同表单弹窗：录入（mode=create）/ 编辑（edit）/ 续签办理（renew）三模式。
// 期限按签订次数由后端自动计算，前端只做「第 N 份 → 期限」提示，不提供期限输入。

import { useMemo, useState } from 'react'
import { App, Alert, DatePicker, Form, Input, Modal, Select } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { createLaborContract, renewLaborContract, updateLaborContract } from '@/actions/hr'
import type { LaborContract } from '@/types/hr'

export type ContractFormMode = 'create' | 'edit' | 'renew'

interface Props {
  open: boolean
  mode: ContractFormMode
  contract?: LaborContract | null
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  employee_option?: { value: string; label: string }
  start_date?: Dayjs
  sign_date?: Dayjs
  position?: string
  remark?: string
}

/** 签订次数 → 期限提示（与后端 term_for_seq 同口径） */
function termHint(seqNo: number): string {
  if (seqNo <= 1) return '3 年'
  if (seqNo === 2) return '6 年'
  return '无固定期限'
}

const TITLE: Record<ContractFormMode, string> = {
  create: '录入劳动合同',
  edit: '编辑合同',
  renew: '办理续签',
}

export default function ContractFormModal({ open, mode, contract, onClose, onSaved }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)

  // 员工下拉：录入时远程搜索在职员工（与提醒配置卡的口径一致）
  const [employeeOptions, setEmployeeOptions] = useState<{ value: string; label: string }[]>([])
  const [employeeSearching, setEmployeeSearching] = useState(false)

  const isCreate = mode === 'create'
  const isRenew = mode === 'renew'

  // 续签：新合同次序 = 原次序 + 1，起始日默认原到期日次日
  const nextSeq = (contract?.seq_no ?? 0) + 1
  const renewDefaultStart = useMemo(() => {
    if (mode !== 'renew' || !contract?.end_date) return undefined
    return dayjs(contract.end_date).add(1, 'day')
  }, [mode, contract?.end_date])

  const searchEmployees = async (keyword: string) => {
    setEmployeeSearching(true)
    try {
      const { fetchEmployeesAction } = await import('@/actions/hr')
      const d = await fetchEmployeesAction({
        status: '在职',
        keyword: keyword || undefined,
        page: 1,
        page_size: 20,
      })
      setEmployeeOptions(
        d.data.map((e) => ({
          value: e.employee_number,
          label: `${e.name}（${e.employee_number || '-'} · ${e.department || '-'}）`,
        })),
      )
    } catch { /* 静默：保留下拉里的上一次结果 */ }
    finally { setEmployeeSearching(false) }
  }

  const submit = async (values: FormValues) => {
    setSaving(true)
    try {
      if (isCreate) {
        await createLaborContract({
          employee_number: values.employee_option?.value || '',
          start_date: values.start_date!.format('YYYY-MM-DD'),
          sign_date: values.sign_date ? values.sign_date.format('YYYY-MM-DD') : null,
          remark: values.remark?.trim() || null,
        })
      } else if (isRenew && contract) {
        await renewLaborContract(contract.id, {
          start_date: values.start_date!.format('YYYY-MM-DD'),
          sign_date: values.sign_date ? values.sign_date.format('YYYY-MM-DD') : null,
        })
      } else if (contract) {
        await updateLaborContract(contract.id, {
          start_date: values.start_date?.format('YYYY-MM-DD'),
          sign_date: values.sign_date?.format('YYYY-MM-DD'),
          position: values.position?.trim() || undefined,
          remark: values.remark?.trim() || undefined,
        })
      }
      message.success(isCreate ? '合同已录入' : isRenew ? '续签已办理' : '已保存')
      onSaved()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={contract ? `${TITLE[mode]}：${contract.name}` : TITLE[mode]}
      okText={isRenew ? '确认续签' : '保存'}
      confirmLoading={saving}
      onCancel={onClose}
      destroyOnHidden
      onOk={() => { void form.validateFields().then((v) => submit(v as FormValues)) }}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        initialValues={
          isCreate
            ? {}
            : {
                start_date: contract?.start_date ? dayjs(contract.start_date) : undefined,
                sign_date: contract?.sign_date ? dayjs(contract.sign_date) : undefined,
                position: contract?.position || undefined,
                remark: contract?.remark || undefined,
              }
        }
      >
        {isCreate && (
          <Form.Item
            name="employee_option"
            label="员工"
            rules={[{ required: true, message: '请选择员工' }]}
          >
            <Select
              showSearch
              filterOption={false}
              options={employeeOptions}
              loading={employeeSearching}
              placeholder="输入姓名/工号搜索在职员工"
              onSearch={(v) => void searchEmployees(v)}
              onOpenChange={(o) => { if (o && employeeOptions.length === 0) void searchEmployees('') }}
              notFoundContent={employeeSearching ? '搜索中…' : undefined}
            />
          </Form.Item>
        )}

        {isRenew && contract && (
          <Alert
            className="!mb-4"
            type="info"
            showIcon
            message={`本次为第 ${nextSeq} 份合同，期限自动带出：${termHint(nextSeq)}（自新合同起始日起算）`}
          />
        )}

        <Form.Item
          name="start_date"
          label="合同起始日"
          rules={[{ required: isCreate || isRenew, message: '请选择起始日' }]}
          extra={isCreate ? '期限自起始日起算（第 1 次 3 年、第 2 次 6 年、第 3 次起无固定）' : undefined}
        >
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="sign_date" label="实际签订日（选填，默认同起始日）">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        {mode === 'edit' && (
          <Form.Item name="position" label="岗位（快照）">
            <Input maxLength={64} placeholder="留空不修改" />
          </Form.Item>
        )}

        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={500} placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
