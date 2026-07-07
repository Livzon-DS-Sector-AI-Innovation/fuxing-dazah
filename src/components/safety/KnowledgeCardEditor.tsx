'use client'

import { useState } from 'react'
import { Button, Input, Space, Tag, Empty, message, Spin, Tooltip } from 'antd'
import {
  RobotOutlined,
  SaveOutlined,
  EyeOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { SafetyKnowledgeArticle, KnowledgeCardContent } from '@/types/safety'
import { generateKnowledgeCard, updateKnowledgeArticle } from '@/actions/safety'

const { TextArea } = Input

/** 6 维度中文标签映射 */
const CARD_FIELD_LABELS: Record<string, string> = {
  hazard_type_definitions: '危险源类型定义',
  hazard_category_criteria: '隐患分类标准',
  hazard_level_criteria: '隐患分级标准',
  key_defect_examples: '典型缺陷示例',
  rectification_requirements: '整改措施要求',
  legal_basis_clauses: '法律依据条文',
}

/** 字段占位符提示 */
const CARD_FIELD_PLACEHOLDERS: Record<string, string> = {
  hazard_type_definitions: '文档中定义的危险源类型与分类方式（人/物/环/管）',
  hazard_category_criteria: '隐患类别的判定标准与典型场景',
  hazard_level_criteria: '重大/一般/低风险的判定依据',
  key_defect_examples: '文档列出的具体安全缺陷示例',
  rectification_requirements: '整改时限、整改标准、防护要求',
  legal_basis_clauses: '可引用的法规条款原文（条款号+内容）',
}

interface Props {
  article: SafetyKnowledgeArticle
  onRefresh: () => void
  onPreviewInjection: () => void
}

export default function KnowledgeCardEditor({
  article,
  onRefresh,
  onPreviewInjection,
}: Props) {
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [editing, setEditing] = useState<Record<string, string>>({})

  const card = article.knowledge_card as KnowledgeCardContent | null | undefined
  const hasCard = card && Object.values(card).some((v) => v)
  const cardFields = Object.keys(CARD_FIELD_LABELS)

  // Initialize editing state from existing card
  const getFieldValue = (key: string) => {
    if (key in editing) return editing[key]
    if (card && (card as Record<string, unknown>)[key]) {
      return (card as Record<string, unknown>)[key] as string
    }
    return ''
  }

  const handleFieldChange = (key: string, value: string) => {
    setEditing((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    // Only save changed fields
    const changedFields: Record<string, unknown> = {}
    for (const key of cardFields) {
      if (key in editing) {
        changedFields[key] = editing[key] || null
      }
    }
    if (Object.keys(changedFields).length === 0) {
      message.info('没有修改')
      return
    }

    // Merge with existing card
    const updatedCard = { ...(card || {}), ...changedFields }
    setSaving(true)
    try {
      const res = await updateKnowledgeArticle(article.id, {
        knowledge_card: updatedCard as unknown as Record<string, unknown>,
      } as never)
      if (res.code === 200) {
        message.success('知识卡片已保存')
        setEditing({})
        onRefresh()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await generateKnowledgeCard(article.id)
      if (res.code === 200 && res.data) {
        message.success(res.data.message || '知识卡片生成成功')
        onRefresh()
      } else {
        message.error(res.message || '生成失败')
      }
    } catch {
      message.error('生成失败，请稍后重试')
    } finally {
      setGenerating(false)
    }
  }

  // Empty state
  if (!hasCard && Object.keys(editing).length === 0) {
    return (
      <Empty
        description={
          <span>
            该文档尚未生成知识卡片
            <br />
            <span style={{ color: '#a4a097', fontSize: 13 }}>
              知识卡片是 AI Agent 注入知识上下文的核心载体
            </span>
          </span>
        }
      >
        <Button
          type="primary"
          icon={<RobotOutlined />}
          loading={generating}
          onClick={handleGenerate}
          size="large"
        >
          AI 生成知识卡片
        </Button>
        {!article.content && (
          <div style={{ marginTop: 12, color: '#dd5b00', fontSize: 13 }}>
            提示：文档缺少正文内容，生成前请先确保文档已解析全文
          </div>
        )}
      </Empty>
    )
  }

  return (
    <div>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <Space>
          <Tag color="blue">版本 {article.card_version || 1}</Tag>
          {Object.keys(editing).length > 0 && (
            <Tag color="orange">有未保存修改</Tag>
          )}
        </Space>
        <Space>
          <Tooltip title="预览 Agent 注入效果">
            <Button icon={<EyeOutlined />} onClick={onPreviewInjection} size="small">
              注入预览
            </Button>
          </Tooltip>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={handleGenerate}
            loading={generating}
            size="small"
          >
            AI 重新生成
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            size="small"
            disabled={Object.keys(editing).length === 0}
          >
            保存修改
          </Button>
        </Space>
      </div>

      {/* 6 Dimension Fields */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {cardFields.map((key) => {
          const value = getFieldValue(key)
          const isEdited = key in editing

          return (
            <div
              key={key}
              style={{
                border: isEdited ? '1px solid #5645d4' : '1px solid #e5e3df',
                borderRadius: 8,
                padding: '12px 16px',
                backgroundColor: isEdited ? '#e6e0f5' : '#fafaf9',
                transition: 'border-color 0.2s, background-color 0.2s',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                }}
              >
                <span style={{ fontWeight: 600, fontSize: 14 }}>
                  {CARD_FIELD_LABELS[key]}
                </span>
                {isEdited && (
                  <Tag color="purple" style={{ fontSize: 11 }}>
                    已修改
                  </Tag>
                )}
              </div>
              <TextArea
                value={value}
                onChange={(e) => handleFieldChange(key, e.target.value)}
                placeholder={CARD_FIELD_PLACEHOLDERS[key]}
                autoSize={{ minRows: 3, maxRows: 6 }}
                style={{
                  borderColor: 'transparent',
                  backgroundColor: 'transparent',
                  boxShadow: 'none',
                  resize: 'none',
                  padding: 0,
                }}
              />
            </div>
          )
        })}
      </div>

      <div style={{ marginTop: 8, color: '#a4a097', fontSize: 12 }}>
        提示：每个字段提取原文中直接相关的内容，不编造。AI 隐患识别/危险源辨识工作流将使用这些内容作为知识上下文注入 prompt。
      </div>
    </div>
  )
}
