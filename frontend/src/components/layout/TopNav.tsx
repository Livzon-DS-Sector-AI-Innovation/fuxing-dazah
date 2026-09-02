"use client"

import { useState, useEffect, useRef, useLayoutEffect, useMemo } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { Dropdown, Avatar } from "antd"
import { LogoutOutlined, UserOutlined, EllipsisOutlined } from "@ant-design/icons"
import { moduleMenus } from "@/lib/menu-config"
import { ModuleIcon, SearchIcon, BellIcon } from "@/components/icons"
import styles from "./TopNav.module.css"
import { logout, getCurrentUser, getImpersonationStatus } from "@/actions/auth"
import { usePermission } from "@/hooks/usePermission"
import { useSidebarStore } from "@/stores/sidebar"
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons"
import { ImpersonateBanner } from "@/components/permission/ImpersonateBanner"
import type { User, ImpersonationStatus } from "@/types/user"

// 顶栏折叠参数
const GAP = 2          // gap-0.5 → 0.125rem ≈ 2px
const MORE_W = 40      // 更多按钮固定宽度 w-10
const RESERVE = MORE_W + GAP + 2 // 更多按钮占位 + 间距 + 微调安全余量

const LOGOUT_MENU_ITEMS = [
  {
    key: "logout",
    label: "退出登录",
    icon: <LogoutOutlined />,
    danger: true,
  },
]

export function TopNav() {
  const pathname = usePathname()
  const router = useRouter()
  const activeModule = pathname.split("/")[1] || "production"
  const [loggingOut, setLoggingOut] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  const { hasPermission, isLoaded } = usePermission()
  const { collapsed, toggle: toggleSidebar } = useSidebarStore()
  const navRef = useRef<HTMLElement>(null)
  const measureItems = useRef<Map<string, HTMLElement>>(new Map())
  const moreRef = useRef<HTMLButtonElement>(null)
  const [indicator, setIndicator] = useState({ left: 0, width: 0 })
  const [folded, setFolded] = useState<string[]>([])

  const [impersonation, setImpersonation] = useState<ImpersonationStatus | null>(null)

  useEffect(() => {
    getCurrentUser().then(setUser)
    getImpersonationStatus().then(setImpersonation)
  }, [isLoaded])

  const handleLogout = async () => {
    setLoggingOut(true)
    await logout()
  }

  const avatarSrc = user?.avatar_url || undefined
  const displayName = user?.name || "API"

  const visibleMenus = useMemo(() => {
    if (!isLoaded) return moduleMenus
    return moduleMenus.filter((mod) => {
      if (!mod.permissions || mod.permissions.length === 0) return true
      return hasPermission(...mod.permissions)
    })
  }, [isLoaded, hasPermission])

  // 测量每个 tab 宽度，计算哪些模块需要折叠进「更多」
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return

    const computeFold = () => {
      const containerWidth = nav.clientWidth
      if (containerWidth <= 0) return
      const widths = visibleMenus.map((m) => measureItems.current.get(m.key)?.offsetWidth ?? 0)
      const total = widths.reduce((a, b) => a + b, 0) + GAP * Math.max(0, widths.length - 1)
      if (total <= containerWidth) {
        setFolded([])
        return
      }
      const limit = containerWidth - RESERVE
      let sum = 0
      const foldKeys: string[] = []
      let cut = false
      for (let i = 0; i < widths.length; i++) {
        const next = sum + (i > 0 ? GAP : 0) + widths[i]
        if (!cut && next <= limit) {
          sum = next
        } else {
          cut = true
          foldKeys.push(visibleMenus[i].key)
        }
      }
      setFolded(foldKeys)
    }

    computeFold()
    const ro = new ResizeObserver(computeFold)
    ro.observe(nav)
    return () => ro.disconnect()
  }, [visibleMenus, isLoaded])

  // 指示条跟随激活 tab；激活模块在「更多」里时收回到更多按钮
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    if (folded.includes(activeModule)) {
      const more = moreRef.current
      if (more) {
        setIndicator({ left: more.offsetLeft + 12, width: more.offsetWidth - 24 })
        return
      }
    }
    const link = nav.querySelector<HTMLAnchorElement>(`[data-module="${activeModule}"]`)
    if (!link) return
    setIndicator({ left: link.offsetLeft + 12, width: link.offsetWidth - 24 })
  }, [activeModule, isLoaded, folded])

  const foldedSet = useMemo(() => new Set(folded), [folded])
  const visibleTabs = visibleMenus.filter((m) => !foldedSet.has(m.key))
  const foldedTabs = visibleMenus.filter((m) => foldedSet.has(m.key))
  const activeInMore = folded.includes(activeModule)

  const moreMenuItems = useMemo(
    () =>
      foldedTabs.map((m) => ({
        key: m.key,
        label: (
          <span className="flex items-center gap-1.5">
            <ModuleIcon name={m.icon} className="w-4 h-4" />
            <span
              className={
                activeModule === m.key
                  ? "text-[var(--color-primary)] font-medium"
                  : "text-[var(--color-ink)]"
              }
            >
              {m.label}
            </span>
          </span>
        ),
      })),
    [foldedTabs, activeModule],
  )

  return (
    <>
      {impersonation?.is_impersonating && impersonation.target_user && (
        <ImpersonateBanner targetUser={impersonation.target_user} />
      )}
    <header className="h-16 bg-[var(--color-canvas)] border-b border-[var(--color-hairline)] flex items-center px-5 shrink-0">
      {/* 离屏测量容器：渲染全部可见模块用于宽度测量 */}
      <div
        aria-hidden
        className="absolute -left-[9999px] top-0 flex items-center gap-0.5 h-16 w-max pointer-events-none invisible"
      >
        {visibleMenus.map((mod) => (
          <span
            key={mod.key}
            ref={(el) => {
              if (el) measureItems.current.set(mod.key, el)
            }}
            className="flex shrink-0 items-center gap-1.5 px-3 h-full text-[14px] font-medium whitespace-nowrap"
          >
            <ModuleIcon name={mod.icon} className="w-4 h-4" />
            {mod.label}
          </span>
        ))}
      </div>

      {/* Logo */}
      <div className="flex items-center gap-2.5 mr-10 shrink-0">
        <div className="w-7 h-7 rounded-[var(--rounded-md)] bg-[var(--color-primary)] flex items-center justify-center">
          <span className="text-white text-xs font-semibold">API</span>
        </div>
        <span className="text-[var(--color-charcoal)] text-[15px] font-semibold tracking-tight">
          原料药
        </span>
      </div>

      {/* Module Tabs */}
      <nav ref={navRef} className="relative flex items-center gap-0.5 flex-1 overflow-hidden h-full">
        {visibleTabs.map((mod) => {
          const isActive = activeModule === mod.key
          return (
            <Link
              key={mod.key}
              href={mod.path}
              data-module={mod.key}
              className={`
                flex items-center gap-1.5 px-3 h-full text-[14px] font-medium transition-colors whitespace-nowrap
                ${isActive
                  ? "text-[var(--color-primary)]"
                  : "text-[var(--color-steel)] hover:text-[var(--color-primary)]"
                }
              `}
            >
              <ModuleIcon name={mod.icon} className="w-4 h-4" />
              {mod.label}
            </Link>
          )
        })}

        {/* 更多：溢出模块折叠进下拉 */}
        {foldedTabs.length > 0 && (
          <Dropdown
            menu={{
              items: moreMenuItems,
              selectedKeys: activeInMore ? [activeModule] : [],
              selectable: true,
              onClick: ({ key }) => {
                const mod = foldedTabs.find((m) => m.key === key)
                if (mod) router.push(mod.path)
              },
            }}
            placement="bottomRight"
          >
            <button
              ref={moreRef}
              className={`
                ${styles.moreBtn} flex items-center justify-center h-full w-10 shrink-0 transition-colors
                ${activeInMore ? styles.isActive : ""}
              `}
              title="更多模块"
            >
              <EllipsisOutlined style={{ fontSize: 18 }} />
            </button>
          </Dropdown>
        )}

        <span
          className="absolute bottom-0 left-0 h-[2px] bg-[var(--color-primary)] rounded-full pointer-events-none transition-[transform,width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]"
          style={{ transform: `translateX(${indicator.left}px)`, width: indicator.width }}
        />
      </nav>

      {/* Right Section */}
      <div className="flex items-center gap-1 ml-4 shrink-0">
        <button
          onClick={toggleSidebar}
          className="w-8 h-8 flex items-center justify-center rounded-[var(--rounded-sm)] text-[var(--color-steel)] hover:text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] transition-colors"
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
        <button className="w-8 h-8 flex items-center justify-center rounded-[var(--rounded-sm)] text-[var(--color-steel)] hover:text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] transition-colors">
          <SearchIcon className="w-[18px] h-[18px]" />
        </button>
        <button className="w-8 h-8 flex items-center justify-center rounded-[var(--rounded-sm)] text-[var(--color-steel)] hover:text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] transition-colors relative">
          <BellIcon className="w-[18px] h-[18px]" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--color-error)] rounded-full" />
        </button>
        <Dropdown
          menu={{
            items: LOGOUT_MENU_ITEMS,
            onClick: (info) => {
              if (info.key === "logout") handleLogout()
            },
          }}
          placement="bottomRight"
        >
          <button
            className="ml-2 flex items-center gap-2 h-8 px-2 rounded-[var(--rounded-md)] hover:bg-[var(--color-surface)] transition-colors disabled:opacity-50"
            disabled={loggingOut}
          >
            {avatarSrc ? (
              <Avatar src={avatarSrc} size={28} />
            ) : (
              <Avatar size={28} icon={<UserOutlined />} />
            )}
            <span className="text-[13px] text-[var(--color-ink)] hidden md:inline">
              {displayName}
            </span>
          </button>
        </Dropdown>
      </div>
    </header>
    </>
  )
}
