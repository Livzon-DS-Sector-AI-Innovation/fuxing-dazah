'use client'

import { Empty, Spin } from 'antd'
import type { SafetyKnowledgeArticle } from '@/types/safety'
import DocumentCard from './DocumentCard'

interface Props {
  articles: SafetyKnowledgeArticle[]
  loading: boolean
  selectedCardIds: string[]
  onSelectCard: (id: string) => void
  onArticleClick: (article: SafetyKnowledgeArticle) => void
  onEdit: (article: SafetyKnowledgeArticle) => void
  onGenerateCard: (id: string) => void
  onGeneratePpt: (id: string) => void
  onGenerateSummary: (id: string) => void
}

export default function DocumentCardGrid({
  articles, loading, selectedCardIds,
  onSelectCard, onArticleClick,
  onEdit, onGenerateCard, onGeneratePpt, onGenerateSummary,
}: Props) {
  const selectionMode = selectedCardIds.length > 0

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (articles.length === 0) {
    return (
      <Empty description="暂无文档" style={{ padding: '60px 0' }}>
        <span style={{ color: '#a4a097', fontSize: 13 }}>
          请选择菜单分类或通过 Bitable 同步文档数据
        </span>
      </Empty>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
      {articles.map((article, idx) => (
        <DocumentCard
          key={article.id}
          article={article}
          selected={selectedCardIds.includes(article.id)}
          selectionMode={selectionMode}
          onSelect={onSelectCard}
          onClick={onArticleClick}
          onEdit={onEdit}
          onGenerateCard={onGenerateCard}
          onGeneratePpt={onGeneratePpt}
          onGenerateSummary={onGenerateSummary}
          animationDelay={idx * 60}
        />
      ))}
    </div>
  )
}
