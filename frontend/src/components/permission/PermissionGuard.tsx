'use client'

import { usePermission } from '@/hooks/usePermission'

interface Props {
  /** 权限编码，支持多个（任一匹配即显示） */
  permission: string | string[]
  /** 无权限时的替代内容，默认 null */
  fallback?: React.ReactNode
  children: React.ReactNode
}

export function PermissionGuard({ permission, fallback = null, children }: Props) {
  const { hasPermission } = usePermission()
  const codes = Array.isArray(permission) ? permission : [permission]
  if (!hasPermission(...codes)) return fallback
  return <>{children}</>
}
