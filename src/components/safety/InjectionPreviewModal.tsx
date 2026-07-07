'use client'

import { Modal, Typography, Tag, Empty } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import type { SafetyKnowledgeArticle, KnowledgeCardContent } from '@/types/safety'

const { Text, Title } = Typography

const CARD_FIELD_LABELS: Record<string, string> = {
  hazard_type_definitions: '隐患分类定义',
  hazard_category_criteria: '隐患类别判定标准',
  hazard_level_criteria: '隐患级别分级标准',
  key_defect_examples: '典型缺陷示例',
  rectification_requirements: '整改措施要求',
  legal_basis_clauses: '可引用的法律依据条文',
}

interface Props {
  article: SafetyKnowledgeArticle | null
  open: boolean
  onClose: () => void
}

export default function InjectionPreviewModal({ article, open, onClose }: Props) {
  if (!article) return null

  const card = article.knowledge_card as KnowledgeCardContent | null | undefined
  const hasCard = card && Object.values(card).some((v) => v)

  const renderInjectedMarkdown = () => {
    if (!card || !hasCard) return null

    const sections: string[] = []

    // Title line
    sections.push(`### 文档: ${article.title}`)
    sections.push(`**类别**: ${article.category} | **优先级**: P1`)

    // 6 dimensions
    for (const [key, label] of Object.entries(CARD_FIELD_LABELS)) {
      const value = (card as Record<string, unknown>)[key] as string | null | undefined
      if (value) {
        sections.push(`\n**${label}**:\n${value}`)
      }
    }

    return sections.join('\n')
  }

  const markdown = renderInjectedMarkdown()

  return (
    <Modal
      title={
        <span>
          <InfoCircleOutlined style={{ marginRight: 8, color: '#1677ff' }} />
          Agent 注入效果预览
        </span>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
    >
      <div
        style={{
          marginBottom: 12,
          padding: '8px 12px',
          backgroundColor: '#fffbe6',
          border: '1px solid #ffe58f',
          borderRadius: 6,
          fontSize: 13,
        }}
      >
        💡 以下为 AI 隐患识别 / 危险源辨识 / 整改初审工作流中注入的知识上下文。
        实际注入时 AI 还会根据隐患描述和部门信息进行智能卡片筛选。
      </div>

      {!markdown ? (
        <Empty description="该文档暂无知识卡片内容，请先生成知识卡片" />
      ) : (
        <div
          style={{
            backgroundColor: '#1e1e1e',
            color: '#d4d4d4',
            padding: '20px 24px',
            borderRadius: 8,
            fontFamily: 'Consolas, Monaco, "Courier New", monospace',
            fontSize: 13,
            lineHeight: 1.8,
            whiteSpace: 'pre-wrap',
            maxHeight: 500,
            overflow: 'auto',
          }}
        >
{`## 法规知识上下文（仅供 AI 分析参考，非最终判定依据）

以下是与该隐患相关的法规标准知识卡片，请在分析时严格基于以下原文内容：
${markdown}

---
**知识库覆盖范围**：以上共 1 份法规标准文档。
请严格基于以上原文内容进行判断，不得依赖训练记忆。`}
        </div>
      )}

      <div style={{ marginTop: 12, color: '#a4a097', fontSize: 12 }}>
        提示：实际场景中，系统会根据隐患描述和部门自动选择最相关的 3-5 张知识卡片进行注入，避免 prompt 过长。
      </div>
    </Modal>
  )
}
