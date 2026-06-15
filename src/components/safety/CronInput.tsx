'use client'

import { Button, Input, Space, Tag } from 'antd'
import { CRON_PRESETS } from '@/types/safety'

interface CronInputProps {
  value?: string
  onChange?: (value: string) => void
  onPresetSelect?: (preset: { value: string; label: string; desc: string }) => void
}

export default function CronInput({ value = '', onChange, onPresetSelect }: CronInputProps) {
  const selectedPreset = CRON_PRESETS.find((p) => p.value === value)

  const handlePresetClick = (preset: (typeof CRON_PRESETS)[number]) => {
    onChange?.(preset.value)
    onPresetSelect?.(preset)
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Input
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder="输入 Cron 表达式，如 0 9 * * *"
        style={{ fontFamily: 'monospace' }}
      />
      <Space wrap size={[8, 4]}>
        {CRON_PRESETS.map((preset) => (
          <Button
            key={preset.label}
            size="small"
            type={value === preset.value ? 'primary' : 'default'}
            onClick={() => handlePresetClick(preset)}
          >
            {preset.label}
          </Button>
        ))}
      </Space>
      {value && (
        <Tag color={selectedPreset ? 'blue' : 'orange'}>
          {selectedPreset ? selectedPreset.desc : '自定义 Cron 表达式'}
        </Tag>
      )}
    </Space>
  )
}
