'use client'

import { useState } from 'react'
import {
  Drawer,
  Button,
  Form,
  Input,
  Select,
  Switch,
  Collapse,
  Space,
  Tag,
  Typography,
  App,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  CaretRightOutlined,
} from '@ant-design/icons'
import type { AIWorkflowConfig, WorkflowStepItem, ReferenceDocsValue } from '@/types/safety'
import { TRIGGER_EVENT_OPTIONS } from '@/types/safety'
import { updateAIWorkflowConfig, createAIWorkflowConfig } from '@/actions/safety'
import ReferenceDocsEditor from './ReferenceDocsEditor'

const { Text, Title } = Typography
const { TextArea } = Input

interface Props {
  open: boolean
  workflow: AIWorkflowConfig | null
  onClose: () => void
  onSaved: () => void
}

const SECTION_GAP = 24
const TEXTAREA_ROWS = 5

export default function WorkflowEditDrawer({ open, workflow, onClose, onSaved }: Props) {
  const { message } = App.useApp()
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [activeScriptKeys, setActiveScriptKeys] = useState<string[]>(['0'])

  // Reset form when workflow changes
  const handleOpen = () => {
    if (workflow) {
      form.setFieldsValue({
        workflow_name: workflow.workflow_name,
        workflow_description: workflow.workflow_description,
        trigger_event: workflow.trigger_event,
        is_enabled: workflow.is_enabled,
        script_configs: (workflow.script_configs || []).map((s) => ({
          ...s,
          // Ensure 4-field format with backward compat
          input_info: s.input_info || s.prompt_template || '',
          work_rules: s.work_rules || '',
          // reference_docs 兼容旧字符串格式 → 新对象格式
          reference_docs:
            typeof s.reference_docs === 'string'
              ? { text: s.reference_docs, attachments: [] }
              : s.reference_docs || { text: '', attachments: [] },
          output_format: s.output_format || '',
        })),
      })
      setActiveScriptKeys(['0'])
    }
  }

  const handleSave = async () => {
    if (!workflow) return
    try {
      const values = await form.validateFields()
      setSaving(true)

      // 保存原始数据引用，用于合并 expected_keys（前端表单不展示此字段）
      const origScripts = workflow.script_configs || []

      // Strip prompt_template for clean 4-field storage
      const cleanScripts = (values.script_configs || []).map(
        (s: WorkflowStepItem & { prompt_template?: string }, i: number) => {
          const { prompt_template, ...rest } = s
          // 合并预设的 expected_keys（表单中不展示，从原始数据回填）
          return {
            ...rest,
            expected_keys: origScripts[i]?.expected_keys || rest.expected_keys || [],
          }
        },
      )

      const isBuiltIn = String(workflow.id).startsWith('builtin-')
      let res
      if (isBuiltIn) {
        // 内置工作流：创建新 DB 记录
        res = await createAIWorkflowConfig({
          module_code: workflow.module_code,
          workflow_name: values.workflow_name,
          workflow_description: values.workflow_description,
          trigger_event: values.trigger_event,
          is_enabled: values.is_enabled,
          script_configs: cleanScripts,
          sort_order: 99,
        })
      } else {
        res = await updateAIWorkflowConfig(workflow.id, {
          ...values,
          script_configs: cleanScripts,
        })
      }
      if (res.data) {
        message.success(isBuiltIn ? '工作流已创建' : '配置已保存')
        onSaved()
        onClose()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      // validation error
    } finally {
      setSaving(false)
    }
  }

  const handleResetScript = (index: number) => {
    const scripts: WorkflowStepItem[] = form.getFieldValue('script_configs') || []
    if (scripts[index]) {
      const updated = [...scripts]
      updated[index] = {
        ...updated[index],
        input_info: '',
        work_rules: '',
        reference_docs: { text: '', attachments: [] } as ReferenceDocsValue,
        output_format: '',
      }
      form.setFieldsValue({ script_configs: updated })
    }
  }

  return (
    <Drawer
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>编辑工作流</span>
          {workflow && (
            <Tag color="purple" style={{ borderRadius: 6 }}>
              {workflow.workflow_name}
            </Tag>
          )}
        </div>
      }
      open={open}
      onClose={onClose}
      size={720}
      afterOpenChange={(visible) => { if (visible) handleOpen() }}
      extra={
        <Space>
          <Button onClick={onClose} style={{ borderRadius: 8 }}>取消</Button>
          <Button
            type="primary"
            onClick={handleSave}
            loading={saving}
            style={{ borderRadius: 8, background: '#5645d4' }}
          >
            保存配置
          </Button>
        </Space>
      }
      styles={{
        body: { padding: '16px 24px', background: '#f6f5f4' },
        header: { borderBottom: '1px solid #e5e3df' },
        footer: { borderTop: '1px solid #e5e3df' },
      }}
    >
      <Form form={form} layout="vertical" style={{ maxWidth: '100%' }}>
        {/* ── Basic Info ── */}
        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            padding: 20,
            marginBottom: SECTION_GAP,
          }}
        >
          <Text strong style={{ fontSize: 14, color: '#37352f', display: 'block', marginBottom: 16 }}>
            基本信息
          </Text>

          <Form.Item
            name="workflow_name"
            label={<span style={{ fontSize: 13, color: '#787671' }}>工作流名称</span>}
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input
              placeholder="工作流名称"
              style={{ borderRadius: 8 }}
            />
          </Form.Item>

          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item
              name="trigger_event"
              label={<span style={{ fontSize: 13, color: '#787671' }}>触发方式</span>}
              style={{ flex: 1 }}
            >
              <Select
                options={TRIGGER_EVENT_OPTIONS}
                placeholder="选择触发方式"
                allowClear
                style={{ width: '100%' }}
              />
            </Form.Item>

            <Form.Item
              name="is_enabled"
              label={<span style={{ fontSize: 13, color: '#787671' }}>启用状态</span>}
              valuePropName="checked"
            >
              <Switch
                checkedChildren="已启用"
                unCheckedChildren="已停用"
                style={{ borderRadius: 9999 }}
              />
            </Form.Item>
          </div>

          <Form.Item
            name="workflow_description"
            label={<span style={{ fontSize: 13, color: '#787671' }}>描述</span>}
            style={{ marginBottom: 0 }}
          >
            <TextArea rows={2} placeholder="工作流功能描述" style={{ borderRadius: 8 }} />
          </Form.Item>
        </div>

        {/* ── Script Steps ── */}
        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            padding: 20,
            marginBottom: SECTION_GAP,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 16,
            }}
          >
            <Text strong style={{ fontSize: 14, color: '#37352f' }}>
              工作流步骤
            </Text>
          </div>

          <Form.List name="script_configs">
            {(fields, { add }) => (
              <>
                <Collapse
                  activeKey={activeScriptKeys}
                  onChange={(keys) => setActiveScriptKeys(Array.isArray(keys) ? keys as string[] : [keys as string])}
                  expandIcon={({ isActive }) => (
                    <CaretRightOutlined rotate={isActive ? 90 : 0} />
                  )}
                  style={{ background: 'transparent' }}
                  expandIconPlacement="end"
                  items={fields.map(({ key, name, ...restField }) => {
                    const scriptNum = name + 1
                    const formValues = form.getFieldValue('script_configs') || []
                    const scriptData = formValues[name] || {}

                    return {
                      key: String(name),
                      style: {
                        marginBottom: 8,
                        borderRadius: 8,
                        border: '1px solid #e5e3df',
                        background: activeScriptKeys.includes(String(name)) ? '#f6f5f4' : '#fafaf9',
                      },
                      label: (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Tag color="blue" style={{ borderRadius: 6, margin: 0 }}>
                            步骤 {scriptNum}
                          </Tag>
                          <Form.Item
                            {...restField}
                            name={[name, 'name']}
                            noStyle
                            rules={[{ required: true, message: '请输入步骤名称' }]}
                          >
                            <Input
                              placeholder="步骤名称"
                              variant="borderless"
                              style={{ width: 220, fontFamily: 'inherit' }}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            name={[name, 'is_enabled']}
                            noStyle
                            valuePropName="checked"
                          >
                            <Switch size="small" style={{ borderRadius: 9999 }} />
                          </Form.Item>
                        </div>
                      ),
                      children: (
                        <div style={{ padding: '4px 0' }}>
                          <Form.Item
                            {...restField}
                            name={[name, 'input_info']}
                            label={<span style={{ fontSize: 12, fontWeight: 600, color: '#37352f' }}>📥 输入信息</span>}
                            help={<span style={{ fontSize: 11, color: '#bbb8b1' }}>Agent 需要读取哪些信息（可包含 {'{context}'} 等占位符）</span>}
                            style={{ marginBottom: 16 }}
                          >
                            <TextArea
                              rows={TEXTAREA_ROWS}
                              placeholder="描述此步骤读取的输入信息、数据来源、前置依赖..."
                              style={{ borderRadius: 8, fontFamily: 'monospace', fontSize: 13 }}
                            />
                          </Form.Item>

                          <Form.Item
                            {...restField}
                            name={[name, 'work_rules']}
                            label={<span style={{ fontSize: 12, fontWeight: 600, color: '#37352f' }}>📐 工作规则</span>}
                            help={<span style={{ fontSize: 11, color: '#bbb8b1' }}>明确目的、要求和限制条件</span>}
                            style={{ marginBottom: 16 }}
                          >
                            <TextArea
                              rows={TEXTAREA_ROWS}
                              placeholder="描述任务目标、执行原则、约束条件..."
                              style={{ borderRadius: 8, fontFamily: 'monospace', fontSize: 13 }}
                            />
                          </Form.Item>

                          <Form.Item
                            {...restField}
                            name={[name, 'reference_docs']}
                            label={<span style={{ fontSize: 12, fontWeight: 600, color: '#37352f' }}>📚 调用文档</span>}
                            help={<span style={{ fontSize: 11, color: '#bbb8b1' }}>引用标准规范、知识库内容、参考文档；可上传附件自动转为 Markdown 供 AI 读取</span>}
                            style={{ marginBottom: 16 }}
                          >
                            <ReferenceDocsEditor />
                          </Form.Item>

                          <Form.Item
                            {...restField}
                            name={[name, 'output_format']}
                            label={<span style={{ fontSize: 12, fontWeight: 600, color: '#37352f' }}>📤 输出格式</span>}
                            help={<span style={{ fontSize: 11, color: '#bbb8b1' }}>描述你希望 AI 输出的内容格式，如"输出为标准 PDF"、"按标准分点输出"、"输出 JSON 结构化数据"等</span>}
                            style={{ marginBottom: 0 }}
                          >
                            <TextArea
                              rows={TEXTAREA_ROWS}
                              placeholder={'描述你希望 AI 以什么格式输出内容，例如：\n- 输出为标准 PDF 格式报告\n- 按以下分点逐条输出：…\n- 输出 JSON 格式（默认）：{"field1": "…", "field2": "…"}'}
                              style={{ borderRadius: 8, fontFamily: 'monospace', fontSize: 13 }}
                            />
                          </Form.Item>

                          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
                            <Button
                              size="small"
                              onClick={() => handleResetScript(name)}
                              style={{ borderRadius: 8, color: '#bbb8b1' }}
                            >
                              重置默认
                            </Button>
                          </div>
                        </div>
                      ),
                    }
                  })}
                />

                {/* Add script step button is hidden — workflows are predefined */}
              </>
            )}
          </Form.List>
        </div>

        {/* ── API 模型选择（信息提示）── */}
        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            padding: 20,
          }}
        >
          <Text strong style={{ fontSize: 14, color: '#37352f', display: 'block', marginBottom: 8 }}>
            API 模型
          </Text>
          <Text style={{ fontSize: 13, color: '#787671' }}>
            所有工作流统一使用系统 API 配置（在"API调用配置"页面管理），
            不再单独为每个工作流指定模型参数。
          </Text>
        </div>
      </Form>
    </Drawer>
  )
}
