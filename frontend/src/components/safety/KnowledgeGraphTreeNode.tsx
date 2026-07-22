'use client'

import { memo } from 'react'
import {
  ApartmentOutlined,
  FileTextOutlined,
  SafetyOutlined,
  NumberOutlined,
  BulbOutlined,
  RightOutlined,
} from '@ant-design/icons'
import type { KnowledgeTreeNode } from '@/lib/buildTreeData'

// ═══════════════════════════════════════════════════════════════
// 文档编号提取 — 从名称中识别标准编号
// 例: "GB 3836.1-2021 爆炸性环境..." → "GB 3836.1-2021"
// ═══════════════════════════════════════════════════════════════

const DOC_NUMBER_RE = /^([A-Z]{2,}(?:\/T)?\s*\d+(?:\.\d+)?-\d{4})/

function extractDocNumber(name: string): string | null {
  const m = name.match(DOC_NUMBER_RE)
  return m ? m[1] : null
}

// ═══════════════════════════════════════════════════════════════
// 节点类型 → 图标 + 颜色 + 背景
// ═══════════════════════════════════════════════════════════════

interface NodeStyle {
  icon: typeof ApartmentOutlined
  color: string
  bg: string
}

const NODE_STYLE_MAP: Record<string, NodeStyle> = {
  category: { icon: ApartmentOutlined, color: '#2a9d99', bg: '#eaf5f5' },
  document: { icon: FileTextOutlined, color: '#0a1530', bg: '#e8ecf2' },
  entity:   { icon: SafetyOutlined, color: '#dd5b00', bg: '#fceee6' },
  clause:   { icon: NumberOutlined, color: '#5645d4', bg: '#eeebfa' },
  concept:  { icon: BulbOutlined, color: '#7b3ff2', bg: '#f1ecfc' },
}

function getNodeStyle(node: KnowledgeTreeNode): NodeStyle {
  if (node.nodeType === 'entity' && node.entityType === 'standard') {
    return NODE_STYLE_MAP.document
  }
  return NODE_STYLE_MAP[node.nodeType] || NODE_STYLE_MAP.entity
}

// ═══════════════════════════════════════════════════════════════
// 搜索高亮
// ═══════════════════════════════════════════════════════════════

function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <mark
        style={{
          background: '#fde68a',
          color: '#1a1a1a',
          borderRadius: 2,
          padding: '0 1px',
        }}
      >
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  )
}

// ═══════════════════════════════════════════════════════════════
// TreeNode — 高密度行组件
// ═══════════════════════════════════════════════════════════════

interface TreeNodeProps {
  node: KnowledgeTreeNode
  level: number
  selectedId: string | null
  focusedId: string | null
  expandedKeys: Set<string>
  searchQuery: string
  onSelect: (node: KnowledgeTreeNode) => void
  onToggleExpand: (nodeId: string) => void
}

const KnowledgeGraphTreeNode = memo(function TreeNode({
  node,
  level,
  selectedId,
  focusedId,
  expandedKeys,
  searchQuery,
  onSelect,
  onToggleExpand,
}: TreeNodeProps) {
  const hasChildren = node.children.length > 0
  const isExpanded = expandedKeys.has(node.id)
  const isSelected = selectedId === node.id
  const isFocused = focusedId === node.id
  const isAi = node.status === 'ai_generated'
  const style = getNodeStyle(node)
  const Icon = style.icon
  const docNumber = extractDocNumber(node.name)
  const displayName = docNumber
    ? node.name.slice(docNumber.length).replace(/^[\s:：]+/, '')
    : node.name

  return (
    <div>
      {/* ── 节点行 ────────────────────────────────────────── */}

      <div
        role="treeitem"
        tabIndex={-1}
        aria-expanded={hasChildren ? isExpanded : undefined}
        aria-selected={isSelected}
        data-node-id={node.id}
        onClick={() => onSelect(node)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 30,
          paddingLeft: 4 + level * 16,
          paddingRight: 8,
          borderRadius: 4,
          cursor: 'pointer',
          background: isSelected
            ? 'var(--color-surface, #f0efed)'
            : isFocused
              ? 'rgba(86,69,212,0.06)'
              : 'transparent',
          outline: isFocused
            ? '1px solid var(--color-primary, #5645d4)'
            : 'none',
          outlineOffset: -1,
          transition: 'background 80ms ease',
          fontSize: 13,
          lineHeight: '18px',
          color: 'var(--color-charcoal, #37352f)',
          fontWeight: isSelected ? 500 : 400,
          fontStyle: isAi ? 'italic' : 'normal',
          opacity: isAi ? 0.8 : 1,
          userSelect: 'none' as const,
        }}
      >
        {/* 展开/折叠 三角 */}
        <span
          role="button"
          tabIndex={-1}
          onClick={(e) => {
            e.stopPropagation()
            onToggleExpand(node.id)
          }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 18,
            height: 18,
            flexShrink: 0,
            transition: 'transform 0.12s ease',
            transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
            visibility: hasChildren ? 'visible' : 'hidden',
          }}
        >
          <RightOutlined
            style={{ fontSize: 9, color: 'var(--color-stone, #a4a097)' }}
          />
        </span>

        {/* 节点图标 */}
        <Icon
          style={{
            fontSize: 14,
            color: isSelected ? style.color : style.color,
            flexShrink: 0,
          }}
        />

        {/* 文档编号（仅法规文档） */}
        {docNumber && (
          <span
            style={{
              fontSize: 11,
              fontFamily:
                'var(--font-mono, "SF Mono", "Cascadia Code", Consolas, monospace)',
              color: 'var(--color-steel, #787671)',
              fontWeight: 500,
              flexShrink: 0,
              background: style.bg,
              borderRadius: 3,
              padding: '0 5px',
              lineHeight: '18px',
              marginRight: 2,
            }}
          >
            {docNumber}
          </span>
        )}

        {/* 名称 */}
        <span
          style={{
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {highlightMatch(displayName, searchQuery)}
        </span>

        {/* AI 置信度 */}
        {node.confidence != null && node.nodeType !== 'category' && (
          <span
            title={`AI 置信度 ${Math.round(node.confidence * 100)}%`}
            style={{
              fontSize: 10,
              flexShrink: 0,
              color:
                node.confidence >= 0.8
                  ? '#1aae39'
                  : node.confidence >= 0.6
                    ? '#dd5b00'
                    : '#e03131',
              background:
                node.confidence >= 0.8
                  ? 'rgba(26,174,57,0.12)'
                  : node.confidence >= 0.6
                    ? 'rgba(221,91,0,0.12)'
                    : 'rgba(224,49,49,0.12)',
              borderRadius: 3,
              padding: '0 4px',
              lineHeight: '16px',
              fontWeight: 500,
            }}
          >
            {Math.round(node.confidence * 100)}%
          </span>
        )}

        {/* 子节点计数 */}
        {hasChildren && (
          <span
            style={{
              fontSize: 10,
              color: 'var(--color-stone, #787671)',
              background: 'var(--color-hairline-soft, #ede9e4)',
              borderRadius: 3,
              padding: '0 5px',
              flexShrink: 0,
              lineHeight: '16px',
            }}
          >
            {node.children.length}
          </span>
        )}

        {/* AI 生成标记点 */}
        {isAi && (
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              backgroundColor: '#b8adeb',
              flexShrink: 0,
            }}
            title="AI 生成"
          />
        )}
      </div>

      {/* ── 子节点 ────────────────────────────────────────── */}

      {hasChildren && isExpanded && (
        <div role="group">
          {node.children.map((child) => (
            <KnowledgeGraphTreeNode
              key={child.id}
              node={child}
              level={level + 1}
              selectedId={selectedId}
              focusedId={focusedId}
              expandedKeys={expandedKeys}
              searchQuery={searchQuery}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </div>
      )}
    </div>
  )
})

export default KnowledgeGraphTreeNode
