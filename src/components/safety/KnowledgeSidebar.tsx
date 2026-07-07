'use client'

import { useState, useMemo } from 'react'
import { Menu } from 'antd'
import type { MenuProps } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import { KNOWLEDGE_MENU } from './knowledgeConstants'
import type { KnowledgeMenuGroup } from './knowledgeConstants'

interface KnowledgeSidebarProps {
  /** 当前选中的菜单 key，null 表示"全部文档" */
  selectedKey: string | null
  /** 菜单项点击回调 */
  onSelect: (key: string) => void
  /** menuKey → document count */
  counts: Map<string, number>
  /** 是否正在加载 */
  loading?: boolean
}

export default function KnowledgeSidebar({
  selectedKey,
  onSelect,
  counts,
  loading,
}: KnowledgeSidebarProps) {
  const [openKeys, setOpenKeys] = useState<string[]>(
    KNOWLEDGE_MENU.map((g) => g.key),
  )

  // 计算总文档数（基于 "all:" 前缀的 group 级别计数）
  const totalDocs = useMemo(() => {
    let groupTotal = 0
    for (const group of KNOWLEDGE_MENU) {
      groupTotal += counts.get('all:' + group.key) || 0
    }
    return groupTotal
  }, [counts])

  // 构建 Ant Design Menu items
  const menuItems: MenuProps['items'] = useMemo(() => {
    return KNOWLEDGE_MENU.map((group) => buildSubMenu(group, counts))
  }, [counts])

  const handleOpenChange = (keys: string[]) => {
    setOpenKeys(keys)
  }

  const handleClick: MenuProps['onClick'] = ({ key }) => {
    onSelect(key)
  }

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
      <div style={{ padding: '14px 16px 10px' }}>
        <h2
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: 'var(--color-charcoal, #1a1a1a)',
            margin: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <FileTextOutlined style={{ fontSize: 16, color: 'var(--color-primary, #5645d4)' }} />
          文档分类
        </h2>
      </div>

      {/* Menu */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 4px' }}>
        <Menu
          mode="inline"
          selectedKeys={selectedKeys}
          openKeys={openKeys}
          onOpenChange={handleOpenChange}
          items={menuItems}
          onClick={handleClick}
          disabled={loading}
          style={{ borderInlineEnd: 'none', background: 'transparent' }}
        />
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '10px 16px',
          borderTop: '1px solid var(--color-hairline, #e5e3df)',
        }}
      >
        <p
          style={{
            fontSize: 12,
            color: 'var(--color-stone, #787671)',
            margin: 0,
          }}
        >
          共 {totalDocs} 份文档
        </p>
      </div>
    </aside>
  )
}

/** 将 KnowledgeMenuGroup 转为 Ant Design SubMenu + MenuItems */
function buildSubMenu(
  group: KnowledgeMenuGroup,
  counts: Map<string, number>,
): NonNullable<MenuProps['items']>[number] {
  const allKey = 'all:' + group.key
  const groupCount = counts.get(allKey) || 0

  const children: MenuProps['items'] = group.children.map((child) => {
    const childCount = child.key === allKey
      ? groupCount
      : counts.get(child.key) || 0

    return {
      key: child.key,
      label: (
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>
            <span style={{ marginRight: 4 }}>{child.emoji}</span>
            {child.label}
          </span>
          <span style={{ fontSize: 12, color: 'var(--color-stone, #787671)', marginLeft: 8 }}>
            {childCount}
          </span>
        </span>
      ),
      disabled: child.disabled || false,
    }
  })

  return {
    key: group.key,
    type: 'submenu' as const,
    label: (
      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>
          <span style={{ marginRight: 6 }}>{group.emoji}</span>
          <span style={{ fontWeight: 600, fontSize: 13 }}>{group.label}</span>
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-stone, #787671)', marginLeft: 8, fontWeight: 400 }}>
          {groupCount}
        </span>
      </span>
    ),
    children,
  }
}
