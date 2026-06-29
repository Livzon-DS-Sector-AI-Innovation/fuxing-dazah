'use client'

import { memo } from 'react'
import { BaseNode, type BaseNodeProps } from './BaseNode'

/**
 * Knowledge retrieval node — loads regulation/standard documents.
 * Cyan header.
 */

interface DazahConfig {
  categories?: string[]
  max_cards?: number
}

export const KnowledgeNode = memo(function KnowledgeNode(props: BaseNodeProps) {
  const { data } = props
  const dazahConfig = data.dazah_config as DazahConfig | undefined
  const topK = data.top_k as number | undefined

  return (
    <BaseNode {...props} headerColor="#13c2c2">
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        {dazahConfig?.categories && dazahConfig.categories.length > 0 && (
          <div style={{ marginBottom: 4 }}>
            {dazahConfig.categories.map((cat) => (
              <span
                key={cat}
                style={{
                  display: 'inline-block',
                  background: '#e6fffb',
                  color: '#08979c',
                  padding: '0 4px',
                  borderRadius: 3,
                  marginRight: 4,
                  fontSize: 10,
                }}
              >
                {cat}
              </span>
            ))}
          </div>
        )}
        <div style={{ color: '#999', fontSize: 11 }}>
          {topK != null ? `Top-K: ${topK}` : '语义检索'}
          {dazahConfig?.max_cards != null ? ` · 最多 ${dazahConfig.max_cards} 张卡片` : ''}
        </div>
      </div>
    </BaseNode>
  )
})
