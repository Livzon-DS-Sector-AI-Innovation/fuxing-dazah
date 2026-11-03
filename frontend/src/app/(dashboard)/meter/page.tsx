'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { MeterOverviewPanel } from '@/components/meter'
import { usePermissionStore } from '@/stores/permission'

// 与菜单同口径（meter:config:manage 精确码）：纯台账查询角色直接输 URL 访问 /meter
// 时落到可见的台账页，不渲染总览面板
export default function MeterPage() {
  const router = useRouter()
  const isLoaded = usePermissionStore((s) => s.isLoaded)
  const permissions = usePermissionStore((s) => s.permissions)
  const allowed = permissions.has('meter:config:manage')
  const fallback = permissions.has('meter:*:read') || permissions.has('meter:instrument:read')
    ? '/meter/instruments'
    : '/meter/gas-detectors'

  useEffect(() => {
    if (isLoaded && !allowed) router.replace(fallback)
  }, [isLoaded, allowed, fallback, router])

  if (!isLoaded || !allowed) return null
  return <MeterOverviewPanel />
}
