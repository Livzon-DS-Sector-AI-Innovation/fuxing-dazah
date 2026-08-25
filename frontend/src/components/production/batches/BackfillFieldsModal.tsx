'use client'

import { useState } from 'react'
import { App, Form, Input, InputNumber, Modal, Select, Switch } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { backfillExecutionFields, completeBatch } from '@/actions/production'
import { fetchRouteGraphClient } from '@/lib/api/production-client'
import type { Execution, FieldDef, MissingField } from '@/types/production'

/** 补录弹窗所需的执行信息（批次详情/工作台均可构造） */
export type BackfillExecution = Pick<
  Execution,
  'id' | 'batch_id' | 'node_id' | 'node_name'
> & { missing_required_fields?: MissingField[] }

interface Props {
  executions: BackfillExecution[]
  routeId: string
  onClose: () => void
  /** 补录全部成功后自动完成批次（工作台「完成批次(需补录)」流程） */
  autoCompleteBatch?: boolean
  onDone?: () => void
}

/**
 * 补录已结束工序缺失的必填字段（end 阶段）。
 * 单个执行（批次详情）或多个执行（工作台完成批次前）均可。
 * 字段按执行分组渲染，提交时逐执行 upsert。
 */
export function BackfillFieldsModal({ executions, routeId, onClose, autoCompleteBatch, onDone }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId),
  })

  // 每个执行 → 该节点 end 阶段字段定义
  const defsByExec = new Map<string, FieldDef[]>()
  const batchId = executions[0]?.batch_id
  for (const ex of executions) {
    const node = graph?.nodes.find(n => n.id === ex.node_id)
    const endDefs = (node?.fields ?? []).filter(f => f.phase === 'end')
    defsByExec.set(ex.id, endDefs)
  }
  const pendingCount = executions.reduce(
    (sum, ex) => sum + (ex.missing_required_fields?.length ?? 0),
    0,
  )

  const handleOk = async () => {
    // 图未加载完时 defs 为空，会静默跳过所有执行造成「假成功」，必须拦截
    if (!graph) {
      message.error('字段定义尚未加载完成，请稍后重试')
      return
    }
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
      for (const ex of executions) {
        const defs = defsByExec.get(ex.id) ?? []
        const fieldValues = defs
          .map(d => ({ key: `${ex.id}::${d.field_key}`, value: values[`${ex.id}::${d.field_key}`] }))
          .filter(v => v.value !== undefined && v.value !== null && v.value !== '')
          .map(v => ({ field_key: v.key.split('::')[1], value: v.value as never }))
        if (fieldValues.length === 0) continue
        const r = await backfillExecutionFields(ex.id, fieldValues)
        if (!r.success) {
          message.error(r.error ?? '补录失败')
          return
        }
      }
      if (autoCompleteBatch && batchId) {
        const r = await completeBatch(batchId)
        if (!r.success) {
          message.error(r.error ?? '补录完成，但批次完成失败')
          return
        }
        message.success('补录完成，批次已完成')
      } else {
        message.success('字段已补录')
      }
      queryClient.invalidateQueries({ queryKey: ['production-batch-detail', batchId] })
      queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
      onDone?.()
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          {autoCompleteBatch ? '补录并完成批次' : '补录字段'}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
      okText={autoCompleteBatch ? '提交补录并完成批次' : '提交补录'}
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      {pendingCount > 0 ? (
        <div style={{ color: '#d48806', fontSize: 13, marginBottom: 12 }}>
          {autoCompleteBatch
            ? `以下工序有必填字段待补录（${pendingCount} 项），提交后批次将完成：`
            : `以下工序有必填字段待补录（${pendingCount} 项）：`}
        </div>
      ) : (
        <div style={{ color: '#787671', fontSize: 13, padding: '8px 0' }}>
          该批次暂无待补录的必填字段。如需修正已填写的字段，直接编辑下方表单。
        </div>
      )}
      <Form form={form} layout="vertical">
        {executions.map((ex, i) => {
          const defs = defsByExec.get(ex.id) ?? []
          if (defs.length === 0) return null
          return (
            <div key={ex.id} style={{ marginBottom: i < executions.length - 1 ? 20 : 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: '#37352f', marginBottom: 8 }}>
                {ex.node_name ?? '工序'}
                {(ex.missing_required_fields?.length ?? 0) > 0 && (
                  <span style={{ color: '#d48806', fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
                    待补录 {ex.missing_required_fields!.length} 项
                  </span>
                )}
              </div>
              {defs.map(d => {
                const name = `${ex.id}::${d.field_key}`
                // 只对真正缺失的必填字段加校验：已填字段若也必填会卡住补录（无法只修一个值）
                const isMissing = (ex.missing_required_fields ?? []).some(m => m.field_key === d.field_key)
                return (
                  <Form.Item
                    key={name}
                    name={name}
                    label={`${d.field_label}${d.unit ? ` (${d.unit})` : ''}${d.required ? '（必填 · 可补录）' : ''}`}
                    rules={d.required && isMissing
                      ? [{ required: true, message: `请填写${d.field_label}` }]
                      : undefined}
                  >
                    <DynamicFieldSingle def={d} />
                  </Form.Item>
                )
              })}
            </div>
          )
        })}
      </Form>
    </Modal>
  )
}

/** 单个字段控件（与 DynamicFieldFormItems 相同渲染，key 由外层拼接）。
 *  必须接收并透传 Form.Item 注入的 value/onChange，否则输入不会进入表单 store。 */
function DynamicFieldSingle({
  def, value, onChange,
}: { def: FieldDef; value?: unknown; onChange?: (v: unknown) => void }) {
  if (def.data_type === 'numeric') {
    return <InputNumber style={{ width: '100%' }} value={value as number | undefined} onChange={onChange} />
  }
  if (def.data_type === 'boolean') {
    return <Switch checked={value as boolean | undefined} onChange={onChange} />
  }
  if (def.data_type === 'select') {
    return (
      <Select
        value={value as string | undefined}
        onChange={onChange}
        options={(def.options ?? []).map(o => ({ value: o, label: o }))}
      />
    )
  }
  return <Input value={value as string | undefined} onChange={onChange} />
}
