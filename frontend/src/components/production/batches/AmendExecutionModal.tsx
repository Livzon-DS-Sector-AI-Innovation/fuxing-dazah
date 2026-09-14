'use client'

import { useState } from 'react'
import { Alert, App, Button, DatePicker, Divider, Form, Input, Modal, Skeleton } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { amendExecution } from '@/actions/production'
import { fetchRouteGraphClient } from '@/lib/api/production-client'
import type {
  AmendExecutionInput,
  Execution,
  FieldDef,
  FieldValueInput,
} from '@/types/production'
import { DynamicFieldFormItems } from './DynamicFieldFormItems'

interface Props {
  execution: Execution
  routeId: string
  onClose: () => void
}

/** 把空值（undefined/''）归一为 null，供脏比较与提交 */
function norm(v: unknown): boolean | number | string | null {
  if (v === undefined || v === '' || v === null) return null
  return v as boolean | number | string
}

/** 按字段定义的 data_type 把已填报值映射回表单初值 */
function buildInitialFieldValues(defs: FieldDef[], execution: Execution) {
  const defByKey = new Map(defs.map(d => [d.field_key, d]))
  const values: Record<string, boolean | number | string | undefined> = {}
  for (const v of execution.field_values) {
    const def = defByKey.get(v.field_key)
    if (!def) continue
    if (def.data_type === 'numeric') values[v.field_key] = v.value_numeric ?? undefined
    else if (def.data_type === 'boolean') values[v.field_key] = v.value_bool ?? undefined
    else values[v.field_key] = v.value_text ?? undefined
  }
  return values
}

export function AmendExecutionModal({ execution, routeId, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const { data: graph, isLoading } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId),
  })
  const node = graph?.nodes.find(n => n.id === execution.node_id)
  const startDefs = node?.fields.filter(f => f.phase === 'start') ?? []
  // 已中止的执行从未走过结束流程，end 字段不适用，不提供编辑
  const endDefs =
    execution.status === 'completed'
      ? node?.fields.filter(f => f.phase === 'end') ?? []
      : []
  const editableDefs = [...startDefs, ...endDefs]

  const initialFieldValues = buildInitialFieldValues(editableDefs, execution)
  // 弹窗自身的起止时间/备注用 __amend_ 前缀键，避免与字段定义同名（field_key 是
  // 自由文本，工序配置里完全可以有一个叫 remark / started_at 的字段）时表单键冲突、
  // 初值互相覆盖、脏检查读写错数据
  const initialValues: Record<string, unknown> = {
    ...initialFieldValues,
    __amend_started_at: dayjs(execution.started_at),
    __amend_finished_at: execution.finished_at ? dayjs(execution.finished_at) : undefined,
    __amend_remark: execution.remark ?? undefined,
  }

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return

    // 脏检查：只提交与初值不同的字段/时间/备注，避免刷新未改字段的填写记录
    const fieldValues: FieldValueInput[] = []
    for (const d of editableDefs) {
      // 从未填过的布尔字段在 Switch 里只有 false/undefined 两种「未填」形态，
      // 均视为未变化，避免伪造 value_bool=false 的填写行
      if (
        d.data_type === 'boolean' &&
        initialValues[d.field_key] === undefined &&
        !values[d.field_key]
      ) {
        continue
      }
      if (norm(initialValues[d.field_key]) !== norm(values[d.field_key])) {
        fieldValues.push({
          field_key: d.field_key,
          value: norm(values[d.field_key]) as never,
        })
      }
    }
    // 时间选择器精度到分钟，脏检查按分钟比较：重选同一分钟不应改写秒级原值
    const startChanged = !((values.__amend_started_at as Dayjs).isSame(
      initialValues.__amend_started_at as Dayjs,
      'minute',
    ))
    const endChanged =
      execution.finished_at != null &&
      !((values.__amend_finished_at as Dayjs).isSame(
        initialValues.__amend_finished_at as Dayjs,
        'minute',
      ))
    const remarkChanged = norm(initialValues.__amend_remark) !== norm(values.__amend_remark)

    if (!fieldValues.length && !startChanged && !endChanged && !remarkChanged) {
      message.info('未做任何修改')
      return
    }

    const input: AmendExecutionInput = {}
    if (startChanged) input.started_at = (values.__amend_started_at as Dayjs).toISOString()
    if (endChanged) input.finished_at = (values.__amend_finished_at as Dayjs).toISOString()
    if (fieldValues.length) input.field_values = fieldValues
    if (remarkChanged) input.remark = (values.__amend_remark as string | undefined) ?? ''

    setSubmitting(true)
    try {
      const result = await amendExecution(execution.id, input)
      if (result.success) {
        message.success('修改已保存')
        queryClient.invalidateQueries({
          queryKey: ['production-batch-detail', execution.batch_id],
        })
        queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        onClose()
      } else {
        message.error(result.error ?? '修改失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const titleSuffix = execution.execution_seq > 1 ? `（第 ${execution.execution_seq} 次）` : ''

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          修改工序数据 · {execution.node_name ?? ''}
          {titleSuffix}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={600}
      okText="保存修改"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      {isLoading || !graph ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : !node ? (
        <Alert
          type="error"
          showIcon
          title="工序定义不存在（路线可能已重新发布），无法编辑该工序的字段"
          action={
            <Button size="small" onClick={onClose}>
              关闭
            </Button>
          }
        />
      ) : (
        <Form form={form} layout="vertical" initialValues={initialValues}>
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            title="修改将记录审计日志（修改人、修改前后值）；工序时间变化会同步重算批次首末时间。"
          />

          <Form.Item
            name="__amend_started_at"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>开始时间</span>}
            rules={[{ required: true, message: '请选择开始时间' }]}
          >
            <DatePicker
              showTime={{ format: 'HH:mm' }}
              format="YYYY-MM-DD HH:mm"
              style={{ width: '100%', borderRadius: 8 }}
            />
          </Form.Item>

          {execution.finished_at && (
            <Form.Item
              name="__amend_finished_at"
              label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>结束时间</span>}
              rules={[{ required: true, message: '请选择结束时间' }]}
            >
              <DatePicker
                showTime={{ format: 'HH:mm' }}
                format="YYYY-MM-DD HH:mm"
                style={{ width: '100%', borderRadius: 8 }}
              />
            </Form.Item>
          )}

          {startDefs.length > 0 && (
            <>
              <Divider titlePlacement="start" style={{ fontSize: 13 }}>
                开始阶段字段
              </Divider>
              <DynamicFieldFormItems defs={startDefs} enforceRequired={false} />
            </>
          )}

          {endDefs.length > 0 && (
            <>
              <Divider titlePlacement="start" style={{ fontSize: 13 }}>
                结束阶段字段
              </Divider>
              <DynamicFieldFormItems defs={endDefs} enforceRequired={false} />
            </>
          )}

          <Form.Item
            name="__amend_remark"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>备注</span>}
            style={{ marginBottom: 0 }}
          >
            <Input.TextArea rows={2} placeholder="备注信息（可选）" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}
