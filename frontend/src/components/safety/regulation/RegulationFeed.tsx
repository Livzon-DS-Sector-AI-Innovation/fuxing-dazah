'use client'

/** 最新法规卡片流：标题/修订标记/AI 判定摘要/时间/原文外链；详情复用 KnowledgeDetailDrawer。 */

import { useState } from 'react'
import { Tag } from 'antd'
import { ExportOutlined } from '@ant-design/icons'
import KnowledgeDetailDrawer from '@/components/safety/KnowledgeDetailDrawer'
import { EmptyGuide } from '@/components/ui-kit'
import { formatMonitorTimeFull } from './format'
import type { RegulationFeedItem } from '@/types/safety'

export default function RegulationFeed({ feed }: { feed: RegulationFeedItem[] }) {
  const [articleId, setArticleId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  if (!feed.length) {
    return <EmptyGuide compact title="暂无收录" description="候选判定收录后将在此展示" />
  }

  return (
    <>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {feed.map((item) => (
          <div
            key={`${item.candidate_id}-${item.ingested_at}`}
            role={item.article_id ? 'button' : undefined}
            tabIndex={item.article_id ? 0 : undefined}
            onClick={() => {
              if (!item.article_id) return
              setArticleId(item.article_id)
              setOpen(true)
            }}
            onKeyDown={(e) => {
              if (item.article_id && (e.key === 'Enter' || e.key === ' ')) {
                setArticleId(item.article_id)
                setOpen(true)
              }
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 14px',
              borderRadius: 10,
              border: '1px solid var(--color-hairline, #eee)',
              background: '#fff',
              cursor: item.article_id ? 'pointer' : 'default',
            }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  className="truncate"
                  style={{ fontWeight: 500, fontSize: 13.5 }}
                  title={item.title ?? undefined}
                >
                  {item.title ?? '（无标题）'}
                </span>
                {item.is_revision && <Tag color="orange">修订</Tag>}
              </div>
              <div style={{ fontSize: 12, color: 'var(--color-steel, #8a8a8a)', marginTop: 2 }}>
                {formatMonitorTimeFull(item.ingested_at)}
                {item.reason ? ` · ${item.reason}` : ''}
              </div>
            </div>
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={{ fontSize: 12, flexShrink: 0 }}
              >
                原文 <ExportOutlined />
              </a>
            )}
          </div>
        ))}
      </div>
      {/* onClose 只关不清（遮罩卡死防御，口径同知识库页） */}
      <KnowledgeDetailDrawer
        articleId={articleId}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
