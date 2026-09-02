'use client'

import { useMemo, useEffect, useState } from 'react'
import { App, DatePicker, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { Dayjs } from 'dayjs'
import { startExecution, fetchNodeAssignments } from '@/actions/production'
import { getCurrentUser } from '@/actions/auth'
import {
  fetchBatchDetailClient,
  fetchRouteGraphClient,
  fetchEquipmentOptionsClient,
  fetchAvailableContainersClient,
} from '@/lib/api/production-client'
import { UserSelect } from '@/components/shared'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'
import { fetchAvailableOutputs } from '@/actions/production'
import type { IdentityPersonnel } from '@/lib/api/identity'

interface Props {
  batchId: string
  onClose: () => void
  defaultNodeId?: string
}

export function StartExecutionModal({ batchId, onClose, defaultNodeId }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)
  const nodeId: string | undefined = Form.useWatch('node_id', form)
  const watchedValues: Record<string, unknown> | undefined = Form.useWatch([], form)

  const { data: detail } = useQuery({
    queryKey: ['production-batch-detail', batchId],
    queryFn: () => fetchBatchDetailClient(batchId),
  })
  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', detail?.route_id],
    queryFn: () => fetchRouteGraphClient(detail!.route_id),
    enabled: !!detail?.route_id,
  })

  // ── 设备远程搜索（数据范围为当前用户在设备台账的可见设备）──
  const [equipmentKeyword, setEquipmentKeyword] = useState('')
  // 已选设备不在当前搜索结果中时 antd 会显示原始 UUID，记录选中时的 label 用于合并回显
  const [equipmentSelectedLabels, setEquipmentSelectedLabels] = useState<Record<string, string>>({})

  const { data: equipmentData, isFetching: equipmentSearchLoading } = useQuery({
    queryKey: ['production-equipment-options', equipmentKeyword],
    queryFn: () => fetchEquipmentOptionsClient({ keyword: equipmentKeyword || undefined, page: 1, page_size: 20 }),
  })

  const { legalNodeIds } = useMemo(() => {
    if (!graph || !detail) return { legalNodeIds: new Set<string>() }
    const completed = new Set(
      detail.executions.filter(e => e.status === 'completed').map(e => e.node_id),
    )
    const inProgress = new Set(
      detail.executions.filter(e => e.status === 'in_progress').map(e => e.node_id),
    )
    const legal = new Set<string>()
    if (completed.size === 0 && inProgress.size === 0) {
      if (detail.entry_node_id) {
        legal.add(detail.entry_node_id)
      } else {
        const hasIncoming = new Set(
          graph.edges.filter(e => e.edge_type === 'normal').map(e => e.to_node_id),
        )
        graph.nodes.forEach(n => {
          if (!hasIncoming.has(n.id)) legal.add(n.id)
        })
      }
    } else {
      graph.edges.forEach(e => {
        if (completed.has(e.from_node_id)) legal.add(e.to_node_id)
        if (e.allow_overlap && !e.is_batch_boundary && inProgress.has(e.from_node_id)) {
          legal.add(e.to_node_id)
        }
      })
    }
    return { legalNodeIds: legal }
  }, [graph, detail])

  const nodeOptions = useMemo(() => {
    if (!graph) return []
    const legal = graph.nodes.filter(n => legalNodeIds.has(n.id))
    const others = graph.nodes.filter(n => !legalNodeIds.has(n.id))
    return [...legal, ...others].map(n => ({
      value: n.id,
      label: `${n.name}（${n.node_code}）${legalNodeIds.has(n.id) ? ' [推荐]' : ''}`,
    }))
  }, [graph, legalNodeIds])

  const { data: nodeAssignmentsData } = useQuery({
    queryKey: ['production-node-assignments', detail?.route_id, nodeId],
    queryFn: async () => {
      if (!detail?.route_id || !nodeId) return []
      const r = await fetchNodeAssignments(detail.route_id, nodeId)
      // 查询失败时抛错（data 保持 undefined）：避免把失败当成"无配置"，
      // 否则会把负责人静默填成本人并授以新执行负责人权限
      if (!r.success) throw new Error(r.error ?? '获取节点负责人配置失败')
      return r.data ?? []
    },
    enabled: !!(detail?.route_id && nodeId),
    staleTime: 30_000,
  })

  // 当前登录用户：该节点无配置默认负责人时，工序负责人默认填本人
  const { data: currentUser } = useQuery({
    queryKey: ['auth-current-user'],
    queryFn: () => getCurrentUser(),
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (defaultNodeId && graph) {
      const currentNode = form.getFieldValue('node_id')
      if (!currentNode) {
        form.setFieldsValue({ node_id: defaultNodeId })
      }
    }
  }, [defaultNodeId, graph, form])

  useEffect(() => {
    // 等该节点的默认负责人配置加载完再决定：有配置 → 第一个配置人；无配置 → 当前登录用户。
    // 用户一旦手动选过负责人（isFieldTouched 仅由用户交互置位，setFieldsValue 不会触碰它），
    // 后续 refetch/切换节点都不再自动填充，避免覆盖手动选择。
    if (!nodeId || nodeAssignmentsData === undefined) return
    if (form.isFieldTouched('owner_id')) return
    const configured = nodeAssignmentsData[0]?.user_id
    const defaultOwner = configured ?? currentUser?.id
    if (!defaultOwner) return
    const currentOwner = form.getFieldValue('owner_id')
    if (currentOwner !== defaultOwner) {
      form.setFieldsValue({ owner_id: defaultOwner })
    }
  }, [nodeId, nodeAssignmentsData, currentUser, form])

  const selectedNode = graph?.nodes.find(n => n.id === nodeId)
  const startDefs = selectedNode?.fields.filter(f => f.phase === 'start') ?? []
  const needsDeviation = !!nodeId && !legalNodeIds.has(nodeId)
  const inputIntermediates = (selectedNode?.intermediates ?? []).filter(im => im.direction === 'input')

  const { data: batchOutputs, isError: outputsError } = useQuery({
    queryKey: ['production-available-outputs', batchId],
    queryFn: async () => {
      const r = await fetchAvailableOutputs(undefined, batchId)
      if (!r.success) throw new Error(r.error ?? '获取可用产出失败')
      return r.data ?? []
    },
    enabled: inputIntermediates.length > 0,
  })

  const getOutputOptions = (intermediateTypeId: string) =>
    (batchOutputs ?? [])
      .filter(o => o.intermediate_type_id === intermediateTypeId)
      .map(o => ({
        value: o.id,
        label: `${o.intermediate_type_name ?? '?'} / ${o.line_name ?? '未标产线'} / ${o.intermediate_batch_no ?? o.batch_no ?? '-'} / 余量 ${o.available_quantity ?? o.quantity}${o.unit}`,
      }))

  // ── 混装容器（消耗可选：从容器取用，不溯源批次）──
  const { data: availableContainers } = useQuery({
    queryKey: ['production-available-containers', batchId],
    queryFn: () => fetchAvailableContainersClient(undefined, batchId),
    enabled: inputIntermediates.length > 0,
  })
  const getContainerOptions = (intermediateTypeId: string) =>
    (availableContainers ?? [])
      .filter(ct => ct.intermediate_type_id === intermediateTypeId)
      .map(ct => ({
        value: ct.id,
        label: `${ct.name}（${ct.line_name ?? '未标产线'}） / 余量 ${ct.available_quantity ?? 0}`,
      }))

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
    const ownerId: string | undefined = values.owner_id
    let ownerName: string | null = null
    if (ownerId) {
      const cache = queryClient.getQueryData<{ items: IdentityPersonnel[] }>(['identity-personnel'])
      ownerName = cache?.items?.find((p) => p.id === ownerId)?.name
        // 人员列表缓存未加载/未同步到本人时，回退到当前登录用户信息
        ?? (ownerId === currentUser?.id ? currentUser.name : null)
    }
    const result = await startExecution(batchId, {
      node_id: values.node_id,
      owner_id: ownerId ?? null,
      owner_name: ownerName,
      equipment_ids: (values.equipment_ids as string[]) ?? [],
      field_values: buildFieldValues(startDefs, values),
      deviation_reason: needsDeviation ? (values.deviation_reason as string) : null,
      remark: (values.remark as string) ?? null,
      started_at: (values.started_at as Dayjs | undefined)?.toISOString() ?? null,
      intermediate_consumptions: inputIntermediates.length > 0
        ? inputIntermediates.flatMap(im => {
            const outputIds = (values as Record<string, string[]>)[`consume_output_${im.intermediate_type_id}`] ?? []
            const containerIds = (values as Record<string, string[]>)[`consume_container_${im.intermediate_type_id}`] ?? []
            const remark = ((values as Record<string, string>)[`consume_remark_${im.intermediate_type_id}`]) || undefined
            return [
              ...outputIds
                .map(outputId => ({
                  intermediate_type_id: im.intermediate_type_id,
                  output_id: outputId,
                  quantity: Number((values as Record<string, number>)[`consume_qty_${im.intermediate_type_id}_${outputId}`]) || 0,
                  remark,
                }))
                .filter(c => c.quantity > 0),
              ...containerIds
                .map(containerId => ({
                  intermediate_type_id: im.intermediate_type_id,
                  container_id: containerId,
                  quantity: Number((values as Record<string, number>)[`consume_cqty_${im.intermediate_type_id}_${containerId}`]) || 0,
                  remark,
                }))
                .filter(c => c.quantity > 0),
            ]
          })
        : [],
    })
    if (result.success) {
      message.success('工序已开始')
      queryClient.invalidateQueries({ queryKey: ['production-batch-detail', batchId] })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      queryClient.invalidateQueries({ queryKey: ['production-trace'] })
      queryClient.invalidateQueries({ queryKey: ['production-available-outputs'] })
      onClose()
    } else {
      message.error(result.error)
    }
    } finally {
      setSubmitting(false)
    }
  }

  const mergedEquipmentOptions = useMemo(() => {
    const searchOptions = (equipmentData?.items ?? []).map(e => ({
      value: e.id,
      label: `${e.name}（${e.equipment_no}）`,
    }))
    const inList = new Set(searchOptions.map(o => o.value))
    return [
      ...searchOptions,
      ...Object.entries(equipmentSelectedLabels)
        .filter(([id]) => !inList.has(id))
        .map(([value, label]) => ({ value, label })),
    ]
  }, [equipmentData, equipmentSelectedLabels])

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          开始工序 · {detail?.batch_no ?? ''}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={600}
      okText="开始工序"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical">
        {/* ── 工序节点 ── */}
        <Form.Item
          name="node_id"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>工序节点</span>}
          rules={[{ required: true, message: '请选择工序节点' }]}
        >
          <Select options={nodeOptions} showSearch placeholder="选择要开始的工序" style={{ borderRadius: 8 }} />
        </Form.Item>

        {/* ── 偏离原因 ── */}
        {needsDeviation && (
          <Form.Item
            name="deviation_reason"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>偏离原因</span>}
            rules={[{ required: true, message: '该流转未在工艺路线中定义，必须说明偏离原因' }]}
          >
            <Input.TextArea rows={2} placeholder="该流转未在工艺路线中定义，请说明原因" style={{ borderRadius: 8 }} />
          </Form.Item>
        )}

        {/* ── 基础信息区 ── */}
        <div style={{
          padding: '16px', borderRadius: 10, marginBottom: 16,
          background: '#fafaf8', border: '1px solid #ede9e4',
        }}>
          <Form.Item
            name="owner_id"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>工序负责人</span>}
          >
            <UserSelect placeholder="选择工序负责人" style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="started_at"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>开始时间（可选）</span>}
          >
            <DatePicker
              showTime={{ format: 'HH:mm' }}
              format="YYYY-MM-DD HH:mm"
              placeholder="留空默认为当前时间"
              style={{ width: '100%', borderRadius: 8 }}
            />
          </Form.Item>

          <Form.Item
            name="equipment_ids"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>使用设备</span>}
            style={{ marginBottom: 0 }}
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="搜索并选择设备"
              showSearch={{ filterOption: false, onSearch: setEquipmentKeyword }}
              loading={equipmentSearchLoading}
              notFoundContent={equipmentSearchLoading ? '搜索中...' : '无匹配设备'}
              onChange={(ids: string[]) => {
                const labelOf = new Map(mergedEquipmentOptions.map(o => [o.value, o.label]))
                setEquipmentSelectedLabels(
                  Object.fromEntries(ids.map(id => [id, labelOf.get(id) ?? equipmentSelectedLabels[id] ?? id])),
                )
              }}
              options={mergedEquipmentOptions}
              style={{ borderRadius: 8 }}
            />
          </Form.Item>
        </div>

        {/* ── 动态字段 ── */}
        <DynamicFieldFormItems defs={startDefs} />

        {/* ── 消耗物料 ── */}
        {inputIntermediates.length > 0 && (
          <div style={{ marginTop: 8, marginBottom: 16 }}>
            {outputsError && (
              <div style={{
                marginBottom: 10, padding: '8px 12px', borderRadius: 6,
                background: '#fff2f0', color: '#e03131', fontSize: 12,
                border: '1px solid #ffccc7',
              }}>
                可用产出加载失败，请稍后重试
              </div>
            )}

            {inputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{
                padding: '14px 16px', marginBottom: 10,
                borderRadius: 10, background: '#ffffff',
                border: '1px solid #ede9e4',
              }}>
                {/* 物料名称 — 突出显示 */}
                <div style={{
                  fontSize: 15, fontWeight: 600, color: '#1a1a1a',
                  marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required && (
                    <span style={{ fontSize: 11, color: '#e03131', fontWeight: 400 }}>必填</span>
                  )}
                </div>

                {/* 选择产出批次 */}
                <Form.Item
                  name={`consume_output_${im.intermediate_type_id}`}
                  rules={im.required ? [{ required: true, message: '请选择产出批次' }] : undefined}
                  style={{ marginBottom: 10 }}
                >
                  <Select
                    mode="multiple"
                    options={getOutputOptions(im.intermediate_type_id)}
                    placeholder="选择上游产出批次"
                    allowClear
                    showSearch
                    style={{ borderRadius: 8 }}
                  />
                </Form.Item>

                {/* 每个选中产出的消耗数量 */}
                {(() => {
                  const selectedIds = (watchedValues?.[`consume_output_${im.intermediate_type_id}`] as string[]) ?? []
                  if (!selectedIds.length) return null
                  return (
                    <div style={{
                      display: 'flex', flexDirection: 'column', gap: 8,
                      padding: '10px 12px', borderRadius: 8,
                      background: '#fafaf8',
                    }}>
                      {selectedIds.map(outputId => {
                        const output = (batchOutputs ?? []).find(o => o.id === outputId)
                        const label = output
                          ? (output.intermediate_batch_no ?? output.batch_no ?? outputId.slice(0, 8))
                          : outputId.slice(0, 8)
                        return (
                          <div key={outputId} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{
                              fontSize: 13, fontWeight: 500, color: '#37352f', flex: 1,
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}>
                              {label}
                            </span>
                            <Form.Item
                              name={`consume_qty_${im.intermediate_type_id}_${outputId}`}
                              rules={im.required ? [{ required: true, message: '请输入' }] : undefined}
                              style={{ margin: 0, width: 140 }}
                            >
                              <InputNumber
                                min={1}
                                max={output?.available_quantity ?? undefined}
                                placeholder={`消耗数量${output?.unit ? ` (${output.unit})` : ''}`}
                                style={{ width: '100%' }}
                              />
                            </Form.Item>
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}

                {/* 选择混装容器（可选：从容器取用，不溯源具体批次） */}
                {getContainerOptions(im.intermediate_type_id).length > 0 && (
                  <>
                    <Form.Item
                      name={`consume_container_${im.intermediate_type_id}`}
                      style={{ marginBottom: 10, marginTop: 10 }}
                    >
                      <Select
                        mode="multiple"
                        options={getContainerOptions(im.intermediate_type_id)}
                        placeholder="或从混装容器取用（可选）"
                        allowClear
                        showSearch
                        style={{ borderRadius: 8 }}
                      />
                    </Form.Item>
                    {(() => {
                      const selectedContainers = (watchedValues?.[`consume_container_${im.intermediate_type_id}`] as string[]) ?? []
                      if (!selectedContainers.length) return null
                      return (
                        <div style={{
                          display: 'flex', flexDirection: 'column', gap: 8,
                          padding: '10px 12px', borderRadius: 8,
                          background: '#fafaf8',
                        }}>
                          {selectedContainers.map(containerId => {
                            const ct = (availableContainers ?? []).find(c => c.id === containerId)
                            const label = ct ? `${ct.name}（混装）` : containerId.slice(0, 8)
                            return (
                              <div key={containerId} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <span style={{
                                  fontSize: 13, fontWeight: 500, color: '#37352f', flex: 1,
                                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                }}>
                                  {label}
                                </span>
                                <Form.Item
                                  name={`consume_cqty_${im.intermediate_type_id}_${containerId}`}
                                  style={{ margin: 0, width: 140 }}
                                >
                                  <InputNumber
                                    min={1}
                                    max={ct?.available_quantity ?? undefined}
                                    placeholder="消耗数量"
                                    style={{ width: '100%' }}
                                  />
                                </Form.Item>
                              </div>
                            )
                          })}
                        </div>
                      )
                    })()}
                  </>
                )}

                {/* 备注 */}
                <Form.Item
                  name={`consume_remark_${im.intermediate_type_id}`}
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
