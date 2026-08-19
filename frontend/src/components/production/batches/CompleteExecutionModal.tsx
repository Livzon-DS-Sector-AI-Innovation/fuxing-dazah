'use client'

import { useEffect, useState } from 'react'
import { App, Alert, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  completeExecution,
  fetchMyLineAssignments,
  fetchLineAssignmentsByUser,
} from '@/actions/production'
import { fetchBatchDetailClient, fetchRouteGraphClient } from '@/lib/api/production-client'
import type { Execution } from '@/types/production'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'

interface Props {
  execution: Execution
  routeId: string
  onClose: () => void
  onSuccess?: () => void
}

export function CompleteExecutionModal({ execution, routeId, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId),
  })
  const node = graph?.nodes.find(n => n.id === execution.node_id)
  const endDefs = node?.fields.filter(f => f.phase === 'end') ?? []
  const outputIntermediates = (node?.intermediates ?? []).filter(im => im.direction === 'output')

  // ── 产线候选：操作人绑定 ∪ 批次负责人绑定（操作人绑定排前）──
  const { data: batchDetail } = useQuery({
    queryKey: ['production-batch-detail', execution.batch_id],
    queryFn: () => fetchBatchDetailClient(execution.batch_id),
    enabled: outputIntermediates.length > 0,
  })
  const { data: myLines } = useQuery({
    queryKey: ['production-my-lines'],
    queryFn: async () => {
      const r = await fetchMyLineAssignments()
      return r.success ? (r.data ?? []) : []
    },
    enabled: outputIntermediates.length > 0,
  })
  const { data: ownerLines } = useQuery({
    queryKey: ['production-owner-lines', batchDetail?.owner_user_id],
    queryFn: async () => {
      if (!batchDetail?.owner_user_id) return []
      const r = await fetchLineAssignmentsByUser(batchDetail.owner_user_id)
      return r.success ? (r.data ?? []) : []
    },
    enabled: outputIntermediates.length > 0 && !!(batchDetail?.owner_user_id),
  })
  // 与后端 resolve_user_line_ids 同口径：操作人绑定优先，仅当操作人无绑定时用批次负责人绑定兜底
  const myLineIds = new Set((myLines ?? []).map(la => la.line_id))
  const lineOptions = (myLineIds.size > 0 ? (myLines ?? []) : (ownerLines ?? []))
    .map(la => ({
      value: la.line_id,
      label: la.line_name ?? la.line_id,
    }))
  // 候选仅一条时自动带出；依赖派生原始值，避免每次渲染重跑 effect
  const autoLineValue = lineOptions.length === 1 ? lineOptions[0].value : null

  useEffect(() => {
    // 字段为空才填充，避免覆盖用户选择
    if (autoLineValue && !form.getFieldValue('line_id')) {
      form.setFieldsValue({ line_id: autoLineValue })
    }
  }, [autoLineValue, form])

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
    const result = await completeExecution(execution.id, {
      field_values: buildFieldValues(endDefs, values),
      remark: (values.remark as string) ?? null,
      intermediate_outputs: outputIntermediates.length > 0
        ? outputIntermediates.map(im => ({
            intermediate_type_id: im.intermediate_type_id,
            quantity: Number((values as Record<string, number>)[`output_qty_${im.intermediate_type_id}`]) || 0,
            unit: ((values as Record<string, string>)[`output_unit_${im.intermediate_type_id}`]) || undefined,
            intermediate_batch_no: ((values as Record<string, string>)[`output_batch_${im.intermediate_type_id}`]) || undefined,
            remark: ((values as Record<string, string>)[`output_remark_${im.intermediate_type_id}`]) || undefined,
          })).filter(o => o.quantity > 0)
        : [],
      line_id: outputIntermediates.length > 0
        ? ((values.line_id as string) ?? null)
        : null,
    })
    if (result.success) {
      const startedMs = new Date(execution.started_at).getTime()
      const isValid = !Number.isNaN(startedMs) && startedMs > 0
      const stepName = execution.node_name ?? '工序'
      if (isValid) {
        const durationMs = Date.now() - startedMs
        const durationMin = Math.round(durationMs / 60000)
        const durationStr = durationMin < 60
          ? `${durationMin} 分钟`
          : `${(durationMin / 60).toFixed(1)} 小时`
        message.success(`${stepName}已完成，耗时 ${durationStr}`)
      } else {
        message.success(`${stepName}已完成`)
      }
      queryClient.invalidateQueries({
        queryKey: ['production-batch-detail', execution.batch_id],
      })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      queryClient.invalidateQueries({ queryKey: ['production-trace'] })
      queryClient.invalidateQueries({ queryKey: ['production-available-outputs'] })
      onSuccess?.()
      onClose()
    } else {
      message.error(result.error)
    }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          结束工序 · {execution.node_name ?? ''}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
      okText="结束工序"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical">
        {/* ── 动态字段（必填不阻断，批次结束前可补录） ── */}
        <DynamicFieldFormItems defs={endDefs} enforceRequired={false} />

        {/* ── 产出物料 ── */}
        {outputIntermediates.length > 0 && (
          <div style={{ marginTop: endDefs.length > 0 ? 8 : 0, marginBottom: 16 }}>
            <Form.Item
              name="line_id"
              label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>产线</span>}
              rules={[
                {
                  // 与后端对齐：仅当本次实际提交产出（数量>0）时 line_id 必填
                  validator: (_: unknown, value: string | undefined) => {
                    const hasOutput = outputIntermediates.some(im => {
                      const v = form.getFieldValue(`output_qty_${im.intermediate_type_id}`)
                      return Number(v) > 0
                    })
                    if (!value && hasOutput) {
                      return Promise.reject(new Error('请选择本次产出落地的产线'))
                    }
                    return Promise.resolve()
                  },
                },
              ]}
            >
              <Select
                placeholder="选择产线"
                options={lineOptions}
                style={{ borderRadius: 6 }}
              />
            </Form.Item>
            {lineOptions.length === 0 && (
              <Alert
                type="warning"
                showIcon
                title="您尚未绑定产线，请联系管理员在「主数据管理-产线」中配置"
                style={{ marginBottom: 12 }}
              />
            )}
            {outputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{
                padding: '14px 16px', marginBottom: 10,
                borderRadius: 10, background: '#ffffff',
                border: '1px solid #ede9e4',
              }}>
                {/* 物料名称 — 突出显示 */}
                <div style={{
                  fontSize: 15, fontWeight: 600, color: '#1a1a1a',
                  marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required && (
                    <span style={{ fontSize: 11, color: '#e03131', fontWeight: 400 }}>必填</span>
                  )}
                </div>

                {/* 产出详情 */}
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 10,
                  padding: '12px 14px', borderRadius: 8,
                  background: '#fafaf8',
                }}>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <Form.Item
                      name={`output_batch_${im.intermediate_type_id}`}
                      label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>中间体批号</span>}
                      style={{ margin: 0, flex: 1 }}
                    >
                      <Input placeholder="默认使用批次号" style={{ borderRadius: 6 }} />
                    </Form.Item>

                    <Form.Item
                      name={`output_unit_${im.intermediate_type_id}`}
                      label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>单位</span>}
                      style={{ margin: 0, width: 120 }}
                    >
                      <Input placeholder={im.unit_override ?? '默认单位'} style={{ borderRadius: 6 }} />
                    </Form.Item>
                  </div>

                  <Form.Item
                    name={`output_qty_${im.intermediate_type_id}`}
                    label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>数量</span>}
                    rules={im.required ? [{ required: true, message: '请输入数量' }] : undefined}
                    style={{ margin: 0 }}
                  >
                    <InputNumber min={1} placeholder="数量" style={{ width: '100%' }} />
                  </Form.Item>
                </div>

                {/* 备注 */}
                <Form.Item
                  name={`output_remark_${im.intermediate_type_id}`}
                  style={{ marginBottom: 0, marginTop: 10 }}
                >
                  <Input placeholder="备注（可选）" style={{ borderRadius: 6 }} />
                </Form.Item>
              </div>
            ))}
          </div>
        )}

        {/* ── 全局备注 ── */}
        <Form.Item
          name="remark"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>备注</span>}
        >
          <Input.TextArea rows={2} placeholder="备注信息（可选）" style={{ borderRadius: 8 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
