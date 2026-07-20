'use client'

import { useMemo } from 'react'
import { App, Form, Input, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { startExecution } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchRouteGraphClient,
} from '@/lib/api/production-client'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { fetchEquipmentsClient } from '@/lib/api/equipment-client'
import { PersonnelSelect } from '@/components/equipment'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'
import { fetchAvailableOutputs } from '@/actions/production'

interface Props {
  batchId: string
  onClose: () => void
}

export function StartExecutionModal({ batchId, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const nodeId: string | undefined = Form.useWatch('node_id', form)
  // 监听全部表单值，用于动态渲染每个产出批次的数量输入
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
  const { data: personnelData } = useQuery({
    queryKey: ['production-personnel'],
    queryFn: () => fetchPersonnelList(),
  })
  const { data: equipmentData } = useQuery({
    queryKey: ['production-equipments'],
    queryFn: () => fetchEquipmentsClient({ page: 1, page_size: 100 }),
  })

  // 合法来路计算（与后端 _check_source_legality 同规则）
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
      // 首执行：entry_node_id 或路线起点（无 normal 入边）
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
        // 流水线边：前道 in_progress 即可开始
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

  const selectedNode = graph?.nodes.find(n => n.id === nodeId)
  const startDefs = selectedNode?.fields.filter(f => f.phase === 'start') ?? []
  const needsDeviation = !!nodeId && !legalNodeIds.has(nodeId)
  const inputIntermediates = (selectedNode?.intermediates ?? []).filter(im => im.direction === 'input')

  // 加载所有可用中间体产出（跨批次），用于消耗时选择上游产出
  const { data: batchOutputs, isError: outputsError } = useQuery({
    queryKey: ['production-available-outputs'],
    queryFn: async () => {
      const r = await fetchAvailableOutputs()
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
        label: `${o.intermediate_type_name ?? '?'} / ${o.intermediate_batch_no ?? o.batch_no ?? '-'} / ${o.quantity}${o.unit}`,
      }))

  const personnel = personnelData?.items ?? []

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const ownerId: string | undefined = values.owner_id
    const owner = personnel.find(
      (p: { user_id?: string | null; id: string }) => (p.user_id || p.id) === ownerId,
    )
    const result = await startExecution(batchId, {
      node_id: values.node_id,
      owner_id: ownerId ?? null,
      owner_name: owner?.name ?? null,
      equipment_ids: (values.equipment_ids as string[]) ?? [],
      field_values: buildFieldValues(startDefs, values),
      deviation_reason: needsDeviation ? (values.deviation_reason as string) : null,
      remark: (values.remark as string) ?? null,
      intermediate_consumptions: inputIntermediates.length > 0
        ? inputIntermediates.flatMap(im => {
            const outputIds = (values as Record<string, string[]>)[`consume_output_${im.intermediate_type_id}`] ?? []
            const remark = ((values as Record<string, string>)[`consume_remark_${im.intermediate_type_id}`]) || undefined
            return outputIds
              .map(outputId => ({
                intermediate_type_id: im.intermediate_type_id,
                output_id: outputId,
                quantity: Number((values as Record<string, number>)[`consume_qty_${im.intermediate_type_id}_${outputId}`]) || 0,
                remark,
              }))
              .filter(c => c.quantity > 0)
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
  }

  return (
    <Modal
      title={`开始工序 · ${detail?.batch_no ?? ''}`}
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="node_id"
          label="工序节点"
          rules={[{ required: true, message: '请选择工序节点' }]}
        >
          <Select options={nodeOptions} showSearch />
        </Form.Item>
        {needsDeviation && (
          <Form.Item
            name="deviation_reason"
            label="偏离原因"
            rules={[{ required: true, message: '该流转未在工艺路线中定义，必须说明偏离原因' }]}
          >
            <Input.TextArea rows={2} placeholder="该流转未在工艺路线中定义，请说明原因" />
          </Form.Item>
        )}
        <Form.Item name="owner_id" label="工序负责人">
          <PersonnelSelect personnel={personnel} allowClear />
        </Form.Item>
        <Form.Item name="equipment_ids" label="使用设备">
          <Select
            mode="multiple"
            allowClear
            showSearch
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
            options={(equipmentData?.items ?? []).map(
              (e: { id: string; name: string; equipment_no: string }) => ({
                value: e.id,
                label: `${e.name}（${e.equipment_no}）`,
              }),
            )}
          />
        </Form.Item>
        <DynamicFieldFormItems defs={startDefs} />
        {inputIntermediates.length > 0 && (
          <>
            <div style={{ marginBottom: 8, fontWeight: 600, fontSize: 13, color: '#555' }}>
              中间体消耗
            </div>
            {outputsError && (
              <div style={{ marginBottom: 8, color: '#ff4d4f', fontSize: 12 }}>
                可用产出加载失败，请稍后重试
              </div>
            )}
            {inputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{ marginBottom: 8, padding: 8, background: '#fafafa', borderRadius: 6 }}>
                <span style={{ fontSize: 12, color: '#888' }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required ? ' *' : ''}
                </span>
                <Form.Item
                  name={`consume_output_${im.intermediate_type_id}`}
                  label="选择产出批次"
                  rules={im.required ? [{ required: true, message: '请选择' }] : undefined}
                  style={{ marginBottom: 4 }}
                >
                  <Select size="small" mode="multiple" options={getOutputOptions(im.intermediate_type_id)} placeholder="选择上游产出" allowClear showSearch filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                </Form.Item>
                {(() => {
                  const selectedIds = (watchedValues?.[`consume_output_${im.intermediate_type_id}`] as string[]) ?? []
                  return selectedIds.map(outputId => {
                    const output = (batchOutputs ?? []).find(o => o.id === outputId)
                    const label = output
                      ? (output.intermediate_batch_no ?? output.batch_no ?? outputId.slice(0, 8))
                      : outputId.slice(0, 8)
                    return (
                      <Form.Item
                        key={outputId}
                        name={`consume_qty_${im.intermediate_type_id}_${outputId}`}
                        label={`消耗数量 · ${label}`}
                        rules={im.required ? [{ required: true, message: '请输入' }] : undefined}
                        style={{ marginBottom: 4 }}
                      >
                        <Input size="small" type="number" placeholder="数量" />
                      </Form.Item>
                    )
                  })
                })()}
                <Form.Item name={`consume_remark_${im.intermediate_type_id}`} label="备注" style={{ marginBottom: 0 }}>
                  <Input size="small" placeholder="可选" />
                </Form.Item>
              </div>
            ))}
          </>
        )}
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
