'use client'

import { useState, useCallback } from 'react'
import { Typography, message } from 'antd'
import { ApiOutlined, CheckCircleOutlined } from '@ant-design/icons'
import type { AIWorkflowConfig } from '@/types/safety'
import { WORKFLOW_MENU_MAP } from '@/types/safety'
import { getAIWorkflowConfigs } from '@/actions/safety'
import AIWorkflowCard from './AIWorkflowCard'
import WorkflowEditDrawer from './WorkflowEditDrawer'
import {
  BUILT_IN_WORKFLOWS,
  EXCLUDED_MODULE_CODES,
} from '@/lib/workflow-templates'

const { Title, Text } = Typography

interface Props {
  initialWorkflows: AIWorkflowConfig[]
  apiConnected: boolean
  apiModelLabel?: string
}

export default function AIWorkflowConfigClient({
  initialWorkflows,
  apiConnected,
  apiModelLabel,
}: Props) {
  const [workflows, setWorkflows] = useState<AIWorkflowConfig[]>(
    () => initialWorkflows.filter((w) => !EXCLUDED_MODULE_CODES.has(w.module_code)),
  )
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingWorkflow, setEditingWorkflow] = useState<AIWorkflowConfig | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await getAIWorkflowConfigs({ page_size: 500 })
      setWorkflows(
        (res.data || []).filter((w) => !EXCLUDED_MODULE_CODES.has(w.module_code)),
      )
    } catch {
      message.error('刷新失败')
    }
  }, [])

  // Merge DB configs with built-in workflows
  const allWorkflows = [...workflows]
  for (const builtIn of BUILT_IN_WORKFLOWS) {
    if (!allWorkflows.find((w) => w.module_code === builtIn.module_code)) {
      allWorkflows.push({
        id: `builtin-${builtIn.module_code}`,
        module_code: builtIn.module_code,
        workflow_name: builtIn.workflow_name,
        workflow_description: builtIn.workflow_description,
        trigger_event: builtIn.trigger_event,
        is_enabled: true,
        script_configs: builtIn.script_configs,
        sort_order: 99,
        notes: '内置工作流（点击编辑可创建数据库配置）',
        created_at: '',
        updated_at: '',
      })
    }
  }

  // Group by menu group
  const grouped: Record<string, AIWorkflowConfig[]> = {}
  for (const w of allWorkflows) {
    const menu = WORKFLOW_MENU_MAP[w.module_code]
    const group = menu?.group || '其他'
    if (!grouped[group]) grouped[group] = []
    grouped[group].push(w)
  }

  const handleEdit = (workflow: AIWorkflowConfig) => {
    setEditingWorkflow(workflow)
    setDrawerOpen(true)
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      {/* ── Page Header ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 24,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0, color: '#37352f' }}>
            AI 工作流配置
          </Title>
          <Text style={{ fontSize: 14, color: '#787671' }}>
            管理安全管理模块所有 AI Agent 工作流的提示词与参数
          </Text>
        </div>

        {/* API status badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 14px',
            borderRadius: 20,
            background: apiConnected ? '#d9f3e1' : '#fde0ec',
            fontSize: 13,
            fontWeight: 500,
            color: apiConnected ? '#1aae39' : '#e03131',
          }}
        >
          {apiConnected ? (
            <>
              <CheckCircleOutlined />
              API: {apiModelLabel || '已连接'}
            </>
          ) : (
            <>
              <ApiOutlined />
              API: 未连接
            </>
          )}
        </div>
      </div>

      {/* ── Workflow Cards by Group ── */}
      {Object.entries(grouped).map(([group, groupWorkflows]) => (
        <div key={group} style={{ marginBottom: 24 }}>
          {/* Group label */}
          <Text
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: '#bbb8b1',
              textTransform: 'uppercase',
              letterSpacing: 1,
              display: 'block',
              marginBottom: 12,
              paddingLeft: 4,
            }}
          >
            {group}
          </Text>

          {groupWorkflows
            .sort((a, b) => a.sort_order - b.sort_order)
            .map((w) => (
              <AIWorkflowCard
                key={w.id}
                workflow={w}
                onEdit={handleEdit}
                onRefresh={refresh}
              />
            ))}
        </div>
      ))}

      {/* ── API Config Link ── */}
      <div
        style={{
          borderRadius: 12,
          border: '1px dashed #c8c4be',
          background: '#fafaf9',
          padding: '16px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              background: '#f0eeec',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 18,
            }}
          >
            🔌
          </div>
          <div>
            <Text style={{ fontSize: 14, fontWeight: 500, color: '#37352f' }}>
              全局 API 连接
            </Text>
            <br />
            <Text style={{ fontSize: 12, color: '#bbb8b1' }}>
              AI 模型连接参数已硬编码配置
            </Text>
          </div>
        </div>
        <a
          style={{
            fontSize: 13,
            color: '#bbb8b1',
            fontWeight: 500,
            textDecoration: 'none',
            cursor: 'default',
          }}
        >
          DeepSeek / Qwen-VL
        </a>
      </div>

      {/* ── Edit Drawer ── */}
      <WorkflowEditDrawer
        open={drawerOpen}
        workflow={editingWorkflow}
        onClose={() => {
          setDrawerOpen(false)
          setEditingWorkflow(null)
        }}
        onSaved={refresh}
      />
    </div>
  )
}
