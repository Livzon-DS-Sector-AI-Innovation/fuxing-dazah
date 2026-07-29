'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import Orb from '@/components/Orb'
import GradientText from '@/components/GradientText'
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

  const noAccess = isLoaded && visibleMenus.length === 0

  return (
    <div className="relative h-full overflow-hidden">
      {/* Orb 背景 */}
      <div className="absolute inset-0 z-0">
        <Orb hue={288} hoverIntensity={2} backgroundColor="#f6f5f4" />
      </div>

      {/* 内容层 */}
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-10 pointer-events-none">
        {noAccess ? (
          <div className="text-center">
            <GradientText
              colors={['#e03131', '#dd5b00', '#e03131']}
              className="text-[32px] font-semibold tracking-tight mb-2"
              animationSpeed={4}
            >
              小朋友，走错地方了哦
            </GradientText>
            <p className="text-[var(--color-steel)] text-[15px]">
              请联系管理员为你分配模块权限
            </p>
          </div>
        ) : (
          <>
            <div className="text-center">
              <GradientText
                colors={['#5645d4', '#ff64c8', '#7b3ff2']}
                className="text-[32px] font-semibold tracking-tight mb-2"
                animationSpeed={6}
              >
                欢迎回来{user?.name ? `，${user.name}` : ''}
              </GradientText>
              <p className="text-[var(--color-steel)] text-[15px]">
                原料药工厂管理平台 · 请选择要进入的模块
              </p>
            </div>

            {isLoaded && (
              <div className="flex flex-wrap items-center justify-center gap-3 max-w-3xl px-8 pointer-events-auto">
                {visibleMenus.map((mod) => (
                  <Link
                    key={mod.key}
                    href={mod.path}
                    className="flex items-center gap-2 px-4 h-10 rounded-full bg-white/50 backdrop-blur-md border border-white/60 !text-[#7b3ff2] text-[14px] font-medium shadow-sm transition-all hover:bg-white/70 hover:shadow-md hover:shadow-md"
                  >
                    <ModuleIcon name={mod.icon} className="w-4 h-4" />
                    {mod.label}
                  </Link>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
