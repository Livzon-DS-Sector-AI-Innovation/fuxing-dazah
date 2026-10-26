'use client'

import { useState } from 'react'
import { Alert, App, Button, DatePicker, Form, Input, Modal, Select } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { createCapa, updateCapa } from '@/actions/qa-deviation'
import {
  CAPA_ACTION_STATUS_LABEL,
  CAPA_ACTION_TYPE_LABEL,
  CAPA_SEVERITY_LABEL,
  EFFECT_METHOD_LABEL,
  type CapaActionItem,
  type CapaActionStatus,
  type CapaActionType,
  type CapaCreateInput,
  type CapaDetail,
  type CapaSeverity,
  type EffectMethod,
} from '@/types/qa-deviation'
import { actionError, toOptions } from '../deviation/shared'

interface ActionRow {
  id?: string
  content?: string
  action_type: CapaActionType
  department_name?: string
  owner_name?: string
  planned_date?: Dayjs | null
  actual_date?: string | null
  status: CapaActionStatus
  note?: string | null
}

interface CapaFormValues {
  severity: CapaSeverity
  summary: string
  responsible_department_name?: string
  planned_completion_date?: Dayjs | null
  effect_method?: EffectMethod | null
  effect_plan?: string
  effect_due_date?: Dayjs | null
  remark?: string
  actions?: ActionRow[]
}

const SEVERITY_OPTIONS = toOptions(CAPA_SEVERITY_LABEL)
const ACTION_TYPE_OPTIONS = toOptions(CAPA_ACTION_TYPE_LABEL)
const ACTION_STATUS_OPTIONS = toOptions(CAPA_ACTION_STATUS_LABEL)
const EFFECT_METHOD_OPTIONS = toOptions(EFFECT_METHOD_LABEL)

function toRow(action: CapaActionItem): ActionRow {
  return {
    id: action.id,
    content: action.content,
    action_type: action.action_type,
    department_name: action.department_name ?? undefined,
    owner_name: action.owner_name ?? undefined,
    planned_date: action.planned_date ? dayjs(action.planned_date) : null,
    actual_date: action.actual_date ?? null,
    status: action.status,
    note: action.note ?? null,
  }
}

function initialValues(
  editing: CapaDetail | null | undefined,
  deviation: { description?: string; department_name?: string | null },
): Partial<CapaFormValues> {
  if (editing) {
    return {
      severity: editing.severity,
      summary: editing.summary,
      responsible_department_name: editing.responsible_department_name ?? undefined,
      planned_completion_date: editing.planned_completion_date ? dayjs(editing.planned_completion_date) : null,
      effect_method: editing.effect_method,
      effect_plan: editing.effect_plan ?? undefined,
      effect_due_date: editing.effect_due_date ? dayjs(editing.effect_due_date) : null,
      remark: editing.remark ?? undefined,
      actions: editing.actions.map(toRow),
    }
  }
  return {
    severity: 'minor',
    summary: deviation.description ? `事件描述：${deviation.description}\n\nCAPA 要求：\n1、` : '',
    responsible_department_name: deviation.department_name ?? undefined,
    effect_method: 'tracking_month',
    actions: [{ action_type: 'corrective', status: 'pending' }],
  }
}

/** 发起 / 编辑 CAPA；parent 传入时为「追加 CAPA」，编号自动加后缀。 */
export function CapaFormModal({
  open,
  onClose,
  onSaved,
  deviation,
  parent,
  editing,
}: {
  open: boolean
  onClose: () => void
  onSaved: (capa: CapaDetail) => void
  deviation: { id: string; deviation_no: string; description?: string; department_name?: string | null }
  parent?: { id: string; capa_no: string } | null
  editing?: CapaDetail | null
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<CapaFormValues>()
  const [submitting, setSubmitting] = useState(false)

  const handleOk = async () => {
    const values = await form.validateFields()
    const actions = (values.actions ?? [])
      .filter((row) => row.content && row.content.trim())
      .map((row) => ({
        content: row.content!.trim(),
        action_type: row.action_type,
        department_name: row.department_name?.trim() || null,
        owner_name: row.owner_name?.trim() || null,
        planned_date: row.planned_date ? row.planned_date.format('YYYY-MM-DD') : null,
        actual_date: row.actual_date ?? null,
        status: row.status ?? 'pending',
        note: row.note ?? null,
      }))
    const base = {
      severity: values.severity,
      summary: values.summary.trim(),
      responsible_department_name: values.responsible_department_name?.trim() || null,
      planned_completion_date: values.planned_completion_date ? values.planned_completion_date.format('YYYY-MM-DD') : null,
      effect_method: values.effect_method ?? null,
      effect_plan: values.effect_plan?.trim() || null,
      effect_due_date: values.effect_due_date ? values.effect_due_date.format('YYYY-MM-DD') : null,
      remark: values.remark?.trim() || null,
      actions,
    }
    setSubmitting(true)
    try {
      const result = editing
        ? await updateCapa(editing.id, base)
        : await createCapa({ ...base, deviation_id: deviation.id, parent_capa_id: parent?.id ?? null } satisfies CapaCreateInput)
      if (!result.success || !result.data) {
        message.error(actionError(result))
        return
      }
      message.success(editing ? 'CAPA 已更新' : `CAPA ${result.data.capa_no} 已发起`)
      form.resetFields()
      onSaved(result.data)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={editing ? `编辑 ${editing.capa_no}` : parent ? `追加 CAPA（上游 ${parent.capa_no}）` : `发起 CAPA · ${deviation.deviation_no}`}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText={editing ? '保存' : '发起 CAPA'}
      cancelText="取消"
      confirmLoading={submitting}
      width={920}
      destroyOnHidden
    >
      {parent && (
        <Alert
          type="warning"
          showIcon
          title="上游 CAPA 有效性评估为无效，追加 CAPA 需针对首次措施失效的原因制定更有效的措施。"
          style={{ marginBottom: 16 }}
        />
      )}
      <Form form={form} layout="vertical" initialValues={initialValues(editing, deviation)} style={{ marginTop: 12 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '0 16px' }}>
          <Form.Item name="severity" label="事件严重性评估" rules={[{ required: true, message: '请选择严重性' }]}>
            <Select options={SEVERITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="responsible_department_name" label="责任部门">
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="planned_completion_date" label="计划完成日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </div>
        <Form.Item
          name="summary"
          label="问题及 CAPA 要求概述"
          rules={[{ required: true, whitespace: true, message: '请填写概述' }]}
        >
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 12 }} maxLength={20000} showCount />
        </Form.Item>

        <Form.Item label="CAPA 措施明细" style={{ marginBottom: 16 }}>
          <Form.List name="actions">
            {(fields, { add, remove }) => (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {fields.map((field) => (
                  <div
                    key={field.key}
                    style={{ display: 'grid', gridTemplateColumns: '1fr 110px 130px 110px 130px 110px 32px', gap: 8, alignItems: 'start' }}
                  >
                    <Form.Item name={[field.name, 'content']} rules={[{ required: true, whitespace: true, message: '填写措施' }]} style={{ marginBottom: 0 }}>
                      <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} placeholder="措施内容" maxLength={4000} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'action_type']} style={{ marginBottom: 0 }}>
                      <Select options={ACTION_TYPE_OPTIONS} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'department_name']} style={{ marginBottom: 0 }}>
                      <Input placeholder="责任部门" maxLength={255} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'owner_name']} style={{ marginBottom: 0 }}>
                      <Input placeholder="责任人" maxLength={128} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'planned_date']} style={{ marginBottom: 0 }}>
                      <DatePicker placeholder="计划完成" style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'status']} style={{ marginBottom: 0 }}>
                      <Select options={ACTION_STATUS_OPTIONS} />
                    </Form.Item>
                    <Button type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)} aria-label="删除措施" />
                  </div>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ action_type: 'preventive', status: 'pending' })} style={{ alignSelf: 'flex-start' }}>
                  添加措施
                </Button>
              </div>
            )}
          </Form.List>
        </Form.Item>

        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 180px', gap: '0 16px' }}>
          <Form.Item name="effect_method" label="有效性评估方式" tooltip="人员操作类跟踪 1 周、生产操作类至少 3 批、仪器类 1 个月">
            <Select options={EFFECT_METHOD_OPTIONS} allowClear />
          </Form.Item>
          <Form.Item name="effect_plan" label="有效性评估方案说明">
            <Input placeholder="如：跟踪 1 个月内紫外仪使用记录的波长确认执行率" maxLength={4000} />
          </Form.Item>
          <Form.Item name="effect_due_date" label="评估到期日" tooltip="留空时按评估方式在措施完成后自动推算">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </div>
        <Form.Item name="remark" label="备注" style={{ marginBottom: 0 }}>
          <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} maxLength={4000} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
