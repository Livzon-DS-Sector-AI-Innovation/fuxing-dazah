'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import Orb from '@/components/Orb'
import { ModuleIcon } from '@/components/icons'
import { moduleMenus } from '@/lib/menu-config'
import { usePermission } from '@/hooks/usePermission'
import { getCurrentUser } from '@/actions/auth'
import type { User } from '@/types/user'

export function WelcomeHero() {
  const { hasPermission, isLoaded } = usePermission()
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    getCurrentUser().then(setUser)
  }, [])

  // 与 TopNav 相同的模块可见性过滤逻辑
  const visibleMenus = isLoaded
    ? moduleMenus.filter((mod) => {
        if (!mod.permissions || mod.permissions.length === 0) return true
        return hasPermission(...mod.permissions)
      })
    : []

  return (
    <div className="relative h-[calc(100%+3rem)] -m-6 overflow-hidden bg-[var(--color-brand-navy-deep)]">
      {/* Orb 背景 */}
      <div className="absolute inset-0">
        <Orb hue={288} hoverIntensity={2} backgroundColor="#0a0e2a" />
      </div>

      {/* 内容层：pointer-events 穿透给 Orb，交互元素单独恢复 */}
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-10 pointer-events-none">
        <div className="text-center">
          <h1 className="text-white text-[32px] font-semibold tracking-tight mb-2">
            欢迎回来{user?.name ? `，${user.name}` : ''}
          </h1>
          <p className="text-white/60 text-[15px]">
            原料药工厂管理平台 · 请选择要进入的模块
          </p>
        </div>

        {isLoaded && (
          <div className="flex flex-wrap items-center justify-center gap-3 max-w-3xl px-8 pointer-events-auto">
            {visibleMenus.map((mod) => (
              <Link
                key={mod.key}
                href={mod.path}
                className="flex items-center gap-2 px-4 h-10 rounded-full bg-white/10 backdrop-blur-md border border-white/15 text-white/85 text-[14px] font-medium transition-colors hover:bg-white/20 hover:text-white"
              >
                <ModuleIcon name={mod.icon} className="w-4 h-4" />
                {mod.label}
              </Link>
            ))}
            {visibleMenus.length === 0 && (
              <p className="text-white/50 text-[14px]">
                暂无可访问的模块，请联系管理员分配权限
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
