"use client"

import { useState, useEffect, useRef, useLayoutEffect } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Dropdown, Avatar } from "antd"
import { LogoutOutlined, UserOutlined } from "@ant-design/icons"
import { moduleMenus } from "@/lib/menu-config"
import { ModuleIcon, SearchIcon, BellIcon } from "@/components/icons"
import { logout, getCurrentUser, getImpersonationStatus } from "@/actions/auth"
import { usePermission } from "@/hooks/usePermission"
import { useSidebarStore } from "@/stores/sidebar"
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons"
import { ImpersonateBanner } from "@/components/permission/ImpersonateBanner"
import type { User, ImpersonationStatus } from "@/types/user"

export function TopNav() {
  const pathname = usePathname()
  const activeModule = pathname.split("/")[1] || "production"
  const [loggingOut, setLoggingOut] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  const { hasPermission, isLoaded } = usePermission()
  const { collapsed, toggle: toggleSidebar } = useSidebarStore()
  const navRef = useRef<HTMLElement>(null)
  const [indicator, setIndicator] = useState({ left: 0, width: 0 })

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

  // 指示条跟随激活 tab 滑动
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const link = nav.querySelector<HTMLAnchorElement>(`[data-module="${activeModule}"]`)
    if (!link) return
    setIndicator({ left: link.offsetLeft + 12, width: link.offsetWidth - 24 })
  }, [activeModule, isLoaded])

  const visibleMenus = isLoaded
    ? moduleMenus.filter((mod) => {
        if (!mod.permissions || mod.permissions.length === 0) return true
        return hasPermission(...mod.permissions)
      })
    : moduleMenus

  return (
    <>
      {impersonation?.is_impersonating && impersonation.target_user && (
        <ImpersonateBanner targetUser={impersonation.target_user} />
      )}
    <header className="h-16 bg-[var(--color-canvas)] border-b border-[var(--color-hairline)] flex items-center px-5 shrink-0">
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
      <nav ref={navRef} className="relative flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-hide h-full">
        {visibleMenus.map((mod) => {
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
            items: [
              {
                key: 'logout',
                label: '退出登录',
                icon: <LogoutOutlined />,
                danger: true,
              },
            ],
            onClick: (info) => {
              if (info.key === 'logout') handleLogout()
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
