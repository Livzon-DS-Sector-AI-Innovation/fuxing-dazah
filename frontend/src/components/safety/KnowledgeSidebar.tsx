'use client'

import { useMemo } from 'react'
import { Menu } from 'antd'
import type { MenuProps } from 'antd'
import { FolderOpenOutlined } from '@ant-design/icons'
import { KNOWLEDGE_MENU } from './knowledgeConstants'

interface KnowledgeSidebarProps {
  selectedKey: string | null
  onSelect: (key: string) => void
  counts: Map<string, number>
  loading?: boolean
}

export default function KnowledgeSidebar({
  selectedKey,
  onSelect,
  counts,
  loading,
}: KnowledgeSidebarProps) {
  const totalDocs = useMemo(() => {
    let total = 0
    for (const item of KNOWLEDGE_MENU) {
      total += counts.get(item.key) || 0
    }
    return total
  }, [counts])

  const menuItems: MenuProps['items'] = useMemo(() => {
    return KNOWLEDGE_MENU.map((item) => {
      const count = counts.get(item.key) || 0
      return {
        key: item.key,
        disabled: item.disabled || false,
        label: (
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: item.color,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 13, lineHeight: 1 }}>{item.emoji}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.label}
              </span>
            </span>
            <span
              style={{
                fontSize: 12,
                color: 'var(--color-stone, #a4a097)',
                marginLeft: 8,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {count}
            </span>
          </span>
        ),
      }
    })
  }, [counts])

  const handleClick: MenuProps['onClick'] = ({ key }) => onSelect(key)
  const selectedKeys = selectedKey ? [selectedKey] : []

  return (
    <aside
      style={{
        width: 232,
        flexShrink: 0,
        background: 'var(--color-canvas, #ffffff)',
        borderRight: '1px solid var(--color-hairline, #e5e3df)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div style={{ padding: '18px 16px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span
            style={{
              width: 26,
              height: 26,
              borderRadius: 7,
              background: 'rgba(86, 69, 212, 0.08)',
              color: 'var(--color-primary, #5645d4)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 14,
            }}
          >
            <FolderOpenOutlined />
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-ink, #1a1a1a)' }}>
            文档分类
          </span>
        </div>
        <p style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)', margin: 0, lineHeight: 1.5 }}>
          按法规、制度与标准浏览
        </p>
      </div>

      {/* Menu */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        <Menu
          mode="inline"
          selectedKeys={selectedKeys}
          items={menuItems}
          onClick={handleClick}
          disabled={loading}
          style={{ borderInlineEnd: 'none', background: 'transparent' }}
        />
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '12px 16px',
          borderTop: '1px solid var(--color-hairline, #e5e3df)',
        }}
      >
        <p
          style={{
            fontSize: 12,
            color: 'var(--color-steel, #787671)',
            margin: 0,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          共 {totalDocs} 份文档
        </p>
      </div>
    </aside>
  )
}
