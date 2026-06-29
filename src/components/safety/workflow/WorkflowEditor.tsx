'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Input, Space, Card, App, Switch, Typography, Collapse } from 'antd'
import { SaveOutlined, PlayCircleOutlined } from '@ant-design/icons'
import {
  createWorkflowDefinition,
  updateWorkflowDefinition,
  runWorkflow,
} from '@/actions/workflow'
import { useWorkflowStore } from '@/stores/safety'
import { WorkflowCanvas } from './WorkflowCanvas'
import { NodePalette } from './NodePalette'
import { NodeConfigPanel } from './NodeConfigPanel'
import { WorkflowRunPanel } from './WorkflowRunPanel'
import type { WorkflowDefResponse } from '@/types/safety'

const { Text } = Typography

interface Props {
  id: string
  initialData: WorkflowDefResponse | null
}

const DEFAULT_GRAPH = {
  nodes: [
    {
      id: 'start',
      type: 'start',
      position: { x: 80, y: 250 },
      data: {
        title: 'Start',
        type: 'start',
        variables: [
          { variable: 'query', label: '输入', type: 'text', required: true },
        ],
      },
    },
    {
      id: 'end',
      type: 'end',
      position: { x: 600, y: 250 },
      data: {
        title: 'End',
        type: 'end',
        outputs: [{ variable: 'result', value_selector: ['start', 'query'] }],
      },
    },
  ],
  edges: [
    {
      id: 'e1',
      source: 'start',
      target: 'end',
      sourceHandle: 'source',
      targetHandle: 'target',
    },
  ],
}

export function WorkflowEditor({ id, initialData }: Props) {
  const router = useRouter()
  const { message } = App.useApp()

  const [name, setName] = useState(initialData?.name || '')
  const [moduleCode, setModuleCode] = useState(initialData?.module_code || '')
  const [isEnabled, setIsEnabled] = useState(initialData?.is_enabled ?? true)
  const [saving, setSaving] = useState(false)
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null)
  const [running, setRunning] = useState(false)
  const [runInputs, setRunInputs] = useState('{}')

  const { loadGraph, getGraph, isDirty } = useWorkflowStore()

  // Load initial graph data
  useEffect(() => {
    if (initialData?.graph) {
      loadGraph(initialData.graph)
    } else if (id === 'new') {
      loadGraph(DEFAULT_GRAPH)
    }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Save workflow
  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const graph = getGraph()

      if (id === 'new') {
        const result = await createWorkflowDefinition({
          name: name || 'Untitled',
          module_code: moduleCode || `workflow_${Date.now()}`,
          graph,
          is_enabled: isEnabled,
        })
        message.success('创建成功')
        router.push(`/safety/workflow/${result.data.id}`)
      } else {
        await updateWorkflowDefinition(id, {
          name,
          module_code: moduleCode,
          graph,
          is_enabled: isEnabled,
        })
        message.success('保存成功')
      }
      router.refresh()
    } catch (e) {
      message.error(`保存失败: ${e}`)
    } finally {
      setSaving(false)
    }
  }, [id, name, moduleCode, isEnabled, getGraph, message, router])

  // Run workflow
  const handleRun = useCallback(async () => {
    if (id === 'new') {
      message.warning('请先保存工作流再运行')
      return
    }
    setRunning(true)
    setRunResult(null)
    try {
      let inputs: Record<string, unknown>
      try {
        inputs = JSON.parse(runInputs)
      } catch {
        inputs = {}
      }

      const result = await runWorkflow(id, { inputs })
      if (result.code === 200) {
        setRunResult(result.data as unknown as Record<string, unknown>)
      } else {
        message.error(`执行失败: ${result.message}`)
        setRunResult(result as unknown as Record<string, unknown>)
      }
    } catch (e) {
      message.error(`执行失败: ${e}`)
      setRunResult({ error: String(e) })
    } finally {
      setRunning(false)
    }
  }, [id, runInputs, message])

  return (
    <div>
      {/* Metadata bar */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 150 }}>
              <Text strong>名称</Text>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="工作流名称"
              />
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <Text strong>模块代码</Text>
              <Input
                value={moduleCode}
                onChange={(e) => setModuleCode(e.target.value)}
                placeholder="唯一标识，如 hazard-identification-step-1"
              />
            </div>
            <div>
              <Text strong>启用</Text>
              <br />
              <Switch checked={isEnabled} onChange={setIsEnabled} />
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              {isDirty && (
                <Text type="warning" style={{ fontSize: 11 }}>
                  未保存
                </Text>
              )}
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={handleSave}
              >
                保存
              </Button>
              {id !== 'new' && (
                <Button
                  icon={<PlayCircleOutlined />}
                  loading={running}
                  onClick={handleRun}
                  style={{ background: '#52c41a', borderColor: '#52c41a', color: '#fff' }}
                >
                  运行
                </Button>
              )}
            </div>
          </div>
        </Space>
      </Card>

      {/* Canvas area: Palette | Canvas | Config */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, border: '1px solid #f0f0f0', borderRadius: 8 }}>
        <NodePalette />
        <div style={{ flex: 1 }}>
          <WorkflowCanvas />
        </div>
        <NodeConfigPanel />
      </div>

      {/* Run Panel (collapsible) */}
      <Collapse
        items={[
          {
            key: 'run',
            label: '运行面板',
            children: (
              <WorkflowRunPanel
                runInputs={runInputs}
                setRunInputs={setRunInputs}
                runResult={runResult}
                running={running}
              />
            ),
          },
        ]}
        style={{ marginTop: 16 }}
      />
    </div>
  )
}
