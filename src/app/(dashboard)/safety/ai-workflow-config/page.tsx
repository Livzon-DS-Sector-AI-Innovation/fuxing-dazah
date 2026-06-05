'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  InputNumber,
  Typography,
  Space,
  Tag,
  Tabs,
  Spin,
  Popconfirm,
  Descriptions,
  Collapse,
  message,
  Tooltip,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SettingOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
  CodeOutlined,
  SaveOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import {
  getAIWorkflowConfigs,
  createAIWorkflowConfig,
  updateAIWorkflowConfig,
  deleteAIWorkflowConfig,
  getAPICallConfigs,
  createAPICallConfig,
  updateAPICallConfig,
  activateAPICallConfig,
  deleteAPICallConfig,
} from '@/actions/safety'
import {
  SAFETY_MODULE_OPTIONS,
  TRIGGER_EVENT_OPTIONS,
  AI_MODEL_OPTIONS,
} from '@/types/safety'
import type {
  AIWorkflowConfig,
  ScriptConfigItem,
  APICallConfig,
} from '@/types/safety'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

// ==================== AI 工作流配置 Tab ====================

function WorkflowConfigTab() {
  const [configs, setConfigs] = useState<AIWorkflowConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<AIWorkflowConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const loadConfigs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getAIWorkflowConfigs({ page_size: 500 })
      setConfigs(res.data || [])
    } catch (error) {
      console.error('Failed to load AI workflow configs:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfigs()
  }, [loadConfigs])

  const handleCreate = () => {
    setEditingConfig(null)
    form.resetFields()
    form.setFieldsValue({
      is_enabled: true,
      sort_order: 0,
      script_configs: [],
    })
    setModalOpen(true)
  }

  const handleEdit = (record: AIWorkflowConfig) => {
    setEditingConfig(record)
    form.setFieldsValue({
      module_code: record.module_code,
      workflow_name: record.workflow_name,
      workflow_description: record.workflow_description,
      trigger_event: record.trigger_event,
      is_enabled: record.is_enabled,
      script_configs: record.script_configs || [],
      sort_order: record.sort_order,
      notes: record.notes,
    })
    setModalOpen(true)
  }

  const handleDelete = async (id: string) => {
    try {
      const res = await deleteAIWorkflowConfig(id)
      if (res.code === 0) {
        message.success('删除成功')
        loadConfigs()
      } else {
        message.error(res.message || '删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingConfig) {
        const res = await updateAIWorkflowConfig(editingConfig.id, values)
        if (res.code === 0) {
          message.success('更新成功')
          setModalOpen(false)
          loadConfigs()
        } else {
          message.error(res.message || '更新失败')
        }
      } else {
        const res = await createAIWorkflowConfig(values)
        if (res.code === 0) {
          message.success('创建成功')
          setModalOpen(false)
          loadConfigs()
        } else {
          message.error(res.message || '创建失败')
        }
      }
    } catch {
      // form validation error
    } finally {
      setSaving(false)
    }
  }

  const handleToggleEnabled = async (record: AIWorkflowConfig) => {
    const res = await updateAIWorkflowConfig(record.id, {
      is_enabled: !record.is_enabled,
    })
    if (res.code === 0) {
      message.success(record.is_enabled ? '已停用' : '已启用')
      loadConfigs()
    } else {
      message.error('操作失败')
    }
  }

  const columns = [
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 70,
      align: 'center' as const,
    },
    {
      title: '所属模块',
      dataIndex: 'module_code',
      key: 'module_code',
      width: 160,
      render: (code: string) => {
        const opt = SAFETY_MODULE_OPTIONS.find((o) => o.value === code)
        return (
          <Space>
            <span>{opt?.icon}</span>
            <span>{opt?.label || code}</span>
          </Space>
        )
      },
    },
    {
      title: '工作流名称',
      dataIndex: 'workflow_name',
      key: 'workflow_name',
      width: 200,
    },
    {
      title: '触发事件',
      dataIndex: 'trigger_event',
      key: 'trigger_event',
      width: 120,
      render: (event: string) => {
        const opt = TRIGGER_EVENT_OPTIONS.find((o) => o.value === event)
        return opt?.label || event || '-'
      },
    },
    {
      title: '脚本数',
      key: 'script_count',
      width: 80,
      align: 'center' as const,
      render: (_: unknown, record: AIWorkflowConfig) => {
        const count = record.script_configs?.length || 0
        return <Tag color={count > 0 ? 'blue' : 'default'}>{count}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 80,
      align: 'center' as const,
      render: (enabled: boolean, record: AIWorkflowConfig) => (
        <Switch
          checked={enabled}
          size="small"
          onChange={() => handleToggleEnabled(record)}
        />
      ),
    },
    {
      title: '描述',
      dataIndex: 'workflow_description',
      key: 'workflow_description',
      ellipsis: true,
      render: (desc: string) => desc || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      align: 'center' as const,
      render: (_: unknown, record: AIWorkflowConfig) => (
        <Space>
          <Tooltip title="编辑">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此配置？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <Text strong className="text-base">AI 工作流配置列表</Text>
          <br />
          <Text type="secondary" className="text-xs">
            为每个安全模块配置独立的 AI 工作流管道，包括脚本步骤、提示词模板和预期输出
          </Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建配置
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={configs}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        expandable={{
          expandedRowRender: (record: AIWorkflowConfig) => (
            <div className="px-4 py-2">
              {record.script_configs && record.script_configs.length > 0 ? (
                <Collapse
                  size="small"
                  items={record.script_configs.map((script: ScriptConfigItem, idx: number) => ({
                    key: String(idx),
                    label: (
                      <Space>
                        <Tag color={script.is_enabled ? 'blue' : 'default'}>
                          脚本 {script.script_number}
                        </Tag>
                        <span>{script.name}</span>
                        <Tag color={script.is_enabled ? 'success' : 'default'}>
                          {script.is_enabled ? '启用' : '停用'}
                        </Tag>
                      </Space>
                    ),
                    children: (
                      <Descriptions size="small" column={2} bordered>
                        <Descriptions.Item label="脚本编号">
                          {script.script_number}
                        </Descriptions.Item>
                        <Descriptions.Item label="脚本名称">
                          {script.name}
                        </Descriptions.Item>
                        <Descriptions.Item label="启用状态">
                          {script.is_enabled ? '✅ 启用' : '❌ 停用'}
                        </Descriptions.Item>
                        <Descriptions.Item label="预期输出键">
                          <Space wrap>
                            {script.expected_keys?.map((key: string) => (
                              <Tag key={key} color="geekblue">
                                {key}
                              </Tag>
                            ))}
                          </Space>
                        </Descriptions.Item>
                        {script.description && (
                          <Descriptions.Item label="描述" span={2}>
                            {script.description}
                          </Descriptions.Item>
                        )}
                        <Descriptions.Item label="提示词模板" span={2}>
                          <pre className="text-xs bg-[var(--color-fill)] p-2 rounded max-h-48 overflow-auto whitespace-pre-wrap">
                            {script.prompt_template}
                          </pre>
                        </Descriptions.Item>
                      </Descriptions>
                    ),
                  }))}
                />
              ) : (
                <div className="text-center py-6">
                  <Text type="secondary">暂无脚本配置，点击"编辑"添加 AI 工作流脚本步骤</Text>
                </div>
              )}
              {record.notes && (
                <div className="mt-2">
                  <Text type="secondary" className="text-xs">
                    备注：{record.notes}
                  </Text>
                </div>
              )}
            </div>
          ),
        }}
      />

      {/* 创建/编辑 Modal */}
      <Modal
        title={editingConfig ? '编辑 AI 工作流配置' : '新建 AI 工作流配置'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        width={1000}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="module_code"
            label="所属模块"
            rules={[{ required: true, message: '请选择模块' }]}
          >
            <Select
              options={SAFETY_MODULE_OPTIONS.map((o) => ({
                value: o.value,
                label: `${o.icon} ${o.label}`,
              }))}
              placeholder="选择安全模块"
              disabled={!!editingConfig}
            />
          </Form.Item>

          <Space className="w-full" size="middle">
            <Form.Item
              name="workflow_name"
              label="工作流名称"
              rules={[{ required: true, message: '请输入名称' }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="例如：危险源7步AI辨识" />
            </Form.Item>

            <Form.Item name="trigger_event" label="触发事件">
              <Select
                options={TRIGGER_EVENT_OPTIONS}
                placeholder="选择触发事件"
                allowClear
                style={{ width: 160 }}
              />
            </Form.Item>

            <Form.Item name="sort_order" label="排序">
              <InputNumber min={0} max={999} style={{ width: 80 }} />
            </Form.Item>
          </Space>

          <Form.Item name="workflow_description" label="描述">
            <TextArea rows={2} placeholder="工作流功能描述" />
          </Form.Item>

          <Form.Item name="is_enabled" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>

          {/* 脚本步骤配置 */}
          <div className="border-t pt-4 mt-2">
            <Text strong className="block mb-3">脚本步骤配置</Text>
            <Form.List name="script_configs">
              {(fields, { add, remove }) => (
                <>
                  <div className="max-h-96 overflow-y-auto space-y-3">
                    {fields.length === 0 ? (
                      <div className="text-center py-6 text-gray-400 bg-gray-50 rounded">
                        暂无脚本步骤，点击下方按钮添加
                      </div>
                    ) : (
                      fields.map(({ key, name, ...restField }) => (
                        <Card
                          key={key}
                          size="small"
                          className="bg-gray-50"
                          title={
                            <Space>
                              <Tag color="blue">脚本 {name + 1}</Tag>
                              <Form.Item
                                {...restField}
                                name={[name, 'name']}
                                noStyle
                                rules={[{ required: true, message: '请输入脚本名称' }]}
                              >
                                <Input
                                  placeholder="脚本名称"
                                  size="small"
                                  style={{ width: 200 }}
                                  variant="borderless"
                                  className="font-medium"
                                />
                              </Form.Item>
                            </Space>
                          }
                          extra={
                            <Button
                              type="link"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() => remove(name)}
                            />
                          }
                        >
                          <Space className="w-full mb-2" size="small" wrap>
                            <Form.Item
                              {...restField}
                              name={[name, 'script_number']}
                              label="编号"
                              rules={[{ required: true, message: '必填' }]}
                            >
                              <InputNumber min={1} max={99} size="small" style={{ width: 70 }} />
                            </Form.Item>
                            <Form.Item
                              {...restField}
                              name={[name, 'is_enabled']}
                              label="启用"
                              valuePropName="checked"
                            >
                              <Switch size="small" />
                            </Form.Item>
                          </Space>
                          <Form.Item
                            {...restField}
                            name={[name, 'description']}
                            label="描述"
                            className="mb-2"
                          >
                            <Input placeholder="脚本功能简述" size="small" />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            name={[name, 'expected_keys']}
                            label="预期输出键"
                            rules={[{ required: true, message: '至少添加一个输出键' }]}
                            className="mb-2"
                          >
                            <Select
                              mode="tags"
                              placeholder="输入键名后回车"
                              size="small"
                              style={{ width: '100%' }}
                            />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            name={[name, 'prompt_template']}
                            label="提示词模板"
                            rules={[{ required: true, message: '请输入提示词模板' }]}
                            className="mb-0"
                          >
                            <TextArea
                              rows={6}
                              placeholder="提示词模板内容（可包含 {context} 等占位符）"
                              size="small"
                              className="font-mono text-xs"
                            />
                          </Form.Item>
                        </Card>
                      ))
                    )}
                  </div>
                  <Button
                    type="dashed"
                    onClick={() =>
                      add({
                        script_number: fields.length + 1,
                        name: '',
                        prompt_template: '',
                        expected_keys: [],
                        is_enabled: true,
                        description: '',
                      })
                    }
                    icon={<PlusOutlined />}
                    size="small"
                    block
                    className="mt-3"
                  >
                    添加脚本步骤
                  </Button>
                </>
              )}
            </Form.List>
          </div>

          <Form.Item name="notes" label="备注" className="mt-4">
            <TextArea rows={2} placeholder="额外备注信息" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ==================== API 调用配置 Tab ====================

function APICallConfigTab() {
  const [configs, setConfigs] = useState<APICallConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<APICallConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [form] = Form.useForm()

  const loadConfigs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getAPICallConfigs()
      setConfigs(res.data || [])
    } catch (error) {
      console.error('Failed to load API call configs:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfigs()
  }, [loadConfigs])

  const handleCreate = () => {
    setEditingConfig(null)
    form.resetFields()
    form.setFieldsValue({
      temperature: 0.1,
      timeout_seconds: 120,
      is_active: false,
    })
    setModalOpen(true)
  }

  const handleEdit = (record: APICallConfig) => {
    setEditingConfig(record)
    form.setFieldsValue({
      config_name: record.config_name,
      api_base_url: record.api_base_url,
      api_key: record.api_key,
      model_name: record.model_name,
      temperature: record.temperature,
      timeout_seconds: record.timeout_seconds,
      max_tokens: record.max_tokens,
      is_active: record.is_active,
      notes: record.notes,
    })
    setModalOpen(true)
  }

  const handleDelete = async (id: string) => {
    try {
      const res = await deleteAPICallConfig(id)
      if (res.code === 0) {
        message.success('删除成功')
        loadConfigs()
      } else {
        message.error(res.message || '删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingConfig) {
        const res = await updateAPICallConfig(editingConfig.id, values)
        if (res.code === 0) {
          message.success('更新成功')
          setModalOpen(false)
          loadConfigs()
        } else {
          message.error(res.message || '更新失败')
        }
      } else {
        const res = await createAPICallConfig(values)
        if (res.code === 0) {
          message.success('创建成功')
          setModalOpen(false)
          loadConfigs()
        } else {
          message.error(res.message || '创建失败')
        }
      }
    } catch {
      // form validation error
    } finally {
      setSaving(false)
    }
  }

  const handleActivate = async (id: string) => {
    setTestingId(id)
    try {
      const res = await activateAPICallConfig(id)
      if (res.code === 0) {
        message.success('已激活，所有 AI 调用将使用此配置')
        loadConfigs()
      } else {
        message.error(res.message || '激活失败')
      }
    } catch {
      message.error('激活失败')
    } finally {
      setTestingId(null)
    }
  }

  const columns = [
    {
      title: '配置名称',
      dataIndex: 'config_name',
      key: 'config_name',
      width: 180,
      render: (name: string, record: APICallConfig) => (
        <Space>
          {name}
          {record.is_active && <Tag color="success">当前使用</Tag>}
        </Space>
      ),
    },
    {
      title: 'API 地址',
      dataIndex: 'api_base_url',
      key: 'api_base_url',
      ellipsis: true,
      width: 260,
    },
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
      width: 160,
      render: (model: string) => {
        const opt = AI_MODEL_OPTIONS.find((o) => o.value === model)
        return (
          <Tag color="purple">{opt?.label || model}</Tag>
        )
      },
    },
    {
      title: 'Temperature',
      dataIndex: 'temperature',
      key: 'temperature',
      width: 100,
      align: 'center' as const,
    },
    {
      title: '超时(秒)',
      dataIndex: 'timeout_seconds',
      key: 'timeout_seconds',
      width: 80,
      align: 'center' as const,
    },
    {
      title: 'Max Tokens',
      dataIndex: 'max_tokens',
      key: 'max_tokens',
      width: 90,
      align: 'center' as const,
      render: (v: number) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      align: 'center' as const,
      render: (active: boolean) =>
        active ? (
          <Tag color="success" icon={<CheckCircleOutlined />}>
            激活
          </Tag>
        ) : (
          <Tag>未激活</Tag>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      align: 'center' as const,
      render: (_: unknown, record: APICallConfig) => (
        <Space>
          {!record.is_active && (
            <Tooltip title="激活此配置">
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                loading={testingId === record.id}
                onClick={() => handleActivate(record.id)}
              >
                激活
              </Button>
            </Tooltip>
          )}
          <Tooltip title="编辑">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此配置？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <Text strong className="text-base">API 调用配置</Text>
          <br />
          <Text type="secondary" className="text-xs">
            配置 AI 大模型 API 连接参数，所有安全模块的 AI 调用通过统一接口。同一时间仅一个配置生效
          </Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建配置
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={configs}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
      />

      {/* 创建/编辑 Modal */}
      <Modal
        title={editingConfig ? '编辑 API 调用配置' : '新建 API 调用配置'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        width={640}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="config_name"
            label="配置名称"
            rules={[{ required: true, message: '请输入配置名称' }]}
          >
            <Input placeholder="例如：生产环境 GPT-4o" />
          </Form.Item>

          <Form.Item
            name="api_base_url"
            label="API 基础 URL"
            rules={[{ required: true, message: '请输入 API 地址' }]}
          >
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label="API 密钥"
            rules={[{ required: true, message: '请输入 API 密钥' }]}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item
            name="model_name"
            label="模型名称"
            rules={[{ required: true, message: '请选择模型' }]}
          >
            <Select
              options={AI_MODEL_OPTIONS}
              placeholder="选择 AI 模型"
              showSearch
            />
          </Form.Item>

          <Space className="w-full" size="middle">
            <Form.Item name="temperature" label="Temperature">
              <InputNumber min={0} max={2} step={0.1} style={{ width: 100 }} />
            </Form.Item>

            <Form.Item name="timeout_seconds" label="超时(秒)">
              <InputNumber min={10} max={600} style={{ width: 100 }} />
            </Form.Item>

            <Form.Item name="max_tokens" label="Max Tokens">
              <InputNumber min={100} max={128000} style={{ width: 120 }} placeholder="不限" />
            </Form.Item>
          </Space>

          <Form.Item name="is_active" label="激活状态" valuePropName="checked">
            <Switch
              checkedChildren="激活"
              unCheckedChildren="未激活"
            />
          </Form.Item>

          <Form.Item name="notes" label="备注">
            <TextArea rows={2} placeholder="配置说明" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ==================== 主页面 ====================

export default function AIWorkflowConfigPage() {
  const [activeTab, setActiveTab] = useState('workflow')

  const tabItems = [
    {
      key: 'workflow',
      label: (
        <Space>
          <SettingOutlined />
          AI 工作流配置
        </Space>
      ),
      children: <WorkflowConfigTab />,
    },
    {
      key: 'api',
      label: (
        <Space>
          <ApiOutlined />
          API 调用配置
        </Space>
      ),
      children: <APICallConfigTab />,
    },
  ]

  return (
    <div className="space-y-4">
      <div>
        <Title level={4} className="mb-1">AI 工作流配置</Title>
        <Text type="secondary">
          管理所有安全模块的 AI 工作流管道和统一 API 调用接口
        </Text>
      </div>

      <Card variant="borderless" className="shadow-sm">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="large"
        />
      </Card>
    </div>
  )
}
