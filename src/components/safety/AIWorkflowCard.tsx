'use client'

import { Card, Switch, Button, Dropdown, Tag, Typography, Popconfirm, message } from 'antd'
import {
  EditOutlined,
  MoreOutlined,
  DeleteOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  RobotOutlined,
  ExportOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import type { AIWorkflowConfig } from '@/types/safety'
import { WORKFLOW_MENU_MAP, WORKFLOW_ICONS } from '@/types/safety'
import { updateAIWorkflowConfig, deleteAIWorkflowConfig } from '@/actions/safety'

const { Text, Paragraph } = Typography

interface Props {
  workflow: AIWorkflowConfig
  onEdit: (workflow: AIWorkflowConfig) => void
  onRefresh: () => void
}

const CARD_STYLE: React.CSSProperties = {
  borderRadius: 12,
  border: '1px solid #e5e3df',
  background: '#ffffff',
  padding: '20px 20px 16px',
  marginBottom: 12,
}

export default function AIWorkflowCard({ workflow, onEdit, onRefresh }: Props) {
  const menuInfo = WORKFLOW_MENU_MAP[workflow.module_code]
  const icon = WORKFLOW_ICONS[workflow.module_code] || '🤖'
  const scriptCount = workflow.script_configs?.filter((s) => s.is_enabled).length || 0
  const totalScripts = workflow.script_configs?.length || 0

  const handleToggle = async (checked: boolean) => {
    const res = await updateAIWorkflowConfig(workflow.id, { is_enabled: checked })
    if (res.code === 200) {
      message.success(checked ? '已启用' : '已停用')
      onRefresh()
    } else {
      message.error(res.message || '操作失败')
    }
  }

  const handleDelete = async () => {
    const res = await deleteAIWorkflowConfig(workflow.id)
    if (res.code === 200) {
      message.success('已删除')
      onRefresh()
    } else {
      message.error(res.message || '删除失败')
    }
  }

  const moreItems: MenuProps['items'] = [
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      label: '删除配置',
      danger: true,
      onClick: handleDelete,
    },
  ]

  return (
    <Card
      variant="borderless"
      style={{
        ...CARD_STYLE,
        opacity: workflow.is_enabled ? 1 : 0.65,
        background: workflow.is_enabled ? '#ffffff' : '#f6f5f4',
      }}
      styles={{ body: { padding: 0 } }}
    >
      {/* Top row: icon + info + actions */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
        {/* Icon */}
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            background: '#f0eeec',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>

        {/* Info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text
              strong
              style={{ fontSize: 16, fontWeight: 500, color: '#37352f', lineHeight: 1.55 }}
            >
              {workflow.workflow_name}
            </Text>
            {!workflow.is_enabled && (
              <Tag color="default" style={{ fontSize: 11, borderRadius: 6 }}>
                已停用
              </Tag>
            )}
          </div>

          {workflow.workflow_description && (
            <Paragraph
              style={{
                fontSize: 14,
                fontWeight: 400,
                color: '#787671',
                margin: '4px 0 0',
                lineHeight: 1.5,
              }}
              ellipsis={{ rows: 2 }}
            >
              {workflow.workflow_description}
            </Paragraph>
          )}

          {/* Meta row */}
          <div
            style={{
              display: 'flex',
              gap: 16,
              marginTop: 8,
              fontSize: 12,
              fontWeight: 500,
              color: '#bbb8b1',
              lineHeight: 1.4,
              flexWrap: 'wrap',
            }}
          >
            {menuInfo && (
              <span>
                <FileTextOutlined style={{ marginRight: 4 }} />
                {menuInfo.group} · {menuInfo.subgroup}
              </span>
            )}
            <span>
              <ThunderboltOutlined style={{ marginRight: 4 }} />
              步骤: {scriptCount}/{totalScripts}
            </span>
            {workflow.trigger_event && (
              <span>
                <RobotOutlined style={{ marginRight: 4 }} />
                触发: {workflow.trigger_event === 'submit' ? '提交时触发' : workflow.trigger_event}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <Popconfirm
            title={workflow.is_enabled ? '确认停用此工作流？' : '确认启用此工作流？'}
            onConfirm={() => handleToggle(!workflow.is_enabled)}
            okText="确认"
            cancelText="取消"
          >
            <Switch
              checked={workflow.is_enabled}
              size="small"
              style={{ borderRadius: 9999 }}
            />
          </Popconfirm>

          <Button
            type="default"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(workflow)}
            style={{ borderRadius: 8, borderColor: '#e5e3df', color: '#37352f' }}
          >
            编辑
          </Button>

          <Dropdown menu={{ items: moreItems }} trigger={['click']} placement="bottomRight">
            <Button
              type="text"
              size="small"
              icon={<MoreOutlined />}
              style={{ borderRadius: 8, color: '#bbb8b1' }}
            />
          </Dropdown>
        </div>
      </div>
    </Card>
  )
}
