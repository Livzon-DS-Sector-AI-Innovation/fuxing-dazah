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
  ThunderboltOutlined,
  PaperClipOutlined,
} from '@ant-design/icons'
import type { SafetyKnowledgeArticle } from '@/types/safety'
import { BT_CATEGORY_STYLE, FALLBACK_STYLE, getCategoryStyle } from './knowledgeConstants'

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

  // 优先使用 Bitable 原始子分类（tags），回退到平台分类
  const style = getCategoryStyle(article.tags, article.category)
  const btCategory = (article.tags as string) || ''
  const categoryLabel = btCategory || article.category

  const hasCard = article.knowledge_card != null
  const cardVersion = article.card_version || 0
  const hasContent = !!article.content
  const hasAttachment = !!article.attachment_original_name
  const attachmentName = article.attachment_original_name || ''

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
        background: '#ffffff',
        borderRadius: 12,
        border: selected ? '2px solid #5645d4' : '1px solid #e5e3df',
        padding: '16px',
        gap: 10,
        transition: 'box-shadow 0.2s ease, transform 0.2s ease, border-color 0.2s ease',
        boxShadow: hovered ? '0 4px 16px rgba(15,15,15,0.08)' : '0 1px 3px rgba(0,0,0,0.04)',
        transform: hovered ? 'translateY(-3px)' : 'translateY(0)',
        animation: 'fadeInUp 0.4s ease both',
        animationDelay: `${animationDelay}ms`,
        userSelect: 'none',
      }}
    >
      {/* ── 顶部：Bitable 分类标签 + 多选框 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            borderRadius: 4,
            fontSize: 11,
            fontWeight: 600,
            color: style.color,
            background: style.bg,
            lineHeight: '18px',
            maxWidth: showCheckbox ? 'calc(100% - 28px)' : '100%',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          <span>{style.emoji}</span>
          {categoryLabel}
        </span>

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

      {/* ── 中部：图标 + 标题 + 编号 ── */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flex: 1 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: style.bg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            flexShrink: 0,
            marginTop: 2,
          }}
        >
          {style.emoji}
        </div>

        <div style={{ minWidth: 0, flex: 1 }}>
          {/* 标题 */}
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: '#1a1a1a',
              lineHeight: 1.4,
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
              wordBreak: 'break-word',
            }}
          >
            {article.title}
          </div>

          {/* 编号 + 版本 + 状态 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            {article.article_no && (
              <span
                style={{
                  fontFamily: '"SF Mono","Fira Code",monospace',
                  fontSize: 12,
                  color: '#5d5b54',
                  fontWeight: 600,
                }}
              >
                {article.article_no}
              </span>
            )}
            <span
              style={{
                display: 'inline-block',
                padding: '0 6px',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 600,
                color: '#5645d4',
                background: '#e6e0f5',
                lineHeight: '18px',
              }}
            >
              v{article.version || 1}
            </span>
            <span
              style={{
                display: 'inline-block',
                padding: '0 6px',
                borderRadius: 4,
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
        </div>
      </div>

      {/* ── 底部：状态栏 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          paddingTop: 8,
          borderTop: '1px solid #f6f5f4',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* 知识卡片状态 */}
          {hasCard ? (
            <Tooltip title={`知识卡片 v${cardVersion}`}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  padding: '1px 8px',
                  borderRadius: 4,
                  fontSize: 12,
                  fontWeight: 600,
                  color: '#1aae39',
                  background: '#d9f3e1',
                }}
              >
                <span style={{ fontSize: 10 }}>✓</span> v{cardVersion}
              </span>
            </Tooltip>
          ) : (
            <span
              style={{
                display: 'inline-block',
                padding: '1px 8px',
                borderRadius: 4,
                fontSize: 12,
                fontWeight: 600,
                color: '#a4a097',
                background: '#f0eeec',
              }}
            >
              —
            </span>
          )}

          {/* 附件指示 */}
          {hasAttachment && (
            <Tooltip title={attachmentName}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  fontSize: 12,
                  color: '#1aae39',
                }}
              >
                <PaperClipOutlined style={{ fontSize: 11 }} />
                <span style={{ maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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

      <style jsx>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
