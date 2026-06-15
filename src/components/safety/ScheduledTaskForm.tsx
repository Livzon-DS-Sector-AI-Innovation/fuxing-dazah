'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Switch,
  message,
} from 'antd'
import { SaveOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import type {
  ScheduledTask,
  ScheduledTaskFormData,
  DataSourceItem,
  DataSourceOption,
  FeishuChat,
  HeaderColor,
  CardPreviewRequest,
} from '@/types/safety'
import { HEADER_COLOR_OPTIONS } from '@/types/safety'
import {
  createScheduledTask,
  updateScheduledTask,
  getDataSourceOptions,
  getFeishuChats,
  previewCard,
} from '@/actions/safety'
import CronInput from './CronInput'
import CardTemplateEditor from './CardTemplateEditor'
import CardPreview from './CardPreview'

interface ScheduledTaskFormProps {
  editData?: ScheduledTask | null
}

export default function ScheduledTaskForm({ editData }: ScheduledTaskFormProps) {
  const router = useRouter()
  const [form] = Form.useForm<ScheduledTaskFormData>()
  const [loading, setLoading] = useState(false)
  const [dataSourceOptions, setDataSourceOptions] = useState<DataSourceOption[]>([])
  const [feishuChats, setFeishuChats] = useState<FeishuChat[]>([])
  const [selectedSources, setSelectedSources] = useState<DataSourceItem[]>([])
  const [cardTemplate, setCardTemplate] = useState('')
  const [headerColor, setHeaderColor] = useState<HeaderColor>('blue' as HeaderColor)
  const [previewData, setPreviewData] = useState<CardPreviewRequest | null>(null)

  const isEdit = !!editData

  // Load reference data
  useEffect(() => {
    getDataSourceOptions().then((res) => {
      if (res.code === 200 && res.data) {
        setDataSourceOptions(res.data)
      }
    })
    getFeishuChats().then((res) => {
      if (res.code === 200 && res.data) {
        setFeishuChats(res.data)
      }
    })
  }, [])

  // Initialize form with edit data
  useEffect(() => {
    if (editData) {
      form.setFieldsValue({
        name: editData.name,
        description: editData.description || '',
        cron_expression: editData.cron_expression,
        cron_desc: editData.cron_desc || '',
        feishu_chat_id: editData.feishu_chat_id,
        feishu_chat_name: editData.feishu_chat_name || '',
        header_color: editData.header_color as HeaderColor,
        is_enabled: editData.is_enabled,
      })
      setSelectedSources(editData.data_sources || [])
      setCardTemplate(editData.card_template || '')
      setHeaderColor((editData.header_color as HeaderColor) || 'blue')
    } else {
      // Default: enable first 3 sources
      const defaults: DataSourceItem[] = dataSourceOptions
        .filter((o) => o.default_enabled)
        .map((o) => ({ key: o.key, label: o.label, enabled: true }))
      setSelectedSources(defaults)
      setCardTemplate('')
    }
  }, [editData, form, dataSourceOptions])

  // Sync preview data
  const updatePreview = useCallback(() => {
    if (selectedSources.length > 0 && cardTemplate) {
      setPreviewData({
        data_sources: selectedSources,
        card_template: cardTemplate,
        header_color: headerColor,
      })
    }
  }, [selectedSources, cardTemplate, headerColor])

  useEffect(() => {
    updatePreview()
  }, [updatePreview])

  const handleSourceToggle = (key: string, checked: boolean) => {
    setSelectedSources((prev) =>
      prev.map((s) => (s.key === key ? { ...s, enabled: checked } : s))
    )
  }

  const handleGenerateTemplate = () => {
    const enabled = selectedSources.filter((s) => s.enabled)
    if (enabled.length === 0) {
      message.warning('请先选择数据来源')
      return
    }
    const lines = ['**📊 安全数据简报**', '']
    for (const src of enabled) {
      lines.push(`- **${src.label}**: {{ ${src.key} }}`)
    }
    lines.push('')
    lines.push('---')
    lines.push('⏰ 数据截止: {{ runtime.timestamp }}')
    const generated = lines.join('\n')
    setCardTemplate(generated)
    message.success('已生成默认模板')
  }

  const handleSubmit = async () => {
    // Validate at least one data source is enabled
    const enabledSources = selectedSources.filter((s) => s.enabled)
    if (enabledSources.length === 0) {
      message.warning('请至少选择一个数据来源')
      return
    }
    // Validate template is not empty
    if (!cardTemplate.trim()) {
      message.warning('请填写消息模板或点击「自动生成默认模板」')
      return
    }

    try {
      const values = await form.validateFields()
      setLoading(true)
      const payload: ScheduledTaskFormData = {
        ...values,
        data_sources: selectedSources,
        card_template: cardTemplate,
      }

      let res
      if (isEdit && editData) {
        res = await updateScheduledTask(editData.id, payload)
      } else {
        res = await createScheduledTask(payload)
      }

      if (res.code === 200) {
        message.success(isEdit ? '已更新' : '已创建')
        router.push('/safety/scheduled-tasks')
      } else {
        message.error(res.message || '操作失败')
      }
    } catch {
      // validation error handled by form
    } finally {
      setLoading(false)
    }
  }

  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 800 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()}>
          返回
        </Button>
        <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={handleSubmit}>
          {isEdit ? '保存修改' : '创建任务'}
        </Button>
      </Space>

      {/* 基本信息 */}
      <Card title="基本信息" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={16}>
            <Form.Item
              name="name"
              label="任务名称"
              rules={[{ required: true, message: '请输入任务名称' }]}
            >
              <Input placeholder="例：每日安全简报推送" maxLength={200} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="is_enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="描述此定时任务的用途" rows={2} />
        </Form.Item>
        <Form.Item
          name="cron_expression"
          label="执行计划 (Cron 表达式)"
          rules={[{ required: true, message: '请输入 Cron 表达式' }]}
        >
          <CronInput
            onPresetSelect={(preset) => {
              form.setFieldsValue({ cron_desc: preset.desc })
            }}
          />
        </Form.Item>
        <Form.Item name="cron_desc" label="计划描述">
          <Input placeholder="例：每天上午9点" maxLength={200} />
        </Form.Item>
      </Card>

      {/* 推送配置 */}
      <Card title="推送配置" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="feishu_chat_id"
              label="目标飞书群聊"
              rules={[{ required: true, message: '请输入或选择群聊' }]}
            >
              <Select
                placeholder="选择飞书群聊"
                showSearch
                allowClear
                options={feishuChats.map((c) => ({
                  value: c.chat_id,
                  label: c.name,
                }))}
                onChange={(val, option) => {
                  form.setFieldsValue({
                    feishu_chat_name:
                      typeof option === 'object' && option ? (option as { label: string }).label : '',
                  })
                }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="feishu_chat_name" label="群聊名称（可选）">
              <Input placeholder="手动输入群聊备注" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="header_color" label="卡片头部颜色">
          <Select
            value={headerColor}
            onChange={(v) => setHeaderColor(v as HeaderColor)}
            options={HEADER_COLOR_OPTIONS.map((c) => ({
              value: c.value,
              label: (
                <Space>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 12,
                      height: 12,
                      borderRadius: 2,
                      background: c.color,
                    }}
                  />
                  {c.label}
                </Space>
              ),
            }))}
          />
        </Form.Item>
      </Card>

      {/* 数据来源 */}
      <Card title="数据来源" style={{ marginBottom: 16 }}>
        <Checkbox.Group style={{ width: '100%' }}>
          <Row gutter={[16, 8]}>
            {dataSourceOptions.map((opt) => {
              const selected = selectedSources.find((s) => s.key === opt.key)
              return (
                <Col span={8} key={opt.key}>
                  <Checkbox
                    checked={selected?.enabled ?? false}
                    onChange={(e) => handleSourceToggle(opt.key, e.target.checked)}
                  >
                    {opt.label}
                  </Checkbox>
                </Col>
              )
            })}
          </Row>
        </Checkbox.Group>
      </Card>

      {/* 消息模板 */}
      <Card
        title="消息模板"
        extra={
          <Button size="small" onClick={handleGenerateTemplate}>
            自动生成默认模板
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        <CardTemplateEditor
          value={cardTemplate}
          onChange={setCardTemplate}
          dataSources={selectedSources}
        />
      </Card>

      {/* 卡片预览 */}
      {previewData && (
        <Card title="卡片预览" style={{ marginBottom: 16 }}>
          <CardPreview
            dataSources={previewData.data_sources}
            cardTemplate={previewData.card_template}
            headerColor={previewData.header_color}
          />
        </Card>
      )}

      <Space style={{ marginTop: 16 }}>
        <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={handleSubmit}>
          {isEdit ? '保存修改' : '创建任务'}
        </Button>
        <Button onClick={() => router.back()}>取消</Button>
      </Space>
    </Form>
  )
}
