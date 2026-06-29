'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Input, Select, Switch, InputNumber, Typography, Card, Empty, Button, Space } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { useWorkflowStore } from '@/stores/safety'
import { NODE_TYPES } from '@/types/safety'
import type { GraphNode } from '@/types/safety'

const { TextArea } = Input
const { Text, Title } = Typography

/**
 * Configuration panel for the selected node.
 * Content changes based on node type.
 */

export function NodeConfigPanel() {
  const { nodes, selectedNodeId, setNodes, setSelectedNode } = useWorkflowStore()
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  )

  // Local state for editing
  const [localData, setLocalData] = useState<Record<string, unknown>>({})

  // Sync local state when selected node changes
  useEffect(() => {
    if (selectedNode) {
      setLocalData({ ...selectedNode.data })
    }
  }, [selectedNode?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const updateNodeData = useCallback(
    (patch: Record<string, unknown>) => {
      if (!selectedNode) return
      const updated = {
        ...localData,
        ...patch,
      }
      setLocalData(updated)

      // Also update the node in the store
      setNodes(
        nodes.map((n) =>
          n.id === selectedNode.id
            ? { ...n, data: updated }
            : n,
        ),
      )
    },
    [selectedNode, localData, nodes, setNodes],
  )

  const handleDelete = useCallback(() => {
    if (!selectedNode) return
    setNodes(nodes.filter((n) => n.id !== selectedNode.id))
    setSelectedNode(null)
  }, [selectedNode, nodes, setNodes, setSelectedNode])

  if (!selectedNode) {
    return (
      <div
        style={{
          width: 300,
          padding: 12,
          borderLeft: '1px solid #f0f0f0',
          background: '#fafafa',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Empty description="选择一个节点查看配置" />
      </div>
    )
  }

  const nodeTypeMeta = NODE_TYPES.find((nt) => nt.type === selectedNode.type)

  return (
    <div
      style={{
        width: 300,
        padding: 12,
        borderLeft: '1px solid #f0f0f0',
        background: '#fafafa',
        overflowY: 'auto',
        maxHeight: 'calc(100vh - 300px)',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: `2px solid ${nodeTypeMeta?.color || '#d9d9d9'}`,
        }}
      >
        <div>
          <Title level={5} style={{ margin: 0, fontSize: 14 }}>
            {nodeTypeMeta?.label || selectedNode.type}
          </Title>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {selectedNode.id}
          </Text>
        </div>
        <Button
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={handleDelete}
          title="删除节点"
        />
      </div>

      {/* Title */}
      <div style={{ marginBottom: 10 }}>
        <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
          标题
        </Text>
        <Input
          size="small"
          value={(localData.title as string) || ''}
          onChange={(e) => updateNodeData({ title: e.target.value })}
          placeholder="节点标题"
        />
      </div>

      {/* Type-specific config */}
      {renderNodeConfig(selectedNode, localData, updateNodeData)}

      {/* JSON (collapsed) for advanced editing */}
      <Card size="small" title="高级 (JSON)" style={{ marginTop: 8 }}>
        <TextArea
          rows={6}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={JSON.stringify(localData, null, 2)}
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value)
              setLocalData(parsed)
              setNodes(
                nodes.map((n) =>
                  n.id === selectedNode.id ? { ...n, data: parsed } : n,
                ),
              )
            } catch {
              // JSON still being typed, do nothing
            }
          }}
        />
      </Card>
    </div>
  )
}

/** Render type-specific configuration fields */
function renderNodeConfig(
  node: GraphNode,
  data: Record<string, unknown>,
  update: (patch: Record<string, unknown>) => void,
) {
  switch (node.type) {
    case 'start':
      return <StartConfig data={data} update={update} />
    case 'end':
      return <EndConfig data={data} update={update} />
    case 'llm':
      return <LLMConfig data={data} update={update} />
    case 'knowledge-retrieval':
      return <KnowledgeConfig data={data} update={update} />
    case 'code':
      return <CodeConfig data={data} update={update} />
    case 'http-request':
      return <HttpConfig data={data} update={update} />
    case 'if-else':
      return <ConditionConfig data={data} update={update} />
    case 'template-transform':
      return <TemplateConfig data={data} update={update} />
    case 'variable-aggregator':
      return <AggregatorConfig data={data} update={update} />
    default:
      return null
  }
}

// ============ Individual Config Sections ============

interface ConfigProps {
  data: Record<string, unknown>
  update: (patch: Record<string, unknown>) => void
}

function StartConfig({ data, update }: ConfigProps) {
  const variables = (data.variables as Array<Record<string, unknown>>) || []
  return (
    <div>
      <Text strong style={{ fontSize: 12 }}>输入变量</Text>
      <TextArea
        rows={4}
        style={{ fontFamily: 'monospace', fontSize: 11, marginTop: 4 }}
        value={JSON.stringify(variables, null, 2)}
        onChange={(e) => {
          try {
            update({ variables: JSON.parse(e.target.value) })
          } catch {}
        }}
        placeholder='[{"variable": "query", "label": "输入", "type": "text", "required": true}]'
      />
    </div>
  )
}

function EndConfig({ data, update }: ConfigProps) {
  const outputs = (data.outputs as Array<Record<string, unknown>>) || []
  return (
    <div>
      <Text strong style={{ fontSize: 12 }}>输出变量</Text>
      <TextArea
        rows={4}
        style={{ fontFamily: 'monospace', fontSize: 11, marginTop: 4 }}
        value={JSON.stringify(outputs, null, 2)}
        onChange={(e) => {
          try {
            update({ outputs: JSON.parse(e.target.value) })
          } catch {}
        }}
        placeholder='[{"variable": "result", "value_selector": ["llm_1", "output"]}]'
      />
    </div>
  )
}

function LLMConfig({ data, update }: ConfigProps) {
  const model = data.model as Record<string, unknown> || {}
  const promptTemplate = data.prompt_template as Array<Record<string, unknown>> || []
  const expectedKeys = data.expected_keys as string[] || []

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <div>
        <Text strong style={{ fontSize: 12 }}>Provider</Text>
        <Input
          size="small"
          value={(model.provider as string) || 'deepseek'}
          onChange={(e) => update({ model: { ...model, provider: e.target.value } })}
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Model</Text>
        <Input
          size="small"
          value={(model.name as string) || 'deepseek-v4-flash'}
          onChange={(e) => update({ model: { ...model, name: e.target.value } })}
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Temperature</Text>
        <InputNumber
          size="small"
          min={0}
          max={2}
          step={0.01}
          style={{ width: '100%' }}
          value={
            ((model.completion_params as Record<string, unknown>)?.temperature as number) ?? 0.05
          }
          onChange={(v) =>
            update({
              model: {
                ...model,
                completion_params: { ...((model.completion_params as Record<string, unknown>) || {}), temperature: v },
              },
            })
          }
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>System Prompt</Text>
        <TextArea
          rows={3}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={(promptTemplate.find((p) => p.role === 'system')?.text as string) || ''}
          onChange={(e) => {
            const others = promptTemplate.filter((p) => p.role !== 'system')
            update({
              prompt_template: [{ role: 'system', text: e.target.value }, ...others],
            })
          }}
          placeholder="You are..."
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>User Prompt</Text>
        <TextArea
          rows={4}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={(promptTemplate.find((p) => p.role === 'user')?.text as string) || ''}
          onChange={(e) => {
            const others = promptTemplate.filter((p) => p.role !== 'user')
            update({
              prompt_template: [...others, { role: 'user', text: e.target.value }],
            })
          }}
          placeholder="{'{{#start.query#}}'}"
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Expected Keys (JSON 数组)</Text>
        <Input
          size="small"
          value={JSON.stringify(expectedKeys)}
          onChange={(e) => {
            try {
              update({ expected_keys: JSON.parse(e.target.value) })
            } catch {}
          }}
          placeholder='["hazard_type", "possible_accident"]'
        />
      </div>
    </Space>
  )
}

function KnowledgeConfig({ data, update }: ConfigProps) {
  const dazahConfig = data.dazah_config as Record<string, unknown> || {}
  const categories = dazahConfig.categories as string[] || []
  const maxCards = (dazahConfig.max_cards as number) || 3
  const topK = (data.top_k as number) || 5

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <div>
        <Text strong style={{ fontSize: 12 }}>知识类别 (逗号分隔)</Text>
        <Input
          size="small"
          value={categories.join(', ')}
          onChange={(e) =>
            update({
              dazah_config: {
                ...dazahConfig,
                categories: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
              },
            })
          }
          placeholder="laws_regulations, standards"
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Max Cards</Text>
        <InputNumber
          size="small"
          min={1}
          max={10}
          style={{ width: '100%' }}
          value={maxCards}
          onChange={(v) =>
            update({ dazah_config: { ...dazahConfig, max_cards: v } })
          }
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Top-K</Text>
        <InputNumber
          size="small"
          min={1}
          max={20}
          style={{ width: '100%' }}
          value={topK}
          onChange={(v) => update({ top_k: v })}
        />
      </div>
    </Space>
  )
}

function CodeConfig({ data, update }: ConfigProps) {
  return (
    <div>
      <Text strong style={{ fontSize: 12 }}>Python 代码</Text>
      <TextArea
        rows={8}
        style={{ fontFamily: 'monospace', fontSize: 11, marginTop: 4 }}
        value={(data.code as string) || ''}
        onChange={(e) => update({ code: e.target.value })}
        placeholder={'def main(inputs: dict) -> dict:\n    return {"result": inputs}'}
      />
    </div>
  )
}

function HttpConfig({ data, update }: ConfigProps) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <div>
        <Text strong style={{ fontSize: 12 }}>Method</Text>
        <Select
          size="small"
          style={{ width: '100%' }}
          value={(data.method as string) || 'GET'}
          onChange={(v) => update({ method: v })}
          options={['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map((m) => ({
            value: m,
            label: m,
          }))}
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>URL</Text>
        <Input
          size="small"
          value={(data.url as string) || ''}
          onChange={(e) => update({ url: e.target.value })}
          placeholder="https://api.example.com/data"
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>Headers (JSON)</Text>
        <TextArea
          rows={3}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={JSON.stringify(data.headers || {}, null, 2)}
          onChange={(e) => {
            try {
              update({ headers: JSON.parse(e.target.value) })
            } catch {}
          }}
          placeholder='{"Authorization": "Bearer ..."}'
        />
      </div>
    </Space>
  )
}

function ConditionConfig({ data, update }: ConfigProps) {
  const conditions = (data.conditions as Array<Record<string, unknown>>) || []
  return (
    <div>
      <Text strong style={{ fontSize: 12 }}>条件列表 (JSON)</Text>
      <TextArea
        rows={6}
        style={{ fontFamily: 'monospace', fontSize: 11, marginTop: 4 }}
        value={JSON.stringify(conditions, null, 2)}
        onChange={(e) => {
          try {
            update({ conditions: JSON.parse(e.target.value) })
          } catch {}
        }}
        placeholder={`[{"variable_selector": ["start", "type"], "operator": "==", "value": "hazard"}]`}
      />
    </div>
  )
}

function TemplateConfig({ data, update }: ConfigProps) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <div>
        <Text strong style={{ fontSize: 12 }}>输出变量名</Text>
        <Input
          size="small"
          value={(data.output_variable as string) || ''}
          onChange={(e) => update({ output_variable: e.target.value })}
          placeholder="formatted_output"
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>模板</Text>
        <TextArea
          rows={5}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={(data.template as string) || ''}
          onChange={(e) => update({ template: e.target.value })}
          placeholder='{"{{#start.query#}}"}'
        />
      </div>
    </Space>
  )
}

function AggregatorConfig({ data, update }: ConfigProps) {
  const variables = (data.variables as Array<Record<string, unknown>>) || []
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <div>
        <Text strong style={{ fontSize: 12 }}>输出类型</Text>
        <Select
          size="small"
          style={{ width: '100%' }}
          value={(data.output_type as string) || 'object'}
          onChange={(v) => update({ output_type: v })}
          options={[
            { value: 'object', label: 'Object (默认)' },
            { value: 'array', label: 'Array' },
          ]}
        />
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>聚合变量 (JSON)</Text>
        <TextArea
          rows={4}
          style={{ fontFamily: 'monospace', fontSize: 11 }}
          value={JSON.stringify(variables, null, 2)}
          onChange={(e) => {
            try {
              update({ variables: JSON.parse(e.target.value) })
            } catch {}
          }}
          placeholder={`[{"variable": "output1", "value_selector": ["prev_node", "field"]}]`}
        />
      </div>
    </Space>
  )
}
