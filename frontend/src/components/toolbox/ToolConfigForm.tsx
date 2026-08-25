'use client'

// 工具配置表单：按工具声明的 config_schema 动态渲染（字段中文标签、类型、分组
// 全部来自后端声明），新增工具无需写前端表单。点路径 key 拆分为 antd 嵌套 name。

import { Fragment, useState } from 'react'
import Link from 'next/link'
import { Alert, Button, Form, Input, InputNumber } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

import { updateToolConfig } from '@/actions/toolbox'
import type { ConfigFieldInfo, ToolConfig } from '@/types/toolbox'

function renderField(field: ConfigFieldInfo) {
  const name = field.key.split('.') as (string | number)[]
  const rules = field.required
    ? [{ required: true, message: `请填写${field.label}` }]
    : undefined
  if (field.type === 'number') {
    return (
      <Form.Item key={field.key} name={name} label={field.label} rules={rules}>
        <InputNumber style={{ width: 200 }} min={0} />
      </Form.Item>
    )
  }
  return (
    <Form.Item key={field.key} name={name} label={field.label} rules={rules}>
      {field.type === 'password' ? <Input.Password /> : <Input />}
    </Form.Item>
  )
}

export function ToolConfigForm({
  toolId,
  toolName,
  schema,
  initial,
}: {
  toolId: string
  toolName: string
  schema: ConfigFieldInfo[]
  initial: ToolConfig
}) {
  const [form] = Form.useForm<ToolConfig>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const onFinish = async (values: ToolConfig) => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await updateToolConfig(toolId, values)
      setSaved(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 按声明顺序分组（section 相同且相邻的字段合并展示）
  const sections: { title: string; fields: ConfigFieldInfo[] }[] = []
  for (const field of schema) {
    const last = sections[sections.length - 1]
    if (last && last.title === field.section) {
      last.fields.push(field)
    } else {
      sections.push({ title: field.section, fields: [field] })
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <Link
        href={`/toolbox/${toolId}`}
        className="inline-flex items-center gap-1 text-[13px] text-[var(--color-slate)] hover:text-[var(--color-primary)] transition-colors"
      >
        <ArrowLeftOutlined />
        返回{toolName}
      </Link>
      <h1 className="mt-3 text-[20px] font-semibold text-[var(--color-charcoal)]">工具配置</h1>
      <p className="mt-1 text-[13px] text-[var(--color-slate)]">
        {toolName}的运行参数，所有用户执行时使用同一份配置
      </p>

      <div className="mt-6 rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-6">
        {error && <Alert className="mb-4" type="error" title={error} showIcon />}
        {saved && <Alert className="mb-4" type="success" title="配置已保存" showIcon />}
        <Form form={form} layout="vertical" initialValues={initial} onFinish={onFinish}>
          {sections.map((section, i) => (
            <Fragment key={section.title || `section-${i}`}>
              {i > 0 && <div className="my-4 border-t border-[var(--color-hairline-soft)]" />}
              {section.title && (
                <h3 className="mb-4 text-[13px] font-semibold text-[var(--color-charcoal)]">
                  {section.title}
                </h3>
              )}
              {section.fields.map(renderField)}
            </Fragment>
          ))}
          <Button type="primary" htmlType="submit" loading={saving}>
            保存配置
          </Button>
        </Form>
      </div>
    </div>
  )
}
