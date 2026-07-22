'use client'

import { useState, useEffect, useCallback } from 'react'
import { Checkbox, Space, Typography, Tag, Spin, Alert } from 'antd'
import { NodeIndexOutlined } from '@ant-design/icons'
import { getRegulationStages } from '@/actions/safety'
import type { RegulationStageInfo } from '@/types/safety'

const { Text } = Typography

interface StageSelectorProps {
  regulationId: string
  value?: string[]
  onChange?: (selectedStages: string[]) => void
}

export default function StageSelector({
  regulationId,
  value = [],
  onChange,
}: StageSelectorProps) {
  const [stages, setStages] = useState<RegulationStageInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadStages = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getRegulationStages(regulationId)
      if (res.code === 200 && res.data) {
        setStages(res.data.stages || [])
      } else {
        setError(res.message || '无法解析该操规的工艺阶段')
      }
    } catch {
      setError('加载工艺阶段失败')
    } finally {
      setLoading(false)
    }
  }, [regulationId])

  useEffect(() => {
    if (regulationId) loadStages()
  }, [regulationId, loadStages])

  const handleCheckAll = () => {
    if (stages.length === 0) return
    if (value.length === stages.length) {
      onChange?.([])
    } else {
      onChange?.(stages.map((s) => s.stage_name))
    }
  }

  const handleToggle = (stageName: string, checked: boolean) => {
    if (checked) {
      onChange?.([...value, stageName])
    } else {
      onChange?.(value.filter((n) => n !== stageName))
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin description="正在解析工艺阶段..." />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="warning"
        message="无法获取工艺阶段"
        description={error}
        showIcon
      />
    )
  }

  if (stages.length === 0) {
    return (
      <Alert
        type="info"
        message="该操规暂无工艺阶段"
        description="请确认操规第7章包含 ## 标题的工艺阶段"
        showIcon
      />
    )
  }

  const allChecked = value.length === stages.length
  const someChecked = value.length > 0 && value.length < stages.length

  return (
    <div style={{ padding: '8px 0' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: '1px solid #f0f0f0',
        }}
      >
        <Space>
          <NodeIndexOutlined style={{ color: '#5645d4' }} />
          <Text strong>
            工艺阶段列表（共 {stages.length} 个）
          </Text>
        </Space>
        <Checkbox
          checked={allChecked}
          indeterminate={someChecked}
          onChange={handleCheckAll}
        >
          全选
        </Checkbox>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {stages.map((stage) => (
          <Checkbox
            key={stage.stage_name}
            checked={value.includes(stage.stage_name)}
            onChange={(e) => handleToggle(stage.stage_name, e.target.checked)}
          >
            <span style={{ fontWeight: 500 }}>{stage.stage_name}</span>
            <span style={{ marginLeft: 8 }}>
              <Tag color="blue">{stage.safety_count} 条安全要求</Tag>
              <Tag color="green">{stage.operation_count} 条操作步骤</Tag>
            </span>
          </Checkbox>
        ))}
      </div>

      {value.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
          <Text type="secondary">
            已选择 <Text strong style={{ color: '#5645d4' }}>{value.length}</Text> / {stages.length} 个工艺阶段
          </Text>
        </div>
      )}
    </div>
  )
}
