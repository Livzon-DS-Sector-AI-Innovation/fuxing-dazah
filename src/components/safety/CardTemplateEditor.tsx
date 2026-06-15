'use client'

import { Input, Space, Tag } from 'antd'
import type { DataSourceItem } from '@/types/safety'

const { TextArea } = Input

interface CardTemplateEditorProps {
  value?: string
  onChange?: (value: string) => void
  dataSources: DataSourceItem[]
}

export default function CardTemplateEditor({
  value = '',
  onChange,
  dataSources,
}: CardTemplateEditorProps) {
  const enabledSources = dataSources.filter((ds) => ds.enabled)

  const insertVariable = (key: string) => {
    const variable = `{{ ${key} }}`
    if (onChange) {
      onChange(value + variable)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <TextArea
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder="输入 Markdown 模板，使用 {{ key }} 引用数据源..."
        rows={8}
        style={{ fontFamily: 'monospace' }}
      />
      <Space wrap size={[8, 4]}>
        <span style={{ fontSize: 12, color: '#666' }}>插入变量：</span>
        {enabledSources.map((ds) => (
          <Tag
            key={ds.key}
            color="blue"
            style={{ cursor: 'pointer' }}
            onClick={() => insertVariable(ds.key)}
          >
            {ds.label} (&#123;&#123; {ds.key} &#125;&#125;)
          </Tag>
        ))}
        <Tag
          color="purple"
          style={{ cursor: 'pointer' }}
          onClick={() => insertVariable('runtime.timestamp')}
        >
          当前时间 (&#123;&#123; runtime.timestamp &#125;&#125;)
        </Tag>
      </Space>
    </Space>
  )
}
