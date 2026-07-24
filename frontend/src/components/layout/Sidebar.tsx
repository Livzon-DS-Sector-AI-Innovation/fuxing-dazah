"use client"

import { usePathname, useRouter } from "next/navigation"
import { useState } from "react"
import { Menu } from "antd"
import type { MenuProps } from "antd"
import { getModuleByKey } from "@/lib/menu-config"
import type { SubMenuItem } from "@/lib/menu-config"
import { useSidebarStore } from "@/stores/sidebar"

type MenuItem = Required<MenuProps>['items'][number]

// ── 构建 key → path 映射（叶子节点 key 唯一，path 可重复）──
function buildKeyPathMap(items: SubMenuItem[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const item of items) {
    if (item.children && item.children.length > 0) {
      const childMap = buildKeyPathMap(item.children)
      childMap.forEach((v, k) => map.set(k, v))
    } else if (item.path) {
      map.set(item.key, item.path)
    }
  }
  return map
}

// ── 递归构建 Ant Design 菜单项 ──
function buildMenuItems(items: SubMenuItem[]): MenuItem[] {
  return items.map((item) => {
    if (item.children && item.children.length > 0) {
      return {
        key: item.key,
        label: item.label,
        children: buildMenuItems(item.children),
      }
    }
    const leaf: MenuItem = { key: item.key, label: item.label }
    if (item.disabled) {
      leaf.disabled = true
    }
    return leaf
  })
}

// ── 收集所有可用的叶子节点（跳过 disabled 和空 path）──
function collectLeaves(items: SubMenuItem[]): SubMenuItem[] {
  return items.flatMap((item) => {
    if (item.children && item.children.length > 0) {
      return collectLeaves(item.children)
    }
    if (item.disabled || !item.path) return []
    return [item]
  })
}

// ── 递归查找当前路径匹配的叶子节点 ──
function findSelectedKey(items: SubMenuItem[], pathname: string): string | undefined {
  const leaves = collectLeaves(items)
  const sorted = leaves.sort((a, b) => b.path.length - a.path.length)
  const match = sorted.find(
    (item) => pathname === item.path || pathname.startsWith(item.path + "/")
  )
  return match?.key
}

// ── 收集所有有子项的 key（用于默认展开所有分组）──
function collectAllSubMenuKeys(items: SubMenuItem[]): string[] {
  return items.flatMap((item) => {
    if (item.children && item.children.length > 0) {
      return [item.key, ...collectAllSubMenuKeys(item.children)]
    }
    return []
  })
}

// ── 收集选中路径的所有祖先 key（用于 auto-open）──
function collectAncestorKeys(items: SubMenuItem[], pathname: string): string[] {
  for (const item of items) {
    if (item.children && item.children.length > 0) {
      if (containsPath(item.children, pathname)) {
        return [item.key, ...collectAncestorKeys(item.children, pathname)]
      }
    }
  }
  return []
}

function containsPath(items: SubMenuItem[], pathname: string): boolean {
  for (const item of items) {
    if (item.children && item.children.length > 0) {
      if (containsPath(item.children, pathname)) return true
    } else if (!item.disabled && item.path && (pathname === item.path || pathname.startsWith(item.path + "/"))) {
      return true
    }
  }
  return false
}

// ═══════════════════════════════════════════════════════════════

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const collapsed = useSidebarStore((s) => s.collapsed)
  const moduleKey = pathname.split("/")[1] || "production"
  const currentModule = getModuleByKey(moduleKey)

  const menuItems = currentModule ? buildMenuItems(currentModule.children) : []
  const keyPathMap = currentModule ? buildKeyPathMap(currentModule.children) : new Map<string, string>()
  const selectedKey = currentModule
    ? findSelectedKey(currentModule.children, pathname)
    : undefined

  // 生产管理模块默认全展开所有子菜单
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    if (!currentModule) return []
    const ancestors = collectAncestorKeys(currentModule.children, pathname)
    return moduleKey === "production"
      ? [...new Set([...collectAllSubMenuKeys(currentModule.children), ...ancestors])]
      : ancestors
  })

  const handleOpenChange = (keys: string[]) => {
    setOpenKeys(keys)
  }

  const handleClick: MenuProps['onClick'] = ({ key }) => {
    const path = keyPathMap.get(key)
    if (path) router.push(path)
  }

  if (!currentModule) return null

  return (
    <aside
      className={`bg-[var(--color-canvas)] border-r border-[var(--color-hairline)] flex flex-col shrink-0 overflow-hidden transition-all duration-200 ${
        collapsed ? "w-0 border-r-0" : "w-56"
      }`}
    >
      <div className="flex-1 overflow-y-auto min-w-[224px]">
        <div
          className={`px-4 pt-5 pb-3${moduleKey === "safety" ? " cursor-pointer group" : ""}`}
          onClick={moduleKey === "safety" ? () => router.push(currentModule.path) : undefined}
        >
          <h2
            className={`text-[18px] font-semibold text-[var(--color-charcoal)]${
              moduleKey === "safety" ? " group-hover:text-[var(--color-primary)] transition-colors" : ""
            }`}
          >
            {currentModule.label}
          </h2>
        </div>

        <Menu
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          openKeys={openKeys}
          onOpenChange={handleOpenChange}
          items={menuItems}
          onClick={handleClick}
          className="sidebar-menu"
          style={{ borderInlineEnd: 'none' }}
        />
      </div>

      <div className="px-4 py-3 border-t border-[var(--color-hairline-soft)] min-w-[224px]">
        <p className="text-[12px] text-[var(--color-stone)]">v0.1.1</p>
      </div>
    </aside>
  )
}
