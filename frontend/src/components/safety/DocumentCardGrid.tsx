'use client'

import { Empty, Skeleton } from 'antd'
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

/** 卡片骨架，贴合 DocumentCard 的视觉结构，避免 Spin 造成的布局跳动 */
function CardSkeleton() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        padding: 16,
        background: 'var(--color-canvas, #ffffff)',
        borderRadius: 12,
        border: '1px solid var(--color-hairline, #e5e3df)',
        minHeight: 220,
      }}
    >
      <Skeleton.Button active size="small" style={{ width: 96, height: 22 }} />
      <div style={{ display: 'flex', gap: 10 }}>
        <Skeleton.Avatar active size={40} shape="square" style={{ borderRadius: 10 }} />
        <div style={{ flex: 1 }}>
          <Skeleton active title={false} paragraph={{ rows: 2, width: ['100%', '60%'] }} />
        </div>
      </div>
      <Skeleton active title={false} paragraph={{ rows: 2, width: ['100%', '88%'] }} />
      <div style={{ flex: 1 }} />
      <Skeleton.Button active size="small" style={{ width: 140, height: 20 }} />
    </div>
  )
}

export default function DocumentCardGrid({
  articles, loading, selectedCardIds,
  onSelectCard, onArticleClick,
  onEdit, onGenerateCard, onGeneratePpt, onGenerateSummary,
}: Props) {
  const selectionMode = selectedCardIds.length > 0

  if (loading) {
    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 16,
        }}
      >
        {Array.from({ length: 6 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    )
  }

  if (articles.length === 0) {
    return (
      <Empty
        description="暂无文档"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        style={{ padding: '80px 0' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--color-stone, #a4a097)', fontSize: 13 }}>
          <span>请选择菜单分类、调整筛选条件，或通过「同步」从 Bitable 拉取文档数据</span>
          <span style={{ fontSize: 12 }}>若已同步仍为空，请检查 Bitable 表格是否包含有效文档记录</span>
        </div>
      </Empty>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
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
          animationDelay={idx < 8 ? idx * 40 : 0}
        />
      ))}
    </div>
  )
}
