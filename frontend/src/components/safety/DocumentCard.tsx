'use client'

import { useState } from 'react'
import { Button, Tooltip, Dropdown, Checkbox } from 'antd'
import type { MenuProps } from 'antd'
import {
  RobotOutlined,
  FilePptOutlined,
  FileTextOutlined,
  EyeOutlined,
  EditOutlined,
  EllipsisOutlined,
  PaperClipOutlined,
  CalendarOutlined,
  UserOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import type { SafetyKnowledgeArticle } from '@/types/safety'
import { KNOWLEDGE_CATEGORY_OPTIONS } from '@/types/safety'
import { getCategoryStyle } from './knowledgeConstants'
import { CategoryChip, MetaItem } from './knowledgeUI'
import dayjs from 'dayjs'

interface Props {
  article: SafetyKnowledgeArticle
  selected: boolean
  selectionMode: boolean
  onSelect: (id: string) => void
  onClick: (article: SafetyKnowledgeArticle) => void
  onEdit: (article: SafetyKnowledgeArticle) => void
  onGenerateCard: (id: string) => void
  onGeneratePpt: (id: string) => void
  onGenerateSummary: (id: string) => void
  animationDelay?: number
}

export default function DocumentCard({
  article,
  selected,
  selectionMode,
  onSelect,
  onClick,
  onEdit,
  onGenerateCard,
  onGeneratePpt,
  onGenerateSummary,
  animationDelay = 0,
}: Props) {
  const [hovered, setHovered] = useState(false)
  const showCheckbox = selectionMode || hovered

  const style = getCategoryStyle(article.tags, article.category)
  const btCategory = (article.tags as string) || ''
  const fallbackLabel =
    KNOWLEDGE_CATEGORY_OPTIONS.find((o) => o.value === article.category)?.label ||
    article.category
  const categoryLabel = btCategory || fallbackLabel

  const hasCard = article.knowledge_card != null
  const cardVersion = article.card_version || 0
  const hasContent = !!article.content
  const hasAttachment = !!article.attachment_original_name
  const attachmentName = article.attachment_original_name || ''
  const summary = article.summary?.trim() || ''
  const source = article.source?.trim() || ''
  const author = article.author?.trim() || ''
  const publishDate = article.publish_date ? dayjs(article.publish_date).format('YYYY-MM-DD') : ''

  const statusBadge: Record<string, { color: string; bg: string; label: string }> = {
    draft:     { color: '#5d5b54', bg: '#f0eeec', label: '草稿' },
    published: { color: '#1aae39', bg: '#d9f3e1', label: '已发布' },
    archived:  { color: '#a4a097', bg: '#f0eeec', label: '已归档' },
  }
  const st = statusBadge[article.status] || { color: '#5d5b54', bg: '#f0eeec', label: article.status }

  const menuItems: MenuProps['items'] = [
    { key: 'view', label: '查看详情', icon: <EyeOutlined />, onClick: () => onClick(article) },
    { key: 'edit', label: '编辑元数据', icon: <EditOutlined />, onClick: () => onEdit(article) },
    { type: 'divider' },
    {
      key: 'card', label: hasCard ? '重新生成卡片' : '生成知识卡片',
      icon: <RobotOutlined />, disabled: !hasContent,
      onClick: () => onGenerateCard(article.id),
    },
    {
      key: 'ppt', label: '生成 PPT',
      icon: <FilePptOutlined />, disabled: !hasContent,
      onClick: () => onGeneratePpt(article.id),
    },
    {
      key: 'summary', label: '生成摘要',
      icon: <FileTextOutlined />, disabled: !hasContent,
      onClick: () => onGenerateSummary(article.id),
    },
  ]

  return (
    <div
      onClick={() => onClick(article)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        cursor: 'pointer',
        background: 'var(--color-canvas, #ffffff)',
        borderRadius: 14,
        border: selected
          ? '1.5px solid var(--color-primary, #5645d4)'
          : '1px solid var(--color-hairline, #e5e3df)',
        padding: '18px',
        gap: 8,
        transition: 'box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease',
        boxShadow: hovered
          ? '0 10px 30px rgba(26, 26, 26, 0.08)'
          : '0 1px 2px rgba(26, 26, 26, 0.03)',
        transform: hovered ? 'translateY(-2px)' : 'translateY(0)',
        animation: 'fadeInUp 0.4s ease both',
        animationDelay: animationDelay + 'ms',
        userSelect: 'none',
      }}
    >
      {/* 顶部分类标签 + 选择框 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <CategoryChip
          emoji={style.emoji}
          label={categoryLabel}
          color={style.color}
          bg={style.bg}
          maxWidth={showCheckbox ? 'calc(100% - 28px)' : '100%'}
        />

        <span
          style={{
            opacity: showCheckbox ? 1 : 0,
            transition: 'opacity 0.15s ease',
            pointerEvents: showCheckbox ? 'auto' : 'none',
            flexShrink: 0,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <Checkbox checked={selected} onChange={() => onSelect(article.id)} />
        </span>
      </div>

      {/* 标题 */}
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: 'var(--color-ink, #1a1a1a)',
          lineHeight: 1.45,
          letterSpacing: '-0.01em',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          wordBreak: 'break-word',
        }}
      >
        {article.title}
      </div>

      {/* 编号 · 版本 · 状态 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        {article.article_no && (
          <span
            style={{
              fontFamily: '"SF Mono", "Fira Code", ui-monospace, monospace',
              fontSize: 12,
              color: 'var(--color-slate, #5d5b54)',
              fontWeight: 600,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {article.article_no}
          </span>
        )}
        <span
          style={{
            display: 'inline-block',
            padding: '0 7px',
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--color-primary, #5645d4)',
            background: 'rgba(86, 69, 212, 0.08)',
            lineHeight: '18px',
          }}
        >
          v{article.version || 1}
        </span>
        <span
          style={{
            display: 'inline-block',
            padding: '0 7px',
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 600,
            color: st.color,
            background: st.bg,
            lineHeight: '18px',
          }}
        >
          {st.label}
        </span>
      </div>

      {/* 摘要 */}
      <div
        style={{
          fontSize: 13,
          lineHeight: 1.6,
          color: summary ? 'var(--color-charcoal, #37352f)' : 'var(--color-stone, #a4a097)',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          wordBreak: 'break-word',
          minHeight: summary ? undefined : '1.6em',
        }}
      >
        {summary || '暂无摘要'}
      </div>

      {/* 弹性占位，压底部状态栏 */}
      <div style={{ flex: 1 }} />

      {/* 元数据行 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 14px' }}>
        {source && <MetaItem icon={<ApartmentOutlined />} text={source} title={'来源：' + source} />}
        {publishDate && <MetaItem icon={<CalendarOutlined />} text={publishDate} title={'发布日期：' + publishDate} />}
        {author && <MetaItem icon={<UserOutlined />} text={author} title={'作者/发布单位：' + author} />}
        <MetaItem
          icon={<EyeOutlined />}
          text={(article.view_count || 0) + ' 次浏览'}
          title={'浏览次数：' + (article.view_count || 0)}
        />
      </div>

      {/* 底部状态栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          paddingTop: 10,
          marginTop: 2,
          borderTop: '1px solid var(--color-hairline-soft, #ede9e4)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          {hasCard ? (
            <Tooltip title={'知识卡片 v' + cardVersion}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '1px 8px',
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: 600,
                  color: '#1aae39',
                  background: '#e7f7ec',
                  flexShrink: 0,
                }}
              >
                <RobotOutlined style={{ fontSize: 11 }} />
                v{cardVersion}
              </span>
            </Tooltip>
          ) : (
            <span
              style={{
                display: 'inline-block',
                padding: '1px 8px',
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--color-stone, #a4a097)',
                background: 'var(--color-surface, #f0eeec)',
                flexShrink: 0,
              }}
            >
              无卡片
            </span>
          )}

          {hasAttachment && (
            <Tooltip title={attachmentName}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  minWidth: 0,
                }}
              >
                <PaperClipOutlined style={{ fontSize: 12, flexShrink: 0 }} />
                <span style={{ maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {attachmentName}
                </span>
              </span>
            </Tooltip>
          )}
        </div>

        {/* 快捷操作（hover 显示） */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            opacity: hovered ? 1 : 0,
            transition: 'opacity 0.15s ease',
            flexShrink: 0,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <Tooltip title="查看详情">
            <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => onClick(article)} />
          </Tooltip>
          {hasContent && !hasCard && (
            <Tooltip title="生成知识卡片">
              <Button type="text" size="small" icon={<RobotOutlined />} onClick={() => onGenerateCard(article.id)} />
            </Tooltip>
          )}
          <Dropdown menu={{ items: menuItems }} trigger={['click']} placement="bottomRight">
            <Button type="text" size="small" icon={<EllipsisOutlined />} />
          </Dropdown>
        </div>
      </div>

      <style jsx>{`@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}`}</style>
    </div>
  )
}
