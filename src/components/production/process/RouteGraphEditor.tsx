'use client'

import { useState } from 'react'
import { App, Button, Checkbox, Input, Popconfirm, Select, Space, Table } from 'antd'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { saveRouteGraph } from '@/actions/production'
import type {
  EdgeIn,
  NodeIn,
  RouteGraph,
  RouteNode,
} from '@/types/production'
import { NodeFieldsDrawer } from './NodeFieldsDrawer'
import { NodeIntermediatesEditor } from './NodeIntermediatesEditor'

/** 后端 RouteGraph → 编辑器内部状态（节点带字段；特殊边=非"相邻 normal"边） */
function graphToEditorState(graph: RouteGraph): { nodes: NodeIn[]; extraEdges: EdgeIn[] } {
  const sorted = [...graph.nodes].sort((a, b) => a.sort_order - b.sort_order)
  const codeById = new Map(graph.nodes.map(n => [n.id, n.node_code]))
  const nodes: NodeIn[] = sorted.map((n, i) => ({
    node_code: n.node_code,
    name: n.name,
    stage_name: n.stage_name,
    node_type: n.node_type,
    sort_order: i + 1,
    fields: n.fields.map(f => ({
      field_key: f.field_key,
      field_label: f.field_label,
      field_group: f.field_group,
      phase: f.phase,
      data_type: f.data_type,
      options: f.options,
      unit: f.unit,
      required: f.required,
      min_value: f.min_value,
      max_value: f.max_value,
      sort_order: f.sort_order,
    })),
    intermediates: (n.intermediates ?? []).map(im => ({
      intermediate_type_id: im.intermediate_type_id,
      direction: im.direction,
      unit_override: im.unit_override ?? undefined,
      required: im.required,
      is_product: im.is_product,
      sort_order: im.sort_order,
      remark: im.remark ?? undefined,
    })),
  }))
  // 相邻 normal 边（自动串联部分）不进特殊边表
  const adjacentPairs = new Set(
    sorted.slice(0, -1).map((n, i) => `${n.node_code}->${sorted[i + 1].node_code}`),
  )
  const extraEdges: EdgeIn[] = graph.edges
    .map(e => ({
      from_node_code: codeById.get(e.from_node_id) ?? '',
      to_node_code: codeById.get(e.to_node_id) ?? '',
      edge_type: e.edge_type,
      is_batch_boundary: e.is_batch_boundary,
      allow_overlap: e.allow_overlap,
      remark: e.remark,
    }))
    .filter(
      e =>
        !(
          e.edge_type === 'normal' &&
          !e.is_batch_boundary &&
          adjacentPairs.has(`${e.from_node_code}->${e.to_node_code}`)
        ),
    )
  return { nodes, extraEdges }
}

/** 编辑器状态 → 后端 RouteGraphIn：相邻自动 normal 边 + 特殊边合并去重 */
function editorStateToGraphIn(nodes: NodeIn[], extraEdges: EdgeIn[]): {
  nodes: NodeIn[]
  edges: EdgeIn[]
} {
  const autoEdges: EdgeIn[] = nodes.slice(0, -1).map((n, i) => ({
    from_node_code: n.node_code,
    to_node_code: nodes[i + 1].node_code,
    edge_type: 'normal' as const,
    is_batch_boundary: false,
    allow_overlap: false,
  }))
  const seen = new Set<string>()
  const merged: EdgeIn[] = []
  // 特殊边优先（可覆盖同 from/to 的自动边，如相邻但标了批次边界）
  for (const e of [...extraEdges, ...autoEdges]) {
    const key = `${e.from_node_code}->${e.to_node_code}:${e.edge_type}`
    const pairKey = `${e.from_node_code}->${e.to_node_code}`
    if (e.edge_type === 'normal' && seen.has(`pair:${pairKey}`)) continue
    if (seen.has(key)) continue
    seen.add(key)
    if (e.edge_type === 'normal') seen.add(`pair:${pairKey}`)
    merged.push(e)
  }
  return { nodes: nodes.map((n, i) => ({ ...n, sort_order: i + 1 })), edges: merged }
}

interface Props {
  routeId: string
  graph: RouteGraph
  onCancel: () => void
  onSaved: () => void
}

export function RouteGraphEditor({ routeId, graph, onCancel, onSaved }: Props) {
  const { message } = App.useApp()
  const [initial] = useState(() => graphToEditorState(graph))
  const [nodes, setNodes] = useState<NodeIn[]>(initial.nodes)
  const [extraEdges, setExtraEdges] = useState<EdgeIn[]>(initial.extraEdges)
  const [fieldsIdx, setFieldsIdx] = useState<number | null>(null)
  const [intermediatesIdx, setIntermediatesIdx] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= nodes.length) return
    const next = [...nodes]
    ;[next[i], next[j]] = [next[j], next[i]]
    setNodes(next)
  }

  const updateNode = (i: number, patch: Partial<NodeIn>) =>
    setNodes(nodes.map((n, idx) => (idx === i ? { ...n, ...patch } : n)))

  const addNode = () =>
    setNodes([
      ...nodes,
      {
        node_code: `N${nodes.length + 1}`,
        name: '',
        stage_name: null,
        node_type: 'process',
        sort_order: nodes.length + 1,
        fields: [],
      },
    ])

  const removeNode = (i: number) => {
    const code = nodes[i].node_code
    setNodes(nodes.filter((_, idx) => idx !== i))
    setExtraEdges(extraEdges.filter(e => e.from_node_code !== code && e.to_node_code !== code))
  }

  const updateEdge = (i: number, patch: Partial<EdgeIn>) =>
    setExtraEdges(extraEdges.map((e, idx) => (idx === i ? { ...e, ...patch } : e)))

  const nodeOptions = nodes.map(n => ({
    value: n.node_code,
    label: `${n.name || '未命名'}（${n.node_code}）`,
  }))

  const handleSave = async () => {
    // 前端预校验
    const codes = nodes.map(n => n.node_code)
    if (new Set(codes).size !== codes.length) {
      message.error('节点编码重复')
      return
    }
    if (nodes.some(n => !n.node_code || !n.name)) {
      message.error('节点编码和名称不能为空')
      return
    }
    for (const e of extraEdges) {
      if (!codes.includes(e.from_node_code) || !codes.includes(e.to_node_code)) {
        message.error('特殊边引用了不存在的节点')
        return
      }
      if (e.edge_type === 'rework' && e.is_batch_boundary) {
        message.error('回流边不允许标记批次边界')
        return
      }
      if (e.is_batch_boundary && e.allow_overlap) {
        message.error('批次边界边不允许开启流水线模式')
        return
      }
    }
    setSaving(true)
    const payload = editorStateToGraphIn(nodes, extraEdges)
    const result = await saveRouteGraph(routeId, payload)
    setSaving(false)
    if (result.success) {
      message.success('工艺已保存')
      onSaved()
    } else {
      message.error(result.error)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 8, fontWeight: 600 }}>工序节点（按顺序自动串联）</div>
      <Table<NodeIn>
        size="small"
        rowKey="node_code"
        dataSource={nodes}
        pagination={false}
        columns={[
          {
            title: '#',
            width: 40,
            render: (_, __, i) => i + 1,
          },
          {
            title: '编码',
            width: 110,
            render: (_, n, i) => (
              <Input
                size="small"
                value={n.node_code}
                onChange={e => updateNode(i, { node_code: e.target.value })}
              />
            ),
          },
          {
            title: '工序名称',
            render: (_, n, i) => (
              <Input
                size="small"
                value={n.name}
                onChange={e => updateNode(i, { name: e.target.value })}
              />
            ),
          },
          {
            title: '工段',
            width: 120,
            render: (_, n, i) => (
              <Input
                size="small"
                placeholder="如 发酵"
                value={n.stage_name ?? ''}
                onChange={e => updateNode(i, { stage_name: e.target.value || null })}
              />
            ),
          },
          {
            title: '字段',
            width: 90,
            render: (_, n, i) => (
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => setFieldsIdx(i)}
              >
                {n.fields.length}
              </Button>
            ),
          },
          {
            title: '消耗',
            width: 80,
            render: (_, n, i) => {
              const count = (n.intermediates ?? []).filter(im => im.direction === 'input').length
              return (
                <Button
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => setIntermediatesIdx(i)}
                >
                  {count || '0'}
                </Button>
              )
            },
          },
          {
            title: '产出',
            width: 80,
            render: (_, n, i) => {
              const count = (n.intermediates ?? []).filter(im => im.direction === 'output').length
              return (
                <Button
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => setIntermediatesIdx(i)}
                >
                  {count || '0'}
                </Button>
              )
            },
          },
          {
            title: '操作',
            width: 120,
            render: (_, __, i) => (
              <Space size={0}>
                <Button size="small" type="text" icon={<ArrowUpOutlined />} onClick={() => move(i, -1)} />
                <Button size="small" type="text" icon={<ArrowDownOutlined />} onClick={() => move(i, 1)} />
                <Popconfirm title="删除该节点？" onConfirm={() => removeNode(i)}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Button size="small" icon={<PlusOutlined />} onClick={addNode} style={{ marginTop: 8 }}>
        添加工序
      </Button>

      <div style={{ margin: '16px 0 8px', fontWeight: 600 }}>
        特殊流转（分叉 / 回流 / 批次边界）
      </div>
      <Table<EdgeIn>
        size="small"
        rowKey={(e) => `${e.from_node_code}-${e.to_node_code}-${e.edge_type}-${e.is_batch_boundary}`}
        dataSource={extraEdges}
        pagination={false}
        columns={[
          {
            title: '从',
            width: 160,
            render: (_, e, i) => (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={e.from_node_code || undefined}
                options={nodeOptions}
                onChange={v => updateEdge(i, { from_node_code: v })}
              />
            ),
          },
          {
            title: '到',
            width: 160,
            render: (_, e, i) => (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={e.to_node_code || undefined}
                options={nodeOptions}
                onChange={v => updateEdge(i, { to_node_code: v })}
              />
            ),
          },
          {
            title: '类型',
            width: 100,
            render: (_, e, i) => (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={e.allow_overlap ? 'pipeline' : e.edge_type}
                options={[
                  { value: 'normal', label: '正常' },
                  { value: 'pipeline', label: '流水线' },
                  { value: 'rework', label: '回流' },
                ]}
                onChange={v => {
                  if (v === 'pipeline') {
                    updateEdge(i, { edge_type: 'normal', allow_overlap: true, is_batch_boundary: false })
                  } else if (v === 'rework') {
                    updateEdge(i, { edge_type: 'rework', allow_overlap: false, is_batch_boundary: false })
                  } else {
                    updateEdge(i, { edge_type: 'normal', allow_overlap: false })
                  }
                }}
              />
            ),
          },
          {
            title: '批次边界',
            width: 80,
            render: (_, e, i) => (
              <Checkbox
                checked={e.is_batch_boundary}
                disabled={e.edge_type === 'rework' || !!e.allow_overlap}
                onChange={ev => updateEdge(i, { is_batch_boundary: ev.target.checked })}
              />
            ),
          },
          {
            title: '备注',
            render: (_, e, i) => (
              <Input
                size="small"
                placeholder="如 不合格时"
                value={e.remark ?? ''}
                onChange={ev => updateEdge(i, { remark: ev.target.value || null })}
              />
            ),
          },
          {
            title: '',
            width: 40,
            render: (_, __, i) => (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => setExtraEdges(extraEdges.filter((_, idx) => idx !== i))}
              />
            ),
          },
        ]}
      />
      <Button
        size="small"
        icon={<PlusOutlined />}
        style={{ marginTop: 8 }}
        onClick={() =>
          setExtraEdges([
            ...extraEdges,
            { from_node_code: '', to_node_code: '', edge_type: 'normal', is_batch_boundary: false, allow_overlap: false },
          ])
        }
      >
        添加流转
      </Button>

      <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button onClick={onCancel}>取消</Button>
        <Button type="primary" loading={saving} onClick={handleSave}>
          保存工艺
        </Button>
      </div>

      <NodeFieldsDrawer
        open={fieldsIdx !== null}
        node={
          fieldsIdx !== null
            ? ({
                id: String(fieldsIdx),
                node_code: nodes[fieldsIdx].node_code,
                name: nodes[fieldsIdx].name,
                stage_name: nodes[fieldsIdx].stage_name ?? null,
                node_type: 'process',
                sort_order: fieldsIdx + 1,
                fields: nodes[fieldsIdx].fields.map((f, fi) => ({
                  ...f,
                  id: String(fi),
                  node_id: String(fieldsIdx),
                  field_group: f.field_group ?? null,
                  options: f.options ?? null,
                  unit: f.unit ?? null,
                  min_value: f.min_value ?? null,
                  max_value: f.max_value ?? null,
                })),
              } as RouteNode)
            : null
        }
        editable
        onClose={() => setFieldsIdx(null)}
        onSave={fields => {
          if (fieldsIdx !== null) updateNode(fieldsIdx, { fields })
          setFieldsIdx(null)
        }}
      />
      <NodeIntermediatesEditor
        open={intermediatesIdx !== null}
        intermediates={
          intermediatesIdx !== null ? nodes[intermediatesIdx].intermediates ?? [] : []
        }
        nodeName={
          intermediatesIdx !== null ? nodes[intermediatesIdx].name || nodes[intermediatesIdx].node_code : ''
        }
        onClose={() => setIntermediatesIdx(null)}
        onSave={(ims: NodeIn['intermediates']) => {
          if (intermediatesIdx !== null) updateNode(intermediatesIdx, { intermediates: ims ?? [] })
          setIntermediatesIdx(null)
        }}
      />
    </div>
  )
}
